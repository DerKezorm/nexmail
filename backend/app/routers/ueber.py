"""Die Ueber-Seite: Fassung, Herkunft, Lizenz, Update-Stand.

⚠️ **Nur der Betreiber.** So entschieden am 01.09.2026: „Ein Fragezeichen-Button
ueber dem Einstellungsbutton links unten. Nur fuer Admins." Die Seite traegt den
Update-Schalter, und der ruft nach draussen — das ist eine Entscheidung ueber
die ganze Installation, keine ueber ein Konto.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__
from ..db import einstellung_lesen, einstellung_schreiben
from ..deps import Betreiber, DbSession
from ..services import aktualisierung

router = APIRouter(prefix="/api/ueber", tags=["ueber"])

SCHLUESSEL_UPDATE_PRUEFEN = "update_pruefen"


class Auskunft(BaseModel):
    version: str
    repo_adresse: str
    release_adresse: str
    projektseite: str
    lizenz: str = "AGPL-3.0-or-later"

    update_pruefen: bool
    geprueft: bool = False
    neueste: str | None = None
    neuer_da: bool = False
    geprueft_am: datetime | None = None


class Schalter(BaseModel):
    update_pruefen: bool


def _an(db) -> bool:
    """⚠️ Ab Werk **an** — so entschieden am 01.09.2026, „wie bei nexview".

    Ein leerer Wert heisst also nicht „aus", sondern „noch nie angefasst".
    """
    wert = einstellung_lesen(db, SCHLUESSEL_UPDATE_PRUEFEN)
    return wert != "0"


def _auskunft(pruefen: bool, stand: aktualisierung.Stand | None) -> Auskunft:
    return Auskunft(
        version=__version__,
        repo_adresse=aktualisierung.REPO_URL,
        release_adresse=aktualisierung.RELEASES_URL,
        projektseite=aktualisierung.PROJEKTSEITE,
        update_pruefen=pruefen,
        geprueft=stand is not None and stand.geprueft_am is not None,
        neueste=stand.neueste if stand else None,
        neuer_da=bool(stand and stand.neuer_da),
        geprueft_am=stand.geprueft_am if stand else None,
    )


@router.get("", response_model=Auskunft)
async def ueber(_: Betreiber, db: DbSession) -> Auskunft:
    pruefen = _an(db)
    return _auskunft(pruefen, await aktualisierung.stand(an=pruefen))


@router.post("/pruefen", response_model=Auskunft)
async def jetzt_pruefen(_: Betreiber, db: DbSession) -> Auskunft:
    """Von Hand nachsehen — auch wenn die tägliche Nachfrage aus ist.

    ⚠️ Das ist kein Widerspruch: Ausgeschaltet heisst „nicht **von selbst**
    hinausrufen". Wer hier klickt, hat es gerade entschieden.
    """
    return _auskunft(_an(db), await aktualisierung.stand(an=True, erzwingen=True))


@router.put("/pruefen", response_model=Auskunft)
async def schalter_setzen(eingabe: Schalter, _: Betreiber, db: DbSession) -> Auskunft:
    einstellung_schreiben(db, SCHLUESSEL_UPDATE_PRUEFEN, "1" if eingabe.update_pruefen else "0")
    db.commit()
    return _auskunft(
        eingabe.update_pruefen,
        await aktualisierung.stand(an=eingabe.update_pruefen),
    )
