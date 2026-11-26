"""Sicherung herunterladen und einspielen.

Seit dem Modul ``sicherung`` (bauplaene/sicherung 1.0.1) zwei Wege:

``/api/server/storage``  die Wege des Moduls (Speicher, Liste, Zeitplan, Jetzt sichern, Hochladen, Prüfen,
                         Herunterladen, Wiederherstellen, Löschen), wie in allen nex-Apps; die Seite ruft sie.
``/api/sicherung``       nexmails alte Wege in ihrer alten Form, jetzt als dünne Hüllen über dem Modul: die Liste der
                         Rücksetzpunkte, Anlegen, Entfernen, das schlanke Archiv, der Zeitplan, Erstellen, Prüfen und
                         Einspielen (auch vor der Einrichtung).

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
from ..db import hat_benutzer
from ..deps import AktiveSitzung, AngemeldeterBenutzer, Betreiber, DbSession
from ..models import Benutzer
from ..services import sicherung, sicherung_haken, sicherungsliste
from ..vendor import nexsicherung
from ..vendor.nexsicherung import routes as sicherung_wege
from ..services.adresse import mit_vorbau
from ..meldung import MeldungHttp

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

    ⚠️ **Wie beim Schema: nur von einem Proxy, dem nexmail traut, und nur der
    rechteste Wert** (``NEXMAIL_CLIENT_IP=proxy[:n]``). Den rechten hängt der nächste Proxy an, alles links davon kann der
    Anfragende selbst geschrieben haben. Das Schema selbst liest hier niemand
    mehr aus der Kopfzeile: ``SchemaVomProxyMiddleware`` hat es nach derselben
    Regel schon in ``request.url`` gesetzt.
    """
    wirt = ""
    if get_settings().anzahl_proxys() > 0:
        werte = [
            teil.strip()
            for zeile in request.headers.getlist("x-forwarded-host")
            for teil in zeile.split(",")
            if teil.strip()
        ]
        wirt = werte[-1][:200] if werte else ""
    if not wirt:
        wirt = request.headers.get("host", "").strip()
    if not wirt:
        return ""
    return f"{request.url.scheme}://{wirt}".rstrip("/")


def _rueckleitpfad(anbieter: dict) -> str:
    """Der Rueckleitpfad, den der Anbieter eines Eintrags kennt.

    ``redirect_path`` fehlt (Archiv von 0.21) oder ist NULL: ein Eintrag von 0.21, sein Anbieter kennt
    ``/api/oidc/<kuerzel>/zurueck``. Leer: der Standard des Moduls. Sonst der eigene Pfad des Eintrags.
    """
    kuerzel = anbieter.get("kuerzel", "")
    pfad = anbieter.get("redirect_path")
    if pfad is None:
        return f"/api/oidc/{kuerzel}/zurueck"
    if pfad:
        return pfad
    return "/api/oidc/callback" if kuerzel == "oidc" else f"/api/oidc/{kuerzel}/callback"


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
                    f"{mit_vorbau(roh['adresse_jetzt'], basis)}{_rueckleitpfad(a)}"
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
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler

    return Response(
        content=daten,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{sicherung.archiv_name()}"'},
    )


#: Wie viel je Schritt gelesen wird. Dieselbe Blockgroesse wie beim
#: mbox-Upload in ``routers/austausch.py``.
UPLOAD_BLOCK = 1024 * 1024


async def _gelesen(datei: UploadFile) -> bytes:
    """Die hochgeladene Sicherung, aber nur bis zur Grenze.

    ⚠️ **Gezaehlt wird WAEHREND des Lesens, nicht danach.** Bis zum
    03.09.2026 stand hier ``daten = await datei.read()`` und die Pruefung eine
    Zeile spaeter — die Grenze griff also erst, wenn die ganze Datei schon im
    Arbeitsspeicher lag. Bei ``MAX_BYTES = 512 MB`` heisst das: Der Container
    hat sich das Halbe-Gigabyte genommen, bevor er ablehnt.

    ⚠️ **Und dieser Weg ist vor der Ersteinrichtung offen.**
    ``/api/sicherung/einspielen-vor-einrichtung`` nimmt einen Upload **ohne
    Anmeldung** entgegen; das steht so begruendet in ``OEFFENTLICHE_PFADE``.
    Genau deshalb ist es hier mehr als eine Aufraeumarbeit.

    Der Nachbarrouter macht es seit jeher richtig
    (``routers/austausch.py``, mbox-Upload) — hier stand nur die andere
    Reihenfolge.
    """
    teile: list[bytes] = []
    gelesen = 0
    while block := await datei.read(UPLOAD_BLOCK):
        gelesen += len(block)
        if gelesen > MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="archiv_zu_gross",
            )
        teile.append(block)
    return b"".join(teile)


