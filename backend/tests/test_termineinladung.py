"""Einladungen verschicken.

⚠️ **Die zweite Stelle, an der nexmail von sich aus Post an Fremde schickt** —
die erste ist die Abwesenheitsnotiz. Entsprechend steht hier mehr Vorsicht als
Funktion, und die Tests halten genau die fest.

⚠️ **Nichts hier geht ins Netz.** Der Versand landet in der Warteschlange; ob
sie abgearbeitet wird, ist Sache von ``test_verfassen.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.models import Ausgang, Benutzer, Kalender, Termin
from app.services import termineinladung as dienst
from test_abgleich import konto  # noqa: F401 - Fixture


@pytest.fixture
def welt(klient, db, konto):  # noqa: F811
    # ⚠️ konto richtet schon ein; ein zweites Mal antwortet der Server mit
    # 404, weil der Weg nach der Ersteinrichtung zu ist.
    person = db.query(Benutzer).one()
    kalender = Kalender(benutzer_id=person.id, name="Privat", farbe=1)
    db.add(kalender)
    db.commit()
    return person, kalender, konto


def _termin(db, person, kalender, **kw):
    vorgabe = dict(
        kalender_id=kalender.id,
        benutzer_id=person.id,
        uid="probe@nexmail",
        titel="Quartalsrunde",
        ort="Zimmer 3",
        beschreibung="Unterlagen mitbringen",
        beginn=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
        ganztaegig=False,
        zeitzone="Europe/Berlin",
        organisator=json.dumps({"name": "Vera Beispiel", "adresse": "anna@icloud.example"}),
        teilnehmer=json.dumps(
            [{"name": "", "adresse": "anja@example.org", "antwort": "NEEDS-ACTION"}]
        ),
    )
    vorgabe.update(kw)
    termin = Termin(**vorgabe)
    db.add(termin)
    db.commit()
    return termin


def test_die_einladung_landet_in_der_warteschlange(db, welt):
    person, kalender, _ = welt
    termin = _termin(db, person, kalender)

    assert dienst.versenden(db, person, termin) == 1

    zeile = db.query(Ausgang).one()
    roh = dienst.sendedienst._datei(zeile.id).read_bytes().decode("utf-8", "replace")
    assert "METHOD:REQUEST" in roh
    assert "ATTENDEE" in roh
    assert "anja@example.org" in json.loads(zeile.an_json)


def test_die_mail_traegt_die_methode_am_medientyp(db, welt):
    """⚠️ Ohne ``method=REQUEST`` am ``text/calendar`` halten Outlook und
    Google die Einladung für einen beliebigen Anhang und zeigen keine
    Zusagen-Knöpfe."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender)
    dienst.versenden(db, person, termin)

    zeile = db.query(Ausgang).one()
    roh = dienst.sendedienst._datei(zeile.id).read_bytes().decode("utf-8", "replace")
    assert 'method="REQUEST"' in roh or "method=REQUEST" in roh


def test_auch_ein_empfaenger_ohne_kalender_sieht_etwas(db, welt):
    """⚠️ Der Kalenderteil steht NEBEN dem Text. Wer ihn nicht versteht, sähe
    sonst eine leere Mail.

    ⚠️ **Geprüft wird der Textteil, nicht die ganze Mail.** Der erste Anlauf
    suchte den Titel irgendwo in den Bytes — und der steht auch im ``SUMMARY``
    der ``.ics``. Der Test war grün, während der Text fehlte.
    """
    from email import message_from_bytes
    from email.policy import default as standard

    person, kalender, _ = welt
    termin = _termin(db, person, kalender)
    dienst.versenden(db, person, termin)

    zeile = db.query(Ausgang).one()
    mail = message_from_bytes(
        dienst.sendedienst._datei(zeile.id).read_bytes(), policy=standard
    )
    nur_text = [
        t.get_content() for t in mail.walk() if t.get_content_type() == "text/plain"
    ]
    assert nur_text, "Die Mail hat gar keinen Textteil."
    zusammen = chr(10).join(nur_text)
    assert "Quartalsrunde" in zusammen
    assert "Zimmer 3" in zusammen


def test_ohne_teilnehmer_geht_nichts_hinaus(db, welt):
    person, kalender, _ = welt
    termin = _termin(db, person, kalender, teilnehmer="")
    with pytest.raises(dienst.EinladungFehler) as f:
        dienst.versenden(db, person, termin)
    assert f.value.kennung == "einladung_ohne_teilnehmer"
    assert db.query(Ausgang).count() == 0


