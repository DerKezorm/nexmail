"""Schlagwort-Definitionen verwalten — Einstellungen -> Schlagworte.

⚠️ **Fehler gehen als KENNUNG hinaus, nicht als Satz.** Die Oberflaeche
uebersetzt ``schlagwort_name_vergeben`` und Co. in beide Sprachen — ein
deutscher Satz als ``detail`` bliebe auf Englisch deutsch.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Schlagwort
from ..services import schlagworte as dienst

router = APIRouter(prefix="/api/schlagworte", tags=["schlagworte"])


class Zeile(BaseModel):
    id: int
    name: str
    #: Das IMAP-Keyword — unveraenderlich, es steht auf dem Server.
    atom: str
    farbe: int
    #: Wie viele bekannte Mails das Schlagwort tragen.
    anzahl: int


class Wunsch(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Aenderung(BaseModel):
    #: Nicht mitgeschickt heisst unveraendert — wie ueberall.
    name: str | None = Field(default=None, max_length=100)
    farbe: int | None = None


class Loeschstand(BaseModel):
    #: Von wie vielen bekannten Mails das Keyword entfernt wurde.
    entfernt: int


def _zeile(db, person, z: Schlagwort, zaehlung: dict[str, int] | None = None) -> Zeile:
    """Eine Zeile fuer die Oberflaeche.

    ⚠️ **Ohne ``zaehlung`` kostet das einen Vollscan.** Fuer eine einzelne
    Zeile ist das richtig; fuer die Liste holt sie der Aufrufer **einmal** fuer
    alle — siehe ``alle_zaehlen``.
    """
    return Zeile(
        id=z.id,
        name=z.name,
        atom=z.atom,
        farbe=z.farbe,
        anzahl=(
            zaehlung.get(z.atom.lower(), 0)
            if zaehlung is not None
            else dienst.betroffene_zaehlen(db, person.id, z.atom)
        ),
    )


def _fehler(fehler: dienst.SchlagwortFehler) -> HTTPException:
    kennung = str(fehler)
    if kennung == "schlagwort_unbekannt":
        # Fremder Besitz und „gibt es nicht" antworten gleich.
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if kennung == "schlagwort_name_vergeben":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=kennung)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=kennung)


@router.get("", response_model=list[Zeile])
def liste(person: AngemeldeterBenutzer, db: DbSession) -> list[Zeile]:
    # ⚠️ **Eine Zaehlung fuer alle, nicht eine je Schlagwort.** Der ``LIKE`` auf
    # die JSON-Spalte kann keinen Index nutzen; je Zeile einzeln zu zaehlen
    # waren bei 250.000 Nachrichten 240 ms mal Anzahl der Schlagworte — fuer
    # eine Liste, die die Oberflaeche bei jedem Oeffnen holt.
    zaehlung = dienst.alle_zaehlen(db, person.id)
    return [_zeile(db, person, z, zaehlung) for z in dienst.meine(db, person.id)]


@router.post("", response_model=Zeile, status_code=status.HTTP_201_CREATED)
def anlegen(wunsch: Wunsch, person: AngemeldeterBenutzer, db: DbSession) -> Zeile:
    try:
        zeile = dienst.anlegen(db, person.id, wunsch.name)
    except dienst.SchlagwortFehler as fehler:
        raise _fehler(fehler) from fehler
    return _zeile(db, person, zeile)


@router.patch("/{schlagwort_id}", response_model=Zeile)
def aendern(
    schlagwort_id: int, wunsch: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> Zeile:
    """Umbenennen (nur der Anzeige-Name) und Farbe wechseln.

    ⚠️ Das Atom laesst sich nicht aendern — es steht als Keyword auf den
    Mailservern, und dort kaeme die Aenderung nie an.
    """
    try:
        zeile = dienst.eines(db, person.id, schlagwort_id)
        if wunsch.name is not None:
            zeile = dienst.umbenennen(db, person.id, schlagwort_id, wunsch.name)
        if wunsch.farbe is not None:
            zeile = dienst.farbe_setzen(db, person.id, schlagwort_id, wunsch.farbe)
    except dienst.SchlagwortFehler as fehler:
        raise _fehler(fehler) from fehler
    return _zeile(db, person, zeile)


@router.delete("/{schlagwort_id}", response_model=Loeschstand)
def loeschen(schlagwort_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Loeschstand:
    """⚠️ Entfernt das Keyword erst auf den Servern (je Konto/Ordner
    gebuendelt), dann lokal, dann die Definition. Scheitert ein Server,
    bleibt die Definition stehen — der 502 kommt aus dem Auffangbehandler."""
    try:
        entfernt = dienst.loeschen(db, person, schlagwort_id)
    except dienst.SchlagwortFehler as fehler:
        raise _fehler(fehler) from fehler
    return Loeschstand(entfernt=entfernt)
