"""Sicherung herunterladen und einspielen.

⚠️ **Einspielen geht auch ohne Anmeldung — aber nur vor der Einrichtung.** Wer
eine Sicherung hat, will sie auf einer frischen Installation einspielen, und da
gibt es noch kein Konto. Der Weg schließt zum selben Zeitpunkt wie das Anlegen
des ersten Kontos: sobald **ein** Benutzer existiert.

Danach führt derselbe Vorgang über die angemeldete Adresse. Zwei Endpunkte für
dieselbe Sache — das ist Absicht: Die Rechte sind verschieden, und ein
Endpunkt, der „mal so, mal so" prüft, ist der Ort, an dem sich Fehler
verstecken.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from ..db import hat_benutzer
from ..deps import AngemeldeterBenutzer, DbSession
from ..services import sicherung

logger = logging.getLogger("nexmail.sicherung")

router = APIRouter(prefix="/api/sicherung", tags=["sicherung"])

#: Maximalgröße einer hochgeladenen Sicherung. Ohne Grenze lädt jemand eine
#: 40-GB-Datei hoch und der Container geht am Arbeitsspeicher aus.
MAX_BYTES = 512 * 1024 * 1024


class Passwort(BaseModel):
    passwort: str = Field(min_length=8, max_length=200)


class Ergebnis(BaseModel):
    schluessel_ersetzt: bool


@router.post("/erstellen")
def erstellen(eingabe: Passwort, _: AngemeldeterBenutzer) -> Response:
    """Ein verschlüsseltes Archiv zum Herunterladen.

    Kein GET: Das Passwort stünde sonst in der Adresszeile und damit im
    Browserverlauf und in jedem Proxy-Protokoll.
    """
    try:
        daten = sicherung.archiv(eingabe.passwort)
    except sicherung.SicherungFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    return Response(
        content=daten,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{sicherung.archiv_name()}"'},
    )


async def _einspielen(datei: UploadFile, passwort: str) -> Ergebnis:
    daten = await datei.read()
    if len(daten) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Die Datei ist zu groß für eine nexmail-Sicherung.",
        )
    try:
        ergebnis = sicherung.wiederherstellen(daten, passwort)
    except sicherung.SicherungFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return Ergebnis(**ergebnis)


@router.post("/einspielen", response_model=Ergebnis)
async def einspielen_angemeldet(
    _: AngemeldeterBenutzer,
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
) -> Ergebnis:
    """Eine Sicherung über die bestehende Installation legen.

    ⚠️ Danach sind alle Sitzungen weg — auch die eigene. Die Datenbank, in der
    sie standen, gibt es nicht mehr. Das ist kein Fehler, sondern die Folge,
    und die Oberfläche sagt es vorher.

    ⚠️ **Erst die eigene Verbindung schließen.** Diese Anfrage hält selbst eine
    offene Sitzung auf die Datei, die gleich ersetzt wird - und solange hält
    SQLite die Begleitdatei ``-wal`` fest. Unter Windows scheitert das Löschen
    sichtbar (genau so ist der erste Testlauf hier abgebrochen), unter Linux
    ginge es still durch und ließe einen Schreiber an einer gelöschten Datei
    zurück. Das Schließen ist also keine Windows-Rücksicht, sondern die
    Behebung. ``engine.dispose()`` allein genügt nicht: Es räumt den Vorrat,
    nicht die gerade entliehene Verbindung.
    """
    db.close()
    return await _einspielen(datei, passwort)


@router.post("/einspielen-vor-einrichtung", response_model=Ergebnis)
async def einspielen_vor_einrichtung(
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
) -> Ergebnis:
    """Eine Sicherung auf einer frischen Installation einspielen."""
    if hat_benutzer(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Die eigene Sitzung schließen, bevor die Datei darunter ausgetauscht wird.
    db.close()
    return await _einspielen(datei, passwort)