def test_eine_fremde_absenderadresse_wird_abgewiesen(db, welt):
    """⚠️ **Die sicherheitsrelevante Zusicherung.** Der Organisator kommt aus
    dem Termin, und der kommt aus der Oberfläche. Ohne Prüfung verschickte
    nexmail Einladungen unter jeder Adresse."""
    person, kalender, _ = welt
    termin = _termin(
        db, person, kalender, organisator=json.dumps({"adresse": "chef@fremde.example"})
    )
    with pytest.raises(dienst.EinladungFehler) as f:
        dienst.versenden(db, person, termin)
    assert f.value.kennung == "einladung_absender_unbekannt"
    assert db.query(Ausgang).count() == 0


def test_ohne_absender_geht_nichts_hinaus(db, welt):
    person, kalender, _ = welt
    termin = _termin(db, person, kalender, organisator="")
    with pytest.raises(dienst.EinladungFehler) as f:
        dienst.versenden(db, person, termin)
    assert f.value.kennung == "einladung_ohne_absender"


def test_die_erste_einladung_behaelt_ihre_nummer(db, welt):
    """⚠️ Mit Hochzählen schon beim ersten Mal wäre sie die „Aktualisierung"
    eines Termins, den niemand kennt."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender, sequenz=0)
    dienst.versenden(db, person, termin)
    assert termin.sequenz == 0
    assert termin.eingeladen_am is not None


def test_jede_weitere_zaehlt_hoch(db, welt):
    """⚠️ Ohne das halten Outlook und Google die zweite Einladung für eine
    Wiederholung der ersten und zeigen die Änderung gar nicht an."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender, sequenz=0)
    dienst.versenden(db, person, termin)
    dienst.versenden(db, person, termin)
    assert termin.sequenz == 1
    assert db.query(Ausgang).count() == 2


def test_eine_mail_an_alle_statt_einer_je_person(db, welt):
    """⚠️ Wer einzeln verschickt, zeigt jedem eine Einladung ohne
    Mitwissende — im Mailkopf sieht dann niemand, wer noch gefragt wurde."""
    person, kalender, _ = welt
    termin = _termin(
        db,
        person,
        kalender,
        teilnehmer=json.dumps(
            [
                {"name": "", "adresse": "anja@example.org", "antwort": ""},
                {"name": "", "adresse": "jan@example.org", "antwort": ""},
            ]
        ),
    )
    assert dienst.versenden(db, person, termin) == 2
    assert db.query(Ausgang).count() == 1

    # ⚠️ **Geprüft werden die Empfänger der Mail, nicht der Rückgabewert.** Der
    # kommt aus der Eingabe und stimmt auch dann, wenn nur einer angeschrieben
    # wurde — der erste Anlauf lief genau daran vorbei.
    zeile = db.query(Ausgang).one()
    assert sorted(json.loads(zeile.an_json)) == ["anja@example.org", "jan@example.org"]


# --- Die Absage -------------------------------------------------------- #


def test_die_absage_traegt_methode_und_status(db, welt):
    """⚠️ **Beides, nicht eines.** Manche Kalender streichen den Termin erst
    bei ``STATUS:CANCELLED``, andere achten nur auf ``METHOD:CANCEL``."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender, eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc))

    assert dienst.absagen(db, person, termin) == 1

    zeile = db.query(Ausgang).one()
    roh = dienst.sendedienst._datei(zeile.id).read_bytes().decode("utf-8", "replace")
    assert "METHOD:CANCEL" in roh
    assert "STATUS:CANCELLED" in roh
    assert "method=cancel" in roh.lower().replace('"', "")


def test_die_absage_zaehlt_hoch(db, welt):
    """⚠️ Ohne hoehere Nummer haelt die Gegenstelle die Absage fuer veraltet
    und laesst den Termin stehen."""
    person, kalender, _ = welt
    termin = _termin(
        db, person, kalender, sequenz=3, eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )

    dienst.absagen(db, person, termin)

    assert termin.sequenz == 4
    zeile = db.query(Ausgang).one()
    roh = dienst.sendedienst._datei(zeile.id).read_bytes().decode("utf-8", "replace")
    assert "SEQUENCE:4" in roh


def test_wer_nie_eingeladen_wurde_bekommt_keine_absage(db, welt):
    """⚠️ Sonst erfaehrt jemand von einem Termin erst dadurch, dass er
    ausfaellt."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender)  # eingeladen_am bleibt None

    assert dienst.absagen(db, person, termin) == 0
    assert db.query(Ausgang).count() == 0


