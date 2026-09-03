"""Termin-Einladungen lesen und beantworten (iCalendar, RFC 5545).

⚠️ **Kein Kalender.** nexmail zeigt die Einladung und sagt dem Einladenden
Bescheid. Es legt den Termin nirgends ab — dafür braucht es weiterhin ein
Kalenderprogramm. Wer das verwechselt, wartet auf eine Erinnerung, die nie
kommt; deshalb sagt es auch die Oberfläche.

⚠️ **Von Hand gelesen, ohne Bibliothek.** Gebraucht wird ein kleiner
Ausschnitt: ein ``VEVENT`` mit Titel, Zeit, Ort, Einladendem und Teilnehmern.
Eine Bibliothek dafür brächte zwei weitere Abhängigkeiten mit, und jede
gepinnte Fassung will fortan gegen OSV geprüft werden (siehe CLAUDE.md,
„Abhaengigkeiten: gepinnt heisst nicht geprueft"). Der Preis dafür steht unten
unter „Was hier NICHT geht" — ehrlich aufgezählt statt stillschweigend falsch
angezeigt.

**Die drei Fallen, an denen ein selbstgebauter Leser scheitert:**

1. **Gefaltete Zeilen.** RFC 5545 bricht lange Zeilen um und rückt die
   Fortsetzung mit einem Leerzeichen ein. Wer erst an ``\\n`` trennt, zerlegt
   mitten im Titel.
2. **Der Doppelpunkt in Parametern.** ``ORGANIZER;CN="Meier: Chef":mailto:…``
   — der erste Doppelpunkt gehört zum Namen, nicht zum Wert.
3. **Maskierter Text.** ``\\n``, ``\\,``, ``\\;`` und ``\\\\`` stehen für
   Zeichen, nicht für sich selbst.

**Was hier NICHT geht**, und was die Oberfläche deshalb sagt statt zu raten:

* Wiederholungen (``RRULE``) werden **erkannt und benannt**, aber nicht
  ausgerechnet. Angezeigt wird der erste Termin plus der Hinweis, dass er sich
  wiederholt.
* Eigene Zeitzonen-Definitionen (``VTIMEZONE``) werden nicht ausgewertet. Ein
  ``TZID``, das die Zeitzonendatenbank kennt (``Europe/Berlin``), wird richtig
  umgerechnet; ein unbekanntes wird **mit seinem Namen** angezeigt statt
  stillschweigend als Ortszeit ausgegeben.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("nexmail.kalender")

#: Was nexmail als Antwort kennt — und was daraus im ``PARTSTAT`` wird.
ANTWORTEN = {
    "zusage": "ACCEPTED",
    "vorbehalt": "TENTATIVE",
    "absage": "DECLINED",
}

_FALTUNG = re.compile(r"\r?\n[ \t]")


@dataclass
class Person:
    name: str = ""
    adresse: str = ""


@dataclass
class Termin:
    uid: str = ""
    #: ``REQUEST``, ``CANCEL``, ``REPLY`` … aus dem ``METHOD`` des Kalenders.
    methode: str = ""
    titel: str = ""
    beschreibung: str = ""
    ort: str = ""
    #: ISO-8601 mit Zeitzone, oder ``JJJJ-MM-TT`` bei einem ganztägigen Termin.
    beginn: str = ""
    ende: str = ""
    ganztaegig: bool = False
    #: Der Name der Zeitzone, wenn sie unbekannt war — dann steht die Zeit so
    #: da, wie sie in der Einladung stand, und die Oberfläche nennt die Zone.
    fremde_zeitzone: str = ""
    wiederholt_sich: bool = False
    abgesagt: bool = False
    organisator: Person = field(default_factory=Person)
    teilnehmer: list[Person] = field(default_factory=list)
    #: Fortlaufende Nummer der Einladung. Gehört in die Antwort, sonst hält der
    #: Einladende sie für eine Antwort auf eine ältere Fassung.
    sequenz: int = 0


def _entfalten(roh: str) -> list[str]:
    """Die gefalteten Zeilen wieder zusammensetzen."""
    return [z for z in _FALTUNG.sub("", roh.replace("\r\n", "\n")).split("\n") if z.strip()]


def _text_lesen(wert: str) -> str:
    """Die Maskierung nach RFC 5545 aufheben."""
    aus: list[str] = []
    i = 0
    while i < len(wert):
        z = wert[i]
        if z == "\\" and i + 1 < len(wert):
            naechstes = wert[i + 1]
            aus.append({"n": "\n", "N": "\n"}.get(naechstes, naechstes))
            i += 2
            continue
        aus.append(z)
        i += 1
    return "".join(aus)


def _zeile_zerlegen(zeile: str) -> tuple[str, dict[str, str], str]:
    """``NAME;PARAM=WERT:Inhalt`` in seine drei Teile.

    ⚠️ **Der erste Doppelpunkt ist nicht immer der richtige.** In
    ``ORGANIZER;CN="Meier: Chef":mailto:…`` steckt einer im Namen. Gesucht wird
    deshalb der erste Doppelpunkt **außerhalb** von Anführungszeichen.
    """
    in_zitat = False
    trenner = -1
    for i, z in enumerate(zeile):
        if z == '"':
            in_zitat = not in_zitat
        elif z == ":" and not in_zitat:
            trenner = i
            break
    if trenner < 0:
        return zeile.upper(), {}, ""

    kopf, wert = zeile[:trenner], zeile[trenner + 1 :]
    stuecke = _teilen_ausserhalb_zitat(kopf, ";")
    name = stuecke[0].upper()
    parameter: dict[str, str] = {}
    for stueck in stuecke[1:]:
        if "=" not in stueck:
            continue
        p_name, p_wert = stueck.split("=", 1)
        parameter[p_name.upper()] = p_wert.strip('"')
    return name, parameter, wert


def _teilen_ausserhalb_zitat(wert: str, trenner: str) -> list[str]:
    aus: list[str] = []
    stand = []
    in_zitat = False
    for z in wert:
        if z == '"':
            in_zitat = not in_zitat
        if z == trenner and not in_zitat:
            aus.append("".join(stand))
            stand = []
            continue
        stand.append(z)
    aus.append("".join(stand))
    return aus


def _person(wert: str, parameter: dict[str, str]) -> Person:
    adresse = wert.strip()
    if adresse.lower().startswith("mailto:"):
        adresse = adresse[7:]
    return Person(name=_text_lesen(parameter.get("CN", "")), adresse=adresse.strip())


def _zeit_lesen(wert: str, parameter: dict[str, str], zielzone: str) -> tuple[str, bool, str]:
    """Rückgabe: ISO-Zeichenkette, ganztägig, unbekannte Zeitzone.

    ⚠️ **Drei Formen, und jede bedeutet etwas anderes.** ``JJJJMMTT`` ist ein
    ganzer Tag. ``…Z`` ist UTC. Alles andere ist Ortszeit in der Zone aus
    ``TZID`` — und wenn wir die nicht kennen, wird sie **nicht** stillschweigend
    als unsere gelesen.
    """
    roh = wert.strip()
    if parameter.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", roh):
        try:
            return date(int(roh[0:4]), int(roh[4:6]), int(roh[6:8])).isoformat(), True, ""
        except ValueError:
            return "", True, ""

    treffer = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", roh)
    if not treffer:
        return "", False, ""
    tag, uhr, zulu = treffer.groups()
    naiv = datetime(
        int(tag[0:4]), int(tag[4:6]), int(tag[6:8]),
        int(uhr[0:2]), int(uhr[2:4]), int(uhr[4:6]),
    )

    if zulu:
        quelle = naiv.replace(tzinfo=timezone.utc)
    else:
        tzid = parameter.get("TZID", "")
        if not tzid:
            # Ohne Zone ist es „schwebende" Zeit: Sie gilt überall gleich
            # abgelesen. Wir zeigen sie so, wie sie dasteht.
            return naiv.isoformat(), False, ""
        try:
            quelle = naiv.replace(tzinfo=ZoneInfo(tzid))
        except Exception:  # noqa: BLE001
            # ⚠️ Unbekannte Zone: nicht raten. Die Zeit steht, wie sie kam,
            # und die Oberfläche nennt den Namen dazu.
            return naiv.isoformat(), False, tzid

    # ⚠️ Die EIGENE Zone laut ausweichen (services/zeit.py); die FREMDE aus der
    # Einladung wird oben zurueckgegeben und in der Oberflaeche benannt.
    from . import zeit as zeitdienst

    return quelle.astimezone(zeitdienst.zone(zielzone)).isoformat(), False, ""


def lesen(roh: bytes | str, zeitzone: str = "UTC") -> Termin | None:
    """Eine ``.ics`` in einen Termin — oder ``None``, wenn keiner darin steckt."""
    if isinstance(roh, bytes):
        text = roh.decode("utf-8", errors="replace")
    else:
        text = roh
    if "BEGIN:VEVENT" not in text.upper():
        return None

    termin = Termin()
    im_event = False
    #: ⚠️ **Ein ``VEVENT`` enthaelt andere Bestandteile.** Ein ``VALARM`` traegt
    #: ein eigenes ``DESCRIPTION`` („Erinnerung"), oft auch ein ``SUMMARY`` und
    #: eine ``DURATION``. Wer die Verschachtelung nicht verfolgt, schreibt die
    #: Erinnerung als Beschreibung des Termins in die Karte — am 03.09.2026 an
    #: einer echten Einladung gesehen. Dieselbe Falle steht fuer ``vevent.py``
    #: schon in CLAUDE.md; hier ist der zweite Leser.
    tiefer = 0
    dauer = ""
    for zeile in _entfalten(text):
        name, parameter, wert = _zeile_zerlegen(zeile)
        if name == "METHOD" and not im_event:
            termin.methode = wert.strip().upper()
            continue
        if name == "BEGIN" and wert.strip().upper() == "VEVENT":
            im_event = True
            continue
        if name == "END" and wert.strip().upper() == "VEVENT" and not tiefer:
            break
        if not im_event:
            continue

        # Alles zwischen einem inneren BEGIN und seinem END gehoert dorthin.
        if name == "BEGIN":
            tiefer += 1
            continue
        if name == "END":
            tiefer = max(0, tiefer - 1)
            continue
        if tiefer:
            continue

        if name == "UID":
            termin.uid = wert.strip()
        elif name == "SUMMARY":
            termin.titel = _text_lesen(wert)
        elif name == "DESCRIPTION":
            termin.beschreibung = _text_lesen(wert)
        elif name == "LOCATION":
            termin.ort = _text_lesen(wert)
        elif name == "DTSTART":
            termin.beginn, termin.ganztaegig, termin.fremde_zeitzone = _zeit_lesen(
                wert, parameter, zeitzone
            )
        elif name == "DTEND":
            termin.ende, _, _ = _zeit_lesen(wert, parameter, zeitzone)
        elif name == "DURATION":
            dauer = wert.strip()
        elif name == "RRULE":
            termin.wiederholt_sich = True
        elif name == "STATUS":
            termin.abgesagt = wert.strip().upper() == "CANCELLED"
        elif name == "SEQUENCE":
            try:
                termin.sequenz = int(wert.strip())
            except ValueError:
                pass
        elif name == "ORGANIZER":
            termin.organisator = _person(wert, parameter)
        elif name == "ATTENDEE":
            termin.teilnehmer.append(_person(wert, parameter))

    if termin.methode == "CANCEL":
        termin.abgesagt = True
    if not termin.ende and dauer and termin.beginn and not termin.ganztaegig:
        termin.ende = _ende_aus_dauer(termin.beginn, dauer)
    return termin if termin.uid or termin.titel else None


def _ende_aus_dauer(beginn: str, dauer: str) -> str:
    """``DURATION:PT1H30M`` auf den Beginn addieren."""
    treffer = re.fullmatch(
        r"[+-]?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", dauer.upper()
    )
    if not treffer:
        return ""
    wochen, tage, stunden, minuten, sekunden = (int(g or 0) for g in treffer.groups())
    try:
        ab = datetime.fromisoformat(beginn)
    except ValueError:
        return ""
    return (
        ab
        + timedelta(
            weeks=wochen, days=tage, hours=stunden, minutes=minuten, seconds=sekunden
        )
    ).isoformat()


def _maskieren(wert: str) -> str:
    return (
        wert.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def antwort_bauen(termin: Termin, ich: Person, antwort: str, jetzt: datetime) -> str:
    """Die ``.ics`` der Antwort — ``METHOD:REPLY`` mit genau einem Teilnehmer.

    ⚠️ **Genau einer, nämlich ich.** Eine Antwort, die alle Teilnehmer
    mitschickt, behauptet, für alle zu sprechen — manche Server übernehmen das
    sogar.

    ⚠️ **``SEQUENCE`` und ``UID`` werden übernommen.** Ohne sie hält der
    Einladende die Antwort für eine auf eine ältere Fassung und zeigt sie
    entweder gar nicht oder als überholt an.
    """
    partstat = ANTWORTEN[antwort]
    stempel = jetzt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f';CN="{_maskieren(ich.name)}"' if ich.name else ""
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//nexapps//nexmail//DE",
        "METHOD:REPLY",
        "BEGIN:VEVENT",
        f"UID:{termin.uid}",
        f"SEQUENCE:{termin.sequenz}",
        f"DTSTAMP:{stempel}",
        f"SUMMARY:{_maskieren(termin.titel)}",
    ]
    if termin.organisator.adresse:
        zeilen.append(f"ORGANIZER:mailto:{termin.organisator.adresse}")
    zeilen.append(f"ATTENDEE{name};PARTSTAT={partstat}:mailto:{ich.adresse}")
    zeilen += ["END:VEVENT", "END:VCALENDAR"]
    # ⚠️ Zeilenenden nach RFC 5545: CRLF, nicht LF.
    return "\r\n".join(zeilen) + "\r\n"
