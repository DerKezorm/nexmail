"""Die Verbindung zu nextime — gespeichert, geprüft, umgerechnet (MAIL-1).

``nextime.py`` spricht mit nextime; hier steht, was nexmail daraus macht:

* **Eine Verbindung je Benutzer** (``NextimeVerbindung``). Verbinden prüft erst
  ``/me`` (alle Merkmale, Schreibrecht, Schlüssel für alle Kalender), dann
  wird gespeichert, verschlüsselt.
* **Kalender heißen ``nt:<id>``.** So stehen sie neben den eigenen
  (uuid-Kennungen) in derselben Liste, und niemand verwechselt beide.
* **Termine bekommen eine feste negative Nummer** aus Kalender, Termin und
  Vorkommen. Die Kalenderseite kennt Termine an einer Zahl; negativ heißt
  „aus nextime", und dieselbe Zahl bei jedem Laden hält Auswahl und offenes
  Fenster fest.
* **Umgerechnet wird über einen ``Termin`` ohne Datenbankzeile**, dieselbe
  Attrappe wie beim Konfliktbild: Dann gilt für nextime-Termine genau dieselbe
  ``TerminZeile`` wie für eigene, samt Wiederholungssatz.

⚠️ **Nichts von nextime wird gespeichert.** Wer etwas sehen will, fragt live.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..meldung import Meldung
from ..models import Benutzer, NextimeVerbindung, Termin, neue_id
from . import nextime, wiederholung

logger = logging.getLogger("nexmail.nextime")

#: Woran man einen nextime-Kalender in nexmail erkennt.
VORSILBE = "nt:"

#: Wie nexmails Umfang bei nextime heißt.
UMFANG = {"dieser": "this", "folgende": "following", "alle": "all"}

#: nexmails Antworten auf Einladungen, wie nextime sie nennt.
ANTWORT_NACH_NEXTIME = {"zusage": "accepted", "vorbehalt": "tentative", "absage": "declined"}
ANTWORT_VON_NEXTIME = {v: k for k, v in ANTWORT_NACH_NEXTIME.items()}

#: Teilnehmerstand, wie nexmail ihn in ``Termin.teilnehmer`` führt.
STAND = {"accepted": "ACCEPTED", "tentative": "TENTATIVE", "declined": "DECLINED", "open": "NEEDS-ACTION"}

_FREQ = {"taeglich": "daily", "woechentlich": "weekly", "monatlich": "monthly", "jaehrlich": "yearly"}
_FREQ_RRULE = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}
_TAGE = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


class VerbindungFehler(Meldung, RuntimeError):
    """Trägt eine KENNUNG, keinen deutschen Satz."""


# --- Verbindung ---------------------------------------------------------------- #


def _kontext(verbindung_id: str) -> str:
    return f"nextime_verbindung:{verbindung_id}:zugang"


def verbindung(db: Session, person: Benutzer) -> NextimeVerbindung | None:
    return db.scalars(
        select(NextimeVerbindung).where(NextimeVerbindung.benutzer_id == person.id)
    ).first()


def zugang(v: NextimeVerbindung) -> nextime.Zugang:
    return nextime.zugang_lesen(crypto.entschluesseln(v.zugang, _kontext(v.id)))


def gebraucht(db: Session, person: Benutzer) -> tuple[NextimeVerbindung, nextime.Zugang]:
    """Die Verbindung samt Zugang — oder ``nextime_nicht_verbunden``."""
    v = verbindung(db, person)
    if v is None:
        raise VerbindungFehler("nextime_nicht_verbunden")
    return v, zugang(v)


def verbinden(db: Session, person: Benutzer, url: str, token: str) -> tuple[NextimeVerbindung, int]:
    """nextime verbinden — erst prüfen, dann speichern. Gibt auch die Zahl der
    Kalender zurück, die der Schlüssel sieht.

    ⚠️ **Eine vorhandene Verbindung wird ersetzt, nicht verdoppelt.** Ihre
    Haken bleiben, wenn es dasselbe nextime ist; bei einer anderen Adresse
    gelten sie nicht mehr (die Kennungen gehören dort anderen Kalendern).
    """
    token = token.strip()
    if not token or len(token) > nextime.MAX_TOKEN:
        raise VerbindungFehler("nextime_schluessel_fehlt")
    neu = nextime.Zugang(url=nextime.adresse_bereinigen(url), token=token)
    ich = nextime.pruefen(neu)
    zahl = len(nextime.kalender(neu))

    v = verbindung(db, person)
    if v is None:
        v = NextimeVerbindung(id=neue_id(), benutzer_id=person.id, sichtbar="{}")
        db.add(v)
    else:
        try:
            alte_url = zugang(v).url
        except nextime.NextimeFehler:
            alte_url = ""
        if alte_url != neu.url:
            v.sichtbar = "{}"
    v.zugang = crypto.verschluesseln(nextime.zugang_schreiben(neu), _kontext(v.id))
    v.name = ich.name
    v.version = ich.version
    v.zeitzone = ich.zeitzone
    v.letzter_fehler = ""
    db.commit()
    logger.info("nextime was connected (version %s, %d calendar(s)).", ich.version or "-", zahl)
    return v, zahl


def trennen(db: Session, person: Benutzer) -> None:
    """⚠️ **Nur hier.** In nextime bleibt alles, auch Termine aus Mails."""
    v = verbindung(db, person)
    if v is not None:
        db.delete(v)
        db.commit()
        logger.info("nextime was disconnected.")


def adresse(v: NextimeVerbindung) -> str:
    try:
        return zugang(v).url
    except nextime.NextimeFehler:
        return ""


def fehler_merken(db: Session, v: NextimeVerbindung, fehler: Meldung | None) -> None:
    """Den letzten Fehler an der Verbindung — oder ihn löschen.

    ⚠️ **Nur Zugangsfehler bleiben stehen.** Ein Netzaussetzer stünde sonst
    unter „Verbindungen", lange nachdem er vorbei ist.
    """
    kennung = fehler.kennung if fehler else ""
    if kennung and kennung not in (
        "nextime_zugang_ungueltig", "nextime_api_aus", "nextime_nur_lesen", "nextime_zu_alt",
    ):
        return
    if v.letzter_fehler != kennung[:80]:
        v.letzter_fehler = kennung[:80]
        db.commit()


# --- Kalender -------------------------------------------------------------------- #


def _haken(v: NextimeVerbindung) -> dict[str, bool]:
    try:
        daten = json.loads(v.sichtbar or "{}")
    except ValueError:
        return {}
    return {str(k): bool(w) for k, w in daten.items()} if isinstance(daten, dict) else {}


def _ohne(v: NextimeVerbindung) -> set[int]:
    try:
        daten = json.loads(v.ohne or "[]")
    except ValueError:
        return set()
    return {int(x) for x in daten if isinstance(x, int) and not isinstance(x, bool)} if isinstance(daten, list) else set()


def kalender_id(roh: str) -> int:
    """``nt:12`` → 12. Alles andere ist kein nextime-Kalender."""
    if not roh.startswith(VORSILBE):
        raise VerbindungFehler("kalender_unbekannt")
    try:
        zahl = int(roh[len(VORSILBE):])
    except ValueError as f:
        raise VerbindungFehler("kalender_unbekannt") from f
    if zahl < 1:
        raise VerbindungFehler("kalender_unbekannt")
    return zahl


@dataclass
class Kalender:
    id: str
    nummer: int
    name: str
    farbe: str
    symbol: str
    sichtbar: bool
    beschreibbar: bool
    nur_belegt: bool
    hintergrund: bool
    gruppe: str
    quelle: str
    besitzer: str
    standard: bool
    #: Nimmt nexmail ihn überhaupt (Auswahl in der Karte)?
    gewaehlt: bool = True


def kalender_liste(v: NextimeVerbindung, roh: list[dict], *, alle: bool = False) -> list[Kalender]:
    """nextimes Kalender in nexmails Form, in nextimes Reihenfolge.

    ⚠️ **Nur die gewählten**, außer mit ``alle`` (für die Auswahl selbst): Ein
    nicht gewählter Kalender erscheint nirgends in nexmail, weder in der
    Seitenleiste noch bei „Neuer Termin", beim Zusagen oder bei den
    Überschneidungen (Entscheidung 23.11.2026).

    ⚠️ **Der Haken gilt nur in nexmail.** Ohne eigenen Haken gilt nextimes
    ``hidden``: In nextime ausgeblendet heißt anfangs auch hier ausgeblendet.
    """
    haken = _haken(v)
    ohne = _ohne(v)
    raus: list[Kalender] = []
    for k in roh:
        nummer = k.get("id")
        if not isinstance(nummer, int) or isinstance(nummer, bool):
            continue
        if nummer in ohne and not alle:
            continue
        schluessel = str(nummer)
        raus.append(
            Kalender(
                id=f"{VORSILBE}{nummer}",
                nummer=nummer,
                name=str(k.get("name") or "")[:200],
                farbe=str(k.get("color") or "slate")[:16],
                symbol=str(k.get("icon") or "")[:40],
                sichtbar=haken.get(schluessel, not bool(k.get("hidden"))),
                beschreibbar=bool(k.get("writable")),
                nur_belegt=bool(k.get("busy_only")),
                hintergrund=bool(k.get("background")),
                gruppe=str(k.get("group") or "own")[:20],
                quelle=str(k.get("source_name") or "")[:120],
                besitzer=str(k.get("owner") or "")[:200],
                standard=bool(k.get("default")),
                gewaehlt=nummer not in ohne,
            )
        )
    return raus


def auswahl_setzen(db: Session, v: NextimeVerbindung, roh_id: str, an: bool) -> None:
    """Einen nextime-Kalender in nexmail nehmen oder weglassen."""
    ohne = _ohne(v)
    nummer = kalender_id(roh_id)
    if an:
        ohne.discard(nummer)
    else:
        ohne.add(nummer)
    v.ohne = json.dumps(sorted(ohne))
    db.commit()


def sichtbar_setzen(db: Session, v: NextimeVerbindung, roh_id: str, an: bool) -> None:
    haken = _haken(v)
    haken[str(kalender_id(roh_id))] = bool(an)
    v.sichtbar = json.dumps(haken)
    db.commit()


# --- Zeiten -------------------------------------------------------------------- #


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def von_nextime(
    wert: object, ganztaegig: bool, *, ende: bool = False, zone: str = ""
) -> datetime | None:
    """nextimes Zeit als nexmails Zeitpunkt.

    ⚠️ **Zwei Formen, je nach Weg** (Prüfbericht MAIL-1, Befund 2): Liste,
    Suche und UID-Suche liefern UTC mit ``Z``; Einzelabruf, Anlegen, Ändern,
    Antworten und Eintragen liefern die **Wanduhr** ``YYYY-MM-DDTHH:MM`` in
    ``time_zone``. Eine Zeit ohne Versatz gilt deshalb in ``zone``, nie in UTC.

    ⚠️ **Ganztägig ist ein Datum, und nextimes Ende ist der LETZTE Tag.**
    nexmail legt ganztägige Termine auf 00:00 UTC und das Ende auf den Tag
    **danach** (wie ``DTEND``). Ohne den Tag mehr wäre ein eintägiger Termin
    null Tage lang.
    """
    if not isinstance(wert, str) or not wert:
        return None
    try:
        if ganztaegig or len(wert) == 10:
            tag = date.fromisoformat(wert[:10])
            if ende:
                tag += timedelta(days=1)
            return datetime.combine(tag, time(0, 0), tzinfo=timezone.utc)
        zeit = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None
    zeit = zeit if zeit.tzinfo else zeit.replace(tzinfo=_zone(zone))
    return zeit.astimezone(timezone.utc)


def nach_nextime(wann: datetime, ganztaegig: bool, zone: str, *, ende: bool = False) -> str:
    """nexmails Zeitpunkt als nextimes Eingabe: Wanduhr in ``zone`` oder Datum.

    ⚠️ **In der Zone des Termins, nicht in UTC.** nextime liest eine Zeit ohne
    Versatz als Wanduhr; in UTC geschickt, rückte „jeden Montag um 9" nach der
    Zeitumstellung um eine Stunde.
    """
    if wann.tzinfo is None:
        wann = wann.replace(tzinfo=timezone.utc)
    if ganztaegig:
        tag = wann.astimezone(timezone.utc).date()
        if ende:
            tag -= timedelta(days=1)
        return tag.isoformat()
    return wann.astimezone(_zone(zone)).strftime("%Y-%m-%dT%H:%M")


# --- Wiederholung ----------------------------------------------------------------- #


def regel_als_rrule(regel: object, serienbeginn: datetime | None) -> str:
    """nextimes Regel als ``RRULE``, damit nexmails Maske und Satz sie lesen.

    ⚠️ **„Der n-te Wochentag" steht bei nextime am Serienbeginn**, nicht in
    der Regel; ohne den Beginn lässt er sich nicht ausschreiben, und die Regel
    bleibt leer (die Oberfläche zeigt dann „wiederholt sich").
    """
    if not isinstance(regel, dict):
        return ""
    freq = _FREQ_RRULE.get(str(regel.get("freq") or ""))
    if not freq:
        return ""
    teile = [f"FREQ={freq}"]
    try:
        intervall = int(regel.get("interval") or 1)
    except (TypeError, ValueError):
        intervall = 1
    if intervall > 1:
        teile.append(f"INTERVAL={intervall}")
    tage = [str(t).upper()[:2] for t in regel.get("weekdays") or [] if str(t).upper()[:2] in _TAGE]
    monatlich = str(regel.get("monthly") or "date")
    if freq == "MONTHLY" and monatlich in ("nth", "last"):
        if serienbeginn is None:
            return ""
        tag = _TAGE[serienbeginn.weekday()]
        n = -1 if monatlich == "last" else (serienbeginn.day - 1) // 7 + 1
        teile.append(f"BYDAY={n}{tag}")
    elif tage and freq == "WEEKLY":
        teile.append("BYDAY=" + ",".join(tage))
    ende = str(regel.get("end") or "never")
    if ende == "count" and regel.get("count"):
        teile.append(f"COUNT={int(regel['count'])}")
    elif ende == "until" and regel.get("until"):
        teile.append("UNTIL=" + str(regel["until"]).replace("-", "")[:8])
    return ";".join(teile)


def rrule_als_regel(rrule: str) -> dict | None:
    """nexmails ``RRULE`` als nextimes Regel. Leer heißt: keine Wiederholung.

    ⚠️ **Was die Maske nicht abbildet, geht nicht hinaus** (``fremd``): Eine
    halb übersetzte Regel wäre eine andere Reihe.
    """
    if not rrule.strip():
        return None
    r = wiederholung.regel_lesen(rrule)
    freq = _FREQ.get(r.freq)
    if r.fremd or not freq:
        raise VerbindungFehler("nextime_regel_nicht_abbildbar")
    regel: dict = {"freq": freq, "interval": r.intervall, "weekdays": [], "monthly": "date", "end": "never"}
    if freq == "weekly":
        regel["weekdays"] = list(r.tage)
    if freq == "monthly" and r.monatsart == "wochentag":
        regel["monthly"] = "last" if r.ordinal == -1 else "nth"
    if r.ende_art == "anzahl" and r.anzahl > 0:
        regel["end"], regel["count"] = "count", r.anzahl
    elif r.ende_art == "datum" and r.bis:
        regel["end"], regel["until"] = "until", r.bis
    return regel


# --- Termine ---------------------------------------------------------------------- #


def nummer(kalender_nr: object, event_id: object, vorkommen: object, start: object = "") -> int:
    """Die feste negative Nummer eines nextime-Vorkommens.

    ⚠️ **Negativ, und kleiner als 2**53**: JavaScript rechnet mit Gleitkomma,
    eine größere Zahl käme verfälscht zurück. 13 Hex-Stellen sind 52 Bit.
    """
    schluessel = f"{kalender_nr}:{event_id}:{vorkommen or ''}:{start if event_id is None else ''}"
    return -(int(hashlib.sha256(schluessel.encode("utf-8")).hexdigest()[:13], 16) + 1)


@dataclass
class Fern:
    """Was nexmail über einen nextime-Termin wissen muss, um ihn zu ändern."""

    id: int | None
    vorkommen: str | None
    etag: str
    link: str
    beschreibbar: bool
    nur_belegt: bool
    hintergrund: bool
    uid: str
    einladung: str
    herkunft: str
    zeitzone: str
    serie: bool


@dataclass
class Sicht:
    termin: Termin
    beginn: datetime
    ende: datetime
    aus_reihe: bool
    fern: Fern
    rest: dict = field(default_factory=dict)


def _leute(detail: dict) -> tuple[str, str]:
    organisator = ""
    o = detail.get("organizer")
    if isinstance(o, dict) and (o.get("email") or o.get("name")):
        organisator = json.dumps(
            {"name": str(o.get("name") or ""), "adresse": str(o.get("email") or "").lower(),
             "antwort": "", "rolle": "CHAIR"},
            ensure_ascii=False,
        )
    leute = []
    for a in detail.get("attendees") or []:
        if not isinstance(a, dict):
            continue
        leute.append({
            "name": str(a.get("name") or ""),
            "adresse": str(a.get("email") or "").lower(),
            "antwort": STAND.get(str(a.get("status") or "open"), "NEEDS-ACTION"),
            "rolle": "",
        })
    return organisator, json.dumps(leute, ensure_ascii=False) if leute else ""


def sicht(e: dict, kalender_nach_nr: dict[int, Kalender], *, detail: bool = False) -> Sicht | None:
    """Ein Vorkommen aus nextime als nexmails ``Sicht``. ``None``, wenn es sich
    nicht lesen lässt (fehlende Zeit) — ein kaputter Eintrag kostet nicht die
    ganze Woche."""
    kal_nr = e.get("calendar_id")
    if not isinstance(kal_nr, int):
        return None
    ganz = bool(e.get("all_day"))
    zone = str(e.get("time_zone") or "")
    beginn = von_nextime(e.get("start"), ganz, zone=zone)
    ende = von_nextime(e.get("end") or e.get("start"), ganz, ende=True, zone=zone)
    if beginn is None or ende is None:
        return None
    kal = kalender_nach_nr.get(kal_nr)
    # ⚠️ Die Suche nennt ``busy_only`` nicht (Befund 10): Dann sagt es der Kalender.
    nur_belegt = bool(e.get("busy_only")) or bool(kal and kal.nur_belegt)
    event_id = e.get("id") if isinstance(e.get("id"), int) and not nur_belegt else None
    vorkommen = e.get("occurrence") if isinstance(e.get("occurrence"), str) else None
    serie = bool(e.get("recurring"))

    rrule = ""
    if detail and serie:
        # ⚠️ ``series_start`` ist bei nextime ein Objekt mit Wanduhr (Befund 3).
        erster = e.get("series_start")
        if isinstance(erster, dict):
            serienbeginn = von_nextime(erster.get("start"), bool(erster.get("all_day")),
                                       zone=str(erster.get("time_zone") or zone))
        else:
            serienbeginn = von_nextime(erster, ganz, zone=zone)
        rrule = regel_als_rrule(e.get("rule"), serienbeginn)
    organisator, teilnehmer = _leute(e) if detail else ("", "")
    einladung = str(e.get("invitation") or "")

    schatten = Termin(
        id=nummer(kal_nr, event_id, vorkommen, e.get("start")),
        kalender_id=f"{VORSILBE}{kal_nr}",
        benutzer_id="",
        uid=str(e.get("uid") or ""),
        titel="" if nur_belegt else str(e.get("title") or ""),
        beschreibung=str(e.get("notes") or "") if detail else "",
        ort="" if nur_belegt else str(e.get("location") or ""),
        beginn=beginn,
        ende=ende,
        ganztaegig=ganz,
        zeitzone=zone or "UTC",
        rrule=rrule,
        exdate="",
        recurrence_id="",
        sequenz=0,
        erinnerung=-1,
        organisator=organisator,
        teilnehmer=teilnehmer,
        fremde_antworten="[]",
        status="CONFIRMED",
        aus_einladung=str(e.get("origin") or "") == "imip",
        eingeladen_am=None,
    )
    beschreibbar = bool(e.get("writable", kal.beschreibbar if kal else False)) and not nur_belegt
    return Sicht(
        termin=schatten,
        beginn=beginn,
        ende=ende,
        aus_reihe=serie,
        fern=Fern(
            id=event_id,
            vorkommen=vorkommen,
            etag=str(e.get("etag") or ""),
            link=nextime.link(e.get("web_url")),
            beschreibbar=beschreibbar,
            nur_belegt=nur_belegt,
            hintergrund=bool(e.get("background", kal.hintergrund if kal else False)),
            uid=str(e.get("uid") or ""),
            einladung=einladung,
            herkunft=str(e.get("origin") or ""),
            zeitzone=zone,
            serie=serie,
        ),
    )


def _kalender_nach_nr(
    z: nextime.Zugang, v: NextimeVerbindung, *, alle: bool = False
) -> dict[int, Kalender]:
    return {k.nummer: k for k in kalender_liste(v, nextime.kalender(z), alle=alle)}


def fenster(
    db: Session, person: Benutzer, von: datetime, bis: datetime, wahl: list[str] | None
) -> list[Sicht]:
    """Alle Vorkommen der gewählten nextime-Kalender im Fenster.

    ⚠️ **Ohne Wahl gelten die mit Haken**, nicht alle: Ein in nexmail
    ausgeblendeter Kalender soll auch dann fehlen, wenn jemand die Liste
    weglässt.
    """
    v, z = gebraucht(db, person)
    kalender = _kalender_nach_nr(z, v)
    if wahl is None:
        nummern = [k.nummer for k in kalender.values() if k.sichtbar]
    else:
        nummern = [kalender_id(w) for w in wahl if w.startswith(VORSILBE)]
        nummern = [n for n in nummern if n in kalender]
    if bis <= von:
        return []
    if (bis - von).days > nextime.MAX_TAGE:
        raise VerbindungFehler("nextime_zeitraum_zu_lang", tage=nextime.MAX_TAGE)
    roh = nextime.termine(z, _iso(von), _iso(bis), nummern)
    return [s for s in (sicht(e, kalender) for e in roh) if s is not None]


def _iso(wann: datetime) -> str:
    if wann.tzinfo is None:
        wann = wann.replace(tzinfo=timezone.utc)
    return wann.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def einzeln(db: Session, person: Benutzer, event_id: int, vorkommen: str | None) -> Sicht:
    v, z = gebraucht(db, person)
    kalender = _kalender_nach_nr(z, v, alle=True)
    s = sicht(nextime.termin(z, event_id, vorkommen), kalender, detail=True)
    if s is None:
        raise VerbindungFehler("nextime_antwort_unlesbar")
    return s


def suchen(db: Session, person: Benutzer, wort: str, wahl: list[str] | None) -> list[Sicht]:
    v, z = gebraucht(db, person)
    kalender = _kalender_nach_nr(z, v)
    erlaubt = (
        {k.nummer for k in kalender.values() if k.sichtbar}
        if wahl is None
        else {kalender_id(w) for w in wahl if w.startswith(VORSILBE)} & set(kalender)
    )
    raus = []
    for e in nextime.suchen(z, wort):
        if e.get("calendar_id") not in erlaubt:
            continue
        s = sicht(e, kalender)
        if s is not None:
            raus.append(s)
    return raus


@dataclass
class Eingabe:
    """Was nexmails Maske schickt, schon in nexmails Form. ``None`` heißt
    unverändert (nur beim Ändern)."""

    titel: str | None = None
    beginn: datetime | None = None
    ende: datetime | None = None
    ganztaegig: bool | None = None
    ort: str | None = None
    beschreibung: str | None = None
    rrule: str | None = None
    zeitzone: str = ""


def _zeiten(rumpf: dict, e: Eingabe, zone: str) -> None:
    """⚠️ **Zeiten gehen zusammen hinaus**: nextime nimmt ``all_day``,
    ``start``, ``end`` und ``time_zone`` nur gemeinsam."""
    if e.beginn is None:
        raise VerbindungFehler("nextime_zeiten_unvollstaendig")
    ganz = bool(e.ganztaegig)
    ende = e.ende
    if ende is None:
        ende = e.beginn + (timedelta(days=1) if ganz else timedelta(hours=1))
    if ende < e.beginn or (ende == e.beginn and ganz):
        raise VerbindungFehler("termin_ende_vor_beginn")
    rumpf["all_day"] = ganz
    rumpf["start"] = nach_nextime(e.beginn, ganz, zone)
    rumpf["end"] = nach_nextime(ende, ganz, zone, ende=True)
    if not ganz:
        rumpf["time_zone"] = zone


def anlegen(
    db: Session, person: Benutzer, roh_kalender: str, e: Eingabe, client_ref: str = ""
) -> Sicht:
    v, z = gebraucht(db, person)
    titel = (e.titel or "").strip()
    if not titel:
        raise VerbindungFehler("termin_ohne_titel")
    nummer_kal = kalender_id(roh_kalender)
    if nummer_kal in _ohne(v):
        # Nicht gewählt: nexmail bietet ihn nirgends an, also nimmt es ihn auch nicht.
        raise VerbindungFehler("kalender_unbekannt")
    rumpf: dict = {"calendar_id": nummer_kal, "title": titel,
                   "notes": e.beschreibung or "", "location": e.ort or ""}
    _zeiten(rumpf, e, e.zeitzone or v.zeitzone or "UTC")
    regel = rrule_als_regel(e.rrule or "")
    if regel:
        rumpf["rule"] = regel
    if client_ref:
        rumpf["client_ref"] = client_ref[:64]
    neu = nextime.anlegen(z, rumpf)
    s = sicht(neu, _kalender_nach_nr(z, v, alle=True), detail=True)
    if s is None:
        raise VerbindungFehler("nextime_antwort_unlesbar")
    return s


def aendern(
    db: Session,
    person: Benutzer,
    event_id: int,
    e: Eingabe,
    *,
    umfang: str,
    vorkommen: str | None,
    etag: str,
) -> Sicht:
    """Nur was sich geändert hat — die Oberfläche schickt nichts anderes.

    ⚠️ **Mit der gelesenen Fassung (``etag``).** nextime lehnt eine ältere
    nicht ab, es merkt den Konflikt und zeigt die überschriebene Fassung dem,
    der sie geschrieben hatte (TIME-5 EC-2, MAIL-1 EC-5).
    """
    v, z = gebraucht(db, person)
    if umfang not in UMFANG:
        raise VerbindungFehler("umfang_unbekannt")
    rumpf: dict = {"scope": UMFANG[umfang]}
    if umfang != "alle" and not vorkommen:
        raise VerbindungFehler("vorkommen_fehlt")
    if vorkommen:
        # ⚠️ **Auch bei „alle"** (Prüfbericht MAIL-1, Befund 1): Ohne Vorkommen
        # rechnet nextime eine neue Zeit vom ersten Termin der Reihe aus. Wer
        # den Termin am 23.11. um eine Stunde zieht, ließe die Reihe sonst am
        # 23.11. beginnen; die früheren Termine wären weg.
        rumpf["occurrence"] = vorkommen
    if etag:
        rumpf["etag"] = etag[:64]
    if e.titel is not None:
        if not e.titel.strip():
            raise VerbindungFehler("termin_ohne_titel")
        rumpf["title"] = e.titel.strip()
    if e.ort is not None:
        rumpf["location"] = e.ort
    if e.beschreibung is not None:
        rumpf["notes"] = e.beschreibung
    if e.beginn is not None or e.ende is not None or e.ganztaegig is not None:
        _zeiten(rumpf, e, e.zeitzone or v.zeitzone or "UTC")
    if e.rrule is not None and umfang != "dieser":
        # ⚠️ ``null`` heißt bei nextime „keine Wiederholung mehr", nicht
        # „unverändert": Darum geht die Regel nur hinaus, wenn sie mitkam.
        rumpf["rule"] = rrule_als_regel(e.rrule)
    neu = nextime.aendern(z, event_id, rumpf)
    s = sicht(neu, _kalender_nach_nr(z, v, alle=True), detail=True)
    if s is None:
        raise VerbindungFehler("nextime_antwort_unlesbar")
    return s


def entfernen(
    db: Session, person: Benutzer, event_id: int, *, umfang: str, vorkommen: str | None
) -> None:
    """⚠️ **In den Papierkorb von nextime**, nicht endgültig."""
    _v, z = gebraucht(db, person)
    if umfang not in UMFANG:
        raise VerbindungFehler("umfang_unbekannt")
    if umfang != "alle" and not vorkommen:
        raise VerbindungFehler("vorkommen_fehlt")
    nextime.loeschen(z, event_id, UMFANG[umfang], vorkommen if umfang != "alle" else None)


# --- Vorwahl je Postfach ------------------------------------------------------- #


def vorwahl_lesen(person: Benutzer) -> dict[str, str]:
    try:
        daten = json.loads(person.kalender_vorwahl or "{}")
    except ValueError:
        return {}
    return {str(k): str(w) for k, w in daten.items()} if isinstance(daten, dict) else {}


def vorwahl_merken(db: Session, person: Benutzer, konto_id: str, kalender: str) -> None:
    """Den gewählten Kalender für dieses Postfach merken (MAIL-1 AC-5)."""
    if not konto_id or not kalender:
        return
    alle = vorwahl_lesen(person)
    if alle.get(konto_id) == kalender:
        return
    alle[konto_id] = kalender[:64]
    person.kalender_vorwahl = json.dumps(alle)
    db.commit()
