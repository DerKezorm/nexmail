"""Die Ueber-Seite und die Update-Nachfrage: die alten Wege ``/api/ueber`` als Hülle über dem Modul updates 0.1.1.

Die Wege des Moduls (``/api/about``) prüfen die Vertragstests in ``tests/nexupdates``; hier stehen die alten Wege mit
ihrer Form, die Regeln für Mitglieder (U15), das Kästchen der Einrichtung (U1) und dass ohne Glocke nichts im
Hintergrund fragt (U19).

⚠️ **Der wichtigste Test hier ist ``test_ein_ausfall_bei_github_reisst_nichts_mit``.**
Die Nachfrage ist Beiwerk. Faellt sie aus, soll dort einfach nichts stehen —
eine Ueber-Seite, die mit 500 antwortet, weil GitHub gerade langsam ist, waere
ein selbstgemachter Fehler an der Stelle, an der man nachsieht, warum etwas
nicht geht.
"""

from __future__ import annotations

import httpx
import pytest

from app import __version__
from app.services import aktualisierung
from app.vendor import nexupdates
from app.vendor.nexupdates import check as pruefung
from conftest import EINRICHTUNGSCODE, anmelden, einrichten, zweiten_benutzer_anlegen


@pytest.fixture(autouse=True)
def ohne_gedaechtnis():
    aktualisierung.zuruecksetzen()
    yield
    aktualisierung.zuruecksetzen()


@pytest.fixture
def ohne_netz(monkeypatch):
    """Kein Test ruft GitHub an — sonst haengt der Lauf am fremden Dienst."""

    monkeypatch.setattr(pruefung, "ask", lambda: None)
    yield


def _antwortet_mit(monkeypatch, tag: str | None):
    monkeypatch.setattr(pruefung, "ask", lambda: tag)


# --- Versionsvergleich ---------------------------------------------------- #


