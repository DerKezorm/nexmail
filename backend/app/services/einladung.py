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
from html import escape
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Einladung
from . import benutzer as benutzerdienst
from . import mailvorlage, systempost

logger = logging.getLogger("nexmail.einladung")

#: ⚠️ **Nicht laenger.** Eine Einladung, die einen Monat gilt, liegt einen
#: Monat lang in einem Postfach, das vielleicht nicht mehr nur dem Eingeladenen
#: gehoert. Wer sie verpasst, bekommt eine neue — das kostet einen Klick.
GUELTIG_TAGE = 7


class EinladungsFehler(Exception):
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
    db: Session, *, benutzername: str, adresse: str, anzeigename: str = ""
) -> tuple[Einladung, str]:
    """Eine Einladung anlegen. Gibt den Klartext-Schluessel **einmal** zurueck."""
    benutzername = benutzername.strip()
    benutzerdienst.benutzername_pruefen(benutzername)

    if benutzerdienst.finden(db, benutzername) is not None:
        raise EinladungsFehler("Diesen Benutzernamen gibt es schon.")

    adresse = adresse.strip()
    if "@" not in adresse:
        raise EinladungsFehler("Das sieht nicht nach einer E-Mail-Adresse aus.")

    # ⚠️ Eine offene Einladung auf denselben Namen wird ersetzt, nicht
    # verdoppelt: Sonst gelten zwei Links fuer dasselbe Konto, und der aeltere
    # bleibt gueltig, obwohl der Betreiber gerade einen neuen verschickt hat.
    for alte in offene(db):
        if alte.benutzername.lower() == benutzername.lower():
            db.delete(alte)

    schluessel = secrets.token_urlsafe(32)
    einladung = Einladung(
        schluessel_hash=_hash(schluessel),
        benutzername=benutzername,
        anzeigename=anzeigename.strip() or benutzername,
        adresse=adresse,
        laeuft_ab=_jetzt() + timedelta(days=GUELTIG_TAGE),
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


def einloesen(db: Session, schluessel: str, passwort: str) -> Benutzer:
    """Die Einladung annehmen und daraus ein Konto machen."""
    einladung = finden(db, schluessel)
    if einladung is None:
        raise EinladungsFehler(
            "Diese Einladung gilt nicht mehr. Bitte um eine neue — sie ist nach "
            f"{GUELTIG_TAGE} Tagen abgelaufen oder wurde schon benutzt."
        )

    # ⚠️ **Der Name wird hier noch einmal geprueft.** Zwischen Einladung und
    # Annahme koennen Tage liegen; in der Zeit kann ihn jemand anders belegt
    # haben. Ohne diese Pruefung scheitert das Anlegen mit einer Meldung, die
    # dem Eingeladenen nichts sagt.
    if benutzerdienst.finden(db, einladung.benutzername) is not None:
        raise EinladungsFehler(
            "Dieser Benutzername ist inzwischen vergeben. Der Betreiber muss "
            "neu einladen."
        )

    neuer = benutzerdienst.anlegen(
        db,
        einladung.benutzername,
        passwort,
        anzeigename=einladung.anzeigename,
    )
    einladung.eingeloest = _jetzt()
    db.commit()
    logger.info("An invitation was redeemed.")
    return neuer


def verschicken(db: Session, einladung: Einladung, schluessel: str, adresse_der_app: str) -> None:
    """Die Einladungsmail senden. Wirft ``systempost.PostFehler``.

    ⚠️ **Text und HTML, nicht entweder-oder.** Der Textteil steht zuerst und
    traegt denselben Link wie der Knopf: Wer einen Nur-Text-Client benutzt,
    einen Bildblocker hat oder vorlesen laesst, haette sonst eine Einladung
    ohne Weg hinein.

    ⚠️ **Das Logo haengt an der Mail** (``cid:``), es wird nicht von einem
    Server geholt. Ein nachgeladenes Bild waere ein Zaehlpixel — und nexmail
    klinkt genau solche in fremder Post aus.
    """
    link = f"{adresse_der_app.rstrip('/')}/einladung/{schluessel}"

    text = (
        f"Hallo {einladung.anzeigename},\n\n"
        "du wurdest zu nexmail eingeladen — einem selbstgehosteten "
        "E-Mail-Client.\n\n"
        f"Dein Benutzername: {einladung.benutzername}\n\n"
        "Über diesen Link vergibst du dein Kennwort:\n"
        f"{link}\n\n"
        f"Der Link gilt {GUELTIG_TAGE} Tage.\n\n"
        "Wenn du damit nichts anfangen kannst, ignoriere diese Mail.\n"
    )

    html = mailvorlage.rahmen(
        ueberschrift=f"Hallo {escape(einladung.anzeigename)}",
        absaetze=[
            "du wurdest zu <strong>nexmail</strong> eingeladen — einem "
            "selbstgehosteten E-Mail-Client.",
            f"Dein Benutzername ist <strong>{escape(einladung.benutzername)}</strong>. "
            "Über den Knopf vergibst du dein Kennwort.",
        ],
        knopf=("Kennwort vergeben", link),
        fusszeile=(
            f"Der Link gilt {GUELTIG_TAGE} Tage. Wenn du damit nichts anfangen "
            "kannst, ignoriere diese Mail — es passiert dann nichts."
        ),
    )
    systempost.senden(db, einladung.adresse, "Deine Einladung zu nexmail", text, html)
