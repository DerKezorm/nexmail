"""Antworten auf eigene Einladungen einsammeln.

Wer eingeladen wurde, schickt eine Mail mit ``METHOD:REPLY`` zurueck. Darin
steht genau ein ``ATTENDEE`` — er selbst — mit seinem ``PARTSTAT``. nexmail
traegt ihn am eigenen Termin nach; ohne das bleibt die Teilnehmerliste eine
Namensliste, und man weiss nicht, wer kommt.

⚠️ **Nur am EIGENEN Termin.** Eine Antwort auf einen Termin, den jemand anders
organisiert, geht uns nichts an — sie kommt dort ohnehin nur zufaellig
vorbei (als Kopie), und sie einzutragen hiesse, den Bestand des Organisators
zu erraten.
"""

from __future__ import annotations

import json
import logging
from email import message_from_bytes
from email.policy import default as regelwerk

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Konto, Nachricht, Termin
from . import vevent

logger = logging.getLogger("nexmail.terminantwort")


def kalenderteil(roh: bytes) -> str:
    """Der ``text/calendar``-Teil einer Mail, oder ``""``.

    ⚠️ **Auch als Anhang, nicht nur als Alternative.** Manche Programme
    haengen die ``.ics`` an, statt sie als zweiten Teil danebenzulegen; wer nur
    auf ``multipart/alternative`` sieht, verliert deren Antworten.
    """
    try:
        mail = message_from_bytes(roh, policy=regelwerk)
    except Exception:  # noqa: BLE001
        return ""
    for teil in mail.walk():
        typ = (teil.get_content_type() or "").lower()
        name = (teil.get_filename() or "").lower()
        if typ == "text/calendar" or name.endswith(".ics"):
            try:
                inhalt = teil.get_content()
            except Exception:  # noqa: BLE001
                continue
            if isinstance(inhalt, bytes):
                inhalt = inhalt.decode("utf-8", "replace")
            if "BEGIN:VCALENDAR" in inhalt.upper():
                return inhalt
    return ""


def _antwortender(ics: str) -> tuple[str, str, str, int]:
    """``(uid, adresse, partstat, sequenz)`` aus einer ``METHOD:REPLY``.

    Leere Werte heissen: Das ist keine Antwort, die uns etwas angeht.
    """
    if "METHOD:REPLY" not in ics.upper().replace(" ", ""):
        return "", "", "", 0
    # ⚠️ **``vevent.lesen``, nicht ``kalender.lesen``.** Der zweite Leser ist
    # fuer die Einladungskarte gebaut und kennt kein ``PARTSTAT`` — genau das
    # ist hier der ganze Inhalt der Nachricht.
    eintraege = vevent.lesen(ics)
    if not eintraege:
        return "", "", "", 0
    termin = eintraege[0]
    leute = termin.get("teilnehmer") or []
    if not leute:
        return "", "", "", 0
    # ⚠️ **Genau der erste.** Eine Antwort spricht fuer eine Person; wer mehr
    # mitschickt, behauptet, fuer andere zu sprechen.
    wer = leute[0]
    return (
        termin.get("uid", ""),
        (wer.get("adresse") or "").strip().lower(),
        (wer.get("antwort") or "").upper(),
        int(termin.get("sequenz") or 0),
    )


def verarbeiten(db: Session, konto: Konto, nachricht: Nachricht, roh: bytes) -> bool:
    """Eine eingegangene Mail als Antwort auf eine eigene Einladung deuten.

    Gibt zurueck, ob etwas nachgetragen wurde.
    """
    uid, adresse, partstat, sequenz = _antwortender(kalenderteil(roh))
    if not uid or not adresse or not partstat:
        return False

    termin = db.execute(
        select(Termin).where(Termin.benutzer_id == konto.benutzer_id, Termin.uid == uid)
    ).scalars().first()
    if termin is None:
        return False

    # ⚠️ **Eine Antwort auf eine aeltere Fassung wird verworfen.** Wer den
    # Termin verschoben und neu eingeladen hat, bekommt sonst die Zusage zum
    # alten Termin als Zusage zum neuen angezeigt.
    if sequenz < (termin.sequenz or 0):
        logger.info("A reply to an older version of an appointment was ignored.")
        return False

    try:
        leute = json.loads(termin.teilnehmer or "[]")
    except ValueError:
        return False
    if not isinstance(leute, list):
        return False

    geaendert = False
    for person in leute:
        if not isinstance(person, dict):
            continue
        if (person.get("adresse") or "").strip().lower() != adresse:
            continue
        # ⚠️ **Nur wer eingeladen wurde, kann antworten.** Sonst traegt ein
        # Fremder sich in eine Teilnehmerliste ein, indem er eine Antwort
        # schickt.
        if person.get("antwort") != partstat:
            person["antwort"] = partstat
            geaendert = True
        break

    if not geaendert:
        return False
    termin.teilnehmer = json.dumps(leute, ensure_ascii=False)
    db.commit()
    logger.info("A reply to an invitation was recorded.")
    return True
