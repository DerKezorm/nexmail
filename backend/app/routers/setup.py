"""Die erste Einrichtung.

⚠️ **Diese Endpunkte sind ohne Anmeldung erreichbar** - anders geht es nicht,
es gibt ja noch kein Konto. Der Schutz ist: **Sobald ein Benutzer existiert,
ist der Weg zu** - mit 404, nicht ausgeblendet.

Das heisst auch, offen gesagt: Wer eine frische, aus dem Netz erreichbare
Installation vor ihrem Besitzer findet, kann sie uebernehmen. Das laesst sich
nicht wegbauen, nur aussprechen - es steht in der README. Ein Einrichtungs-Code
aus dem Container-Protokoll wurde erwogen und verworfen (31.08.2026): Solche
Installationen laufen in aller Regel zuerst im Heimnetz, und der Code waere
fuer den Normalfall Reibung ohne Gegenwert.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import hat_benutzer
from ..deps import DbSession
from ..services import benutzer as benutzerdienst
from ..services import sitzung as sitzungsdienst
from ..services import zwei_faktor
from ..meldung import MeldungHttp

logger = logging.getLogger("nexmail.setup")

router = APIRouter(prefix="/api/setup", tags=["setup"])


class Stand(BaseModel):
    eingerichtet: bool
    zwei_faktor_aus: bool


class KontoEingabe(BaseModel):
    benutzername: str = Field(min_length=3, max_length=64)
    passwort: str = Field(min_length=10, max_length=200)
    anzeigename: str = Field(default="", max_length=120)


class KontoAntwort(BaseModel):
    benutzername: str


def _nur_vor_der_einrichtung(db) -> None:
    if hat_benutzer(db):
        # 404 und nicht 403: Es gibt diesen Weg nach der Einrichtung nicht
        # mehr, und das ist eine ehrlichere Auskunft als "verboten".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/status", response_model=Stand)
def status_lesen(db: DbSession) -> Stand:
    """Ob die Oberflaeche den Einrichtungsassistenten zeigen muss."""
    return Stand(
        eingerichtet=hat_benutzer(db),
        zwei_faktor_aus=get_settings().zwei_faktor_aus,
    )


@router.post("/konto", response_model=KontoAntwort, status_code=status.HTTP_201_CREATED)
def konto_anlegen(
    eingabe: KontoEingabe, request: Request, response: Response, db: DbSession
) -> KontoAntwort:
    """Das erste Konto anlegen - und damit die Tuer schliessen.

    ⚠️ **Der Betreiber-Haken entsteht hier, und das ist der Regelfall.** Wer
    nexmail aufsetzt, muss dafuer nichts wissen und nichts eintragen: Das Konto
    aus dem Assistenten gehoert dem Menschen, dem der Server gehoert.
    ``NEXMAIL_2FA_AUS`` ist nur der Nothammer fuer spaeter.

    ⚠️ **Der zweite Faktor wird hier nicht mehr erzwungen** (01.09.2026). Er
    war Pflicht; jetzt ist er eine Wahl, die unter Einstellungen → Sicherheit
    getroffen wird. Ein Assistent, aus dem man nicht herauskommt, ohne ein
    Telefon zur Hand zu haben, sperrt genau die Leute aus, fuer die nexmail
    gedacht ist - jemanden, der es abends im eigenen Netz aufsetzt.

    Die Sitzung ist deshalb sofort vollstaendig.
    """
    _nur_vor_der_einrichtung(db)

    try:
        neuer = benutzerdienst.anlegen(
            db,
            eingabe.benutzername,
            eingabe.passwort,
            anzeigename=eingabe.anzeigename,
            ist_betreiber=True,
        )
    except benutzerdienst.BenutzerFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler

    sitzungsdienst.anlegen(db, neuer, request, response, bestaetigt=True)
    logger.info("Initial setup completed: the operator account was created.")

    return KontoAntwort(benutzername=neuer.benutzername)
