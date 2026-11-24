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
