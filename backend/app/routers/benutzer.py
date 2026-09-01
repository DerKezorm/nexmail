"""Benutzerverwaltung — was der Anwendung gehoert, nicht dem Einzelnen.

⚠️ **Nur der Betreiber.** ``ist_betreiber`` ist dabei ein Haken, kein Rang: Er
sagt nicht, was dieser Mensch darf, sondern was andere mit ihm nicht duerfen.

⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
einzeln. nexmail ist der Mail-Client eines Haushalts, keine Plattform.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import einstellung_lesen
from ..deps import Betreiber, DbSession
from ..models import Benutzer, Einladung
from ..routers.einstellungen import SCHLUESSEL_OEFFENTLICHE_ADRESSE
from ..services import benutzer as benutzerdienst
from ..services import einladung as einladungsdienst
from ..services import systempost

logger = logging.getLogger("nexmail.benutzer")

router = APIRouter(prefix="/api/benutzer", tags=["benutzer"])


class BenutzerZeile(BaseModel):
    id: str
    benutzername: str
    anzeigename: str
    ist_betreiber: bool
    zwei_faktor_aktiv: bool
    angelegt: datetime
    #: Wie viele Postfaecher an ihm haengen — die Liste soll etwas aussagen.
    postfaecher: int


class EinladungsZeile(BaseModel):
    id: str
    benutzername: str
    anzeigename: str
    adresse: str
    angelegt: datetime
    laeuft_ab: datetime
    abgelaufen: bool


class Bestand(BaseModel):
    benutzer: list[BenutzerZeile]
    einladungen: list[EinladungsZeile]
    #: Ohne Postausgang laesst sich niemand einladen — das sagt die Oberflaeche
    #: **vorher**, statt den Betreiber gegen einen Fehler laufen zu lassen.
    postausgang_da: bool
    #: Ohne oeffentliche Adresse waere der Link in der Mail unbrauchbar.
    adresse_da: bool


class Einladen(BaseModel):
    benutzername: str = Field(min_length=1, max_length=64)
    adresse: str = Field(min_length=3, max_length=320)
    anzeigename: str = Field(default="", max_length=120)


class Umfang(BaseModel):
    postfaecher: int
    nachrichten: int
    kontakte: int
    regeln: int
    signaturen: int


def _zeile(db, person: Benutzer) -> BenutzerZeile:
    from ..models import Konto

    anzahl = len(db.execute(select(Konto.id).where(Konto.benutzer_id == person.id)).all())
    return BenutzerZeile(
        id=person.id,
        benutzername=person.benutzername,
        anzeigename=person.anzeigename,
        ist_betreiber=person.ist_betreiber,
        zwei_faktor_aktiv=person.totp_bestaetigt,
        angelegt=person.angelegt,
        postfaecher=anzahl,
    )


def _einladungszeile(e: Einladung) -> EinladungsZeile:
    return EinladungsZeile(
        id=e.id,
        benutzername=e.benutzername,
        anzeigename=e.anzeigename,
        adresse=e.adresse,
        angelegt=e.angelegt,
        laeuft_ab=e.laeuft_ab,
        abgelaufen=einladungsdienst.abgelaufen(e),
    )


@router.get("", response_model=Bestand)
def liste(_: Betreiber, db: DbSession) -> Bestand:
    leute = db.execute(select(Benutzer).order_by(Benutzer.angelegt)).scalars().all()
    return Bestand(
        benutzer=[_zeile(db, p) for p in leute],
        einladungen=[_einladungszeile(e) for e in einladungsdienst.offene(db)],
        postausgang_da=systempost.lesen(db).eingerichtet,
        adresse_da=bool(einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE)),
    )


@router.post("/einladungen", response_model=EinladungsZeile, status_code=status.HTTP_201_CREATED)
def einladen(eingabe: Einladen, _: Betreiber, db: DbSession) -> EinladungsZeile:
    """Einladen — anlegen **und** verschicken.

    ⚠️ **Beides oder nichts.** Eine Einladung, die in der Liste steht, deren
    Mail aber nie hinausging, ist die schlimmste Sorte: Der Betreiber wartet,
    der Eingeladene weiss von nichts, und in der Oberflaeche sieht alles
    richtig aus. Geht der Versand schief, wird die Zeile wieder entfernt und
    der Grund gemeldet.
    """
    adresse_der_app = einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE)
    if not adresse_der_app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Ohne öffentliche Adresse führt der Link in der Einladung ins "
                "Leere. Sie steht in der Verwaltung unter „Server“."
            ),
        )

    try:
        einladung, schluessel = einladungsdienst.aussprechen(
            db,
            benutzername=eingabe.benutzername,
            adresse=eingabe.adresse,
            anzeigename=eingabe.anzeigename,
        )
    except einladungsdienst.EinladungsFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    try:
        einladungsdienst.verschicken(db, einladung, schluessel, adresse_der_app)
    except systempost.PostFehler as fehler:
        db.delete(einladung)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(fehler)) from fehler

    return _einladungszeile(einladung)


@router.delete("/einladungen/{einladung_id}", status_code=status.HTTP_204_NO_CONTENT)
def einladung_zuruecknehmen(einladung_id: str, _: Betreiber, db: DbSession) -> None:
    einladung = db.get(Einladung, einladung_id)
    if einladung is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    db.delete(einladung)
    db.commit()
    logger.info("An invitation was withdrawn.")


@router.get("/{benutzer_id}/umfang", response_model=Umfang)
def umfang(benutzer_id: str, _: Betreiber, db: DbSession) -> Umfang:
    """Was am Benutzer haengt — fuer die Rueckfrage vor dem Entfernen."""
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Umfang(**benutzerdienst.umfang(db, person))


@router.delete("/{benutzer_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(benutzer_id: str, ich: Betreiber, db: DbSession) -> None:
    """Einen Benutzer mit allem entfernen, was ihm gehoert.

    ⚠️ **Der Betreiber selbst geht nicht.** Danach haette nexmail niemanden,
    der die Verwaltung oeffnen kann — und aus der Anwendung heraus fuehrt kein
    Weg zurueck. Wer den Betreiber wechseln will, uebergibt den Haken; das ist
    ein anderer Vorgang und keine Loeschung.
    """
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if person.id == ich.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Du kannst dich nicht selbst entfernen.",
        )
    if person.ist_betreiber:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Der Betreiber lässt sich nicht entfernen.",
        )
    benutzerdienst.entfernen(db, person)
