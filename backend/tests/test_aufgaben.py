"""Aufgaben: Mails, die noch etwas von einem wollen.

⚠️ **Die beiden wichtigsten Tests hier drehen sich um dasselbe:** Was passiert,
wenn die Mail sich bewegt oder verschwindet. Eine Aufgabe, die dabei lautlos
verlorengeht, ist schlimmer als keine — man merkt es genau dann nicht, wenn es
darauf ankommt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Aufgabe, Nachricht, Ordner
from app.services import anbieter, konten
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from test_konten import _eingabe, _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="", token="": _guter_befund())
    yield


@pytest.fixture
def welt(klient, ohne_netz, db):
    """Ein Postfach mit drei Mails im Posteingang."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]
    posteingang = (
        db.query(Ordner).filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang").one()
    )
    ids = []
    for n in range(3):
        m = Nachricht(
            benutzer_id=posteingang.konto.benutzer_id,
            konto_id=konto_id,
            ordner_id=posteingang.id,
            uid=100 + n,
            message_id=f"<mail{n}@example.com>",
            betreff=f"Mail {n}",
            von_name="Wer Auch Immer",
            von_adresse="wer@example.com",
            datum=datetime(2026, 9, 1, 12, n, tzinfo=timezone.utc),
        )
        db.add(m)
        db.flush()
        ids.append(m.id)
    db.commit()
    return konto_id, posteingang, ids


def test_aus_einer_mail_wird_eine_aufgabe(klient, welt):
    _, _, ids = welt
    antwort = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]})
    assert antwort.status_code == 201, antwort.text

    zeile = antwort.json()
    assert zeile["betreff"] == "Mail 0"
    assert zeile["nachricht_id"] == ids[0]
    assert zeile["erledigt"] is None
    assert zeile["verwaist"] is False


def test_zweimal_dieselbe_mail_gibt_eine_aufgabe(klient, welt):
    """⚠️ Zweimal „zu Aufgabe machen" ist ein Verklicken, keine Ausnahme.

    Ein Doppel muesste man zweimal abhaken — und eine Fehlermeldung dafuer
    waere Schikane.
    """
    _, _, ids = welt
    erste = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()
    zweite = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()

    assert erste["id"] == zweite["id"]
    assert len(klient.get("/api/aufgaben").json()) == 1


def test_neue_aufgaben_kommen_nach_oben(klient, welt):
    """Was man gerade vorgemerkt hat, ist das, woran man denkt."""
    _, _, ids = welt
    for kennung in ids:
        klient.post("/api/aufgaben", json={"nachricht_id": kennung})

    betreffe = [z["betreff"] for z in klient.get("/api/aufgaben").json()]
    assert betreffe == ["Mail 2", "Mail 1", "Mail 0"]


def test_abhaken_und_zurueckholen(klient, welt):
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()

    erledigt = klient.patch(f"/api/aufgaben/{a['id']}", json={"erledigt": True})
    assert erledigt.status_code == 200
    assert erledigt.json()["erledigt"] is not None

    # ⚠️ **Erledigte verschwinden nicht.** Wer sich vertan hat, will sie
    # zurueckholen koennen, ohne die Mail zu suchen.
    assert len(klient.get("/api/aufgaben").json()) == 1

    zurueck = klient.patch(f"/api/aufgaben/{a['id']}", json={"erledigt": False})
    assert zurueck.json()["erledigt"] is None


def test_erledigte_stehen_unten(klient, welt):
    _, _, ids = welt
    angelegt = [klient.post("/api/aufgaben", json={"nachricht_id": k}).json() for k in ids]
    klient.patch(f"/api/aufgaben/{angelegt[2]['id']}", json={"erledigt": True})

    liste = klient.get("/api/aufgaben").json()
    assert liste[-1]["betreff"] == "Mail 2"
    assert all(z["erledigt"] is None for z in liste[:-1])


def test_abhaken_verliert_die_faelligkeit_nicht(klient, welt):
    """⚠️ Nicht mitgeschickt heisst **unveraendert**, nicht „leer".

    Dieselbe Regel wie beim Passwort. Ohne sie loescht jedes Abhaken das Datum.
    """
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()
    wann = "2026-09-10T00:00:00Z"

    klient.patch(f"/api/aufgaben/{a['id']}", json={"faellig": wann, "faellig_setzen": True})
    danach = klient.patch(f"/api/aufgaben/{a['id']}", json={"erledigt": True})
    assert danach.json()["faellig"] is not None

    # Ausdruecklich leeren geht trotzdem.
    leer = klient.patch(f"/api/aufgaben/{a['id']}", json={"faellig": None, "faellig_setzen": True})
    assert leer.json()["faellig"] is None


