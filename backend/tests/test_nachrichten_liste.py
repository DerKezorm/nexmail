"""Die Sammelansichten und ihre Einschraenkung auf Schlagwort-Gruppen.

⚠️ **Warum das im Server geprueft wird und nicht in der Oberflaeche.** Die
Liste holt nur die neuesten 200 Zeilen. Wuerde erst geholt und dann nach
Postfach ausgesiebt, zeigte ein voller Posteingang womoeglich drei Mails — und
behauptete damit, mehr gebe es nicht. Der Fehler faellt in einem kleinen
Testbestand nie auf; deshalb steht die Einschraenkung in der Abfrage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import Nachricht, Ordner
from app.services import anbieter, konten
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from test_konten import _eingabe, _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="", token="": _guter_befund())
    yield


def _postfach_mit_mail(klient, adresse: str, betreff: str, markiert: bool = False) -> str:
    """Ein Postfach anlegen und eine Mail in seinen Posteingang legen."""
    konto_id = klient.post("/api/konten", json=_eingabe(adresse)).json()["id"]
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        db.add(
            Nachricht(
                benutzer_id=posteingang.konto.benutzer_id,
                konto_id=konto_id,
                ordner_id=posteingang.id,
                uid=1,
                betreff=betreff,
                markiert=markiert,
            )
        )
        db.commit()
    return konto_id


def _betreffe(antwort) -> set[str]:
    return {z["betreff"] for z in antwort.json()}


def test_ohne_einschraenkung_kommen_alle_posteingaenge(klient, ohne_netz):
    einrichten(klient)
    _postfach_mit_mail(klient, "privat@beispiel.example", "Privatpost")
    _postfach_mit_mail(klient, "arbeit@beispiel.example", "Dienstpost")

    antwort = klient.get("/api/nachrichten?nur_posteingaenge=true&grenze=200")
    assert _betreffe(antwort) == {"Privatpost", "Dienstpost"}


def test_konto_ids_schraenkt_die_sammelansicht_ein(klient, ohne_netz):
    """Der eigentliche Punkt: „Alle Posteingaenge" folgt der gewaehlten Gruppe."""
    einrichten(klient)
    privat = _postfach_mit_mail(klient, "privat@beispiel.example", "Privatpost")
    _postfach_mit_mail(klient, "arbeit@beispiel.example", "Dienstpost")

    antwort = klient.get(
        f"/api/nachrichten?nur_posteingaenge=true&grenze=200&konto_ids={privat}"
    )
    assert _betreffe(antwort) == {"Privatpost"}


def test_konto_ids_schraenkt_auch_die_markierten_ein(klient, ohne_netz):
    einrichten(klient)
    privat = _postfach_mit_mail(klient, "privat@beispiel.example", "Privatpost", markiert=True)
    _postfach_mit_mail(klient, "arbeit@beispiel.example", "Dienstpost", markiert=True)

    alle = klient.get("/api/nachrichten?filter=markiert&grenze=200")
    assert _betreffe(alle) == {"Privatpost", "Dienstpost"}

    nur_privat = klient.get(f"/api/nachrichten?filter=markiert&grenze=200&konto_ids={privat}")
    assert _betreffe(nur_privat) == {"Privatpost"}


def test_mehrere_kennungen_gehen_zusammen(klient, ohne_netz):
    einrichten(klient)
    a = _postfach_mit_mail(klient, "eins@beispiel.example", "Eins")
    b = _postfach_mit_mail(klient, "zwei@beispiel.example", "Zwei")
    _postfach_mit_mail(klient, "drei@beispiel.example", "Drei")

    antwort = klient.get(f"/api/nachrichten?nur_posteingaenge=true&grenze=200&konto_ids={a},{b}")
    assert _betreffe(antwort) == {"Eins", "Zwei"}


def test_eine_fremde_kennung_holt_nichts_heraus(klient, zweiter_klient, ohne_netz, db):
    """⚠️ Eine echte Kennung ist noch keine Berechtigung.

    Die Einschraenkung darf nicht zum Schlupfloch werden: Wer die Kennung eines
    fremden Postfachs kennt, bekommt trotzdem nichts.

    ⚠️ **Was dieser Test beweist und was nicht.** Er prueft die *Eigenschaft*,
    nicht eine bestimmte Zeile. Bei der Mutationsprobe am 01.09.2026 blieb er
    gruen, als die Benutzerpruefung *innerhalb* der Einschraenkung entfernt
    wurde — geschuetzt hat da die aeussere Bedingung
    ``Nachricht.benutzer_id == person.id``. Die innere ist ein zweites Schloss,
    kein einziges. Wer sie fuer ueberfluessig haelt und herausnimmt, verlaesst
    sich darauf, dass die aeussere nie verrutscht.
    """
    einrichten(klient)
    fremd = _postfach_mit_mail(klient, "privat@beispiel.example", "Privatpost")

    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.get(
        f"/api/nachrichten?nur_posteingaenge=true&grenze=200&konto_ids={fremd}"
    )
    assert antwort.status_code == 200
    assert antwort.json() == []


