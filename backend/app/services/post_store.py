"""Die Anbindung des gemeinsamen Mailmoduls (``app.vendor.nexpost``) an nexmails Systempostausgang.

Nur fuer **Systemmails** (Einladung, Passwort vergessen, Adresse bestaetigen, Bescheide, Neue Anmeldung, Testmail),
nie fuer die Post der Menschen: die geht wie bisher ueber die eingerichteten Postfaecher.

⚠️ **Die Einstellungen bleiben, wo sie sind** (``einstellung``, Schluessel ``system_smtp_*``, Passwort versiegelt mit
dem Kontext ``system:smtp_passwort``, ``services/systempost``): Ein Postausgang von vorher gilt ohne Zutun weiter.
Die Verschluesselung heisst bei nexmail ``starttls``/``ssl``/``keine``, im Modul ``starttls``/``tls``/``none``.

⚠️ **Die Outbox** (Tabelle ``post_ausgang``) holt Versuche nach 1, 5, 15, 60, 180 Minuten nach; der Takt ruft
``abarbeiten`` jede Minute, und gleich nach dem Einreihen versucht es die Anfrage selbst einmal, damit ein Link nicht
erst eine Minute spaeter ankommt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..models import PostAusgang
from ..vendor import nexpost
from ..vendor.nexpost.model import Letter, MailSettings, MailStatus, OutboxItem
from . import systempost

logger = logging.getLogger("nexmail.post")

ZU_MODUL = {"ssl": "tls", "starttls": "starttls"}
ZU_NEXMAIL = {"tls": "ssl", "starttls": "starttls", "none": "keine"}

S_OK = "post_zuletzt_ok"
S_FEHLER = "post_letzter_fehler"
S_FEHLER_AM = "post_letzter_fehler_am"


def einrichten() -> None:
    from .mailvorlage import LOGO

    nexpost.configure(
        nexpost.AppConfig(app_name="nexmail", display_name="nexmail", logo=LOGO.read_bytes(), logger_name="nexmail.post")
    )


einrichten()


def _zeit(roh: str) -> datetime | None:
    try:
        return datetime.fromisoformat(roh) if roh else None
    except ValueError:
        return None


def _bewusst(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class PostStore:
    """``nexpost.Store`` ueber nexmails Tabellen, in einer Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def mail_settings(self) -> MailSettings:
        angaben = systempost.lesen(self.db)
        sicherheit = ZU_MODUL.get((angaben.sicherheit or "").lower(), "none")
        return MailSettings(
            host=angaben.server,
            port=angaben.port,
            security=sicherheit,
            user=angaben.benutzer,
            password=systempost.passwort_lesen(self.db),
            sender=angaben.absender,
            sender_name=angaben.absendername,
        )

    def save_mail_settings(self, settings: MailSettings, password: str | None) -> None:
        systempost.schreiben(
            self.db,
            systempost.Postausgang(
                server=settings.host,
                port=settings.port,
                sicherheit=ZU_NEXMAIL.get(settings.security, "keine"),
                benutzer=settings.user,
                absender=settings.sender,
                absendername=settings.sender_name,
            ),
            password,
        )

    def add_to_outbox(self, letter: Letter, now: datetime) -> int:
        zeile = PostAusgang(
            an=letter.to, betreff=letter.subject, text=letter.text, html=letter.html, art=letter.kind,
            angelegt=now, naechster=now,
        )
        self.db.add(zeile)
        self.db.flush()
        return zeile.id

    def _eintrag(self, z: PostAusgang) -> OutboxItem:
        return OutboxItem(
            id=z.id,
            letter=Letter(to=z.an, subject=z.betreff, text=z.text, html=z.html, kind=z.art),
            created_at=_bewusst(z.angelegt),
            next_at=_bewusst(z.naechster) if z.naechster else _bewusst(z.angelegt),
            attempts=z.versuche,
            error=z.fehler,
        )

    def due(self, now: datetime, limit: int) -> list[OutboxItem]:
        zeilen = self.db.scalars(
            select(PostAusgang)
            .where(PostAusgang.verschickt.is_(None), PostAusgang.naechster.is_not(None), PostAusgang.naechster <= now)
            .order_by(PostAusgang.angelegt)
            .limit(limit)
        )
        return [self._eintrag(z) for z in zeilen]

    def claim(self, item_id: int | str, now: datetime, until: datetime) -> bool:
        ergebnis = self.db.execute(
            update(PostAusgang)
            .where(
                PostAusgang.id == int(item_id),
                PostAusgang.verschickt.is_(None),
                PostAusgang.naechster.is_not(None),
                PostAusgang.naechster <= now,
            )
            .values(naechster=until)
        )
        return int(ergebnis.rowcount or 0) == 1

    def mark_sent(self, item_id: int | str) -> None:
        self.db.execute(
            update(PostAusgang).where(PostAusgang.id == int(item_id)).values(verschickt=datetime.now(timezone.utc))
        )

    def mark_failed(self, item_id: int | str, attempts: int, next_at: datetime | None, error: str) -> None:
        self.db.execute(
            update(PostAusgang)
            .where(PostAusgang.id == int(item_id))
            .values(versuche=attempts, naechster=next_at, fehler=error[:500])
        )

    def note_result(self, status: MailStatus) -> None:
        einstellung_schreiben(self.db, S_OK, status.last_ok_at.isoformat() if status.last_ok_at else "")
        einstellung_schreiben(self.db, S_FEHLER, status.last_error or "")
        einstellung_schreiben(self.db, S_FEHLER_AM, status.last_error_at.isoformat() if status.last_error_at else "")

    def mail_status(self) -> MailStatus:
        return MailStatus(
            last_ok_at=_zeit(einstellung_lesen(self.db, S_OK)),
            last_error=einstellung_lesen(self.db, S_FEHLER),
            last_error_at=_zeit(einstellung_lesen(self.db, S_FEHLER_AM)),
        )

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def einreihen(db: Session, brief: Letter) -> None:
    """In die Outbox und gleich ein Versuch. Was scheitert, holt der Takt nach; die Antwort an den Menschen haengt
    nicht daran."""
    store = PostStore(db)
    nexpost.outbox.queue(store, brief)
    store.commit()
    try:
        nexpost.outbox.run_once(store)
    except Exception:  # noqa: BLE001 - der Takt versucht es wieder
        store.rollback()
        logger.warning("Sending from the outbox failed; it tries again later.", exc_info=True)


def abarbeiten() -> int:
    """Der Arbeiter des Takts: was faellig ist, hinaus."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        return nexpost.outbox.run_once(PostStore(db))
