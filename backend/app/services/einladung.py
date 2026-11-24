"""Einladungen: wie ein zweiter Mensch in nexmail hineinkommt.

⚠️ **Kein offenes Anmelden.** nexmail ist keine Plattform, sondern der
Mail-Client eines Haushalts. Wer hinein darf, entscheidet der Betreiber — und
er entscheidet es einzeln, nicht durch einen Schalter „Registrierung offen".

⚠️ **Der Schluessel steht in der Mail und nur als Hash in der Datenbank.** Er
oeffnet ein Konto, ist also ein Passwort. Wer die Datei liest, soll damit
nichts anfangen koennen — dieselbe Regel wie bei den Wiederherstellungscodes.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Einladung
from ..meldung import Meldung

logger = logging.getLogger("nexmail.einladung")

#: Ab Werk; der Betreiber waehlt 1, 7 oder 30 Tage (``nexkonten.invites.INVITE_DAYS``).
GUELTIG_TAGE = 7


class EinladungsFehler(Meldung):
    """Mit einem Satz, den man dem Betreiber oder dem Eingeladenen zeigt."""


def _hash(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode()).hexdigest()


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def offene(db: Session) -> list[Einladung]:
    """Alle, die noch niemand angenommen hat — abgelaufene inbegriffen.

    ⚠️ **Abgelaufene bleiben sichtbar.** Sonst verschwindet eine Einladung
    lautlos, und der Betreiber wartet auf jemanden, der nie einen gueltigen
    Link hatte.
    """
    zeilen = db.execute(
        select(Einladung).where(Einladung.eingeloest.is_(None)).order_by(Einladung.angelegt.desc())
    )
    return list(zeilen.scalars().all())


def abgelaufen(einladung: Einladung) -> bool:
    ablauf = einladung.laeuft_ab
    if ablauf.tzinfo is None:
        ablauf = ablauf.replace(tzinfo=timezone.utc)
    return ablauf < _jetzt()


def aussprechen(
    db: Session,
    *,
    adresse: str = "",
    anzeigename: str = "",
    laeuft_ab: datetime | None = None,
    benutzername: str = "",
) -> tuple[Einladung, str]:
    """Eine Einladung anlegen, mit Werten, die das Kontenmodul schon geprueft hat (``invites.invite_values``).
    Gibt den Klartext-Schluessel **einmal** zurueck.

    ⚠️ **Kein Benutzername mehr** (Kontenmodul): Den waehlt der Eingeladene selbst. ``benutzername`` gibt es nur noch
    fuer Tests, die eine offene Einladung von vorher nachstellen.
    """
    from datetime import timedelta

    laeuft_ab = laeuft_ab or _jetzt() + timedelta(days=GUELTIG_TAGE)
    # ⚠️ Eine offene Einladung an dieselbe Adresse wird ersetzt, nicht verdoppelt: Sonst gelten zwei Links fuer
    # denselben Menschen, und der aeltere bleibt gueltig, obwohl der Betreiber gerade einen neuen verschickt hat.
    if adresse:
        for alte in offene(db):
            if (alte.adresse or "").lower() == adresse.lower():
                db.delete(alte)

    schluessel = secrets.token_urlsafe(32)
    einladung = Einladung(
        schluessel_hash=_hash(schluessel),
        benutzername=benutzername,
        anzeigename=anzeigename,
        adresse=adresse,
        laeuft_ab=laeuft_ab,
    )
    db.add(einladung)
    db.commit()
    logger.info("An invitation was created.")
    return einladung, schluessel


def finden(db: Session, schluessel: str) -> Einladung | None:
    zeile = db.execute(
        select(Einladung).where(Einladung.schluessel_hash == _hash(schluessel))
    ).scalar_one_or_none()
    if zeile is None or zeile.eingeloest is not None or abgelaufen(zeile):
        return None
    return zeile
