"""Allgemein › Sprachen (Bauplan „Einstellungen“, E48; wie nexnotes): eigene Sprachdateien des Betreibers."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import sprachen
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen


@pytest.fixture(autouse=True)
def frisch():
    import shutil

    shutil.rmtree(sprachen.locales_dir(), ignore_errors=True)
    sprachen.forget()
    yield
    shutil.rmtree(sprachen.locales_dir(), ignore_errors=True)
    sprachen.forget()


def _hoch(klient, code: str, inhalt: bytes):
    return klient.put(f"/api/locales/{code}", content=inhalt, headers={"content-type": "application/json"})


def test_der_betreiber_laedt_eine_sprache_hoch_und_jeder_liest_sie(klient):
    einrichten(klient)
    datei = json.dumps({"_meta": {"name": "Nederlands"}, "aktion": {"schliessen": "Sluiten"}, "nav": {"post": "Post"}})
    antwort = _hoch(klient, "nl", datei.encode())
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"code": "nl", "name": "Nederlands", "keys": 2}
    fremd = TestClient(app)
    assert fremd.get("/api/locales").json() == [{"code": "nl", "name": "Nederlands", "keys": 2}]
    assert fremd.get("/api/locales/nl").json() == {"aktion": {"schliessen": "Sluiten"}, "nav": {"post": "Post"}}


def test_ein_mitglied_laedt_nichts_hoch_und_entfernt_nichts(klient, zweiter_klient, db):
    einrichten(klient)
    assert _hoch(klient, "nl", b'{"a": "b"}').status_code == 200
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    assert _hoch(zweiter_klient, "fr", b'{"a": "b"}').status_code == 403
    assert zweiter_klient.delete("/api/locales/nl").status_code == 403
    assert [e["code"] for e in klient.get("/api/locales").json()] == ["nl"]


@pytest.mark.parametrize(
    ("code", "inhalt", "kennung"),
    [
        ("nl", b"kein json", "sprachdatei_unbrauchbar"),
        ("nl", b'{"a": 1}', "sprachdatei_unbrauchbar"),
        ("nl", b"{}", "sprachdatei_unbrauchbar"),
        ("NL", b'{"a": "b"}', "sprachdatei_unbrauchbar"),
        ("nl..x", b'{"a": "b"}', "sprachdatei_unbrauchbar"),
    ],
)
def test_unbrauchbare_dateien_und_codes_werden_abgewiesen(klient, code, inhalt, kennung):
    einrichten(klient)
    antwort = _hoch(klient, code, inhalt)
    assert antwort.status_code == 422
    assert antwort.json()["detail"] == kennung
    assert klient.get("/api/locales").json() == []


def test_zu_grosse_datei_nennt_die_grenze(klient):
    einrichten(klient)
    antwort = _hoch(klient, "nl", b'{"a": "' + b"x" * (sprachen.MAX_BYTES + 10) + b'"}')
    assert antwort.status_code == 413
    assert antwort.json() == {"detail": "sprachdatei_zu_gross", "werte": {"max_kb": 512}}


def test_entfernen_und_ein_unbekannter_code(klient):
    einrichten(klient)
    assert _hoch(klient, "nl", b'{"a": "b"}').status_code == 200
    assert klient.delete("/api/locales/nl").status_code == 204
    assert klient.get("/api/locales").json() == []
    assert klient.delete("/api/locales/nl").status_code == 404
    assert TestClient(app).get("/api/locales/nl").status_code == 404
    assert TestClient(app).get("/api/locales/..%2Fsecret").status_code == 404


# --- Absichern (Nacharbeit 26.11.2026): nur gültiges JSON mit Texten, Grenze 512 KB, ein Sprachcode, nichts Internes - #


@pytest.mark.parametrize(
    "inhalt",
    [
        b'{"a": null}',
        b'{"a": ["eins", "zwei"]}',
        b'{"a": true}',
        b'["kein", "objekt"]',
        b'"nur ein text"',
        b'{"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "zu tief"}}}}}}}}}',
        b'{"": "leerer schluessel"}',
        b'\xff\xfe nicht utf-8',
    ],
)
def test_nur_texte_und_gruppen_von_texten(klient, inhalt):
    einrichten(klient)
    antwort = _hoch(klient, "nl", inhalt)
    assert antwort.status_code == 422
    assert antwort.json() == {"detail": "sprachdatei_unbrauchbar"}
    assert not (sprachen.locales_dir() / "nl.json").exists()


@pytest.mark.parametrize("code", ["nl.json", "nl-", "nl-ABCDE", "n", "nlnl", "nl_NL", "nl%20x", "..", "nl-..", "Nl"])
def test_nur_ein_sprachcode_wird_zum_dateinamen(klient, code):
    einrichten(klient)
    antwort = _hoch(klient, code, b'{"a": "b"}')
    assert antwort.status_code in (404, 405, 422)
    ordner = sprachen.locales_dir()
    assert not ordner.exists() or list(ordner.iterdir()) == []


@pytest.mark.parametrize("code", ["nl", "pt-BR", "zh-Hant", "fil"])
def test_gueltige_codes_gehen(klient, code):
    einrichten(klient)
    assert _hoch(klient, code, b'{"a": "b"}').status_code == 200
    assert (sprachen.locales_dir() / f"{code}.json").is_file()


def test_lesen_ohne_anmeldung_gibt_nur_die_texte(klient):
    einrichten(klient)
    assert _hoch(klient, "nl", json.dumps({"_meta": {"name": "Nederlands"}, "a": {"b": "c"}}).encode()).status_code == 200
    fremd = TestClient(app)
    liste = fremd.get("/api/locales").json()
    assert [set(e) for e in liste] == [{"code", "name", "keys"}]
    assert fremd.get("/api/locales/nl").json() == {"a": {"b": "c"}}


def test_eine_kaputte_datei_im_ordner_verraet_nichts(klient):
    """Von Hand in den Ordner gelegt und kaputt: die Liste übergeht sie, Lesen sagt nur die Kennung, kein Pfad, kein
    Dateiname, keine Meldung des Parsers."""
    einrichten(klient)
    ordner = sprachen.locales_dir()
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "nl.json").write_text('{"a": 1, "geheim": "x"', encoding="utf-8")
    fremd = TestClient(app)
    assert fremd.get("/api/locales").json() == []
    antwort = fremd.get("/api/locales/nl")
    assert antwort.status_code == 422
    assert antwort.json() == {"detail": "sprachdatei_unbrauchbar"}
    assert str(ordner) not in antwort.text and "json" not in antwort.text.lower()


def test_ein_verweis_aus_dem_ordner_hinaus_wird_nicht_gelesen(klient, tmp_path):
    einrichten(klient)
    draussen = tmp_path / "geheim.json"
    draussen.write_text('{"geheim": "nicht für fremde"}', encoding="utf-8")
    ordner = sprachen.locales_dir()
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "nl.json").symlink_to(draussen)
    fremd = TestClient(app)
    assert fremd.get("/api/locales").json() == []
    antwort = fremd.get("/api/locales/nl")
    assert antwort.status_code in (404, 422)
    assert "nicht für fremde" not in antwort.text
    # Hochladen über einen Verweis schreibt nicht hinaus.
    assert _hoch(klient, "nl", b'{"a": "b"}').status_code == 422
    assert json.loads(draussen.read_text(encoding="utf-8")) == {"geheim": "nicht für fremde"}
