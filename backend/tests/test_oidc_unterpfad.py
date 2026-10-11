"""Die Anmeldung ueber Anbieter unter einem Unterpfad (``NEXMAIL_URL_BASE=/nexmail``).

0.21 baute jede Rueckleitadresse aus der gespeicherten Adresse UND dem Vorbau; die Adresse stand ohne ihn da. Seit dem
Anmeldemodul gilt die gespeicherte Adresse samt Vorbau. Die Wanderung haengt ihn deshalb einmal an, damit die Adresse,
die die Anbieter kennen, gleich bleibt, und jede andere Stelle, die den Vorbau anhaengt, schreibt ihn nie doppelt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent / "nexoidc"))

from test_oidc_app import (  # noqa: F401  (Fixtures)
    BETREIBER,
    PASSWORT,
    betreiber,
    eintrag_wie_021,
    einstellung_holen,
    einstellung_setzen,
    netz,
    sso,
)

from app.config import get_settings
from app.db import SessionLocal, engine
from app.main import app
from app.middleware import BasisPfadMiddleware
from app.models import OidcVerknuepfung
from app.services import oidc_wanderung
from app.services.adresse import mit_vorbau

VORBAU = "/nexmail"
ADRESSE_021 = "https://mail.example.org"


@pytest.fixture
def unterpfad(monkeypatch):
    """NEXMAIL_URL_BASE gesetzt (die Einstellungen werden bei jedem Aufruf gelesen); die Anwendung selbst bleibt, wie
    sie ist, damit die Fixtures der anderen Tests nicht ins Leere greifen."""
    monkeypatch.setenv("NEXMAIL_URL_BASE", VORBAU)
    get_settings.cache_clear()
    try:
        yield
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_the_prefix_is_never_written_twice():
    assert mit_vorbau("https://mail.example.org", "/nexmail") == "https://mail.example.org/nexmail"
    assert mit_vorbau("https://mail.example.org/", "/nexmail") == "https://mail.example.org/nexmail"
    assert mit_vorbau("https://mail.example.org/nexmail", "/nexmail") == "https://mail.example.org/nexmail"
    assert mit_vorbau("https://mail.example.org/nexmail/", "/nexmail") == "https://mail.example.org/nexmail"
    assert mit_vorbau("https://mail.example.org/", "") == "https://mail.example.org"
    assert mit_vorbau("", "/nexmail") == "/nexmail", "ohne Adresse bleibt der Vorbau, wie 0.21 ihn baute"


def test_the_migration_gives_the_stored_address_its_prefix_once_and_the_redirect_address_stays(
    betreiber, sso, unterpfad, caplog
):
    """Eine Adresse ohne Vorbau aus 0.21 plus ``NEXMAIL_URL_BASE``: Die Rueckleitadresse bleibt, wie 0.21 sie baute
    (``<Adresse><Vorbau>/api/oidc/<kuerzel>/zurueck``). Gesichert wird vorher, im Protokoll steht eine Zeile, der
    zweite Start tut nichts."""
    einstellung_setzen("oeffentliche_adresse", ADRESSE_021)
    eintrag_wie_021("keycloak", sso.issuer, sso.client_id, sso.client_secret)
    ordner = get_settings().data_dir / "sicherungen"
    vorher = set(ordner.glob("*.db")) if ordner.is_dir() else set()
    wie_021 = f"{ADRESSE_021}{VORBAU}/api/oidc/keycloak/zurueck"

    with caplog.at_level("INFO", logger="nexmail.oidc"):
        oidc_wanderung.laufen(engine)

    assert einstellung_holen("oeffentliche_adresse") == ADRESSE_021 + VORBAU
    assert len(set(ordner.glob("*.db")) - vorher) == 1, "vor der Aenderung wird gesichert"
    assert sum("sub path" in zeile for zeile in caplog.messages) == 1
    assert betreiber.get("/api/oidc/admin/providers").json()[0]["redirect_uri"] == wie_021
    # Zweiter Start: nichts mehr, der Vorbau steht nicht doppelt.
    gesichert = set(ordner.glob("*.db"))
    caplog.clear()
    oidc_wanderung.laufen(engine)
    assert einstellung_holen("oeffentliche_adresse") == ADRESSE_021 + VORBAU
    assert set(ordner.glob("*.db")) == gesichert and "sub path" not in caplog.text


@pytest.mark.parametrize(
    ("gespeichert", "danach"),
    [
        ("", ""),
        (ADRESSE_021 + VORBAU, ADRESSE_021 + VORBAU),
        (ADRESSE_021 + VORBAU + "/", ADRESSE_021 + VORBAU + "/"),
        (ADRESSE_021 + "/", ADRESSE_021 + VORBAU),
    ],
)
def test_the_migration_adds_the_prefix_only_where_it_is_missing(betreiber, sso, unterpfad, gespeichert, danach):
    einstellung_setzen("oeffentliche_adresse", gespeichert)
    eintrag_wie_021("keycloak", sso.issuer, sso.client_id, sso.client_secret)
    oidc_wanderung.laufen(engine)
    assert einstellung_holen("oeffentliche_adresse") == danach


def test_without_a_sub_path_or_without_entries_from_0_21_the_address_is_left_alone(betreiber, sso, monkeypatch):
    einstellung_setzen("oeffentliche_adresse", ADRESSE_021)
    eintrag_wie_021("keycloak", sso.issuer, sso.client_id, sso.client_secret)
    oidc_wanderung.laufen(engine)
    assert einstellung_holen("oeffentliche_adresse") == ADRESSE_021, "ohne Unterpfad bleibt sie"
    monkeypatch.setenv("NEXMAIL_URL_BASE", VORBAU)
    get_settings.cache_clear()
    try:
        # Die Eintraege sind uebernommen; ein spaeterer Start (auch mit anderer Einstellung) fasst sie nicht an.
        oidc_wanderung.laufen(engine)
        assert einstellung_holen("oeffentliche_adresse") == ADRESSE_021
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_the_mail_account_return_address_does_not_double_the_prefix(unterpfad):
    """``mailoauth`` haengte den Vorbau schon in 0.21 an die gespeicherte Adresse; die Wanderung hat ihn nun dort
    hineingeschrieben. Die Rueckkehr-Adresse beim Postfach-Anbieter bleibt dieselbe."""
    from app.routers.mailoauth import _rueckkehr

    erwartet = f"{ADRESSE_021}{VORBAU}/api/mailoauth/google/zurueck"
    for gespeichert in (ADRESSE_021, ADRESSE_021 + VORBAU):
        einstellung_setzen("oeffentliche_adresse", gespeichert)
        with SessionLocal() as db:
            assert _rueckkehr(db, "google") == erwartet


def test_the_backup_report_names_the_redirect_address_with_the_prefix_once(unterpfad):
    from app.routers.sicherung import _befund_bauen

    roh = {
        "version": "0.21.0",
        "erstellt": "",
        "schluessel_dabei": False,
        "nachrichten_entfernt": 0,
        "adresse_im_archiv": "",
        "adresse_jetzt": ADRESSE_021 + VORBAU,
        "adresse_weicht_ab": False,
        "oidc_anbieter": [{"kuerzel": "keycloak", "anzeigename": "Keycloak", "issuer": "https://auth.example.com"}],
    }
    assert _befund_bauen(roh).oidc_anbieter[0].rueckkehr_adresse == f"{ADRESSE_021}{VORBAU}/api/oidc/keycloak/zurueck"
    roh["adresse_jetzt"] = ADRESSE_021
    assert _befund_bauen(roh).oidc_anbieter[0].rueckkehr_adresse == f"{ADRESSE_021}{VORBAU}/api/oidc/keycloak/zurueck"


def test_linking_under_a_sub_path_bounces_to_the_address_with_the_prefix(netz, unterpfad):
    """Das Sitzungs-Cookie ist ``strict``; beim Durchreichen muss die Adresse den Vorbau tragen, genau einmal: Der
    Browser loest die Weiterleitung selbst auf, der Proxy schneidet den Vorbau erst dahinter ab."""
    fake = netz.add(__import__("oidc_fakes").FakeProvider())
    with TestClient(BasisPfadMiddleware(app, VORBAU), base_url="http://testserver", follow_redirects=False) as c:
        eingerichtet = c.post(
            f"{VORBAU}/api/setup/konto", json={"benutzername": BETREIBER, "passwort": PASSWORT}
        )
        assert eingerichtet.status_code == 201, eingerichtet.text
        angelegt = c.post(
            f"{VORBAU}/api/oidc/admin/providers",
            json={
                "label": "SSO",
                "slug": "sso",
                "issuer": fake.issuer,
                "client_id": fake.client_id,
                "client_secret": fake.client_secret,
            },
        )
        assert angelegt.status_code == 201, angelegt.text
        url = c.post(f"{VORBAU}/api/oidc/sso/link", json={"password": PASSWORT}).json()["url"]
        rueckkehr = parse_qs(urlsplit(url).query)["redirect_uri"][0]
        assert rueckkehr == f"http://testserver{VORBAU}/api/oidc/sso/callback"
        zurueck = f"{urlsplit(rueckkehr).path}?{urlencode(fake.authorize(url))}"
        sitzung = c.cookies.get("nexmail_sitzung")
        c.cookies.delete("nexmail_sitzung")
        seite = c.get(zurueck, headers={"Sec-Fetch-Site": "cross-site"})
        assert seite.status_code == 200
        assert f'url={VORBAU}/api/oidc/sso/callback?' in seite.text and f"{VORBAU}{VORBAU}" not in seite.text
        c.cookies.set("nexmail_sitzung", sitzung, path=f"{VORBAU}/api")
        fertig = c.get(zurueck, headers={"Sec-Fetch-Site": "same-origin"})
        assert fertig.status_code == 303
        # (Die Seite danach steht beim Import der Anwendung fest, ohne Vorbau; hier zaehlt, dass verknuepft ist.)
        assert "/konto/sicherheit?linked=sso" in fertig.headers["location"], fertig.headers["location"]
    with SessionLocal() as db:
        assert db.scalar(select(OidcVerknuepfung.subject)) == "person-1"
