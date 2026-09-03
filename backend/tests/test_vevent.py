"""``VEVENT`` lesen und verlustfrei zurückschreiben.

⚠️ **Der teuerste Fehler hier ist stiller Datenverlust.** Ein Termin von
iCloud trägt Erinnerungen, Teilnehmer und ein Dutzend `X-APPLE-…`. Wer beim
Zurückschreiben neu baut statt zu ersetzen, löscht das alles — und der
Besitzer merkt es erst, wenn die Erinnerung ausbleibt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services import vevent

BERLIN = ZoneInfo("Europe/Berlin")
JETZT = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _ics(*zeilen: str) -> str:
    return "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", *zeilen, "END:VCALENDAR"]
    )


def _termin(**kw):
    vorgabe = dict(
        uid="a@example.com", titel="Zahnarzt", beschreibung="", ort="",
        beginn=datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
        ganztaegig=False, zeitzone="Europe/Berlin", rrule="", exdate="",
        recurrence_id="", sequenz=0,
    )
    vorgabe.update(kw)
    return SimpleNamespace(**vorgabe)


# --- Lesen ---------------------------------------------------------------- #


def test_ein_einfacher_termin():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT",
            "UID:a@example.com",
            "SUMMARY:Zahnarzt",
            "LOCATION:Hauptstraße 1",
            "DTSTART:20260907T070000Z",
            "DTEND:20260907T080000Z",
            "END:VEVENT",
        )
    )
    assert len(raus) == 1
    e = raus[0]
    assert e["uid"] == "a@example.com"
    assert e["titel"] == "Zahnarzt"
    assert e["ort"] == "Hauptstraße 1"
    assert e["beginn"] == datetime(2026, 9, 7, 7, tzinfo=timezone.utc)
    assert e["ganztaegig"] is False


def test_mehrere_termine_in_einer_datei():
    """⚠️ Bei CalDAV liegt eine Reihe samt ihren Ausnahmen in EINER Datei.

    Wer nur den ersten liest, verliert die überschriebenen Einzeltermine.
    """
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a@example.com", "SUMMARY:Reihe",
            "DTSTART:20260907T070000Z", "RRULE:FREQ=WEEKLY", "END:VEVENT",
            "BEGIN:VEVENT", "UID:a@example.com", "SUMMARY:Ausnahme",
            "RECURRENCE-ID:20260914T070000Z",
            "DTSTART:20260914T090000Z", "END:VEVENT",
        )
    )
    assert [e["titel"] for e in raus] == ["Reihe", "Ausnahme"]
    assert raus[1]["recurrence_id"] == "2026-09-14T07:00:00+00:00"


def test_eine_gefaltete_zeile_wird_zusammengesetzt():
    """⚠️ Wer an ``\\n`` trennt, schneidet mitten im Titel ab."""
    raus = vevent.lesen(
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\n"
        "SUMMARY:Ein sehr langer Titel\r\n  der umgebrochen wurde\r\n"
        "DTSTART:20260907T070000Z\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )
    assert raus[0]["titel"] == "Ein sehr langer Titel der umgebrochen wurde"


def test_ein_ganztaegiger_termin():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a", "SUMMARY:Feiertag",
            "DTSTART;VALUE=DATE:20261003", "DTEND;VALUE=DATE:20261004", "END:VEVENT",
        )
    )
    assert raus[0]["ganztaegig"] is True
    assert raus[0]["ende"] - raus[0]["beginn"] == timedelta(days=1)


def test_eine_zeitzone_wird_umgerechnet():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a", "SUMMARY:X",
            "DTSTART;TZID=Europe/Berlin:20260907T090000", "END:VEVENT",
        )
    )
    # 9 Uhr Berlin im September = 7 Uhr UTC.
    assert raus[0]["beginn"] == datetime(2026, 9, 7, 7, tzinfo=timezone.utc)
    assert raus[0]["zeitzone"] == "Europe/Berlin"


def test_ohne_ende_dauert_ein_ganztaegiger_einen_tag():
    """RFC 5545 3.6.1 — und ein zeitgebundener null Sekunden, was man nicht
    zeichnen kann. Daraus wird eine Stunde, wie in jedem Kalenderprogramm."""
    ganz = vevent.lesen(
        _ics("BEGIN:VEVENT", "UID:a", "DTSTART;VALUE=DATE:20261003", "END:VEVENT")
    )[0]
    kurz = vevent.lesen(
        _ics("BEGIN:VEVENT", "UID:b", "DTSTART:20260907T070000Z", "END:VEVENT")
    )[0]
    assert ganz["ende"] - ganz["beginn"] == timedelta(days=1)
    assert kurz["ende"] - kurz["beginn"] == timedelta(hours=1)


def test_eine_dauer_statt_eines_endes():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a", "DTSTART:20260907T070000Z",
            "DURATION:PT1H30M", "END:VEVENT",
        )
    )
    assert raus[0]["ende"] - raus[0]["beginn"] == timedelta(hours=1, minutes=30)


def test_das_dtstart_einer_zeitzonenregel_zaehlt_nicht():
    """⚠️ **Die Falle, die einen Termin um Jahre verschiebt.**

    Ein ``VTIMEZONE`` enthält selbst ``DTSTART``-Zeilen — sie stehen dort für
    den Beginn einer Sommerzeitregel, meist im Jahr 1970. Wer nur auf
    ``BEGIN:VEVENT`` wartet und die Verschachtelung nicht verfolgt, liest sie
    als Termindatum.
    """
    raus = vevent.lesen(
        _ics(
            "BEGIN:VTIMEZONE",
            "TZID:Europe/Berlin",
            "BEGIN:DAYLIGHT",
            "DTSTART:19700329T020000",
            "TZOFFSETFROM:+0100",
            "END:DAYLIGHT",
            "END:VTIMEZONE",
            "BEGIN:VEVENT",
            "UID:a",
            "SUMMARY:Echt",
            "DTSTART:20260907T070000Z",
            "END:VEVENT",
        )
    )
    assert len(raus) == 1
    assert raus[0]["beginn"].year == 2026


def test_ein_alarm_liefert_keinen_zweiten_termin():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a", "SUMMARY:Mit Alarm",
            "DTSTART:20260907T070000Z",
            "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "END:VALARM",
            "END:VEVENT",
        )
    )
    assert len(raus) == 1
    assert raus[0]["titel"] == "Mit Alarm"


def test_maskierter_text_wird_entschluesselt():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a",
            "DESCRIPTION:Erste Zeile\\nZweite\\, mit Komma",
            "DTSTART:20260907T070000Z", "END:VEVENT",
        )
    )
    assert raus[0]["beschreibung"] == "Erste Zeile\nZweite, mit Komma"


def test_exdate_kommt_als_liste():
    raus = vevent.lesen(
        _ics(
            "BEGIN:VEVENT", "UID:a", "DTSTART:20260907T070000Z",
            "RRULE:FREQ=WEEKLY",
            "EXDATE:20260914T070000Z,20260921T070000Z",
            "END:VEVENT",
        )
    )
    assert raus[0]["exdate"].count(",") == 1


def test_eine_leere_datei_gibt_nichts():
    assert vevent.lesen("") == []
    assert vevent.lesen("BEGIN:VCALENDAR\r\nEND:VCALENDAR") == []


# --- Schreiben ------------------------------------------------------------ #


def test_gebautes_laesst_sich_wieder_lesen():
    roh = vevent.bauen(_termin(ort="Praxis", rrule="FREQ=WEEKLY"), JETZT)
    wieder = vevent.lesen(roh)[0]

    assert wieder["uid"] == "a@example.com"
    assert wieder["titel"] == "Zahnarzt"
    assert wieder["ort"] == "Praxis"
    assert wieder["rrule"] == "FREQ=WEEKLY"
    assert wieder["beginn"] == datetime(2026, 9, 7, 7, tzinfo=timezone.utc)


def test_geschrieben_wird_mit_crlf():
    """⚠️ Manche Server weisen alles andere ab."""
    roh = vevent.bauen(_termin(), JETZT)
    assert "\r\n" in roh
    assert "\n" not in roh.replace("\r\n", "")


def test_eine_lange_zeile_wird_gefaltet():
    """⚠️ Über 75 Oktett bricht RFC 5545 um — sonst schneidet ein Server ab."""
    roh = vevent.bauen(_termin(titel="A" * 200), JETZT)
    assert all(len(z.encode()) <= 75 for z in roh.split("\r\n"))
    assert vevent.lesen(roh)[0]["titel"] == "A" * 200


def test_ein_umlaut_zerfaellt_beim_falten_nicht():
    """⚠️ Gefaltet wird auf Byte-Ebene; ein Zeichen darf dabei nicht
    auseinanderfallen."""
    titel = "ä" * 120
    roh = vevent.bauen(_termin(titel=titel), JETZT)
    assert vevent.lesen(roh)[0]["titel"] == titel


def test_ein_ganztaegiger_termin_wird_als_datum_geschrieben():
    roh = vevent.bauen(
        _termin(
            ganztaegig=True,
            beginn=datetime(2026, 10, 3, tzinfo=timezone.utc),
            ende=datetime(2026, 10, 4, tzinfo=timezone.utc),
        ),
        JETZT,
    )
    assert "DTSTART;VALUE=DATE:20261003" in roh
    assert vevent.lesen(roh)[0]["ganztaegig"] is True


def test_eine_zone_wird_als_tzid_geschrieben():
    """⚠️ Sonst friert der Versatz von heute ein — „9 Uhr" wäre nach der
    Zeitumstellung 8 oder 10."""
    roh = vevent.bauen(_termin(zeitzone="Europe/Berlin"), JETZT)
    assert "DTSTART;TZID=Europe/Berlin:20260907T090000" in roh


# --- Aktualisieren: die Rückfahrkarte ------------------------------------- #

FREMD = _ics(
    "BEGIN:VEVENT",
    "UID:a@example.com",
    "SUMMARY:Alter Titel",
    "DTSTART:20260907T070000Z",
    "DTEND:20260907T080000Z",
    "ATTENDEE;CN=Anja;PARTSTAT=ACCEPTED:mailto:anja@example.org",
    "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC",
    "BEGIN:VALARM",
    "TRIGGER:-PT15M",
    "ACTION:DISPLAY",
    "END:VALARM",
    "END:VEVENT",
)


def test_was_nexmail_nicht_kennt_bleibt_stehen():
    """⚠️ **Der Test, um den es geht.** Teilnehmer, Alarm und die
    Apple-Eigenheiten überleben eine Änderung des Titels."""
    raus = vevent.aktualisieren(FREMD, _termin(titel="Neuer Titel"), JETZT)

    assert "ATTENDEE;CN=Anja;PARTSTAT=ACCEPTED:mailto:anja@example.org" in raus
    assert "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC" in raus
    assert "BEGIN:VALARM" in raus
    assert "TRIGGER:-PT15M" in raus


def test_der_titel_wird_wirklich_ersetzt():
    raus = vevent.aktualisieren(FREMD, _termin(titel="Neuer Titel"), JETZT)
    assert "Alter Titel" not in raus
    assert vevent.lesen(raus)[0]["titel"] == "Neuer Titel"


def test_es_bleibt_bei_EINEM_dtstart():
    """Sonst hat der Termin zwei Anfänge, und welcher gilt, entscheidet der
    Zufall des lesenden Programms."""
    raus = vevent.aktualisieren(FREMD, _termin(), JETZT)
    zeilen = [z for z in raus.split("\r\n") if z.startswith("DTSTART")]
    assert len(zeilen) == 1


def test_ein_alarm_behaelt_seine_eigenen_zeilen():
    """⚠️ ``DTSTART`` in einem ``VALARM`` gehört dorthin — gefiltert wird nur
    im ``VEVENT`` selbst."""
    mit = _ics(
        "BEGIN:VEVENT", "UID:a", "SUMMARY:X", "DTSTART:20260907T070000Z",
        "BEGIN:VALARM", "TRIGGER;VALUE=DATE-TIME:20260907T063000Z",
        "ACTION:DISPLAY", "END:VALARM", "END:VEVENT",
    )
    raus = vevent.aktualisieren(mit, _termin(), JETZT)
    assert "TRIGGER;VALUE=DATE-TIME:20260907T063000Z" in raus


def test_ohne_original_wird_gebaut():
    raus = vevent.aktualisieren("", _termin(), JETZT)
    assert vevent.lesen(raus)[0]["titel"] == "Zahnarzt"


@pytest.mark.parametrize(
    "dauer,erwartet",
    [
        ("PT1H", timedelta(hours=1)),
        ("PT30M", timedelta(minutes=30)),
        ("P2D", timedelta(days=2)),
        ("P1W", timedelta(weeks=1)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("Unfug", None),
    ],
)
def test_dauerformen(dauer, erwartet):
    assert vevent._dauer_lesen(dauer) == erwartet
