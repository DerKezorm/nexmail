"""Textvorlagen — wiederkehrende Antworten fuer das Verfassen-Fenster.

⚠️ **Fehler tragen eine KENNUNG, keinen Satz** — dasselbe Muster wie bei den
Schlagworten. Die Oberflaeche uebersetzt ``textvorlage_name_vergeben`` in
beide Sprachen; ein deutscher Satz als ``detail`` bliebe auf Englisch deutsch.

⚠️ **Der Name wird klein verglichen.** „Absage" und „absage" staenden sonst
als zwei Eintraege im Menue, die gleich aussehen — dieselbe Entscheidung wie
bei den Schlagworten und den Postfach-Gruppen.

⚠️ **Dieselbe Bereinigung wie beim Senden.** Der Inhalt entsteht im selben
Editor wie eine Mail und landet wortwoertlich in einer — wer eine Vorlage aus
einem alten Client hineinkopiert, bringt fremde Auszeichnung mit.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Textvorlage
from . import bereinigen
from ..meldung import Meldung

logger = logging.getLogger("nexmail.textvorlagen")


class TextvorlagenFehler(Meldung, RuntimeError):
    """Traegt eine Kennung, die die Oberflaeche uebersetzt."""


def meine(db: Session, person: Benutzer) -> list[Textvorlage]:
    return list(
        db.execute(
            select(Textvorlage)
            .where(Textvorlage.benutzer_id == person.id)
            .order_by(Textvorlage.reihenfolge, Textvorlage.name)
        )
        .scalars()
        .all()
    )


def anlegen(db: Session, person: Benutzer, name: str, inhalt_html: str) -> Textvorlage:
    name = name.strip()
    if not name:
        raise TextvorlagenFehler("textvorlage_name_fehlt")
    _name_frei(db, person, name)

    vorhandene = meine(db, person)
    eintrag = Textvorlage(
        benutzer_id=person.id,
        name=name,
        inhalt_html=bereinigen.fuer_versand(inhalt_html),
        # Neue Vorlagen hinten anstellen — wer sein Menue sortiert hat, will
        # es nicht von der naechsten Vorlage umgestossen bekommen.
        reihenfolge=max((v.reihenfolge for v in vorhandene), default=-1) + 1,
    )
    db.add(eintrag)
    db.commit()
    return eintrag


def aendern(
    db: Session, person: Benutzer, vorlage_id: int, name: str, inhalt_html: str
) -> Textvorlage:
    eintrag = _meine(db, person, vorlage_id)
    name = name.strip()
    if not name:
        raise TextvorlagenFehler("textvorlage_name_fehlt")
    _name_frei(db, person, name, ausser=eintrag.id)
    eintrag.name = name
    eintrag.inhalt_html = bereinigen.fuer_versand(inhalt_html)
    db.commit()
    return eintrag


def entfernen(db: Session, person: Benutzer, vorlage_id: int) -> None:
    db.delete(_meine(db, person, vorlage_id))
    db.commit()
    logger.info("A text template was removed.")


def ordnen(db: Session, person: Benutzer, reihenfolge: list[int]) -> None:
    """Die gezogene Reihenfolge uebernehmen — dasselbe Muster wie bei den
    Aufgaben.

    ⚠️ **Nur was mitkommt, wird umgestellt.** Eine Kennung, die es nicht gibt
    oder die einem anderen gehoert, stellt nichts um und wirft auch keinen
    Fehler: Die Liste kann sich zwischen Laden und Ziehen geaendert haben.
    """
    eigene = {v.id: v for v in meine(db, person)}
    for platz, kennung in enumerate(reihenfolge):
        if kennung in eigene:
            eigene[kennung].reihenfolge = platz
    db.commit()


def _meine(db: Session, person: Benutzer, vorlage_id: int) -> Textvorlage:
    eintrag = db.get(Textvorlage, vorlage_id)
    if eintrag is None or eintrag.benutzer_id != person.id:
        # Fremder Besitz und „gibt es nicht" antworten gleich.
        raise TextvorlagenFehler("textvorlage_unbekannt")
    return eintrag


def _name_frei(db: Session, person: Benutzer, name: str, ausser: int | None = None) -> None:
    for andere in meine(db, person):
        if andere.id != ausser and andere.name.lower() == name.lower():
            raise TextvorlagenFehler("textvorlage_name_vergeben")


__all__ = [
    "TextvorlagenFehler",
    "aendern",
    "anlegen",
    "entfernen",
    "meine",
    "ordnen",
]
