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

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import einstellung_lesen, einstellung_schreiben, hat_benutzer
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..services import sicherung, sicherungsliste

logger = logging.getLogger("nexmail.sicherung")

router = APIRouter(prefix="/api/sicherung", tags=["sicherung"])

#: Maximalgröße einer hochgeladenen Sicherung. Ohne Grenze lädt jemand eine
#: 40-GB-Datei hoch und der Container geht am Arbeitsspeicher aus.
MAX_BYTES = 512 * 1024 * 1024


class Passwort(BaseModel):
    passwort: str = Field(min_length=8, max_length=200)


class Ergebnis(BaseModel):
    schluessel_ersetzt: bool
    adresse_gesetzt: str | None = None


class Anbieter(BaseModel):
    kuerzel: str
    anzeigename: str
    issuer: str
    rueckkehr_adresse: str


class Befund(BaseModel):
    """Was das Einspielen täte — erhoben, bevor irgendetwas ersetzt ist."""

    version: str
    erstellt: str
    schluessel_dabei: bool
    nachrichten_entfernt: int
    adresse_im_archiv: str
    adresse_jetzt: str
    adresse_weicht_ab: bool
    oidc_anbieter: list[Anbieter]


def _adresse_aus_anfrage(request: Request) -> str:
    """Über welche Adresse diese Anfrage hereinkam.

    ⚠️ **Hinter einem Proxy steht die echte Adresse nur in den Kopfzeilen.**
    ``request.url`` zeigt dort auf den Container — ``http://nexmail:8000`` —,
    und ein Vergleich damit meldete bei *jeder* Wiederherstellung eine
    Abweichung. Ein Hinweis, der immer erscheint, wird nach dem zweiten Mal
    weggeklickt.

    ⚠️ **Die Kopfzeilen sind fremde Eingabe.** Sie werden hier nur *angezeigt*
    und zur Auswahl gestellt — es hängt keine Rechteentscheidung daran. Wer sie
    fälscht, schlägt dem Betreiber eine falsche Adresse vor, die dieser
    ablehnen kann; er setzt sie nicht selbst.
    """
    schema = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    wirt = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if not wirt:
        wirt = request.headers.get("host", "").strip()
    if not wirt:
        return ""
    if not schema:
        schema = request.url.scheme
    return f"{schema}://{wirt}".rstrip("/")


def _befund_bauen(roh: dict) -> Befund:
    basis = get_settings().url_base
    return Befund(
        **{k: v for k, v in roh.items() if k != "oidc_anbieter"},
        oidc_anbieter=[
            Anbieter(
                kuerzel=a.get("kuerzel", ""),
                anzeigename=a.get("anzeigename", ""),
                issuer=a.get("issuer", ""),
                # Die Adresse, die beim Anbieter stehen muss, wenn die
                # Installation umgezogen ist. nexmail kann sie dort nicht
                # eintragen - also nennt es sie wenigstens.
                rueckkehr_adresse=(
                    f"{roh['adresse_jetzt']}{basis}/api/oidc/{a.get('kuerzel', '')}/zurueck"
                    if roh.get("adresse_jetzt")
                    else ""
                ),
            )
            for a in roh.get("oidc_anbieter", [])
        ],
    )


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


async def _gelesen(datei: UploadFile) -> bytes:
    daten = await datei.read()
    if len(daten) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Die Datei ist zu groß für eine nexmail-Sicherung.",
        )
    return daten


async def _pruefen(request: Request, datei: UploadFile, passwort: str) -> Befund:
    daten = await _gelesen(datei)
    try:
        roh = sicherung.pruefen(daten, passwort, _adresse_aus_anfrage(request))
    except sicherung.SicherungFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return _befund_bauen(roh)


async def _einspielen(datei: UploadFile, passwort: str, adresse: str | None) -> Ergebnis:
    daten = await _gelesen(datei)
    try:
        ergebnis = sicherung.wiederherstellen(daten, passwort, adresse)
    except sicherung.SicherungFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return Ergebnis(**ergebnis)


@router.post("/pruefen", response_model=Befund)
async def pruefen_angemeldet(
    request: Request,
    _: AngemeldeterBenutzer,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
) -> Befund:
    """Was das Einspielen täte. **Es wird nichts angefasst.**"""
    return await _pruefen(request, datei, passwort)


