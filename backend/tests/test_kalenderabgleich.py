"""Kalender mit ihrer Gegenstelle abgleichen.

⚠️ **Hier kann eine fremde Änderung spurlos verschwinden.** Wer ohne
``If-Match`` schreibt oder einen Konflikt überbügelt, löscht, was jemand am
Telefon eingetragen hat — und niemand erfährt davon.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.db import SessionLocal
from app.models import Benutzer, Kalender, Termin
from app.services import caldav, kalenderabgleich, termine
from conftest import einrichten
from test_caldav import PRIVAT, WURZEL, Server

TERMIN_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
    "UID:a@example.com\r\nSUMMARY:Elternabend\r\n"
    "DTSTART:20260907T170000Z\r\nDTEND:20260907T183000Z\r\n"
    "ATTENDEE;CN=Anja:mailto:anja@example.org\r\n"
    "BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nACTION:DISPLAY\r\nEND:VALARM\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)

REIHE_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:r@example.com\r\nSUMMARY:Reihe\r\n"
    "DTSTART:20260907T070000Z\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:r@example.com\r\nSUMMARY:Ausnahme\r\n"
    "RECURRENCE-ID:20260914T070000Z\r\nDTSTART:20260914T090000Z\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


@pytest.fixture
def welt(klient, db, monkeypatch):
    einrichten(klient)
    person = db.query(Benutzer).one()
    server = Server()

    kalender = Kalender(
        benutzer_id=person.id, name="Familie", farbe=3, art="caldav",
        herkunft="iCloud", url=PRIVAT, benutzer_name="anja",
    )
    db.add(kalender)
    db.flush()
    kalenderabgleich.passwort_schreiben(kalender, "geheim")
    db.commit()

    # ⚠️ Der Zugang bekommt den falschen Server untergeschoben — sonst ginge
    # jeder Test ins echte Netz.
    echt = kalenderabgleich.zugang

    def mit_transport(k, db=None):
        z = echt(k, db)
        z.transport = server.transport()
        return z

    monkeypatch.setattr(kalenderabgleich, "zugang", mit_transport)
    return person, kalender, server


# --- Hereinholen ---------------------------------------------------------- #


def test_ein_termin_vom_server_landet_hier(db, welt):
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)

    runde = kalenderabgleich.abgleichen(db, kalender)

    assert runde.neu == 1
    zeile = db.query(Termin).one()
    assert zeile.titel == "Elternabend"
    assert zeile.etag == "e1"
    assert zeile.beginn == datetime(2026, 9, 7, 17, tzinfo=timezone.utc)


def test_das_original_wird_aufgehoben(db, welt):
    """⚠️ **Die Rückfahrkarte.** Teilnehmer und Alarm müssen beim
    Zurückschreiben erhalten bleiben — dafür liegt das ``VEVENT`` roh dabei."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)

    zeile = db.query(Termin).one()
    assert "ATTENDEE;CN=Anja" in zeile.roh
    assert "BEGIN:VALARM" in zeile.roh


def test_eine_reihe_samt_ausnahme_aus_einer_datei(db, welt):
    """⚠️ Wer nur den ersten ``VEVENT`` liest, verliert die Ausnahmen."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/r.ics"] = ("e1", REIHE_ICS)

    kalenderabgleich.abgleichen(db, kalender)

    zeilen = db.query(Termin).all()
    assert len(zeilen) == 2
    assert {z.recurrence_id for z in zeilen} == {"", "2026-09-14T07:00:00+00:00"}


def test_unveraendert_spart_den_abruf(db, welt):
    """⚠️ Das ``ctag`` ist der Grund, warum ein Abgleich nichts kostet, wenn
    sich nichts getan hat."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)

    server.anfragen.clear()
    runde = kalenderabgleich.abgleichen(db, kalender)

    assert runde.unveraendert is True
    assert not any(a[0] == "REPORT" for a in server.anfragen)


