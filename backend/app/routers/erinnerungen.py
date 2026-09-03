"""Fällige Erinnerungen — die Adressen.

⚠️ **Der Kanal steht im Server, nicht in der Anfrage.** Diese Adresse ist der
Kanal „in der App": Die Oberfläche holt ab, was fällig ist. Ein Web-Push oder
eine Erinnerungsmail wäre ein zweiter Kanal mit eigenem Anstoß — er ruft
denselben Dienst mit einem anderen Namen. Wer den Kanal von außen wählbar
machte, ließe jeden Benutzer die Buchführung eines fremden Kanals zerschießen.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import erinnerungen as dienst

router = APIRouter(prefix="/api/erinnerungen", tags=["erinnerungen"])


class FaelligZeile(BaseModel):
    id: int
    termin_id: int
    titel: str
    ort: str
    kalender: str
    farbe: int
    beginn: datetime
    ganztaegig: bool
    vorlauf: int


class Schlummerwunsch(BaseModel):
    minuten: int


@router.get("/faellig", response_model=list[FaelligZeile])
def faellig(person: AngemeldeterBenutzer, db: DbSession) -> list[FaelligZeile]:
    """Was jetzt dran ist.

    ⚠️ **Der Abruf merkt sich, dass zugestellt wurde.** Er ist damit nicht
    nebenwirkungsfrei — das ist Absicht: Genau daran hängt, dass dieselbe
    Erinnerung nicht bei jedem Abruf erneut aufpoppt.
    """
    return [
        FaelligZeile(
            id=f.id,
            termin_id=f.termin_id,
            titel=f.titel,
            ort=f.ort,
            kalender=f.kalender,
            farbe=f.farbe,
            beginn=f.beginn,
            ganztaegig=f.ganztaegig,
            vorlauf=f.vorlauf,
        )
        for f in dienst.faellige(db, person)
    ]


@router.post("/{zustellung_id}/erledigt", status_code=status.HTTP_204_NO_CONTENT)
def erledigt(zustellung_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Response:
    try:
        dienst.erledigt(db, person, zustellung_id)
    except dienst.ErinnerungFehler as f:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(f)) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{zustellung_id}/schlummern", status_code=status.HTTP_204_NO_CONTENT)
def schlummern(
    zustellung_id: int, wunsch: Schlummerwunsch, person: AngemeldeterBenutzer, db: DbSession
) -> Response:
    try:
        dienst.schlummern(db, person, zustellung_id, wunsch.minuten)
    except dienst.ErinnerungFehler as f:
        kennung = str(f)
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if kennung == "schlummer_unbekannt"
                else status.HTTP_404_NOT_FOUND
            ),
            detail=kennung,
        ) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)