def test_unbekannte_kennung_gibt_leer_statt_alles(klient, ohne_netz):
    """⚠️ Ein Tippfehler darf nicht in „dann eben alles" umschlagen.

    Waere die Bedingung bei unbekannter Kennung wirkungslos, saehe der
    Betreiber unter „privat" wieder seine Dienstpost — und haette keinen Anlass,
    an der Kennung zu zweifeln.
    """
    einrichten(klient)
    _postfach_mit_mail(klient, "privat@beispiel.example", "Privatpost")

    antwort = klient.get(
        "/api/nachrichten?nur_posteingaenge=true&grenze=200&konto_ids=gibtesnicht"
    )
    assert antwort.json() == []


# --- Weiterlesen: der Merkpunkt statt „versatz" -------------------------- #


def _mails_legen(konto_id: str, wieviele: int, sekunden_abstand: int = 60) -> None:
    """``wieviele`` Mails in den Posteingang, die neueste zuerst betitelt."""
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        start = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        for n in range(wieviele):
            db.add(
                Nachricht(
                    benutzer_id=posteingang.konto.benutzer_id,
                    konto_id=konto_id,
                    ordner_id=posteingang.id,
                    uid=100 + n,
                    betreff=f"Mail {n:02}",
                    datum=start - timedelta(seconds=n * sekunden_abstand),
                )
            )
        db.commit()


def _seite(klient, konto_id: str, grenze: int, nach: str = "") -> list[dict]:
    frage = f"/api/nachrichten?nur_posteingaenge=true&grenze={grenze}"
    if nach:
        frage += f"&nach={nach}"
    antwort = klient.get(frage)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _merkpunkt(zeile: dict) -> str:
    return f"{zeile['datum']},{zeile['id']}"


def test_weiterlesen_holt_die_naechsten_ohne_luecke(klient, ohne_netz):
    einrichten(klient)
    konto = klient.post("/api/konten", json=_eingabe()).json()["id"]
    _mails_legen(konto, 5)

    erste = _seite(klient, konto, 2)
    zweite = _seite(klient, konto, 2, _merkpunkt(erste[-1]))
    dritte = _seite(klient, konto, 2, _merkpunkt(zweite[-1]))

    assert [z["betreff"] for z in erste] == ["Mail 00", "Mail 01"]
    assert [z["betreff"] for z in zweite] == ["Mail 02", "Mail 03"]
    assert [z["betreff"] for z in dritte] == ["Mail 04"]
    # Am Ende kommt nichts mehr — daran erkennt die Oberflaeche das Ende.
    assert _seite(klient, konto, 2, _merkpunkt(dritte[-1])) == []


def test_neue_post_zwischen_zwei_seiten_verdoppelt_nichts(klient, ohne_netz):
    """⚠️ **Der Grund für den Merkpunkt.**

    Mit ``versatz`` waere das hier kaputt: Kommt zwischen zwei Seiten eine Mail
    an, rutscht alles um eins nach unten, und Seite 2 beginnt mit der letzten
    Zeile von Seite 1. Doppelte Eintraege in der Liste sehen aus wie ein
    Abgleichfehler — man sucht die Ursache im IMAP, nicht im Blaettern.
    """
    einrichten(klient)
    konto = klient.post("/api/konten", json=_eingabe()).json()["id"]
    _mails_legen(konto, 4)

    erste = _seite(klient, konto, 2)
    assert [z["betreff"] for z in erste] == ["Mail 00", "Mail 01"]

    # Jetzt trifft neue Post ein — sie gehoert oben hin, nicht in Seite 2.
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto, Ordner.rolle == "posteingang")
            .one()
        )
        db.add(
            Nachricht(
                benutzer_id=posteingang.konto.benutzer_id,
                konto_id=konto,
                ordner_id=posteingang.id,
                uid=999,
                betreff="Ganz frisch",
                datum=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()

    zweite = _seite(klient, konto, 2, _merkpunkt(erste[-1]))
    assert [z["betreff"] for z in zweite] == ["Mail 02", "Mail 03"]

    gesehen = [z["betreff"] for z in erste + zweite]
    assert len(gesehen) == len(set(gesehen)), f"Doppelte Zeilen: {gesehen}"


def test_gleiche_sekunde_bleibt_eindeutig(klient, ohne_netz):
    """⚠️ Zwei Mails in derselben Sekunde sind der Normalfall bei Massenpost.

    Ohne die Kennung als zweites Ordnungsmerkmal ist ihre Reihenfolge nicht
    festgelegt — und der Merkpunkt trifft mal die eine, mal die andere. Dann
    fehlt beim Weiterlesen eine Mail, und zwar lautlos.
    """
    einrichten(klient)
    konto = klient.post("/api/konten", json=_eingabe()).json()["id"]
    _mails_legen(konto, 6, sekunden_abstand=0)

    alle: list[str] = []
    merk = ""
    for _ in range(6):
        seite = _seite(klient, konto, 2, merk)
        if not seite:
            break
        alle += [z["betreff"] for z in seite]
        merk = _merkpunkt(seite[-1])

    assert sorted(alle) == [f"Mail {n:02}" for n in range(6)]
    assert len(alle) == len(set(alle)), f"Doppelte Zeilen: {alle}"


def test_kaputter_merkpunkt_faengt_nicht_von_vorne_an(klient, ohne_netz):
    """⚠️ Sonst haengt das Nachladen in der Schleife und zeigt immer dasselbe."""
    einrichten(klient)
    konto = klient.post("/api/konten", json=_eingabe()).json()["id"]
    _mails_legen(konto, 3)

    antwort = klient.get("/api/nachrichten?nur_posteingaenge=true&nach=kaputt")
    assert antwort.status_code == 400, antwort.text
