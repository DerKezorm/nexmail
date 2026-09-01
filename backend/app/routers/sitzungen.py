"""Angemeldete Geräte sehen und einzeln kündigen.

Das ist der Gegenwert dafür, dass die Sitzungen im Server liegen statt in
einem Token: Man sieht sie, und „abmelden" wirkt sofort.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..deps import AktiveSitzung, AngemeldeterBenutzer, DbSession
from ..services import sitzung as sitzungsdienst

router = APIRouter(prefix="/api/sitzungen", tags=["sitzungen"])


class Geraet(BaseModel):
    id: str
    geraet: str
    adresse: str
    angelegt: datetime
    zuletzt_gesehen: datetime
    #: Die Sitzung, mit der gerade gearbeitet wird - die darf man nicht
    #: versehentlich für „irgendein anderes Gerät" halten.
    aktuell: bool


@router.get("", response_model=list[Geraet])
def liste(person: AngemeldeterBenutzer, aktuelle: AktiveSitzung) -> list[Geraet]:
    return [
        Geraet(
            id=s.id,
            geraet=s.geraet,
            adresse=s.adresse,
            angelegt=s.angelegt,
            zuletzt_gesehen=s.zuletzt_gesehen,
            aktuell=s.id == aktuelle.id,
        )
        for s in sorted(person.sitzungen, key=lambda s: s.zuletzt_gesehen, reverse=True)
        if s.bestaetigt
    ]


@router.delete("/{sitzung_id}", status_code=status.HTTP_204_NO_CONTENT)
def beenden(
    sitzung_id: str, person: AngemeldeterBenutzer, aktuelle: AktiveSitzung, db: DbSession
) -> None:
    """Ein einzelnes Gerät abmelden.

    Nur eigene Sitzungen - die Schleife läuft über ``person.sitzungen``, nicht
    über die Tabelle. Eine fremde Kennung findet hier nichts und bekommt 404.
    """
    for s in person.sitzungen:
        if s.id == sitzung_id:
            if s.id == aktuelle.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Diese Sitzung ist die aktuelle - dafür gibt es Abmelden.",
                )
            db.delete(s)
            db.commit()
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


class Ergebnis(BaseModel):
    beendet: int


@router.post("/alle-beenden", response_model=Ergebnis)
def alle_beenden(
    person: AngemeldeterBenutzer, aktuelle: AktiveSitzung, db: DbSession
) -> Ergebnis:
    """Auf allen anderen Geräten abmelden. Die eigene bleibt."""
    return Ergebnis(beendet=sitzungsdienst.alle_beenden(db, person, ausser=aktuelle.id))