def test_reihenfolge_laesst_sich_ziehen(klient, welt):
    _, _, ids = welt
    angelegt = [klient.post("/api/aufgaben", json={"nachricht_id": k}).json() for k in ids]
    umgekehrt = [a["id"] for a in angelegt]  # Mail 0, 1, 2

    assert klient.put("/api/aufgaben/reihenfolge", json={"ids": umgekehrt}).status_code == 204
    assert [z["betreff"] for z in klient.get("/api/aufgaben").json()] == [
        "Mail 0",
        "Mail 1",
        "Mail 2",
    ]


def test_eine_fremde_kennung_stellt_nichts_um(klient, welt, db):
    """Die Liste kann sich zwischen Laden und Ziehen geaendert haben."""
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()
    assert klient.put("/api/aufgaben/reihenfolge", json={"ids": [a["id"], 9999]}).status_code == 204
    assert db.query(Aufgabe).count() == 1


# --- Der Kern: was passiert mit der Mail --------------------------------- #


def test_die_aufgabe_zieht_mit_der_mail_um(klient, welt, db):
    """⚠️ **Der wichtigste Test hier.**

    Wer eine Mail vom Telefon aus in einen anderen Ordner schiebt, bekommt beim
    naechsten Abgleich eine **neue** Zeile mit neuer Kennung — die alte ist
    weg. Ueber die Zeilennummer waere die Aufgabe damit verwaist, obwohl die
    Mail zwei Ordner weiter liegt. Wiedergefunden wird ueber die
    ``Message-ID``: Die vergibt der absendende Server und sie bleibt.
    """
    konto_id, posteingang, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()

    # ⚠️ Papierkorb statt Archiv: Das Testpostfach hat keins — und „vom
    # Handy aus weggeraeumt" ist ohnehin der haeufigere Fall.
    archiv = (
        db.query(Ordner)
        .filter(Ordner.konto_id == konto_id, Ordner.rolle == "papierkorb")
        .one()
    )
    alt = db.get(Nachricht, ids[0])
    kopie = Nachricht(
        benutzer_id=alt.benutzer_id,
        konto_id=konto_id,
        ordner_id=archiv.id,
        uid=500,
        message_id=alt.message_id,
        betreff=alt.betreff,
        datum=alt.datum,
    )
    db.delete(alt)
    db.add(kopie)
    db.commit()

    zeile = next(z for z in klient.get("/api/aufgaben").json() if z["id"] == a["id"])
    assert zeile["verwaist"] is False, "Die Aufgabe hat den Umzug ihrer Mail nicht mitbekommen."
    assert zeile["nachricht_id"] == kopie.id


def test_die_aufgabe_ueberlebt_ihre_mail(klient, welt, db):
    """⚠️ Wer im Papierkorb aufraeumt, soll nicht still seine Liste mitloeschen.

    Und sie muss **lesbar** bleiben: Eine Aufgabe, die dann nur noch „(weg)"
    heisst, ist wertlos — man weiss nicht mehr, worum es ging.
    """
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()

    db.delete(db.get(Nachricht, ids[0]))
    db.commit()

    zeile = next(z for z in klient.get("/api/aufgaben").json() if z["id"] == a["id"])
    assert zeile["verwaist"] is True
    assert zeile["nachricht_id"] is None
    # Der Abzug traegt weiter, worum es ging.
    assert zeile["betreff"] == "Mail 0"
    assert zeile["von_adresse"] == "wer@example.com"


def test_entfernen_laesst_die_mail_in_ruhe(klient, welt, db):
    """Abhaken und Entfernen sind Sachen der Aufgabe, nicht der Post."""
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()

    assert klient.delete(f"/api/aufgaben/{a['id']}").status_code == 204
    assert klient.get("/api/aufgaben").json() == []
    assert db.get(Nachricht, ids[0]) is not None


def test_fremde_aufgaben_bleiben_fremd(klient, zweiter_klient, welt, db):
    """Der Waechter ueber die Trennung gilt auch hier."""
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()

    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get("/api/aufgaben").json() == []
    assert zweiter_klient.patch(f"/api/aufgaben/{a['id']}", json={"erledigt": True}).status_code == 404
    assert zweiter_klient.delete(f"/api/aufgaben/{a['id']}").status_code == 404
    # Und aus einer fremden Mail laesst sich keine Aufgabe machen.
    assert zweiter_klient.post("/api/aufgaben", json={"nachricht_id": ids[1]}).status_code == 404


def test_faelligkeit_kommt_zurueck(klient, welt):
    _, _, ids = welt
    a = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()
    wann = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

    antwort = klient.patch(f"/api/aufgaben/{a['id']}", json={"faellig": wann, "faellig_setzen": True})
    assert antwort.status_code == 200
    assert antwort.json()["faellig"] is not None
