"""Erinnerungen — was fällig ist, und was genau einmal fällig ist.

⚠️ **Hier kann eine Erinnerung still ausbleiben oder im Kreis läuten.** Beides
sieht man erst im Betrieb: das eine, weil nichts passiert, das andere, weil man
es wegklickt und es wiederkommt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Benutzer, Erinnerungszustellung, Termin
from app.services import erinnerungen, termine
from conftest import einrichten

JETZT = datetime(2026, 9, 17, 13, 45, tzinfo=timezone.utc)


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    kalender = termine.kalender_anlegen(db, person, "Privat")
    return person, kalender


def _termin(db, person, kalender, **kw):
    daten = dict(
        titel="Quartalsbesprechung",
        beginn=datetime(2026, 9, 17, 14, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 17, 15, tzinfo=timezone.utc),
        erinnerung=15,
    )
    daten.update(kw)
    return termine.anlegen(db, person, kalender.id, **daten)


# --- Fällig oder nicht ---------------------------------------------------- #


def test_fuenfzehn_minuten_vorher_ist_faellig(db, welt):
    person, kalender = welt
    _termin(db, person, kalender)

    raus = erinnerungen.faellige(db, person, jetzt=JETZT)

    assert [f.titel for f in raus] == ["Quartalsbesprechung"]
    assert raus[0].vorlauf == 15


def test_vorher_ist_noch_nichts_faellig(db, welt):
    """⚠️ Eine Erinnerung, die zu früh kommt, ist keine."""
    person, kalender = welt
    _termin(db, person, kalender)

    assert erinnerungen.faellige(db, person, jetzt=JETZT - timedelta(minutes=5)) == []


def test_ohne_erinnerung_kommt_nichts(db, welt):
    person, kalender = welt
    _termin(db, person, kalender, erinnerung=-1)

    assert erinnerungen.faellige(db, person, jetzt=JETZT) == []


def test_ein_alter_termin_laeutet_nicht_nach(db, welt):
    """⚠️ Wer nexmail nach zwei Wochen öffnet, will nicht vierzehn Wecker."""
    person, kalender = welt
    _termin(db, person, kalender)

    spaeter = JETZT + timedelta(days=3)
    assert erinnerungen.faellige(db, person, jetzt=spaeter) == []


# --- Genau einmal --------------------------------------------------------- #


def test_ein_zeigender_kanal_behaelt_sie_bis_zum_handeln(db, welt):
    """⚠️ **Ein Fenster zeigt, ein Push feuert.**

    Die Oberfläche fragt im Takt nach und lädt zwischendurch auch mal neu. Wer
    dann seine Erinnerung nicht mehr fände, hätte sie verloren, ohne sie je
    weggeklickt zu haben.
    """
    person, kalender = welt
    _termin(db, person, kalender)

    erste = erinnerungen.faellige(db, person, jetzt=JETZT)
    zweite = erinnerungen.faellige(db, person, jetzt=JETZT + timedelta(seconds=30))

    assert len(erste) == 1
    assert [f.id for f in zweite] == [f.id for f in erste]


def test_ein_feuernder_kanal_bekommt_sie_genau_einmal(db, welt):
    """Die andere Haltung: Ein zweites Mal wäre eine zweite Benachrichtigung
    auf dem Telefon. Der Kanal steht heute noch nicht, die Regel schon."""
    person, kalender = welt
    _termin(db, person, kalender)

    erste = erinnerungen.faellige(db, person, jetzt=JETZT, kanal="push", nur_einmal=True)
    zweite = erinnerungen.faellige(
        db, person, jetzt=JETZT + timedelta(seconds=30), kanal="push", nur_einmal=True
    )

    assert len(erste) == 1
    assert zweite == []


def test_weggeklickt_bleibt_weg(db, welt):
    person, kalender = welt
    _termin(db, person, kalender)
    faellig = erinnerungen.faellige(db, person, jetzt=JETZT)[0]

    erinnerungen.erledigt(db, person, faellig.id)

    assert erinnerungen.faellige(db, person, jetzt=JETZT + timedelta(minutes=1)) == []


def test_geschlummert_kommt_wieder(db, welt):
    """Schlummern ist nicht Wegklicken — sonst wäre es dasselbe."""
    person, kalender = welt
    _termin(db, person, kalender)
    faellig = erinnerungen.faellige(db, person, jetzt=JETZT)[0]

    erinnerungen.schlummern(db, person, faellig.id, 5, jetzt=JETZT)

    # Innerhalb der Schlummerzeit: Ruhe.
    assert erinnerungen.faellige(db, person, jetzt=JETZT + timedelta(minutes=2)) == []
    # Danach wieder da.
    spaeter = erinnerungen.faellige(db, person, jetzt=JETZT + timedelta(minutes=6))
    assert [f.titel for f in spaeter] == ["Quartalsbesprechung"]


def test_ein_erfundenes_schlummern_wird_abgewiesen(db, welt):
    person, kalender = welt
    _termin(db, person, kalender)
    faellig = erinnerungen.faellige(db, person, jetzt=JETZT)[0]

    with pytest.raises(erinnerungen.ErinnerungFehler) as f:
        erinnerungen.schlummern(db, person, faellig.id, 3)
    assert str(f.value) == "schlummer_unbekannt"


# --- Wiederholungen ------------------------------------------------------- #


def test_eine_reihe_erinnert_bei_jedem_vorkommen(db, welt):
    """⚠️ **Je Vorkommen, nicht je Termin.** Eine wöchentliche Besprechung
    erinnerte sonst genau einmal — und danach nie wieder."""
    person, kalender = welt
    _termin(db, person, kalender, rrule="FREQ=WEEKLY")

    erste = erinnerungen.faellige(db, person, jetzt=JETZT)
    assert len(erste) == 1

    naechste_woche = JETZT + timedelta(days=7)
    zweite = erinnerungen.faellige(db, person, jetzt=naechste_woche)
    assert len(zweite) == 1, "Das zweite Vorkommen fehlt."
    assert zweite[0].id != erste[0].id, "Es ist dieselbe Zustellung wie letzte Woche."


def test_ein_weggeklicktes_vorkommen_stumm_das_naechste_nicht(db, welt):
    person, kalender = welt
    _termin(db, person, kalender, rrule="FREQ=WEEKLY")
    erinnerungen.erledigt(db, person, erinnerungen.faellige(db, person, jetzt=JETZT)[0].id)

    naechste = erinnerungen.faellige(db, person, jetzt=JETZT + timedelta(days=7))
    assert len(naechste) == 1


# --- Der Kanal ------------------------------------------------------------ #


def test_der_kanal_gehoert_in_den_schluessel(db, welt):
    """⚠️ **Die Vorsorge, die den ganzen Bau trägt.**

    Heute gibt es einen Kanal. Ohne den Kanal im Schlüssel müsste man beim
    ersten Web-Push umbauen: Der zweite Kanal fände die Zustellung des ersten
    und schwiege.
    """
    person, kalender = welt
    _termin(db, person, kalender)

    erinnerungen.faellige(db, person, jetzt=JETZT, kanal="app")
    ueber_push = erinnerungen.faellige(db, person, jetzt=JETZT, kanal="push")

    assert len(ueber_push) == 1, "Der zweite Kanal wurde vom ersten stummgeschaltet."
    assert db.query(Erinnerungszustellung).count() == 2


def test_fremde_erinnerungen_bleiben_fremd(db, klient, welt):
    """Ein zweiter Benutzer sieht die Erinnerungen des ersten nicht."""
    from conftest import zweiten_benutzer_anlegen

    person, kalender = welt
    _termin(db, person, kalender)
    zweiter, _ = zweiten_benutzer_anlegen(db)

    assert erinnerungen.faellige(db, zweiter, jetzt=JETZT) == []


# --- Der VALARM fährt mit ------------------------------------------------- #


def test_die_erinnerung_steht_im_vevent(db, welt):
    """⚠️ **Der Alarm gehört zum Termin, nicht zur Anzeige.** Wer ihn hier
    setzt, wird auch auf dem Telefon erinnert — sonst wäre es eine Notiz, die
    nur nexmail kennt."""
    from app.services import vevent

    person, kalender = welt
    termin = _termin(db, person, kalender, erinnerung=30)

    ics = vevent.bauen(termin, JETZT)

    assert "BEGIN:VALARM" in ics
    assert "TRIGGER:-PT30M" in ics
    # ⚠️ Ohne ACTION und DESCRIPTION weisen manche Server den Termin ab.
    assert "ACTION:DISPLAY" in ics
    assert "DESCRIPTION:" in ics.split("BEGIN:VALARM", 1)[1]


def test_ohne_erinnerung_kein_valarm(db, welt):
    from app.services import vevent

    person, kalender = welt
    termin = _termin(db, person, kalender, erinnerung=-1)

    assert "BEGIN:VALARM" not in vevent.bauen(termin, JETZT)


def test_mehrere_vorkommen_kommen_in_einem_zug(db, welt):
    """⚠️ **Der Beweis, dass wirklich je Vorkommen gerechnet wird.**

    Wer nur den Beginn der Reihe nimmt, meldet genau eine Erinnerung — und der
    Test mit „nächste Woche" merkt es nicht, weil dort die Reihe eben mit dem
    nächsten Vorkommen anfängt. Eine stündliche Reihe liefert im Rückblick von
    zwölf Stunden dagegen viele auf einmal.
    """
    person, kalender = welt
    # Die Reihe laeuft schon seit fuenf Stunden — sonst liegt nur das erste
    # Vorkommen im Rueckblick, und der Test bewiese nichts.
    _termin(
        db, person, kalender,
        beginn=JETZT - timedelta(hours=5),
        ende=JETZT - timedelta(hours=4),
        rrule="FREQ=HOURLY",
    )

    raus = erinnerungen.faellige(db, person, jetzt=JETZT)

    assert len(raus) > 1, "Es kam nur ein Vorkommen."
    # Und jedes mit seiner eigenen Zustellung, sonst wäre das Wegklicken
    # des einen das Wegklicken aller.
    assert len({f.id for f in raus}) == len(raus)
