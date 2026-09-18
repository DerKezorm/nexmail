"""Der Riegel des Betreibers: Kalender- und Adressbuchserver im eigenen Netz.

Nextcloud, Radicale und Baikal stehen bei den meisten, die nexmail selbst
betreiben, im selben Netz wie nexmail. Die Pruefung in ``caldav._pruefen``
weist solche Adressen ab, und das aus gutem Grund; fuer genau diese Leute ist
sie aber die Wand vor dem eigenen Kalender.

⚠️ **Ab Werk zu, und der Betreiber macht auf, nicht jeder Benutzer fuer
sich.** Mit der Freigabe kann jeder angemeldete Benutzer nexmail eine Adresse
im Netz des Betreibers ansprechen lassen. Wer nexmail allein oder im Haushalt
benutzt, verliert dabei nichts; wer Fremde eingeladen hat, soll es wissen,
bevor er den Schalter umlegt. Die Oberflaeche sagt es an derselben Stelle.

⚠️ **Nur Kalender, Adressbuecher und ICS-Abos.** Der Bildvermittler bleibt
zu, egal wie der Schalter steht: Dort kommt die Adresse aus einer fremden
Mail, nicht von einem angemeldeten Menschen.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..db import SessionLocal, einstellung_lesen, einstellung_schreiben

logger = logging.getLogger("nexmail.netz")

#: Der Schluessel des Riegels in der ``einstellung``-Tabelle.
SCHALTER = "dav_eigenes_netz_erlaubt"


def erlaubt(db: Session) -> bool:
    return einstellung_lesen(db, SCHALTER, "0") == "1"


def erlauben(db: Session, ja: bool) -> bool:
    einstellung_schreiben(db, SCHALTER, "1" if ja else "0")
    logger.info(
        "The operator %s calendar and address book servers on the local network.",
        "allowed" if ja else "blocked",
    )
    return ja


def erlaubt_jetzt() -> bool:
    """Dieselbe Frage fuer eine Stelle, die keine Sitzung in der Hand hat.

    ``caldav.py`` spricht mit fremden Servern und kennt die Datenbank nicht.
    Gefragt wird nur, wenn eine Adresse wirklich ins eigene Netz zeigt; der
    gewoehnliche Abgleich mit iCloud oder Google kommt hier nie vorbei.
    """
    with SessionLocal() as db:
        return erlaubt(db)
