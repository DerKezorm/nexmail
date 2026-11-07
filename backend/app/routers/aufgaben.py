"""Aufgaben — Mails, die noch etwas von einem wollen."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Nachricht
from ..services import aufgaben as dienst
from ..services import aufgabenziele, nextasks, todoist, webhook
from ..meldung import MeldungHttp
from .nachrichten import _koerper_sicherstellen

router = APIRouter(prefix="/api/aufgaben", tags=["aufgaben"])


class Zeile(BaseModel):
    id: int
    #: Die **aktuelle** Kennung der Mail, frisch nachgeschlagen. ``null``
    #: heisst: Die Mail ist nicht mehr da.
    nachricht_id: int | None
    konto_id: str
    betreff: str
    von_name: str
    von_adresse: str
    mail_datum: datetime | None
    erledigt: datetime | None
    faellig: datetime | None
    #: ⚠️ Die Aufgabe bleibt, die Mail ist weg. Die Oberflaeche sagt das —
    #: sonst klickt man ins Leere und haelt nexmail fuer kaputt.
    verwaist: bool


class ZeileVoll(Zeile):
    """Die Zeile samt dem, was eine Todo-App dazu weiss.

    ⚠️ **Eine eigene Form, nicht mehr Felder an ``Zeile``.** ``Zeile`` ist
    auch die Antwort von ``POST /api/app/1/tasks`` und steht im Abdruck der
    iPhone-Schnittstelle; ein neues Feld dort waere eine Vertragsaenderung.
    """

    #: Leer heisst: nexmails eigene Aufgabe.
    fern_art: str = ""
    fern_url: str = ""
    fern_liste: str = ""
    #: In der App geloescht — die Zeile sagt es, statt zu verschwinden.
    fern_geloescht: bool = False
    #: ⚠️ ``False`` nach dem Trennen der Verbindung: Dann wird nicht mehr
    #: abgeglichen, und der Haken hier ist nur noch ein eigener.
    fern_verbunden: bool = False


class Wunsch(BaseModel):
    nachricht_id: int


class ZielWunsch(BaseModel):
    nachricht_id: int
    #: Leer heisst: nexmails eigene Liste. Sonst ``<verbindung>:<liste>``.
    ziel: str = Field(default="", max_length=200)
    #: Leer heisst: der Betreff der Mail.
    titel: str = Field(default="", max_length=500)
    #: Nur zum Anzeigen hier („Todoist › Arbeit"); die App kennt ihre Namen.
    liste_name: str = Field(default="", max_length=200)
    faellig: date | None = None
    #: Wie der Browser nexmail erreicht — nur, wenn keine oeffentliche Adresse
    #: eingestellt ist, fuer den Link zurueck zur Mail.
    adresse: str = Field(default="", max_length=500)


class Angelegt(BaseModel):
    aufgabe: ZeileVoll
    #: ``False``: Zu dieser Mail gab es schon eine Aufgabe, und das ist sie.
    neu: bool


class MailFund(BaseModel):
    nachricht_id: int


class Aenderung(BaseModel):
    erledigt: bool | None = None
    #: ⚠️ Nicht mitgeschickt heisst **unveraendert**; ``null`` ausdruecklich
    #: „kein Datum". Ohne den Unterschied verloere jedes Abhaken die
    #: Faelligkeit.
    faellig: datetime | None = None
    faellig_setzen: bool = False


class Sortierung(BaseModel):
    ids: list[int] = Field(default_factory=list)


def _zeile(s: dienst.Sicht) -> Zeile:
    return Zeile(**_voll(s).model_dump(include=set(Zeile.model_fields)))


def _voll(s: dienst.Sicht) -> ZeileVoll:
    a = s.aufgabe
    return ZeileVoll(
        id=a.id,
        nachricht_id=s.nachricht_id,
        konto_id=a.konto_id,
        betreff=a.betreff,
        von_name=a.von_name,
        von_adresse=a.von_adresse,
        mail_datum=a.mail_datum,
        erledigt=a.erledigt,
        faellig=a.faellig,
        verwaist=s.verwaist,
        fern_art=a.fern_art,
        fern_url=a.fern_url,
        fern_liste=a.fern_liste,
        fern_geloescht=a.fern_geloescht,
        fern_verbunden=bool(a.fern_art and a.verbindung_id),
    )


#: ⚠️ **Was der Mensch an der Verbindung beheben muss**, nie 401: Bei 401
#: meldet die Oberflaeche aus nexmail ab. nextasks sagt zudem, wenn der
#: Betreiber dort die Schnittstelle abgeschaltet hat, der Token nur lesen darf,
#: es zu alt ist, die Liste fehlt oder die Aufgabe in einem Bereich liegt, den
#: der Token nicht sieht.
NEU_VERBINDEN = (
    "todoist_zugang_ungueltig",
    "nextasks_zugang_ungueltig",
    "nextasks_api_aus",
    "nextasks_nur_lesen",
    "nextasks_zu_alt",
    "nextasks_nicht_erlaubt",
    "nextasks_liste_unbekannt",
    "nextasks_konflikt",
)


def _status(fehler: Exception) -> int:
    """⚠️ **Ein abgelehnter Token ist kein 401.** Die Oberflaeche meldet bei
    401 aus nexmail ab; der Mensch soll die Todo-App neu verbinden, nicht sich
    selbst neu anmelden."""
    kennung = getattr(fehler, "kennung", "")
    if kennung in NEU_VERBINDEN:
        return status.HTTP_409_CONFLICT
    if kennung in ("todoist_zu_viele_anfragen", "nextasks_zu_viele_anfragen"):
        return status.HTTP_429_TOO_MANY_REQUESTS
    if isinstance(fehler, todoist.TodoistFehler) and kennung != "todoist_zugang_fehlt":
        return status.HTTP_502_BAD_GATEWAY
    # ⚠️ Eine Adresse, die nexmail nicht ansprechen darf, ist eine Eingabe,
    # kein Ausfall des Empfaengers.
    if isinstance(fehler, webhook.WebhookFehler) and not kennung.startswith("webhook_adresse_"):
        return status.HTTP_502_BAD_GATEWAY
    if isinstance(fehler, nextasks.NextasksFehler) and not (
        kennung.startswith("nextasks_adresse_") or kennung == "nextasks_zugang_fehlt"
    ):
        return status.HTTP_502_BAD_GATEWAY
    if kennung in ("aufgabe_unbekannt", "nachricht_unbekannt", "aufgabenverbindung_unbekannt"):
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


def _frisch(db, person, aufgabe_id: int) -> ZeileVoll:
    # Frisch nachschlagen: Die Mail kann inzwischen umgezogen sein.
    # ⚠️ Mit Gesendetem: Auch eine Mail, die nur an einen Webhook ging, soll
    # sagen koennen, wohin.
    for sicht in dienst.alle(db, person, mit_gesendeten=True):
        if sicht.aufgabe.id == aufgabe_id:
            return _voll(sicht)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("", response_model=list[ZeileVoll])
def liste(person: AngemeldeterBenutzer, db: DbSession) -> list[ZeileVoll]:
    return [_voll(s) for s in dienst.alle(db, person)]


@router.post("/mit-ziel", response_model=Angelegt)
def mit_ziel(wunsch: ZielWunsch, person: AngemeldeterBenutzer, db: DbSession) -> Angelegt:
    """Eine Aufgabe dort anlegen, wo der Mensch sie haben will."""
    try:
        aufgabe, neu = aufgabenziele.anlegen(
            db,
            person,
            wunsch.nachricht_id,
            ziel=wunsch.ziel,
            titel=wunsch.titel,
            liste_name=wunsch.liste_name,
            faellig=wunsch.faellig,
            vom_browser=wunsch.adresse,
            koerper=lambda n: _koerper_sicherstellen(db, n),
        )
    except (dienst.AufgabenFehler, aufgabenziele.ZielFehler, *aufgabenziele.AppFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return Angelegt(aufgabe=_frisch(db, person, aufgabe.id), neu=neu)


@router.post("/abgleichen", status_code=status.HTTP_204_NO_CONTENT)
def abgleichen(person: AngemeldeterBenutzer, db: DbSession) -> None:
    """Beim Oeffnen der Liste nachsehen, was die Todo-Apps sagen.

    ⚠️ **Kein Fehler nach aussen.** Klemmt eine App, steht das an ihrer
    Verbindung; die Liste zeigt dann den letzten Stand, statt rot zu werden.
    """
    aufgabenziele.abgleichen(db, person, beim_oeffnen=True)


@router.get("/mail", response_model=MailFund)
def mail_finden(
    person: AngemeldeterBenutzer,
    db: DbSession,
    message_id: str = Query(min_length=1, max_length=500),
) -> MailFund:
    """Der Link aus einer Todo-App: von der ``Message-ID`` zur Mail, wo sie
    heute liegt. ⚠️ **Nur in der eigenen Post** — eine fremde Kennung findet
    nichts, und die Antwort ist dieselbe wie bei einer, die es nicht gibt."""
    treffer = db.scalars(
        select(Nachricht.id)
        .where(Nachricht.benutzer_id == person.id, Nachricht.message_id == message_id)
        .order_by(Nachricht.id.desc())
        .limit(1)
    ).first()
    if treffer is None:
        raise MeldungHttp(status.HTTP_404_NOT_FOUND, "nachricht_unbekannt")
    return MailFund(nachricht_id=treffer)


@router.post("", response_model=Zeile, status_code=status.HTTP_201_CREATED)
def anlegen(wunsch: Wunsch, person: AngemeldeterBenutzer, db: DbSession) -> Zeile:
    try:
        aufgabe = dienst.anlegen(db, person, wunsch.nachricht_id)
    except dienst.AufgabenFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler
    return _zeile(dienst.Sicht(aufgabe=aufgabe, nachricht_id=aufgabe.nachricht_id, verwaist=False))


@router.put("/reihenfolge", status_code=status.HTTP_204_NO_CONTENT)
def ordnen(wunsch: Sortierung, person: AngemeldeterBenutzer, db: DbSession) -> None:
    """⚠️ **Vor ``/{aufgabe_id}``**, sonst schluckt die Kennung dieses Wort.

    FastAPI nimmt die erste passende Route. Stuende sie darunter, landete
    „reihenfolge" als Kennung in ``aufgabe_id`` und gaebe eine
    Pydantic-Meldung ueber eine kaputte Zahl.
    """
    dienst.ordnen(db, person, wunsch.ids)


@router.patch("/{aufgabe_id}", response_model=ZeileVoll)
def aendern(
    aufgabe_id: int, wunsch: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> ZeileVoll:
    try:
        if wunsch.erledigt is not None:
            aufgabenziele.abhaken(db, person, aufgabe_id, wunsch.erledigt)
        if wunsch.faellig_setzen:
            aufgabenziele.faelligkeit(db, person, aufgabe_id, wunsch.faellig)
        aufgabe = dienst.eine(db, person, aufgabe_id)
    except (dienst.AufgabenFehler, aufgabenziele.ZielFehler, *aufgabenziele.AppFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _frisch(db, person, aufgabe.id)


@router.delete("/{aufgabe_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(aufgabe_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        dienst.entfernen(db, person, aufgabe_id)
    except dienst.AufgabenFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler
