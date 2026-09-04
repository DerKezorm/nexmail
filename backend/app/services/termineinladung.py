"""Eine Einladung zu einem eigenen Termin verschicken.

⚠️ **Das ist die zweite Stelle, an der nexmail von sich aus Post an Fremde
schickt** — die erste ist die Abwesenheitsnotiz. Dort steht in
``services/abwesenheit.py`` mehr Vorsicht als Funktion, und aus demselben Grund
steht auch hier eine Rueckfrage davor: Verschickt wird **nur** auf
ausdrueckliches Kommando aus der Oberflaeche, nie beim Speichern von selbst.

⚠️ **Warum das nicht der Abgleich erledigt.** Ein CalDAV-Server nimmt den
Termin entgegen und stellt ihn niemandem zu; ein Kalender ist kein Postausgang.
Wer glaubt, „hochschieben reicht", laedt niemanden ein und merkt es erst, wenn
keiner kommt.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..meldung import Meldung
from ..models import Benutzer, Konto, Termin
from . import konten as kontendienst
from . import senden as sendedienst
from . import verfassen
from . import vevent
from .aliase import lesen as aliase_lesen

logger = logging.getLogger("nexmail.einladung")


class EinladungFehler(Meldung, RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


def _leute(termin: Termin) -> list[dict]:
    try:
        wert = json.loads(termin.teilnehmer or "[]")
    except ValueError:
        return []
    return [e for e in wert if isinstance(e, dict) and e.get("adresse")]


def _absender(termin: Termin) -> dict:
    try:
        wert = json.loads(termin.organisator or "null")
    except ValueError:
        return {}
    return wert if isinstance(wert, dict) else {}


def postfach_fuer(db: Session, benutzer: Benutzer, adresse: str) -> Konto:
    """Das Postfach, das unter dieser Adresse senden darf.

    ⚠️ **Die Adresse wird gegen die Postfaecher gehalten, nicht uebernommen.**
    Sie kommt aus dem Termin, und der kommt aus der Oberflaeche. Dieselbe
    Pruefung wie beim Verfassen — ohne sie verschickte nexmail Post unter jeder
    Adresse, die jemand eintraegt.
    """
    gesucht = (adresse or "").strip().lower()
    if not gesucht:
        raise EinladungFehler("einladung_ohne_absender")
    for konto in kontendienst.meine(db, benutzer):
        if konto.adresse.strip().lower() == gesucht:
            return konto
        if any(a.adresse == gesucht for a in aliase_lesen(konto)):
            return konto
    raise EinladungFehler("einladung_absender_unbekannt", adresse=gesucht)


def _text(termin: Termin, sprache_egal: None = None) -> str:
    """Der lesbare Teil der Mail.

    ⚠️ **Ohne ihn sieht ein Empfaenger ohne Kalender eine leere Mail.** Es
    genuegt nicht, dass der Kalenderteil daneben liegt: Wer ihn nicht
    versteht, sieht gar nichts.

    ⚠️ **Auf Englisch, wie alles, was nexmail nach aussen schreibt.** Die
    Sprache des Empfaengers kennt niemand, und die des Absenders ist nicht
    seine.
    """
    zeilen = [termin.titel, ""]
    zeilen.append(f"When: {termin.beginn:%Y-%m-%d %H:%M} - {termin.ende:%H:%M} ({termin.zeitzone})")
    if termin.ort:
        zeilen.append(f"Where: {termin.ort}")
    if termin.beschreibung:
        zeilen += ["", termin.beschreibung]
    return "\n".join(zeilen) + "\n"


def versenden(db: Session, benutzer: Benutzer, termin: Termin) -> int:
    """Die Einladung in die Warteschlange legen. Gibt die Zahl der Empfaenger.

    ⚠️ **Ueber den gewoehnlichen Ausgang**, nicht mit einer eigenen
    SMTP-Verbindung. So gelten Wiederholung, Abbruch und die Anzeige im
    Postausgang auch hier — und ein Netzaussetzer kostet keine Einladung.

    ⚠️ **Eine Mail an alle, nicht eine je Person.** Wer einzeln verschickt,
    zeigt jedem Eingeladenen eine Einladung ohne Mitwissende; die anderen
    Teilnehmer stehen zwar in der ``.ics``, aber im Mailkopf sieht niemand,
    wer noch gefragt wurde.
    """
    leute = _leute(termin)
    if not leute:
        raise EinladungFehler("einladung_ohne_teilnehmer")

    absender = _absender(termin)
    konto = postfach_fuer(db, benutzer, absender.get("adresse", ""))

    # ⚠️ **Die erste Einladung behaelt ihre Nummer, jede weitere zaehlt hoch.**
    # Ohne Hochzaehlen halten Outlook und Google die zweite fuer eine
    # Wiederholung der ersten und zeigen die Aenderung nicht an. Mit
    # Hochzaehlen schon beim ersten Mal waere sie die „Aktualisierung" eines
    # Termins, den niemand kennt.
    if termin.eingeladen_am is not None:
        termin.sequenz = (termin.sequenz or 0) + 1

    jetzt = datetime.now(timezone.utc)
    ics = vevent.bauen(termin, jetzt, methode="REQUEST")

    sendedienst.einreihen(
        db,
        konto,
        verfassen.Entwurf(
            von_name=absender.get("name") or kontendienst.absendername(konto),
            von_adresse=absender.get("adresse", ""),
            an=[p["adresse"] for p in leute],
            betreff=f"Invitation: {termin.titel}".strip(),
            text=_text(termin),
            kalender=ics,
            kalender_methode="REQUEST",
        ),
    )
    termin.eingeladen_am = jetzt
    db.commit()
    logger.info("An invitation was queued for %s recipient(s).", len(leute))
    return len(leute)
