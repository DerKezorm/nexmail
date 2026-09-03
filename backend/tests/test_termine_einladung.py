"""Eine Einladung in den Kalender übernehmen.

⚠️ **Auf Klick, nicht als Folge des Zusagens.** So entschieden am 02.09.2026:
Wer zusagt, ohne den Termin wirklich zu wollen, soll ihn nicht im Kalender
wiederfinden.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Benutzer, Kalender, Nachricht, Termin
from app.services import termine as kalenderdienst
from conftest import einrichten


def test_die_uid_der_einladung_bleibt(klient, db):
    """⚠️ Daran erkennt jeder andere Client denselben Termin wieder — und
    daran sieht die Karte beim zweiten Öffnen, dass er schon drin ist."""
    einrichten(klient)
    person = db.query(Benutzer).one()
    kalender = kalenderdienst.kalender_anlegen(db, person, "Privat")

    termin = kalenderdienst.anlegen(
        db, person, kalender.id, titel="Aus einer Einladung",
        beginn=datetime(2026, 9, 8, 9, tzinfo=timezone.utc), aus_einladung=True,
    )
    termin.uid = "einladung@example.org"
    db.commit()

    from app.routers.termine import _liegt_im_kalender

    assert _liegt_im_kalender(db, person, "einladung@example.org") is True
    assert _liegt_im_kalender(db, person, "andere@example.org") is False


def test_ohne_kalender_wird_es_benannt(klient, db):
    """⚠️ „Du hast noch keinen Kalender" ist etwas anderes als „ging nicht" —
    und nur das Erste kann man beheben."""
    einrichten(klient)
    person = db.query(Benutzer).one()
    offene = [k for k in kalenderdienst.liste(db, person) if not k.nur_lesen]
    assert offene == []


def test_ein_abo_kann_nichts_aufnehmen(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    abo = Kalender(
        benutzer_id=person.id, name="Feiertage", farbe=5, art="ics",
        url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()

    offene = [k for k in kalenderdienst.liste(db, person) if not k.nur_lesen]
    assert offene == []
