"""Todo-Apps — Einstellungen des BENUTZERS, nicht der Verwaltung.

⚠️ **Je Benutzer.** Jeder verbindet seine eigenen Apps mit seinem eigenen
Token; der Betreiber gibt nichts vor und sieht nichts davon.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import MeldungHttp
from ..services import anmeldebremse, aufgabenziele, nextasks, todoist, webhook
from .aufgaben import _status

router = APIRouter(prefix="/api/aufgabenziele", tags=["aufgabenziele"])


class Verbindung(BaseModel):
    id: str
    art: str
    name: str
    #: ⚠️ **Nicht der Token**, nur ob die App ihn zuletzt angenommen hat.
    fehler: str
    angelegt: datetime
    zuletzt_abgeglichen: datetime | None


class Stand(BaseModel):
    #: Leer heisst: nexmails eigene Liste.
    standard: str
    verbindungen: list[Verbindung]


class Neu(BaseModel):
    art: str = Field(max_length=20)
    zugang: str = Field(min_length=1, max_length=500)
    name: str = Field(default="", max_length=80)


class Standard(BaseModel):
    ziel: str = Field(default="", max_length=200)


class Liste(BaseModel):
    ziel: str
    name: str


class Gruppe(BaseModel):
    verbindung_id: str
    art: str
    name: str
    fehler: str
    listen: list[Liste]


def _verbindung(v) -> Verbindung:
    return Verbindung(
        id=v.id,
        art=v.art,
        name=v.name,
        fehler=v.letzter_fehler,
        angelegt=v.angelegt,
        zuletzt_abgeglichen=v.zuletzt_abgeglichen,
    )


def _stand(db, person) -> Stand:
    return Stand(
        standard=aufgabenziele.standard_von(db, person),
        verbindungen=[_verbindung(v) for v in aufgabenziele.verbindungen(db, person)],
    )


@router.get("", response_model=Stand)
def stand(person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    return _stand(db, person)


@router.post("", response_model=Verbindung, status_code=status.HTTP_201_CREATED)
def verbinden(eingabe: Neu, person: AngemeldeterBenutzer, db: DbSession) -> Verbindung:
    """⚠️ **Die Bremse fehlt hier mit Absicht**, anders als bei der Modellliste
    des KI-Dienstes: Die Adresse steht im Code (Todoist), nicht in der
    Anfrage. nexmail laesst sich hierueber nicht auf fremde Server lenken."""
    try:
        v = aufgabenziele.verbinden(db, person, eingabe.art, eingabe.zugang, eingabe.name)
    except (aufgabenziele.ZielFehler, todoist.TodoistFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _verbindung(v)


@router.delete("/{verbindung_id}", status_code=status.HTTP_204_NO_CONTENT)
def trennen(verbindung_id: str, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        aufgabenziele.trennen(db, person, verbindung_id)
    except aufgabenziele.ZielFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler


@router.put("/standard", response_model=Stand)
def standard(eingabe: Standard, person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    try:
        aufgabenziele.standard_setzen(db, person, eingabe.ziel)
    except aufgabenziele.ZielFehler as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _stand(db, person)


@router.get("/listen", response_model=list[Gruppe])
def listen(person: AngemeldeterBenutzer, db: DbSession) -> list[Gruppe]:
    """Alle waehlbaren Listen, je Verbindung live geholt. Die eigene Liste
    steht nicht darin; die kennt die Oberflaeche selbst."""
    return [
        Gruppe(
            verbindung_id=g.verbindung_id,
            art=g.art,
            name=g.name,
            fehler=g.fehler,
            listen=[Liste(ziel=l.ziel, name=l.name) for l in g.listen],
        )
        for g in aufgabenziele.ziele(db, person)
    ]


# --- Webhook ------------------------------------------------------------------ #


class WebhookNeu(BaseModel):
    url: str = Field(min_length=1, max_length=webhook.MAX_ADRESSE)
    name: str = Field(default="", max_length=80)
    #: Leer heisst: nexmail erzeugt eins.
    geheimnis: str = Field(default="", max_length=webhook.MAX_GEHEIMNIS)
    nur_senden: bool = False
    mit_text: bool = False


class WebhookVerbunden(BaseModel):
    verbindung: Verbindung
    #: ⚠️ **Genau einmal, hier.** Danach zeigt nexmail es nicht mehr.
    geheimnis: str


class WebhookAenderung(BaseModel):
    url: str = Field(min_length=1, max_length=webhook.MAX_ADRESSE)
    nur_senden: bool = False
    mit_text: bool = False


class WebhookEinstellung(BaseModel):
    url: str
    nur_senden: bool
    mit_text: bool
    #: Ob der Betreiber den Text der Mail freigegeben hat. Ohne Freigabe
    #: bleibt ``mit_text`` gespeichert, wirkt aber nicht.
    mailtext_erlaubt: bool


def _bremse(request: Request, person) -> None:
    """⚠️ **Hier steht die Bremse**, anders als beim Todoist-Token: Die
    Adresse kommt aus der Anfrage. Gezaehlt wird jeder Aufruf, nicht nur ein
    gescheiterter, wie bei der Modellliste des KI-Dienstes; begrenzt werden
    soll ja der Aufruf, der hinausgeht."""
    anmeldebremse.torwaechter(request, "webhook", person.benutzername).fehlgeschlagen()


def _einstellung(db, s: aufgabenziele.WebhookStand) -> WebhookEinstellung:
    return WebhookEinstellung(
        url=s.url,
        nur_senden=s.nur_senden,
        mit_text=s.mit_text,
        mailtext_erlaubt=webhook.mailtext_erlaubt(db),
    )


@router.post("/webhook", response_model=WebhookVerbunden, status_code=status.HTTP_201_CREATED)
def webhook_verbinden(
    eingabe: WebhookNeu, request: Request, person: AngemeldeterBenutzer, db: DbSession
) -> WebhookVerbunden:
    _bremse(request, person)
    try:
        v, geheimnis = aufgabenziele.webhook_verbinden(
            db,
            person,
            eingabe.url,
            name=eingabe.name,
            geheimnis=eingabe.geheimnis,
            nur_senden=eingabe.nur_senden,
            mit_text=eingabe.mit_text,
        )
    except (aufgabenziele.ZielFehler, webhook.WebhookFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return WebhookVerbunden(verbindung=_verbindung(v), geheimnis=geheimnis)


@router.get("/{verbindung_id}/webhook", response_model=WebhookEinstellung)
def webhook_lesen(verbindung_id: str, person: AngemeldeterBenutzer, db: DbSession) -> WebhookEinstellung:
    try:
        return _einstellung(db, aufgabenziele.webhook_stand(db, person, verbindung_id))
    except (aufgabenziele.ZielFehler, webhook.WebhookFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler


@router.put("/{verbindung_id}/webhook", response_model=WebhookEinstellung)
def webhook_aendern(
    verbindung_id: str,
    eingabe: WebhookAenderung,
    request: Request,
    person: AngemeldeterBenutzer,
    db: DbSession,
) -> WebhookEinstellung:
    _bremse(request, person)
    try:
        s = aufgabenziele.webhook_aendern(
            db,
            person,
            verbindung_id,
            url=eingabe.url,
            nur_senden=eingabe.nur_senden,
            mit_text=eingabe.mit_text,
        )
    except (aufgabenziele.ZielFehler, webhook.WebhookFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _einstellung(db, s)


@router.post("/{verbindung_id}/test", status_code=status.HTTP_204_NO_CONTENT)
def webhook_testen(
    verbindung_id: str, request: Request, person: AngemeldeterBenutzer, db: DbSession
) -> None:
    """Der Knopf „Test senden": ein ``ping``, und der Status, wenn es nicht 2xx war."""
    _bremse(request, person)
    try:
        aufgabenziele.webhook_testen(db, person, verbindung_id)
    except (aufgabenziele.ZielFehler, webhook.WebhookFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler

# --- nextasks ----------------------------------------------------------------- #


class NextasksNeu(BaseModel):
    url: str = Field(min_length=1, max_length=nextasks.MAX_ADRESSE)
    token: str = Field(min_length=1, max_length=nextasks.MAX_TOKEN)
    name: str = Field(default="", max_length=80)


class NextasksAenderung(BaseModel):
    url: str = Field(min_length=1, max_length=nextasks.MAX_ADRESSE)
    token: str = Field(min_length=1, max_length=nextasks.MAX_TOKEN)


class NextasksEinstellung(BaseModel):
    #: ⚠️ **Nur die Adresse**, nie der Token.
    url: str


def _nextasks_bremse(request: Request, person) -> None:
    """⚠️ **Mit Bremse wie beim Webhook**: Die Adresse kommt aus der Anfrage,
    und jeder Aufruf geht hinaus."""
    anmeldebremse.torwaechter(request, "nextasks", person.benutzername).fehlgeschlagen()


@router.post("/nextasks", response_model=Verbindung, status_code=status.HTTP_201_CREATED)
def nextasks_verbinden(
    eingabe: NextasksNeu, request: Request, person: AngemeldeterBenutzer, db: DbSession
) -> Verbindung:
    _nextasks_bremse(request, person)
    try:
        v = aufgabenziele.nextasks_verbinden(db, person, eingabe.url, eingabe.token, eingabe.name)
    except (aufgabenziele.ZielFehler, nextasks.NextasksFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _verbindung(v)


@router.get("/{verbindung_id}/nextasks", response_model=NextasksEinstellung)
def nextasks_lesen(verbindung_id: str, person: AngemeldeterBenutzer, db: DbSession) -> NextasksEinstellung:
    try:
        return NextasksEinstellung(url=aufgabenziele.nextasks_adresse(db, person, verbindung_id))
    except (aufgabenziele.ZielFehler, nextasks.NextasksFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler


@router.put("/{verbindung_id}/nextasks", response_model=Verbindung)
def nextasks_aendern(
    verbindung_id: str,
    eingabe: NextasksAenderung,
    request: Request,
    person: AngemeldeterBenutzer,
    db: DbSession,
) -> Verbindung:
    """Neuer Token (oder neue Adresse) an derselben Verbindung. Die Aufgaben
    bleiben dran; gespeichert wird erst, wenn nextasks ihn annimmt."""
    _nextasks_bremse(request, person)
    try:
        v = aufgabenziele.nextasks_aendern(db, person, verbindung_id, eingabe.url, eingabe.token)
    except (aufgabenziele.ZielFehler, nextasks.NextasksFehler) as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return _verbindung(v)
