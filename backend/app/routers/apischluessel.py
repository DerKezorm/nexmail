"""Die eigenen API-Schluessel verwalten, und der Riegel des Betreibers.

Gelesen wird mit einem Schluessel ueber ``/api/v1`` (``routers/api_v1.py``).
Hier stehen die Adressen fuer die Oberflaeche, also mit Sitzung.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..meldung import MeldungHttp
from ..models import ApiSchluessel
from ..services import apischluessel as dienst

router = APIRouter(prefix="/api/apischluessel", tags=["apischluessel"])


class Eintrag(BaseModel):
    id: str
    name: str
    praefix: str
    stufe: str
    konten: list[str]
    angelegt: datetime
    zuletzt_benutzt: datetime | None


class Stand(BaseModel):
    erlaubt: bool
    schluessel: list[Eintrag]


class Eingabe(BaseModel):
    name: str = Field(default="", max_length=200)
    stufe: str = "anzahl"
    konten: list[str] = Field(default_factory=list, max_length=200)


class Neu(Eintrag):
    #: ⚠️ **Nur in dieser einen Antwort.** Danach kennt nexmail nur noch den Hash.
    schluessel: str


class Riegel(BaseModel):
    erlaubt: bool


def _eintrag(zeile: ApiSchluessel, eigene: set[str]) -> Eintrag:
    return Eintrag(
        id=zeile.id,
        name=zeile.name,
        praefix=zeile.praefix,
        stufe=zeile.stufe,
        # Entfernte Postfaecher fallen hier heraus, wie beim Lesen.
        konten=[k for k in dienst.konten_lesen(zeile) if k in eigene],
        angelegt=zeile.angelegt,
        zuletzt_benutzt=zeile.zuletzt_benutzt,
    )


def _abgewiesen(fehler: dienst.SchluesselFehler) -> MeldungHttp:
    return MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST)


@router.get("", response_model=Stand)
def lesen(person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    eigene = {k.id for k in dienst.eigene_konten(db, person.id)}
    return Stand(
        erlaubt=dienst.erlaubt(db),
        schluessel=[_eintrag(z, eigene) for z in dienst.liste(db, person)],
    )


# ⚠️ **Vor den Adressen mit Kennung.** Sonst faengt ``PUT /{schluessel_id}``
# das Wort „erlaubt“ als Kennung ab, und der Riegel antwortet mit 404.
@router.get("/erlaubt", response_model=Riegel)
def riegel_lesen(_: AngemeldeterBenutzer, db: DbSession) -> Riegel:
    return Riegel(erlaubt=dienst.erlaubt(db))


@router.put("/erlaubt", response_model=Riegel)
def riegel_setzen(eingabe: Riegel, _: Betreiber, db: DbSession) -> Riegel:
    """⚠️ **Nur der Betreiber.** Ob Betreff und Absender das Haus verlassen
    duerfen, entscheidet der, der fuer die Installation verantwortlich ist."""
    return Riegel(erlaubt=dienst.erlauben(db, eingabe.erlaubt))


@router.post("", response_model=Neu, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession) -> Neu:
    # ⚠️ **Auch hier der Riegel, nicht nur beim Lesen.** Sonst entstuenden
    # Schluessel, die in dem Moment funktionieren, in dem der Betreiber
    # aufmacht, ohne dass er weiss, dass es sie gibt.
    if not dienst.erlaubt(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="api_schluessel_abgeschaltet")
    try:
        zeile, klartext = dienst.anlegen(db, person, eingabe.name, eingabe.stufe, eingabe.konten)
    except dienst.SchluesselFehler as fehler:
        raise _abgewiesen(fehler) from fehler
    eigene = {k.id for k in dienst.eigene_konten(db, person.id)}
    return Neu(**_eintrag(zeile, eigene).model_dump(), schluessel=klartext)


@router.put("/{schluessel_id}", response_model=Eintrag)
def aendern(
    schluessel_id: str, eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession
) -> Eintrag:
    try:
        zeile = dienst.aendern(
            db, person, schluessel_id, eingabe.name, eingabe.stufe, eingabe.konten
        )
    except dienst.SchluesselFehler as fehler:
        raise _abgewiesen(fehler) from fehler
    if zeile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api_schluessel_unbekannt")
    eigene = {k.id for k in dienst.eigene_konten(db, person.id)}
    return _eintrag(zeile, eigene)


@router.delete("/{schluessel_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(schluessel_id: str, person: AngemeldeterBenutzer, db: DbSession) -> None:
    """Widerrufen wirkt sofort: Die naechste Abfrage mit diesem Schluessel
    bekommt 401."""
    if not dienst.entfernen(db, person, schluessel_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api_schluessel_unbekannt")
