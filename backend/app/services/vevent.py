"""``VEVENT`` lesen und schreiben — für den Kalender, nicht für Einladungen.

``services/kalender.py`` liest **eine** Einladung und beantwortet sie. Hier
geht es um den Bestand eines Kalenders: viele Termine, mit Wiederholungen,
Ausnahmen und überschriebenen Einzelterminen. Die Zerlegehilfen kommen von
dort — Faltung, Parameter und Maskierung sind dieselben, und zwei Fassungen
davon wären zwei Stellen, an denen dieselbe Falle zuschlägt.

⚠️ **Geschrieben wird auf dem Original, nicht daneben.** Ein ``VEVENT`` von
iCloud trägt Teilnehmer, Erinnerungen und ein Dutzend ``X-APPLE-…``. Wer beim
Zurückschreiben nur die Felder ausgibt, die er versteht, löscht dem Besitzer
stillschweigend seine Alarme und die halbe Teilnehmerliste. ``aktualisieren``
ersetzt deshalb einzelne Zeilen und lässt alles andere stehen — dieselbe
Überlegung wie bei mboxrd: Das Format muss verlustfrei durch nexmail
hindurchgehen.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from .kalender import _entfalten, _maskieren, _text_lesen, _zeile_zerlegen
from . import zeit as zeitdienst

logger = logging.getLogger("nexmail.vevent")

#: Die Zeilen, die nexmail selbst schreibt. Alles andere bleibt unberührt.
#: ⚠️ ``DTSTART``/``DTEND`` stehen hier mit, weil sich ihre Parameter aendern
#: koennen (``VALUE=DATE`` kommt und geht mit „ganztaegig").
EIGENE = (
    "SUMMARY",
    "DESCRIPTION",
    "LOCATION",
    "DTSTART",
    "DTEND",
    "DURATION",
    "RRULE",
    "EXDATE",
    "SEQUENCE",
    "LAST-MODIFIED",
    "DTSTAMP",
)


class VeventFehler(ValueError):
    pass


def _zeit_und_form(
    wert: str, parameter: dict[str, str]
) -> tuple[datetime | None, bool, str]:
    """Rückgabe: Zeitpunkt in UTC, ganztägig, Name der Zone.

    ⚠️ **Drei Formen, und jede bedeutet etwas anderes.** ``JJJJMMTT`` ist ein
    ganzer Tag, ``…Z`` ist UTC, alles andere ist Ortszeit in der Zone aus
    ``TZID``. Eine unbekannte Zone wird **nicht** stillschweigend als unsere
    gelesen — sie kommt als Name zurück, und der Aufrufer entscheidet.
    """
    roh = wert.strip()
    if parameter.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", roh):
        try:
            tag = date(int(roh[0:4]), int(roh[4:6]), int(roh[6:8]))
        except ValueError:
            return None, True, ""
        return datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc), True, ""

    treffer = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", roh)
    if not treffer:
        return None, False, ""
    tagteil, uhr, zulu = treffer.groups()
    naiv = datetime(
        int(tagteil[0:4]), int(tagteil[4:6]), int(tagteil[6:8]),
        int(uhr[0:2]), int(uhr[2:4]), int(uhr[4:6]),
    )
    if zulu:
        return naiv.replace(tzinfo=timezone.utc), False, "UTC"

    tzid = parameter.get("TZID", "")
    if not tzid:
        # „Schwebende" Zeit: Sie gilt überall gleich abgelesen. Wir legen sie
        # in der Zone der Anwendung ab und merken uns das.
        return naiv.replace(tzinfo=timezone.utc), False, ""
    zone = zeitdienst.zone(tzid)
    return naiv.replace(tzinfo=zone).astimezone(timezone.utc), False, tzid


def _dauer_lesen(wert: str) -> timedelta | None:
    """``PT1H30M``, ``P2D`` — die Formen, die wirklich vorkommen."""
    treffer = re.fullmatch(
        r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        wert.strip().upper(),
    )
    if not treffer:
        return None
    zeichen, wochen, tage, stunden, minuten, sekunden = treffer.groups()
    spanne = timedelta(
        weeks=int(wochen or 0), days=int(tage or 0), hours=int(stunden or 0),
        minutes=int(minuten or 0), seconds=int(sekunden or 0),
    )
    return -spanne if zeichen == "-" else spanne


def lesen(roh: str) -> list[dict]:
    """Alle ``VEVENT`` einer ``.ics`` als schlichte Wörterbücher.

    ⚠️ **Eine Datei kann mehrere Termine enthalten** — bei CalDAV liegt eine
    Reihe samt ihren überschriebenen Einzelterminen in **einer** Datei. Wer
    nur den ersten liest, verliert die Ausnahmen.

    ⚠️ **``VTIMEZONE`` wird übersprungen**, aber sein ``DTSTART`` darf nicht in
    den Termin geraten: Es steht dort für den Beginn einer Sommerzeitregel und
    ist mitten in einem ``VEVENT``-losen Block. Deshalb wird die Verschachtelung
    wirklich verfolgt, statt nur auf ``BEGIN:VEVENT`` zu warten.
    """
    if not roh:
        return []
    raus: list[dict] = []
    tiefe: list[str] = []
    aktuell: dict | None = None

    for zeile in _entfalten(roh):
        name, parameter, wert = _zeile_zerlegen(zeile)
        if name == "BEGIN":
            tiefe.append(wert.strip().upper())
            if tiefe[-1] == "VEVENT" and len(tiefe) >= 1:
                aktuell = {"exdate": [], "roh_zeilen": []}
            continue
        if name == "END":
            geschlossen = tiefe.pop() if tiefe else ""
            if geschlossen == "VEVENT" and aktuell is not None:
                raus.append(_fertig(aktuell))
                aktuell = None
            continue
        if aktuell is None or (tiefe and tiefe[-1] != "VEVENT"):
            # ⚠️ **Ein VALARM ist die eine Ausnahme.** Alles andere ausserhalb
            # des VEVENT — VTIMEZONE zumal — gehoert dorthin und wird nicht
            # gelesen. Der Alarm aber ist eine Eigenschaft des Termins: Ohne
            # ihn hier zeigte nexmail keine Erinnerung an, die ein anderer
            # Client gesetzt hat.
            if name == "TRIGGER" and tiefe[-1:] == ["VALARM"] and "erinnerung" not in aktuell:
                minuten = _trigger_lesen(wert, parameter)
                if minuten is not None:
                    aktuell["erinnerung"] = minuten
            continue
        _eintragen(aktuell, name, parameter, wert)

    return raus


def _trigger_lesen(wert: str, parameter: dict[str, str]) -> int | None:
    """``TRIGGER:-PT15M`` als Minuten vor dem Beginn — oder ``None``.

    ⚠️ **Nur relative Alarme vor dem Beginn.** Ein absoluter
    (``VALUE=DATE-TIME``) oder einer, der sich am Ende ausrichtet
    (``RELATED=END``), laesst sich nicht als „X Minuten vorher" anzeigen. Er
    bleibt in ``roh`` stehen und wird nicht angetastet — falsch anzuzeigen
    waere schlimmer, als nichts anzuzeigen.
    """
    if parameter.get("VALUE", "").upper() == "DATE-TIME":
        return None
    if parameter.get("RELATED", "START").upper() != "START":
        return None
    text = wert.strip().upper()
    if not text.startswith("-P"):
        # Ein Alarm NACH dem Beginn — gibt es, ist hier aber keine Erinnerung.
        return None
    treffer = re.fullmatch(r"-P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text)
    if treffer is None:
        return None
    tage, stunden, minuten, sekunden = (int(g or 0) for g in treffer.groups())
    gesamt = tage * 1440 + stunden * 60 + minuten + sekunden // 60
    return gesamt


def _person_lesen(wert: str, parameter: dict[str, str]) -> dict:
    """``ATTENDEE;CN=Anja;PARTSTAT=ACCEPTED:mailto:anja@example.com``.

    ⚠️ **Gelesen, aber nicht geschrieben.** Teilnehmer stehen NICHT in
    ``EIGENE``: Sie bleiben in ``roh`` und gehen unangetastet zurueck. nexmail
    zeigt sie nur — wer sie aendern koennte, muesste auch einladen koennen,
    und dazu gehoert der ganze Rueckkanal (siehe SPAETER.md).
    """
    adresse = wert.strip()
    if adresse.lower().startswith("mailto:"):
        adresse = adresse[7:]
    return {
        "name": _text_lesen(parameter.get("CN", "")),
        "adresse": adresse.strip(),
        # NEEDS-ACTION | ACCEPTED | DECLINED | TENTATIVE | DELEGATED
        "antwort": parameter.get("PARTSTAT", "").upper(),
        "rolle": parameter.get("ROLE", "").upper(),
    }


def _eintragen(ziel: dict, name: str, parameter: dict[str, str], wert: str) -> None:
    if name == "ORGANIZER":
        ziel["organisator"] = _person_lesen(wert, parameter)
    elif name == "ATTENDEE":
        ziel.setdefault("teilnehmer", []).append(_person_lesen(wert, parameter))
    elif name == "UID":
        ziel["uid"] = wert.strip()
    elif name == "SUMMARY":
        ziel["titel"] = _text_lesen(wert)
    elif name == "DESCRIPTION":
        ziel["beschreibung"] = _text_lesen(wert)
    elif name == "LOCATION":
        ziel["ort"] = _text_lesen(wert)
    elif name == "DTSTART":
        ziel["beginn"], ziel["ganztaegig"], ziel["zeitzone"] = _zeit_und_form(wert, parameter)
    elif name == "DTEND":
        ziel["ende"], _, _ = _zeit_und_form(wert, parameter)
    elif name == "DURATION":
        ziel["dauer"] = _dauer_lesen(wert)
    elif name == "RRULE":
        ziel["rrule"] = wert.strip()
    elif name == "EXDATE":
        for stueck in wert.split(","):
            wann, _, _ = _zeit_und_form(stueck, parameter)
            if wann:
                ziel["exdate"].append(wann.isoformat())
    elif name == "RECURRENCE-ID":
        wann, _, _ = _zeit_und_form(wert, parameter)
        if wann:
            ziel["recurrence_id"] = wann.isoformat()
    elif name == "SEQUENCE":
        try:
            ziel["sequenz"] = int(wert.strip())
        except ValueError:
            ziel["sequenz"] = 0
    elif name == "STATUS":
        ziel["status"] = wert.strip().upper()


def _fertig(roh: dict) -> dict:
    """Fehlendes ergänzen — nach den Regeln, die RFC 5545 dafür vorgibt."""
    beginn = roh.get("beginn")
    ganztaegig = bool(roh.get("ganztaegig"))
    ende = roh.get("ende")
    if ende is None and beginn is not None:
        dauer = roh.get("dauer")
        if dauer:
            ende = beginn + dauer
        else:
            # ⚠️ **Ohne DTEND und ohne DURATION** dauert ein ganztägiger Termin
            # einen Tag und ein zeitgebundener null Sekunden (RFC 5545 3.6.1).
            # Null Sekunden zeichnet man nicht — daraus wird eine Stunde, und
            # das ist die Wahl jedes Kalenderprogramms.
            ende = beginn + (timedelta(days=1) if ganztaegig else timedelta(hours=1))
    return {
        "uid": roh.get("uid", ""),
        "titel": roh.get("titel", ""),
        "beschreibung": roh.get("beschreibung", ""),
        "ort": roh.get("ort", ""),
        "beginn": beginn,
        "ende": ende,
        "ganztaegig": ganztaegig,
        "zeitzone": roh.get("zeitzone", "") or "UTC",
        "rrule": roh.get("rrule", ""),
        "exdate": ",".join(roh.get("exdate", [])),
        "recurrence_id": roh.get("recurrence_id", ""),
        "sequenz": roh.get("sequenz", 0),
        "status": roh.get("status", "CONFIRMED"),
        # -1 heisst „kein Alarm, den nexmail anzeigen kann" — das ist auch der
        # Fall bei einem absoluten oder am Ende ausgerichteten VALARM.
        "erinnerung": roh.get("erinnerung", -1),
        "organisator": roh.get("organisator") or None,
        "teilnehmer": roh.get("teilnehmer", []),
    }


# --- Schreiben ------------------------------------------------------------ #


def _zeitzeile(name: str, wann: datetime, ganztaegig: bool, zone: str) -> str:
    if ganztaegig:
        return f"{name};VALUE=DATE:{wann.astimezone(timezone.utc):%Y%m%d}"
    if not zone or zone == "UTC":
        return f"{name}:{wann.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
    ortszeit = wann.astimezone(zeitdienst.zone(zone))
    return f"{name};TZID={zone}:{ortszeit:%Y%m%dT%H%M%S}"


def _zeilen_fuer(termin, jetzt: datetime) -> list[str]:
    """Die Zeilen, die nexmail verantwortet — in der Reihenfolge des Formats."""
    zeilen = [
        f"UID:{termin.uid}",
        f"DTSTAMP:{jetzt.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
        _zeitzeile("DTSTART", termin.beginn, termin.ganztaegig, termin.zeitzone),
        _zeitzeile("DTEND", termin.ende, termin.ganztaegig, termin.zeitzone),
        f"SUMMARY:{_maskieren(termin.titel)}",
        f"SEQUENCE:{termin.sequenz}",
    ]
    if termin.ort:
        zeilen.append(f"LOCATION:{_maskieren(termin.ort)}")
    if termin.beschreibung:
        zeilen.append(f"DESCRIPTION:{_maskieren(termin.beschreibung)}")
    if termin.rrule:
        zeilen.append(f"RRULE:{termin.rrule}")
    for stueck in [s for s in termin.exdate.split(",") if s]:
        try:
            wann = datetime.fromisoformat(stueck)
        except ValueError:
            continue
        zeilen.append(_zeitzeile("EXDATE", wann, termin.ganztaegig, termin.zeitzone))
    if termin.recurrence_id:
        try:
            wann = datetime.fromisoformat(termin.recurrence_id)
            zeilen.append(_zeitzeile("RECURRENCE-ID", wann, termin.ganztaegig, termin.zeitzone))
        except ValueError:
            pass
    return zeilen


def _alarm_zeilen(minuten: int) -> list[str]:
    """Ein ``VALARM``, wie ihn jeder Client versteht.

    ⚠️ **``ACTION:DISPLAY`` und ein ``DESCRIPTION`` sind Pflicht** (RFC 5545
    3.6.6). Ohne die Beschreibung weisen manche Server den ganzen Termin ab,
    und andere zeigen einen leeren Alarm.
    """
    return [
        "BEGIN:VALARM",
        f"TRIGGER:-PT{minuten}M",
        "ACTION:DISPLAY",
        "DESCRIPTION:Erinnerung",
        "END:VALARM",
    ]


def _falten(zeile: str) -> list[str]:
    """⚠️ **Zeilen über 75 Oktett müssen umgebrochen werden** (RFC 5545 3.1).

    Manche Server weisen eine zu lange Zeile ab, andere schneiden sie ab — und
    dann fehlt die Hälfte des Titels, ohne dass jemand einen Fehler sieht.

    ⚠️ **Gezählt werden Oktett, getrennt wird zwischen Zeichen.** „ä" sind zwei
    Bytes; wer stumpf bei 75 schneidet, zerlegt es und bekommt beim Lesen einen
    Dekodierfehler. Am 03.09.2026 beim ersten Testlauf genau so passiert — und
    ``errors="ignore"`` wäre die schlimmere Behebung gewesen: Dann fehlte
    einfach ein Buchstabe.
    """
    roh = zeile.encode("utf-8")
    if len(roh) <= 75:
        return [zeile]

    raus: list[str] = []
    i = 0
    erste = True
    while i < len(roh):
        breite = 75 if erste else 74
        ende = min(i + breite, len(roh))
        # Zurück, solange die Grenze mitten in einem Zeichen läge — erkennbar
        # daran, dass das Byte DAHINTER ein Folgebyte ist (10xxxxxx).
        while ende > i + 1 and ende < len(roh) and (roh[ende] & 0xC0) == 0x80:
            ende -= 1
        raus.append(("" if erste else " ") + roh[i:ende].decode("utf-8"))
        i = ende
        erste = False
    return raus


def bauen(termin, jetzt: datetime) -> str:
    """Eine vollständige ``.ics`` mit genau einem ``VEVENT``.

    Für Termine, die in nexmail entstanden sind — dort gibt es kein Original,
    auf dem man schreiben könnte.
    """
    zeilen = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//nexapps//nexmail//DE", "BEGIN:VEVENT"]
    zeilen += _zeilen_fuer(termin, jetzt)
    if getattr(termin, "erinnerung", -1) >= 0:
        zeilen += _alarm_zeilen(termin.erinnerung)
    zeilen += ["END:VEVENT", "END:VCALENDAR"]
    gefaltet: list[str] = []
    for zeile in zeilen:
        gefaltet += _falten(zeile)
    # ⚠️ CRLF, nicht ``\n``. Manche Server weisen alles andere ab.
    return "\r\n".join(gefaltet) + "\r\n"


def aktualisieren(roh: str, termin, jetzt: datetime, alarm_ersetzen: bool = False) -> str:
    """Die eigenen Zeilen in einem vorhandenen ``VEVENT`` ersetzen.

    ⚠️ **Das ist die Rückfahrkarte.** Alles, was nexmail nicht kennt — Alarme,
    Teilnehmer, ``X-APPLE-…`` —, bleibt unangetastet stehen. Wer stattdessen
    neu baut, löscht dem Besitzer die Hälfte seines Termins, und er merkt es
    erst, wenn die Erinnerung ausbleibt.

    ⚠️ **``alarm_ersetzen`` nur, wenn jemand die Erinnerung wirklich
    angefasst hat.** Sonst gilt dasselbe wie fuer alles andere: nicht
    anfassen. Wer bei jedem Speichern die Alarme neu schreibt, wirft einem
    fremden Termin seinen Alarm mit E-Mail-Aktion oder festem Zeitpunkt weg —
    und der Besitzer merkt es erst, wenn die Erinnerung ausbleibt.

    Gibt es kein Original, wird eines gebaut.
    """
    if not roh or "BEGIN:VEVENT" not in roh.upper():
        return bauen(termin, jetzt)

    neue = _zeilen_fuer(termin, jetzt)
    if alarm_ersetzen and getattr(termin, "erinnerung", -1) >= 0:
        neue += _alarm_zeilen(termin.erinnerung)
    raus: list[str] = []
    tiefe: list[str] = []
    im_termin = False
    eingesetzt = False
    im_alarm = 0

    for zeile in _entfalten(roh):
        name, _, wert = _zeile_zerlegen(zeile)
        if name == "BEGIN":
            tiefe.append(wert.strip().upper())
            im_termin = tiefe[-1] == "VEVENT"
            if alarm_ersetzen and tiefe[-1] == "VALARM":
                im_alarm += 1
                continue
            if im_alarm:
                continue
            raus.append(zeile)
            continue
        if name == "END":
            geschlossen = tiefe.pop() if tiefe else ""
            if geschlossen == "VALARM" and im_alarm:
                im_alarm -= 1
                im_termin = bool(tiefe) and tiefe[-1] == "VEVENT"
                continue
            if im_alarm:
                continue
            if geschlossen == "VEVENT" and not eingesetzt:
                raus += neue
                eingesetzt = True
            im_termin = bool(tiefe) and tiefe[-1] == "VEVENT"
            raus.append(zeile)
            continue
        if im_alarm:
            # Der alte Alarm faellt weg — der neue steht schon in ``neue``.
            continue
        # ⚠️ Nur im VEVENT selbst filtern. Ein ``DTSTART`` in ``VALARM`` oder
        # ``VTIMEZONE`` gehoert dorthin und darf nicht verschwinden.
        if im_termin and name in EIGENE:
            continue
        raus.append(zeile)

    gefaltet: list[str] = []
    for zeile in raus:
        gefaltet += _falten(zeile)
    return "\r\n".join(gefaltet) + "\r\n"