def test_ohne_teilnehmer_geht_keine_absage_hinaus(db, welt):
    person, kalender, _ = welt
    termin = _termin(
        db,
        person,
        kalender,
        teilnehmer="[]",
        eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )

    assert dienst.absagen(db, person, termin) == 0
    assert db.query(Ausgang).count() == 0


def test_die_absage_nennt_den_termin_im_text(db, welt):
    """⚠️ Wer den Kalenderteil nicht versteht, saehe sonst eine leere Mail und
    wuesste nicht, was ausfaellt."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender, eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc))
    dienst.absagen(db, person, termin)

    zeile = db.query(Ausgang).one()
    roh = dienst.sendedienst._datei(zeile.id).read_bytes()
    from email import message_from_bytes
    from email.policy import default as regelwerk

    mail = message_from_bytes(roh, policy=regelwerk)
    text = ""
    for teil in mail.walk():
        if teil.get_content_type() == "text/plain":
            text = teil.get_content()
            break
    # ⚠️ Im Text, nicht irgendwo in der Mail — der Titel steht auch in der ics.
    assert "Quartalsrunde" in text
    assert "cancelled" in text.lower()


def test_eine_fremde_absenderadresse_wird_auch_bei_der_absage_abgewiesen(db, welt):
    person, kalender, _ = welt
    termin = _termin(
        db,
        person,
        kalender,
        organisator=json.dumps({"name": "", "adresse": "fremd@example.net"}),
        eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )

    with pytest.raises(dienst.EinladungFehler):
        dienst.absagen(db, person, termin)


# --- Die Zeitangabe im Textteil ---------------------------------------- #
#
# ⚠️ **Am 04.09.2026 an einer echten Einladung aufgefallen**, nicht hier: In
# der Mail stand „When: 2026-09-08 08:30 - 09:15 ()" — die Zeit in UTC und
# eine leere Klammer, wo die Zone stehen sollte. Der Kalenderteil daneben war
# richtig; nur wer keine Kalender-App hat, las die falsche Uhrzeit.


def _zone_setzen(db, name: str) -> None:
    from app.db import einstellung_schreiben
    from app.routers.einstellungen import SCHLUESSEL_ZEITZONE

    einstellung_schreiben(db, SCHLUESSEL_ZEITZONE, name)


def _textteil(db) -> str:
    from email import message_from_bytes
    from email.policy import default as regelwerk

    zeile = db.query(Ausgang).one()
    mail = message_from_bytes(
        dienst.sendedienst._datei(zeile.id).read_bytes(), policy=regelwerk
    )
    for teil in mail.walk():
        if teil.get_content_type() == "text/plain":
            return teil.get_content()
    return ""


def test_die_zeit_steht_in_der_eingestellten_zone(db, welt):
    person, kalender, _ = welt
    _zone_setzen(db, "Europe/Berlin")
    # 08:30 UTC ist 10:30 in Berlin — die Uhrzeit, die jemand eingetragen hat.
    termin = _termin(
        db,
        person,
        kalender,
        beginn=datetime(2026, 9, 8, 8, 30, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 8, 9, 15, tzinfo=timezone.utc),
        zeitzone="",
    )
    dienst.versenden(db, person, termin)

    text = _textteil(db)
    assert "When: 2026-09-08 10:30 - 11:15 (Europe/Berlin)" in text
    # ⚠️ Und die rohe UTC-Zeit steht nirgends mehr da.
    assert "08:30" not in text


def test_ohne_zone_steht_nicht_eine_leere_klammer_da(db, welt):
    """⚠️ „(…)" ohne Inhalt ist schlimmer als „(UTC)": Es sieht aus, als sei
    die Zone die des Lesers."""
    person, kalender, _ = welt
    _zone_setzen(db, "")
    termin = _termin(db, person, kalender, zeitzone="")
    dienst.versenden(db, person, termin)

    text = _textteil(db)
    assert "()" not in text
    assert "(UTC)" in text


def test_die_zone_des_termins_geht_vor(db, welt):
    """Ein uebernommener Termin bringt seine eigene Zone mit."""
    person, kalender, _ = welt
    _zone_setzen(db, "Europe/Berlin")
    termin = _termin(
        db,
        person,
        kalender,
        beginn=datetime(2026, 9, 8, 8, 30, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 8, 9, 15, tzinfo=timezone.utc),
        zeitzone="America/New_York",
    )
    dienst.versenden(db, person, termin)
    assert "When: 2026-09-08 04:30 - 05:15 (America/New_York)" in _textteil(db)


def test_ein_ganztaegiger_termin_nennt_keine_uhrzeit(db, welt):
    """⚠️ Sonst stuende dort „00:00 - 00:00"."""
    person, kalender, _ = welt
    _zone_setzen(db, "Europe/Berlin")
    termin = _termin(
        db,
        person,
        kalender,
        ganztaegig=True,
        beginn=datetime(2026, 9, 8, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 9, tzinfo=timezone.utc),
        zeitzone="UTC",
    )
    dienst.versenden(db, person, termin)

    text = _textteil(db)
    assert "When: 2026-09-08 (all day)" in text
    assert "00:00" not in text