@router.post("/pruefen-vor-einrichtung", response_model=Befund)
async def pruefen_vor_einrichtung(
    request: Request,
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
) -> Befund:
    if hat_benutzer(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return await _pruefen(request, datei, passwort)


@router.post("/einspielen", response_model=Ergebnis)
async def einspielen_angemeldet(
    _: AngemeldeterBenutzer,
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
    adresse: str = Form(""),
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
    return await _einspielen(datei, passwort, adresse or None)


@router.post("/einspielen-vor-einrichtung", response_model=Ergebnis)
async def einspielen_vor_einrichtung(
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
    adresse: str = Form(""),
) -> Ergebnis:
    """Eine Sicherung auf einer frischen Installation einspielen."""
    if hat_benutzer(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Die eigene Sitzung schließen, bevor die Datei darunter ausgetauscht wird.
    db.close()
    return await _einspielen(datei, passwort, adresse or None)


# --- Ruecksetzpunkte auf dem Server --------------------------------------- #
#
# ⚠️ **Nur der Betreiber.** Eine Kopie der Datenbank enthaelt die Postfaecher
# *aller* Benutzer. Was fuer das Einspielen gilt, gilt hier schon beim Anlegen.


class Ruecksetzpunkt(BaseModel):
    name: str
    groesse: int
    erstellt: str
    art: str
    kommentar: str
    version: str


class Zeitplan(BaseModel):
    takt: str = Field(default="aus")
    behalten: int = Field(default=sicherungsliste.BEHALTEN_VORGABE, ge=1, le=50)


class Uebersicht(BaseModel):
    eintraege: list[Ruecksetzpunkt]
    zeitplan: Zeitplan
    zuletzt: str


class Anlegen(BaseModel):
    kommentar: str = Field(default="", max_length=200)


def _zeitplan_lesen(db) -> Zeitplan:
    takt = einstellung_lesen(db, sicherungsliste.SCHLUESSEL_TAKT) or "aus"
    behalten = einstellung_lesen(db, sicherungsliste.SCHLUESSEL_BEHALTEN)
    return Zeitplan(
        takt=takt if takt in sicherungsliste.TAKTE else "aus",
        behalten=int(behalten) if behalten.isdigit() else sicherungsliste.BEHALTEN_VORGABE,
    )


@router.get("/liste", response_model=Uebersicht)
def uebersicht(_: Betreiber, db: DbSession) -> Uebersicht:
    return Uebersicht(
        eintraege=[Ruecksetzpunkt(**e) for e in sicherungsliste.liste()],
        zeitplan=_zeitplan_lesen(db),
        zuletzt=einstellung_lesen(db, sicherungsliste.SCHLUESSEL_ZULETZT),
    )


@router.post("/liste", response_model=Ruecksetzpunkt, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Anlegen, _: Betreiber, db: DbSession) -> Ruecksetzpunkt:
    eintrag = sicherungsliste.anlegen("manuell", eingabe.kommentar)
    sicherungsliste.aufraeumen(_zeitplan_lesen(db).behalten)
    return Ruecksetzpunkt(**eintrag)


@router.delete("/liste/{name}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(name: str, _: Betreiber) -> Response:
    try:
        sicherungsliste.entfernen(name)
    except sicherung.SicherungFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/liste/{name}/archiv")
def archiv_aus_punkt(name: str, eingabe: Passwort, _: Betreiber) -> Response:
    """Einen Rücksetzpunkt als schlanke, verschlüsselte Sicherung herunterladen.

    ⚠️ Was hinausgeht, ist **nicht** die Datei aus der Liste: Die Nachrichten
    bleiben draußen. Die Größe in der Tabelle ist die des Rücksetzpunkts.
    """
    try:
        daten = sicherungsliste.archiv_aus(name, eingabe.passwort)
    except sicherung.SicherungFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    return Response(
        content=daten,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{name[:-3]}.zip"'},
    )


@router.put("/zeitplan", response_model=Zeitplan)
def zeitplan_setzen(eingabe: Zeitplan, _: Betreiber, db: DbSession) -> Zeitplan:
    if eingabe.takt not in sicherungsliste.TAKTE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannter Takt. Möglich sind: {', '.join(sicherungsliste.TAKTE)}.",
        )
    einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, eingabe.takt)
    einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_BEHALTEN, str(eingabe.behalten))
    db.commit()
    sicherungsliste.aufraeumen(eingabe.behalten)
    return eingabe
