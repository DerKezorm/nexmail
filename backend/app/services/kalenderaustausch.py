"""Einen Kalender als ``.ics`` ausgeben und einlesen.

Das Gegenstück zu mbox bei der Post: Umzug und Sicherung. Wer nexmail verlässt,
nimmt seine Termine mit; wer aus Thunderbird oder Apple Kalender kommt, bringt
sie mit.

⚠️ **Ausgegeben wird das Original, nicht ein Nachbau.** Ein ``VEVENT`` von
iCloud trägt Teilnehmer, Erinnerungen und ein Dutzend ``X-APPLE-…``. Wer beim
Ausgeben nur die Felder schreibt, die nexmail kennt, liefert dem Menschen eine
Datei, in der die Hälfte seines Kalenders fehlt — und er merkt es erst beim
Einlesen woanders. Dieselbe Überlegung wie bei mboxrd: Das Format muss
verlustfrei durch nexmail hindurchgehen.

⚠️ **Eingelesen wird nur in einen Kalender, der hier lebt.** Bei einem
CalDAV-Kalender gilt „erst der Server, dann die eigene Datenbank"; hundert
Termine einzeln hochzuschieben ist ein eigener Vorgang mit eigenem Fortschritt
und eigener Abbruchbehandlung. Bis den jemand baut, sagt nexmail es, statt
Termine anzulegen, die nie beim Anbieter ankommen.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..meldung import Meldung
from ..models import Benutzer, Kalender, Termin
from . import vevent
from .kalender import _maskieren as maskieren

logger = logging.getLogger("nexmail.kalenderaustausch")

#: Zeilenenden, einmal benannt statt siebenmal maskiert.
CR = chr(13)
NL = chr(10)
CRLF = CR + NL

#: ⚠️ **Eine Grenze, weil die Datei von außen kommt.** Ein Jahreskalender hat
#: Kilobyte; wer zehn Megabyte schickt, meint etwas anderes. Dieselbe
#: Überlegung wie bei den 25 MB des ICS-Abos, nur enger: Hier liest ein Mensch
#: eine Datei von seiner Platte ein, kein Dienst einen Feiertagskalender.
MAX_BYTES = 10 * 1024 * 1024

#: Wie viele Termine eine Einfuhr höchstens anlegt.
#:
#: ⚠️ **Nicht wegen des Speichers, sondern wegen der Zeit.** Das Einlesen läuft
#: in der Anfrage; wer zwanzigtausend Termine schickt, bekäme eine Zeitgrenze
#: des Proxys statt einer Antwort. Die Zahl steht in der Meldung, damit
#: „mehr geht nicht" von „mehr war nicht drin" zu unterscheiden ist.
MAX_TERMINE = 5_000


class AustauschFehler(Meldung):
    """Etwas, das dem Menschen davor gezeigt wird."""


@dataclass
class Bericht:
    """Was beim Einlesen herauskam."""

    angelegt: int = 0
    #: Schon da — erkannt an ``UID`` samt ``RECURRENCE-ID``.
    uebersprungen: int = 0
    #: Ohne ``UID`` oder ohne Beginn; damit ist es kein Termin.
    unbrauchbar: int = 0
    #: Wahr, wenn die Datei mehr enthielt, als angelegt wurde.
    abgeschnitten: bool = False
    fehler: list[str] = field(default_factory=list)


# --- Ausgeben ------------------------------------------------------------- #


def _bloecke(roh: str, name: str) -> list[str]:
    """Alle ``BEGIN:<name>`` … ``END:<name>``-Blöcke einer Datei.

    ⚠️ **Verglichen wird auf den GANZEN Namen, nicht auf ``END:``.** Ein
    ``VEVENT`` enthält ein ``VALARM``, ein ``VTIMEZONE`` enthält ``STANDARD``
    und ``DAYLIGHT``. Wer auf das erste ``END:`` wartet, schneidet mitten
    hinein — dieselbe Falle wie in ``services/kalender.py``.

    ⚠️ **Einen Tiefenzähler braucht es dafür nicht**, und der erste Anlauf
    hatte einen: Ein ``VEVENT`` enthält nie ein ``VEVENT``, ein ``VTIMEZONE``
    nie ein ``VTIMEZONE`` — das Format kennt das gar nicht. Die
    Mutationsprobe hat ihn als unerreichbar entlarvt, und unerreichbarer Code
    ist kein Sicherheitsnetz, sondern eine Behauptung.
    """
    gefunden: list[str] = []
    laufend: list[str] | None = None
    anfang = f"BEGIN:{name}"
    ende = f"END:{name}"
    for zeile in roh.replace(CRLF, NL).split(NL):
        blank = zeile.strip().upper()
        if blank == anfang and laufend is None:
            laufend = []
        if laufend is not None:
            laufend.append(zeile.rstrip(CR))
            if blank == ende:
                gefunden.append(NL.join(laufend))
                laufend = None
    return gefunden


def _kennung(block: str) -> tuple[str, str]:
    """``(uid, recurrence_id)`` eines ``VEVENT``-Blocks, roh gelesen."""
    uid = wieder = ""
    for zeile in block.split("\n"):
        name, _, wert = zeile.partition(":")
        kopf = name.split(";")[0].strip().upper()
        if kopf == "UID" and not uid:
            uid = wert.strip()
        elif kopf == "RECURRENCE-ID" and not wieder:
            wieder = wert.strip()
    return uid, wieder


def _tzid(block: str) -> str:
    for zeile in block.split("\n"):
        name, _, wert = zeile.partition(":")
        if name.split(";")[0].strip().upper() == "TZID":
            return wert.strip()
    return ""


def ausgeben(db: Session, person: Benutzer, kalender: Kalender) -> str:
    """Den ganzen Kalender als eine ``.ics``.

    ⚠️ **Je Termin genau ein ``VEVENT``.** Bei einem CalDAV-Kalender steht in
    ``termin.roh`` die **ganze Datei** — und mehrere Zeilen einer Reihe teilen
    sich dieselbe. Wer ``roh`` je Zeile ausgibt, schreibt die Reihe samt allen
    Ausnahmen so oft hinein, wie es Zeilen gibt.

    ⚠️ **Die ``VTIMEZONE`` müssen mit.** Ohne sie zeigt ein ``DTSTART`` auf eine
    Zone, die in der Datei nicht steht; strenge Leser weisen das ab, freundliche
    raten. Gesammelt wird über alle Quelldateien, je ``TZID`` einmal.
    """
    if kalender.benutzer_id != person.id:
        raise AustauschFehler("kalender_nicht_gefunden")

    termine = list(
        db.scalars(
            select(Termin)
            .where(Termin.kalender_id == kalender.id)
            .order_by(Termin.beginn)
        )
    )

    jetzt = datetime.now(timezone.utc)
    zonen: dict[str, str] = {}
    ereignisse: list[str] = []

    # ⚠️ **Keine eigene Wache gegen Doppel.** ``uq_termin_uid`` ueber
    # (kalender_id, uid, recurrence_id) schliesst sie aus; eine zweite
    # daneben liesse sich gegen keine Mutation pruefen und rostete vor sich
    # hin — dieselbe Lehre wie bei der Digest-Pruefung in ``caldav.py``.
    for termin in termine:
        schluessel = (termin.uid, termin.recurrence_id or "")
        block = ""
        if termin.roh:
            for kandidat in _bloecke(termin.roh, "VEVENT"):
                if _kennung(kandidat) == schluessel:
                    block = kandidat
                    break
            for zone in _bloecke(termin.roh, "VTIMEZONE"):
                name = _tzid(zone)
                if name and name not in zonen:
                    zonen[name] = zone

        if not block:
            # ⚠️ Ein in nexmail angelegter Termin hat kein Original. Dann ist
            # der Nachbau nicht der zweitbeste Weg, sondern der einzige.
            gebaut = vevent.bauen(termin, jetzt)
            treffer = _bloecke(gebaut, "VEVENT")
            if not treffer:
                continue
            block = treffer[0]
        ereignisse.append(block)

    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//nexapps//nexmail//DE",
        "CALSCALE:GREGORIAN",
        # ⚠️ Der Name kommt aus der Datenbank und darf ein Komma tragen —
        # im Format trennt das Parameter.
        f"X-WR-CALNAME:{maskieren(kalender.name)}",
    ]
    for zone in zonen.values():
        zeilen.append(zone)
    zeilen += ereignisse
    zeilen.append("END:VCALENDAR")

    gefaltet: list[str] = []
    for zeile in "\n".join(zeilen).split("\n"):
        gefaltet += vevent._falten(zeile)
    logger.info("A calendar was exported (%s event(s)).", len(ereignisse))
    # ⚠️ CRLF, nicht ``\n`` — manche Leser weisen alles andere ab.
    return "\r\n".join(gefaltet) + "\r\n"


def dateiname(kalender: Kalender) -> str:
    """Ein Dateiname, der auf jedem Dateisystem ankommt."""
    from .austausch import sicherer_stamm

    return f"{sicherer_stamm(kalender.name, 'kalender')}.ics"


# --- Einlesen ------------------------------------------------------------- #


def einlesen(db: Session, person: Benutzer, kalender: Kalender, roh: str) -> Bericht:
    """Die ``VEVENT`` einer Datei in einen Kalender übernehmen.

    ⚠️ **Übersprungen wird an ``UID`` samt ``RECURRENCE-ID``**, und darauf ruht
    alles: Wer dieselbe Datei zweimal einliest — weil der erste Anlauf abbrach
    oder weil er nicht mehr weiß, ob er es schon getan hat —, bekommt seinen
    Kalender sonst doppelt. Dieselbe Regel wie die ``Message-ID`` beim
    mbox-Import.

    ⚠️ **Nur in einen Kalender, der hier lebt.** Siehe den Kopf dieser Datei.

    ⚠️ **Ein kaputter Termin kostet nicht die Datei.** Er kommt von einem
    fremden Programm; sein Fehler steht im Bericht, die anderen kommen an.
    """
    if kalender.benutzer_id != person.id:
        raise AustauschFehler("kalender_nicht_gefunden")
    if kalender.nur_lesen:
        raise AustauschFehler("kalender_nur_lesen")
    if kalender.art:
        raise AustauschFehler("einfuhr_nur_in_eigenen_kalender")

    if "BEGIN:VCALENDAR" not in roh.upper():
        raise AustauschFehler("keine_ics_datei")

    bericht = Bericht()
    vorhanden = {
        (u, r or "")
        for u, r in db.execute(
            select(Termin.uid, Termin.recurrence_id).where(Termin.kalender_id == kalender.id)
        )
    }

    for daten in vevent.lesen(roh):
        if bericht.angelegt >= MAX_TERMINE:
            bericht.abgeschnitten = True
            break
        try:
            if not daten["uid"] or daten["beginn"] is None:
                bericht.unbrauchbar += 1
                continue
            schluessel = (daten["uid"], daten["recurrence_id"] or "")
            if schluessel in vorhanden:
                bericht.uebersprungen += 1
                continue
            vorhanden.add(schluessel)

            db.add(
                Termin(
                    kalender_id=kalender.id,
                    benutzer_id=person.id,
                    uid=daten["uid"],
                    recurrence_id=daten["recurrence_id"],
                    # ⚠️ **Die Rückfahrkarte kommt mit.** Was nexmail nicht
                    # versteht, geht beim nächsten Ausgeben wieder hinaus.
                    roh=roh,
                    **{
                        feld: daten[feld]
                        for feld in (
                            "titel", "beschreibung", "ort", "beginn", "ende",
                            "ganztaegig", "zeitzone", "rrule", "exdate",
                            "sequenz", "status", "erinnerung",
                        )
                    },
                    organisator=json.dumps(daten["organisator"]) if daten["organisator"] else "",
                    teilnehmer=json.dumps(daten["teilnehmer"]) if daten["teilnehmer"] else "",
                )
            )
            bericht.angelegt += 1
        except Exception as fehler:  # noqa: BLE001
            # ⚠️ Der Titel steht dabei, sonst sucht man den Termin in einer
            # Datei mit dreitausend Zeilen.
            bericht.fehler.append(f"{daten.get('titel') or daten.get('uid') or '?'}: {fehler}")

    db.commit()
    logger.info(
        "A calendar import finished: %s created, %s skipped, %s unusable.",
        bericht.angelegt,
        bericht.uebersprungen,
        bericht.unbrauchbar,
    )
    return bericht
