"""Einen Kalender als `.ics` ausgeben und einlesen.

⚠️ **Das Format muss verlustfrei durch nexmail hindurchgehen** — dieselbe
Zusage wie bei mboxrd. Wer beim Ausgeben nur die Felder schreibt, die nexmail
kennt, liefert eine Datei, in der die Hälfte des Kalenders fehlt, und merkt es
erst beim Einlesen woanders.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Benutzer, Kalender, Termin
from app.services import kalenderaustausch as dienst
from conftest import einrichten

FREMD = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//iOS 18.0//EN
BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
DTSTART:19700329T020000
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
DTSTART:19701025T030000
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:fremd-1@icloud
DTSTAMP:20260901T080000Z
DTSTART;TZID=Europe/Berlin:20260910T090000
DTEND;TZID=Europe/Berlin:20260910T100000
SUMMARY:Fremder Termin
X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-PT15M
DESCRIPTION:Erinnerung
END:VALARM
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    eigener = Kalender(benutzer_id=person.id, name="Privat", farbe=1)
    db.add(eigener)
    db.commit()
    return person, eigener


def _termin(db, person, kalender, **kw):
    vorgabe = dict(
        kalender_id=kalender.id,
        benutzer_id=person.id,
        uid="eigen-1@nexmail",
        titel="Zahnarzt",
        beginn=datetime(2026, 9, 10, 8, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 10, 9, tzinfo=timezone.utc),
        zeitzone="Europe/Berlin",
    )
    vorgabe.update(kw)
    zeile = Termin(**vorgabe)
    db.add(zeile)
    db.commit()
    return zeile


# --- Ausgeben ------------------------------------------------------------- #


def test_ein_eigener_termin_wird_gebaut(db, welt):
    person, kalender = welt
    _termin(db, person, kalender)

    text = dienst.ausgeben(db, person, kalender)

    assert text.startswith("BEGIN:VCALENDAR")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "UID:eigen-1@nexmail" in text
    assert "SUMMARY:Zahnarzt" in text
    # ⚠️ CRLF, sonst weisen manche Leser die Datei ab.
    assert "\r\n" in text and "\n\n" not in text


def test_das_original_geht_unangetastet_hinaus(db, welt):
    """⚠️ **Die Rückfahrkarte.** Alarme, `X-APPLE-…` und die Teilnehmer stehen
    nur im Original; wer neu baut, wirft sie weg."""
    person, kalender = welt
    _termin(db, person, kalender, uid="fremd-1@icloud", roh=FREMD)

    text = dienst.ausgeben(db, person, kalender)

    assert "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC" in text
    assert "BEGIN:VALARM" in text
    assert "TRIGGER:-PT15M" in text
    # ⚠️ **Und der Block ist zu.** Ein am ``END:VALARM`` abgeschnittenes
    # ``VEVENT`` enthält alle Zeilen oben trotzdem — es fehlt nur sein Ende,
    # und damit ist die ganze Datei kaputt. Genau daran lief die erste
    # Mutationsprobe vorbei.
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") == 1
    assert text.count("BEGIN:VALARM") == text.count("END:VALARM") == 1
    assert text.count("BEGIN:VTIMEZONE") == text.count("END:VTIMEZONE") == 1


def test_die_zeitzone_kommt_mit(db, welt):
    """⚠️ Ohne `VTIMEZONE` zeigt `DTSTART;TZID=…` auf eine Zone, die in der
    Datei nicht steht — strenge Leser weisen das ab, freundliche raten."""
    person, kalender = welt
    _termin(db, person, kalender, uid="fremd-1@icloud", roh=FREMD)

    text = dienst.ausgeben(db, person, kalender)

    assert "BEGIN:VTIMEZONE" in text
    assert "TZID:Europe/Berlin" in text


def test_eine_reihe_steht_einmal_da(db, welt):
    """⚠️ **Bei CalDAV hält jede Zeile die GANZE Datei in `roh`.** Wer sie je
    Zeile ausgibt, schreibt die Reihe so oft hinein, wie es Zeilen gibt."""
    person, kalender = welt
    _termin(db, person, kalender, uid="fremd-1@icloud", roh=FREMD)
    _termin(
        db,
        person,
        kalender,
        uid="fremd-1@icloud",
        recurrence_id="20260917T070000Z",
        roh=FREMD,
    )

    text = dienst.ausgeben(db, person, kalender)

    # Das Original kennt nur EIN VEVENT; die Ausnahme steht nicht darin und
    # wird deshalb gebaut. Zusammen sind es zwei, nicht drei.
    assert text.count("BEGIN:VEVENT") == 2
    assert text.count("X-APPLE-TRAVEL-ADVISORY-BEHAVIOR") == 1


def test_ein_fremder_kalender_wird_nicht_ausgegeben(db, welt, klient):
    person, kalender = welt
    fremd = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(fremd)
    db.commit()

    with pytest.raises(dienst.AustauschFehler):
        dienst.ausgeben(db, fremd, kalender)


def test_der_dateiname_traegt_den_kalendernamen(db, welt):
    person, kalender = welt
    kalender.name = "Arbeit / Verein"
    db.commit()
    name = dienst.dateiname(kalender)
    assert name.endswith(".ics")
    # ⚠️ Kein Schrägstrich — der macht daraus ein Verzeichnis.
    assert "/" not in name


# --- Einlesen ------------------------------------------------------------- #


def test_eine_datei_wird_eingelesen(db, welt):
    person, kalender = welt

    bericht = dienst.einlesen(db, person, kalender, FREMD)

    assert bericht.angelegt == 1
    zeile = db.query(Termin).one()
    assert zeile.uid == "fremd-1@icloud"
    assert zeile.titel == "Fremder Termin"
    # ⚠️ Die Rückfahrkarte kommt mit, sonst ist beim nächsten Ausgeben alles weg.
    assert "X-APPLE" in zeile.roh


def test_dieselbe_datei_zweimal_gibt_keine_doppel(db, welt):
    """⚠️ **Darauf ruht alles.** Wer nicht mehr weiß, ob er es schon getan hat,
    hätte seinen Kalender sonst doppelt — und von Hand ist das nicht mehr
    aufzuräumen. Dieselbe Regel wie die `Message-ID` beim mbox-Import."""
    person, kalender = welt

    dienst.einlesen(db, person, kalender, FREMD)
    zweiter = dienst.einlesen(db, person, kalender, FREMD)

    assert zweiter.angelegt == 0
    assert zweiter.uebersprungen == 1
    assert db.query(Termin).count() == 1


def test_ein_termin_ohne_uid_ist_kein_termin(db, welt):
    person, kalender = welt
    ohne = FREMD.replace("UID:fremd-1@icloud\n", "")

    bericht = dienst.einlesen(db, person, kalender, ohne)

    assert bericht.angelegt == 0
    assert bericht.unbrauchbar == 1


def test_in_einen_caldav_kalender_wird_nicht_eingelesen(db, welt):
    """⚠️ **Erst der Server, dann die eigene Datenbank.** Termine, die nur hier
    stehen, kämen beim Anbieter nie an — und niemand sähe, warum."""
    person, kalender = welt
    kalender.art = "caldav"
    db.commit()

    with pytest.raises(dienst.AustauschFehler) as f:
        dienst.einlesen(db, person, kalender, FREMD)
    assert f.value.kennung == "einfuhr_nur_in_eigenen_kalender"
    assert db.query(Termin).count() == 0


def test_in_ein_abo_wird_nicht_eingelesen(db, welt):
    person, kalender = welt
    # ⚠️ ``nur_lesen`` ist abgeleitet, kein Feld: Es gilt genau fuer ``ics``.
    kalender.art = "ics"
    db.commit()

    with pytest.raises(dienst.AustauschFehler) as f:
        dienst.einlesen(db, person, kalender, FREMD)
    # Die genauere Meldung gewinnt: Ein Abo bietet keinen Weg zurueck, das ist
    # etwas anderes als "geht nur in einen eigenen Kalender".
    assert f.value.kennung == "kalender_nur_lesen"


def test_etwas_das_keine_ics_ist_wird_benannt(db, welt):
    """⚠️ Sonst steht „0 angelegt" da, und man sucht den Fehler im Kalender."""
    person, kalender = welt

    with pytest.raises(dienst.AustauschFehler) as f:
        dienst.einlesen(db, person, kalender, "Hallo, das ist ein Brief.")
    assert f.value.kennung == "keine_ics_datei"


