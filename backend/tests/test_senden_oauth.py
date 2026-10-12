"""Senden mit Zustimmung, und zwischen Passwort und Zustimmung umstellen.

⚠️ **Issue #8.** Bis 0.23.2 meldete sich der Versand immer mit dem
gespeicherten Passwort an, auch bei einem Google- oder Microsoft-Postfach.
Kein solches Postfach hat je eine Mail verschickt, und kein Test sah es:
Geprüft war nur die SASL-Zeichenkette, nie der Weg dorthin.

Deshalb läuft hier das echte ``_smtp_senden`` gegen eine Leitung, die jeden
Befehl mitschreibt. Ein Doppelgänger für ``_smtp_senden`` selbst hätte
denselben Fehler wieder verdeckt.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import Benutzer, Konto, OauthZugang
from app.services import konten as kontendienst
from app.services import mailoauth, senden
from conftest import zweiten_benutzer_anlegen
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture
from test_mailoauth import anbieter  # noqa: F401 - Fixture
from test_verfassen import _entwurf


class Leitung:
    """Eine SMTP-Verbindung, die mitschreibt und nichts verschickt."""

    alle: list["Leitung"] = []

    def __init__(self, host, port, timeout=None):  # noqa: ARG002
        self.befehle: list[tuple] = []
        Leitung.alle.append(self)

    def starttls(self, context=None):  # noqa: ARG002
        self.befehle.append(("STARTTLS",))

    def login(self, benutzer, passwort):
        self.befehle.append(("LOGIN", benutzer, passwort))

    def docmd(self, befehl, argument=""):
        self.befehle.append(("DOCMD", befehl, argument))
        return (235, b"2.7.0 Accepted") if befehl == "AUTH" else (250, b"OK")

    def sendmail(self, von, an, roh):  # noqa: ARG002
        self.befehle.append(("SENDMAIL", von, tuple(an)))

    def quit(self):
        pass


@pytest.fixture
def leitung(db, konto, monkeypatch):  # noqa: F811
    Leitung.alle = []
    monkeypatch.setattr(senden.smtplib, "SMTP", Leitung)
    monkeypatch.setattr(senden.smtplib, "SMTP_SSL", Leitung)
    server = FalscherServer()
    server.anlegen("INBOX")
    monkeypatch.setattr(senden.imapdienst, "verbinden", lambda *a, **k: server)
    return Leitung


@pytest.fixture
def zugang(db, konto, anbieter):  # noqa: F811
    person = db.query(Benutzer).one()
    mailoauth.anbieter_setzen(db, "google", "kennung.apps.googleusercontent.com", "geheim")
    return mailoauth.einloesen(db, person, "google", "code-1", "https://mail.example.com/z")


def _anmeldung(leitung_: type[Leitung]) -> list[tuple]:
    """Was die eine Verbindung zur Anmeldung gesagt hat."""
    assert len(leitung_.alle) == 1
    return [b for b in leitung_.alle[0].befehle if b[0] in ("LOGIN", "DOCMD")]


# --- Senden ---------------------------------------------------------------- #


def test_mit_zustimmung_meldet_sich_der_versand_mit_dem_token_an(db, konto, zugang, leitung):  # noqa: F811
    konto.oauth_zugang_id = zugang.id
    db.commit()

    zeile = senden.einreihen(db, konto, _entwurf())
    senden.versenden(db, zeile)

    anmeldung = _anmeldung(leitung)
    assert [b[0] for b in anmeldung] == ["DOCMD"]
    _, befehl, argument = anmeldung[0]
    assert befehl == "AUTH"
    verfahren, roh = argument.split(" ", 1)
    assert verfahren == "XOAUTH2"
    assert base64.b64decode(roh).decode() == mailoauth.xoauth2(konto.smtp_benutzer, "zugriff-1")
    assert any(b[0] == "SENDMAIL" for b in leitung.alle[0].befehle)
    db.refresh(zeile)
    assert zeile.stand == "gesendet"


def test_ohne_zustimmung_bleibt_es_beim_passwort(db, konto, leitung):  # noqa: F811
    zeile = senden.einreihen(db, konto, _entwurf())
    senden.versenden(db, zeile)

    assert _anmeldung(leitung) == [("LOGIN", konto.smtp_benutzer, "geheim")]


def test_eine_abgelaufene_zustimmung_setzt_beim_senden_den_banner(db, konto, zugang, anbieter, leitung):  # noqa: F811
    """⚠️ Sonst stünde nur im Postausgang „gescheitert", und niemand käme
    darauf, dass neu verbunden werden muss."""
    konto.oauth_zugang_id = zugang.id
    zugang.ablauf = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    anbieter.antworten.append(httpx.Response(400, json={"error": "invalid_grant"}))

    zeile = senden.einreihen(db, konto, _entwurf())
    with pytest.raises(senden.SendeFehler):
        senden.versenden(db, zeile)

    # Ohne Token geht keine Anmeldung hinaus, auch nicht mit dem Passwort.
    assert leitung.alle == []
    db.refresh(konto)
    db.refresh(zeile)
    assert konto.stoerung == "anmeldung"
    assert "neu verbinden" in zeile.letzter_fehler


# --- Umstellen ------------------------------------------------------------- #


def _aenderung(klient, konto_id: str, **anders) -> httpx.Response:
    """Das Formular schickt beim Speichern alle Felder des Postfachs mit."""
    zeile = next(k for k in klient.get("/api/konten").json() if k["id"] == konto_id)
    felder = {
        k: zeile[k]
        for k in (
            "anzeigename", "adresse", "imap_server", "imap_port", "imap_sicherheit",
            "imap_benutzer", "smtp_server", "smtp_port", "smtp_sicherheit", "smtp_benutzer",
        )
    }
    return klient.put(f"/api/konten/{konto_id}", json={**felder, **anders})


def _passwoerter(db, konto_id: str) -> tuple[str, str]:
    db.expire_all()
    return kontendienst.passwoerter_lesen(db.get(Konto, konto_id))


def test_die_antwort_nennt_die_zustimmung(klient, db, konto, zugang):  # noqa: F811
    """⚠️ Ohne sie begann das Formular beim Bearbeiten immer bei „Mit Passwort"."""
    konto.oauth_zugang_id = zugang.id
    db.commit()

    zeile = next(k for k in klient.get("/api/konten").json() if k["id"] == konto.id)
    assert zeile["oauth_zugang_id"] == zugang.id