def test_die_absage_nennt_die_zeit_genauso(db, welt):
    person, kalender, _ = welt
    _zone_setzen(db, "Europe/Berlin")
    termin = _termin(
        db,
        person,
        kalender,
        beginn=datetime(2026, 9, 8, 8, 30, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 8, 9, 15, tzinfo=timezone.utc),
        zeitzone="",
        eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )
    dienst.absagen(db, person, termin)

    text = _textteil(db)
    assert "2026-09-08 10:30" in text
    assert "()" not in text


# --- Wird sie auch abgeschickt? ---------------------------------------- #
#
# ⚠️ **Am 04.09.2026 an einer echten Einladung aufgefallen.** Der Dienst
# reihte nur ein. ``faellige_geplante`` sieht nur Eintraege mit ``senden_ab``,
# und das hat eine Einladung nicht — die Mail lag im Ausgang, bis jemand
# nexmail neu startete. Die Oberflaeche meldete „1 Person bekommt eine Mail",
# und niemand bekam eine. Zwanzig gruene Tests haben das nicht gemerkt, weil
# keiner ueber das Einreihen hinaussah.


def test_die_einladung_wird_gleich_hinausgeschickt(db, welt, monkeypatch):
    person, kalender, _ = welt
    termin = _termin(db, person, kalender)

    versucht = []
    monkeypatch.setattr(
        dienst.sendedienst, "versenden", lambda db_, zeile: versucht.append(zeile.id)
    )

    dienst.versenden(db, person, termin)

    assert versucht == [db.query(Ausgang).one().id]


def test_die_absage_genauso_gleich(db, welt, monkeypatch):
    person, kalender, _ = welt
    termin = _termin(
        db, person, kalender, eingeladen_am=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )

    versucht = []
    monkeypatch.setattr(
        dienst.sendedienst, "versenden", lambda db_, zeile: versucht.append(zeile.id)
    )

    dienst.absagen(db, person, termin)

    assert versucht == [db.query(Ausgang).one().id]


def test_ein_stummer_mailserver_kostet_die_einladung_nicht(db, welt, monkeypatch):
    """⚠️ Sie liegt dann im Ausgang und geht beim naechsten Versuch hinaus —
    dieselbe Zusage wie beim Verfassen."""
    person, kalender, _ = welt
    termin = _termin(db, person, kalender)

    def streikt(db_, zeile):
        raise dienst.sendedienst.SendeFehler("postausgang_nicht_erreichbar")

    monkeypatch.setattr(dienst.sendedienst, "versenden", streikt)

    # Kein Fehler nach oben, und der Termin gilt als eingeladen.
    assert dienst.versenden(db, person, termin) == 1
    assert termin.eingeladen_am is not None
    assert db.query(Ausgang).one().stand == "wartet"


def test_eine_unbekannte_zone_wird_nicht_als_zone_ausgegeben(db, welt):
    """⚠️ Outlook schickt Windows-Namen wie „W. Europe Standard Time".
    ``zeit.zone`` kennt die nicht und weicht auf UTC aus — stuende der Name
    trotzdem in der Klammer, naennte die Zeile eine Zone und zeigte eine
    andere."""
    person, kalender, _ = welt
    termin = _termin(
        db,
        person,
        kalender,
        beginn=datetime(2026, 9, 8, 8, 30, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 8, 9, 15, tzinfo=timezone.utc),
        zeitzone="W. Europe Standard Time",
    )
    dienst.versenden(db, person, termin)

    text = _textteil(db)
    assert "W. Europe Standard Time" not in text
    assert "When: 2026-09-08 08:30 - 09:15 (UTC)" in text
