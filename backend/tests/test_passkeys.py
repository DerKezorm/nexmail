"""Passkeys in nexmail (Kontenmodul Teil 2): hinzufuegen mit dem Passwort, anmelden ohne Passwort und ohne Code,
entfernen, der Schalter des Betreibers, und nur mit einer https-Adresse."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, einstellung_schreiben
from app.main import app
from app.services import anmeldebremse
from app.vendor.nexkonten import passkeys
from conftest import einrichten, zwei_faktor_an

sys.path.insert(0, str(Path(__file__).resolve().parent / "nexkonten"))
from webauthn_device import Device  # noqa: E402

PASSWORT = "sehr-geheim-123"
ADRESSE = "https://mail.example"


@pytest.fixture(autouse=True)
def frisch():
    anmeldebremse.zuruecksetzen()
    passkeys.forget()
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", ADRESSE)
    yield
    passkeys.forget()


def _hinzufuegen(klient: TestClient, geraet: Device, passwort: str = PASSWORT):
    start = klient.post("/api/auth/passkeys/start", json={"passwort": passwort})
    if start.status_code != 200:
        return start
    return klient.post("/api/auth/passkeys", json={"credential": geraet.create(start.json()), "name": "Laptop"})


def _anmelden(klient: TestClient, geraet: Device):
    start = klient.post("/api/auth/passkey/start")
    assert start.status_code == 200, start.text
    return klient.post("/api/auth/passkey", json={"credential": geraet.get(start.json())})


def test_mit_passkey_anmelden_ohne_passwort_und_ohne_code(klient):
    einrichten(klient)
    zwei_faktor_an(klient)
    geraet = Device(ADRESSE, "mail.example")
    neu = _hinzufuegen(klient, geraet)
    assert neu.status_code == 201, neu.text
    liste = klient.get("/api/auth/passkeys").json()
    assert liste["erlaubt"] is True and [p["name"] for p in liste["passkeys"]] == ["Laptop"]

    browser = TestClient(app)
    assert browser.get("/api/auth/passkey").json()["an"] is True
    antwort = _anmelden(browser, geraet)
    assert antwort.status_code == 200 and antwort.json()["schritt"] == "fertig", antwort.text
    assert browser.get("/api/auth/ich").json()["benutzername"] == "betreiber"


def test_hinzufuegen_nur_mit_dem_passwort(klient):
    einrichten(klient)
    antwort = _hinzufuegen(klient, Device(ADRESSE, "mail.example"), passwort="falsch-falsch")
    assert antwort.status_code == 401, antwort.text
    assert klient.get("/api/auth/passkeys").json()["passkeys"] == []


def test_entfernen_und_ein_fremder_passkey_meldet_nicht_an(klient):
    einrichten(klient)
    geraet = Device(ADRESSE, "mail.example")
    assert _hinzufuegen(klient, geraet).status_code == 201
    uid = klient.get("/api/auth/passkeys").json()["passkeys"][0]["uid"]
    weg = klient.post(f"/api/auth/passkeys/{uid}/entfernen", json={"passwort": PASSWORT})
    assert weg.status_code == 204, weg.text
    assert _anmelden(TestClient(app), geraet).status_code == 401
    assert _anmelden(TestClient(app), Device(ADRESSE, "mail.example")).status_code == 401


def test_der_betreiber_schaltet_passkeys_ab(klient):
    einrichten(klient)
    geraet = Device(ADRESSE, "mail.example")
    assert _hinzufuegen(klient, geraet).status_code == 201
    aus = klient.put("/api/oidc/admin/anmeldung", json={"passkeys_erlaubt": False})
    assert aus.status_code == 200 and aus.json()["passkeys_erlaubt"] is False
    browser = TestClient(app)
    assert browser.get("/api/auth/passkey").json()["an"] is False
    assert browser.post("/api/auth/passkey/start").status_code == 409


def test_ohne_https_adresse_keine_passkeys(klient):
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "http://mail.example")
    assert TestClient(app).get("/api/auth/passkey").json()["an"] is False
    liste = klient.get("/api/auth/passkeys").json()
    assert liste["erlaubt"] is False and liste["grund"] == "passkeys_off"
    # E39, wie nexnotes: der Kasten steht trotzdem, weil der Betreiber Passkeys erlaubt; nur das Anlegen scheitert.
    assert liste["eingeschaltet"] is True
    # konten 1.1.0 (E49): ohne https-Adresse bietet der Kasten keinen Knopf, er sagt, was fehlt.
    assert liste["passkeys_can_add"] is False
    with SessionLocal() as db:
        einstellung_schreiben(db, "passkeys_erlaubt", "0")
    assert klient.get("/api/auth/passkeys").json()["eingeschaltet"] is False


def test_auf_localhost_gehoert_der_passkey_zur_seite_selbst(klient):
    """Browser erlauben WebAuthn auf localhost ohne https; die Seite laeuft dort oft unter einem anderen Port als die
    eingetragene Adresse. Der Passkey gehoert dann zu ``localhost``, nirgends sonst."""
    einrichten(klient)
    lokal = TestClient(app, base_url="http://localhost:8399", headers={"origin": "http://localhost:5173"})
    assert lokal.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT}).status_code == 200
    geraet = Device("http://localhost:5173", "localhost")
    assert lokal.get("/api/auth/passkeys").json()["erlaubt"] is True
    assert lokal.get("/api/auth/passkeys").json()["passkeys_can_add"] is True
    assert _hinzufuegen(lokal, geraet).status_code == 201
    browser = TestClient(app, base_url="http://localhost:8399", headers={"origin": "http://localhost:5173"})
    assert browser.get("/api/auth/passkey").json()["an"] is True
    assert _anmelden(browser, geraet).status_code == 200
    # Derselbe Passkey taugt unter der echten Adresse nicht.
    assert _anmelden(TestClient(app), geraet).status_code == 401


def test_ein_passkey_ist_der_zweite_schritt_wenn_der_betreiber_ihn_verlangt(klient):
    """Entscheidung 25.11.2026: Ein Passkey zaehlt als zweiter Faktor. Mit „fuer alle verlangen“ folgt er dem
    Passwort; eine Authenticator-App muss nicht dazu. Ohne den Schalter genuegt das Passwort wie bisher."""
    einrichten(klient)
    geraet = Device(ADRESSE, "mail.example")
    assert _hinzufuegen(klient, geraet).status_code == 201
    daten = {"benutzername": "betreiber", "passwort": PASSWORT}
    assert TestClient(app).post("/api/auth/anmelden", json=daten).json()["schritt"] == "fertig"

    assert klient.put("/api/oidc/admin/anmeldung", json={"zwei_faktor_fuer_alle": True}).status_code == 200
    browser = TestClient(app)
    erst = browser.post("/api/auth/anmelden", json=daten)
    assert erst.json()["schritt"] == "passkey", erst.text
    assert browser.get("/api/auth/ich").status_code == 401
    assert _anmelden(browser, geraet).status_code == 200
    assert browser.get("/api/auth/ich").json()["benutzername"] == "betreiber"


def test_passkey_hinzufuegen_zaehlt_eine_gesetzte_adresse_allein(klient):
    """konten c0b07ab: Ist eine öffentliche Adresse gesetzt, entscheidet nur sie (und nur mit https); ohne Adresse geht
    es nur auf localhost. Eine http-Adresse wird auch auf localhost nicht zum Knopf."""
    einrichten(klient)
    lokal = TestClient(app, base_url="http://localhost:8399", headers={"origin": "http://localhost:5173"})
    assert lokal.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT}).status_code == 200
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "http://mail.example.com")
    assert lokal.get("/api/auth/passkeys").json()["passkeys_can_add"] is False
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
    assert lokal.get("/api/auth/passkeys").json()["passkeys_can_add"] is True
    assert klient.get("/api/auth/passkeys").json()["passkeys_can_add"] is True
