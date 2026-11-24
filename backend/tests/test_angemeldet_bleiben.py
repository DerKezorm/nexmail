"""„Angemeldet bleiben“, bekannte Browser und die Mail „Neue Anmeldung“ (Kontenmodul Teil 2)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, einstellung_schreiben
from app.main import app
from app.models import Benutzer, Sitzung, utcnow
from app.services import anmeldebremse, systempost
from app.services import sitzung as sitzungsdienst
from conftest import einrichten

PASSWORT = "sehr-geheim-123"


@pytest.fixture(autouse=True)
def freie_bremse():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def post(monkeypatch):
    versandt: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(systempost, "senden", lambda db, an, betreff, text, html="": versandt.append((an, betreff, text, html)))
    monkeypatch.setattr(
        systempost, "lesen", lambda db: systempost.Postausgang(server="s.example", absender="a@example.com")
    )
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")
    return versandt


def _neuer_browser() -> TestClient:
    return TestClient(app)


def _anmelden(klient: TestClient, bleiben: bool | None = None, passwort: str = PASSWORT):
    daten = {"benutzername": "betreiber", "passwort": passwort}
    if bleiben is not None:
        daten["angemeldet_bleiben"] = bleiben
    return klient.post("/api/auth/anmelden", json=daten)


def _sitzungscookie(antwort) -> str:
    for zeile in antwort.headers.get_list("set-cookie"):
        if zeile.startswith(sitzungsdienst.COOKIE_NAME + "="):
            return zeile
    raise AssertionError("kein Sitzungscookie")


def _adresse_bestaetigt(db) -> None:
    ich = db.query(Benutzer).one()
    ich.kontaktadresse = "betreiber@example.com"
    ich.kontaktadresse_zaehlt = True
    db.commit()


def test_angemeldet_bleiben_ist_ab_werk_an_und_gleitet(klient, db):
    einrichten(klient)
    antwort = _anmelden(_neuer_browser())
    assert antwort.status_code == 200, antwort.text
    cookie = _sitzungscookie(antwort).lower()
    assert f"max-age={400 * 86400}" in cookie
    neueste = db.query(Sitzung).order_by(Sitzung.angelegt.desc()).first()
    assert neueste.merken
    assert neueste.gueltig_bis - utcnow() > timedelta(days=29)


def test_ohne_angemeldet_bleiben_endet_die_sitzung_mit_dem_browser(klient, db):
    einrichten(klient)
    browser = _neuer_browser()
    antwort = _anmelden(browser, bleiben=False)
    assert antwort.status_code == 200, antwort.text
    assert "max-age" not in _sitzungscookie(antwort).lower()
    sitzung = db.query(Sitzung).filter(Sitzung.merken.is_(False)).one()
    assert timedelta(hours=11) < sitzung.gueltig_bis - utcnow() <= timedelta(hours=12)

    # Sie gleitet nicht: auch nach langer Arbeit spaetestens nach 12 Stunden Schluss.
    sitzung.zuletzt_gesehen = utcnow() - timedelta(hours=2)
    ende = sitzung.gueltig_bis
    db.commit()
    assert browser.get("/api/auth/ich").status_code == 200
    db.expire_all()
    assert db.get(Sitzung, sitzung.id).gueltig_bis == ende


def test_neue_anmeldung_meldet_nur_unbekannte_browser(klient, db, post):
    einrichten(klient)
    _adresse_bestaetigt(db)

    fremd = _neuer_browser()
    assert _anmelden(fremd).status_code == 200
    assert [an for an, *_ in post] == ["betreiber@example.com"]
    betreff, text = post[0][1], post[0][2]
    # Der User-Agent des Testklienten ist kein bekannter Browser: Die Mail sagt das, ohne seinen Text zu zeigen.
    assert betreff and "testclient" not in text.lower()

    # Derselbe Browser ein zweites Mal: bekannt, keine Mail.
    assert _anmelden(fremd).status_code == 200
    assert len(post) == 1

    # Abgeschaltet im Profil: auch ein neuer Browser bleibt still.
    assert klient.put("/api/auth/ich/neue-anmeldung", json={"an": False}).json()["mail_neue_anmeldung"] is False
    assert _anmelden(_neuer_browser()).status_code == 200
    assert len(post) == 1


def test_ein_browser_von_vor_dem_update_wird_still_bekannt(klient, db, post):
    """Wer schon angemeldet war, bekommt beim naechsten Anmelden am eigenen Rechner keine Mail."""
    einrichten(klient)
    _adresse_bestaetigt(db)
    klient.cookies.delete(sitzungsdienst.BEKANNT_COOKIE)
    assert klient.get("/api/auth/ich").status_code == 200
    assert klient.cookies.get(sitzungsdienst.BEKANNT_COOKIE)
    assert _anmelden(klient).status_code == 200
    assert post == []


def test_der_bekannte_browser_ist_von_der_kontosperre_ausgenommen(klient, db, monkeypatch):
    einrichten(klient)
    # Die Bremse ist ein eigener Riegel; hier geht es um die Sperre am Konto.
    monkeypatch.setattr(anmeldebremse, "torwaechter", lambda *a, **k: _OhneBremse())

    fremd = _neuer_browser()
    for _ in range(10):
        assert _anmelden(fremd, passwort="falsch-falsch").status_code == 401
    db.expire_all()
    assert db.query(Benutzer).one().gesperrt_bis is not None
    assert _anmelden(_neuer_browser()).status_code == 401
    assert _anmelden(klient).status_code == 200


class _OhneBremse:
    def fehlgeschlagen(self) -> None:
        pass

    def geschafft(self) -> None:
        pass


def test_der_bekannte_browser_kommt_auch_an_der_bremse_vorbei(klient, db):
    """konten 0.3.1: Wer fremd das Passwort durchprobiert, fuellt den Topf des Kontos; der Besitzer an seinem Rechner
    hat einen eigenen."""
    einrichten(klient)
    fremd = _neuer_browser()
    for _ in range(anmeldebremse.SPERRE_AB_VERSUCH):
        for zaehler in anmeldebremse._zaehler.values():
            zaehler.frei_ab = 0
        fremd.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "falsch-falsch"})
    assert _anmelden(_neuer_browser()).status_code == 429
    assert _anmelden(klient).status_code == 200


def test_zweiter_faktor_fuer_alle_verlangt_ihn_bei_der_naechsten_anmeldung(klient, db):
    """Kontenmodul Teil 2: ab Werk aus; an, richtet ein Konto ohne Faktor ihn beim Anmelden ein."""
    from app.services import benutzer as benutzerdienst
    from conftest import aktueller_code

    einrichten(klient)
    benutzerdienst.anlegen(db, "zweiter", "auch-geheim-456")
    db.commit()
    stand = klient.get("/api/oidc/admin/anmeldung").json()
    assert stand["zwei_faktor_fuer_alle"] is False
    an = klient.put("/api/oidc/admin/anmeldung", json={"zwei_faktor_fuer_alle": True})
    assert an.status_code == 200 and an.json()["zwei_faktor_fuer_alle"] is True and an.json()["passwort"] is True

    browser = _neuer_browser()
    antwort = browser.post("/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": "auch-geheim-456"})
    assert antwort.json()["schritt"] == "einrichten", antwort.text
    assert browser.get("/api/auth/ich").status_code == 401
    geheimnis = browser.get("/api/auth/einrichtung").json()["geheimnis"]
    fertig = browser.post("/api/auth/code", json={"code": aktueller_code(geheimnis)})
    assert fertig.status_code == 200 and fertig.json()["schritt"] == "fertig", fertig.text
    assert browser.get("/api/auth/ich").json()["zwei_faktor_aktiv"] is True


def test_der_betreiber_sieht_den_letzten_fehler_der_systempost(klient, db, monkeypatch):
    """Mailmodul: Eine Systemmail, die scheitert, steht als letzter Fehler im Postausgang und wartet auf den naechsten
    Versuch."""
    from app.vendor import nexpost
    from app.vendor.nexpost.errors import MailError

    einrichten(klient)
    with SessionLocal() as s:
        systempost.schreiben(s, systempost.Postausgang(server="s.example", absender="a@example.com"), None)
        einstellung_schreiben(s, "oeffentliche_adresse", "https://mail.example")

    class Weg:
        def __init__(self, *a, **k) -> None:
            raise MailError("mail_unreachable", "no route")

    nexpost.config.use_smtp(lambda *a, **k: Weg())
    _adresse_bestaetigt(db)
    assert _anmelden(_neuer_browser()).status_code == 200
    stand = klient.get("/api/einstellungen/postausgang").json()
    assert stand["letzter_fehler"] == "mail_unreachable" and stand["letzter_fehler_am"]
    assert stand["wartend"] == 1
