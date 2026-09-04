"""Kalender und Termine — anlegen, ändern, anzeigen.

⚠️ **Eine Reihe steht einmal in der Datenbank.** Was der Kalender zeigt, wird
für das sichtbare Fenster ausgerechnet (``services/wiederholung.py``). Wer die
Vorkommen ausschreibt, muss raten, wie weit — und liegt beim ersten Blick ins
Jahr 2031 daneben.

⚠️ **„Nur dieser · Dieser und folgende · Alle" ist keine Erfindung.** Jedes
Kalenderprogramm fragt das, und jedes löst es gleich, weil das Format es so
vorgibt:

* **Nur dieser** — beim Löschen ein ``EXDATE`` an der Reihe, beim Ändern eine
  eigene Zeile mit ``RECURRENCE-ID``. Die Reihe bleibt, wie sie ist.
* **Dieser und folgende** — die alte Reihe bekommt ein ``UNTIL`` bis kurz
  davor, ab hier beginnt eine **neue** Reihe. ⚠️ Sie braucht eine eigene
  ``UID``: Zwei Reihen unter derselben Kennung sind für jeden anderen Client
  ein Widerspruch.
* **Alle** — die eine Zeile ändert sich.

⚠️ **Ganztägig heißt: Datum, nicht Mitternacht.** ``beginn`` liegt auf 00:00
UTC des ersten Tages, ``ende`` auf 00:00 UTC des Tages **danach** — das
``DTEND`` von iCalendar ist ausschließend. Wer das Ende auf denselben Tag legt,
zeichnet einen eintägigen Termin als null Tage lang.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Benutzer, Kalender, Termin, utcnow
from . import wiederholung
from . import zeit as zeitdienst
from ..meldung import Meldung

logger = logging.getLogger("nexmail.termine")


class TerminFehler(Meldung, RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz — die Oberflaeche uebersetzt."""


#: Wie lang ein neuer Termin ist, wenn niemand etwas anderes sagt.
VORGABE_DAUER = timedelta(hours=1)

#: Wie weit ein Fenster hoechstens reichen darf. ⚠️ Ohne Deckel fragt ein
#: verirrter Aufruf zehn Jahre auf einmal ab und rechnet jede Reihe darin aus.
MAX_FENSTER = timedelta(days=400)

UMFAENGE = ("dieser", "folgende", "alle")


# --- Kalender ------------------------------------------------------------- #


def liste(db: Session, benutzer: Benutzer) -> list[Kalender]:
    return list(
        db.scalars(
            select(Kalender)
            .where(Kalender.benutzer_id == benutzer.id)
            .order_by(Kalender.reihenfolge, Kalender.angelegt)
        )
    )


def naechste_farbe(vorhanden: list[Kalender]) -> int:
    """Die erste freie der sechs geprueften Farben, sonst reihum.

    ⚠️ **Zugeteilt, nicht gewaehlt** — dieselbe Regel wie beim Postfach-Punkt.
    Zwei selbstgemischte, kaum unterscheidbare Toene fallen erst auf, wenn man
    den falschen Termin angesehen hat.
    """
    vergeben = {k.farbe for k in vorhanden}
    for f in range(1, 7):
        if f not in vergeben:
            return f
    return len(vorhanden) % 6 + 1


def kalender_anlegen(db: Session, benutzer: Benutzer, name: str, farbe: int = 0) -> Kalender:
    if not name.strip():
        raise TerminFehler("kalender_ohne_namen")
    vorhanden = liste(db, benutzer)
    kalender = Kalender(
        benutzer_id=benutzer.id,
        name=name.strip()[:120],
        farbe=farbe if farbe in range(1, 7) else naechste_farbe(vorhanden),
        reihenfolge=len(vorhanden),
    )
    db.add(kalender)
    db.commit()
    logger.info("A calendar was created.")
    return kalender


def _meiner(db: Session, benutzer: Benutzer, kalender_id: str) -> Kalender:
    kalender = db.get(Kalender, kalender_id)
    # Erst holen, dann Besitzer pruefen — und bei fremdem Besitz dasselbe
    # melden wie bei „gibt es nicht".
    if kalender is None or kalender.benutzer_id != benutzer.id:
        raise TerminFehler("kalender_unbekannt")
    return kalender


