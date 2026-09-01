"""Aufgaben — Mails, die noch etwas von einem wollen."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import aufgaben as dienst

router = APIRouter(prefix="/api/aufgaben", tags=["aufgaben"])


class Zeile(BaseModel):
    id: int
    #: Die **aktuelle** Kennung der Mail, frisch nachgeschlagen. ``null``
    #: heisst: Die Mail ist nicht mehr da.
    nachricht_id: int | None
    konto_id: str
    betreff: str
    von_name: str
    von_adresse: str
    mail_datum: datetime | None
    erledigt: datetime | None
    faellig: datetime | None
    #: ⚠️ Die Aufgabe bleibt, die Mail ist weg. Die Oberflaeche sagt das —
    #: sonst klickt man ins Leere und haelt nexmail fuer kaputt.
    verwaist: bool


class Wunsch(BaseModel):
    nachricht_id: int


class Aenderung(BaseModel):
    erledigt: bool | None = None
    #: ⚠️ Nicht mitgeschickt heisst **unveraendert**; ``null`` ausdruecklich
    #: „kein Datum". Ohne den Unterschied verloere jedes Abhaken die
    #: Faelligkeit.
    faellig: datetime | None = None
    faellig_setzen: bool = False


class Sortierung(BaseModel):
    ids: list[int] = Field(default_factory=list)


def _zeile(s: dienst.Sicht) -> Zeile:
    a = s.aufgabe
    return Zeile(
        id=a.id,
        nachricht_id=s.nachricht_id,
        konto_id=a.konto_id,
        betreff=a.betreff,
        von_name=a.von_name,
        von_adresse=a.von_adresse,
        mail_datum=a.mail_datum,
        erledigt=a.erledigt,
        faellig=a.faellig,
        verwaist=s.verwaist,
    )


@router.get("", response_model=list[Zeile])
def liste(person: AngemeldeterBenutzer, db: DbSession) -> list[Zeile]:
    return [_zeile(s) for s in dienst.alle(db, person)]


@router.post("", response_model=Zeile, status_code=status.HTTP_201_CREATED)
def anlegen(wunsch: Wunsch, person: AngemeldeterBenutzer, db: DbSession) -> Zeile:
    try:
        aufgabe = dienst.anlegen(db, person, wunsch.nachricht_id)
    except dienst.AufgabenFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler
    return _zeile(dienst.Sicht(aufgabe=aufgabe, nachricht_id=aufgabe.nachricht_id, verwaist=False))


@router.put("/reihenfolge", status_code=status.HTTP_204_NO_CONTENT)
def ordnen(wunsch: Sortierung, person: AngemeldeterBenutzer, db: DbSession) -> None:
    """⚠️ **Vor ``/{aufgabe_id}``**, sonst schluckt die Kennung dieses Wort.

    FastAPI nimmt die erste passende Route. Stuende sie darunter, landete
    „reihenfolge" als Kennung in ``aufgabe_id`` und gaebe eine
    Pydantic-Meldung ueber eine kaputte Zahl.
    """
    dienst.ordnen(db, person, wunsch.ids)


@router.patch("/{aufgabe_id}", response_model=Zeile)
def aendern(
    aufgabe_id: int, wunsch: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> Zeile:
    try:
        if wunsch.erledigt is not None:
            dienst.abhaken(db, person, aufgabe_id, wunsch.erledigt)
        if wunsch.faellig_setzen:
            dienst.faelligkeit(db, person, aufgabe_id, wunsch.faellig)
        aufgabe = dienst.eine(db, person, aufgabe_id)
    except dienst.AufgabenFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler

    # Frisch nachschlagen: Die Mail kann inzwischen umgezogen sein.
    for sicht in dienst.alle(db, person):
        if sicht.aufgabe.id == aufgabe.id:
            return _zeile(sicht)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete("/{aufgabe_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(aufgabe_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        dienst.entfernen(db, person, aufgabe_id)
    except dienst.AufgabenFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler
