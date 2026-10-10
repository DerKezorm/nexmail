"""Die Anmeldung ueber Anbieter, soweit nexmail sie selbst leistet (Bauplan "Anmeldung mit OIDC und authentik").

Was in jeder App gleich ist, pruefen die Vertragstests in ``tests/nexoidc`` (Pflichttests 1 bis 39). Hier steht, was
nur nexmail hat:

- die Liste von 0.21 (Wanderung beim Start, Rueckleitadresse ``…/zurueck``, Rueckweg auf derselben Tabelle);
- ``aktiv`` als Spiegel fuer 0.21, das Geheimnis zweimal, die Nummern fuer das Modul;
- Sitzung mit ``SameSite=strict`` (Durchreichen beim Verknuepfen), Bremse je Absender, Passwort-Anmeldung abschaltbar,
  die Kontenliste mit Marken, die Rueckfrage beim Speichern der oeffentlichen Adresse, das Schema hinter dem Proxy;
- Einladungen ohne Rechte (die Teile von Pflichttest 16, die "editor" verlangen, in nexmails Begriffen).
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parent / "nexoidc"))

import oidc_fakes as fakes
from conftest import einrichten

from app import crypto
from app.config import get_settings
from app.db import SessionLocal, einstellung_lesen, einstellung_schreiben, engine
from app.main import app
from app.middleware import SchemaVomProxyMiddleware
from app.models import Benutzer, Einladung, OidcAnbieter, OidcVerknuepfung
from app.services import anmeldebremse, oidc_wanderung
from app.services import einladung as einladungsdienst
from app.services.oidc_store import alter_kontext
from app.vendor import nexoidc
from app.vendor.nexoidc import attempt, protocol, secret_context

BETREIBER, PASSWORT = "betreiber", "sehr-geheim-123"


def einstellung_setzen(schluessel: str, wert: str) -> None:
    with SessionLocal() as db:
        einstellung_schreiben(db, schluessel, wert)


def einstellung_holen(schluessel: str) -> str:
    # ⚠️ Jede Sitzung wird geschlossen: Eine offene haelt unter Windows die WAL-Datei fest, und die Wiederherstellung
    # in einem spaeteren Test kann sie dann nicht loeschen.
    with SessionLocal() as db:
        return einstellung_lesen(db, schluessel)


@pytest.fixture
def netz():
    netz = fakes.Network()
    nexoidc.use_transport(netz.transport())
    protocol.clear_caches()
    attempt.forget_used_states()
    yield netz
    nexoidc.use_transport(None)
    protocol.clear_caches()
    attempt.forget_used_states()


@pytest.fixture
def sso(netz):
    return netz.add(fakes.FakeProvider())


def browser() -> TestClient:
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


@pytest.fixture
def betreiber() -> TestClient:
    klient = browser()
    einrichten(klient, BETREIBER, PASSWORT)
    return klient


def anbieter_anlegen(betreiber: TestClient, fake, slug: str = "sso", **mehr) -> dict:
    antwort = betreiber.post(
        "/api/oidc/admin/providers",
        json={
            "label": slug.upper(),
            "slug": slug,
            "issuer": fake.issuer,
            "client_id": fake.client_id,
            "client_secret": fake.client_secret,
            **mehr,
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def ziel(antwort) -> str:
    assert antwort.status_code in (302, 303), (antwort.status_code, antwort.text[:200])
    return antwort.headers["location"]


def fehler_in(antwort) -> str | None:
    return parse_qs(urlsplit(ziel(antwort)).query).get("error", [None])[0]


def hin_und_zurueck(klient: TestClient, fake, slug: str = "sso", *, einladung: str | None = None, **kopf):
    start = klient.get(f"/api/oidc/{slug}/start", params={"invite": einladung} if einladung else {})
    beim_anbieter = ziel(start)
    pfad = urlsplit(parse_qs(urlsplit(beim_anbieter).query)["redirect_uri"][0]).path
    return klient.get(f"{pfad}?{urlencode(fake.authorize(beim_anbieter))}", headers=kopf)


def wer(klient: TestClient) -> str | None:
    antwort = klient.get("/api/auth/ich")
    return antwort.json()["benutzername"] if antwort.status_code == 200 else None


def verknuepfen(klient: TestClient, fake, slug: str = "sso", passwort: str = PASSWORT, **kopf):
    antwort = klient.post(f"/api/oidc/{slug}/link", json={"password": passwort})
    assert antwort.status_code == 200, antwort.text
    url = antwort.json()["url"]
    pfad = urlsplit(parse_qs(urlsplit(url).query)["redirect_uri"][0]).path
    return klient.get(f"{pfad}?{urlencode(fake.authorize(url))}", headers=kopf)


# --- Die Liste von 0.21 ----------------------------------------------------------------------------------------------


def eintrag_wie_021(kuerzel: str, issuer: str, client_id: str, geheimnis: str = "", *, aktiv: bool = True) -> str:
    """Ein Eintrag so, wie 0.21 ihn schrieb: nur ihre Spalten, Geheimnis mit ihrem Kontext."""
    from app.models import neue_id

    kennung = neue_id()
    wert = crypto.verschluesseln(geheimnis, alter_kontext(kennung)) if geheimnis else ""
    with engine.begin() as verbindung:
        verbindung.execute(
            text(
                "INSERT INTO oidc_anbieter (id, kuerzel, anzeigename, issuer, client_id, client_secret, scopes, "
                "aktiv, angelegt) VALUES (:id, :k, :a, :i, :c, :s, 'openid email profile', :aktiv, "
                "'2026-10-09 10:00:00')"
            ),
            {"id": kennung, "k": kuerzel, "a": kuerzel.title(), "i": issuer, "c": client_id, "s": wert, "aktiv": aktiv},
        )
    return kennung


def verknuepfung_wie_021(benutzer_id: str, issuer: str, subject: str) -> None:
    with engine.begin() as verbindung:
        verbindung.execute(
            text(
                "INSERT INTO oidc_verknuepfung (benutzer_id, issuer, subject, adresse_bestaetigt, angelegt) "
                "VALUES (:b, :i, :s, 0, '2026-10-09 10:00:00')"
            ),
            {"b": benutzer_id, "i": issuer, "s": subject},
        )


def benutzer_id(name: str) -> str:
    with SessionLocal() as db:
        return db.scalar(select(Benutzer.id).where(Benutzer.benutzername == name))


def test_the_list_of_0_21_keeps_its_redirect_address_and_signs_in_there(betreiber, sso, caplog):
    """Bauplan 01, letzter Absatz: Eintraege von 0.21 behalten ``/api/oidc/<kuerzel>/zurueck``; die Wanderung
    sichert vorher, ordnet die Verknuepfungen zu und laesst beim zweiten Start alles in Ruhe."""
    einstellung_setzen("oeffentliche_adresse", "http://testserver")
    eintrag_wie_021("keycloak", sso.issuer + "/", sso.client_id, sso.client_secret)
    # 0.21 speicherte ``iss`` des Tokens an der Verknuepfung.
    verknuepfung_wie_021(benutzer_id(BETREIBER), sso.issuer, "person-1")
    ordner = get_settings().data_dir / "sicherungen"
    vorher = set(ordner.glob("*.db")) if ordner.is_dir() else set()

    oidc_wanderung.laufen(engine)

    nachher = set(ordner.glob("*.db"))
    assert len(nachher - vorher) == 1, "vor der Wanderung wird gesichert"
    with SessionLocal() as db:
        row = db.scalar(select(OidcAnbieter).where(OidcAnbieter.kuerzel == "keycloak"))
        assert row.redirect_path == "/api/oidc/keycloak/zurueck"
        assert row.issuer == sso.issuer + "/", "der Aussteller behaelt seine Schreibweise"
        assert row.eingeschaltet is True and row.trusts_second_factor is True and row.managed == ""
        assert crypto.entschluesseln(row.client_secret_enc, secret_context(row.nummer)) == sso.client_secret
        link = db.scalar(select(OidcVerknuepfung))
        assert link.anbieter_id == row.id
    eintraege = betreiber.get("/api/oidc/admin/providers").json()
    assert eintraege[0]["redirect_uri"] == "http://testserver/api/oidc/keycloak/zurueck"
    klient = browser()
    antwort = hin_und_zurueck(klient, sso, "keycloak")
    assert urlsplit(ziel(antwort)).path == "/" and wer(klient) == BETREIBER
    # Zweiter Start: still.
    caplog.clear()
    oidc_wanderung.laufen(engine)
    assert set(ordner.glob("*.db")) == nachher
    assert "0.21" not in caplog.text


def test_the_button_entry_of_0_21_counts_as_set_up_through_authentik(betreiber):
    eintrag_wie_021("authentik", "https://auth.example.com/application/o/nexmail/", "abc")
    eintrag_wie_021("authentik-zwei", "https://auth.example.com/application/o/nexmail-2/", "def")
    oidc_wanderung.laufen(engine)
    with SessionLocal() as db:
        verwaltet = dict(db.execute(select(OidcAnbieter.kuerzel, OidcAnbieter.managed)).all())
    assert verwaltet == {"authentik": "authentik", "authentik-zwei": ""}


def test_every_new_column_has_a_default_so_0_21_keeps_writing(betreiber):
    """0.21 kennt die neuen Spalten nicht. Auf einer Datenbank, die der neue Code angelegt hat, legt sie weiter
    Eintraege, Verknuepfungen, Konten und Sitzungen an (rohe INSERTs nur mit ihren Spalten)."""
    with engine.connect() as verbindung:
        for tabelle, neue in (
            ("oidc_anbieter", {"client_secret_enc", "auto_create", "trusts_second_factor", "managed", "position",
                               "registered_redirect"}),
            ("oidc_verknuepfung", {"email", "adresse_bestaetigt"}),
        ):
            spalten = {zeile[1]: zeile for zeile in verbindung.execute(text(f"PRAGMA table_info({tabelle})"))}
            for name in neue:
                assert spalten[name][4] is not None, f"{tabelle}.{name} ohne Vorgabe"
        for name in ("nummer", "eingeschaltet", "redirect_path"):
            spalten = {zeile[1]: zeile for zeile in verbindung.execute(text("PRAGMA table_info(oidc_anbieter)"))}
            assert spalten[name][3] == 0, f"oidc_anbieter.{name} muss NULL erlauben"
    kennung = eintrag_wie_021("alt", "https://alt.example.com", "x")
    verknuepfung_wie_021(benutzer_id(BETREIBER), "https://alt.example.com", "s-1")
    # Ein Konto von 0.21 hat keine Nummer (ihr Modell kennt die Spalte nicht); die echte alte Fassung prueft die
    # Rueckweg-Probe (``bericht.md``), hier nur die Folge.
    with engine.begin() as verbindung:
        verbindung.execute(text("UPDATE benutzer SET nummer = NULL"))
    with SessionLocal() as db:
        row = db.get(OidcAnbieter, kennung)
        assert (row.auto_create, row.trusts_second_factor, row.managed, row.position) == (False, True, "", 0)
        assert row.nummer is None and row.redirect_path is None
    oidc_wanderung.laufen(engine)
    with SessionLocal() as db:
        assert db.get(OidcAnbieter, kennung).nummer is not None
        assert db.scalar(select(Benutzer.nummer).where(Benutzer.benutzername == BETREIBER)) is not None


def test_aktiv_is_what_0_21_sees_and_its_switch_comes_back(betreiber, sso):
    """``aktiv`` ist an nur mit Eintrag an UND „Anbieter prueft den zweiten Faktor selbst" (0.21 fragt keinen Code).
    Schaltet 0.21 um, gilt das beim naechsten Start auch hier."""
    eintrag = anbieter_anlegen(betreiber, sso, trusts_second_factor=False)

    def zeile() -> OidcAnbieter:
        with SessionLocal() as db:
            return db.scalar(select(OidcAnbieter).where(OidcAnbieter.kuerzel == "sso"))

    assert zeile().aktiv is False and zeile().eingeschaltet is True
    # 0.21 schaltet ihn ein: dort fragte nach dem Anbieter niemand den Code.
    with engine.begin() as verbindung:
        verbindung.execute(text("UPDATE oidc_anbieter SET aktiv = 1 WHERE kuerzel = 'sso'"))
    oidc_wanderung.laufen(engine)
    assert (zeile().aktiv, zeile().eingeschaltet, zeile().trusts_second_factor) == (True, True, True)
    # 0.21 schaltet ihn aus.
    with engine.begin() as verbindung:
        verbindung.execute(text("UPDATE oidc_anbieter SET aktiv = 0 WHERE kuerzel = 'sso'"))
    oidc_wanderung.laufen(engine)
    assert zeile().eingeschaltet is False
    assert betreiber.get("/api/oidc/admin/providers").json()[0]["enabled"] is False
    assert eintrag["id"] == zeile().nummer


def test_a_secret_0_21_changed_is_taken_over(betreiber, sso):
    anbieter_anlegen(betreiber, sso)
    with SessionLocal() as db:
        row = db.scalar(select(OidcAnbieter))
        assert crypto.entschluesseln(row.client_secret, alter_kontext(row.id)) == sso.client_secret
        row.client_secret = crypto.verschluesseln("neu-aus-alt", alter_kontext(row.id))
        db.commit()
    oidc_wanderung.laufen(engine)
    with SessionLocal() as db:
        row = db.scalar(select(OidcAnbieter))
        assert crypto.entschluesseln(row.client_secret_enc, secret_context(row.nummer)) == "neu-aus-alt"


def test_a_link_whose_entry_got_another_issuer_in_0_21_signs_in_nowhere_until_it_is_back(betreiber, sso, netz):
    anbieter_anlegen(betreiber, sso)
    verknuepfen(betreiber, sso)
    anderer = netz.add(fakes.FakeProvider("https://other.example.com", client_id=sso.client_id))
    with engine.begin() as verbindung:
        verbindung.execute(text("UPDATE oidc_anbieter SET issuer = :i"), {"i": anderer.issuer})
    oidc_wanderung.laufen(engine)
    with SessionLocal() as db:
        assert db.scalar(select(OidcVerknuepfung)).anbieter_id is None
    anderer.client_secret = sso.client_secret
    assert fehler_in(hin_und_zurueck(browser(), anderer)) == "oidc_no_account"
    with engine.begin() as verbindung:
        verbindung.execute(text("UPDATE oidc_anbieter SET issuer = :i"), {"i": sso.issuer})
    oidc_wanderung.laufen(engine)
    klient = browser()
    hin_und_zurueck(klient, sso)
    assert wer(klient) == BETREIBER


def test_saving_the_same_issuer_keeps_how_it_was_written(betreiber, sso):
    eintrag_wie_021("sso", sso.issuer + "/", sso.client_id, sso.client_secret)
    oidc_wanderung.laufen(engine)
    item = betreiber.get("/api/oidc/admin/providers").json()[0]
    body = {k: item[k] for k in ("label", "issuer", "client_id", "scopes", "enabled", "auto_create",
                                 "trusts_second_factor")}
    antwort = betreiber.put(f"/api/oidc/admin/providers/{item['id']}", json={**body, "label": "Neu", "client_secret": ""})
    assert antwort.status_code == 200, antwort.text
    with SessionLocal() as db:
        assert db.scalar(select(OidcAnbieter.issuer)) == sso.issuer + "/"


# --- Sitzung, Bremse, Routen --------------------------------------------------------------------------------------


def test_the_brake_is_not_fed_by_returns_without_an_attempt(betreiber, sso):
    """Eine Rueckkehr ohne gueltiges Anlauf-Cookie (``?error=``, Muell, erfundener Kurzname) fuettert die Bremse
    nie: sonst sperrte jeder Fremde alle anderen hinter demselben Proxy aus."""
    get_settings().client_ip = "direct"
    try:
        anbieter_anlegen(betreiber, sso)
        fremd = browser()
        for _ in range(anmeldebremse.SPERRE_AB_VERSUCH + 2):
            fremd.get("/api/oidc/sso/callback?error=access_denied")
            fremd.get("/api/oidc/sso/callback?code=x&state=y")
            fremd.get("/api/oidc/gibtsnicht/callback?code=x&state=y")
            fremd.get("/api/oidc/sso/zurueck?code=x&state=y")
        assert not any(k.startswith("oidc:") for k in anmeldebremse._zaehler), "die Bremse wurde gefuettert"
        start = browser().get("/api/oidc/sso/start")
        assert "authorize" in ziel(start)
        # Mit gueltigem Anlauf und falschem Code zaehlt es.
        klient = browser()
        ziel_url = ziel(klient.get("/api/oidc/sso/start"))
        state = parse_qs(urlsplit(ziel_url).query)["state"][0]
        assert fehler_in(klient.get(f"/api/oidc/sso/callback?code=falsch&state={state}")) == "oidc_token_refused"
        assert anmeldebremse._zaehler["oidc:adresse:testclient"].versuche == 1
    finally:
        get_settings().client_ip = ""


def test_a_provider_named_authentik_is_not_hidden_by_the_fixed_routes(betreiber, netz):
    """Der Knopf legt den Kurznamen ``authentik`` an; ``/api/oidc/authentik/address`` und Co. duerfen dessen Start
    und Rueckkehr nicht verdecken."""
    fake = netz.add(fakes.FakeProvider("https://auth.example.com/application/o/nexmail/"))
    verknuepft = anbieter_anlegen(betreiber, fake, "authentik")
    assert verknuepft["slug"] == "authentik"
    verknuepfen(betreiber, fake, "authentik")
    klient = browser()
    antwort = hin_und_zurueck(klient, fake, "authentik")
    assert urlsplit(ziel(antwort)).path == "/" and wer(klient) == BETREIBER


def test_linking_bounces_once_to_see_the_strict_session(betreiber, sso):
    """Das Sitzungs-Cookie ist ``SameSite=strict``; ein Browser schickt es bei der Rueckkehr vom Anbieter (fremde
    Seite) nicht mit. Die Rueckkehr reicht dann einmal durch (eigene Seite, nichts verbraucht) und nimmt danach das
    Konto aus der Sitzung."""
    anbieter_anlegen(betreiber, sso)
    antwort = betreiber.post("/api/oidc/sso/link", json={"password": PASSWORT})
    url = antwort.json()["url"]
    pfad = urlsplit(parse_qs(urlsplit(url).query)["redirect_uri"][0]).path
    zurueck = f"{pfad}?{urlencode(sso.authorize(url))}"
    sitzung = betreiber.cookies.get("nexmail_sitzung")
    betreiber.cookies.delete("nexmail_sitzung")
    erst = betreiber.get(zurueck, headers={"Sec-Fetch-Site": "cross-site"})
    assert erst.status_code == 200 and 'http-equiv="refresh"' in erst.text
    assert zurueck.replace("&", "&amp;") in erst.text
    betreiber.cookies.set("nexmail_sitzung", sitzung, path="/api")
    dann = betreiber.get(zurueck, headers={"Sec-Fetch-Site": "same-origin"})
    assert fehler_in(dann) is None and urlsplit(ziel(dann)).path == "/konto/sicherheit"
    with SessionLocal() as db:
        assert db.scalar(select(OidcVerknuepfung.subject)) == "person-1"


def test_without_a_session_a_bounced_linking_ends_refused(betreiber, sso):
    anbieter_anlegen(betreiber, sso)
    url = betreiber.post("/api/oidc/sso/link", json={"password": PASSWORT}).json()["url"]
    pfad = urlsplit(parse_qs(urlsplit(url).query)["redirect_uri"][0]).path
    zurueck = f"{pfad}?{urlencode(sso.authorize(url))}"
    betreiber.cookies.delete("nexmail_sitzung")
    dann = betreiber.get(zurueck, headers={"Sec-Fetch-Site": "same-origin"})
    assert fehler_in(dann) == "oidc_link_mismatch"


def test_linking_asks_the_password_again(betreiber, sso):
    anbieter_anlegen(betreiber, sso)
    antwort = betreiber.post("/api/oidc/sso/link", json={"password": "falsch-falsch"})
    assert antwort.status_code == 400 and antwort.json()["detail"] == "kennwort_falsch"


def test_a_provider_that_does_not_check_the_second_factor_asks_the_code(betreiber, sso):
    from conftest import aktueller_code, zwei_faktor_an

    geheimnis, _ = zwei_faktor_an(betreiber)
    anbieter_anlegen(betreiber, sso, trusts_second_factor=False)
    verknuepfen(betreiber, sso)
    klient = browser()
    antwort = hin_und_zurueck(klient, sso)
    assert ziel(antwort) == "/anmelden?schritt=code" and wer(klient) is None
    with SessionLocal() as db:
        db.execute(text("UPDATE benutzer SET totp_letzter_schritt = 0"))
        db.commit()
    code = klient.post("/api/auth/code", json={"code": aktueller_code(geheimnis)})
    assert code.status_code == 200 and wer(klient) == BETREIBER


# --- Passwort-Anmeldung, Kontenliste, oeffentliche Adresse --------------------------------------------------------


def test_password_sign_in_switches_off_only_with_an_active_provider_and_the_operator_keeps_it(betreiber, sso):
    assert betreiber.put("/api/oidc/admin/anmeldung", json={"passwort": False}).status_code == 409
    eintrag = anbieter_anlegen(betreiber, sso)
    assert betreiber.put("/api/oidc/admin/anmeldung", json={"passwort": False}).json()["passwort"] is False
    with SessionLocal() as db:
        from app.services import benutzer as benutzerdienst

        benutzerdienst.anlegen(db, "mitglied", "auch-sehr-geheim-1")
    seite = browser().get("/api/oidc/anmeldeseite").json()
    assert seite == {"providers": [{"slug": "sso", "label": "SSO"}], "password": False}
    abgewiesen = browser().post("/api/auth/anmelden", json={"benutzername": "mitglied", "passwort": "auch-sehr-geheim-1"})
    assert abgewiesen.status_code == 403 and abgewiesen.json()["detail"] == "passwort_anmeldung_aus"
    selbst = browser().post("/api/auth/anmelden", json={"benutzername": BETREIBER, "passwort": PASSWORT})
    assert selbst.status_code == 200
    # Eine Einladung nimmt dann kein Kennwort an.
    with SessionLocal() as db:
        _, schluessel = einladungsdienst.aussprechen(db, benutzername="neu", adresse="neu@example.com")
    assert browser().get(f"/api/einladung/{schluessel}").json()["passwort"] is False
    assert browser().post(f"/api/einladung/{schluessel}", json={"passwort": "noch-ein-kennwort"}).status_code == 403
    # Kein aktiver Anbieter mehr: Das Passwort gilt von selbst wieder.
    item = betreiber.get("/api/oidc/admin/providers").json()[0]
    body = {k: item[k] for k in ("label", "issuer", "client_id", "scopes", "auto_create", "trusts_second_factor")}
    assert betreiber.put(f"/api/oidc/admin/providers/{eintrag['id']}", json={**body, "enabled": False}).status_code == 200
    wieder = browser().post("/api/auth/anmelden", json={"benutzername": "mitglied", "passwort": "auch-sehr-geheim-1"})
    assert wieder.status_code == 200


def test_the_account_list_shows_the_links_and_the_operator_unlinks_with_the_own_password(betreiber, sso):
    eintrag = anbieter_anlegen(betreiber, sso)
    verknuepfen(betreiber, sso)
    zeilen = betreiber.get("/api/benutzer").json()["benutzer"]
    ich = next(z for z in zeilen if z["benutzername"] == BETREIBER)
    assert ich["anbieter"] == [{"id": eintrag["id"], "slug": "sso", "label": "SSO"}] and ich["nummer"] > 0
    weg = betreiber.request(
        "DELETE", f"/api/oidc/admin/accounts/{ich['nummer']}/links/{eintrag['id']}", json={"password": PASSWORT}
    )
    assert weg.status_code == 204
    assert betreiber.get("/api/benutzer").json()["benutzer"][0]["anbieter"] == []


def test_saving_or_clearing_the_public_address_asks_while_a_provider_knows_it(betreiber, sso):
    einstellung_setzen("oeffentliche_adresse", "https://mail.example.org")
    anbieter_anlegen(betreiber, sso)
    for neu in ("https://other.example.org", ""):
        gefragt = betreiber.put("/api/einstellungen", json={"oeffentliche_adresse": neu, "zeitzone": ""})
        assert gefragt.status_code == 409 and gefragt.json()["detail"] == "public_url_change"
        assert gefragt.json()["werte"]["hand"] == 1
        assert einstellung_holen("oeffentliche_adresse") == "https://mail.example.org"
    ja = betreiber.put(
        "/api/einstellungen", json={"oeffentliche_adresse": "", "zeitzone": "", "adresse_bestaetigt": True}
    )
    assert ja.status_code == 200 and einstellung_holen("oeffentliche_adresse") == ""
    # Dieselbe Adresse noch einmal (nur die Zeitzone geaendert) fragt nichts.
    assert betreiber.put("/api/einstellungen", json={"oeffentliche_adresse": "", "zeitzone": "UTC"}).status_code == 200


@pytest.mark.parametrize(
    "adresse", ["https://exa mple.org", "https://app.example.org/../x", "https://bücher.example.org", "https://a.example.org/?x=1"]
)
def test_the_public_address_is_checked_as_strictly_as_the_module_does(betreiber, adresse):
    antwort = betreiber.put("/api/einstellungen", json={"oeffentliche_adresse": adresse, "zeitzone": ""})
    assert antwort.status_code == 400, antwort.text
    assert einstellung_holen("oeffentliche_adresse") == ""


# --- Einladungen (Pflichttest 16 ohne Rechte) ------------------------------------------------------------------------


def test_an_invitation_through_a_provider_makes_one_account_named_by_the_provider(betreiber, sso):
    anbieter_anlegen(betreiber, sso)
    with SessionLocal() as db:
        _, schluessel = einladungsdienst.aussprechen(
            db, benutzername="annalena", adresse="anna@example.com", anzeigename="Anna Lena"
        )
    sso.person = {"sub": "p-anna", "preferred_username": "anna@example.com", "email": "anders@example.com"}
    klient = browser()
    antwort = hin_und_zurueck(klient, sso, einladung=schluessel)
    assert urlsplit(ziel(antwort)).path == "/" and wer(klient) == "anna"
    with SessionLocal() as db:
        person = db.scalar(select(Benutzer).where(Benutzer.benutzername == "anna"))
        assert (person.anzeigename, person.kontaktadresse, person.passwort_hash) == ("Anna Lena", "anna@example.com", "")
        assert db.scalar(select(Einladung.eingeloest)) is not None
    assert fehler_in(browser().get("/api/oidc/sso/start", params={"invite": schluessel})) == "invite_invalid"


def test_a_known_identity_with_an_invitation_signs_in_and_uses_it_up(betreiber, sso):
    anbieter_anlegen(betreiber, sso)
    verknuepfen(betreiber, sso)
    with SessionLocal() as db:
        _, schluessel = einladungsdienst.aussprechen(db, benutzername="zweiter", adresse="z@example.com")
        vorher = len(db.scalars(select(Benutzer.id)).all())
    klient = browser()
    hin_und_zurueck(klient, sso, einladung=schluessel)
    assert wer(klient) == BETREIBER
    with SessionLocal() as db:
        assert len(db.scalars(select(Benutzer.id)).all()) == vorher
        assert db.scalar(select(Einladung.eingeloest)) is not None


# --- Hinter einem Proxy ---------------------------------------------------------------------------------------------


async def _schema_hinter(client_ip: str, kopfzeilen: list[tuple[bytes, bytes]], art: str = "http") -> str:
    gesehen: dict[str, str] = {}

    async def innen(scope, receive, send):
        gesehen["schema"] = scope["scheme"]

    vorher = get_settings().client_ip
    get_settings().client_ip = client_ip
    try:
        await SchemaVomProxyMiddleware(innen)(
            {"type": art, "scheme": "ws" if art == "websocket" else "http", "headers": kopfzeilen}, None, None
        )
    finally:
        get_settings().client_ip = vorher
    return gesehen["schema"]


@pytest.mark.parametrize(
    ("client_ip", "kopf", "art", "erwartet"),
    [
        ("", [(b"x-forwarded-proto", b"https")], "http", "http"),
        ("direct", [(b"x-forwarded-proto", b"https")], "http", "http"),
        ("proxy", [(b"x-forwarded-proto", b"https")], "http", "https"),
        ("proxy", [(b"X-Forwarded-Proto", b"HTTPS")], "http", "https"),
        ("proxy", [(b"x-forwarded-proto", b"https, http")], "http", "http"),
        ("proxy", [(b"x-forwarded-proto", b"http"), (b"x-forwarded-proto", b"https")], "http", "https"),
        ("proxy", [(b"x-forwarded-proto", b"gopher")], "http", "http"),
        ("proxy:2", [(b"x-forwarded-proto", b"https")], "websocket", "wss"),
        ("proxy", [], "http", "http"),
    ],
)
def test_the_scheme_comes_from_a_trusted_proxy_only_rightmost(client_ip, kopf, art, erwartet):
    import asyncio

    assert asyncio.run(_schema_hinter(client_ip, kopf, art)) == erwartet


def test_behind_a_trusted_proxy_the_redirect_address_is_https(betreiber, sso):
    anbieter_anlegen(betreiber, sso)
    get_settings().client_ip = "proxy"
    try:
        start = browser().get("/api/oidc/sso/start", headers={"X-Forwarded-Proto": "https"})
        assert parse_qs(urlsplit(ziel(start)).query)["redirect_uri"][0].startswith("https://testserver/")
    finally:
        get_settings().client_ip = ""
    fremd = browser().get("/api/oidc/sso/start", headers={"X-Forwarded-Proto": "https"})
    assert parse_qs(urlsplit(ziel(fremd)).query)["redirect_uri"][0].startswith("http://testserver/")


# --- Kennungen -------------------------------------------------------------------------------------------------------


def test_every_code_of_the_oidc_routes_has_a_text_in_the_module_wording():
    """``routers/oidc.abgelehnt`` gibt Kennungen des Moduls hinaus; uebersetzt werden sie aus dessen Wortlauten
    (``oidc.error``, ``oidc.formError``) oder von der Seite selbst (die Rueckfragen zur Adresse)."""
    import ast
    import json

    wurzel = Path(__file__).resolve().parents[2]
    wortlaut = json.loads((wurzel / "frontend/src/vendor/nexoidc/oidc.de.json").read_text(encoding="utf-8"))["oidc"]
    bekannt = set(wortlaut["error"]) | set(wortlaut["formError"])
    rueckfragen = {"public_url_change", "public_url_invalid", "public_url_needed"}
    genannt: set[str] = set()
    for datei in (wurzel / "backend/app/routers").glob("*.py"):
        for knoten in ast.walk(ast.parse(datei.read_text(encoding="utf-8"))):
            if isinstance(knoten, ast.Call) and getattr(knoten.func, "attr", getattr(knoten.func, "id", "")) == "abgelehnt":
                erst = knoten.args[1]
                if isinstance(erst, ast.Constant):
                    genannt.add(erst.value)
    assert genannt, "keine Stelle gefunden: der Waechter sieht nichts"
    assert genannt - bekannt - rueckfragen == set()
    assert {"too_many_attempts", "oidc_not_configured", "public_url_change"} <= genannt
