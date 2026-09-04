"""Kennwort vergessen — die zweite Tür neben der Anmeldung.

⚠️ **Wer sie schlecht baut, hebt die Anmeldung auf.** Ein Rücksetz-Link, der zu
lange gilt, zu leicht zu raten ist oder verrät, welche Namen es gibt, ist ein
Generalschlüssel mit Verzögerung. Die Tests hier halten genau das fest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import einstellung_schreiben
from app.models import Benutzer, Kennwortruecksetzung, Sitzung
from app.routers.einstellungen import SCHLUESSEL_OEFFENTLICHE_ADRESSE
from app.services import anmeldebremse
from app.services import benutzer as benutzerdienst
from app.services import ruecksetzung as dienst
from app.services import systempost
from conftest import einrichten

KENNWORT = "sehr-geheim-123"


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def welt(klient, db, monkeypatch):
    einrichten(klient)
    person = db.query(Benutzer).one()
    person.kontaktadresse = "wer@example.org"
    einstellung_schreiben(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE, "https://mail.example.com")
    db.commit()

    post: list[dict] = []

    def merken(db_, an, betreff, text, html=""):
        post.append({"an": an, "betreff": betreff, "text": text, "html": html})

    monkeypatch.setattr(systempost, "senden", merken)
    return person, post


def _schluessel_aus(text: str) -> str:
    marke = "/kennwort/"
    i = text.index(marke) + len(marke)
    return text[i:].split()[0]


# --- Anfordern ---------------------------------------------------------- #


def test_der_link_geht_an_die_kontaktadresse(klient, db, welt):
    person, post = welt

    antwort = klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    assert antwort.status_code == 202, antwort.text

    assert len(post) == 1
    assert post[0]["an"] == "wer@example.org"
    # ⚠️ Der Link steht auch im Textteil — wer nur Text liest, braucht ihn.
    assert "/kennwort/" in post[0]["text"]
    assert db.query(Kennwortruecksetzung).count() == 1


def test_ein_unbekannter_name_sieht_genauso_aus(klient, db, welt):
    """⚠️ **Sonst wird das Formular zur Namensliste.** Status, Körper und die
    Tatsache, dass nichts hinausging, müssen von außen ununterscheidbar sein."""
    person, post = welt

    gut = klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    anmeldebremse.zuruecksetzen()
    schlecht = klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "gibtesnicht"})

    assert gut.status_code == schlecht.status_code == 202
    assert gut.text == schlecht.text
    # Verschickt wurde trotzdem nur eine.
    assert len(post) == 1


def test_ohne_kontaktadresse_geht_nichts_hinaus(klient, db, welt):
    """⚠️ Und es sieht nach außen genauso aus wie ein Erfolg."""
    person, post = welt
    person.kontaktadresse = ""
    db.commit()

    antwort = klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})

    assert antwort.status_code == 202
    assert post == []
    assert db.query(Kennwortruecksetzung).count() == 0


def test_ein_zweiter_link_macht_den_ersten_ungueltig(klient, db, welt):
    """⚠️ Sonst liegen zwei Schlüssel für dasselbe Konto herum, und der ältere
    in einem Postfach, aus dem der Mensch gerade ausgesperrt ist."""
    person, post = welt

    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    erster = _schluessel_aus(post[0]["text"])
    anmeldebremse.zuruecksetzen()
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})

    assert db.query(Kennwortruecksetzung).count() == 1
    assert dienst.finden(db, erster) is None


def test_ein_kaputter_postausgang_verraet_nichts(klient, db, welt, monkeypatch):
    """⚠️ Sonst sagt die Fehlermeldung, dass es den Namen gibt."""
    person, post = welt

    def streikt(*a, **k):
        raise systempost.PostFehler("postausgang_nicht_erreichbar", server="x", port=1)

    monkeypatch.setattr(systempost, "senden", streikt)

    antwort = klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    assert antwort.status_code == 202


# --- Einlösen ----------------------------------------------------------- #


def test_der_link_setzt_das_kennwort(klient, db, welt):
    person, post = welt
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    schluessel = _schluessel_aus(post[0]["text"])

    antwort = klient.post(
        "/api/auth/kennwort-neu", json={"schluessel": schluessel, "passwort": "ganz-neu-4711"}
    )
    assert antwort.status_code == 204, antwort.text

    db.refresh(person)
    assert benutzerdienst.passwort_stimmt(person, "ganz-neu-4711")
    assert not benutzerdienst.passwort_stimmt(person, KENNWORT)


def test_alle_sitzungen_fliegen_raus(klient, db, welt):
    """⚠️ Wer zurücksetzt, tut es oft, weil jemand anders hineingekommen ist.
    Bliebe dessen Sitzung stehen, hätte das Zurücksetzen nichts geändert."""
    person, post = welt
    assert db.query(Sitzung).count() >= 1

    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    klient.post(
        "/api/auth/kennwort-neu",
        json={"schluessel": _schluessel_aus(post[0]["text"]), "passwort": "ganz-neu-4711"},
    )

    assert db.query(Sitzung).count() == 0


def test_ein_verbrauchter_link_geht_nicht_zweimal(klient, db, welt):
    person, post = welt
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    schluessel = _schluessel_aus(post[0]["text"])

    klient.post(
        "/api/auth/kennwort-neu", json={"schluessel": schluessel, "passwort": "ganz-neu-4711"}
    )
    zweite = klient.post(
        "/api/auth/kennwort-neu", json={"schluessel": schluessel, "passwort": "noch-neuer-4712"}
    )

    assert zweite.status_code == 400
    assert zweite.json()["detail"] == "ruecksetzung_ungueltig"


def test_ein_abgelaufener_link_geht_nicht(klient, db, welt):
    person, post = welt
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    schluessel = _schluessel_aus(post[0]["text"])

    zeile = db.query(Kennwortruecksetzung).one()
    zeile.laeuft_ab = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    antwort = klient.post(
        "/api/auth/kennwort-neu", json={"schluessel": schluessel, "passwort": "ganz-neu-4711"}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "ruecksetzung_ungueltig"


def test_erfunden_und_abgelaufen_sehen_gleich_aus(klient, db, welt):
    """⚠️ Ein Unterschied wäre nur für jemanden nützlich, der Schlüssel
    durchprobiert."""
    person, post = welt
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    zeile = db.query(Kennwortruecksetzung).one()
    zeile.laeuft_ab = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    alt = klient.post(
        "/api/auth/kennwort-neu",
        json={"schluessel": _schluessel_aus(post[0]["text"]), "passwort": "ganz-neu-4711"},
    )
    anmeldebremse.zuruecksetzen()
    erfunden = klient.post(
        "/api/auth/kennwort-neu", json={"schluessel": "gibtesnicht", "passwort": "ganz-neu-4711"}
    )

    assert alt.status_code == erfunden.status_code
    assert alt.json() == erfunden.json()


def test_ein_zu_kurzes_kennwort_wird_benannt(klient, db, welt):
    person, post = welt
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})

    antwort = klient.post(
        "/api/auth/kennwort-neu",
        json={"schluessel": _schluessel_aus(post[0]["text"]), "passwort": "kurz"},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] != "ruecksetzung_ungueltig"
    # ⚠️ Und der Link bleibt gültig — sonst kostet ein Tippfehler den Weg.
    assert db.query(Kennwortruecksetzung).one().eingeloest is None


def test_der_schluessel_steht_nur_als_hash_da(klient, db, welt):
    """⚠️ Er öffnet ein Konto, ist also ein Passwort."""
    person, post = welt
    klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"})
    schluessel = _schluessel_aus(post[0]["text"])

    zeile = db.query(Kennwortruecksetzung).one()
    assert schluessel not in zeile.schluessel_hash
    assert len(zeile.schluessel_hash) == 64


def test_die_bremse_zaehlt_mit(klient, db, welt):
    """⚠️ Ohne sie schickt eine Maschine tausend Mails los, und der Postausgang
    landet auf einer Sperrliste."""
    person, post = welt
    codes = [
        klient.post(
            "/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in codes
