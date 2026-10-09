"""Entra ID mit ``common``, und ein Ausweis mit dem Client-Geheimnis.

⚠️ **Gefunden am 09.10.2026 in nexbeat**, nachgezogen in nexmail. Mit
``common`` oder ``organizations`` nennt Entras Selbstauskunft
``https://login.microsoftonline.com/{tenantid}/v2.0``; nexmail wies das schon
beim Vergleich mit der eingetragenen Adresse ab, also kam niemand herein.

Echte RS256-Unterschriften wie in ``test_oidc.py``; nur die Adressen und
``tid`` sind die von Entra.
"""

from __future__ import annotations

import pytest

from app.models import Benutzer, OidcVerknuepfung
from app.services import anmeldebremse, oidc
from conftest import einrichten
from oidc_attrappe import CLIENT_ID, Attrappe, einspannen

BASIS = "https://login.example"
EINGETRAGEN = f"{BASIS}/common/v2.0"
VORLAGE = f"{BASIS}/{{tenantid}}/v2.0"
#: ⚠️ Aus gleichen Ziffern: Der Scanner im pre-push-Hook haelt aufsteigende
#: Ziffernfolgen fuer Testpasswoerter.
MANDANT = "99999999-9999-4999-8999-999999999999"
ANDERER = "88888888-8888-4888-8888-888888888888"