def kalender_aendern(
    db: Session,
    benutzer: Benutzer,
    kalender_id: str,
    *,
    name: str | None = None,
    farbe: int | None = None,
    sichtbar: bool | None = None,
) -> Kalender:
    kalender = _meiner(db, benutzer, kalender_id)
    if name is not None:
        if not name.strip():
            raise TerminFehler("kalender_ohne_namen")
        kalender.name = name.strip()[:120]
    if farbe is not None and farbe in range(1, 7):
        kalender.farbe = farbe
    if sichtbar is not None:
        kalender.sichtbar = sichtbar
    db.commit()
    return kalender


def kalender_entfernen(db: Session, benutzer: Benutzer, kalender_id: str) -> int:
    """Mit allem, was darin liegt. Die Zahl sagt, wie viel das war.

    ⚠️ **Bei einer Gegenstelle wird hier nichts geloescht, was dort liegt.**
    Der Kalender verschwindet aus nexmail; auf dem Server bleibt er. Das ist
    die vorsichtige Richtung — und die Oberflaeche sagt es, bevor sie fragt.
    """
    kalender = _meiner(db, benutzer, kalender_id)
    anzahl = len(kalender.termine)
    db.delete(kalender)
    db.commit()
    logger.info("A calendar with %s event(s) was removed.", anzahl)
    return anzahl


# --- Anzeigen ------------------------------------------------------------- #


@dataclass
class Sicht:
    """Ein einzelnes Vorkommen, wie es im Raster steht."""

    termin: Termin
    beginn: datetime
    ende: datetime
    #: Wahr, wenn es aus einer Wiederholung stammt — die Oberflaeche zeigt das
    #: Symbol, und beim Aendern wird gefragt.
    aus_reihe: bool


def fenster(
    db: Session,
    benutzer: Benutzer,
    von: datetime,
    bis: datetime,
    kalender_ids: list[str] | None = None,
) -> list[Sicht]:
    """Alle Vorkommen, die den Zeitraum beruehren — nach Beginn sortiert.

    ⚠️ **Eingeschraenkt wird hier, nicht im Browser.** Dieselbe Regel wie bei
    der Nachrichtenliste: Wer alles holt und dann aussiebt, zeigt bei einem
    vollen Kalender drei Termine und behauptet damit, mehr gebe es nicht.
    """
    if bis <= von:
        raise TerminFehler("fenster_verdreht")
    if bis - von > MAX_FENSTER:
        raise TerminFehler("fenster_zu_gross")

    abfrage = (
        select(Termin)
        .join(Kalender)
        .where(Kalender.benutzer_id == benutzer.id)
        # ⚠️ **Eine Reihe kann VOR dem Fenster beginnen und hineinreichen.**
        # Auf ``beginn >= von`` einzuschraenken liesse jeden wiederholten
        # Termin verschwinden, sobald man eine Woche weiterblaettert. Reihen
        # bleiben deshalb ohne unteres Ende; ausgerechnet werden sie danach.
        #
        # ⚠️ **Ein EINZELNER Termin braucht das nicht.** Bis zum 03.09.2026
        # fehlte hier jede untere Grenze, und damit las eine Monatsansicht die
        # gesamte Vergangenheit mit — samt der ``roh``-Spalte, in der das ganze
        # ``VEVENT`` steht. Gemessen bei 20.000 Terminen ueber zehn Jahre:
        # 19.438 Zeilen statt der 660, die das Fenster beruehren. Je weiter man
        # blaettert, desto mehr Vergangenheit kam mit.
        #
        # ⚠️ **``ende > von``, nicht ``beginn >= von``.** Ein Termin, der
        # vor dem Fenster beginnt und hineinragt, gehoert dazu. Und ``DTEND``
        # ist ausschliessend: Ein ganztaegiger Termin am Vortag endet auf
        # 00:00 des Fenstertages und faellt damit richtig heraus.
        .where(
            (Termin.rrule != "")
            | ((Termin.beginn < bis) & (Termin.ende > von))
        )
    )
    if kalender_ids is not None:
        abfrage = abfrage.where(Termin.kalender_id.in_(kalender_ids))

    raus: list[Sicht] = []
    ueberschrieben: set[tuple[str, str]] = set()
    zeilen = list(db.scalars(abfrage))

    # Zuerst die Ausnahmen einsammeln: „dieser eine Montag faellt auf 10 Uhr".
    for zeile in zeilen:
        if zeile.recurrence_id:
            ueberschrieben.add((zeile.uid, zeile.recurrence_id))

    for zeile in zeilen:
        if zeile.status == "CANCELLED":
            continue
        if zeile.recurrence_id:
            # Eine Ausnahme steht fuer sich; ihre Reihe hat sie ausgeklinkt.
            if zeile.beginn < bis and zeile.ende > von:
                raus.append(Sicht(zeile, zeile.beginn, zeile.ende, aus_reihe=True))
            continue

        for v in wiederholung.ausrechnen(
            zeile.beginn, zeile.ende, zeile.rrule, zeile.exdate, zeile.zeitzone, von, bis
        ):
            # ⚠️ Ein Vorkommen, fuer das es eine eigene Zeile gibt, darf nicht
            # doppelt erscheinen.
            if (zeile.uid, v.beginn.isoformat()) in ueberschrieben:
                continue
            raus.append(Sicht(zeile, v.beginn, v.ende, aus_reihe=bool(zeile.rrule)))

    raus.sort(key=lambda s: (s.beginn, s.termin.id))
    return raus


