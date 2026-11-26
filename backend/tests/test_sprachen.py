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
