"""Der authentik-Knopf gegen ein nachgestelltes authentik (API v3), und der Blueprint.

Uebernommen aus nexbeat. Die Attrappe beantwortet die Aufrufe des Dienstes und
merkt sich jede Anfrage: So pruefen die Tests, dass das Token nur im
Authorization-Kopf reist, dass der Lauf beim ersten Fehler stehen bleibt und
dass ein vorhandener Provider aktualisiert statt verdoppelt wird. Kein Netz.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import httpx
import pytest

from app import crypto
from app.models import OidcAnbieter
from app.services import authentik_einrichtung
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

ADRESSE = "https://auth.example.com"
TOKEN = "einmal-token-das-nirgends-auftauchen-darf"
ISSUER = f"{ADRESSE}/application/o/nexmail/"
OEFFENTLICH = "https://mail.example"
RUECKKEHR = f"{OEFFENTLICH}/api/oidc/authentik/zurueck"

_ECHTER_KLIENT = httpx.AsyncClient


@dataclass
class Aufruf:
    methode: str
    pfad: str
    frage: dict[str, str]
    kopf: str
    rumpf: dict | None


@dataclass
class FalschesAuthentik:
    """authentik als MockTransport. ``vorhanden`` sagt, was es dort schon gibt."""

    vorhanden: set[str] = field(default_factory=set)
    scheitert: tuple[str, str, int] | None = None
    selbstauskunft_ok: bool = True
    #: Ein authentik, das den Filter ``name=`` uebergeht und fremde Provider mitliefert.
    filter_uebergangen: bool = False
    provider_rueckkehr: str = ""
    aufrufe: list[Aufruf] = field(default_factory=list)

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        if anfrage.url.host != "auth.example.com":
            raise httpx.ConnectError("no such host")
        methode, pfad = anfrage.method, anfrage.url.path
        frage = dict(anfrage.url.params.items())
        rumpf = json.loads(anfrage.content) if anfrage.content else None
        self.aufrufe.append(Aufruf(methode, pfad, frage, anfrage.headers.get("authorization", ""), rumpf))
        if self.scheitert and (methode, pfad) == self.scheitert[:2]:
            return httpx.Response(self.scheitert[2], text="<html>Fehlerseite mit eigenen Geheimnissen</html>")
        if pfad.endswith("/.well-known/openid-configuration"):
            if not self.selbstauskunft_ok:
                return httpx.Response(404, text="not found")
            aussteller = pfad.removesuffix(".well-known/openid-configuration")
            return httpx.Response(
                200,
                json={
                    "issuer": f"{ADRESSE}{aussteller}",
                    "authorization_endpoint": f"{ADRESSE}{aussteller}authorize/",
                    "token_endpoint": f"{ADRESSE}/application/o/token/",
                    "jwks_uri": f"{ADRESSE}{aussteller}jwks/",
                },
            )
        if not pfad.startswith("/api/v3/"):
            return httpx.Response(404)
        if anfrage.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(403, json={"detail": "Authentication credentials were not provided."})
        return self._api(methode, pfad[len("/api/v3") :], frage, rumpf)

    def _api(self, methode: str, pfad: str, frage: dict[str, str], rumpf: dict | None) -> httpx.Response:
        if (methode, pfad) == ("GET", "/admin/version/"):
            return httpx.Response(200, json={"version_current": "2026.8.1"})
        if (methode, pfad) == ("GET", "/crypto/certificatekeypairs/"):
            zeilen = [{"pk": "cert-uuid", "name": "nexmail"}] if "cert" in self.vorhanden else []
            return httpx.Response(200, json={"results": zeilen})
        if (methode, pfad) == ("POST", "/crypto/certificatekeypairs/generate/"):
            return httpx.Response(200, json={"pk": "cert-uuid", "name": rumpf["common_name"]})
        if (methode, pfad) == ("GET", "/propertymappings/provider/scope/"):
            zeilen = [
                {"pk": "map-openid", "managed": "goauthentik.io/providers/oauth2/scope-openid"},
                {"pk": "map-profile", "managed": "goauthentik.io/providers/oauth2/scope-profile"},
                {"pk": "map-email", "managed": "goauthentik.io/providers/oauth2/scope-email"},
            ]
            if "managed" in frage:
                zeilen = [z for z in zeilen if z["managed"] == frage["managed"]]
            return httpx.Response(200, json={"results": zeilen})
        if (methode, pfad) == ("GET", "/flows/instances/"):
            if frage.get("designation") == "authorization":
                zeilen = [
                    {"pk": "flow-explicit", "slug": "default-provider-authorization-explicit-consent"},
                    {"pk": "flow-implicit", "slug": "default-provider-authorization-implicit-consent"},
                ]
            else:
                zeilen = [{"pk": "flow-invalidation", "slug": "default-provider-invalidation-flow"}]
            return httpx.Response(200, json={"results": zeilen})
        if (methode, pfad) == ("GET", "/providers/oauth2/"):
            zeilen = [{"pk": 7, "name": "nexmail"}] if "provider" in self.vorhanden else []
            if zeilen and self.provider_rueckkehr:
                zeilen[0]["redirect_uris"] = [{"matching_mode": "strict", "url": self.provider_rueckkehr}]
            if self.filter_uebergangen:
                zeilen = [{"pk": 3, "name": "fremde-anwendung"}, *zeilen]
            elif "name" in frage:
                zeilen = [z for z in zeilen if z["name"] == frage["name"]]
            return httpx.Response(200, json={"results": zeilen})
        if (methode, pfad) == ("PATCH", "/providers/oauth2/3/"):
            return httpx.Response(200, json={**rumpf, "pk": 3, "client_id": "fremd", "client_secret": "fremd"})
        if (methode, pfad) in (("POST", "/providers/oauth2/"), ("PATCH", "/providers/oauth2/7/")):
            return httpx.Response(
                201 if methode == "POST" else 200,
                json={**rumpf, "pk": 7, "client_id": "erzeugte-client-id", "client_secret": "erzeugtes-geheimnis"},
            )
        if (methode, pfad) == ("GET", "/core/applications/"):
            zeilen = [{"pk": "app-uuid", "slug": "nexmail"}] if "anwendung" in self.vorhanden else []
            if "slug" in frage:
                zeilen = [z for z in zeilen if z["slug"] == frage["slug"]]
            return httpx.Response(200, json={"results": zeilen})
        if methode in ("POST", "PATCH") and pfad.startswith("/core/applications/"):
            return httpx.Response(201 if methode == "POST" else 200, json={**rumpf, "pk": "app-uuid"})
        return httpx.Response(404, json={"detail": f"no fake answer for {methode} {pfad}"})


@pytest.fixture
def falsch(monkeypatch):
    server = FalschesAuthentik()
    transport = httpx.MockTransport(server)
    monkeypatch.setattr(authentik_einrichtung, "transport_fuer_tests", transport)

    # Die Selbstauskunft holt ``services/oidc`` mit einem eigenen Klienten;
    # auch der bekommt die Attrappe.
    def gebaut(*args, **kwargs):
        kwargs["transport"] = transport
        return _ECHTER_KLIENT(*args, **kwargs)

    from app.services import oidc

    monkeypatch.setattr(oidc.httpx, "AsyncClient", gebaut)
    yield server


@pytest.fixture
def betreiber(klient):
    from app.db import SessionLocal, einstellung_schreiben

    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", OEFFENTLICH)
    return klient


def _lauf(klient, adresse: str = ADRESSE, token: str = TOKEN) -> dict:
    antwort = klient.post("/api/oidc/authentik/einrichten", json={"adresse": adresse, "token": token})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _schritte(ergebnis: dict) -> list[tuple[str, bool]]:
    return [(s["kennung"], s["ok"]) for s in ergebnis["schritte"]]


def _gespeichert(db) -> OidcAnbieter | None:
    db.expire_all()
    return db.query(OidcAnbieter).filter(OidcAnbieter.kuerzel == "authentik").one_or_none()


def test_der_knopf_legt_alles_an_und_traegt_den_anbieter_ein(betreiber, falsch, db):
    ergebnis = _lauf(betreiber)
    assert ergebnis["ok"] is True
    assert _schritte(ergebnis) == [(k, True) for k in authentik_einrichtung.SCHRITTE]
    assert ergebnis["client_id"] == "erzeugte-client-id" and ergebnis["issuer"] == ISSUER
    assert "2026.8.1" in ergebnis["schritte"][0]["text"]

    zeile = _gespeichert(db)
    assert zeile is not None
    assert zeile.issuer == ISSUER.rstrip("/") and zeile.client_id == "erzeugte-client-id" and zeile.aktiv
    # Verschluesselt, und unter dem Kontext, mit dem der Rueckweg es liest.
    assert "erzeugtes-geheimnis" not in zeile.client_secret
    assert crypto.entschluesseln(zeile.client_secret, f"oidc:{zeile.id}:geheimnis") == "erzeugtes-geheimnis"
    # Die Anmeldeseite bietet ihn an, und die Rueckkehr-Adresse stimmt.
    assert {"kuerzel": "authentik", "anzeigename": "authentik"} in betreiber.get("/api/oidc/knoepfe").json()
    assert betreiber.get("/api/oidc/anbieter").json()[0]["rueckkehr_adresse"] == RUECKKEHR

    angelegt = [a for a in falsch.aufrufe if (a.methode, a.pfad) == ("POST", "/api/v3/providers/oauth2/")]
    assert len(angelegt) == 1
    gesendet = angelegt[0].rumpf
    assert gesendet["name"] == "nexmail" and gesendet["client_type"] == "confidential"
    # ⚠️ authentik 2026.8 lehnt jede Anmeldung ab, deren Ablauf nicht am Provider steht.
    assert gesendet["grant_types"] == ["authorization_code"]
    assert gesendet["redirect_uris"] == [{"matching_mode": "strict", "url": RUECKKEHR}]
    # ⚠️ Ohne Schluessel unterschriebe authentik mit HS256.
    assert gesendet["signing_key"] == "cert-uuid" and gesendet["sub_mode"] == "user_uuid"
    assert gesendet["authorization_flow"] == "flow-implicit"
    assert gesendet["invalidation_flow"] == "flow-invalidation"
    assert sorted(gesendet["property_mappings"]) == ["map-email", "map-openid", "map-profile"]


def test_das_token_reist_nur_im_kopf(betreiber, falsch, db, caplog):
    caplog.set_level(logging.DEBUG)
    ergebnis = _lauf(betreiber)
    for aufruf in falsch.aufrufe:
        if aufruf.pfad.startswith("/api/v3/"):
            assert aufruf.kopf == f"Bearer {TOKEN}"
        assert TOKEN not in json.dumps(aufruf.rumpf or {}) and TOKEN not in json.dumps(aufruf.frage)
    assert TOKEN not in json.dumps(ergebnis)
    assert TOKEN not in caplog.text
    for zeile in db.query(OidcAnbieter).all():
        assert TOKEN not in (zeile.client_secret + zeile.client_id + zeile.issuer)


def test_ein_zweiter_druck_aktualisiert_statt_zu_verdoppeln(betreiber, falsch, db):
    _lauf(betreiber)
    falsch.vorhanden |= {"cert", "provider", "anwendung"}
    falsch.aufrufe.clear()
    ergebnis = _lauf(betreiber)
    assert ergebnis["ok"] is True
    wege = {(a.methode, a.pfad) for a in falsch.aufrufe}
    assert ("PATCH", "/api/v3/providers/oauth2/7/") in wege
    assert ("PATCH", "/api/v3/core/applications/nexmail/") in wege
    assert not any(m == "POST" for m, _ in wege), wege
    assert db.query(OidcAnbieter).count() == 1


def test_der_erste_fehlschlag_haelt_an_und_nennt_den_status_nicht_die_antwort(betreiber, falsch, db):
    falsch.scheitert = ("POST", "/api/v3/providers/oauth2/", 403)
    ergebnis = _lauf(betreiber)
    assert ergebnis["ok"] is False
    assert _schritte(ergebnis) == [
        ("erreicht", True),
        ("schluessel", True),
        ("zuordnungen", True),
        ("provider", False),
    ]
    text = ergebnis["schritte"][-1]["text"]
    assert "403" in text and "may not" in text
    assert "Geheimnissen" not in text, "der Rumpf einer fremden Antwort gehoert nicht in den Browser"
    assert _gespeichert(db) is None


def test_ein_falsches_token_haelt_beim_ersten_schritt(betreiber, falsch, db):
    ergebnis = _lauf(betreiber, token="nicht-das-token")
    assert _schritte(ergebnis) == [("erreicht", False)]
    assert _gespeichert(db) is None


def test_ein_unerreichbares_authentik_wird_benannt(betreiber, falsch):
    ergebnis = _lauf(betreiber, adresse="https://nirgends.example.com")
    assert _schritte(ergebnis) == [("erreicht", False)]
    assert "not reachable" in ergebnis["schritte"][0]["text"]


def test_ein_zweites_nexmail_nimmt_dem_ersten_den_provider_nicht_weg(betreiber, falsch):
    falsch.vorhanden |= {"provider"}
    falsch.provider_rueckkehr = "https://mail.anderswo.example/api/oidc/authentik/zurueck"
    ergebnis = _lauf(betreiber)
    assert ergebnis["ok"] is True
    assert ergebnis["issuer"] == f"{ADRESSE}/application/o/nexmail-mail-example/"
    angelegt = [a for a in falsch.aufrufe if (a.methode, a.pfad) == ("POST", "/api/v3/providers/oauth2/")]
    assert angelegt and angelegt[0].rumpf["name"] == "nexmail (mail.example)"
    assert not any(a.methode == "PATCH" for a in falsch.aufrufe)


def test_ein_uebergangener_filter_ueberschreibt_keinen_fremden_provider(betreiber, falsch):
    """⚠️ Liefert authentik trotz ``name=`` die ganze Liste, darf der erste
    Eintrag nicht als „unserer" gelten; sonst baut der Knopf die Anwendung
    eines anderen um."""
    falsch.filter_uebergangen = True
    assert _lauf(betreiber)["ok"] is True
    wege = {(a.methode, a.pfad) for a in falsch.aufrufe}
    assert ("PATCH", "/api/v3/providers/oauth2/3/") not in wege
    assert ("POST", "/api/v3/providers/oauth2/") in wege


def test_eine_gescheiterte_selbstauskunft_behaelt_was_authentik_ausgab(betreiber, falsch, db):
    falsch.selbstauskunft_ok = False
    ergebnis = _lauf(betreiber)
    assert _schritte(ergebnis)[-1] == ("eingetragen", False)
    assert "discovery" in ergebnis["schritte"][-1]["text"]
    zeile = _gespeichert(db)
    assert zeile is not None and zeile.client_id == "erzeugte-client-id"


def test_ein_vorhandener_anbieter_authentik_wird_aktualisiert(betreiber, falsch, db):
    angelegt = betreiber.post(
        "/api/oidc/anbieter",
        json={
            "kuerzel": "authentik",
            "anzeigename": "Mein authentik",
            "issuer": "https://alt.example/application/o/post",
            "client_id": "alt",
            "client_secret": "alt-geheim",
            "aktiv": False,
        },
    )
    assert angelegt.status_code == 201, angelegt.text
    assert _lauf(betreiber)["ok"] is True
    zeile = _gespeichert(db)
    assert db.query(OidcAnbieter).count() == 1
    assert zeile.issuer == ISSUER.rstrip("/") and zeile.client_id == "erzeugte-client-id" and zeile.aktiv
    # Der Name auf dem Knopf gehoert dem Betreiber.
    assert zeile.anzeigename == "Mein authentik"


def test_nur_der_betreiber_darf_druecken(betreiber, zweiter_klient, falsch, db):
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    abgewiesen = zweiter_klient.post(
        "/api/oidc/authentik/einrichten", json={"adresse": ADRESSE, "token": TOKEN}
    )
    assert abgewiesen.status_code == 403
    assert zweiter_klient.get("/api/oidc/authentik/blueprint").status_code == 403
    assert falsch.aufrufe == []


def test_ohne_oeffentliche_adresse_geht_nichts_hinaus(klient, falsch):
    einrichten(klient)
    abgewiesen = klient.post("/api/oidc/authentik/einrichten", json={"adresse": ADRESSE, "token": TOKEN})
    assert abgewiesen.status_code == 400 and abgewiesen.json()["detail"] == "oidc_keine_adresse"
    assert klient.get("/api/oidc/authentik/blueprint").json()["detail"] == "oidc_keine_adresse"
    assert falsch.aufrufe == []


def test_eine_adresse_ohne_schema_wird_abgewiesen(betreiber, falsch):
    abgewiesen = betreiber.post(
        "/api/oidc/authentik/einrichten", json={"adresse": "auth.example.com", "token": TOKEN}
    )
    assert abgewiesen.status_code == 400 and abgewiesen.json()["detail"] == "anbieter_adresse_ohne_schema"
    assert falsch.aufrufe == []


def test_der_blueprint_beschreibt_dieselben_dinge(betreiber):
    antwort = betreiber.get("/api/oidc/authentik/blueprint")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["dateiname"] == "nexmail-authentik.yaml"
    text = daten["inhalt"]
    modelle = [z.split(":", 1)[1].strip() for z in text.splitlines() if z.strip().startswith("- model:")]
    assert modelle == ["authentik_providers_oauth2.oauth2provider", "authentik_core.application"]
    assert "        - authorization_code" in text
    assert f"          url: {json.dumps(RUECKKEHR)}" in text
    for verwaltet in authentik_einrichtung.VERWALTETE_ZUORDNUNGEN:
        assert f"[managed, {verwaltet}]" in text
    assert "signing_key: !Find" in text
    assert "nexbeat" not in text and "nexdeck" not in text