# --- Suchen --------------------------------------------------------------- #


#: ⚠️ **Gedeckelt, wie jede Liste in nexmail.** Ohne Deckel liefert „a" bei drei
#: Jahren Bestand alles, und die Oberfläche zeichnet minutenlang.
SUCHE_HOECHSTENS = 50

#: Wie weit nach vorn nach dem nächsten Vorkommen einer Reihe gesucht wird.
#: ⚠️ Ohne Grenze rechnete eine tägliche Reihe ohne Ende bis ans Ende der Zeit.
SUCHE_VORAUS = timedelta(days=730)


@dataclass
class Treffer:
    """Ein gefundener Termin samt dem Vorkommen, das gezeigt wird."""

    termin: Termin
    beginn: datetime
    ende: datetime
    aus_reihe: bool


def _gezeigtes_vorkommen(zeile: Termin, jetzt: datetime) -> tuple[datetime, datetime]:
    """Welches Vorkommen einer Reihe im Treffer steht.

    ⚠️ **Das nächste, nicht das erste.** „Team-Runde" gibt es zweihundertmal;
    wer sie sucht, meint fast immer die nächste. Das erste Vorkommen liegt bei
    einer alten Reihe Jahre zurück und beantwortet keine Frage.

    ⚠️ **Und bei einer abgelaufenen Reihe das letzte.** Sonst stünde dort das
    Startdatum von vor drei Jahren, und der Termin sähe aus, als fände er noch
    statt.
    """
    if not zeile.rrule:
        return zeile.beginn, zeile.ende

    voraus = list(
        wiederholung.ausrechnen(
            zeile.beginn, zeile.ende, zeile.rrule, zeile.exdate, zeile.zeitzone,
            jetzt, jetzt + SUCHE_VORAUS,
        )
    )
    if voraus:
        return voraus[0].beginn, voraus[0].ende

    zurueck = list(
        wiederholung.ausrechnen(
            zeile.beginn, zeile.ende, zeile.rrule, zeile.exdate, zeile.zeitzone,
            zeile.beginn, jetzt,
        )
    )
    if zurueck:
        return zurueck[-1].beginn, zurueck[-1].ende
    return zeile.beginn, zeile.ende