def test_vom_passwort_zur_zustimmung(klient, db, konto, zugang):  # noqa: F811
    antwort = _aenderung(klient, konto.id, oauth_zugang_id=zugang.id)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["oauth_zugang_id"] == zugang.id
    db.expire_all()
    assert db.get(Konto, konto.id).oauth_zugang_id == zugang.id
    # Die alten Passwörter braucht niemand mehr; sie gehen weg.
    assert _passwoerter(db, konto.id) == ("", "")


def test_zurueck_aufs_passwort_nur_mit_einem_neuen(klient, db, konto, zugang):  # noqa: F811
    konto.oauth_zugang_id = zugang.id
    db.commit()

    ohne = _aenderung(klient, konto.id, oauth_zugang_id="")
    assert ohne.status_code == 400
    assert ohne.json()["detail"] == "passwort_fehlt"
    db.expire_all()
    assert db.get(Konto, konto.id).oauth_zugang_id == zugang.id

    mit = _aenderung(
        klient, konto.id, oauth_zugang_id="", imap_passwort="neu-1", smtp_passwort="neu-1"
    )
    assert mit.status_code == 200, mit.text
    db.expire_all()
    assert db.get(Konto, konto.id).oauth_zugang_id is None
    assert _passwoerter(db, konto.id) == ("neu-1", "neu-1")


def test_nicht_mitgeschickt_heisst_unveraendert(klient, db, konto, zugang):  # noqa: F811
    """Wer nur den Namen ändert (oder ein Skript, das das Feld nicht kennt),
    stellt nicht nebenbei aufs Passwort zurück."""
    konto.oauth_zugang_id = zugang.id
    db.commit()

    antwort = _aenderung(klient, konto.id, anzeigename="Arbeit")

    assert antwort.status_code == 200, antwort.text
    db.expire_all()
    assert db.get(Konto, konto.id).oauth_zugang_id == zugang.id


def test_eine_fremde_zustimmung_geht_nicht(klient, db, konto):  # noqa: F811
    """⚠️ Die Kennung kommt aus dem Browser."""
    fremder, _ = zweiten_benutzer_anlegen(db)
    fremd = OauthZugang(
        benutzer_id=fremder.id,
        art="google",
        adresse="jemand@example.org",
    )
    db.add(fremd)
    db.commit()

    antwort = _aenderung(klient, konto.id, oauth_zugang_id=fremd.id)

    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "oauth_zugang_unbekannt"
    db.expire_all()
    assert db.get(Konto, konto.id).oauth_zugang_id is None
    assert _passwoerter(db, konto.id) == ("geheim", "geheim")
