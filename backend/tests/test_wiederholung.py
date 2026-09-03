"""Wiederholte Termine ausrechnen.

⚠️ **Die Fehler hier sind still.** Ein Termin, der um eine Stunde oder einen
Tag danebenliegt, sieht richtig aus — er ist nur falsch. Man merkt es, wenn
man zu spät kommt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services import wiederholung

BERLIN = "Europe/Berlin"


def _utc(jahr, monat, tag, stunde=0, minute=0) -> datetime:
    return datetime(jahr, monat, tag, stunde, minute, tzinfo=timezone.utc)


def _berlin(jahr, monat, tag, stunde, minute=0) -> datetime:
    return datetime(jahr, monat, tag, stunde, minute, tzinfo=ZoneInfo(BERLIN))


def _reihe(beginn, rrule, von, bis, dauer_min=60, exdate="", zone=BERLIN):
    return list(
        wiederholung.ausrechnen(
            beginn, beginn + timedelta(minutes=dauer_min), rrule, exdate, zone, von, bis
        )
    )


# --- Ohne Wiederholung ---------------------------------------------------- #


def test_ein_einzelner_termin_kommt_einmal():
    beginn = _utc(2026, 9, 2, 9)
    raus = _reihe(beginn, "", _utc(2026, 9, 1), _utc(2026, 9, 8))
    assert len(raus) == 1
    assert raus[0].beginn == beginn
    assert raus[0].ist_start is True


def test_ein_termin_ausserhalb_des_fensters_kommt_nicht():
    assert _reihe(_utc(2026, 9, 20, 9), "", _utc(2026, 9, 1), _utc(2026, 9, 8)) == []


def test_ein_langer_termin_zaehlt_auch_MITTEN_im_fenster():
    """⚠️ Ein Urlaub von Freitag bis Montag gehört in die Woche dazwischen.

    Wer nur auf den Beginn prüft, lässt lange Termine aus der Mitte
    verschwinden — und niemand sucht sie dort, wo sie angefangen haben.
    """
    raus = _reihe(_utc(2026, 8, 28), "", _utc(2026, 9, 1), _utc(2026, 9, 2), dauer_min=60 * 24 * 10)
    assert len(raus) == 1


# --- Wiederholungen ------------------------------------------------------- #


def test_jede_woche_montags():
    raus = _reihe(
        _berlin(2026, 9, 7, 9), "FREQ=WEEKLY;BYDAY=MO", _utc(2026, 9, 1), _utc(2026, 10, 1)
    )
    tage = [v.beginn.astimezone(ZoneInfo(BERLIN)).day for v in raus]
    assert tage == [7, 14, 21, 28]


def test_count_begrenzt_die_reihe():
    raus = _reihe(_berlin(2026, 9, 7, 9), "FREQ=DAILY;COUNT=3", _utc(2026, 9, 1), _utc(2026, 10, 1))
    assert len(raus) == 3


def test_until_begrenzt_die_reihe():
    raus = _reihe(
        _berlin(2026, 9, 7, 9),
        "FREQ=DAILY;UNTIL=20260909T235959Z",
        _utc(2026, 9, 1),
        _utc(2026, 10, 1),
    )
    assert len(raus) == 3


def test_jeden_letzten_freitag_im_monat():
    """Der Fall, an dem ein selbstgebauter Rechner scheitert."""
    raus = _reihe(
        _berlin(2026, 1, 30, 16),
        "FREQ=MONTHLY;BYDAY=-1FR",
        _utc(2026, 1, 1),
        _utc(2026, 5, 1),
    )
    tage = [(v.beginn.astimezone(ZoneInfo(BERLIN)).month, v.beginn.astimezone(ZoneInfo(BERLIN)).day) for v in raus]
    assert tage == [(1, 30), (2, 27), (3, 27), (4, 24)]


def test_nur_das_fenster_wird_ausgerechnet():
    """⚠️ Eine Regel ohne Ende läuft ewig — gerechnet wird nur, was man sieht."""
    raus = _reihe(_berlin(2020, 1, 1, 9), "FREQ=DAILY", _utc(2026, 9, 1), _utc(2026, 9, 8))
    assert len(raus) == 7


# --- Sommerzeit ----------------------------------------------------------- #


def test_neun_uhr_bleibt_neun_uhr_ueber_die_zeitumstellung():
    """⚠️ **Der Fehler, der den halben Kalender verschiebt.**

    „Jeden Montag um 9 Uhr" heißt neun Uhr Ortszeit, auch nach der Umstellung.
    Wer die Reihe in UTC ausrechnet, hat ab Ende Oktober überall 10 Uhr — und
    niemand bringt das mit der Zeitumstellung in Verbindung.
    """
    # Umstellung in Europa: letzter Sonntag im Oktober 2026 = 25.10.
    raus = _reihe(
        _berlin(2026, 10, 19, 9), "FREQ=WEEKLY;BYDAY=MO", _utc(2026, 10, 1), _utc(2026, 11, 15)
    )
    ortszeiten = {v.beginn.astimezone(ZoneInfo(BERLIN)).hour for v in raus}
    assert ortszeiten == {9}, f"Nach der Umstellung verschoben: {sorted(ortszeiten)}"
    # Und die Gegenprobe: in UTC sind es wirklich zwei verschiedene Stunden.
    assert len({v.beginn.hour for v in raus}) == 2


def test_ein_termin_in_UTC_bleibt_in_UTC():
    """Wer ausdrücklich UTC will, bekommt keine Ortszeit untergeschoben."""
    raus = _reihe(
        _utc(2026, 10, 19, 9), "FREQ=WEEKLY;BYDAY=MO", _utc(2026, 10, 1), _utc(2026, 11, 15),
        zone="UTC",
    )
    assert {v.beginn.hour for v in raus} == {9}


# --- Ausnahmen ------------------------------------------------------------ #


def test_eine_ausnahme_faellt_aus():
    """⚠️ Ohne das steht ein abgesagter Termin weiter im Kalender."""
    exdate = _berlin(2026, 9, 14, 9).isoformat()
    raus = _reihe(
        _berlin(2026, 9, 7, 9),
        "FREQ=WEEKLY;BYDAY=MO",
        _utc(2026, 9, 1),
        _utc(2026, 10, 1),
        exdate=exdate,
    )
    tage = [v.beginn.astimezone(ZoneInfo(BERLIN)).day for v in raus]
    assert 14 not in tage
    assert tage == [7, 21, 28]


def test_eine_ausnahme_mit_sekunden_greift_trotzdem():
    """Manche Server schreiben Sekunden mit, andere nicht."""
    exdate = _berlin(2026, 9, 14, 9).replace(second=30).isoformat()
    raus = _reihe(
        _berlin(2026, 9, 7, 9), "FREQ=WEEKLY;BYDAY=MO", _utc(2026, 9, 1), _utc(2026, 10, 1),
        exdate=exdate,
    )
    assert 14 not in [v.beginn.astimezone(ZoneInfo(BERLIN)).day for v in raus]


def test_eine_unlesbare_ausnahme_wirft_nichts_um():
    raus = _reihe(
        _berlin(2026, 9, 7, 9), "FREQ=WEEKLY;BYDAY=MO", _utc(2026, 9, 1), _utc(2026, 10, 1),
        exdate="das ist kein Datum",
    )
    assert len(raus) == 4


# --- Fehlerfälle ---------------------------------------------------------- #


def test_eine_kaputte_regel_verschluckt_den_termin_nicht():
    """⚠️ Sie kommt von einem fremden Server — er darf uns keinen Eintrag kosten."""
    raus = _reihe(_utc(2026, 9, 2, 9), "FREQ=NIEMALS;BLA", _utc(2026, 9, 1), _utc(2026, 9, 8))
    assert len(raus) == 1


def test_eine_regel_die_jede_sekunde_trifft_wird_gedeckelt(monkeypatch):
    """⚠️ Ohne Deckel rechnet ein einziger Termin den Server fest."""
    monkeypatch.setattr(wiederholung, "MAX_VORKOMMEN", 50)
    raus = _reihe(_utc(2026, 9, 2, 9), "FREQ=SECONDLY", _utc(2026, 9, 2), _utc(2026, 9, 3))
    assert len(raus) == 50


# --- Die Kennung für die Oberfläche --------------------------------------- #


@pytest.mark.parametrize(
    "rrule,erwartet",
    [
        ("FREQ=DAILY", ("taeglich", [], 1)),
        ("FREQ=WEEKLY", ("woechentlich", [], 1)),
        ("FREQ=WEEKLY;BYDAY=MO", ("woechentlich", ["MO"], 1)),
        ("FREQ=WEEKLY;BYDAY=TU,TH", ("woechentlich", ["TU", "TH"], 1)),
        ("FREQ=MONTHLY", ("monatlich", [], 1)),
        ("FREQ=YEARLY", ("jaehrlich", [], 1)),
        ("FREQ=WEEKLY;INTERVAL=2", ("woechentlich", [], 2)),
        ("", ("", [], 1)),
    ],
)
def test_die_regel_wird_zu_einer_kennung(rrule, erwartet):
    """⚠️ Keine deutschen Sätze im Server — nexmail spricht zwei Sprachen.

    ⚠️ **Und die Wochentage kommen als Liste, nicht in der Kennung.** Ein
    ``woechentlich_tu_th`` als Übersetzungsschlüssel hieße: für jede der 127
    möglichen Kombinationen ein Satz in zwei Sprachen.
    """
    assert wiederholung.als_satz(rrule) == erwartet


def test_ein_besonderer_wochentag_wird_nicht_zu_freitags():
    """⚠️ „Jeder letzte Freitag" ist etwas anderes als „freitags".

    Es als „freitags" auszugeben wäre eine falsche Auskunft — lieber
    „wiederholt sich" und die Regel bleibt unangetastet.
    """
    assert wiederholung.als_satz("FREQ=MONTHLY;BYDAY=-1FR") == ("allgemein", [], 1)


def test_ein_kaputtes_intervall_wirft_nichts_um():
    assert wiederholung.als_satz("FREQ=DAILY;INTERVAL=viele") == ("taeglich", [], 1)


# --- Das nächste Vorkommen ------------------------------------------------ #


def test_das_naechste_vorkommen():
    naechste = wiederholung.naechstes(
        _berlin(2026, 9, 7, 9), "FREQ=WEEKLY;BYDAY=MO", "", BERLIN, _utc(2026, 9, 10)
    )
    assert naechste is not None
    assert naechste.astimezone(ZoneInfo(BERLIN)).day == 14


def test_eine_abgelaufene_reihe_hat_kein_naechstes():
    assert (
        wiederholung.naechstes(
            _berlin(2026, 9, 7, 9), "FREQ=DAILY;COUNT=2", "", BERLIN, _utc(2026, 9, 10)
        )
        is None
    )