def suchen(
    db: Session,
    benutzer: Benutzer,
    wort: str,
    kalender_ids: list[str] | None = None,
    jetzt: datetime | None = None,
) -> tuple[list[Treffer], bool]:
    """Termine nach Titel, Ort und Beschreibung suchen.

    Gibt die Treffer und zurück, ob abgeschnitten wurde.

    ⚠️ **Eine Reihe steht EINMAL im Ergebnis.** Sie steht auch einmal in der
    Datenbank; sie aufzurechnen hiesse, eine wöchentliche Besprechung als
    zweihundert Treffer zu zeigen und alles andere darunter zu begraben.

    ⚠️ **Gesucht wird im Server, nicht im Browser.** Dieselbe Regel wie bei der
    Nachrichtenliste: Wer alles holt und dann aussiebt, findet nur, was
    zufällig schon geladen war.

    ⚠️ **Kein Volltextindex.** Anders als bei der Post: Termine sind kurz und
    es sind Größenordnungen weniger. Ein ``LIKE`` über die Spalten liest die
    Tabelle, und der Deckel begrenzt, was daraus wird. Wer je hunderttausend
    Termine hat, hat den Punkt erreicht, an dem sich der Index lohnt.
    """
    gesucht = wort.strip()
    if not gesucht:
        return [], False
    jetzt = jetzt or datetime.now(timezone.utc)

    muster = f"%{gesucht.lower()}%"
    abfrage = (
        select(Termin)
        .join(Kalender)
        .where(Kalender.benutzer_id == benutzer.id)
        .where(Termin.status != "CANCELLED")
        .where(
            or_(
                func.lower(Termin.titel).like(muster),
                func.lower(Termin.ort).like(muster),
                func.lower(Termin.beschreibung).like(muster),
            )
        )
    )
    if kalender_ids is not None:
        abfrage = abfrage.where(Termin.kalender_id.in_(kalender_ids))

    treffer: list[Treffer] = []
    for zeile in db.scalars(abfrage):
        # ⚠️ Eine überschriebene Einzelausnahme steht für sich; ihre Reihe hat
        # sie ausgeklinkt, und beide zu zeigen wäre derselbe Termin zweimal.
        beginn, ende = _gezeigtes_vorkommen(zeile, jetzt)
        treffer.append(Treffer(zeile, beginn, ende, aus_reihe=bool(zeile.rrule)))

    # ⚠️ **Das Nächstliegende zuerst, nicht das Älteste.** Wer sucht, meint in
    # aller Regel etwas, das noch kommt; eine Sortierung nach Datum begönne mit
    # der ältesten Karteileiche.
    treffer.sort(key=lambda tr: (abs((tr.beginn - jetzt).total_seconds()), tr.termin.id))
    abgeschnitten = len(treffer) > SUCHE_HOECHSTENS
    return treffer[:SUCHE_HOECHSTENS], abgeschnitten


# --- Termine anlegen und ändern ------------------------------------------- #


def _hinaus(db: Session, termin: Termin, alarm_ersetzen: bool = False) -> None:
    """Einen geänderten Termin sofort zum Server bringen.

    ⚠️ **Erst der Server, dann die eigene Datenbank** — dieselbe Regel wie bei
    jeder Mail-Handlung. Wer lokal ändert und später hochschiebt, hat beim
    Konflikt zwei Fassungen und keine Regel, welche gilt.

    ⚠️ **Ein Konflikt bricht ab, statt zu überschreiben.** Jemand hat denselben
    Termin am Telefon geändert; ihn zu überbügeln hieße, eine fremde Änderung
    spurlos zu löschen.
    """
    from . import caldav
    from . import kalenderabgleich

    if termin.kalender is None or termin.kalender.art != "caldav":
        return
    try:
        kalenderabgleich.hochschieben(db, termin, alarm_ersetzen=alarm_ersetzen)
    except caldav.Konflikt as f:
        db.rollback()
        raise TerminFehler("termin_konflikt") from f
    except caldav.CaldavFehler as f:
        db.rollback()
        raise TerminFehler(str(f)) from f


