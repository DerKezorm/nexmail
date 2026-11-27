"""Die Wege des Gerätemoduls ``geraete`` 0.1.0 (``vendor/nexgeraete``): iPhone, iPad und Mac koppeln und verwalten.

* ``app_router`` (``/api/app/1``): Abholen mit QR-Code oder Code, weiteres Gerät über iCloud, Liste, Umbenennen,
  Trennen, Mitteilungen samt Arten je Gerät. nexmail hängt die Wege einzeln in seine Fläche (``routers/app1.py``,
  ``routers/app_kopplung.public_router``), die Wege der veröffentlichten App mit ihrer alten Antwortform in der
  Beschreibung; was die App ohne ``X-Nex-App`` schickt, beantwortet das Modul in nexmails alter Form (``mail``).
* ``browser_router`` (``/api``): ``/app-pairing``, ``/app-connect``, ``/app-devices``, ``/server/accounts/{id}/devices``
  (Betreiber); nur Browser-Sitzungen.

Uhr, Versand und der Haken nach dem Koppeln gehen über ``services/geraete_store`` (der Vertragsadapter ersetzt sie
dort).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.routing import APIRoute

from ..config import get_settings
from ..deps import angemeldet, nur_betreiber
from ..services import anmeldebremse
from ..services import geraete_store as gs
from ..vendor.nexgeraete import api
from ..vendor.nexkonten import brake


def _absender(request: Request) -> str:
    """Die Adresse des Anfragenden hinter nexmails Proxys (``NEXMAIL_CLIENT_IP``), sonst leer: dann ein Topf."""
    return anmeldebremse.adresse_von(request)


def _adresse(_request: Request) -> str:
    """⚠️ **Die Einstellung geht vor** (Verwaltung › öffentliche Adresse): wer nexmail im Heimnetz über eine
    IP-Adresse aufruft, will der App trotzdem die Adresse mitgeben, unter der es auch unterwegs erreichbar ist."""
    from ..db import SessionLocal, einstellung_lesen
    from ..services import adresse as adressdienst

    with SessionLocal() as db:
        gespeichert = einstellung_lesen(db, "oeffentliche_adresse")
    return adressdienst.fuer_modul(gespeichert, get_settings().url_base)


app_router = api.app_router(
    config=gs.KONFIGURATION,
    store=gs.store_der_anfrage,
    brake=brake.BRAKE,
    on_paired=lambda inhaber, geraet: gs.nach_kopplung(inhaber, geraet),
    send=lambda url, rumpf: gs.senden(url, rumpf),
    sender=_absender,
    clock=lambda: gs.jetzt(),
)

browser_router = api.browser_router(
    config=gs.KONFIGURATION,
    store=gs.store_der_anfrage,
    account=angemeldet,
    operator=nur_betreiber,
    account_id=lambda person: person.id,
    address=_adresse,
    send=lambda url, rumpf: gs.senden(url, rumpf),
    clock=lambda: gs.jetzt(),
)


def modulweg(pfad: str, methode: str) -> APIRoute:
    """Ein Weg des ``app_router`` (``pfad`` ohne ``/api/app/1``), um ihn in nexmails Fläche einzuhängen."""
    for route in app_router.routes:
        if isinstance(route, APIRoute) and route.path == f"/api/app/1{pfad}" and methode in route.methods:
            return route
    raise LookupError(f"{methode} {pfad} is no route of nexgeraete")


__all__ = ["app_router", "browser_router", "modulweg"]