@pytest.mark.parametrize(
    "neueste,jetzige,erwartet",
    [
        ("v0.2.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("v0.1.0", "0.2.0", False),
        # ⚠️ Der Fall, den ein Textvergleich falsch macht — und zwar genau
        # einmal, naemlich bei der zehnten Nebenfassung.
        ("v0.10.0", "0.9.0", True),
        ("v0.9.0", "0.10.0", False),
        ("kein-tag", "0.1.0", False),
        ("", "0.1.0", False),
    ],
)
def test_verglichen_werden_zahlen_keine_zeichenketten(neueste, jetzige, erwartet):
    assert aktualisierung.ist_neuer(neueste, jetzige) is erwartet


# --- Die Seite ------------------------------------------------------------ #


def test_die_seite_nennt_fassung_lizenz_und_herkunft(klient, ohne_netz):
    einrichten(klient)
    daten = klient.get("/api/ueber").json()

    assert daten["version"] == __version__
    assert daten["lizenz"] == "AGPL-3.0"
    assert daten["repo_adresse"].endswith("/nexmail")
    # U18: solange die Projektseiten abgeschaltet sind, keine (die Zeile fällt weg); das Feld bleibt, leer.
    assert daten["projektseite"] == ""


def test_jeder_sieht_sie_nur_der_betreiber_schaltet(klient, db, ohne_netz):
    """Lesen wie in nexnotes für jedes Konto; Schalter und „Jetzt prüfen"
    entscheiden über die ganze Installation und bleiben beim Betreiber."""
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    klient.post("/api/auth/abmelden")
    anmelden(klient, "zweiter", "auch-geheim-456", geheimnis)

    assert klient.get("/api/ueber").status_code == 200
    assert klient.put("/api/ueber/pruefen", json={"update_pruefen": False}).status_code == 403
    assert klient.post("/api/ueber/pruefen").status_code == 403


def test_ohne_anmeldung_nichts(klient, ohne_netz):
    einrichten(klient)
    klient.post("/api/auth/abmelden")
    assert klient.get("/api/ueber").status_code == 401


def test_die_nachfrage_ist_ab_werk_an(klient, ohne_netz):
    """Ohne Eintrag ist die Nachfrage an."""
    einrichten(klient)
    assert klient.get("/api/ueber").json()["update_pruefen"] is True


def test_ausschalten_wird_gemerkt(klient, ohne_netz):
    einrichten(klient)
    assert (
        klient.put("/api/ueber/pruefen", json={"update_pruefen": False}).json()["update_pruefen"]
        is False
    )
    assert klient.get("/api/ueber").json()["update_pruefen"] is False


def test_ausgeschaltet_geht_nichts_hinaus(klient, monkeypatch):
    """⚠️ Der Grund fuer den Schalter — nicht nur ein leeres Feld in der Anzeige."""
    gerufen: list[int] = []

    def zaehlen():
        gerufen.append(1)
        return "v9.9.9"

    monkeypatch.setattr(pruefung, "ask", zaehlen)

    einrichten(klient)
    klient.put("/api/ueber/pruefen", json={"update_pruefen": False})
    gerufen.clear()

    daten = klient.get("/api/ueber").json()
    assert gerufen == [], "Trotz ausgeschalteter Nachfrage ging eine Anfrage hinaus."
    assert daten["geprueft"] is False
    assert daten["neueste"] is None


def test_von_hand_geht_auch_ausgeschaltet(klient, monkeypatch):
    """Ausgeschaltet heisst „nicht **von selbst**". Ein Klick ist eine Entscheidung."""
    _antwortet_mit(monkeypatch, "v9.9.9")

    einrichten(klient)
    klient.put("/api/ueber/pruefen", json={"update_pruefen": False})

    daten = klient.post("/api/ueber/pruefen").json()
    assert daten["neueste"] == "v9.9.9"
    assert daten["neuer_da"] is True
    # Und der Schalter bleibt trotzdem aus.
    assert daten["update_pruefen"] is False


def test_eine_neuere_fassung_wird_gemeldet(klient, monkeypatch):
    _antwortet_mit(monkeypatch, "v99.0.0")
    einrichten(klient)

    daten = klient.get("/api/ueber").json()
    assert daten["neueste"] == "v99.0.0"
    assert daten["neuer_da"] is True
    assert daten["geprueft_am"] is not None


def test_dieselbe_fassung_meldet_nichts(klient, monkeypatch):
    _antwortet_mit(monkeypatch, f"v{__version__}")
    einrichten(klient)

    daten = klient.get("/api/ueber").json()
    assert daten["neuer_da"] is False
    assert daten["geprueft"] is True


def test_ein_ausfall_bei_github_reisst_nichts_mit(klient, monkeypatch):
    """⚠️ **Der Kern.** Auch ``httpx.InvalidURL`` — in Nexview lief genau die
    an einem ``httpx.HTTPError`` vorbei und riss eine ganze Seite mit."""

    einrichten(klient)

    for fehler in (
        httpx.ConnectTimeout("zu langsam"),
        httpx.InvalidURL("kaputte Adresse"),
        ValueError("etwas ganz anderes"),
    ):

        class Attrappe:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def stream(self, *a, **k):
                raise fehler

        monkeypatch.setattr(httpx, "Client", Attrappe)
        aktualisierung.zuruecksetzen()

        antwort = klient.get("/api/ueber")
        assert antwort.status_code == 200, f"{fehler!r} hat die Seite mitgerissen."
        assert antwort.json()["neueste"] is None
        assert antwort.json()["version"] == __version__


def test_hoechstens_einmal_am_tag(klient, monkeypatch):
    """GitHub erlaubt ohne Anmeldung 60 Anfragen je Stunde und Adresse."""
    gerufen: list[int] = []

    def zaehlen():
        gerufen.append(1)
        return "v0.1.0"

    monkeypatch.setattr(pruefung, "ask", zaehlen)

    einrichten(klient)
    for _ in range(4):
        klient.get("/api/ueber")

    assert len(gerufen) == 1, f"Es gingen {len(gerufen)} Anfragen hinaus statt einer."


# --- Seit dem Modul updates 0.1.1 ------------------------------------------ #


def _zaehler(monkeypatch, tag: str = "v99.0.0") -> list[int]:
    gerufen: list[int] = []

    def zaehlen():
        gerufen.append(1)
        return tag

    monkeypatch.setattr(pruefung, "ask", zaehlen)
    return gerufen


def test_ein_mitglied_erfaehrt_nichts_und_fragt_nie(klient, db, monkeypatch):
    """U2, U15: Fassung, Lizenz und Quelltext wie bisher; der Stand und der Schalter leer in ihren alten Typen, und
    sein Aufruf geht nie hinaus, auch wenn der Schalter an ist."""
    gerufen = _zaehler(monkeypatch)
    einrichten(klient)
    assert klient.get("/api/ueber").json()["neueste"] == "v99.0.0"
    _, geheimnis = zweiten_benutzer_anlegen(db)
    klient.post("/api/auth/abmelden")
    anmelden(klient, "zweiter", "auch-geheim-456", geheimnis)
    gerufen.clear()
    nexupdates.forget()

    daten = klient.get("/api/ueber").json()
    assert daten["version"] == __version__ and daten["repo_adresse"].endswith("/nexmail")
    assert (daten["update_pruefen"], daten["geprueft"], daten["neueste"], daten["neuer_da"], daten["geprueft_am"]) == (
        False,
        False,
        None,
        False,
        None,
    )
    assert "99.0.0" not in klient.get("/api/ueber").text
    assert gerufen == []


def test_der_hintergrund_fragt_nur_fuer_ein_geraet_das_es_will_hoechstens_einmal_am_tag(klient, monkeypatch):
    """U19, U24 (updates 0.1.3, geraete G56): nexmail hat keine Glocke (``on_newer`` fehlt), aber gekoppelte Geräte.
    Der Hintergrund fragt nur, solange „Einmal am Tag nachsehen“ an ist **und** ein Gerät eines Betreibers „Neue
    Version“ will (``devices_want``), höchstens einmal am Tag; die neue Version geht einmal an diese Geräte
    (``on_devices``)."""
    from app.services import geraete_store

    gemeldet: list[str] = []
    will = [False]
    monkeypatch.setattr(geraete_store, "neue_version", gemeldet.append)
    monkeypatch.setattr(geraete_store, "update_gewollt", lambda: will[0])
    gerufen = _zaehler(monkeypatch)
    einrichten(klient)
    konfiguration = nexupdates.current()
    assert konfiguration.on_newer is None, "keine Glocke"
    assert konfiguration.devices_want is not None and konfiguration.on_devices is not None
    klient.put("/api/ueber/pruefen", json={"update_pruefen": True})
    gerufen.clear()
    nexupdates.forget()
    for _ in range(2):
        nexupdates.look_once()
    assert gerufen == [] and gemeldet == [], "kein Gerät will es: der Hintergrund fragt nie (U19)"
    will[0] = True
    klient.put("/api/ueber/pruefen", json={"update_pruefen": False})
    gerufen.clear()
    nexupdates.forget()
    assert nexupdates.look_once() is None
    assert gerufen == [], "Aus heißt: nie nach außen"
    klient.put("/api/ueber/pruefen", json={"update_pruefen": True})
    gerufen.clear()
    nexupdates.forget()
    for _ in range(3):
        nexupdates.look_once()
    assert len(gerufen) == 1, "höchstens einmal am Tag"
    assert gemeldet == ["99.0.0"], "einmal je Version an die Geräte, ohne das v des Tags"


def test_alte_und_neue_wege_teilen_den_schalter(klient, db, monkeypatch):
    """Der Schalter liegt, wo er immer lag (``update_pruefen``, ``"0"``/``"1"``); beide Wege lesen und schreiben ihn."""
    from app.db import einstellung_lesen

    _antwortet_mit(monkeypatch, None)
    einrichten(klient)
    assert einstellung_lesen(db, "update_pruefen") == ""
    klient.put("/api/about/updates", json={"update_check": False})
    db.expire_all()
    assert einstellung_lesen(db, "update_pruefen") == "0"
    assert klient.get("/api/ueber").json()["update_pruefen"] is False
    klient.put("/api/ueber/pruefen", json={"update_pruefen": True})
    db.expire_all()
    assert einstellung_lesen(db, "update_pruefen") == "1"
    assert klient.get("/api/about/updates").json()["update_check"] is True


@pytest.mark.parametrize("an", [True, False])
def test_die_einrichtung_fragt_einmal(klient, db, monkeypatch, an):
    """U1: das Kästchen „Nach neuen Versionen sehen“ der Einrichtung wird gespeichert."""
    from app.db import einstellung_lesen

    _antwortet_mit(monkeypatch, None)
    antwort = klient.post(
        "/api/setup/konto",
        json={
            "benutzername": "betreiber",
            "passwort": "sehr-geheim-123",
            "anzeigename": "Betreiber",
            "einrichtungscode": EINRICHTUNGSCODE,
            "update_check": an,
        },
    )
    assert antwort.status_code == 201, antwort.text
    assert einstellung_lesen(db, "update_pruefen") == ("1" if an else "0")
    assert klient.get("/api/ueber").json()["update_pruefen"] is an


def test_eine_einrichtung_ohne_kaestchen_laesst_den_schalter_ungespeichert(klient, db, ohne_netz):
    """Ein Skript von vorher schickt das Feld nicht: nichts gespeichert, also an wie bisher."""
    from app.db import einstellung_lesen

    einrichten(klient)
    assert einstellung_lesen(db, "update_pruefen") == ""
    assert klient.get("/api/ueber").json()["update_pruefen"] is True


def test_ein_fehlschlag_behaelt_den_letzten_guten_stand(klient, monkeypatch):
    """Vorher überschrieb ein Fehlschlag den guten Stand für 24 Stunden mit „nichts“."""
    _antwortet_mit(monkeypatch, "v99.0.0")
    einrichten(klient)
    assert klient.post("/api/ueber/pruefen").json()["neueste"] == "v99.0.0"
    _antwortet_mit(monkeypatch, None)
    daten = klient.post("/api/ueber/pruefen").json()
    assert (daten["neueste"], daten["neuer_da"]) == ("v99.0.0", True)


def test_nur_ein_tag_der_festen_form_wird_gezeigt(klient, monkeypatch):
    """Vorher stand jeder Tag ungeprüft in der Anzeige."""
    einrichten(klient)
    for tag in ("<script>", "v1.2.3-rc1", "latest"):
        monkeypatch.setattr(pruefung, "ask", lambda tag=tag: tag)
        daten = klient.post("/api/ueber/pruefen").json()
        assert (daten["neueste"], daten["neuer_da"]) == (None, False), tag