def _weg(db: Session, termin: Termin) -> None:
    """Einen Termin beim Server löschen — ebenfalls zuerst."""
    from . import caldav
    from . import kalenderabgleich

    if termin.kalender is None or termin.kalender.art != "caldav" or not termin.href:
        return
    try:
        kalenderabgleich.wegnehmen(db, termin.kalender, termin.href, termin.etag)
    except caldav.Konflikt as f:
        raise TerminFehler("termin_konflikt") from f
    except caldav.CaldavFehler as f:
        raise TerminFehler(str(f)) from f


def _meiner_termin(db: Session, benutzer: Benutzer, termin_id: int) -> Termin:
    termin = db.get(Termin, termin_id)
    if termin is None or termin.benutzer_id != benutzer.id:
        raise TerminFehler("termin_unbekannt")
    return termin


def _schreibbar(kalender: Kalender) -> None:
    if kalender.nur_lesen:
        raise TerminFehler("kalender_nur_lesen")


def anlegen(
    db: Session,
    benutzer: Benutzer,
    kalender_id: str,
    *,
    titel: str,
    beginn: datetime,
    ende: datetime | None = None,
    ganztaegig: bool = False,
    ort: str = "",
    beschreibung: str = "",
    rrule: str = "",
    zeitzone: str = "",
    aus_einladung: bool = False,
    erinnerung: int = -1,
    #: JSON, wie es in ``Termin`` liegt — nur zum Anzeigen. ⚠️ Ohne das
    #: verliert ein aus einer Einladung uebernommener Termin genau die
    #: Angaben, die ihn zur Einladung machen.
    organisator: str = "",
    teilnehmer: str = "",
) -> Termin:
    kalender = _meiner(db, benutzer, kalender_id)
    _schreibbar(kalender)
    if not titel.strip():
        raise TerminFehler("termin_ohne_titel")

    zeitzone_wirklich = zeitzone or zeitdienst.zonenname_der_anwendung(db)
    ende = ende or (beginn + timedelta(days=1) if ganztaegig else beginn + VORGABE_DAUER)
    if ganztaegig:
        beginn, ende = ganztags_gerade_ruecken(beginn, ende)
    if ende <= beginn:
        raise TerminFehler("termin_ende_vor_beginn")

    termin = Termin(
        kalender_id=kalender.id,
        benutzer_id=benutzer.id,
        # ⚠️ Die UID gehoert dem Termin, nicht der Zeile. Jeder andere Client
        # erkennt ihn daran wieder — auch nach einem Umzug in einen anderen
        # Kalender.
        uid=f"{uuid.uuid4()}@nexmail",
        titel=titel.strip(),
        ort=ort.strip(),
        beschreibung=beschreibung,
        beginn=beginn,
        ende=ende,
        ganztaegig=ganztaegig,
        zeitzone=zeitzone_wirklich,
        rrule=wiederholung.regel_normieren(rrule.strip(), beginn, zeitzone_wirklich),
        erinnerung=erinnerung,
        organisator=organisator,
        teilnehmer=teilnehmer,
        aus_einladung=aus_einladung,
        schmutzig=bool(kalender.art),
    )
    db.add(termin)
    db.flush()
    _hinaus(db, termin)
    db.commit()
    logger.info("An event was created.")
    return termin


