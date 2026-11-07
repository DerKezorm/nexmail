"""Die Schnittstelle fuer andere Anwendungen: lesen mit einem API-Schluessel.

Gebaut fuer Dashboards wie nexdeck. Drei Adressen lesen:

* ``GET /api/v1/me`` - wem der Schluessel gehoert, was er darf, welche
  Postfaecher er sieht. Daraus baut ein Dashboard seine Auswahlliste.
* ``GET /api/v1/summary`` - ungelesene Mails im Posteingang, je Postfach.
* ``GET /api/v1/messages/latest`` - Absender und Betreff der neuesten Mails.
  Nur mit der Stufe ``betreff``.

Und zwei schreiben, fuer den Empfaenger eines Webhooks (Issue #17):

* ``POST /api/v1/tasks/{id}/complete`` und ``/reopen`` - eine Aufgabe abhaken
  oder wieder oeffnen. Nur mit einem Schluessel, an dem ``aufgaben`` steht,
  und nur Aufgaben aus den Postfaechern am Schluessel.

Und Schlagworte, fuer denselben Empfaenger (Issue #17, zweite Runde):

* ``GET /api/v1/tags`` - die Schlagworte des Besitzers, mit Kennung.
* ``GET /api/v1/tasks/{id}/tags`` - die Schlagworte an der Mail der Aufgabe.
* ``POST`` und ``DELETE /api/v1/tasks/{id}/tags/{tag_id}`` - eines setzen
  oder nehmen. Nur mit einem Schluessel, an dem ``schlagworte`` steht.
  ⚠️ **Geschrieben wird auf den Mailserver**, als IMAP-Keyword, auf dem Weg
  der Oberflaeche (``schlagworte.zuweisen``): erst der Server, dann lokal.

⚠️ **Die Feldnamen sind englisch**, anders als der Rest der Schnittstelle.
Diese Adressen gehoeren nicht der eigenen Oberflaeche, sondern fremden
Programmen, und nach aussen ist nexmail englisch.

⚠️ **Gezaehlt wird im Posteingang, und zwar gezaehlt, nicht abgelesen.**
Dieselbe Regel wie im Ordnerbaum (``routers/konten.py``): ``ordner.ungelesen``
kann veralten, die Nachrichten selbst nicht. Die Zahl ist so frisch wie der
letzte Abgleich mit dem Mailserver.

⚠️ **Kein Text, keine Anhaenge, keine Empfaenger.** Nicht einmal der
Anreisser. Ein Dashboard haengt oft an einem Bildschirm, den jeder im Raum
sieht; was hier nicht herausgeht, kann dort nicht stehen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from ..deps import ApiZugriff, DbSession
from ..meldung import MeldungHttp
from ..models import Aufgabe, Benutzer, Nachricht, Ordner
from ..services import apischluessel as dienst
from ..services import aufgaben as aufgabendienst
from ..services import aufgabenziele, nextasks, todoist
from ..services import schlagworte as schlagwortdienst

router = APIRouter(prefix="/api/v1", tags=["api-v1"])

POSTEINGANG = "posteingang"

#: Die Stufe heisst intern deutsch; nach aussen geht das englische Wort.
SCOPE = {"anzahl": "count", "betreff": "headers"}


class Mailbox(BaseModel):
    id: str
    name: str
    address: str


class Owner(BaseModel):
    username: str
    display_name: str


class Key(BaseModel):
    name: str
    #: ``count`` or ``headers``.
    scope: str
    #: May complete and reopen tasks.
    tasks: bool = False
    #: May list tags and set them on the message of a task.
    tags: bool = False


class Me(BaseModel):
    user: Owner
    key: Key
    mailboxes: list[Mailbox]


class MailboxSummary(Mailbox):
    unread: int
    #: ``ok``, or ``sign_in_failed`` when the mail server rejects the stored
    #: credentials. The count is stale then.
    status: str


class Summary(BaseModel):
    unread: int
    mailboxes: list[MailboxSummary]


class Message(BaseModel):
    id: int
    mailbox_id: str
    mailbox: str
    from_name: str
    from_address: str
    subject: str
    date: datetime
    unread: bool
    flagged: bool


class Latest(BaseModel):
    messages: list[Message]


def _mailbox(konto) -> Mailbox:
    return Mailbox(id=konto.id, name=konto.anzeigename, address=konto.adresse)


@router.get("/me", response_model=Me)
def me(schluessel: ApiZugriff, db: DbSession) -> Me:
    person = db.get(Benutzer, schluessel.benutzer_id)
    return Me(
        user=Owner(
            username=person.benutzername if person else "",
            display_name=(person.anzeigename if person else "") or "",
        ),
        key=Key(
            name=schluessel.name,
            scope=SCOPE.get(schluessel.stufe, "count"),
            tasks=schluessel.aufgaben,
            tags=schluessel.schlagworte,
        ),
        mailboxes=[_mailbox(k) for k in dienst.freigegebene_konten(db, schluessel)],
    )


@router.get("/summary", response_model=Summary)
def summary(schluessel: ApiZugriff, db: DbSession) -> Summary:
    konten = dienst.freigegebene_konten(db, schluessel)
    ids = [k.id for k in konten]
    zahlen: dict[str, int] = {}
    if ids:
        zeilen = db.execute(
            select(Nachricht.konto_id, func.count())
            .join(Ordner, Ordner.id == Nachricht.ordner_id)
            .where(
                Nachricht.benutzer_id == schluessel.benutzer_id,
                Nachricht.konto_id.in_(ids),
                Nachricht.gelesen.is_(False),
                Ordner.rolle == POSTEINGANG,
            )
            .group_by(Nachricht.konto_id)
        ).all()
        zahlen = {konto_id: anzahl for konto_id, anzahl in zeilen}
    postfaecher = [
        MailboxSummary(
            **_mailbox(k).model_dump(),
            unread=zahlen.get(k.id, 0),
            status="sign_in_failed" if k.stoerung else "ok",
        )
        for k in konten
    ]
    return Summary(unread=sum(p.unread for p in postfaecher), mailboxes=postfaecher)


@router.get("/messages/latest", response_model=Latest)
def latest(
    schluessel: ApiZugriff,
    db: DbSession,
    mailbox: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    unread_only: bool = False,
) -> Latest:
    """Die neuesten Mails im Posteingang, ueber alle oder die genannten Postfaecher.

    ⚠️ **Ein Postfach, das nicht am Schluessel steht, ist unbekannt** - auch
    wenn es dem Besitzer gehoert. Sonst liesse sich die Auswahl am Schluessel
    einfach umgehen.
    """
    if schluessel.stufe != "betreff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="api_schluessel_nur_anzahl")
    konten = {k.id: k for k in dienst.freigegebene_konten(db, schluessel)}
    if mailbox:
        if any(m not in konten for m in mailbox):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="postfach_unbekannt")
        ids = list(dict.fromkeys(mailbox))
    else:
        ids = list(konten)
    if not ids:
        return Latest(messages=[])

    abfrage = (
        select(Nachricht)
        .join(Ordner, Ordner.id == Nachricht.ordner_id)
        .where(
            Nachricht.benutzer_id == schluessel.benutzer_id,
            Nachricht.konto_id.in_(ids),
            Ordner.rolle == POSTEINGANG,
        )
        .order_by(Nachricht.datum.desc(), Nachricht.id.desc())
        .limit(limit)
    )
    if unread_only:
        abfrage = abfrage.where(Nachricht.gelesen.is_(False))

    return Latest(
        messages=[
            Message(
                id=n.id,
                mailbox_id=n.konto_id,
                mailbox=konten[n.konto_id].anzeigename,
                from_name=n.von_name,
                from_address=n.von_adresse,
                subject=n.betreff,
                date=n.datum,
                unread=not n.gelesen,
                flagged=n.markiert,
            )
            for n in db.scalars(abfrage)
        ]
    )


class Task(BaseModel):
    id: str
    #: What the receiver of the webhook answered to ``task.created``, if anything.
    external_id: str | None
    title: str
    done: bool
    completed_at: datetime | None


def _aufgabe(schluessel, db, task_id: str) -> Aufgabe:
    """⚠️ **Eine fremde Aufgabe sieht aus wie eine, die es nicht gibt**, und
    ebenso eine aus einem Postfach, das nicht am Schluessel steht."""
    aufgabe = db.get(Aufgabe, int(task_id)) if task_id.isdigit() and len(task_id) < 18 else None
    konten = {k.id for k in dienst.freigegebene_konten(db, schluessel)}
    if aufgabe is None or aufgabe.benutzer_id != schluessel.benutzer_id or aufgabe.konto_id not in konten:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="aufgabe_unbekannt")
    return aufgabe


def _haken(schluessel, db, task_id: str, erledigt: bool) -> Task:
    if not schluessel.aufgaben:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="api_schluessel_ohne_aufgaben")
    aufgabe = _aufgabe(schluessel, db, task_id)
    person = db.get(Benutzer, schluessel.benutzer_id)
    try:
        aufgabe = aufgabenziele.von_aussen_abhaken(db, person, aufgabe, erledigt)
    except (todoist.TodoistFehler, nextasks.NextasksFehler) as fehler:
        # Eine Aufgabe in Todoist oder nextasks geht erst dorthin; lehnt es ab,
        # bleibt der Haken.
        raise MeldungHttp.aus(fehler, status.HTTP_502_BAD_GATEWAY) from fehler
    return Task(
        id=str(aufgabe.id),
        external_id=aufgabe.fern_id or None,
        title=aufgabe.betreff,
        done=aufgabe.erledigt is not None,
        completed_at=aufgabe.erledigt,
    )


@router.post("/tasks/{task_id}/complete", response_model=Task)
def complete(task_id: str, schluessel: ApiZugriff, db: DbSession) -> Task:
    """Eine Aufgabe abhaken. Schon erledigt bleibt erledigt, mit der alten Zeit."""
    return _haken(schluessel, db, task_id, True)


@router.post("/tasks/{task_id}/reopen", response_model=Task)
def reopen(task_id: str, schluessel: ApiZugriff, db: DbSession) -> Task:
    return _haken(schluessel, db, task_id, False)

# --- Schlagworte -------------------------------------------------------------- #


class Tag(BaseModel):
    id: int
    name: str
    #: The IMAP keyword on the mail server. Fixed, also when the tag is renamed.
    keyword: str


class Tags(BaseModel):
    tags: list[Tag]


class TaskTags(BaseModel):
    task_id: str
    #: The tags on the message of the task, now.
    tags: list[Tag]


def _schlagworte_erlaubt(schluessel) -> None:
    if not schluessel.schlagworte:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="api_schluessel_ohne_schlagworte")


def _mails(schluessel, db, task_id: str):
    """Die Aufgabe, ihr Besitzer und jede Fassung ihrer Mail.

    ⚠️ **Ohne Mail 409, nicht 404.** Die Aufgabe gibt es, nur ihre Mail nicht
    mehr (geloescht, oder in ein Postfach gewandert, das nexmail nicht
    abgleicht). Ein 404 hiesse fuer den Empfaenger: falsche Kennung.
    """
    aufgabe = _aufgabe(schluessel, db, task_id)
    person = db.get(Benutzer, schluessel.benutzer_id)
    mails = aufgabendienst.mails_der_aufgabe(db, person, aufgabe)
    if not mails:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="aufgabe_ohne_mail")
    return aufgabe, person, mails


def _task_tags(db, aufgabe: Aufgabe, mails) -> TaskTags:
    return TaskTags(
        task_id=str(aufgabe.id),
        tags=[Tag(**t) for t in schlagwortdienst.fuer_aussen(db, aufgabe.benutzer_id, mails)],
    )


@router.get("/tags", response_model=Tags)
def tags(schluessel: ApiZugriff, db: DbSession) -> Tags:
    """Die Schlagworte des Besitzers, in der Reihenfolge der Einstellungen."""
    _schlagworte_erlaubt(schluessel)
    return Tags(
        tags=[
            Tag(id=z.id, name=z.name, keyword=z.atom)
            for z in schlagwortdienst.meine(db, schluessel.benutzer_id)
        ]
    )


@router.get("/tasks/{task_id}/tags", response_model=TaskTags)
def task_tags(task_id: str, schluessel: ApiZugriff, db: DbSession) -> TaskTags:
    _schlagworte_erlaubt(schluessel)
    aufgabe, _, mails = _mails(schluessel, db, task_id)
    return _task_tags(db, aufgabe, mails)


def _zuweisen(schluessel, db, task_id: str, tag_id: str, setzen: bool) -> TaskTags:
    """⚠️ **Erst der Server, dann lokal**, wie in der Oberflaeche. Kein Echo an
    den Webhook: Schlagworte loesen dort kein Ereignis aus."""
    _schlagworte_erlaubt(schluessel)
    aufgabe, person, mails = _mails(schluessel, db, task_id)
    try:
        if not (tag_id.isdigit() and len(tag_id) < 18):
            raise schlagwortdienst.SchlagwortFehler("schlagwort_unbekannt")
        definition = schlagwortdienst.eines(db, person.id, int(tag_id))
        schlagwortdienst.zuweisen(db, person, mails, definition.atom, setzen)
    except schlagwortdienst.SchlagwortFehler as fehler:
        kennung = str(fehler)
        code = status.HTTP_404_NOT_FOUND if kennung == "schlagwort_unbekannt" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=kennung) from fehler
    db.expire_all()
    return _task_tags(db, aufgabe, aufgabendienst.mails_der_aufgabe(db, person, aufgabe))


@router.post("/tasks/{task_id}/tags/{tag_id}", response_model=TaskTags)
def tag_setzen(task_id: str, tag_id: str, schluessel: ApiZugriff, db: DbSession) -> TaskTags:
    """Ein Schlagwort an die Mail der Aufgabe. Schon gesetzt bleibt gesetzt."""
    return _zuweisen(schluessel, db, task_id, tag_id, True)


@router.delete("/tasks/{task_id}/tags/{tag_id}", response_model=TaskTags)
def tag_nehmen(task_id: str, tag_id: str, schluessel: ApiZugriff, db: DbSession) -> TaskTags:
    return _zuweisen(schluessel, db, task_id, tag_id, False)
