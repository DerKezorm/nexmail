"""Papierkorb und Junk leeren sich selbst — nach der eingestellten Aufbewahrung.

Jeder Benutzer stellt in Tagen ein, wie lange Papierkorb und Junk aufheben
(``aufraeumen_papierkorb_tage`` / ``aufraeumen_junk_tage`` am Benutzer).
⚠️ **Die Vorgabe ist 0 — nie.** Endgueltiges Loeschen schaltet man ein, es
passiert nicht von Werk aus.

⚠️ **Hoechstens eine Runde am Tag je Benutzer.** Gemerkt wird der letzte Lauf
in ``aufraeumen_zuletzt`` — dasselbe Muster wie beim Sicherungs-Zeitplan
(``sicherung_zuletzt``), nur je Benutzer: Gemessen wird am Abstand seit dem
letzten Lauf, nicht an einer Uhrzeit, denn ein NAS, das nachts schlaeft,
verpasst jede Uhrzeit.

⚠️ **Ein klemmendes Postfach toetet die Runde nicht.** Jeder Ordner wird
einzeln gefangen — sonst hielte ein falsch eingetragener Server das Aufraeumen
aller anderen Postfaecher an. Der Merker wird trotzdem gesetzt: Ein Server,
der heute klemmt, klemmt meist auch in einer Stunde noch, und stuendliche
Anlaeufe dagegen waeren nur Laerm im Protokoll.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Benutzer, Konto, utcnow

logger = logging.getLogger("nexmail.aufraeumen")

#: Was die Oberflaeche anbietet. 0 heisst: nie von selbst leeren.
ERLAUBTE_TAGE = (0, 7, 14, 30, 90)

#: Wie oft der Faden nachsieht, ob bei jemandem eine Runde faellig ist. Der
#: Vergleich kostet eine Datenbankabfrage — er darf ruhig oefter laufen als
#: die Runde selbst.
NACHSEHEN_SEKUNDEN = 3600


def faellig(person: Benutzer) -> bool:
    """Ist fuer diesen Benutzer eine Aufraeumrunde dran?"""
    if person.aufraeumen_papierkorb_tage <= 0 and person.aufraeumen_junk_tage <= 0:
        return False
    if person.aufraeumen_zuletzt is None:
        return True
    return (utcnow() - person.aufraeumen_zuletzt).days >= 1


def benutzer_aufraeumen(db: Session, person: Benutzer) -> int:
    """Eine Runde fuer einen Benutzer: alle Konten, Papierkorb und Junk."""
    from . import handeln

    vorgaben = (
        ("papierkorb", person.aufraeumen_papierkorb_tage),
        ("junk", person.aufraeumen_junk_tage),
    )

    geloescht = 0
    konten = (
        db.execute(
            select(Konto).where(Konto.benutzer_id == person.id, Konto.aktiv.is_(True))
        )
        .scalars()
        .all()
    )
    for konto in konten:
        for rolle, tage in vorgaben:
            if tage <= 0:
                continue
            stichtag = utcnow() - timedelta(days=tage)
            # ⚠️ **Dieser Rollenfilter ist die ganze Sicherheit des Laufs.**
            # ``handeln.alte_entfernen`` loescht in jedem Ordner, den es
            # bekommt — wer hier die Rolle wegnimmt, raeumt den Posteingang.
            # Genau dagegen steht der Test mit dem alten Posteingangs-Brief.
            for ordner in konto.ordner:
                if ordner.rolle != rolle:
                    continue
                try:
                    geloescht += handeln.alte_entfernen(db, ordner, stichtag)
                except Exception as fehler:  # noqa: BLE001
                    # Fangen, warnen, weiter — dasselbe Muster wie im Takt.
                    logger.warning(
                        "Auto-clean skipped %s (%s): %s", konto.adresse, ordner.pfad, fehler
                    )
    return geloescht


def runde() -> dict[str, int]:
    """Eine Runde ueber alle Benutzer, bei denen sie faellig ist."""
    stand = {"benutzer": 0, "geloescht": 0}
    with SessionLocal() as db:
        leute = db.execute(select(Benutzer)).scalars().all()
        for person in leute:
            if not faellig(person):
                continue
            stand["benutzer"] += 1
            stand["geloescht"] += benutzer_aufraeumen(db, person)
            person.aufraeumen_zuletzt = utcnow()
            db.commit()
    if stand["geloescht"]:
        logger.info(
            "Auto-clean removed %s old message(s) for %s user(s).",
            stand["geloescht"],
            stand["benutzer"],
        )
    return stand


__all__ = ["ERLAUBTE_TAGE", "NACHSEHEN_SEKUNDEN", "benutzer_aufraeumen", "faellig", "runde"]