def test_ein_geaendertes_etag_holt_neu(db, welt):
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)

    server.termine["/dav/anja/kalender/privat/a.ics"] = (
        "e2", TERMIN_ICS.replace("Elternabend", "Elternabend (verschoben)")
    )
    server.ctag = "ctag-2"
    kalenderabgleich.abgleichen(db, kalender)

    assert db.query(Termin).one().titel == "Elternabend (verschoben)"


def test_was_dort_weg_ist_ist_auch_hier_weg(db, welt):
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)
    assert db.query(Termin).count() == 1

    server.termine.clear()
    server.ctag = "ctag-2"
    runde = kalenderabgleich.abgleichen(db, kalender)

    assert runde.entfernt == 1
    assert db.query(Termin).count() == 0


def test_ein_kaputter_server_hinterlaesst_eine_kennung(db, welt):
    """⚠️ Die Kennung, nicht der Satz — die Oberfläche übersetzt."""
    person, kalender, server = welt

    def abweisen(anfrage):
        return httpx.Response(401)

    kalender.url = PRIVAT
    import app.services.kalenderabgleich as ka

    echt = ka.zugang
    ka.zugang = lambda k, db=None: caldav.Zugang(
        k.url, "a", "b", transport=httpx.MockTransport(abweisen)
    )
    try:
        kalenderabgleich.abgleichen(db, kalender)
    finally:
        ka.zugang = echt

    db.refresh(kalender)
    assert kalender.letzter_fehler == "caldav_abgewiesen"


# --- Hinausschreiben ------------------------------------------------------ #


def test_ein_neuer_termin_geht_sofort_hinaus(db, welt):
    """⚠️ Erst der Server, dann die eigene Datenbank."""
    person, kalender, server = welt

    termine.anlegen(
        db, person, kalender.id, titel="Neu hier",
        beginn=datetime(2026, 9, 8, 9, tzinfo=timezone.utc),
    )

    assert len(server.termine) == 1
    ics = next(iter(server.termine.values()))[1]
    assert "SUMMARY:Neu hier" in ics


def test_beim_aendern_bleibt_der_alarm_stehen(db, welt):
    """⚠️ **Der teuerste stille Datenverlust.** Wer beim Zurückschreiben neu
    baut, löscht dem Besitzer Alarm und Teilnehmerliste."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)
    zeile = db.query(Termin).one()

    termine.aendern(db, person, zeile.id, titel="Elternabend B")

    hinaus = server.termine["/dav/anja/kalender/privat/a.ics"][1]
    assert "SUMMARY:Elternabend B" in hinaus
    assert "ATTENDEE;CN=Anja" in hinaus
    assert "BEGIN:VALARM" in hinaus


def test_ein_konflikt_aendert_hier_NICHTS(db, welt):
    """⚠️ **Der Test, um den es geht.** Jemand hat den Termin am Telefon
    geändert; nexmail darf ihn weder dort noch hier überbügeln."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)
    zeile = db.query(Termin).one()

    # Jemand anders war schneller.
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e-neu", TERMIN_ICS)

    with pytest.raises(termine.TerminFehler) as f:
        termine.aendern(db, person, zeile.id, titel="Meine Fassung")
    assert str(f.value) == "termin_konflikt"

    db.expire_all()
    assert db.query(Termin).one().titel == "Elternabend"
    assert "Meine Fassung" not in server.termine["/dav/anja/kalender/privat/a.ics"][1]


def test_loeschen_nimmt_ihn_auch_dort_weg(db, welt):
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)
    zeile = db.query(Termin).one()

    termine.entfernen(db, person, zeile.id)

    assert server.termine == {}
    assert db.query(Termin).count() == 0


def test_der_dateiname_folgt_der_uid(db, welt):
    """So findet auch ein anderer Client den Termin wieder."""
    person, kalender, server = welt
    termin = termine.anlegen(
        db, person, kalender.id, titel="X",
        beginn=datetime(2026, 9, 8, 9, tzinfo=timezone.utc),
    )
    assert termin.href.endswith(".ics")
    assert termin.uid.split("@")[0][:8] in termin.href


# --- ICS-Abo -------------------------------------------------------------- #


