"""Das Protokoll ansehen, umschalten und herunterladen.

⚠️ **Nur für den Betreiber.** Im Protokoll steht, wer wann was getan hat —
bei mehreren Benutzern wäre das ein Fenster in fremde Vorgänge. Das
Betreiberkonto ist ohnehin das erste; später entscheidet der Haken.

⚠️ **Der Download nimmt die alten Stände mit.** Wer beim Suchen hilft, braucht
mehr als die letzten zweihundert Zeilen — und soll nicht darum bitten müssen.
"""

from __future__ import annotations

import io
import logging
import zipfile

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import protokoll as dienst

logger = logging.getLogger("nexmail.protokoll")

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
    #: ``True`` heißt: ``NEXMAIL_LOG_STUFE`` ist gesetzt und die Oberfläche
    #: kann nichts umstellen. Das muss dastehen, sonst klickt man ins Leere.
    durch_umgebung: bool
    stufen: list[str]
    minuten: list[int]


class StufenWunsch(BaseModel):
    stufe: str
    #: 0 heißt „bis zum Neustart" — bei den tiefen Stufen nicht erlaubt.
    minuten: int = Field(default=30, ge=0, le=1440)


def _nur_betreiber(person) -> None:
    if not getattr(person, "ist_betreiber", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Das Protokoll sieht nur der Betreiber.",
        )


@router.get("/stand", response_model=StandAntwort)
def stand(person: AngemeldeterBenutzer, db: DbSession) -> StandAntwort:
    _nur_betreiber(person)
    s = dienst.stand(db)
    return StandAntwort(
        stufe=s.stufe,
        bis=s.bis,
        durch_umgebung=s.durch_umgebung,
        stufen=list(dienst.STUFEN),
        minuten=list(dienst.ERLAUBTE_MINUTEN),
    )


@router.put("/stufe", response_model=StandAntwort)
def stufe_setzen(
    wunsch: StufenWunsch, person: AngemeldeterBenutzer, db: DbSession
) -> StandAntwort:
    _nur_betreiber(person)
    if dienst.stand(db).durch_umgebung:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Die Stufe steht in NEXMAIL_LOG_STUFE und lässt sich hier nicht "
                "ändern. Nimm sie aus der compose-Datei heraus."
            ),
        )
    try:
        s = dienst.stufe_setzen(db, wunsch.stufe, wunsch.minuten)
    except ValueError as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return StandAntwort(
        stufe=s.stufe,
        bis=s.bis,
        durch_umgebung=s.durch_umgebung,
        stufen=list(dienst.STUFEN),
        minuten=list(dienst.ERLAUBTE_MINUTEN),
    )


@router.get("", response_model=list[Zeile])
def lesen(
    person: AngemeldeterBenutzer,
    grenze: int = 200,
    stufe: str = "",
    suche: str = "",
) -> list[Zeile]:
    _nur_betreiber(person)
    return [
        Zeile(
            zeit=z.zeit,
            stufe=z.stufe,
            modul=z.modul,
            meldung=z.meldung,
            vorgang=z.vorgang,
            benutzer=z.benutzer,
        )
        for z in dienst.lesen(min(grenze, 1000), stufe or None, suche or None)
    ]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def leeren(person: AngemeldeterBenutzer) -> None:
    _nur_betreiber(person)
    dienst.leeren()
    logger.warning("The log was cleared by the operator.")


@router.get("/download")
def herunterladen(person: AngemeldeterBenutzer) -> Response:
    """Alle Stände als ZIP — das, was man beim Melden eines Fehlers mitschickt.

    ⚠️ **Im Arbeitsspeicher gebaut, nicht als Datei im Datenverzeichnis.**
    Eine Zwischendatei dort landete sonst in der nächsten Sicherung und
    verdoppelte sie — und niemand räumt sie weg.
    """
    _nur_betreiber(person)

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        aktuell = dienst.datei()
        if aktuell.is_file():
            archiv.write(aktuell, aktuell.name)
        for alt in dienst.alte_dateien():
            archiv.write(alt, alt.name)

    logger.info("The log was downloaded by the operator.")
    return Response(
        content=puffer.getvalue(),
        media_type="application/zip",
        headers={"content-disposition": 'attachment; filename="nexmail-protokoll.zip"'},
    )
