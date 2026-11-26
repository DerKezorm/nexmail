"""Die alten Wege der Über-Seite (``/api/ueber``): dünne Hülle über dem Modul updates 0.1.1 (U16, E53).

Die Seite selbst nutzt seit dem Durchgang „Module“ die Wege des Moduls unter ``/api/about``. Diese hier bleiben mit
ihrer Form, ihren deutschen Feldern, Namen und Statuscodes für alles, was sie noch ruft: lesen jedes angemeldete Konto,
schalten und von Hand nachsehen nur der Betreiber, ohne Anmeldung 401.

⚠️ **Ein Mitglied erfährt nichts über die Prüfung** (U2, U15): Fassung, Lizenz und Quelltext bekommt es wie bisher,
die Felder zum Stand und der Schalter sind für es leer in ihren alten Typen (``update_pruefen`` false), und sein
Aufruf fragt nie hinaus. Nur der Blick eines Betreibers fragt (wenn der Stand einen Tag alt ist und der Schalter an).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__
from ..deps import AngemeldeterBenutzer, Betreiber
from ..services import aktualisierung
from ..vendor import nexupdates
from ..vendor.nexupdates import api as nexupdates_api

router = APIRouter(prefix="/api/ueber", tags=["ueber"])

SCHLUESSEL_UPDATE_PRUEFEN = aktualisierung.SCHLUESSEL_UPDATE_PRUEFEN


class Auskunft(BaseModel):
    version: str
    repo_adresse: str
    release_adresse: str
    projektseite: str
    lizenz: str = "AGPL-3.0"

    update_pruefen: bool
    geprueft: bool = False
    neueste: str | None = None
    neuer_da: bool = False
    geprueft_am: datetime | None = None


class Schalter(BaseModel):
    update_pruefen: bool


def _auskunft(pruefen: bool, stand: nexupdates.State | None) -> Auskunft:
    """Die alte Form; der Stand so, wie das Modul ihn zeigt (nur ein Tag der festen Form zählt)."""
    gesehen = nexupdates_api.view(stand, pruefen) if stand is not None else None
    return Auskunft(
        version=__version__,
        repo_adresse=aktualisierung.REPO_URL,
        release_adresse=aktualisierung.RELEASES_URL,
        projektseite=aktualisierung.PROJEKTSEITE,
        update_pruefen=pruefen,
        geprueft=bool(gesehen and gesehen["checked"]),
        neueste=gesehen["latest"] if gesehen else None,
        neuer_da=bool(gesehen and gesehen["newer"]),
        geprueft_am=gesehen["checked_at"] if gesehen else None,
    )


@router.get("", response_model=Auskunft)
def ueber(person: AngemeldeterBenutzer) -> Auskunft:
    if not person.ist_betreiber:
        # U15: dieselbe Form, aber nichts über die Prüfung und nie eine Frage.
        return _auskunft(False, None)
    an = nexupdates.switch_on()
    return _auskunft(an, nexupdates.state(on=an))


@router.post("/pruefen", response_model=Auskunft)
def jetzt_pruefen(_: Betreiber) -> Auskunft:
    """Von Hand nachsehen — auch wenn die Nachfrage beim Öffnen aus ist.

    ⚠️ Das ist kein Widerspruch: Ausgeschaltet heisst „nicht **von selbst**
    hinausrufen". Wer hier klickt, hat es gerade entschieden.
    """
    return _auskunft(nexupdates.switch_on(), nexupdates.state(on=True, force=True))


@router.put("/pruefen", response_model=Auskunft)
def schalter_setzen(eingabe: Schalter, _: Betreiber) -> Auskunft:
    an = nexupdates.set_switch(eingabe.update_pruefen)
    return _auskunft(an, nexupdates.state(on=an))
