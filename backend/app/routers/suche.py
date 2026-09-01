"""Suchen — im Zwischenspeicher und, auf ausdrücklichen Wunsch, beim Anbieter.

⚠️ **Die Antwort sagt, wo gesucht wurde.** Sonst schließt der Betreiber aus
null Treffern, dass es die Mail nicht gibt — dabei wurde nur der Text noch nie
geholt. Das Feld ``vollstaendig`` trägt genau diese Auskunft.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import suche as suchdienst
from .nachrichten import Zeile, _zeile

logger = logging.getLogger("nexmail.suche")

router = APIRouter(prefix="/api/suche", tags=["suche"])

BEREICHE = ("ordner", "postfach", "alle")


class Suchwunsch(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    bereich: str = "alle"
    ordner_id: int | None = None
    konto_id: str | None = None
    #: Auch den Anbieter fragen. Dauert — deshalb nie von selbst.
    beim_anbieter: bool = False
    grenze: int = Field(default=200, ge=1, le=500)


class Suchergebnis(BaseModel):
    treffer: list[Zeile]
    #: ``False`` heißt: Nur Betreff und Absender wurden vollständig durchsucht,
    #: die Texte nur, soweit sie schon geholt waren. Die Oberfläche muss das
    #: sagen und die Serversuche anbieten.
    vollstaendig: bool


@router.post("", response_model=Suchergebnis)
def suchen(wunsch: Suchwunsch, person: AngemeldeterBenutzer, db: DbSession) -> Suchergebnis:
    if wunsch.bereich not in BEREICHE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannter Suchbereich."
        )

    if wunsch.beim_anbieter:
        gefunden = suchdienst.beim_anbieter_suchen(
            db,
            person,
            wunsch.text,
            wunsch.bereich,
            wunsch.ordner_id,
            wunsch.konto_id,
            wunsch.grenze,
        )
        return Suchergebnis(
            treffer=[_zeile(n) for n in gefunden], vollstaendig=True
        )

    gefunden = suchdienst.suchen(
        db, person, wunsch.text, wunsch.bereich, wunsch.ordner_id, wunsch.konto_id, wunsch.grenze
    )
    return Suchergebnis(treffer=[_zeile(n) for n in gefunden], vollstaendig=False)


@router.post("/index-neu-bauen")
def index_neu_bauen(person: AngemeldeterBenutzer, db: DbSession) -> dict[str, int]:
    """Den Volltextindex aus der Tabelle neu befüllen.

    ⚠️ **Nach einer Wiederherstellung ist das nötig.** Die Sicherung bringt die
    Nachrichten mit, aber die Auslöser haben dabei nie gefeuert — die Suche
    fände sonst nichts, und niemand käme auf die Ursache.
    """
    logger.info("Full-text index rebuild requested by %s.", person.benutzername)
    return {"nachrichten": suchdienst.neu_aufbauen(db)}
