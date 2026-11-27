"""Eine Verbindung mit nexfolk öffnet nur ``mails.about`` (verbinden 0.1.13).

nexmail gewährt seit 0.1.13 erstmals einen Zweck, und der hat die Stufe „read“. Ein Token dieser Verbindung darf
deshalb nichts öffnen als ``GET /api/connect/about/mails.about`` (und ``hello`` des Moduls): keine Mails, Ordner,
Postfächer, Kontakte, nicht über ``/api/v1``, ``/api/app/1``, MCP oder sonst einen Weg. Geprüft wird jeder GET-Weg der
App mit und ohne das Token: Was ohne Token zu ist, bleibt mit ihm zu.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.db import einstellung_schreiben
from app.main import app
from app.models import Konto, Nachricht, Ordner, neue_id
from app.services import apischluessel as apidienst, benutzer as benutzerdienst
from app.services.verbinden_store import store_fuer
from app.vendor import nexverbinden
from app.vendor.nexverbinden.shared import oauthcore

PAT = "pat@example.com"
#: Was die Verbindung öffnen darf (der Weg des Zwecks und die Probe des Moduls).
ERLAUBT = {"/api/connect/about/{purpose}", "/api/connect/hello"}


def _verbindung(db) -> tuple[str, str]:
    """Konto mit einem Postfach und einer Mail von Pat, die API-Schlüssel an, eine Verbindung mit nexfolk, die nur
    ``mails.about`` gewährt. Das Token dieser Verbindung."""
    person = benutzerdienst.anlegen(db, "betreiber", "sehr-geheim-123")
    konto = Konto(
        id=neue_id(), benutzer_id=person.id, anzeigename="Privat", adresse="privat@example.org",
        imap_server="imap.example.org", imap_benutzer="p", smtp_server="smtp.example.org", smtp_benutzer="p",
    )  # fmt: skip
    db.add(konto)
    db.flush()
    ordner = Ordner(konto_id=konto.id, pfad="INBOX", name="INBOX", rolle="posteingang")
    db.add(ordner)
    db.flush()
    db.add(
        Nachricht(
            benutzer_id=person.id, konto_id=konto.id, ordner_id=ordner.id, uid=1, message_id="<a@example.org>",
            von_adresse=PAT, an_json=json.dumps([{"n": "", "a": konto.adresse}]), betreff="Geheim",
        )
    )  # fmt: skip
    einstellung_schreiben(db, apidienst.SCHALTER, "1")
    token = "nxv_" + secrets.token_urlsafe(32)
    jetzt = datetime.now(UTC)
    store = store_fuer(db)
    store.save(
        nexverbinden.Connection(
            id=neue_id(), account_id=person.id, partner="nexfolk", partner_base="https://folk.example.com",
            partner_account="kim", uses=("contacts.read",), grants=("mails.about",), areas_granted=None,
            areas_used=None, held="", issued_access_hash=oauthcore.digest(token), issued_refresh_hash="x",
            issued_access_expires=jetzt + timedelta(hours=1), created_at=jetzt, used_at=jetzt,
        )
    )  # fmt: skip
    store.commit()
    return token, konto.id


def _get_wege() -> list[str]:
    wege = []
    for route in app.routes:
        if isinstance(route, APIRoute) and "GET" in route.methods and route.path.startswith("/api/"):
            wege.append(route.path)
    return sorted(set(wege))


def test_das_token_oeffnet_nur_den_weg_des_zwecks(db):
    token, _konto = _verbindung(db)
    mit = {"Authorization": f"Bearer {token}"}
    with TestClient(app, base_url="https://mail.example.com") as programm:
        # Der Weg des Zwecks antwortet, mit der Mail von Pat.
        gefunden = programm.get("/api/connect/about/mails.about", params={"mail": PAT}, headers=mit)
        assert gefunden.status_code == 200, gefunden.text
        assert gefunden.json()["count"] == 1
        geoeffnet = []
        wege = _get_wege()
        assert len(wege) > 100, len(wege)  # Bodenschwelle: wirklich alle GET-Wege der App, nicht eine leere Liste
        for weg in wege:
            if weg in ERLAUBT:
                continue
            pfad = re.sub(r"\{[^}]+\}", "1", weg)
            ohne = programm.get(pfad).status_code
            mit_token = programm.get(pfad, headers=mit)
            # Zu heißt 401 oder 403; kommt das Token an der Tür vorbei (auch zu einem 404 oder 422 dahinter), ist sie
            # offen.
            if ohne in (401, 403) and mit_token.status_code not in (401, 403):
                geoeffnet.append(f"{weg}: {mit_token.status_code} (ohne Token {ohne})")
            elif 200 <= mit_token.status_code < 300 and not 200 <= ohne < 300:
                geoeffnet.append(f"{weg}: {mit_token.status_code} (ohne Token {ohne})")
        assert geoeffnet == [], "Das Token einer Verbindung öffnet:\n  " + "\n  ".join(geoeffnet)
        # Die Lesewege für Programme ausdrücklich: zu, mit dem Token wie ohne.
        lesewege = ("/api/v1/me", "/api/v1/summary", "/api/v1/messages/latest", "/api/v1/tags", "/api/app/1/me",
                    "/api/app/1/accounts", "/api/app/1/messages", "/api/nachrichten")  # fmt: skip
        for pfad in lesewege:
            antwort = programm.get(pfad, headers=mit)
            assert antwort.status_code in (401, 403), (pfad, antwort.status_code, antwort.text)
        # Ein anderer Zweck über den Weg der Personen: 404 (nexmail kennt ihn nicht) oder 403, nie eine Antwort.
        anderer = programm.get("/api/connect/about/contacts.read", params={"mail": PAT}, headers=mit)
        assert anderer.status_code in (403, 404)


def test_ohne_den_zweck_auch_der_weg_der_personen_nicht(db):
    """Eine Verbindung, der ``mails.about`` fehlt, bekommt 403 ``purpose_missing``."""
    from dataclasses import replace

    token, _konto = _verbindung(db)
    store = store_fuer(db)
    verbindung = store.connections(store.by_issued_access(oauthcore.digest(token)).account_id)[0]
    store.save(replace(verbindung, grants=()))
    store.commit()
    with TestClient(app, base_url="https://mail.example.com") as programm:
        antwort = programm.get(
            "/api/connect/about/mails.about", params={"mail": PAT}, headers={"Authorization": f"Bearer {token}"}
        )
    assert antwort.status_code == 403
    assert antwort.json()["detail"]["code"] == "purpose_missing"