def _kurz_davor(wann: datetime) -> str:
    """``UNTIL`` fuer „dieser und folgende": eine Sekunde vor dem Vorkommen."""
    return (wann - timedelta(seconds=1)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _reihe_kappen(termin: Termin, ab: datetime) -> None:
    """Die Reihe endet vor ``ab``. Ein vorhandenes ``UNTIL``/``COUNT`` faellt.

    ⚠️ ``COUNT`` und ``UNTIL`` schliessen sich nach RFC 5545 aus. Wer nur
    ``UNTIL`` anhaengt und ein ``COUNT`` stehen laesst, baut eine Regel, die
    manche Clients gar nicht lesen.
    """
    teile = [
        p
        for p in termin.rrule.split(";")
        if p and not p.upper().startswith(("UNTIL=", "COUNT="))
    ]
    teile.append(f"UNTIL={_kurz_davor(ab)}")
    termin.rrule = ";".join(teile)


def aendern(
    db: Session,
    benutzer: Benutzer,
    termin_id: int,
    *,
    vorkommen: datetime | None = None,
    umfang: str = "alle",
    **felder,
) -> Termin:
    """Einen Termin ändern. Bei einer Reihe entscheidet ``umfang``.

    ``vorkommen`` ist der Beginn des angeklickten Vorkommens — ohne ihn lässt
    sich „nur dieser" nicht sagen.
    """
    termin = _meiner_termin(db, benutzer, termin_id)
    kalender = _meiner(db, benutzer, termin.kalender_id)
    _schreibbar(kalender)
    if umfang not in UMFAENGE:
        raise TerminFehler("umfang_unbekannt")

    # ⚠️ Nur wenn die Erinnerung wirklich mitgeschickt wurde, wird der Alarm
    # im Original ersetzt — siehe ``_hinaus``.
    alarm_neu = felder.get("erinnerung") is not None

    ist_reihe = bool(termin.rrule) and not termin.recurrence_id
    if not ist_reihe or umfang == "alle":
        _felder_setzen(termin, felder)
        termin.geaendert = utcnow()
        termin.schmutzig = bool(kalender.art)
        _hinaus(db, termin, alarm_ersetzen=alarm_neu)
        db.commit()
        return termin

    if vorkommen is None:
        raise TerminFehler("vorkommen_fehlt")

    if umfang == "dieser":
        # Eine eigene Zeile fuer dieses eine Vorkommen. Die Reihe bleibt.
        neu = Termin(
            kalender_id=termin.kalender_id,
            benutzer_id=benutzer.id,
            uid=termin.uid,
            recurrence_id=vorkommen.astimezone(timezone.utc).isoformat(),
            titel=termin.titel,
            ort=termin.ort,
            beschreibung=termin.beschreibung,
            beginn=vorkommen,
            ende=vorkommen + (termin.ende - termin.beginn),
            ganztaegig=termin.ganztaegig,
            zeitzone=termin.zeitzone,
            schmutzig=bool(kalender.art),
        )
        _felder_setzen(neu, felder)
        db.add(neu)
        db.flush()
        # ⚠️ Die Ausnahme liegt beim Server in DERSELBEN Datei wie ihre Reihe —
        # geschrieben wird deshalb die Reihe, nicht die Ausnahme allein.
        neu.href = termin.href
        neu.etag = termin.etag
        neu.roh = termin.roh
        _hinaus(db, neu)
        termin.etag = neu.etag
        db.commit()
        logger.info("A single occurrence was overridden.")
        return neu

    # „Dieser und folgende": alte Reihe kappen, neue Reihe ab hier.
    neu = Termin(
        kalender_id=termin.kalender_id,
        benutzer_id=benutzer.id,
        # ⚠️ Eigene UID. Zwei Reihen unter derselben Kennung sind fuer jeden
        # anderen Client ein Widerspruch.
        uid=f"{uuid.uuid4()}@nexmail",
        titel=termin.titel,
        ort=termin.ort,
        beschreibung=termin.beschreibung,
        beginn=vorkommen,
        ende=vorkommen + (termin.ende - termin.beginn),
        ganztaegig=termin.ganztaegig,
        zeitzone=termin.zeitzone,
        rrule=termin.rrule,
        schmutzig=bool(kalender.art),
    )
    _felder_setzen(neu, felder)
    _reihe_kappen(termin, vorkommen)
    termin.schmutzig = bool(kalender.art)
    termin.geaendert = utcnow()
    db.add(neu)
    db.flush()
    _hinaus(db, termin)
    _hinaus(db, neu)
    db.commit()
    logger.info("A series was split.")
    return neu


def ganztags_gerade_ruecken(
    beginn: datetime, ende: datetime | None
) -> tuple[datetime, datetime]:
    """Ein ganztaegiger Termin liegt auf **UTC-Mitternacht**, Ende ausschliessend.

    ⚠️ **Das erzwingt der Server, nicht die Oberflaeche.** Ein Kalendertag ist
    kein Zeitpunkt: Wer ihn durch eine Ortszeit schickt, legt ihn in Berlin auf
    ``22:00Z des Vortags``, und danach steht er ueber zwei Tage — oder, westlich
    von Greenwich, einen Tag zu frueh. Am 03.09.2026 aus dem Betrieb gemeldet
    („in nexmail steht er von 14–15"), und in der Datenbank lag ein
    ganztaegiger Termin mit **einer Stunde** Dauer.

    Die Regel gehoert hierher und nicht in die Oberflaeche: Es gibt mehr als
    einen Weg herein (Einladung uebernehmen, CalDAV, spaeter fremde Clients),
    und jeder von ihnen kann sie sonst verletzen.
    """
    tag = beginn.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    schluss = (ende or beginn).astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # ⚠️ Mindestens ein ganzer Tag. „Null Tage lang" zeichnet man nicht — und
    # genau das entstand aus einem Ende, das eine Stunde nach dem Beginn lag.
    if schluss <= tag:
        schluss = tag + timedelta(days=1)
    return tag, schluss


def _felder_setzen(termin: Termin, felder: dict) -> None:
    for name in ("titel", "ort", "beschreibung", "rrule"):
        if felder.get(name) is not None:
            setzen = str(felder[name]).strip() if name != "beschreibung" else felder[name]
            if name == "rrule":
                # ⚠️ Die beiden Regeln, an denen man sich schneidet, entscheidet
                # der Server — nicht die Maske. Siehe ``regel_normieren``.
                setzen = wiederholung.regel_normieren(
                    setzen, felder.get("beginn") or termin.beginn, termin.zeitzone
                )
            setattr(termin, name, setzen)
    if felder.get("ganztaegig") is not None:
        termin.ganztaegig = bool(felder["ganztaegig"])
    if felder.get("erinnerung") is not None:
        termin.erinnerung = int(felder["erinnerung"])
    if felder.get("beginn") is not None:
        # ⚠️ Die Dauer bleibt, wenn nur der Beginn verschoben wird — sonst
        # rutscht das Ende beim Verschieben auf den alten Zeitpunkt.
        dauer = termin.ende - termin.beginn
        termin.beginn = felder["beginn"]
        termin.ende = felder.get("ende") or termin.beginn + dauer
    elif felder.get("ende") is not None:
        termin.ende = felder["ende"]
    if termin.ganztaegig:
        termin.beginn, termin.ende = ganztags_gerade_ruecken(termin.beginn, termin.ende)
    if termin.ende <= termin.beginn:
        raise TerminFehler("termin_ende_vor_beginn")
    if not termin.titel.strip():
        raise TerminFehler("termin_ohne_titel")


def entfernen(
    db: Session,
    benutzer: Benutzer,
    termin_id: int,
    *,
    vorkommen: datetime | None = None,
    umfang: str = "alle",
) -> None:
    termin = _meiner_termin(db, benutzer, termin_id)
    kalender = _meiner(db, benutzer, termin.kalender_id)
    _schreibbar(kalender)
    if umfang not in UMFAENGE:
        raise TerminFehler("umfang_unbekannt")

    ist_reihe = bool(termin.rrule) and not termin.recurrence_id
    if not ist_reihe or umfang == "alle":
        # ⚠️ Bei „alle" fallen auch die Ausnahmen der Reihe — sonst blieben
        # einzelne Termine ohne ihre Reihe stehen, und niemand wuesste, wozu
        # sie gehoerten.
        _weg(db, termin)
        for andere in list(kalender.termine):
            if andere.uid == termin.uid and andere.id != termin.id:
                db.delete(andere)
        db.delete(termin)
        db.commit()
        logger.info("An event was removed.")
        return

    if vorkommen is None:
        raise TerminFehler("vorkommen_fehlt")

    if umfang == "dieser":
        vorhandene = [t for t in termin.exdate.split(",") if t]
        vorhandene.append(vorkommen.astimezone(timezone.utc).isoformat())
        termin.exdate = ",".join(vorhandene)
    else:
        _reihe_kappen(termin, vorkommen)
    termin.schmutzig = bool(kalender.art)
    termin.geaendert = utcnow()
    _hinaus(db, termin)
    db.commit()
    logger.info("Part of a series was removed (%s).", umfang)
