"""Die Schnittstelle fuer andere Anwendungen: lesen mit einem API-Schluessel.

Gebaut fuer Dashboards wie nexdeck. Drei Adressen, alle nur lesend:

* ``GET /api/v1/me`` - wem der Schluessel gehoert, was er darf, welche
  Postfaecher er sieht. Daraus baut ein Dashboard seine Auswahlliste.
* ``GET /api/v1/summary`` - ungelesene Mails im Posteingang, je Postfach.
* ``GET /api/v1/messages/latest`` - Absender und Betreff der neuesten Mails.
  Nur mit der Stufe ``betreff``.

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
from ..models import Benutzer, Nachricht, Ordner
from ..services import apischluessel as dienst

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
        key=Key(name=schluessel.name, scope=SCOPE.get(schluessel.stufe, "count")),
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
