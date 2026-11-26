"""Server › Anmeldung: die Schalter und „Bereit fürs Internet?" (Kontenmodul 1.1.0, ``signin`` und ``readiness``).

``GET  /api/server/sign-in``            die Schalter (``signin.view``) und die öffentliche Adresse
``PUT  /api/server/sign-in``            ändern mit den Regeln des Moduls: „Anmeldung mit Passwort" aus nur mit einem
                                        aktiven Anbieter, „Zweiten Faktor für alle verlangen" an erst mit eigenem
                                        Faktor, aus nur mit dem eigenen Passwort
``GET  /api/server/sign-in/readiness``  „Bereit fürs Internet?", bei jedem Öffnen der Seite neu geprüft

Der alte Weg ``/api/oidc/admin/anmeldung`` bleibt (``routers/oidc.py``) und geht seit 1.1.0 durch dieselben Regeln.
Nur für Betreiber.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import AktiveSitzung, Betreiber, DbSession
from ..services import kontenpost
from ..services import konten_store as kontenstore
from ..services.oidc_store import SqlStore
from ..vendor import nexkonten

router = APIRouter(prefix="/api/server/sign-in", tags=["anmeldung"])


class AnmeldungAendern(BaseModel):
    password_login: bool | None = None
    factor_required: bool | None = None
    passkeys_allowed: bool | None = None
    #: Das eigene Passwort, wenn „Zweiten Faktor für alle" abgeschaltet wird.
    password: str = Field(default="", max_length=300)


def _anbieter_geprueft(sitzung) -> bool:
    """Ob die Sitzung von einem Anbieter kommt, der den zweiten Faktor selbst prüft (``sitzung.anbieter_geprueft``)."""
    return bool(getattr(sitzung, "anbieter_geprueft", False))


def ansicht(db, ich, sitzung) -> dict[str, Any]:
    store = kontenstore.store_fuer(db)
    return {
        **nexkonten.signin.view(store, ich.id, provider_checked=_anbieter_geprueft(sitzung)),
        "public_url": kontenpost.oeffentliche_adresse(db),
    }


@router.get("", summary="The switches of the page Server, Sign-in")
def lesen(ich: Betreiber, sitzung: AktiveSitzung, db: DbSession) -> dict[str, Any]:
    return ansicht(db, ich, sitzung)


@router.put("", summary="Change the switches of the page Server, Sign-in, with the module's rules")
def aendern(eingabe: AnmeldungAendern, ich: Betreiber, sitzung: AktiveSitzung, db: DbSession) -> dict[str, Any]:
    from .auth import _bestaetigt

    store = kontenstore.store_fuer(db)
    try:
        nexkonten.signin.change(
            store,
            ich.id,
            password_login=eingabe.password_login,
            factor_required=eingabe.factor_required,
            passkeys_allowed=eingabe.passkeys_allowed,
            password=eingabe.password,
            actor_confirmed=_bestaetigt(ich, sitzung),
            provider_checked=_anbieter_geprueft(sitzung),
        )
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    return ansicht(db, ich, sitzung)


def _vertraute(request: Request) -> list[str]:
    """nexmail kennt keine Liste vertrauter Netze: ``NEXMAIL_CLIENT_IP=proxy[:n]`` vertraut dem, der verbindet."""
    if get_settings().anzahl_proxys() <= 0 or request.client is None:
        return []
    try:
        adresse = ipaddress.ip_address(request.client.host)
    except ValueError:
        return []
    return [f"{adresse}/{adresse.max_prefixlen}"]


@router.get("/readiness", summary="Ready for the internet? Checked anew each time the page opens")
def bereit(request: Request, ich: Betreiber, db: DbSession) -> dict[str, Any]:
    store = kontenstore.store_fuer(db)
    einstellungen = store.sign_in_settings()
    pruefende = [
        entry.label for entry in SqlStore(db).list_providers() if entry.enabled and entry.trusts_second_factor
    ]
    return nexkonten.readiness.check(
        public_url=kontenpost.oeffentliche_adresse(db),
        request_https=request.url.scheme == "https",
        factor_required=einstellungen.factor_required,
        own_factor=nexkonten.signin.has_own_factor(store, ich.id),
        trusted_proxies=_vertraute(request),
        peer=request.client.host if request.client else "",
        forwarded="x-forwarded-for" in request.headers,
        cookie_secure=get_settings().cookie_secure,
        providers_checking=pruefende if einstellungen.factor_required else [],
        proxies_variable="NEXMAIL_CLIENT_IP",
        cookie_variable="NEXMAIL_COOKIE_SECURE",
    ).as_dict()
