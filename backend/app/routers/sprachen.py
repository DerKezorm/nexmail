"""Die eigenen Sprachen des Betreibers fuer die Sprachauswahl (wie nexnotes, ``/api/locales``).

Lesen ohne Anmeldung: Die Anmeldeseite steht auch in der gewaehlten Sprache, und die Texte sind fuer alle gleich.
Hochladen und Entfernen nur der Betreiber.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from ..deps import Betreiber
from ..meldung import MeldungHttp
from ..services import sprachen

router = APIRouter(prefix="/api/locales", tags=["locales"])


class Eintrag(BaseModel):
    code: str
    name: str
    keys: int


@router.get("", response_model=list[Eintrag], summary="Languages the operator added")
def liste() -> list[sprachen.Locale]:
    return sprachen.available()


@router.get("/{code}", summary="The texts of one added language", response_model=None)
def lesen(code: str) -> dict[str, Any]:
    if not sprachen.valid_code(code):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sprache_unbekannt")
    try:
        return sprachen.load(code)
    except FileNotFoundError as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sprache_unbekannt") from fehler
    except (sprachen.LocaleError, OSError) as fehler:
        raise HTTPException(status_code=422, detail="sprachdatei_unbrauchbar") from fehler


@router.put("/{code}", response_model=Eintrag, summary="Add or replace a language (operator)")
async def hochladen(code: str, request: Request, _: Betreiber) -> sprachen.Locale:
    """Der Rumpf ist die JSON-Datei selbst, hoechstens 512 KB."""
    roh = bytearray()
    async for stueck in request.stream():
        roh.extend(stueck)
        if len(roh) > sprachen.MAX_BYTES:
            raise MeldungHttp(413, "sprachdatei_zu_gross", {"max_kb": sprachen.MAX_BYTES // 1024})
    try:
        return sprachen.save(code, bytes(roh))
    except sprachen.LocaleError as fehler:
        raise HTTPException(status_code=422, detail="sprachdatei_unbrauchbar") from fehler


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an added language (operator)")
def entfernen(code: str, _: Betreiber) -> None:
    if not sprachen.remove(code):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sprache_unbekannt")