async def _pruefen(request: Request, datei: UploadFile, passwort: str) -> Befund:
    daten = await _gelesen(datei)
    try:
        roh = sicherung.pruefen(daten, passwort, _adresse_aus_anfrage(request))
    except sicherung.SicherungFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return _befund_bauen(roh)


async def _einspielen(datei: UploadFile, passwort: str, adresse: str | None) -> Ergebnis:
    daten = await _gelesen(datei)
    try:
        ergebnis = sicherung.wiederherstellen(daten, passwort, adresse)
    except sicherung.SicherungFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
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


def _einrichtungscode_pruefen(request: Request, db, code: str) -> None:
    """⚠️ **Vor der Einrichtung schuetzt der Einrichtungscode auch diesen Weg** (Kontenmodul): Wer eine Sicherung
    einspielt, ist danach Betreiber, mit den Konten darin. Ohne Code waere der Code an der Einrichtung Zierde. 404,
    sobald es ein Konto gibt, wie bisher."""
    from ..services import anmeldebremse
    from ..services import konten_store as kontenstore
    from ..vendor import nexkonten

    if hat_benutzer(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    wache = anmeldebremse.torwaechter(request, "einrichtung", "-")
    try:
        nexkonten.setup.check_code(kontenstore.store_fuer(db), code)
    except nexkonten.AccountError as fehler:
        wache.fehlgeschlagen()
        raise kontenstore.http(fehler) from fehler
    wache.geschafft()


@router.post("/pruefen-vor-einrichtung", response_model=Befund)
async def pruefen_vor_einrichtung(
    request: Request,
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
    einrichtungscode: str = Form(""),
) -> Befund:
    _einrichtungscode_pruefen(request, db, einrichtungscode)
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
    # Seit dem Modul sicherung auch hier: erst der jetzige Stand als Sicherung („vor einer Änderung"), dann das Archiv.
    daten = await _gelesen(datei)
    try:
        sicherung.pruefen(daten, passwort, "")
    except sicherung.SicherungFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    nexsicherung.archives.create(kind=nexsicherung.UPDATE, note="before restoring an uploaded archive")
    try:
        ergebnis = sicherung.wiederherstellen(daten, passwort, adresse or None)
    except sicherung.SicherungFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return Ergebnis(**ergebnis)


@router.post("/einspielen-vor-einrichtung", response_model=Ergebnis)
async def einspielen_vor_einrichtung(
    request: Request,
    db: DbSession,
    datei: UploadFile = File(...),
    passwort: str = Form(...),
    adresse: str = Form(""),
    einrichtungscode: str = Form(""),
) -> Ergebnis:
    """Eine Sicherung auf einer frischen Installation einspielen, mit dem Einrichtungscode."""
    _einrichtungscode_pruefen(request, db, einrichtungscode)
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
    #: Seit dem Modul 1 bis 365 (vorher 1 bis 50).
    behalten: int = Field(default=sicherungsliste.BEHALTEN_VORGABE, ge=1, le=365)


class Uebersicht(BaseModel):
    eintraege: list[Ruecksetzpunkt]
    zeitplan: Zeitplan
    zuletzt: str


class Anlegen(BaseModel):
    kommentar: str = Field(default="", max_length=200)


def _zeitplan_lesen(db=None) -> Zeitplan:  # noqa: ARG001
    plan = nexsicherung.plan.load()
    return Zeitplan(takt=sicherung_haken.EVERY_ZU_TAKT.get(plan.every, "aus"), behalten=plan.keep)


def _alt(eintrag: nexsicherung.Entry) -> Ruecksetzpunkt:
    return Ruecksetzpunkt(
        name=eintrag.name,
        groesse=eintrag.size,
        erstellt=eintrag.created,
        art=sicherung_haken.KIND_ZU_ART.get(eintrag.kind, "manuell"),
        kommentar=eintrag.note,
        version=eintrag.version,
    )


def _nicht_gefunden(fehler: nexsicherung.BackupError) -> MeldungHttp:  # noqa: ARG001
    """Wie vorher: eine Sicherung, die es nicht (mehr) gibt, ist 404 ``ruecksetzpunkt_weg``."""
    return MeldungHttp(status.HTTP_404_NOT_FOUND, "ruecksetzpunkt_weg", {})


@router.get("/liste", response_model=Uebersicht)
def uebersicht(_: Betreiber) -> Uebersicht:
    """Alle Sicherungen in der alten Form (auch die des Moduls); ``zuletzt`` ist die neueste geplante."""
    eintraege = [e for e in nexsicherung.archives.entries() if e.readable]
    geplant = next((e for e in eintraege if e.kind == nexsicherung.SCHEDULED), None)
    return Uebersicht(
        eintraege=[_alt(e) for e in eintraege],
        zeitplan=_zeitplan_lesen(),
        zuletzt=geplant.created if geplant else "",
    )


@router.post("/liste", response_model=Ruecksetzpunkt, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Anlegen, _: Betreiber) -> Ruecksetzpunkt:
    try:
        pfad = nexsicherung.archives.create(kind=nexsicherung.MANUAL, note=eingabe.kommentar, wait=False)
    except nexsicherung.BackupError as fehler:
        raise MeldungHttp(fehler.status, fehler.code, {}) from fehler
    eintrag = next(e for e in nexsicherung.archives.entries() if e.name == pfad.name)
    return _alt(eintrag)


@router.delete("/liste/{name}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(name: str, _: Betreiber) -> Response:
    try:
        nexsicherung.archives.remove(name)
    except nexsicherung.BackupError as fehler:
        raise _nicht_gefunden(fehler) from fehler
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/liste/{name}/archiv")
def archiv_aus_punkt(name: str, eingabe: Passwort, _: Betreiber) -> Response:
    """Eine Sicherung als schlankes, verschlüsseltes Archiv herunterladen (der Haken ``download`` des Moduls).

    ⚠️ Was hinausgeht, ist **nicht** die Datei aus der Liste: Die Nachrichten bleiben draußen.
    """
    try:
        quelle = nexsicherung.archives.path_of(name)
        datei = nexsicherung.current().hooks.download(quelle, archive_password=eingabe.passwort)
    except nexsicherung.BackupError as fehler:
        # Wie vorher: ein Name, der keiner ist, ist hier eine Ablehnung (400), kein 404.
        raise MeldungHttp(status.HTTP_400_BAD_REQUEST, "name_unbekannt", {}) from fehler
    except sicherung.SicherungFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    try:
        daten = datei.read_bytes()
    finally:
        if datei != quelle:
            datei.unlink(missing_ok=True)
    return Response(
        content=daten,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{quelle.stem}.zip"'},
    )


@router.put("/zeitplan", response_model=Zeitplan)
def zeitplan_setzen(eingabe: Zeitplan, _: Betreiber) -> Zeitplan:
    if eingabe.takt not in sicherungsliste.TAKTE:
        raise MeldungHttp(
            status.HTTP_400_BAD_REQUEST,
            "takt_unbekannt",
            {"moeglich": list(sicherungsliste.TAKTE)},
        )
    jetzt = nexsicherung.plan.load()
    nexsicherung.plan.save(
        nexsicherung.plan.checked(sicherung_haken.TAKT_ZU_EVERY[eingabe.takt], jetzt.time, eingabe.behalten)
    )
    return eingabe


# --- Die Wege des Moduls (``/api/server/storage``) ------------------------------------------------------------------


def betreiber_fuer_sicherung(request: Request, sitzung: AktiveSitzung, db: DbSession) -> Benutzer:
    """Nur der Betreiber, und **ohne offene Verbindung der Anfrage**.

    ⚠️ Wiederherstellen tauscht die Datenbank im laufenden Betrieb (restore = "now"). Hielte diese Anfrage noch eine
    Verbindung auf die Datei, bliebe unter Linux ein Schreiber an einer gelöschten Datei zurück (siehe
    ``db.datenbank_ersetzen``). Deshalb wird die Sitzung der Anfrage hier geschlossen; das Konto bleibt lesbar
    (``expire_on_commit=False``)."""
    person = sitzung.benutzer
    if not person.ist_betreiber:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="nur_betreiber")
    request.state.nexmail_angemeldet_um = sitzung.angelegt
    db.close()
    return person


def _ablehnung(kennung: str) -> dict[str, str]:
    """Die Form, die die Seite des Moduls liest (``detail.code``)."""
    return {"code": kennung}


def _bestaetigen(request: Request, person: Benutzer, passwort: str) -> None:
    """Das Passwort des Betreibers noch einmal (Herunterladen, Wiederherstellen, Löschen, Hochladen), an der Bremse
    des Kontenmoduls (``confirm:<Konto>``). Ein Konto ohne Passwort braucht eine frische Anmeldung beim Anbieter."""
    from ..services import anmeldebremse
    from ..services import benutzer as benutzerdienst
    from ..vendor import nexkonten

    if not person.passwort_hash:
        if not nexkonten.common.fresh_sign_in(getattr(request.state, "nexmail_angemeldet_um", None)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ablehnung("fresh_sign_in_needed"),
            )
        return
    wache = anmeldebremse.bestaetigen(person.id)
    if not benutzerdienst.passwort_stimmt(person, passwort):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_ablehnung("wrong_password"),
        )
    wache.geschafft()


modul_router = sicherung_wege.router(
    operator=betreiber_fuer_sicherung,
    confirm=_bestaetigen,
    prefix="/api/server/storage",
)
