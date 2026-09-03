"""Wiederholte Termine ausrechnen — ``RRULE`` nach RFC 5545.

Ein wiederholter Termin steht **einmal** in der Datenbank. Was der Kalender
zeigt, wird für das sichtbare Fenster ausgerechnet; die einzelnen Vorkommen
werden nicht gespeichert.

⚠️ **Sonst wüchse ein „jeden Montag" ohne Ende ins Unendliche.** Eine Regel
ohne ``UNTIL`` und ohne ``COUNT`` läuft laut Norm ewig. Wer sie beim Anlegen
ausschreibt, muss raten, wie weit — und liegt beim ersten Blick ins Jahr 2031
daneben.

⚠️ **Gerechnet wird in der Zone des Termins, nicht in UTC.** „Jeden Montag um
9 Uhr" heißt neun Uhr Ortszeit, auch nachdem die Sommerzeit gewechselt hat.
Wer die Reihe in UTC ausrechnet, verschiebt den halben Kalender zweimal im
Jahr um eine Stunde — und niemand bringt das mit der Zeitumstellung in
Verbindung. Genau dafür wird hier in die Zone hinein- und wieder
herausgerechnet.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from dateutil import rrule as dr

from . import zeit as zeitdienst

logger = logging.getLogger("nexmail.wiederholung")

#: Wie viele Vorkommen ein Fenster höchstens hergibt.
#: ⚠️ **Eine Regel kann jede Sekunde treffen** (``FREQ=SECONDLY``). Ohne Deckel
#: rechnet ein einziger Termin den Server fest, und der Betreiber sieht nur
#: eine Seite, die nicht lädt.
MAX_VORKOMMEN = 1_000


@dataclass(frozen=True)
class Vorkommen:
    """Ein einzelnes Auftreten eines wiederholten Termins."""

    beginn: datetime
    ende: datetime
    #: Wahr beim ersten Vorkommen — die Reihe hängt an ihm.
    ist_start: bool = False


def _in_zone(wann: datetime, zone: str):
    """Einen Zeitpunkt in der Zone des Termins ablesen, ohne Zone am Ergebnis.

    ``dateutil.rrule`` rechnet mit *naiven* Zeitpunkten. Wer ihm eine Zone
    mitgibt, bekommt die Umstellung nicht — deshalb hinein, rechnen, hinaus.
    """
    return wann.astimezone(zeitdienst.zone(zone)).replace(tzinfo=None)


def _zurueck(naiv: datetime, zone: str) -> datetime:
    """Und wieder heraus. ⚠️ ``fold=0``: Bei der Stunde, die im Herbst zweimal
    kommt, gilt die erste — dieselbe Wahl wie in jedem Kalenderprogramm."""
    return naiv.replace(tzinfo=zeitdienst.zone(zone), fold=0).astimezone(timezone.utc)


def _ausnahmen(exdate: str, zone: str) -> set[datetime]:
    """Die ``EXDATE`` als Menge naiver Zeitpunkte in der Zone des Termins.

    ⚠️ **Verglichen wird auf die Minute, nicht auf die Sekunde.** Manche Server
    schreiben ``EXDATE`` mit Sekunden, andere ohne; ein Vergleich auf Gleichheit
    ließe die Ausnahme dann wirkungslos, und der abgesagte Termin stünde weiter
    im Kalender.
    """
    raus: set[datetime] = set()
    for teil in exdate.replace(" ", "").split(","):
        if not teil:
            continue
        try:
            wann = datetime.fromisoformat(teil)
        except ValueError:
            logger.debug("Unreadable EXDATE %r; ignored.", teil)
            continue
        naiv = _in_zone(wann, zone) if wann.tzinfo else wann
        raus.add(naiv.replace(second=0, microsecond=0))
    return raus


_UNTIL = re.compile(r"(UNTIL=)(\d{8}T\d{6})Z", re.IGNORECASE)


def _until_anpassen(rrule: str, zone: str) -> str:
    """``UNTIL=…Z`` in die Zone des Termins umrechnen.

    ⚠️ **Sonst scheitert jede Reihe mit Enddatum.** Gerechnet wird mit naiven
    Zeitpunkten in der Zone des Termins (siehe Kopf); ``UNTIL`` steht laut
    RFC 5545 bei einem Termin mit Uhrzeit aber **immer in UTC**. dateutil weist
    die Mischung ab — und der Rückfall „dann eben ein Einzeltermin" machte
    daraus stillschweigend einen Termin statt einer Reihe.

    Am 02.09.2026 beim ersten Testlauf aufgefallen. Die Meldung stand im
    Protokoll (``Unreadable RRULE``), die Oberfläche hätte nur einen Termin
    gezeigt und keinen Fehler.
    """

    def um(t: re.Match[str]) -> str:
        roh = t.group(2)
        wann = datetime(
            int(roh[0:4]), int(roh[4:6]), int(roh[6:8]),
            int(roh[9:11]), int(roh[11:13]), int(roh[13:15]),
            tzinfo=timezone.utc,
        )
        return t.group(1) + _in_zone(wann, zone).strftime("%Y%m%dT%H%M%S")

    return _UNTIL.sub(um, rrule)


def ausrechnen(
    beginn: datetime,
    ende: datetime,
    rrule: str,
    exdate: str,
    zone: str,
    von: datetime,
    bis: datetime,
) -> Iterator[Vorkommen]:
    """Alle Vorkommen, die das Fenster ``von``–``bis`` berühren.

    ⚠️ **Berühren, nicht beginnen.** Ein Termin von Freitag bis Montag gehört
    in die Woche, in der man am Samstag nachsieht — auch wenn er weder darin
    beginnt noch endet. Wer nur auf den Beginn prüft, lässt lange Termine aus
    der Mitte verschwinden.
    """
    dauer = ende - beginn

    if not rrule.strip():
        if beginn < bis and ende > von:
            yield Vorkommen(beginn, ende, ist_start=True)
        return

    naiv = _in_zone(beginn, zone)
    try:
        reihe = dr.rrulestr(f"RRULE:{_until_anpassen(rrule.strip(), zone)}", dtstart=naiv)
    except Exception:  # noqa: BLE001
        # ⚠️ **Eine kaputte Regel darf den Termin nicht verschlucken.** Sie
        # kommt von einem fremden Server; er darf uns keinen Eintrag kosten.
        logger.warning("Unreadable RRULE %r; showing the single event.", rrule)
        if beginn < bis and ende > von:
            yield Vorkommen(beginn, ende, ist_start=True)
        return

    ausnahmen = _ausnahmen(exdate, zone)
    # Rückwärts so weit, dass ein Vorkommen, das VOR dem Fenster beginnt und
    # hineinragt, noch gefunden wird.
    such_von = _in_zone(von, zone) - dauer
    such_bis = _in_zone(bis, zone)

    gezaehlt = 0
    for treffer in reihe.between(such_von, such_bis, inc=True):
        if treffer.replace(second=0, microsecond=0) in ausnahmen:
            continue
        gezaehlt += 1
        if gezaehlt > MAX_VORKOMMEN:
            logger.warning("More than %s occurrences in one window; cut off.", MAX_VORKOMMEN)
            return
        start = _zurueck(treffer, zone)
        yield Vorkommen(start, start + dauer, ist_start=treffer == naiv)


def naechstes(
    beginn: datetime, rrule: str, exdate: str, zone: str, ab: datetime
) -> datetime | None:
    """Das nächste Vorkommen ab einem Zeitpunkt — für Erinnerungen und Listen."""
    fenster = ab + timedelta(days=370)
    for v in ausrechnen(beginn, beginn, rrule, exdate, zone, ab, fenster):
        if v.beginn >= ab:
            return v.beginn
    return None


def als_satz(rrule: str) -> tuple[str, list[str], int]:
    """Die Regel als KENNUNG, Wochentage und Intervall — nicht als Satz.

    ⚠️ **Übersetzt wird vorn, nicht hier.** nexmail spricht zwei Sprachen; ein
    hier gebauter Satz wäre in einer davon falsch.

    ⚠️ **Die Wochentage kommen als Liste, nicht in der Kennung.** Ein
    ``woechentlich_tu_th`` als Übersetzungsschlüssel hiesse: für jede der 127
    möglichen Kombinationen ein eigener Satz in zwei Sprachen. Die Oberfläche
    setzt „Jede Woche · Di, Do" aus den Namen zusammen, die der Browser
    ohnehin kennt.
    """
    teile = dict(p.split("=", 1) for p in rrule.upper().split(";") if "=" in p)
    freq = teile.get("FREQ", "")
    if not freq:
        return "", [], 1
    try:
        intervall = max(1, int(teile.get("INTERVAL", "1")))
    except ValueError:
        intervall = 1
    stamm = {
        "SECONDLY": "sekuendlich",
        "MINUTELY": "minuetlich",
        "HOURLY": "stuendlich",
        "DAILY": "taeglich",
        "WEEKLY": "woechentlich",
        "MONTHLY": "monatlich",
        "YEARLY": "jaehrlich",
    }.get(freq, "allgemein")
    # ⚠️ Nur die schlichten Wochentage. „-1FR" (jeder letzte Freitag) ist etwas
    # anderes und wird nicht als „freitags" ausgegeben — das waere falsch.
    tage = [
        w for w in teile.get("BYDAY", "").split(",")
        if w in ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    ]
    if teile.get("BYDAY") and len(tage) != len(teile["BYDAY"].split(",")):
        return "allgemein", [], intervall
    return stamm, tage, intervall


# --- Die Regel als Bausteine ---------------------------------------------- #
#
# ⚠️ **Gelesen wird hier, zusammengesetzt in der Oberfläche, geprüft wieder
# hier.** Das klingt nach zwei Stellen und ist eine: Die Oberfläche baut eine
# Zeichenkette, aber die beiden Regeln, an denen man sich schneidet — ``UNTIL``
# steht in UTC, und ``COUNT`` und ``UNTIL`` schliessen sich aus —, entscheidet
# der Server. Eine Regel, die nur die Oberfläche kennt, gilt für keinen anderen
# Client.

#: Die Wochentage in der Reihenfolge, die RFC 5545 vorgibt.
TAGE = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

_ORDINAL = re.compile(r"^(-?\d+)(MO|TU|WE|TH|FR|SA|SU)$")


@dataclass
class Regel:
    """Eine Wiederholung, wie die Maske sie zeigt.

    ``fremd`` heisst: Die Regel enthaelt etwas, das die Maske nicht abbildet
    (``BYMONTHDAY``, ``BYSETPOS``, ``FREQ=HOURLY`` …). ⚠️ **Dann wird sie nicht
    zerlegt angeboten**, sondern bleibt als Ganzes stehen — sonst zerstoert ein
    Speichern die Wiederholung eines fremden Termins.
    """

    freq: str = ""
    intervall: int = 1
    #: Bei ``woechentlich``: MO..SU. Leer heisst „am Wochentag des Beginns".
    tage: list[str] = field(default_factory=list)
    #: Bei ``monatlich``: ``tag`` (am 17.) oder ``wochentag`` (am 3. Dienstag).
    monatsart: str = "tag"
    #: Der Wievielte bei ``monatsart="wochentag"``: 1..4, oder **-1 fuer den
    #: letzten**. ⚠️ Ohne ihn waere „jeder letzte Freitag" nicht von „jeder
    #: erste Freitag" zu unterscheiden.
    ordinal: int = 1
    #: ``nie`` | ``anzahl`` | ``datum``
    ende_art: str = "nie"
    anzahl: int = 0
    #: ``JJJJ-MM-TT`` — der letzte Tag, an dem die Reihe noch auftreten darf.
    bis: str = ""
    fremd: bool = False


#: Was die Maske anbietet. Alles andere ist ``fremd``.
_FREQ_ZU_KENNUNG = {
    "DAILY": "taeglich",
    "WEEKLY": "woechentlich",
    "MONTHLY": "monatlich",
    "YEARLY": "jaehrlich",
}
_KENNUNG_ZU_FREQ = {v: k for k, v in _FREQ_ZU_KENNUNG.items()}

#: Teile, die die Maske versteht. Steht hier eine andere, ist die Regel fremd.
_BEKANNT = {"FREQ", "INTERVAL", "BYDAY", "COUNT", "UNTIL", "WKST"}


def regel_lesen(rrule: str) -> Regel:
    """Eine ``RRULE`` in ihre Bausteine — oder ``fremd``."""
    if not rrule.strip():
        return Regel()
    teile = dict(p.split("=", 1) for p in rrule.upper().split(";") if "=" in p)
    freq = _FREQ_ZU_KENNUNG.get(teile.get("FREQ", ""), "")
    if not freq or set(teile) - _BEKANNT:
        return Regel(fremd=True)

    try:
        intervall = max(1, int(teile.get("INTERVAL", "1")))
    except ValueError:
        return Regel(fremd=True)

    tage: list[str] = []
    monatsart = "tag"
    ordinal = 1
    roh_tage = [w for w in teile.get("BYDAY", "").split(",") if w]
    for wert in roh_tage:
        if wert in TAGE:
            tage.append(wert)
            continue
        treffer = _ORDINAL.match(wert)
        # ⚠️ „Jeder dritte Dienstag" ist genau EIN Eintrag. Mehrere davon
        # (``1MO,3MO``) bildet die Maske nicht ab.
        if treffer is None or len(roh_tage) != 1 or freq != "monatlich":
            return Regel(fremd=True)
        monatsart = "wochentag"
        ordinal = int(treffer.group(1))
        if ordinal not in (1, 2, 3, 4, -1):
            return Regel(fremd=True)
        tage = [treffer.group(2)]

    ende_art, anzahl, bis = "nie", 0, ""
    if "COUNT" in teile:
        try:
            anzahl = int(teile["COUNT"])
        except ValueError:
            return Regel(fremd=True)
        ende_art = "anzahl"
    elif "UNTIL" in teile:
        roh = teile["UNTIL"]
        if len(roh) < 8 or not roh[:8].isdigit():
            return Regel(fremd=True)
        ende_art = "datum"
        bis = f"{roh[0:4]}-{roh[4:6]}-{roh[6:8]}"

    return Regel(
        freq=freq, intervall=intervall, tage=tage, monatsart=monatsart,
        ordinal=ordinal, ende_art=ende_art, anzahl=anzahl, bis=bis,
    )


def regel_normieren(rrule: str, beginn: datetime, zone: str) -> str:
    """Eine von der Oberfläche gebaute ``RRULE`` geradeziehen.

    ⚠️ **``COUNT`` und ``UNTIL`` schliessen sich aus** (RFC 5545). Wer beides
    schickt, baut eine Regel, die manche Clients gar nicht lesen. ``COUNT``
    gewinnt — es steht in der Maske vor dem Datum.

    ⚠️ **``UNTIL`` steht bei einem Termin mit Uhrzeit in UTC**, und es muss den
    letzten Tag noch **einschliessen**. Die Maske schickt ein Datum; daraus
    wird das Ende dieses Tages in der Zone des Termins, umgerechnet nach UTC.
    Ohne das fiele das letzte Vorkommen weg — und niemand brächte das mit dem
    Enddatum in Verbindung.
    """
    if not rrule.strip():
        return ""
    teile = [p for p in rrule.upper().split(";") if "=" in p]
    hat_count = any(p.startswith("COUNT=") for p in teile)
    raus: list[str] = []
    for stueck in teile:
        if stueck.startswith("UNTIL="):
            if hat_count:
                continue
            wert = stueck[6:]
            if len(wert) >= 8 and wert[:8].isdigit():
                stueck = f"UNTIL={_bis_utc(wert[:8], beginn, zone)}"
        raus.append(stueck)
    return ";".join(raus)


def _bis_utc(tag: str, beginn: datetime, zone: str) -> str:
    """``JJJJMMTT`` als letzter einschliessender Zeitpunkt, in UTC."""
    ende_des_tages = datetime(
        int(tag[0:4]), int(tag[4:6]), int(tag[6:8]), 23, 59, 59,
        tzinfo=zeitdienst.zone(zone) if zone else timezone.utc,
    )
    return ende_des_tages.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
