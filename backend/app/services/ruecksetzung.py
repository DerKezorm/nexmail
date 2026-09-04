"""Kennwort vergessen: der einzige Weg zurueck in ein Konto.

⚠️ **Er ist die zweite Tuer neben der Anmeldung.** Wer sie schlecht baut, hebt
die Anmeldung auf: Ein Ruecksetz-Link, der zu lange gilt, zu leicht zu raten
ist oder verraet, welche Namen es gibt, ist ein Generalschluessel mit
Verzoegerung. Deshalb steht hier mehr Vorsicht als Funktion.

⚠️ **Der Schluessel steht in der Mail und nur als Hash in der Datenbank** —
dieselbe Regel wie bei der Einladung und den Wiederherstellungscodes.

⚠️ **Die Antwort ist immer dieselbe.** Ob es den Namen gibt, ob eine
Kontaktadresse hinterlegt ist, ob der Postausgang steht: Nach aussen sieht
alles gleich aus. Sonst wird das Formular zur Namensliste.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..meldung import Meldung
from ..models import Benutzer, Kennwortruecksetzung, Sitzung
from . import benutzer as benutzerdienst
from . import mailvorlage, systempost

logger = logging.getLogger("nexmail.ruecksetzung")

#: ⚠️ **Zwei Stunden, nicht sieben Tage.** Eine Einladung wartet auf jemanden,
#: der vielleicht erst am Wochenende Zeit hat. Ein Ruecksetz-Link entsteht,
#: weil jemand gerade jetzt vor der Tuer steht — und liegt danach in einem
#: Postfach herum.
GUELTIG_STUNDEN = 2


class RuecksetzFehler(Meldung):
    """Etwas, das dem Menschen davor gezeigt werden darf."""


def _hash(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode()).hexdigest()


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def abgelaufen(zeile: Kennwortruecksetzung) -> bool:
    ablauf = zeile.laeuft_ab
    if ablauf.tzinfo is None:
        ablauf = ablauf.replace(tzinfo=timezone.utc)
    return ablauf < _jetzt()


def anfordern(db: Session, benutzername: str, adresse_der_app: str) -> None:
    """Einen Ruecksetz-Link verschicken, wenn es etwas zu verschicken gibt.

    ⚠️ **Gibt nichts zurueck, und wirft nichts.** Weder „den Namen gibt es
    nicht" noch „dort ist keine Adresse hinterlegt" darf nach aussen dringen.
    Wer hier einen Unterschied sehen kann, kann Namen durchprobieren.

    ⚠️ **Auch ein kaputter Postausgang bleibt drin.** Er wird protokolliert,
    nicht gemeldet: Sonst verraet die Fehlermeldung, dass es den Namen gibt.
    """
    person = benutzerdienst.finden(db, benutzername.strip())
    if person is None or not (person.kontaktadresse or "").strip():
        logger.info("A password reset was requested for an account that cannot receive one.")
        return

    # ⚠️ **Ein aelterer offener Link wird ungueltig.** Sonst gelten zwei
    # Schluessel fuer dasselbe Konto, und der aeltere liegt noch in einem
    # Postfach, aus dem der Mensch gerade ausgesperrt ist.
    for alte in db.execute(
        select(Kennwortruecksetzung).where(
            Kennwortruecksetzung.benutzer_id == person.id,
            Kennwortruecksetzung.eingeloest.is_(None),
        )
    ).scalars():
        db.delete(alte)

    schluessel = secrets.token_urlsafe(32)
    zeile = Kennwortruecksetzung(
        schluessel_hash=_hash(schluessel),
        benutzer_id=person.id,
        laeuft_ab=_jetzt() + timedelta(hours=GUELTIG_STUNDEN),
    )
    db.add(zeile)
    db.commit()
    logger.info("A password reset link was created.")

    try:
        verschicken(db, person, schluessel, adresse_der_app)
    except systempost.PostFehler as fehler:
        logger.warning("The password reset mail could not be sent: %s", fehler.kennung)


def finden(db: Session, schluessel: str) -> Kennwortruecksetzung | None:
    zeile = db.execute(
        select(Kennwortruecksetzung).where(
            Kennwortruecksetzung.schluessel_hash == _hash(schluessel)
        )
    ).scalar_one_or_none()
    if zeile is None or zeile.eingeloest is not None or abgelaufen(zeile):
        return None
    return zeile


def einloesen(db: Session, schluessel: str, passwort: str) -> Benutzer:
    """Das neue Kennwort setzen und alle Sitzungen beenden.

    ⚠️ **Dieselbe Meldung fuer „gibt es nicht" und „abgelaufen".** Beides ist
    fuer den Menschen davor derselbe Vorgang: noch einmal anfordern. Ein
    Unterschied waere nur fuer jemanden nuetzlich, der Schluessel durchprobiert.

    ⚠️ **Alle Sitzungen fliegen raus.** Wer sein Kennwort zuruecksetzt, tut es
    oft, weil jemand anders hineingekommen ist. Bliebe dessen Sitzung stehen,
    haette das Zuruecksetzen nichts geaendert.
    """
    zeile = finden(db, schluessel)
    if zeile is None:
        raise RuecksetzFehler("ruecksetzung_ungueltig", stunden=GUELTIG_STUNDEN)

    person = db.get(Benutzer, zeile.benutzer_id)
    if person is None:
        raise RuecksetzFehler("ruecksetzung_ungueltig", stunden=GUELTIG_STUNDEN)

    # ⚠️ **Nicht ``passwort_aendern``.** Das verlangt das alte Kennwort, und
    # genau das hat hier niemand — der Link IST der Beweis.
    benutzerdienst.passwort_pruefen_regeln(passwort)
    person.passwort_hash = benutzerdienst.hashen(passwort)
    zeile.eingeloest = _jetzt()

    for sitzung in db.execute(
        select(Sitzung).where(Sitzung.benutzer_id == person.id)
    ).scalars():
        db.delete(sitzung)

    db.commit()
    logger.info("A password was reset through a link; every session was ended.")
    return person


def verschicken(
    db: Session, person: Benutzer, schluessel: str, adresse_der_app: str
) -> None:
    """Die Mail mit dem Link. Wirft ``systempost.PostFehler``.

    ⚠️ **Text und HTML**, wie bei der Einladung: Wer einen Nur-Text-Client
    benutzt oder vorlesen laesst, haette sonst einen Weg ohne Weg.
    """
    link = f"{adresse_der_app.rstrip('/')}/kennwort/{schluessel}"
    name = person.anzeigename or person.benutzername

    text = (
        f"Hallo {name},\n\n"
        "für dein nexmail-Konto wurde ein neues Kennwort angefordert.\n\n"
        f"Dein Benutzername: {person.benutzername}\n\n"
        "Über diesen Link vergibst du ein neues Kennwort:\n"
        f"{link}\n\n"
        f"Der Link gilt {GUELTIG_STUNDEN} Stunden. Danach musst du ihn neu "
        "anfordern.\n\n"
        "Warst du das nicht, ist nichts passiert: Solange niemand den Link "
        "öffnet, bleibt dein Kennwort, wie es war.\n"
    )

    html = mailvorlage.rahmen(
        ueberschrift=f"Hallo {escape(name)}",
        absaetze=[
            "für dein <strong>nexmail</strong>-Konto wurde ein neues Kennwort "
            "angefordert.",
            f"Dein Benutzername ist <strong>{escape(person.benutzername)}</strong>. "
            "Über den Knopf vergibst du ein neues Kennwort.",
        ],
        knopf=("Neues Kennwort vergeben", link),
        fusszeile=(
            f"Der Link gilt {GUELTIG_STUNDEN} Stunden. Warst du das nicht, ist "
            "nichts passiert: Solange niemand den Link öffnet, bleibt dein "
            "Kennwort, wie es war."
        ),
    )

    systempost.senden(
        db,
        an=person.kontaktadresse,
        betreff="Neues Kennwort für nexmail",
        text=text,
        html=html,
    )
