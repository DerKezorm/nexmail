"""Papierkorb und Junk leeren sich selbst — gegen den IMAP-Doppelgänger.

⚠️ **Der wichtigste Test hier ist der Posteingang.** Das Aufräumen löscht
endgültig, und die einzige Grenze ist der Rollenfilter in
``services/aufraeumen.py``. Fällt er weg, räumt es jeden Ordner — genau das
muss dieser Lauf rot zeigen, nicht ein Betreiber am nächsten Morgen.

⚠️ **Kein echter Server, kein Entwicklungs-Datenbestand.** Der Doppelgänger
datiert alle Mails auf denselben Tag; das Alter wird deshalb an den lokalen
Zeilen gesetzt, für „alt“ wie für „neu“ — der Abgleich fasst ein Datum nie
wieder an.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from app.models import Benutzer, Nachricht, Ordner, utcnow
from app.services import abgleich, aufraeumen, handeln
from test_abgleich import konto  # noqa: F401 - Fixture
from test_handeln import Server


@pytest.fixture
def welt(db, konto, monkeypatch):  # noqa: F811
    """Posteingang, Papierkorb und Junk — mit je einer alten und einer neuen Mail."""
    for pfad, rolle in (("Deleted Messages", "papierkorb"), ("Junk", "junk")):
        db.add(Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle=rolle))
    db.commit()
    db.refresh(konto)

    server = Server()
    for pfad in ("INBOX", "Deleted Messages", "Junk"):
        server.anlegen(pfad)
    for pfad, uid, betreff in (
        ("INBOX", 1, "Posteingang alt"),
        ("INBOX", 2, "Posteingang neu"),
        ("Deleted Messages", 1, "Papierkorb alt"),
        ("Deleted Messages", 2, "Papierkorb neu"),
        ("Junk", 1, "Junk alt"),
        ("Junk", 2, "Junk neu"),
    ):
        server.einwerfen(pfad, uid, betreff)

    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)
    monkeypatch.setattr(handeln.imapdienst, "verbinden", lambda *a, **k: server)

    for ordner in konto.ordner:
        abgleich.ordner_abgleichen(server, db, konto, ordner)

    alt = utcnow() - timedelta(days=30)
    for betreff in ("Posteingang alt", "Papierkorb alt", "Junk alt"):
        zeile = db.query(Nachricht).filter(Nachricht.betreff == betreff).one()
        zeile.datum = alt
        # ⚠️ Der Papierkorb misst die **Verweildauer** (``angekommen``), nicht
        # das Absendedatum — eine alte Mail gilt dort erst als alt, wenn sie
        # lange genug drinliegt. Der Posteingang bekommt beides, damit der
        # Rollenfilter-Test gegen die strengste Lesart steht.
        zeile.angekommen = alt
    # ⚠️ Die neuen Zeilen bekommen ihr Datum ebenfalls hier. Der Doppelgänger
    # datiert fest auf einen Tag (test_abgleich.Server), und am siebten Tag
    # danach war „neu“ älter als die Aufbewahrung: Am 06.09.2026 um 12:00 UTC
    # kippten zwei Tests von selbst, ohne dass jemand etwas geändert hatte.
    frisch = utcnow()
    for betreff in ("Posteingang neu", "Papierkorb neu", "Junk neu"):
        zeile = db.query(Nachricht).filter(Nachricht.betreff == betreff).one()
        zeile.datum = frisch
    db.commit()
    return server, konto


def _person(db) -> Benutzer:
    return db.query(Benutzer).one()


def _betreffe(db, ordner: Ordner) -> list[str]:
    return sorted(n.betreff for n in db.query(Nachricht).filter_by(ordner_id=ordner.id))


def _ordner(konto, rolle: str) -> Ordner:  # noqa: F811
    return next(o for o in konto.ordner if o.rolle == rolle)


def test_bei_null_passiert_nichts(db, welt):
    """⚠️ Die Vorgabe ist aus — ohne Einstellung wird nichts angefasst."""
    server, _ = welt

    stand = aufraeumen.runde()

    assert stand == {"benutzer": 0, "geloescht": 0}
    # Nicht einmal eine Verbindung: Der Doppelgänger hat keinen Befehl gesehen.
    assert server.protokoll == []
    assert db.query(Nachricht).count() == 6


def test_aeltere_verschwinden_nur_in_papierkorb_und_junk(db, welt):
    """⚠️ **Der wichtigste Test dieser Gruppe.**

    Bei 7 Tagen verschwinden nur die älteren, und nur in Papierkorb und Junk.
    Der Posteingang trägt eine genauso alte Mail — bleibt sie nicht liegen,
    ist der Rollenfilter weg, und das Aufräumen ist ein Datenvernichter.
    """
    server, konto = welt  # noqa: F811
    person = _person(db)
    person.aufraeumen_papierkorb_tage = 7
    person.aufraeumen_junk_tage = 7
    db.commit()

    stand = aufraeumen.runde()
    db.expire_all()

    assert stand["benutzer"] == 1
    assert stand["geloescht"] == 2

    # Lokal: Die alten sind weg, die neuen stehen noch.
    assert _betreffe(db, _ordner(konto, "papierkorb")) == ["Papierkorb neu"]
    assert _betreffe(db, _ordner(konto, "junk")) == ["Junk neu"]

    # Auf dem Server genauso — sonst springt beim nächsten Abgleich alles zurück.
    assert len(server.ordner["Deleted Messages"]["nachrichten"]) == 1
    assert len(server.ordner["Junk"]["nachrichten"]) == 1

    # ⚠️ Und der Posteingang ist unberührt, obwohl seine Mail genauso alt ist.
    assert _betreffe(db, _ordner(konto, "posteingang")) == [
        "Posteingang alt",
        "Posteingang neu",
    ], "Das Aufräumen hat den Posteingang angefasst — der Rollenfilter fehlt."
    assert len(server.ordner["INBOX"]["nachrichten"]) == 2


def test_der_merker_verhindert_zwei_laeufe_am_selben_tag(db, welt):
    _, konto = welt  # noqa: F811
    person = _person(db)
    person.aufraeumen_papierkorb_tage = 7
    db.commit()

    aufraeumen.runde()
    db.expire_all()
    assert _person(db).aufraeumen_zuletzt is not None

    # Zwischen den Läufen altert die nächste Mail über die Grenze …
    naechste = db.query(Nachricht).filter(Nachricht.betreff == "Papierkorb neu").one()
    naechste.datum = utcnow() - timedelta(days=30)
    naechste.angekommen = utcnow() - timedelta(days=30)
    db.commit()

    # … aber am selben Tag läuft keine zweite Runde.
    stand = aufraeumen.runde()
    db.expire_all()
    assert stand == {"benutzer": 0, "geloescht": 0}
    assert _betreffe(db, _ordner(konto, "papierkorb")) == ["Papierkorb neu"]


def test_nach_einem_tag_laeuft_es_wieder(db, welt):
    """Der Merker sperrt den Tag, nicht für immer."""
    _, konto = welt  # noqa: F811
    person = _person(db)
    person.aufraeumen_papierkorb_tage = 7
    person.aufraeumen_zuletzt = utcnow() - timedelta(days=1, hours=1)
    db.commit()

    stand = aufraeumen.runde()
    db.expire_all()

    assert stand["geloescht"] == 1
    assert _betreffe(db, _ordner(konto, "papierkorb")) == ["Papierkorb neu"]


def test_ein_klemmendes_postfach_haelt_die_runde_nicht_auf(db, welt, monkeypatch, caplog):
    """⚠️ Fangen, warnen, weiter — dasselbe Muster wie im Takt."""
    from app.services import konten

    server, konto = welt  # noqa: F811
    person = _person(db)
    person.aufraeumen_papierkorb_tage = 7
    db.commit()

    kaputtes = konten.anlegen(
        db,
        person,
        konten.Zugangsdaten("Klemmt", "zweit@b.example", "klemmt.example", 993, "ssl",
                            "u", "p", "s", 587, "starttls", "u", "p"),
    )
    db.add(Ordner(konto_id=kaputtes.id, pfad="Trash", name="Trash", rolle="papierkorb"))
    db.commit()

    def waehlerisch(host, *a, **k):
        if host == "klemmt.example":
            raise RuntimeError("connection refused")
        return server

    monkeypatch.setattr(handeln.imapdienst, "verbinden", waehlerisch)

    with caplog.at_level(logging.WARNING, logger="nexmail.aufraeumen"):
        stand = aufraeumen.runde()
    db.expire_all()

    # Das klemmende Postfach ist gemeldet, das gesunde trotzdem geräumt.
    assert any("Auto-clean skipped" in z.message for z in caplog.records)
    assert stand["geloescht"] == 1
    assert _betreffe(db, _ordner(konto, "papierkorb")) == ["Papierkorb neu"]


def test_der_papierkorb_misst_die_verweildauer_nicht_das_absendedatum(db, welt):
    """⚠️ **Die Rueckholfrist.** Eine heute geloeschte Januar-Mail ist nach dem
    Absendedatum sofort „alt" — gemessen wird deshalb an ``angekommen``, der
    Ankunft im Papierkorb. Sonst waere sie bei der naechsten Runde endgueltig
    weg, mit null Tagen Frist. Junk misst weiter am Absendedatum: Dort trifft
    die Post direkt ein, „aelter als n Tage" meint genau das.
    """
    _, konto = welt  # noqa: F811
    person = _person(db)
    person.aufraeumen_papierkorb_tage = 7
    person.aufraeumen_junk_tage = 7
    db.commit()

    # Die Januar-Mail, heute in den Papierkorb gelegt: Absendedatum uralt,
    # Verweildauer null.
    heute_geloescht = db.query(Nachricht).filter(Nachricht.betreff == "Papierkorb neu").one()
    heute_geloescht.datum = utcnow() - timedelta(days=200)
    db.commit()

    aufraeumen.runde()
    db.expire_all()

    # Sie liegt noch da — nur die wirklich lange liegende ist weg.
    assert _betreffe(db, _ordner(konto, "papierkorb")) == ["Papierkorb neu"], (
        "Die heute geloeschte Mail wurde am Absendedatum gemessen und ist "
        "endgueltig weg — null Tage Rueckholfrist."
    )
    # Junk dagegen: Absendedatum zaehlt, die alte ist weg, obwohl sie erst
    # eben abgeglichen (angekommen=jetzt) wurde.
    assert _betreffe(db, _ordner(konto, "junk")) == ["Junk neu"]


def test_ein_selbst_angelegter_spam_unterordner_ist_kein_loeschziel():
    """⚠️ ``Archiv/Spam`` ist ein Ablageordner. Die Namensheuristik gilt nur
    auf oberster Ebene — sonst leerte das Aufraeumen einen selbst angelegten
    Unterordner mit endgueltigem EXPUNGE. Die SPECIAL-USE-Kennzeichen des
    Servers gelten dagegen in jeder Tiefe.
    """
    from app.services import imap

    assert imap._rolle_bestimmen("Archiv/Spam", []) == "eigen"
    assert imap._rolle_bestimmen("Archiv.Trash", []) == "eigen"
    # Sagt der **Server**, dass es Junk ist, gilt das auch in der Tiefe.
    assert imap._rolle_bestimmen("Archiv/Spam", [rb"\Junk"]) == "junk"
    # Oberste Ebene bleibt, wie sie war — samt INBOX-Vorbau.
    assert imap._rolle_bestimmen("Spam", []) == "junk"
    assert imap._rolle_bestimmen("INBOX.Spam", []) == "junk"


# --- Über die Schnittstelle ---------------------------------------------- #


def test_einstellung_gilt_je_benutzer(klient, zweiter_klient, db):
    from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

    einrichten(klient)

    vorher = klient.get("/api/einstellungen/aufraeumen").json()
    assert vorher == {"papierkorb_tage": 0, "junk_tage": 0}

    antwort = klient.put(
        "/api/einstellungen/aufraeumen", json={"papierkorb_tage": 7, "junk_tage": 30}
    )
    assert antwort.status_code == 200
    assert antwort.json() == {"papierkorb_tage": 7, "junk_tage": 30}
    assert klient.get("/api/einstellungen/aufraeumen").json() == {
        "papierkorb_tage": 7,
        "junk_tage": 30,
    }

    # ⚠️ Je Benutzer: Der zweite sieht weiter seine eigene Vorgabe.
    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)
    assert zweiter_klient.get("/api/einstellungen/aufraeumen").json() == {
        "papierkorb_tage": 0,
        "junk_tage": 0,
    }


def test_nur_die_angebotenen_stufen(klient):
    """⚠️ Positivliste: Ein von Hand geschicktes „1" hieße, dass morgen früh
    alles von gestern endgültig weg ist."""
    from conftest import einrichten

    einrichten(klient)
    antwort = klient.put(
        "/api/einstellungen/aufraeumen", json={"papierkorb_tage": 1, "junk_tage": 0}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "aufbewahrung_ungueltig"


def test_ein_gescheiterter_benutzer_haelt_die_runde_nicht_auf(db, welt, monkeypatch, caplog):
    """⚠️ **Die Falle vom 03.09.2026, einen Dienst weiter.**

    Takt und Wiedervorlage haben seit dem Vorfall je eine Absicherung um den
    einzelnen Vorgang; das Aufräumen hatte als einziges keine. Ein Fehler beim
    k-ten Benutzer — etwa ein `StaleDataError`, weil jemand gerade ein Postfach
    entfernt hat — riss alle folgenden mit, und die nächste Runde kommt erst in
    einer Stunde (`NACHSEHEN_SEKUNDEN = 3600`).

    Geprüft wird mit zwei Benutzern: Der erste platzt, der zweite muss trotzdem
    drankommen. Mit nur einem wäre der Test grün, egal wie der Code aussieht.
    """
    from conftest import zweiten_benutzer_anlegen

    erster = _person(db)
    zweiter, _ = zweiten_benutzer_anlegen(db)
    for wer in (erster, zweiter):
        wer.aufraeumen_papierkorb_tage = 7
        wer.aufraeumen_zuletzt = None
    db.commit()

    drangewesen: list[str] = []
    echt = aufraeumen.benutzer_aufraeumen

    def platzt(sitzung, person):
        drangewesen.append(person.benutzername)
        if person.id == erster.id:
            raise RuntimeError("Das Postfach gibt es nicht mehr.")
        return echt(sitzung, person)

    monkeypatch.setattr(aufraeumen, "benutzer_aufraeumen", platzt)

    with caplog.at_level(logging.ERROR, logger="nexmail.aufraeumen"):
        aufraeumen.runde()

    assert len(drangewesen) == 2, (
        f"Nach dem Fehler kam niemand mehr dran: {drangewesen}"
    )
    assert any("Auto-clean failed" in e.getMessage() for e in caplog.records), (
        "Der Fehler steht nicht im Protokoll."
    )
