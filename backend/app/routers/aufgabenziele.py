"""Todo-Apps — Einstellungen des BENUTZERS, nicht der Verwaltung.

⚠️ **Je Benutzer.** Jeder verbindet seine eigenen Apps mit seinem eigenen
Token; der Betreiber gibt nichts vor und sieht nichts davon.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import MeldungHttp
from ..services import aufgabenziele, todoist
from .aufgaben import _status

router = APIRouter(prefix="/api/aufgabenziele", tags=["aufgabenziele"])


class Verbindung(BaseModel):
    id: str
    art: str
    name: str
    #: ⚠️ **Nicht der Token**, nur ob die App ihn zuletzt angenommen hat.
    fehler: str
    angelegt: datetime
    zuletzt_abgeglichen: datetime | None


class Stand(BaseModel):
    #: Leer heisst: nexmails eigene Liste.
    standard: str
    verbindungen: list[Verbindung]


class Neu(BaseModel):
    art: str = Field(max_length=20)
    zugang: str = Field(min_length=1, max_length=500)
    name: str = Field(default="", max_length=80)


class Standard(BaseModel):
    ziel: str = Field(default="", max_length=200)


class Liste(BaseModel):
    ziel: str
    name: str


class Gruppe(BaseModel):
    verbindung_id: str
    art: str
    name: str
    fehler: str
    listen: list[Liste]


def _verbindung(v) -> Verbindung:
    return Verbindung(
        id=v.id,
        art=v.art,
        name=v.name,
        fehler=v.letzter_fehler,
        angelegt=v.angelegt,
        zuletzt_abgeglichen=v.zuletzt_abgeglichen,
    )


def _stand(db, person) -> Stand:
    return Stand(
        standard=aufgabenziele.standard_von(db, person),
        verbindungen=[_verbindung(v) for v in aufgabenziele.verbindungen(db, person)],
    )


@router.get("", response_model=Stand)
def stand(person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    return _stand(db, person)


@router.post("", response_model=Verbindung, status_code=status.HTTP_201_CREATED)
def verbinden(eingabe: Neu, person: AngemeldeterBenutzer, db: DbSession) -> Verbindung:
    """⚠️ **Die Bremse fehlt hier mit Absicht**, anders als bei der Modellliste
    des KI-Dienstes: Die Adresse steht im Code (Todoist), nicht in der
    Anfrage. nexmail laesst sich hierueber nicht auf fremde Server lenken."""
    try:
        v = aufgabenziele.verbinden(db, person, eingabe.art, eingabe.zugang, eingabe.name)
    except (aufgabenziele.ZielFehler, todoist.TodoistFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _verbindung(v)


@router.delete("/{verbindung_id}", status_code=status.HTTP_204_NO_CONTENT)
def trennen(verbindung_id: str, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        aufgabenziele.trennen(db, person, verbindung_id)
    except aufgabenziele.ZielFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler


@router.put("/standard", response_model=Stand)
def standard(eingabe: Standard, person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    try:
        aufgabenziele.standard_setzen(db, person, eingabe.ziel)
    except aufgabenziele.ZielFehler as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _stand(db, person)


@router.get("/listen", response_model=list[Gruppe])
def listen(person: AngemeldeterBenutzer, db: DbSession) -> list[Gruppe]:
    """Alle waehlbaren Listen, je Verbindung live geholt. Die eigene Liste
    steht nicht darin; die kennt die Oberflaeche selbst."""
    return [
        Gruppe(
            verbindung_id=g.verbindung_id,
            art=g.art,
            name=g.name,
            fehler=g.fehler,
            listen=[Liste(ziel=l.ziel, name=l.name) for l in g.listen],
        )
        for g in aufgabenziele.ziele(db, person)
    ]
