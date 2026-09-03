"""Termin-Einladungen lesen und beantworten.

⚠️ **Ein selbstgebauter iCalendar-Leser scheitert an drei Stellen**, und jede
hat hier ihren Test: gefaltete Zeilen, der Doppelpunkt in einem Parameter, und
maskierter Text. Wer eine davon übersieht, zeigt einen abgeschnittenen Titel
oder eine falsche Adresse an — und merkt es erst, wenn jemand zur falschen Zeit
im falschen Raum sitzt.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import anbieter, kalender, konten
from test_konten import _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="", token="": _guter_befund())
    yield


def _ics(*zeilen: str) -> str:
    return "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", "METHOD:REQUEST", "BEGIN:VEVENT", *zeilen,
         "END:VEVENT", "END:VCALENDAR"]
    )


# --- Die drei Fallen ------------------------------------------------------ #


def test_gefaltete_zeilen_werden_zusammengesetzt():
    """⚠️ RFC 5545 bricht lange Zeilen um. Wer an ``\\n`` trennt, schneidet
    mitten im Titel ab."""
    roh = _ics(
        "UID:1@example.org",
        "SUMMARY:Quartalsbesprechung mit dem gesamten Team und anschlie",
        " ßender Führung durch die Halle",
    )
    termin = kalender.lesen(roh)
    assert termin.titel == (
        "Quartalsbesprechung mit dem gesamten Team und anschließender Führung durch die Halle"
    )


def test_ein_doppelpunkt_im_parameter_verwirrt_nicht():
    """⚠️ ``CN="Meier: Chef"`` — der erste Doppelpunkt gehört zum Namen."""
    roh = _ics(
        "UID:2@example.org",
        'ORGANIZER;CN="Meier: Chef":mailto:chef@example.org',
    )
    termin = kalender.lesen(roh)
    assert termin.organisator.name == "Meier: Chef"
    assert termin.organisator.adresse == "chef@example.org"


def test_maskierter_text_wird_entmaskiert():
    """⚠️ ``\\n``, ``\\,`` und ``\\;`` stehen für Zeichen, nicht für sich selbst."""
    roh = _ics(
        "UID:3@example.org",
        "SUMMARY:Termin mit Meier\\, Schulze und Co.",
        "DESCRIPTION:Erste Zeile\\nZweite Zeile\\; mit Semikolon",
        "LOCATION:Halle 3\\, Eingang Nord",
    )
    termin = kalender.lesen(roh)
    assert termin.titel == "Termin mit Meier, Schulze und Co."
    assert termin.beschreibung == "Erste Zeile\nZweite Zeile; mit Semikolon"
    assert termin.ort == "Halle 3, Eingang Nord"


# --- Die Zeit ------------------------------------------------------------- #


def test_utc_wird_in_die_eigene_zeitzone_gerechnet():
    roh = _ics("UID:4@example.org", "DTSTART:20260910T080000Z", "DTEND:20260910T093000Z")
    termin = kalender.lesen(roh, "Europe/Berlin")
    # 08:00 UTC ist im September 10:00 in Berlin.
    assert termin.beginn.startswith("2026-09-10T10:00:00")
    assert termin.ende.startswith("2026-09-10T11:30:00")
    assert termin.ganztaegig is False


def test_eine_bekannte_zeitzone_wird_umgerechnet():
    roh = _ics("UID:5@example.org", "DTSTART;TZID=America/New_York:20260910T090000")
    termin = kalender.lesen(roh, "Europe/Berlin")
    # 09:00 in New York ist 15:00 in Berlin.
    assert termin.beginn.startswith("2026-09-10T15:00:00")
    assert termin.fremde_zeitzone == ""


def test_eine_unbekannte_zeitzone_wird_nicht_geraten():
    """⚠️ Lieber die Zeit so zeigen, wie sie kam, und die Zone benennen.

    Sie stillschweigend als eigene Ortszeit zu lesen, verschiebt den Termin um
    Stunden — und niemand sieht es der Anzeige an.
    """
    roh = _ics("UID:6@example.org", 'DTSTART;TZID="Hausinterne Zeit":20260910T090000')
    termin = kalender.lesen(roh, "Europe/Berlin")
    assert termin.beginn.startswith("2026-09-10T09:00:00")
    assert termin.fremde_zeitzone == "Hausinterne Zeit"


def test_ein_ganzer_tag_ist_kein_zeitpunkt():
    roh = _ics("UID:7@example.org", "DTSTART;VALUE=DATE:20260910")
    termin = kalender.lesen(roh, "Europe/Berlin")
    assert termin.ganztaegig is True
    assert termin.beginn == "2026-09-10"


def test_dauer_statt_ende():
    roh = _ics("UID:8@example.org", "DTSTART:20260910T080000Z", "DURATION:PT1H30M")
    termin = kalender.lesen(roh, "UTC")
    assert termin.ende.startswith("2026-09-10T09:30:00")


# --- Was die Anzeige wissen muss ------------------------------------------ #


def test_eine_wiederholung_wird_benannt_nicht_ausgerechnet():
    """Ausrechnen wäre gelogen; verschweigen wäre schlimmer."""
    roh = _ics("UID:9@example.org", "DTSTART:20260910T080000Z", "RRULE:FREQ=WEEKLY;COUNT=10")
    assert kalender.lesen(roh).wiederholt_sich is True


def test_eine_absage_ist_als_solche_erkennbar():
    roh = "\r\n".join(
        ["BEGIN:VCALENDAR", "METHOD:CANCEL", "BEGIN:VEVENT", "UID:10@example.org",
         "END:VEVENT", "END:VCALENDAR"]
    )
    termin = kalender.lesen(roh)
    assert termin.methode == "CANCEL"
    assert termin.abgesagt is True


def test_teilnehmer_werden_gelesen():
    roh = _ics(
        "UID:11@example.org",
        'ATTENDEE;CN="Anna Beispiel":mailto:anna@example.org',
        "ATTENDEE:mailto:bert@example.org",
    )
    termin = kalender.lesen(roh)
    assert [t.adresse for t in termin.teilnehmer] == ["anna@example.org", "bert@example.org"]
    assert termin.teilnehmer[0].name == "Anna Beispiel"


def test_ohne_vevent_kommt_nichts_zurueck():
    assert kalender.lesen("BEGIN:VCALENDAR\r\nEND:VCALENDAR") is None
    assert kalender.lesen(b"") is None


def test_kaputtes_kalenderblatt_wirft_nicht():
    """Eine Einladung ist fremder Inhalt. Sie darf nichts umreißen."""
    assert kalender.lesen(_ics("UID:12@example.org", "DTSTART:voelliger-unsinn")).beginn == ""


# --- Die Antwort ---------------------------------------------------------- #


@pytest.mark.parametrize(
    "antwort,partstat",
    [("zusage", "ACCEPTED"), ("vorbehalt", "TENTATIVE"), ("absage", "DECLINED")],
)
def test_die_antwort_traegt_den_richtigen_stand(antwort, partstat):
    termin = kalender.lesen(
        _ics("UID:13@example.org", "SUMMARY:Besprechung", "SEQUENCE:2",
             "ORGANIZER:mailto:chef@example.org")
    )
    ics = kalender.antwort_bauen(
        termin, kalender.Person("Ich Selbst", "ich@example.com"), antwort,
        datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert "METHOD:REPLY" in ics
    assert f"PARTSTAT={partstat}" in ics
    assert "UID:13@example.org" in ics
    # ⚠️ Ohne die Folgenummer hält der Einladende die Antwort für eine auf eine
    # ältere Fassung.
    assert "SEQUENCE:2" in ics
    assert "ORGANIZER:mailto:chef@example.org" in ics


def test_die_antwort_spricht_nur_fuer_mich():
    """⚠️ Eine Antwort mit allen Teilnehmern behauptet, für alle zu sprechen —
    und manche Server übernehmen das sogar."""
    termin = kalender.lesen(
        _ics(
            "UID:14@example.org",
            "ATTENDEE:mailto:anna@example.org",
            "ATTENDEE:mailto:bert@example.org",
            "ATTENDEE:mailto:ich@example.com",
        )
    )
    ics = kalender.antwort_bauen(
        termin, kalender.Person("", "ich@example.com"), "zusage",
        datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert ics.count("ATTENDEE") == 1
    assert "anna@example.org" not in ics
    assert "ich@example.com" in ics


def test_die_antwort_hat_die_zeilenenden_der_norm():
    """⚠️ RFC 5545 verlangt CRLF. Manche Kalender werfen alles andere weg."""
    termin = kalender.lesen(_ics("UID:15@example.org"))
    ics = kalender.antwort_bauen(
        termin, kalender.Person("", "ich@example.com"), "zusage",
        datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert "\r\n" in ics
    assert not ics.replace("\r\n", "").count("\n")


def test_ein_komma_im_namen_bricht_die_antwort_nicht():
    termin = kalender.lesen(_ics("UID:16@example.org", "SUMMARY:Treffen mit Meier\\, Schulze"))
    ics = kalender.antwort_bauen(
        termin, kalender.Person("Ich; der Erste", "ich@example.com"), "zusage",
        datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert "SUMMARY:Treffen mit Meier\\, Schulze" in ics
    assert "Ich\\; der Erste" in ics


# --- Der ganze Weg durch die Anwendung ------------------------------------ #


def _mail_mit_einladung(klient, ics: str, dateiname: str = "einladung.ics",
                        mime: str = "text/calendar; method=REQUEST") -> int:
    """Eine Mail mit einer ``.ics`` im Anhang — samt Blob auf der Platte."""
    from datetime import datetime as dt

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Anhang, Nachricht, Ordner
    from test_konten import _eingabe

    konto_id = klient.post("/api/konten", json=_eingabe("termin@beispiel.example")).json()["id"]
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        nachricht = Nachricht(
            benutzer_id=posteingang.konto.benutzer_id,
            konto_id=konto_id,
            ordner_id=posteingang.id,
            uid=1,
            betreff="Einladung",
            von_adresse="chef@example.org",
            datum=dt(2026, 9, 3, 8, 0, tzinfo=timezone.utc),
            koerper_html="<p>Bitte kommen.</p>",
            koerper_geholt=dt.now(timezone.utc),
        )
        db.add(nachricht)
        db.flush()

        roh = ics.encode()
        ordner = get_settings().blob_dir
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / "icsblob").write_bytes(roh)
        db.add(
            Anhang(
                nachricht_id=nachricht.id,
                dateiname=dateiname,
                mime=mime,
                groesse=len(roh),
                blob_hash="icsblob",
            )
        )
        db.commit()
        return nachricht.id


def test_die_einladung_kommt_bei_der_oberflaeche_an(klient, ohne_netz):
    from conftest import einrichten

    einrichten(klient)
    kennung = _mail_mit_einladung(
        klient,
        _ics("UID:20@example.org", "SUMMARY:Quartalsrunde", "LOCATION:Halle 3",
             "DTSTART:20260910T080000Z", "DTEND:20260910T093000Z",
             "ORGANIZER;CN=Chefin:mailto:chefin@example.org"),
    )
    daten = klient.get(f"/api/termine/{kennung}").json()
    assert daten["titel"] == "Quartalsrunde"
    assert daten["ort"] == "Halle 3"
    assert daten["organisator"]["adresse"] == "chefin@example.org"
    assert daten["antwort"] == ""


def test_eine_mail_ohne_einladung_gibt_nichts(klient, ohne_netz):
    from datetime import datetime as dt

    from app.db import SessionLocal
    from app.models import Nachricht, Ordner
    from conftest import einrichten
    from test_konten import _eingabe

    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("ohne@beispiel.example")).json()["id"]
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        n = Nachricht(
            benutzer_id=posteingang.konto.benutzer_id, konto_id=konto_id,
            ordner_id=posteingang.id, uid=1, betreff="Nur Text",
            von_adresse="wer@example.org",
            datum=dt(2026, 9, 3, 8, tzinfo=timezone.utc),
            koerper_geholt=dt.now(timezone.utc),
        )
        db.add(n)
        db.commit()
        kennung = n.id
    assert klient.get(f"/api/termine/{kennung}").json() is None


def test_antworten_merkt_sich_und_verschickt(klient, ohne_netz):
    """⚠️ Die Folge zählt: gemerkt UND eine Mail in der Warteschlange."""
    from app.db import SessionLocal
    from app.models import Ausgang
    from conftest import einrichten

    einrichten(klient)
    kennung = _mail_mit_einladung(
        klient,
        _ics("UID:21@example.org", "SUMMARY:Quartalsrunde", "SEQUENCE:3",
             "ORGANIZER:mailto:chefin@example.org"),
    )

    daten = klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "vorbehalt"}).json()
    assert daten["antwort"] == "vorbehalt"
    assert daten["antwort_am"]

    with SessionLocal() as db:
        ausgang = db.query(Ausgang).all()
        assert len(ausgang) == 1
        assert ausgang[0].betreff == "Mit Vorbehalt: Quartalsrunde"
        # ⚠️ An den Einladenden, nicht an alle Teilnehmer.
        assert "chefin@example.org" in ausgang[0].an_json


def test_umentscheiden_ueberschreibt_die_antwort(klient, ohne_netz):
    from conftest import einrichten

    einrichten(klient)
    kennung = _mail_mit_einladung(
        klient, _ics("UID:22@example.org", "SUMMARY:Runde", "ORGANIZER:mailto:chefin@example.org")
    )
    klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage"})
    daten = klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "absage"}).json()
    assert daten["antwort"] == "absage"


def test_ohne_einladenden_geht_keine_antwort(klient, ohne_netz):
    """Eine Antwort ohne Empfänger wäre eine Mail ins Nichts."""
    from conftest import einrichten

    einrichten(klient)
    kennung = _mail_mit_einladung(klient, _ics("UID:23@example.org", "SUMMARY:Runde"))
    antwort = klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "termin_ohne_einladenden"


def test_eine_erfundene_antwort_wird_abgewiesen(klient, ohne_netz):
    from conftest import einrichten

    einrichten(klient)
    kennung = _mail_mit_einladung(
        klient, _ics("UID:24@example.org", "ORGANIZER:mailto:chefin@example.org")
    )
    antwort = klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "vielleicht-mal"})
    assert antwort.status_code == 400


def test_fremde_post_bleibt_zu(klient, zweiter_klient, db, ohne_netz):
    from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

    einrichten(klient)
    kennung = _mail_mit_einladung(
        klient, _ics("UID:25@example.org", "ORGANIZER:mailto:chefin@example.org")
    )
    person, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, person.benutzername, "auch-geheim-456", geheimnis)
    assert zweiter_klient.get(f"/api/termine/{kennung}").status_code == 404


def test_ein_alarm_ueberschreibt_die_beschreibung_nicht():
    """⚠️ **Ein ``VEVENT`` enthält andere Bestandteile.**

    Ein ``VALARM`` trägt ein eigenes ``DESCRIPTION`` („Erinnerung"), oft auch
    ein ``SUMMARY``. Wer die Verschachtelung nicht verfolgt, schreibt die
    Erinnerung als Beschreibung des Termins in die Karte — am 03.09.2026 an
    einer echten Einladung gesehen. Dieselbe Falle wie in ``vevent.py``, nur
    im zweiten Leser.
    """
    roh = _ics(
        "UID:a@example.com",
        "SUMMARY:Quartalsbesprechung",
        "DESCRIPTION:Zahlen zum dritten Quartal.",
        "DTSTART:20260917T120000Z",
        "DTEND:20260917T133000Z",
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "ACTION:DISPLAY",
        "SUMMARY:Gleich geht es los",
        "DESCRIPTION:Erinnerung",
        "END:VALARM",
    )

    termin = kalender.lesen(roh)

    assert termin is not None
    assert termin.titel == "Quartalsbesprechung"
    assert termin.beschreibung == "Zahlen zum dritten Quartal."


def test_nach_dem_alarm_wird_weitergelesen():
    """Die Gegenprobe: Das Überspringen darf nicht den Rest verschlucken —
    sonst fehlten Ort und Teilnehmer, die hinter dem Alarm stehen."""
    roh = _ics(
        "UID:a@example.com",
        "SUMMARY:Quartalsbesprechung",
        "DTSTART:20260917T120000Z",
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "END:VALARM",
        "LOCATION:Halle 3",
        "ATTENDEE;CN=Jan:mailto:jan@example.com",
    )

    termin = kalender.lesen(roh)

    assert termin is not None
    assert termin.ort == "Halle 3"
    assert [t.adresse for t in termin.teilnehmer] == ["jan@example.com"]