def test_die_grenze_wird_gesagt(db, welt, monkeypatch):
    """⚠️ „Mehr geht nicht" muss von „mehr war nicht drin" zu unterscheiden
    sein — dieselbe Regel wie am Fuß der Nachrichtenliste."""
    person, kalender = welt
    monkeypatch.setattr(dienst, "MAX_TERMINE", 1)

    zwei = FREMD.replace(
        "END:VCALENDAR",
        "BEGIN:VEVENT\nUID:fremd-2@icloud\nDTSTART:20260911T090000Z\n"
        "SUMMARY:Noch einer\nEND:VEVENT\nEND:VCALENDAR",
    )
    bericht = dienst.einlesen(db, person, kalender, zwei)

    assert bericht.angelegt == 1
    assert bericht.abgeschnitten is True


def test_ein_fremder_kalender_wird_nicht_befuellt(db, welt):
    person, kalender = welt
    fremd = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(fremd)
    db.commit()

    with pytest.raises(dienst.AustauschFehler):
        dienst.einlesen(db, fremd, kalender, FREMD)


# --- Hin und zurück ------------------------------------------------------- #


def test_ausgeben_und_wieder_einlesen_verliert_nichts(db, welt):
    """⚠️ **Die eigentliche Zusage.** Ein Umzug, bei dem unterwegs etwas
    wegfällt, ist kein Umzug."""
    person, kalender = welt
    dienst.einlesen(db, person, kalender, FREMD)
    text = dienst.ausgeben(db, person, kalender)

    zweiter = Kalender(benutzer_id=person.id, name="Kopie", farbe=2)
    db.add(zweiter)
    db.commit()
    bericht = dienst.einlesen(db, person, zweiter, text)

    assert bericht.angelegt == 1
    kopie = db.query(Termin).filter_by(kalender_id=zweiter.id).one()
    original = db.query(Termin).filter_by(kalender_id=kalender.id).one()
    assert kopie.titel == original.titel
    assert kopie.beginn == original.beginn
    assert kopie.zeitzone == original.zeitzone
    assert "X-APPLE" in kopie.roh
    assert "BEGIN:VALARM" in kopie.roh
