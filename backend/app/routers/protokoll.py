"""Das Protokoll ansehen, umschalten, herunterladen und leeren, nur für Betreiber.

Seit dem Modul ``log`` (bauplaene/log 1.0.0) zwei Wege auf dieselben Funktionen:

``/api/logs``       die Wege des Moduls (``nexlog.api``), wie in allen nex-Apps; die Karte „Log" ruft sie.
``/api/protokoll``  der alte Weg in seiner alten Form (deutsche Stufen, ``minuten`` 0 = 30), für alles, was ihn
                    schon kennt. Der Download ist jetzt ein Text statt eines ZIP (E21): ältere Datei zuerst, je Datei
                    eine Kopfzeile, wie überall.

⚠️ **Nur für den Betreiber.** Im Protokoll steht, wer wann was getan hat; bei mehreren Benutzern wäre das ein Fenster
in fremde Vorgänge.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..deps import Betreiber, nur_betreiber
from ..services import protokoll as dienst
from ..vendor import nexlog
from ..vendor.nexlog import api as nexlog_api

logger = logging.getLogger("nexmail.protokoll")

#: Die Wege des Moduls unter ``/api/logs``.
modul_router = nexlog_api.router(operator=nur_betreiber, prefix="/api/logs", tags=["logs"])

router = APIRouter(prefix="/api/protokoll", tags=["protokoll"])


class Zeile(BaseModel):
    zeit: str
    stufe: str
    modul: str
    meldung: str
    vorgang: str | None = None
    benutzer: str | None = None


class StandAntwort(BaseModel):
    stufe: str
    bis: str | None
    #: ``True`` heißt: ``NEXMAIL_LOG_STUFE`` ist gesetzt und die Oberfläche kann nichts umstellen.
    durch_umgebung: bool
    stufen: list[str]
    minuten: list[int]


class StufenWunsch(BaseModel):
    stufe: str
    #: 0 hieß „bis zum Neustart"; eine tiefe Stufe läuft dann 30 Minuten.
    minuten: int = Field(default=30, ge=0, le=1440)


def _antwort(s: dienst.Stand) -> StandAntwort:
    return StandAntwort(
        stufe=s.stufe,
        bis=s.bis,
        durch_umgebung=s.durch_umgebung,
        stufen=list(dienst.STUFEN),
        minuten=list(dienst.ERLAUBTE_MINUTEN),
    )


@router.get("/stand", response_model=StandAntwort)
def stand(person: Betreiber) -> StandAntwort:
    return _antwort(dienst.stand())


@router.put("/stufe", response_model=StandAntwort)
def stufe_setzen(wunsch: StufenWunsch, person: Betreiber) -> StandAntwort:
    if dienst.stand().durch_umgebung:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stufe_aus_der_umgebung")
    try:
        s = dienst.stufe_setzen(None, wunsch.stufe, wunsch.minuten)
    except ValueError as fehler:
        # Vor dem Modul fiel das hier mit 500 um (``MeldungHttp.aus`` nimmt keinen ValueError).
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unbekannte_stufe") from fehler
    return _antwort(s)


@router.get("", response_model=list[Zeile])
def lesen(person: Betreiber, grenze: int = 200, stufe: str = "", suche: str = "") -> list[Zeile]:
    return [
        Zeile(
            zeit=z.zeit, stufe=z.stufe, modul=z.modul, meldung=z.meldung, vorgang=z.vorgang, benutzer=z.benutzer
        )
        for z in dienst.lesen(max(1, min(grenze, 1000)), stufe or None, suche or None)
    ]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def leeren(person: Betreiber) -> None:
    dienst.leeren()


@router.get("/download")
def herunterladen(person: Betreiber) -> Response:
    """Alle Stände als ein Text, wie der Weg des Moduls (``/api/logs/download``)."""
    text = nexlog.download_text()
    logger.info("Log downloaded by operator")
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{nexlog.download_name()}"'},
    )
