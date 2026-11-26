"""nextime verbinden, seine Kalender und Termine (MAIL-1).

⚠️ **Jede Absage von nextime ist 409, nie 401.** Bei 401 meldet die
Oberfläche den Menschen aus nexmail ab; ein abgelaufener Schlüssel in nextime
ist aber kein abgelaufenes nexmail. Ausnahmen: 429 bleibt 429 (mit
``Retry-After``), „nicht da" ist 404, „nicht erreichbar" 502.

⚠️ **Termine kommen in nexmails Form** (``TerminZeile`` aus ``kalender.py``)
mit dem Zusatz ``fern``. Die Oberfläche legt sie neben die eigenen und
schickt Änderungen an die Wege hier.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import Meldung, MeldungHttp
from ..services import anmeldebremse, nextime, nextimeverbindung as dienst
from .kalender import FernZeile, KalenderZeile, TerminZeile, _sicht
from ..services import termine as termindienst

logger = logging.getLogger("nexmail.nextime")

router = APIRouter(prefix="/api/nextime", tags=["nextime"])

#: Was als 404 hinausgeht statt als 409.
NICHT_DA = ("nextime_nicht_gefunden", "nextime_nicht_verbunden", "kalender_unbekannt")
#: Was als 502 hinausgeht: nextime war nicht zu sprechen.
NETZ = ("nextime_nicht_erreichbar", "nextime_zeitueberschreitung", "nextime_fehler",
        "nextime_antwort_unlesbar", "nextime_weiterleitung")
#: Was eine schlechte Eingabe von hier ist, nicht eine Absage von nextime.
EINGABE = ("termin_ohne_titel", "termin_ende_vor_beginn", "umfang_unbekannt", "vorkommen_fehlt",
           "nextime_regel_nicht_abbildbar", "nextime_zeiten_unvollstaendig",
           "nextime_zeitraum_zu_lang", "nextime_schluessel_fehlt", "nextime_adresse_ungueltig",
           "nextime_adresse_localhost")


def http(f: Meldung) -> MeldungHttp:
    """Eine Meldung aus ``nextime``/``nextimeverbindung`` als Antwort."""
    if f.kennung == "nextime_zu_viele_anfragen":
        return MeldungHttp(
            status.HTTP_429_TOO_MANY_REQUESTS, f.kennung, f.werte,
            headers={"Retry-After": str(f.werte.get("sekunden", nextime.PAUSE_OHNE_ANGABE))},
        )
    if f.kennung in NICHT_DA:
        return MeldungHttp(status.HTTP_404_NOT_FOUND, f.kennung, f.werte)
    if f.kennung in NETZ:
        return MeldungHttp(status.HTTP_502_BAD_GATEWAY, f.kennung, f.werte)
    if f.kennung in EINGABE:
        return MeldungHttp(status.HTTP_400_BAD_REQUEST, f.kennung, f.werte)
    return MeldungHttp(status.HTTP_409_CONFLICT, f.kennung, f.werte)


def _zugangsfehler(db, person, f: Meldung) -> None:
    v = dienst.verbindung(db, person)
    if v is not None:
        dienst.fehler_merken(db, v, f)


# --- Formen --------------------------------------------------------------------- #


class Stand(BaseModel):
    verbunden: bool
    adresse: str = ""
    name: str = ""
    version: str = ""
    #: Eine Kennung, wenn der Zugang zuletzt abgelehnt wurde.
    letzter_fehler: str = ""
    #: Per „Verbinden“ gemacht (Modul verbinden): Schlüssel und Trennen stehen dann in der Karte des Moduls.
    per_klick: bool = False


class Verbinden(BaseModel):
    adresse: str = Field(max_length=nextime.MAX_ADRESSE)
    schluessel: str = Field(max_length=nextime.MAX_TOKEN)


class Verbunden(Stand):
    kalender: int = 0


class Haken(BaseModel):
    #: Der Haken in der Seitenleiste: ein- oder ausgeblendet.
    sichtbar: bool | None = None
    #: Die Auswahl in der Karte: Nimmt nexmail den Kalender überhaupt?
    gewaehlt: bool | None = None


class Neu(BaseModel):
    kalender_id: str = Field(max_length=40)
    titel: str = Field(max_length=100_000)
    beginn: datetime
    ende: datetime | None = None
    ganztaegig: bool = False
    ort: str = Field(default="", max_length=100_000)
    beschreibung: str = Field(default="", max_length=1_000_000)
    rrule: str = Field(default="", max_length=2000)
    #: Eigener Schlüssel für diesen Wunsch: Dasselbe zweimal (Doppelklick)
    #: gibt den Termin vom ersten Mal (MAIL-1 EC-15).
    anfrage: str = Field(default="", max_length=64)


class Aenderung(BaseModel):
    """⚠️ **Nur was sich geändert hat.** ``None`` heißt unverändert; die
    Oberfläche vergleicht mit der Fassung, die sie beim Öffnen geholt hat."""

    titel: str | None = Field(default=None, max_length=100_000)
    beginn: datetime | None = None
    ende: datetime | None = None
    ganztaegig: bool | None = None
    ort: str | None = Field(default=None, max_length=100_000)
    beschreibung: str | None = Field(default=None, max_length=1_000_000)
    rrule: str | None = Field(default=None, max_length=2000)
    zeitzone: str = Field(default="", max_length=64)
    umfang: str = "alle"
    vorkommen: str | None = Field(default=None, max_length=20)
    etag: str = Field(default="", max_length=64)


class Suchergebnis(BaseModel):
    treffer: list[TerminZeile]
    abgeschnitten: bool = False


def _kalender(k: dienst.Kalender) -> KalenderZeile:
    return KalenderZeile(
        id=k.id, name=k.name, farbe=1, sichtbar=k.sichtbar, art="nextime",
        herkunft=k.quelle or "nextime", nur_lesen=not k.beschreibbar, letzter_fehler="",
        gruppe=k.gruppe, farbe_nextime=k.farbe, symbol=k.symbol, standard=k.standard,
        nur_belegt=k.nur_belegt, hintergrund=k.hintergrund, gewaehlt=k.gewaehlt,
    )


def zeile(s: dienst.Sicht) -> TerminZeile:
    """Ein nextime-Vorkommen in nexmails Form, samt ``fern``."""
    z = _sicht(termindienst.Sicht(s.termin, s.beginn, s.ende, s.aus_reihe))
    f = s.fern
    z.fern = FernZeile(
        id=f.id, vorkommen=f.vorkommen, etag=f.etag, link=f.link, beschreibbar=f.beschreibbar,
        nur_belegt=f.nur_belegt, hintergrund=f.hintergrund, uid=f.uid, einladung=f.einladung,
        herkunft=f.herkunft, zeitzone=f.zeitzone,
    )
    return z


# --- Verbindung ------------------------------------------------------------------ #


@router.get("/verbindung", response_model=Stand)
def stand(person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    v = dienst.verbindung(db, person)
    if v is None:
        return Stand(verbunden=False)
    try:
        per_klick = bool(dienst.zugang(v).ueber)
    except Exception:  # noqa: BLE001
        per_klick = False
    return Stand(verbunden=True, adresse=dienst.adresse(v), name=v.name, version=v.version,
                 letzter_fehler=v.letzter_fehler, per_klick=per_klick)


@router.post("/verbindung", response_model=Verbunden)
def verbinden(
    eingabe: Verbinden, request: Request, person: AngemeldeterBenutzer, db: DbSession
) -> Verbunden:
    """Erst ``/me`` und die Kalender, dann speichern (MAIL-1 AC-1, EC-2 bis EC-4).

    ⚠️ **Hinter der Bremse**: Die Adresse kommt aus der Anfrage, und jeder
    Versuch ist eine Anfrage von nexmails Server aus.
    """
    anmeldebremse.torwaechter(request, "nextime", person.benutzername).fehlgeschlagen()
    try:
        v, zahl = dienst.verbinden(db, person, eingabe.adresse, eingabe.schluessel)
    except Meldung as f:
        raise http(f) from f
    return Verbunden(verbunden=True, adresse=dienst.adresse(v), name=v.name, version=v.version,
                     kalender=zahl)


@router.delete("/verbindung", status_code=status.HTTP_204_NO_CONTENT)
def trennen(person: AngemeldeterBenutzer, db: DbSession) -> Response:
    dienst.trennen(db, person)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Kalender und Termine (Termin-Adressen VOR /kalender/{id}) ----------------- #


@router.get("/kalender", response_model=list[KalenderZeile])
def kalender(person: AngemeldeterBenutzer, db: DbSession, alle: bool = False) -> list[KalenderZeile]:
    """Die gewählten nextime-Kalender, mit ``alle`` auch die nicht gewählten
    (für die Auswahl in der Karte)."""
    try:
        v, z = dienst.gebraucht(db, person)
        liste = dienst.kalender_liste(v, nextime.kalender(z), alle=alle)
    except Meldung as f:
        _zugangsfehler(db, person, f)
        raise http(f) from f
    dienst.fehler_merken(db, v, None)
    return [_kalender(k) for k in liste]


@router.patch("/kalender/{kalender_id}", response_model=Haken)
def haken(kalender_id: str, eingabe: Haken, person: AngemeldeterBenutzer, db: DbSession) -> Haken:
    """⚠️ **Nur in nexmail** (MAIL-1 AC-3): In nextime bleibt der Kalender, wie er ist."""
    try:
        v, _z = dienst.gebraucht(db, person)
        if eingabe.sichtbar is not None:
            dienst.sichtbar_setzen(db, v, kalender_id, eingabe.sichtbar)
        if eingabe.gewaehlt is not None:
            dienst.auswahl_setzen(db, v, kalender_id, eingabe.gewaehlt)
    except Meldung as f:
        raise http(f) from f
    return eingabe


@router.get("/termine", response_model=list[TerminZeile])
def fenster(
    person: AngemeldeterBenutzer,
    db: DbSession,
    von: datetime,
    bis: datetime,
    kalender: list[str] | None = Query(default=None),
) -> list[TerminZeile]:
    try:
        return [zeile(s) for s in dienst.fenster(db, person, von, bis, kalender)]
    except Meldung as f:
        _zugangsfehler(db, person, f)
        raise http(f) from f


@router.get("/suche", response_model=Suchergebnis)
def suche(
    person: AngemeldeterBenutzer,
    db: DbSession,
    q: str = Query(max_length=2000),
    kalender: list[str] | None = Query(default=None),
) -> Suchergebnis:
    if len(q.strip()) < 2:
        return Suchergebnis(treffer=[])
    try:
        return Suchergebnis(treffer=[zeile(s) for s in dienst.suchen(db, person, q.strip(), kalender)])
    except Meldung as f:
        raise http(f) from f


@router.get("/stand")
def aenderungsstand(person: AngemeldeterBenutzer, db: DbSession) -> dict[str, str]:
    """nextimes Versionsnummer: Ändert sie sich, lädt die Oberfläche neu (EC-6)."""
    try:
        _v, z = dienst.gebraucht(db, person)
        return {"version": nextime.stand(z)}
    except Meldung as f:
        raise http(f) from f


@router.post("/termine", response_model=TerminZeile, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Neu, person: AngemeldeterBenutzer, db: DbSession) -> TerminZeile:
    try:
        s = dienst.anlegen(
            db, person, eingabe.kalender_id,
            dienst.Eingabe(titel=eingabe.titel, beginn=eingabe.beginn, ende=eingabe.ende,
                           ganztaegig=eingabe.ganztaegig, ort=eingabe.ort,
                           beschreibung=eingabe.beschreibung, rrule=eingabe.rrule),
            client_ref=f"nexmail:{eingabe.anfrage}" if eingabe.anfrage else "",
        )
    except Meldung as f:
        raise http(f) from f
    return zeile(s)


@router.get("/termine/{event_id}", response_model=TerminZeile)
def einzeln(
    event_id: int,
    person: AngemeldeterBenutzer,
    db: DbSession,
    vorkommen: str | None = Query(default=None, max_length=20),
) -> TerminZeile:
    """Ein Termin samt Notiz, Regel, Organisator und Teilnehmern.

    ⚠️ **Vor dem Bearbeiten holen.** Das Fenster liefert keine Notizen; wer
    mit dem leeren Feld speicherte, löschte sie in nextime.
    """
    try:
        return zeile(dienst.einzeln(db, person, event_id, vorkommen))
    except Meldung as f:
        raise http(f) from f


@router.patch("/termine/{event_id}", response_model=TerminZeile)
def aendern(event_id: int, eingabe: Aenderung, person: AngemeldeterBenutzer, db: DbSession) -> TerminZeile:
    try:
        s = dienst.aendern(
            db, person, event_id,
            dienst.Eingabe(titel=eingabe.titel, beginn=eingabe.beginn, ende=eingabe.ende,
                           ganztaegig=eingabe.ganztaegig, ort=eingabe.ort,
                           beschreibung=eingabe.beschreibung, rrule=eingabe.rrule,
                           zeitzone=eingabe.zeitzone),
            umfang=eingabe.umfang, vorkommen=eingabe.vorkommen, etag=eingabe.etag,
        )
    except Meldung as f:
        raise http(f) from f
    return zeile(s)


@router.delete("/termine/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(
    event_id: int,
    person: AngemeldeterBenutzer,
    db: DbSession,
    umfang: str = "alle",
    vorkommen: str | None = Query(default=None, max_length=20),
) -> Response:
    try:
        dienst.entfernen(db, person, event_id, umfang=umfang, vorkommen=vorkommen)
    except Meldung as f:
        raise http(f) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)
