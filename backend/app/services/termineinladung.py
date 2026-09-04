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
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..meldung import Meldung
from ..models import Benutzer, Konto, Termin
from . import konten as kontendienst
from . import senden as sendedienst
from . import verfassen
from . import vevent
from . import zeit
from .aliase import lesen as aliase_lesen
from .zeit import zonenname_der_anwendung

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


def _wann(db: Session, termin: Termin) -> str:
    """Der Zeitpunkt, wie ein Mensch ihn liest — in der richtigen Zone.

    ⚠️ **Der Kalenderteil daneben genuegt nicht.** Wer keine Kalender-App hat,
    liest nur diese Zeile. Bis zum 04.09.2026 stand hier ``termin.beginn`` roh,
    also **UTC**, dazu ``termin.zeitzone`` — und die ist bei einem in nexmail
    angelegten Termin leer. Aus „10:30 (Europe/Berlin)" wurde „08:30 ()".
    Genau der Fall, vor dem ``services/zeit.py`` in seinem eigenen Kopf warnt.

    ⚠️ **Ein ganztaegiger Termin hat keine Uhrzeit.** Sonst stuende dort
    „00:00 - 00:00".
    """
    name = (termin.zeitzone or "").strip() or zonenname_der_anwendung(db)
    wo = zeit.zone(name)
    # ⚠️ **Die Beschriftung kommt aus der aufgeloesten Zone, nicht aus dem
    # Namen.** Outlook schickt Windows-Namen wie „W. Europe Standard Time";
    # ``zeit.zone`` kennt die nicht und weicht auf UTC aus. Stuende dann der
    # Name in der Klammer, naennte die Zeile eine Zone und zeigte eine andere.
    name = getattr(wo, "key", "") or "UTC"

    def hier(wert: datetime) -> datetime:
        # Naiv gespeicherte Werte sind UTC — so schreibt sie ``vevent``.
        if wert.tzinfo is None:
            wert = wert.replace(tzinfo=timezone.utc)
        return wert.astimezone(wo)

    beginn = hier(termin.beginn)
    if termin.ganztaegig:
        ende = hier(termin.ende) if termin.ende else beginn
        # Ein Kalendertag endet um Mitternacht des Folgetags; genannt wird der
        # letzte Tag, an dem etwas ist.
        letzter = (ende - timedelta(seconds=1)).date()
        if letzter <= beginn.date():
            return f"{beginn:%Y-%m-%d} (all day)"
        return f"{beginn:%Y-%m-%d} - {letzter:%Y-%m-%d} (all day)"

    gezeigt = name or "UTC"
    if termin.ende:
        return f"{beginn:%Y-%m-%d %H:%M} - {hier(termin.ende):%H:%M} ({gezeigt})"
    return f"{beginn:%Y-%m-%d %H:%M} ({gezeigt})"


def _text(db: Session, termin: Termin) -> str:
    """Der lesbare Teil der Mail.

    ⚠️ **Ohne ihn sieht ein Empfaenger ohne Kalender eine leere Mail.** Es
    genuegt nicht, dass der Kalenderteil daneben liegt: Wer ihn nicht
    versteht, sieht gar nichts.

    ⚠️ **Auf Englisch, wie alles, was nexmail nach aussen schreibt.** Die
    Sprache des Empfaengers kennt niemand, und die des Absenders ist nicht
    seine.
    """
    zeilen = [termin.titel, "", f"When: {_wann(db, termin)}"]
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

    zeile = sendedienst.einreihen(
        db,
        konto,
        verfassen.Entwurf(
            von_name=absender.get("name") or kontendienst.absendername(konto),
            von_adresse=absender.get("adresse", ""),
            an=[p["adresse"] for p in leute],
            betreff=f"Invitation: {termin.titel}".strip(),
            text=_text(db, termin),
            kalender=ics,
            kalender_methode="REQUEST",
        ),
    )
    termin.eingeladen_am = jetzt
    db.commit()
    _hinausschicken(db, zeile)
    logger.info("An invitation was queued for %s recipient(s).", len(leute))
    return len(leute)


def _hinausschicken(db: Session, zeile) -> None:
    """Den eingereihten Eintrag gleich versuchen.

    ⚠️ **Einreihen allein verschickt nichts.** Bis zum 04.09.2026 endete der
    Versand hier — und die Mail lag im Ausgang, bis jemand nexmail neu
    startete: ``faellige_geplante`` sieht nur Eintraege mit ``senden_ab``, und
    das hat eine Einladung nicht. Die Oberflaeche meldete „1 Person bekommt
    eine Mail", und niemand bekam eine. Aufgefallen ist es erst an einer echten
    Einladung, nicht im Testlauf.

    ⚠️ **Ein Fehlschlag ist kein Fehler.** Die Mail liegt dann im Ausgang und
    geht beim naechsten Versuch hinaus — dieselbe Zusage wie beim Verfassen.
    """
    try:
        sendedienst.versenden(db, zeile)
    except sendedienst.SendeFehler as fehler:
        logger.warning("The invitation stays in the outbox for now: %s", fehler)


def absagen(db: Session, benutzer: Benutzer, termin: Termin) -> int:
    """Den Eingeladenen sagen, dass der Termin ausfaellt. Gibt die Empfaenger.

    ⚠️ **Ohne das steht der Termin bei allen anderen weiter im Kalender.** Ein
    geloeschter Termin ist nur bei uns geloescht; wer eingeladen wurde, sieht
    ihn bis zum Tag selbst und kommt.

    ⚠️ **Und trotzdem nicht von selbst.** Auch die Absage ist Post an Fremde.
    Die Oberflaeche fragt vor dem Loeschen, ob sie hinausgehen soll — sonst
    verschickt ein versehentliches Loeschen Mail, die niemand zurueckholen
    kann.
    """
    leute = _leute(termin)
    if not leute:
        return 0
    # ⚠️ **Wer nie eingeladen wurde, bekommt keine Absage.** Sonst erfaehrt
    # jemand von einem Termin erst dadurch, dass er ausfaellt.
    if termin.eingeladen_am is None:
        return 0

    absender = _absender(termin)
    konto = postfach_fuer(db, benutzer, absender.get("adresse", ""))

    # ⚠️ **Die Absage zaehlt hoch.** Sie muss ueber der letzten verschickten
    # Fassung liegen, sonst haelt die Gegenstelle sie fuer veraltet und laesst
    # den Termin stehen.
    termin.sequenz = (termin.sequenz or 0) + 1

    jetzt = datetime.now(timezone.utc)
    ics = vevent.bauen(termin, jetzt, methode="CANCEL", status="CANCELLED")

    zeile = sendedienst.einreihen(
        db,
        konto,
        verfassen.Entwurf(
            von_name=absender.get("name") or kontendienst.absendername(konto),
            von_adresse=absender.get("adresse", ""),
            an=[p["adresse"] for p in leute],
            betreff=f"Cancelled: {termin.titel}".strip(),
            text=_absagetext(db, termin),
            kalender=ics,
            kalender_methode="CANCEL",
        ),
    )
    db.commit()
    _hinausschicken(db, zeile)
    logger.info("A cancellation was queued for %s recipient(s).", len(leute))
    return len(leute)


def _absagetext(db: Session, termin: Termin) -> str:
    """Der lesbare Teil der Absage — englisch, aus demselben Grund wie oben."""
    return (
        f"{termin.titel} has been cancelled.\n\n"
        f"It was scheduled for {_wann(db, termin)}.\n"
    )
