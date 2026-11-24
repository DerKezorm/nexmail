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
from ..vendor.nexpost.letters import describe_browser

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


def anzeige(sitzung, sprache: str) -> str:
    """Was die Liste von einem Eintrag zeigt. ⚠️ **Nie der rohe User-Agent** (fremder Text, und unlesbar): ein
    Browser heisst „Firefox auf Linux“ wie in der Mail „Neue Anmeldung“ (``nexpost.letters.describe_browser``). Ein
    gekoppeltes Geraet traegt den Namen, den die App beim Koppeln gab."""
    if sitzung.art == "geraet":
        return sitzung.geraet
    return describe_browser(sitzung.geraet, sprache)


@router.get("", response_model=list[Geraet])
def liste(
    person: AngemeldeterBenutzer, aktuelle: AktiveSitzung, db: DbSession, sprache: str = ""
) -> list[Geraet]:
    """``sprache``: die der Oberflaeche (``de``, ``en``, ``fr``); sonst die des Kontos."""
    if sprache[:2] not in ("de", "en", "fr"):
        from ..services import kontenpost

        sprache = kontenpost._sprache(db, person.id)
    return [
        Geraet(
            id=s.id,
            geraet=anzeige(s, sprache[:2]),
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
                    detail="sitzung_ist_aktuell",
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
