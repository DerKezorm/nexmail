"""Kalender und Termine.

⚠️ **Der heikle Teil ist „nur dieser · dieser und folgende · alle".** Jedes
Kalenderprogramm fragt das, und wer es falsch umsetzt, löscht dem Besitzer eine
ganze Reihe, obwohl er einen Termin absagen wollte — oder lässt einen
abgesagten stehen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import Benutzer, Kalender, Termin
from app.services import termine
from conftest import einrichten

BERLIN = ZoneInfo("Europe/Berlin")


def _berlin(tag: int, stunde: int = 9) -> datetime:
    return datetime(2026, 9, tag, stunde, tzinfo=BERLIN)


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    kalender = termine.kalender_anlegen(db, person, "Privat")
    return person, kalender


def _fenster(db, person, von_tag: int, bis_tag: int, **kw):
    return termine.fenster(db, person, _berlin(von_tag, 0), _berlin(bis_tag, 0), **kw)


# --- Kalender ------------------------------------------------------------- #


def test_ein_kalender_bekommt_die_naechste_freie_farbe(db, welt):
    person, erster = welt
    zweiter = termine.kalender_anlegen(db, person, "Arbeit")
    dritter = termine.kalender_anlegen(db, person, "Verein")
    assert [erster.farbe, zweiter.farbe, dritter.farbe] == [1, 2, 3]


def test_ein_kalender_ohne_namen_geht_nicht(db, welt):
    person, _ = welt
    with pytest.raises(termine.TerminFehler) as f:
        termine.kalender_anlegen(db, person, "   ")
    assert str(f.value) == "kalender_ohne_namen"


def test_ein_fremder_kalender_ist_unbekannt(db, welt):
    person, _ = welt
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.flush()
    seiner = termine.kalender_anlegen(db, anderer, "Privat")
    db.commit()

    with pytest.raises(termine.TerminFehler) as f:
        termine.kalender_aendern(db, person, seiner.id, name="Meiner")
    # ⚠️ Dieselbe Meldung wie „gibt es nicht" — sonst verrät der Fehler, dass
    # es ihn gibt.
    assert str(f.value) == "kalender_unbekannt"


def test_einen_kalender_entfernen_nimmt_die_termine_mit(db, welt):
    person, kalender = welt
    termine.anlegen(db, person, kalender.id, titel="Eins", beginn=_berlin(2))
    termine.anlegen(db, person, kalender.id, titel="Zwei", beginn=_berlin(3))

    assert termine.kalender_entfernen(db, person, kalender.id) == 2
    assert db.query(Termin).count() == 0


def test_ein_abo_laesst_sich_nicht_beschreiben(db, welt):
    """⚠️ Ein veröffentlichter ICS-Link bietet keinen Weg zurück."""
    person, _ = welt
    abo = Kalender(
        benutzer_id=person.id, name="Feiertage", farbe=5, art="ics",
        url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()

    with pytest.raises(termine.TerminFehler) as f:
        termine.anlegen(db, person, abo.id, titel="Geht nicht", beginn=_berlin(2))
    assert str(f.value) == "kalender_nur_lesen"


# --- Anlegen -------------------------------------------------------------- #


def test_ein_termin_ohne_ende_dauert_eine_stunde(db, welt):
    person, kalender = welt
    t = termine.anlegen(db, person, kalender.id, titel="Zahnarzt", beginn=_berlin(2, 8))
    assert t.ende - t.beginn == timedelta(hours=1)


def test_ein_ganztaegiger_termin_dauert_einen_tag(db, welt):
    """⚠️ ``DTEND`` ist ausschließend — sonst ist er null Tage lang."""
    person, kalender = welt
    t = termine.anlegen(
        db, person, kalender.id, titel="Feiertag", beginn=_berlin(3, 0), ganztaegig=True
    )
    assert t.ende - t.beginn == timedelta(days=1)


def test_ein_ende_vor_dem_beginn_geht_nicht(db, welt):
    person, kalender = welt
    with pytest.raises(termine.TerminFehler) as f:
        termine.anlegen(
            db, person, kalender.id, titel="Verdreht",
            beginn=_berlin(2, 10), ende=_berlin(2, 9),
        )
    assert str(f.value) == "termin_ende_vor_beginn"


def test_jeder_termin_bekommt_eine_eigene_uid(db, welt):
    person, kalender = welt
    a = termine.anlegen(db, person, kalender.id, titel="Eins", beginn=_berlin(2))
    b = termine.anlegen(db, person, kalender.id, titel="Zwei", beginn=_berlin(3))
    assert a.uid and b.uid and a.uid != b.uid


# --- Anzeigen ------------------------------------------------------------- #


def test_das_fenster_zeigt_die_reihe_ausgerechnet(db, welt):
    person, kalender = welt
    termine.anlegen(
        db, person, kalender.id, titel="Wochenstart",
        beginn=_berlin(7), rrule="FREQ=WEEKLY;BYDAY=MO", zeitzone="Europe/Berlin",
    )
    raus = _fenster(db, person, 1, 30)
    assert [s.beginn.astimezone(BERLIN).day for s in raus] == [7, 14, 21, 28]
    assert all(s.aus_reihe for s in raus)


def test_eine_reihe_verschwindet_nicht_beim_weiterblaettern(db, welt):
    """⚠️ Sie beginnt VOR dem Fenster. Wer auf ``beginn >= von`` einschränkt,
    verliert jeden wiederholten Termin, sobald man eine Woche weiterblättert."""
    person, kalender = welt
    termine.anlegen(
        db, person, kalender.id, titel="Wochenstart",
        beginn=_berlin(7), rrule="FREQ=WEEKLY;BYDAY=MO", zeitzone="Europe/Berlin",
    )
    assert len(_fenster(db, person, 20, 30)) == 2


def _gelesene_termine(db, arbeit):
    """Wie viele ``Termin``-Zeilen die Abfrage wirklich aus der Datei holt.

    ⚠️ **Das Ergebnis allein beweist hier nichts.** ``fenster`` siebt
    hinterher in Python nach, was das Fenster beruehrt — die Liste war also
    auch vorher richtig. Falsch war, wie viel dafuer gelesen wurde. Ein Test
    auf die Rueckgabe bestand die Mutationsprobe deshalb klaglos.
    """
    from sqlalchemy import event as _event

    from app.models import Termin as _Termin

    db.expunge_all()  # sonst kommen sie aus der Identitaetsabbildung
    geladen: list[int] = []

    @_event.listens_for(db, "loaded_as_persistent")
    def merken(sitzung, instanz):  # noqa: ARG001
        if isinstance(instanz, _Termin):
            geladen.append(instanz.id)

    try:
        ergebnis = arbeit()
    finally:
        _event.remove(db, "loaded_as_persistent", merken)
    return ergebnis, geladen


def test_die_vergangenheit_wird_nicht_mitgelesen(db, welt):
    """⚠️ **Ohne untere Grenze las jede Monatsansicht den ganzen Bestand.**

    Bis zum 03.09.2026 stand hier nur ``beginn < bis``. Ein einzelner Termin
    von vor drei Jahren kam damit bei jedem Blaettern mit — samt seiner
    ``roh``-Spalte, in der das ganze ``VEVENT`` steht. Gemessen bei 20.000
    Terminen ueber zehn Jahre: 19.438 gelesene Zeilen statt der 660, die das
    Fenster wirklich beruehren.
    """
    person, kalender = welt
    for tag in (1, 2, 3, 4):
        termine.anlegen(db, person, kalender.id, titel=f"Lange her {tag}", beginn=_berlin(tag))
    termine.anlegen(db, person, kalender.id, titel="Im Fenster", beginn=_berlin(12))

    raus, gelesen = _gelesene_termine(db, lambda: _fenster(db, person, 10, 15))

    assert [s.termin.titel for s in raus] == ["Im Fenster"]
    assert len(gelesen) == 1, (
        f"{len(gelesen)} Zeilen gelesen, um einen Termin zu zeigen — "
        "die Vergangenheit kommt mit."
    )


def test_ein_termin_der_ins_fenster_hineinragt_bleibt_drin(db, welt):
    """⚠️ **``ende > von``, nicht ``beginn >= von``.**

    Eine Fortbildung von Montag bis Freitag muss auch dann dastehen, wenn das
    Fenster erst am Mittwoch beginnt. Wer auf den Beginn einschraenkt, laesst
    sie verschwinden, und zwar nur beim Blaettern — also genau dort, wo es
    niemand ausprobiert.
    """
    person, kalender = welt
    termine.anlegen(
        db, person, kalender.id, titel="Fortbildung",
        beginn=_berlin(8), ende=_berlin(12),
    )
    assert [s.termin.titel for s in _fenster(db, person, 10, 15)] == ["Fortbildung"]


def test_ein_termin_der_genau_am_fensteranfang_endet_faellt_heraus(db, welt):
    """⚠️ **``DTEND`` ist ausschliessend, und hier faellt das auf.**

    Eine Besprechung von 22 bis 24 Uhr endet genau dann, wenn das Fenster des
    naechsten Tages beginnt. Sie beruehrt es nicht mehr. Mit ``ende >= von``
    wuerde sie weiterhin aus der Datei gelesen; im Ergebnis saehe man das
    nicht, weil ``fenster`` sie danach aussiebt — gelesen waere sie trotzdem,
    und bei einem Kalender mit Jahren an Bestand ist genau das der Posten.

    ⚠️ **Nicht mit einem ganztaegigen Termin geprueft.** Der landet auf
    UTC-Mitternacht (nachgemessen: Beginn 9. September 00:00 Berlin wird zu
    ``2026-09-08 00:00+00:00``) und liegt damit gar nicht am Rand. Ein Test
    darauf saehe richtig aus und bewiese nichts — die erste Fassung dieses
    Tests hat die Mutationsprobe deshalb klaglos bestanden.
    """
    person, kalender = welt
    termine.anlegen(
        db, person, kalender.id, titel="Endet punktgenau",
        beginn=_berlin(9, 22), ende=_berlin(10, 0),
    )
    termine.anlegen(db, person, kalender.id, titel="Im Fenster", beginn=_berlin(11))

    raus, gelesen = _gelesene_termine(db, lambda: _fenster(db, person, 10, 15))

    assert [s.termin.titel for s in raus] == ["Im Fenster"]
    assert len(gelesen) == 1, (
        "Der Termin, der genau zum Fensteranfang endet, wird mitgelesen."
    )


def test_ein_abgesagter_termin_steht_nicht_im_kalender(db, welt):
    person, kalender = welt
    t = termine.anlegen(db, person, kalender.id, titel="Weg", beginn=_berlin(2))
    t.status = "CANCELLED"
    db.commit()
    assert _fenster(db, person, 1, 5) == []


def test_das_fenster_laesst_sich_auf_kalender_einschraenken(db, welt):
    person, kalender = welt
    zweiter = termine.kalender_anlegen(db, person, "Arbeit")
    termine.anlegen(db, person, kalender.id, titel="Privat", beginn=_berlin(2))
    termine.anlegen(db, person, zweiter.id, titel="Arbeit", beginn=_berlin(2, 11))

    raus = _fenster(db, person, 1, 5, kalender_ids=[zweiter.id])
    assert [s.termin.titel for s in raus] == ["Arbeit"]


def test_ein_verdrehtes_fenster_geht_nicht(db, welt):
    person, _ = welt
    with pytest.raises(termine.TerminFehler) as f:
        termine.fenster(db, person, _berlin(9), _berlin(2))
    assert str(f.value) == "fenster_verdreht"


def test_ein_riesiges_fenster_geht_nicht(db, welt):
    """⚠️ Ohne Deckel rechnet ein verirrter Aufruf zehn Jahre Reihen aus."""
    person, _ = welt
    with pytest.raises(termine.TerminFehler) as f:
        termine.fenster(db, person, _berlin(2), _berlin(2) + timedelta(days=3000))
    assert str(f.value) == "fenster_zu_gross"


# --- Ändern: der heikle Teil ---------------------------------------------- #


def _reihe(db, person, kalender):
    return termine.anlegen(
        db, person, kalender.id, titel="Wochenstart",
        beginn=_berlin(7), rrule="FREQ=WEEKLY;BYDAY=MO", zeitzone="Europe/Berlin",
    )


def test_alle_aendert_die_ganze_reihe(db, welt):
    person, kalender = welt
    t = _reihe(db, person, kalender)
    termine.aendern(db, person, t.id, umfang="alle", titel="Jour fixe")
    assert {s.termin.titel for s in _fenster(db, person, 1, 30)} == {"Jour fixe"}


def test_nur_dieser_aendert_genau_einen(db, welt):
    """⚠️ **Der Fall, um den es geht.** Die Reihe bleibt, wie sie ist."""
    person, kalender = welt
    t = _reihe(db, person, kalender)

    termine.aendern(
        db, person, t.id, umfang="dieser", vorkommen=_berlin(14), titel="Ausnahmsweise"
    )

    raus = _fenster(db, person, 1, 30)
    nach_tag = {s.beginn.astimezone(BERLIN).day: s.termin.titel for s in raus}
    assert nach_tag == {7: "Wochenstart", 14: "Ausnahmsweise", 21: "Wochenstart", 28: "Wochenstart"}


def test_der_geaenderte_termin_erscheint_nicht_doppelt(db, welt):
    """⚠️ Die Ausnahme UND die Reihe würden sonst beide den 14. zeigen."""
    person, kalender = welt
    t = _reihe(db, person, kalender)
    termine.aendern(db, person, t.id, umfang="dieser", vorkommen=_berlin(14), titel="X")

    tage = [s.beginn.astimezone(BERLIN).day for s in _fenster(db, person, 1, 30)]
    assert tage.count(14) == 1


def test_dieser_und_folgende_teilt_die_reihe(db, welt):
    person, kalender = welt
    t = _reihe(db, person, kalender)

    termine.aendern(
        db, person, t.id, umfang="folgende", vorkommen=_berlin(21), titel="Neuer Name"
    )

    raus = _fenster(db, person, 1, 30)
    nach_tag = {s.beginn.astimezone(BERLIN).day: s.termin.titel for s in raus}
    assert nach_tag == {7: "Wochenstart", 14: "Wochenstart", 21: "Neuer Name", 28: "Neuer Name"}


def test_die_neue_reihe_hat_eine_eigene_uid(db, welt):
    """⚠️ Zwei Reihen unter derselben Kennung sind für jeden anderen Client
    ein Widerspruch."""
    person, kalender = welt
    t = _reihe(db, person, kalender)
    neu = termine.aendern(db, person, t.id, umfang="folgende", vorkommen=_berlin(21), titel="X")
    assert neu.uid != t.uid


def test_beim_teilen_faellt_ein_vorhandenes_count(db, welt):
    """⚠️ ``COUNT`` und ``UNTIL`` schließen sich aus (RFC 5545) — eine Regel
    mit beidem lesen manche Clients gar nicht."""
    person, kalender = welt
    t = termine.anlegen(
        db, person, kalender.id, titel="Vier Mal", beginn=_berlin(7),
        rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=4", zeitzone="Europe/Berlin",
    )
    termine.aendern(db, person, t.id, umfang="folgende", vorkommen=_berlin(21), titel="X")
    db.refresh(t)
    assert "COUNT" not in t.rrule.upper()
    assert "UNTIL" in t.rrule.upper()


def test_verschieben_behaelt_die_dauer(db, welt):
    """⚠️ Sonst rutscht das Ende beim Verschieben auf den alten Zeitpunkt."""
    person, kalender = welt
    t = termine.anlegen(
        db, person, kalender.id, titel="Lang", beginn=_berlin(2, 9), ende=_berlin(2, 12)
    )
    termine.aendern(db, person, t.id, beginn=_berlin(3, 14))
    db.refresh(t)
    assert t.ende - t.beginn == timedelta(hours=3)


def test_ein_unbekannter_umfang_geht_nicht(db, welt):
    person, kalender = welt
    t = _reihe(db, person, kalender)
    with pytest.raises(termine.TerminFehler) as f:
        termine.aendern(db, person, t.id, umfang="vielleicht", titel="X")
    assert str(f.value) == "umfang_unbekannt"


# --- Löschen -------------------------------------------------------------- #


def test_nur_diesen_loeschen_klinkt_ihn_aus(db, welt):
    person, kalender = welt
    t = _reihe(db, person, kalender)

    termine.entfernen(db, person, t.id, umfang="dieser", vorkommen=_berlin(14))

    tage = [s.beginn.astimezone(BERLIN).day for s in _fenster(db, person, 1, 30)]
    assert tage == [7, 21, 28]


def test_diesen_und_folgende_loeschen_kappt_die_reihe(db, welt):
    person, kalender = welt
    t = _reihe(db, person, kalender)

    termine.entfernen(db, person, t.id, umfang="folgende", vorkommen=_berlin(21))

    tage = [s.beginn.astimezone(BERLIN).day for s in _fenster(db, person, 1, 30)]
    assert tage == [7, 14]


def test_alle_loeschen_nimmt_auch_die_ausnahmen_mit(db, welt):
    """⚠️ Sonst bleiben einzelne Termine ohne ihre Reihe stehen, und niemand
    weiß mehr, wozu sie gehörten."""
    person, kalender = welt
    t = _reihe(db, person, kalender)
    termine.aendern(db, person, t.id, umfang="dieser", vorkommen=_berlin(14), titel="Ausnahme")
    assert db.query(Termin).count() == 2

    termine.entfernen(db, person, t.id, umfang="alle")

    assert db.query(Termin).count() == 0


def test_ein_einzelner_termin_braucht_keinen_umfang(db, welt):
    person, kalender = welt
    t = termine.anlegen(db, person, kalender.id, titel="Einmalig", beginn=_berlin(2))
    termine.entfernen(db, person, t.id)
    assert _fenster(db, person, 1, 5) == []


def test_ohne_vorkommen_geht_nur_dieser_nicht(db, welt):
    person, kalender = welt
    t = _reihe(db, person, kalender)
    with pytest.raises(termine.TerminFehler) as f:
        termine.entfernen(db, person, t.id, umfang="dieser")
    assert str(f.value) == "vorkommen_fehlt"


def test_ein_fremder_termin_ist_unbekannt(db, welt):
    person, kalender = welt
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.flush()
    seiner = termine.kalender_anlegen(db, anderer, "Privat")
    seins = termine.anlegen(db, anderer, seiner.id, titel="Geheim", beginn=_berlin(2))

    with pytest.raises(termine.TerminFehler) as f:
        termine.entfernen(db, person, seins.id)
    assert str(f.value) == "termin_unbekannt"


# --- Ganztägig ist ein Datum, kein Zeitpunkt ------------------------------ #


def test_ganztaegig_liegt_auf_utc_mitternacht(db, welt):
    """⚠️ **Ein Kalendertag ist kein Zeitpunkt.**

    Die Oberfläche schickte den 14. als Ortszeit; in Berlin wurde daraus
    ``2026-09-13T22:00:00Z``, und der Termin stand danach über zwei Tage.
    Westlich von Greenwich wäre er einen Tag zu früh gewesen. Am 03.09.2026 aus
    dem Betrieb gemeldet: „in nexmail steht er von 14–15".
    """
    person, kalender = welt

    termin = termine.anlegen(
        db, person, kalender.id,
        titel="Betriebsausflug",
        beginn=datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 14, 22, tzinfo=timezone.utc),
        ganztaegig=True,
    )

    assert termin.beginn == datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert termin.ende == datetime(2026, 9, 14, tzinfo=timezone.utc)


def test_ganztaegig_dauert_mindestens_einen_tag(db, welt):
    """⚠️ **„Null Tage lang" zeichnet man nicht.** In der Datenbank lag ein
    ganztägiger Termin mit **einer Stunde** Dauer — das Ende kam aus
    „eine Stunde später", weil die Maske für ganztägig dieselbe Vorgabe
    benutzte wie für einen Termin mit Uhrzeit."""
    person, kalender = welt

    termin = termine.anlegen(
        db, person, kalender.id,
        titel="Feiertag",
        beginn=datetime(2026, 9, 9, 22, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 9, 23, tzinfo=timezone.utc),
        ganztaegig=True,
    )

    assert termin.beginn == datetime(2026, 9, 9, tzinfo=timezone.utc)
    assert termin.ende == datetime(2026, 9, 10, tzinfo=timezone.utc)


def test_auch_beim_aendern(db, welt):
    """Dieselbe Regel beim Ändern — sonst zieht ein Haken bei „Ganztägig"
    einen sauberen Termin wieder schief."""
    person, kalender = welt
    termin = termine.anlegen(
        db, person, kalender.id,
        titel="Besprechung",
        beginn=datetime(2026, 9, 14, 8, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 14, 9, tzinfo=timezone.utc),
    )

    termine.aendern(db, person, termin.id, ganztaegig=True)

    assert termin.beginn == datetime(2026, 9, 14, tzinfo=timezone.utc)
    assert termin.ende == datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_ein_termin_mit_uhrzeit_bleibt_unberuehrt(db, welt):
    """Die Regel gilt **nur** ganztägig — sonst verlöre jede Besprechung ihre
    Uhrzeit."""
    person, kalender = welt
    termin = termine.anlegen(
        db, person, kalender.id,
        titel="Besprechung",
        beginn=datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 14, 9, 15, tzinfo=timezone.utc),
    )
    assert termin.beginn == datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc)
    assert termin.ende == datetime(2026, 9, 14, 9, 15, tzinfo=timezone.utc)


# --- Die Regel als Bausteine ---------------------------------------------- #


def test_eine_regel_wird_zerlegt():
    """Was die Maske füllt: Häufigkeit, Intervall, Tage, Ende."""
    from app.services import wiederholung

    regel = wiederholung.regel_lesen("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH;COUNT=10")

    assert regel.freq == "woechentlich"
    assert regel.intervall == 2
    assert regel.tage == ["TU", "TH"]
    assert (regel.ende_art, regel.anzahl) == ("anzahl", 10)
    assert not regel.fremd


def test_der_letzte_freitag_behaelt_seinen_wievielten():
    """⚠️ Ohne den Ordinal wäre „jeder letzte Freitag" nicht von „jeder erste
    Freitag" zu unterscheiden — und ein Speichern verschöbe die Reihe um drei
    Wochen."""
    from app.services import wiederholung

    regel = wiederholung.regel_lesen("FREQ=MONTHLY;BYDAY=-1FR")

    assert (regel.monatsart, regel.ordinal, regel.tage) == ("wochentag", -1, ["FR"])
    assert not regel.fremd


def test_was_die_maske_nicht_kann_bleibt_ganz():
    """⚠️ **Der wichtigste Fall.** Eine Regel mit ``BYMONTHDAY`` oder
    ``BYSETPOS`` zerlegt anzubieten hieße, sie beim Speichern zu zerstören —
    aus „am 15. jedes Monats" würde „monatlich" und der Tag ginge verloren."""
    from app.services import wiederholung

    for rrule in (
        "FREQ=MONTHLY;BYMONTHDAY=15",
        "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
        "FREQ=HOURLY",
        "FREQ=MONTHLY;BYDAY=1MO,3MO",
        "FREQ=MONTHLY;BYDAY=5MO",
    ):
        assert wiederholung.regel_lesen(rrule).fremd is True, rrule


def test_count_und_until_zusammen_gibt_es_nicht(db, welt):
    """⚠️ **RFC 5545: die beiden schließen sich aus.** Wer beides schickt, baut
    eine Regel, die manche Clients gar nicht lesen."""
    person, kalender = welt

    termin = termine.anlegen(
        db, person, kalender.id, titel="Reihe",
        beginn=datetime(2026, 9, 7, 9, tzinfo=timezone.utc),
        rrule="FREQ=DAILY;COUNT=5;UNTIL=20261231",
    )

    assert "COUNT=5" in termin.rrule
    assert "UNTIL" not in termin.rrule


def test_ein_enddatum_schliesst_seinen_tag_ein(db, welt):
    """⚠️ **``UNTIL`` steht in UTC und muss den letzten Tag noch einschließen.**

    Die Maske schickt ein Datum. Wer daraus Mitternacht macht, verliert das
    letzte Vorkommen — und niemand bringt das mit dem Enddatum in Verbindung.
    """
    person, kalender = welt

    termin = termine.anlegen(
        db, person, kalender.id, titel="Reihe",
        beginn=datetime(2026, 9, 7, 9, tzinfo=timezone.utc),
        rrule="FREQ=DAILY;UNTIL=20260910",
        zeitzone="Europe/Berlin",
    )

    # Der 10.09. muss noch dabei sein.
    fenster = termine.fenster(
        db, person,
        datetime(2026, 9, 7, tzinfo=timezone.utc),
        datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
    tage = sorted({s.beginn.date().isoformat() for s in fenster})
    assert tage[-1] == "2026-09-10", f"Der letzte Tag fehlt: {tage}"
