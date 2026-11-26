"""„Als Dokument an nexpaper“: die Tresore, in die die Klick-Verbindung Dokumente legen darf (V38).

Ist mehr als einer freigegeben, fragt die Oberfläche in einem kleinen Fenster, vorgewählt der zuletzt genutzte (je
Konto gemerkt, ``einstellung`` ``nexpaper_tresor:<konto>``); sonst geht der Anhang direkt.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel

from ..db import einstellung_lesen, einstellung_schreiben
from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import MeldungHttp
from ..services import nexpaper

router = APIRouter(prefix="/api/nexpaper", tags=["nexpaper"])


def merk_schluessel(konto_id: str) -> str:
    return f"nexpaper_tresor:{konto_id}"


def zuletzt(db, konto_id: str) -> int | None:
    wert = einstellung_lesen(db, merk_schluessel(konto_id), "")
    return int(wert) if wert.isdigit() else None


def merken(db, konto_id: str, tresor: int | None) -> None:
    if tresor is not None:
        einstellung_schreiben(db, merk_schluessel(konto_id), str(tresor))


class Tresor(BaseModel):
    id: int
    name: str


class Tresore(BaseModel):
    tresore: list[Tresor]
    #: Der zuletzt genutzte, wenn er noch dabei ist.
    zuletzt: int | None = None


def http(f: nexpaper.NexpaperFehler) -> MeldungHttp:
    code = status.HTTP_502_BAD_GATEWAY if f.kennung == "nexpaper_nicht_erreichbar" else status.HTTP_409_CONFLICT
    return MeldungHttp(code, f.kennung, f.werte)


@router.get("/tresore", response_model=Tresore)
def tresore(person: AngemeldeterBenutzer, db: DbSession) -> Tresore:
    try:
        liste = nexpaper.tresore(str(person.id))
    except nexpaper.NexpaperFehler as f:
        raise http(f) from f
    gemerkt = zuletzt(db, str(person.id))
    return Tresore(
        tresore=[Tresor(**t) for t in liste],
        zuletzt=gemerkt if any(t["id"] == gemerkt for t in liste) else None,
    )