@pytest.fixture(autouse=True)
def freie_bremse():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def entra_da(klient):
    from app.db import SessionLocal, einstellung_schreiben

    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")
    antwort = klient.post(
        "/api/oidc/anbieter",
        json={
            "kuerzel": "entra",
            "anzeigename": "Microsoft",
            "issuer": EINGETRAGEN,
            "client_id": CLIENT_ID,
            "client_secret": "geheim",
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _entra(**anders) -> Attrappe:
    """Ein Anbieter wie Entra mit ``common``: Vorlage in der Selbstauskunft, Mandant im Ausweis."""
    werte = {
        "issuer": EINGETRAGEN,
        "falscher_aussteller": VORLAGE,
        "aussteller_im_ausweis": f"{BASIS}/{MANDANT}/v2.0",
        "tid": MANDANT,
        # Entra schickt ohne optionalen Claim keine Adresse und nie email_verified.
        "email": None,
        "email_bestaetigt": None,
    }
    werte.update(anders)
    return Attrappe(**werte)


def _lauf(klient, attrappe, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    einspannen(monkeypatch, attrappe)
    hin = klient.get("/api/oidc/entra/start", follow_redirects=False)
    assert hin.status_code == 303
    if "oidc_fehler" in hin.headers["location"]:
        return hin
    frage = parse_qs(urlparse(hin.headers["location"]).query)
    attrappe._nonce = frage["nonce"][0]
    return klient.get(
        f"/api/oidc/entra/zurueck?code=abc&state={frage['state'][0]}", follow_redirects=False
    )


def test_common_kommt_herein_und_verknuepft_den_echten_mandanten(klient, entra_da, monkeypatch, db):
    antwort = _lauf(klient, _entra(), monkeypatch)

    assert antwort.headers["location"].endswith("oidc=verknuepft"), antwort.headers["location"]
    verknuepfung = db.query(OidcVerknuepfung).one()
    # ⚠️ Nie der Platzhalter: Eine Verknuepfung darauf galte fuer jeden Mandanten.
    assert verknuepfung.issuer == f"{BASIS}/{MANDANT}/v2.0"

    # Das Profil findet den Anbieter trotz ``common`` in seiner Adresse.
    meine = klient.get("/api/oidc/meine").json()
    assert meine[0]["kuerzel"] == "entra"
    assert meine[0]["anzeigename"] == "Microsoft"

    # Und danach meldet derselbe Mensch sich an.
    klient.cookies.clear()
    antwort = _lauf(klient, _entra(), monkeypatch)
    assert "oidc_fehler" not in antwort.headers["location"], antwort.headers["location"]
    assert klient.get("/api/auth/ich").json()["benutzername"] == "betreiber"


def test_derselbe_mensch_aus_einem_anderen_mandanten_ist_ein_anderer(klient, entra_da, monkeypatch, db):
    """⚠️ Ein ``sub`` gilt nur bei dem, der es vergeben hat."""
    _lauf(klient, _entra(), monkeypatch)
    klient.cookies.clear()

    fremd = _entra(aussteller_im_ausweis=f"{BASIS}/{ANDERER}/v2.0", tid=ANDERER)
    antwort = _lauf(klient, fremd, monkeypatch)
    assert "oidc_kein_konto" in antwort.headers["location"]
    assert klient.get("/api/auth/ich").status_code == 401


def test_ein_ausweis_eines_fremden_mandanten_wird_abgewiesen(klient, entra_da, monkeypatch, db):
    """``iss`` und ``tid`` muessen zusammenpassen."""
    klient.cookies.clear()
    antwort = _lauf(klient, _entra(tid=ANDERER), monkeypatch)
    assert "oidc_ausweis" in antwort.headers["location"]
    assert db.query(OidcVerknuepfung).count() == 0


@pytest.mark.parametrize("tid", [None, "", "keine-kennung", "{tenantid}", MANDANT])
def test_der_platzhalter_gilt_nie_als_aussteller(klient, entra_da, monkeypatch, db, tid):
    """Wer ``{tenantid}`` wörtlich in den Ausweis schreibt, kommt nicht herein.

    ⚠️ **Auch mit gueltigem ``tid``.** Ohne diesen Fall lief die Mutation
    „Platzhalter zusaetzlich zugelassen" durch, weil ein ungueltiges ``tid``
    schon vorher abweist.
    """
    klient.cookies.clear()
    antwort = _lauf(klient, _entra(aussteller_im_ausweis=VORLAGE, tid=tid), monkeypatch)
    assert "oidc_ausweis" in antwort.headers["location"]
    assert db.query(OidcVerknuepfung).count() == 0


def test_eine_vorlage_auf_einem_fremden_rechner_passt_nicht(klient, entra_da, monkeypatch):
    klient.cookies.clear()
    antwort = _lauf(klient, _entra(falscher_aussteller="https://boese.example/{tenantid}/v2.0"), monkeypatch)
    assert "oidc_falscher_aussteller" in antwort.headers["location"]


def test_eine_einladung_geht_auch_ueber_entra(klient, entra_da, monkeypatch, db):
    """Ohne ``email`` und ohne ``email_verified``, wie Entra ab Werk."""
    from urllib.parse import parse_qs, urlparse

    from app.services import einladung as einladungsdienst

    _, schluessel = einladungsdienst.aussprechen(db, benutzername="anna", adresse="anna@example.com")
    klient.cookies.clear()
    attrappe = _entra()
    einspannen(monkeypatch, attrappe)
    ziel = klient.post("/api/oidc/entra/einladung", json={"schluessel": schluessel}).json()["ziel"]
    frage = parse_qs(urlparse(ziel).query)
    attrappe._nonce = frage["nonce"][0]
    antwort = klient.get(f"/api/oidc/entra/zurueck?code=abc&state={frage['state'][0]}", follow_redirects=False)

    assert "oidc_fehler" not in antwort.headers["location"], antwort.headers["location"]
    anna = db.query(Benutzer).filter(Benutzer.benutzername == "anna").one()
    assert db.query(OidcVerknuepfung).filter(OidcVerknuepfung.benutzer_id == anna.id).one().issuer == (
        f"{BASIS}/{MANDANT}/v2.0"
    )


# --- Die Regeln einzeln ---------------------------------------------------- #


@pytest.mark.parametrize(
    "eingetragen,gemeldet,passt",
    [
        ("https://a.example/x", "https://a.example/x/", True),
        (EINGETRAGEN, VORLAGE, True),
        (f"{BASIS}/organizations/v2.0", VORLAGE, True),
        (f"{BASIS}/consumers/v2.0", VORLAGE, True),
        (f"{BASIS}/{MANDANT}/v2.0", VORLAGE, True),
        (f"{BASIS}/irgendwas/v2.0", VORLAGE, False),
        (f"{BASIS}/common/v1.0", VORLAGE, False),
        ("https://boese.example/common/v2.0", VORLAGE, False),
        (f"{BASIS}/common/extra/v2.0", VORLAGE, False),
        (EINGETRAGEN, "", False),
        (EINGETRAGEN, f"{BASIS}/{{tenantid}}/{{tenantid}}/v2.0", False),
    ],
)
def test_aussteller_passt_zur_vorlage(eingetragen, gemeldet, passt):
    assert oidc.aussteller_passt_zur_vorlage(eingetragen, gemeldet) is passt


@pytest.mark.parametrize(
    "anbieter,verknuepft,gehoert",
    [
        ("https://a.example/x", "https://a.example/x/", True),
        (EINGETRAGEN, f"{BASIS}/{MANDANT}/v2.0", True),
        (f"{BASIS}/organizations/v2.0", f"{BASIS}/{MANDANT}/v2.0", True),
        (EINGETRAGEN, f"{BASIS}/irgendwas/v2.0", False),
        (EINGETRAGEN, f"https://boese.example/{MANDANT}/v2.0", False),
        (f"{BASIS}/{ANDERER}/v2.0", f"{BASIS}/{MANDANT}/v2.0", False),
    ],
)
def test_gehoert_zum_anbieter(anbieter, verknuepft, gehoert):
    assert oidc.gehoert_zum_anbieter(anbieter, verknuepft) is gehoert


# --- HS256 beim Namen nennen ---------------------------------------------- #


def test_ein_ausweis_mit_dem_client_geheimnis_wird_benannt(klient, entra_da, monkeypatch, db):
    """authentik ohne Signierschluessel: HS256 und eine leere Schluesselliste.

    ⚠️ Angenommen wird er nie; die Meldung sagt nur, wo man suchen muss.
    """
    import jwt as pyjwt

    attrappe = Attrappe(issuer=EINGETRAGEN, alg_verwechslung=True)
    einspannen(monkeypatch, attrappe)

    class LeereListe:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_signing_key_from_jwt(self, token: str):
            raise pyjwt.PyJWKClientError("The JWKS endpoint did not contain any signing keys")

    monkeypatch.setattr(oidc.jwt, "PyJWKClient", LeereListe)

    from urllib.parse import parse_qs, urlparse

    klient.cookies.clear()
    hin = klient.get("/api/oidc/entra/start", follow_redirects=False)
    frage = parse_qs(urlparse(hin.headers["location"]).query)
    attrappe._nonce = frage["nonce"][0]
    antwort = klient.get(f"/api/oidc/entra/zurueck?code=abc&state={frage['state'][0]}", follow_redirects=False)

    assert "oidc_ausweis_hs256" in antwort.headers["location"]
    assert klient.get("/api/auth/ich").status_code == 401
