"""Aufgaben: Mails, die noch etwas von einem wollen.

⚠️ **Eine Aufgabe zeigt auf eine Mail, sie kopiert sie nicht.** Angeklickt
oeffnet sie die Mail; abgehakt bleibt die Mail, wo sie ist. nexmail wird kein
Aufgabenverwalter — es merkt sich nur, was noch offen ist.

⚠️ **Und sie ueberlebt ihre Mail.** Wer im Papierkorb aufraeumt, soll nicht
lautlos seine Aufgabenliste mitloeschen. Eine Aufgabe, die genau dann
verschwindet, wenn man sie braucht, ist schlimmer als keine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Aufgabe, Benutzer, Nachricht
from ..meldung import Meldung

logger = logging.getLogger("nexmail.aufgaben")


class AufgabenFehler(Meldung):
    """Mit einem Satz, den man zeigen kann."""


@dataclass
class Sicht:
    """Eine Aufgabe, wie die Oberflaeche sie braucht.

    ``nachricht_id`` ist die **aktuelle** Kennung, frisch nachgeschlagen —
    nicht die gespeicherte. ``verwaist`` heisst: Die Mail ist nicht mehr da.
    """

    aufgabe: Aufgabe
    nachricht_id: int | None
    verwaist: bool


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _wiederfinden(db: Session, benutzer: Benutzer, aufgabe: Aufgabe) -> Nachricht | None:
    """Die Mail zur Aufgabe — auch wenn sie inzwischen woanders liegt.

    ⚠️ **Zuerst ueber die ``Message-ID``.** Wer eine Mail vom Telefon aus in
    einen anderen Ordner schiebt, bekommt beim naechsten Abgleich eine neue
    Zeile mit neuer Kennung; die gespeicherte zeigt ins Leere. Die
    ``Message-ID`` vergibt der absendende Server und bleibt.

    Nur wenn eine Mail gar keine hat — es gibt solche —, zaehlt die Zeile.
    """
    if aufgabe.message_id:
        treffer = db.execute(
            select(Nachricht).where(
                Nachricht.benutzer_id == benutzer.id,
                Nachricht.message_id == aufgabe.message_id,
            )
        ).scalars().first()
        if treffer is not None:
            return treffer

    if aufgabe.nachricht_id is None:
        return None
    zeile = db.get(Nachricht, aufgabe.nachricht_id)
    return zeile if zeile is not None and zeile.benutzer_id == benutzer.id else None


def alle(db: Session, benutzer: Benutzer) -> list[Sicht]:
    """Offene zuerst, in der gezogenen Reihenfolge; Erledigte darunter.

    ⚠️ **Erledigte verschwinden nicht.** Wer gerade abgehakt hat, will es
    einen Moment lang noch sehen — und wer sich vertan hat, will es
    zurueckholen koennen, ohne die Mail zu suchen.
    """
    zeilen = db.execute(
        select(Aufgabe)
        .where(Aufgabe.benutzer_id == benutzer.id)
        .order_by(
            # SQLite sortiert NULL zuerst — genau richtig: offen vor erledigt.
            Aufgabe.erledigt.is_(None).desc(),
            Aufgabe.reihenfolge,
            Aufgabe.id,
        )
    ).scalars().all()

    heraus: list[Sicht] = []
    for a in zeilen:
        mail = _wiederfinden(db, benutzer, a)
        if mail is not None and mail.id != a.nachricht_id:
            # Die Mail ist umgezogen — die Aufgabe zieht mit.
            a.nachricht_id = mail.id
        heraus.append(
            Sicht(aufgabe=a, nachricht_id=mail.id if mail else None, verwaist=mail is None)
        )
    db.commit()
    return heraus


def anlegen(db: Session, benutzer: Benutzer, nachricht_id: int) -> Aufgabe:
    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != benutzer.id:
        raise AufgabenFehler("nachricht_unbekannt")

    if nachricht.message_id:
        schon = db.execute(
            select(Aufgabe).where(
                Aufgabe.benutzer_id == benutzer.id,
                Aufgabe.message_id == nachricht.message_id,
            )
        ).scalars().first()
        if schon is not None:
            # ⚠️ Kein Fehler. Zweimal „zu Aufgabe machen" ist ein Verklicken,
            # keine Ausnahme — und eine Fehlermeldung dafuer waere Schikane.
            return schon

    # Neue Aufgaben kommen nach oben: Was man gerade vorgemerkt hat, ist das,
    # woran man denkt.
    kleinste = db.execute(
        select(Aufgabe.reihenfolge)
        .where(Aufgabe.benutzer_id == benutzer.id)
        .order_by(Aufgabe.reihenfolge)
        .limit(1)
    ).scalar()

    aufgabe = Aufgabe(
        benutzer_id=benutzer.id,
        konto_id=nachricht.konto_id,
        nachricht_id=nachricht.id,
        message_id=nachricht.message_id,
        betreff=nachricht.betreff,
        von_name=nachricht.von_name,
        von_adresse=nachricht.von_adresse,
        mail_datum=nachricht.datum,
        reihenfolge=(kleinste if kleinste is not None else 0) - 1,
    )
    db.add(aufgabe)
    db.commit()
    logger.info("A message was turned into a task.")
    return aufgabe


def eine(db: Session, benutzer: Benutzer, aufgabe_id: int) -> Aufgabe:
    aufgabe = db.get(Aufgabe, aufgabe_id)
    if aufgabe is None or aufgabe.benutzer_id != benutzer.id:
        raise AufgabenFehler("aufgabe_unbekannt")
    return aufgabe


def abhaken(db: Session, benutzer: Benutzer, aufgabe_id: int, erledigt: bool) -> Aufgabe:
    aufgabe = eine(db, benutzer, aufgabe_id)
    aufgabe.erledigt = _jetzt() if erledigt else None
    db.commit()
    return aufgabe


def faelligkeit(
    db: Session, benutzer: Benutzer, aufgabe_id: int, wann: datetime | None
) -> Aufgabe:
    aufgabe = eine(db, benutzer, aufgabe_id)
    aufgabe.faellig = wann
    db.commit()
    return aufgabe


def entfernen(db: Session, benutzer: Benutzer, aufgabe_id: int) -> None:
    db.delete(eine(db, benutzer, aufgabe_id))
    db.commit()
    logger.info("A task was removed.")


def ordnen(db: Session, benutzer: Benutzer, reihenfolge: list[int]) -> None:
    """Die gezogene Reihenfolge uebernehmen.

    ⚠️ **Nur was mitkommt, wird umgestellt.** Wer eine Kennung schickt, die
    ihm nicht gehoert oder die es nicht gibt, stellt damit nichts um — und
    bekommt auch keinen Fehler: Die Liste kann sich zwischen Laden und Ziehen
    geaendert haben, und ein Abbruch mitten im Sortieren waere die schlechteste
    Antwort darauf.
    """
    meine = {
        a.id: a
        for a in db.execute(
            select(Aufgabe).where(Aufgabe.benutzer_id == benutzer.id)
        ).scalars().all()
    }
    for platz, kennung in enumerate(reihenfolge):
        if kennung in meine:
            meine[kennung].reihenfolge = platz
    db.commit()


def offene(db: Session, benutzer: Benutzer) -> int:
    """Wie viele noch offen sind — fuer die Zahl an der Leiste."""
    return len(
        db.execute(
            select(Aufgabe.id).where(
                Aufgabe.benutzer_id == benutzer.id, Aufgabe.erledigt.is_(None)
            )
        ).all()
    )