def test_ein_abo_wird_ersetzt_nicht_zusammengefuehrt(db, klient, monkeypatch):
    """⚠️ Ein Abo hat kein ETag. Was aus der Datei verschwindet, ist abgesagt —
    ein Termin, der stehen bliebe, verschwände nie wieder."""
    person = db.query(Benutzer).one() if db.query(Benutzer).count() else None
    if person is None:
        einrichten(klient)
        person = db.query(Benutzer).one()

    abo = Kalender(
        benutzer_id=person.id, name="Feiertage", farbe=5, art="ics",
        url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()

    monkeypatch.setattr(
        kalenderabgleich.caldav,
        "abo_holen",
        lambda url, marke="": caldav.Abo(roh=REIHE_ICS),
    )
    kalenderabgleich.abgleichen(db, abo)
    assert db.query(Termin).count() == 2

    monkeypatch.setattr(
        kalenderabgleich.caldav,
        "abo_holen",
        lambda url, marke="": caldav.Abo(
            roh=(
                "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:r@example.com\r\n"
                "SUMMARY:Reihe\r\nDTSTART:20260907T070000Z\r\nRRULE:FREQ=WEEKLY\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n"
            )
        ),
    )
    kalenderabgleich.abgleichen(db, abo)

    assert db.query(Termin).count() == 1


def test_in_ein_abo_wird_nichts_geschrieben(db, klient, monkeypatch):
    einrichten(klient)
    person = db.query(Benutzer).one()
    abo = Kalender(
        benutzer_id=person.id, name="Feiertage", farbe=5, art="ics",
        url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()

    with pytest.raises(termine.TerminFehler) as f:
        termine.anlegen(
            db, person, abo.id, titel="Geht nicht",
            beginn=datetime(2026, 9, 8, 9, tzinfo=timezone.utc),
        )
    assert str(f.value) == "kalender_nur_lesen"


# --- Ein Kalender, der mitten im Abgleich verschwindet -------------------- #


def test_ein_geloeschter_kalender_haelt_die_runde_nicht_auf(db, welt, monkeypatch):
    """⚠️ **Der Abgleich laeuft in einem eigenen Faden.**

    Wer im selben Moment auf „Entfernen" drueckt, laesst den abschliessenden
    ``UPDATE`` auf null Zeilen laufen: ``StaleDataError``, Sitzung gesperrt —
    und ohne Zurueckrollen reisst es die ganze Runde mit, samt aller uebrigen
    Kalender. Am 03.09.2026 aus dem Betrieb gemeldet, im Protokoll stand
    „A calendar sync round failed".
    """
    person, kalender, server = welt

    zweiter = Kalender(
        benutzer_id=person.id, name="Zweiter", farbe=4, art="caldav",
        herkunft="iCloud", url=PRIVAT, benutzer_name="anja",
    )
    db.add(zweiter)
    db.flush()
    kalenderabgleich.passwort_schreiben(zweiter, "geheim")
    db.commit()

    # Der erste Kalender faellt genau dann weg, wenn er abgeglichen wird — so
    # wie ein Klick auf „Entfernen" waehrend der Takt laeuft. ⚠️ **Aus einer
    # ZWEITEN Sitzung**, denn genau das ist der Fall: Die Web-Anfrage loescht,
    # der Takt-Faden schreibt weiter.
    echt = kalenderabgleich._caldav_abgleichen
    geschlagen = kalender.id

    def dazwischenfunken(db_, k):
        raus = echt(db_, k)
        if k.id == geschlagen:
            with SessionLocal() as andere:
                andere.execute(
                    Kalender.__table__.delete().where(Kalender.__table__.c.id == geschlagen)
                )
                andere.commit()
        return raus

    monkeypatch.setattr(kalenderabgleich, "_caldav_abgleichen", dazwischenfunken)

    raus = kalenderabgleich.alle_abgleichen(db, person)

    # ⚠️ **Der zweite muss drankommen.** Genau das ging verloren.
    assert zweiter.id in raus
    # Und die Sitzung ist danach benutzbar, nicht gesperrt.
    assert db.query(Kalender).count() == 1


def test_ein_verschwundener_kalender_ist_kein_fehler(db, welt):
    """Derselbe Fall, aber am einzelnen Abgleich statt an der Runde.

    ``abgleichen`` wird auch direkt aufgerufen — beim Verbinden und über
    ``POST /api/kalender/abgleichen``. Ohne die Wache dort bekäme der Betreiber
    dann einen Serverfehler für etwas, das er selbst gerade veranlasst hat.
    """
    _, kalender, _ = welt

    with SessionLocal() as andere:
        andere.execute(Kalender.__table__.delete().where(Kalender.__table__.c.id == kalender.id))
        andere.commit()

    # Wirft nicht — und lässt die Sitzung benutzbar zurück.
    kalenderabgleich.abgleichen(db, kalender)
    assert db.query(Kalender).count() == 0


def test_eine_gesperrte_sitzung_kostet_nur_einen_kalender(db, welt, monkeypatch):
    """⚠️ **Ein Kalender, der klemmt, hält die anderen nicht auf** — auch dann
    nicht, wenn er die Sitzung gesperrt zurücklässt.

    ``StaleDataError`` ist nur der Fall, den wir kennen. Jeder gescheiterte
    Schreibvorgang sperrt die Sitzung, und dann wirft schon die nächste Abfrage.
    Zwei Vorkehrungen tragen das: die Liste wird **vorher** geholt (sonst fällt
    die Ausnahme in der ``for``-Zeile an, also außerhalb des ``try``), und nach
    einem Fehlschlag wird zurückgerollt.
    """
    person, kalender, _ = welt

    zweiter = Kalender(
        benutzer_id=person.id, name="Zweiter", farbe=4, art="caldav",
        herkunft="iCloud", url=PRIVAT, benutzer_name="anja",
    )
    db.add(zweiter)
    db.flush()
    kalenderabgleich.passwort_schreiben(zweiter, "geheim")
    db.commit()

    echt = kalenderabgleich.abgleichen
    geschlagen = kalender.id

    def sperren(db_, k):
        if k.id != geschlagen:
            return echt(db_, k)
        with SessionLocal() as andere:
            andere.execute(
                Kalender.__table__.delete().where(Kalender.__table__.c.id == geschlagen)
            )
            andere.commit()
        k.name = "weg"
        try:
            db_.commit()
        except Exception:  # noqa: BLE001
            pass  # absichtlich NICHT zurückgerollt — das macht die Runde
        raise RuntimeError("etwas ganz anderes")

    monkeypatch.setattr(kalenderabgleich, "abgleichen", sperren)

    raus = kalenderabgleich.alle_abgleichen(db, person)

    assert zweiter.id in raus


# --- Nichts zweimal verbinden --------------------------------------------- #


def test_derselbe_kalender_wird_nicht_zweimal_verbunden(db, welt):
    """⚠️ **Zweimal derselbe Kalender heisst: jeder Termin doppelt.**

    Und schlimmer: Wer dann eine der beiden Zeilen entfernt, sieht den Termin,
    den er gerade offen hatte, als „gibt es nicht mehr" — richtig gemeldet und
    trotzdem unverständlich. Am 03.09.2026 aus dem Betrieb gemeldet
    („Ich kann den google kalender auch mehrfach verbinden").
    """
    person, kalender, _ = welt

    with pytest.raises(kalenderabgleich.AbgleichFehler) as f:
        kalenderabgleich.verbinden(
            db, person,
            herkunft="iCloud",
            benutzer_name="anja",
            passwort="geheim",
            auswahl=[(kalender.url, "Familie noch mal")],
        )
    assert str(f.value) == "kalender_schon_verbunden"
    assert db.query(Kalender).count() == 1


def test_neben_dem_bekannten_wird_der_neue_verbunden(db, welt):
    """Nur das Doppel faellt weg, nicht der ganze Vorgang — sonst müsste man
    die schon verbundenen von Hand abwählen."""
    person, kalender, _ = welt

    neu = kalenderabgleich.verbinden(
        db, person,
        herkunft="iCloud",
        benutzer_name="anja",
        passwort="geheim",
        auswahl=[(kalender.url, "schon da"), ("https://dav.example.com/neu/", "Neu")],
    )

    assert [k.name for k in neu] == ["Neu"]
    assert db.query(Kalender).count() == 2


def test_ein_abo_wird_nicht_zweimal_abonniert(db, welt):
    person, _, _ = welt
    kalenderabgleich.abonnieren(
        db, person, url="https://example.com/feiertage.ics", name="Feiertage"
    )
    with pytest.raises(kalenderabgleich.AbgleichFehler) as f:
        kalenderabgleich.abonnieren(
            db, person, url="https://example.com/feiertage.ics", name="Noch mal"
        )
    assert str(f.value) == "kalender_schon_verbunden"


def test_ein_kodierter_pfad_erzeugt_kein_doppel(db, welt):
    """⚠️ **Der Fehler, der jeden neuen Termin bei der nächsten Runde
    verschwinden liess.**

    Google nimmt das ``PUT`` auf ``…/<uid>@nexmail.ics`` an und meldet denselben
    Termin danach als ``…/<uid>%40nexmail.ics``. Woertlich verglichen war das
    ein unbekannter Eintrag **und** eine verschwundene Zeile: Der Abgleich legte
    ihn neu an und loeschte den eigenen — **bei jeder Runde**, mit neuer
    Kennung. „Sobald ich aktualisieren klicke ist alles weg oder verschoben",
    am 03.09.2026 aus dem Betrieb gemeldet.
    """
    person, kalender, server = welt
    server.kodiert_zurueck = True

    termin = termine.anlegen(
        db, person, kalender.id,
        titel="Elternabend",
        beginn=datetime(2026, 9, 7, 17, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 7, 18, tzinfo=timezone.utc),
    )
    kennung = termin.id
    assert db.query(Termin).count() == 1

    # Zweimal abgleichen: Der Fehler schlug bei JEDER Runde zu.
    for _ in range(2):
        kalenderabgleich.abgleichen(db, kalender)

    uebrig = db.query(Termin).all()
    assert len(uebrig) == 1, "Der Termin wurde doppelt angelegt."
    assert uebrig[0].id == kennung, "Der Termin bekam eine neue Kennung."


# --- „Geändert" heißt geändert -------------------------------------------- #


def _abo_anlegen(db, person):
    abo = Kalender(
        benutzer_id=person.id, name="Feiertage", farbe=5, art="ics",
        url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()
    return abo


def test_ein_zweiter_lauf_meldet_keine_aenderung(db, klient, monkeypatch):
    """⚠️ **„53 geändert" ohne eine einzige Änderung ist keine Auskunft,
    sondern ein Schrecken.**

    Ein ICS-Abo wird als Ganzes ersetzt; vorher zählte deshalb jede bekannte
    Zeile als geändert — bei jedem Klick auf Aktualisieren aufs Neue. Am
    03.09.2026 aus dem Betrieb gemeldet: „Ich habe nichts geändert und das
    kommt jedes Mal wieder."
    """
    einrichten(klient)
    person = db.query(Benutzer).one()
    abo = _abo_anlegen(db, person)

    # ⚠️ Ohne Marke: Sonst spart schon der 304 die Runde, und der Zähler käme
    # gar nicht erst zum Zug. Geprüft wird hier das Zählen, nicht das Sparen.
    monkeypatch.setattr(
        kalenderabgleich.caldav, "abo_holen", lambda url, marke="": caldav.Abo(roh=TERMIN_ICS)
    )

    erste = kalenderabgleich.abgleichen(db, abo)
    assert (erste.neu, erste.geaendert) == (1, 0)

    zweite = kalenderabgleich.abgleichen(db, abo)
    assert (zweite.neu, zweite.geaendert) == (0, 0), "Nichts hat sich getan."


def test_eine_echte_aenderung_wird_gezaehlt(db, klient, monkeypatch):
    """Die Gegenprobe: Ein geänderter Titel muss ankommen — sonst hätte der
    Zähler nur gelernt zu schweigen."""
    einrichten(klient)
    person = db.query(Benutzer).one()
    abo = _abo_anlegen(db, person)

    monkeypatch.setattr(
        kalenderabgleich.caldav, "abo_holen", lambda url, marke="": caldav.Abo(roh=TERMIN_ICS)
    )
    kalenderabgleich.abgleichen(db, abo)

    monkeypatch.setattr(
        kalenderabgleich.caldav,
        "abo_holen",
        lambda url, marke="": caldav.Abo(roh=TERMIN_ICS.replace("Elternabend", "Elternabend II")),
    )
    runde = kalenderabgleich.abgleichen(db, abo)

    assert (runde.neu, runde.geaendert) == (0, 1)
    assert db.query(Termin).one().titel == "Elternabend II"


def test_ein_unveraendertes_abo_wird_gar_nicht_erst_geholt(db, klient, monkeypatch):
    """⚠️ **Erst fragen, dann holen.** Ein Abo hat kein ``ctag``; die Marke aus
    ``ETag``/``Last-Modified`` übernimmt die Rolle. Ohne sie lädt nexmail bei
    jedem Takt die ganze Datei — bei einem Feiertagskalender jede Stunde
    umsonst."""
    einrichten(klient)
    person = db.query(Benutzer).one()
    abo = _abo_anlegen(db, person)

    gefragt: list[str] = []

    def erst_voll(url, marke=""):
        gefragt.append(marke)
        if marke == '"m1"':
            return caldav.Abo(roh="", marke=marke, unveraendert=True)
        return caldav.Abo(roh=TERMIN_ICS, marke='"m1"')

    monkeypatch.setattr(kalenderabgleich.caldav, "abo_holen", erst_voll)

    kalenderabgleich.abgleichen(db, abo)
    runde = kalenderabgleich.abgleichen(db, abo)

    # Beim zweiten Mal fuhr die Marke mit, und der Server sagte „unveraendert".
    assert gefragt == ["", '"m1"']
    assert runde.unveraendert


# --- Teilnehmer: gelesen, aber nicht angefasst ---------------------------- #


TEILNEHMER_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
    "UID:t@example.com\r\nSUMMARY:Planung\r\n"
    "DTSTART:20260924T080000Z\r\nDTEND:20260924T093000Z\r\n"
    "ORGANIZER;CN=Vera Beispiel:mailto:vera@example.com\r\n"
    "ATTENDEE;CN=Anja;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:anja@example.com\r\n"
    "ATTENDEE;CN=Jan;PARTSTAT=NEEDS-ACTION:mailto:jan@example.com\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_teilnehmer_kommen_mit(db, welt):
    """⚠️ Termine aus einem verbundenen Kalender haben Teilnehmer — nexmail
    zeigte sie nicht, obwohl sie in der Rückfahrkarte lagen."""
    import json

    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/t.ics"] = ("e1", TEILNEHMER_ICS)

    kalenderabgleich.abgleichen(db, kalender)

    zeile = db.query(Termin).one()
    assert json.loads(zeile.organisator)["adresse"] == "vera@example.com"
    leute = json.loads(zeile.teilnehmer)
    assert [t["adresse"] for t in leute] == ["anja@example.com", "jan@example.com"]
    # ⚠️ Der Zusagestand gehört dazu — ohne ihn ist eine Teilnehmerliste eine
    # Namensliste, und man weiß nicht, wer kommt.
    assert [t["antwort"] for t in leute] == ["ACCEPTED", "NEEDS-ACTION"]


def test_teilnehmer_ueberleben_eine_aenderung(db, welt):
    """⚠️ **Der teuerste stille Datenverlust.** Sie stehen NICHT in ``EIGENE``:
    Wer den Titel ändert, darf die Teilnehmerliste nicht mitnehmen."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/t.ics"] = ("e1", TEILNEHMER_ICS)
    kalenderabgleich.abgleichen(db, kalender)
    zeile = db.query(Termin).one()

    termine.aendern(db, person, zeile.id, titel="Planung B")

    hinaus = server.termine["/dav/anja/kalender/privat/t.ics"][1]
    assert "SUMMARY:Planung B" in hinaus
    assert "ORGANIZER;CN=Vera Beispiel" in hinaus
    assert hinaus.count("ATTENDEE") == 2


# --- Der Konflikt: beide Fassungen zeigen --------------------------------- #
#
# ⚠️ **„Bitte erst abgleichen" ist keine Auskunft.** Es sagt nicht, was drüben
# steht, und wer es befolgt, wirft seine eigene Änderung weg, ohne sie mit der
# anderen verglichen zu haben. Bis zum 04.09.2026 war das der ganze Ausgang
# eines 412.


def _mit_konflikt(db, welt):
    """Ein Termin, den jemand woanders geändert hat — das ETag stimmt nicht."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", TERMIN_ICS)
    kalenderabgleich.abgleichen(db, kalender)
    zeile = db.query(Termin).one()

    # Jemand am Telefon: neuer Titel, neues ETag.
    server.termine["/dav/anja/kalender/privat/a.ics"] = (
        "e2",
        TERMIN_ICS.replace("SUMMARY:Elternabend", "SUMMARY:Am Telefon geaendert"),
    )
    return person, kalender, server, zeile


def test_ein_konflikt_ueberbuegelt_nichts(db, welt):
    person, kalender, server, zeile = _mit_konflikt(db, welt)

    zeile.titel = "Hier geaendert"
    with pytest.raises(caldav.Konflikt):
        kalenderabgleich.hochschieben(db, zeile)

    # Beim Server steht unverändert die fremde Fassung.
    assert "Am Telefon geaendert" in server.termine["/dav/anja/kalender/privat/a.ics"][1]


def test_die_fremde_fassung_laesst_sich_ansehen(db, welt):
    """⚠️ **Ohne etwas zu ändern.** Ansehen ist keine Entscheidung."""
    person, kalender, server, zeile = _mit_konflikt(db, welt)
    zeile.titel = "Hier geaendert"

    fremd = kalenderabgleich.fremde_fassung(db, zeile)

    assert fremd is not None
    assert fremd["titel"] == "Am Telefon geaendert"
    assert fremd["_etag"] == "e2"
    # ⚠️ Die eigene Zeile ist unberührt — sonst wäre Ansehen schon Übernehmen.
    assert zeile.titel == "Hier geaendert"


def test_ein_drueben_geloeschter_termin_ist_ein_anderer_fall(db, welt):
    """⚠️ Sonst sähe „gelöscht" aus wie „unverändert", und die Oberfläche böte
    an, eine Fassung zu übernehmen, die es nicht gibt."""
    person, kalender, server, zeile = _mit_konflikt(db, welt)
    server.termine.clear()

    assert kalenderabgleich.fremde_fassung(db, zeile) is None


def test_die_fremde_fassung_uebernehmen_wirft_die_eigene_weg(db, welt):
    person, kalender, server, zeile = _mit_konflikt(db, welt)
    zeile.titel = "Hier geaendert"
    # ⚠️ **Wirklich schmutzig, nicht nur behauptet.** So steht die Zeile nach
    # einem gescheiterten Hochschieben da; ohne das prüft der Test einen Wert,
    # der ohnehin schon falsch ist, und die Mutationsprobe läuft durch.
    zeile.schmutzig = True
    db.commit()

    assert kalenderabgleich.fremde_fassung_uebernehmen(db, zeile) is True

    db.refresh(zeile)
    assert zeile.titel == "Am Telefon geaendert"
    assert zeile.etag == "e2"
    # ⚠️ Und sie gilt als sauber — sonst schöbe der nächste Takt sie hoch.
    assert zeile.schmutzig is False


def test_meine_fassung_gewinnt_erst_nach_dem_frischmachen(db, welt):
    """⚠️ **Die Kette, auf der Punkt 6 steht.** Ohne das frische ETag scheitert
    auch der zweite Anlauf mit 412 — und der Mensch hat entschieden, ohne dass
    es etwas ändert."""
    person, kalender, server, zeile = _mit_konflikt(db, welt)
    zeile.titel = "Hier geaendert"

    assert kalenderabgleich.frisch_machen(db, zeile) is True
    kalenderabgleich.hochschieben(db, zeile)

    beim_server = server.termine["/dav/anja/kalender/privat/a.ics"][1]
    assert "SUMMARY:Hier geaendert" in beim_server


def test_frischmachen_holt_die_fremden_zeilen_mit(db, welt):
    """⚠️ **Nicht die alte Fassung überbügeln.** Was drüben dazukam und nexmail
    nicht verwaltet — Alarme, Teilnehmer, `X-APPLE-…` —, muss stehen bleiben;
    sonst trifft „meine Fassung gewinnt" mehr, als der Mensch entschieden hat."""
    person, kalender, server, zeile = _mit_konflikt(db, welt)
    server.termine["/dav/anja/kalender/privat/a.ics"] = (
        "e3",
        TERMIN_ICS.replace(
            "BEGIN:VALARM", "X-APPLE-SPUR:drueben-dazugekommen\r\nBEGIN:VALARM"
        ),
    )
    zeile.titel = "Hier geaendert"

    kalenderabgleich.frisch_machen(db, zeile)
    kalenderabgleich.hochschieben(db, zeile)

    beim_server = server.termine["/dav/anja/kalender/privat/a.ics"][1]
    assert "SUMMARY:Hier geaendert" in beim_server
    assert "X-APPLE-SPUR:drueben-dazugekommen" in beim_server


def test_aus_einer_reihe_wird_der_richtige_termin_gelesen(db, welt):
    """⚠️ **Eine Datei kann mehrere ``VEVENT`` enthalten** — eine Reihe samt
    ihren Ausnahmen. Wer den ersten nimmt, zeigt beim Konflikt die falsche
    Fassung, und der Mensch entscheidet über etwas anderes, als er sieht."""
    person, kalender, server = welt
    server.termine["/dav/anja/kalender/privat/r.ics"] = ("e1", REIHE_ICS)
    kalenderabgleich.abgleichen(db, kalender)

    ausnahme = db.query(Termin).filter(Termin.recurrence_id != "").one()
    assert ausnahme.titel == "Ausnahme"

    fremd = kalenderabgleich.fremde_fassung(db, ausnahme)

    assert fremd is not None
    assert fremd["titel"] == "Ausnahme"
    assert fremd["recurrence_id"] == ausnahme.recurrence_id


def test_erzwingen_macht_die_fassung_erst_frisch(db, welt):
    """⚠️ **Der ganze Weg, nicht nur sein Baustein.** ``frisch_machen`` allein
    zu prüfen sagt nichts darüber, ob ``erzwingen`` es auch ruft — und genau
    daran lief die erste Mutationsprobe vorbei."""
    person, kalender, server, zeile = _mit_konflikt(db, welt)

    raus = termine.aendern(
        db, person, zeile.id, titel="Meine Fassung gewinnt", erzwingen=True
    )

    assert raus.titel == "Meine Fassung gewinnt"
    beim_server = server.termine["/dav/anja/kalender/privat/a.ics"][1]
    assert "SUMMARY:Meine Fassung gewinnt" in beim_server


def test_ohne_erzwingen_bleibt_der_konflikt_stehen(db, welt):
    """Die Gegenprobe: Ohne die Entscheidung wird nichts überbügelt."""
    person, kalender, server, zeile = _mit_konflikt(db, welt)

    with pytest.raises(termine.TerminFehler) as f:
        termine.aendern(db, person, zeile.id, titel="Heimlich")
    assert f.value.kennung == "termin_konflikt"
    assert "Am Telefon geaendert" in server.termine["/dav/anja/kalender/privat/a.ics"][1]
