"""Versand planen: später senden, fällig werden, abbrechen.

⚠️ **Nichts hier geht ins Netz.** SMTP und IMAP kommen als Doppelgänger aus
``test_verfassen`` bzw. ``test_abgleich``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from sqlalchemy import select

from app.models import Ausgang, Nachricht, Ordner, utcnow
from app.services import senden
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture
from test_verfassen import _entwurf, postausgang  # noqa: F401 - Fixture


def _in_zukunft(minuten: int = 60):
    return utcnow() + timedelta(minutes=minuten)


def _vergangen(minuten: int = 5):
    return utcnow() - timedelta(minutes=minuten)


@pytest.fixture
def entwurfsordner(db, postausgang):  # noqa: F811
    """Ein Entwurfsordner am Konto und auf dem Doppelgänger-Server."""
    konto, _, server = postausgang
    db.add(Ordner(konto_id=konto.id, pfad="Drafts", name="Drafts", rolle="entwuerfe"))
    db.commit()
    db.refresh(konto)
    server.anlegen("Drafts")
    return konto


# --- Überspringen --------------------------------------------------------- #


def test_geplant_wird_nicht_sofort_gesendet(db, postausgang):
    """⚠️ Der Kern des Aufschubs: Die Warteschlange fasst Geplantes nicht an."""
    konto, smtp, _ = postausgang

    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_in_zukunft())
    ergebnis = senden.warteschlange_abarbeiten(db)

    assert ergebnis["versucht"] == 0
    db.refresh(zeile)
    assert zeile.stand == "wartet"
    assert smtp.gesendet == []
    # Der Inhalt liegt weiter auf der Platte - er muss den Zeitpunkt erleben.
    assert senden._datei(zeile.id).is_file()


def test_nach_ablauf_geht_es_hinaus(db, postausgang):
    konto, smtp, _ = postausgang

    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_vergangen())
    ergebnis = senden.warteschlange_abarbeiten(db)

    assert ergebnis["gesendet"] == 1
    db.refresh(zeile)
    assert zeile.stand == "gesendet"
    assert len(smtp.gesendet) == 1


def test_der_versandplan_schickt_nur_faelliges(db, postausgang):
    """Was der Faden im Minutentakt aufruft — Geplantes ja, Zukünftiges nein."""
    konto, smtp, _ = postausgang

    frueh = senden.einreihen(db, konto, _entwurf(betreff="Frueh"), senden_ab=_vergangen())
    spaet = senden.einreihen(db, konto, _entwurf(betreff="Spaet"), senden_ab=_in_zukunft())

    assert senden.faellige_geplante(db) == 1
    db.refresh(frueh)
    db.refresh(spaet)
    assert frueh.stand == "gesendet"
    assert spaet.stand == "wartet"
    assert len(smtp.gesendet) == 1


def test_nachschieben_laesst_geplantes_liegen(klient, db, postausgang):
    """Der Knopf „noch einmal versuchen" ist kein „jetzt doch sofort"."""
    konto, smtp, _ = postausgang
    senden.einreihen(db, konto, _entwurf(), senden_ab=_in_zukunft())

    antwort = klient.post("/api/verfassen/ausgang/nachschieben")

    assert antwort.status_code == 200
    assert antwort.json()["versucht"] == 0
    assert smtp.gesendet == []


# --- Der Sende-Endpunkt --------------------------------------------------- #


def test_senden_ohne_senden_ab_wie_bisher(klient, db, postausgang):
    """Wer nichts plant, merkt von alledem nichts."""
    konto, smtp, _ = postausgang

    antwort = klient.post(
        "/api/verfassen/senden",
        json={"konto_id": konto.id, "an": ["anja@example.org"], "betreff": "Sofort", "html": "<p>x</p>"},
    )

    assert antwort.status_code == 200
    assert antwort.json()["stand"] == "gesendet"
    assert len(smtp.gesendet) == 1
    zeile = db.execute(select(Ausgang)).scalars().one()
    assert zeile.senden_ab is None


def test_der_endpunkt_plant_statt_zu_senden(klient, db, postausgang):
    konto, smtp, _ = postausgang
    zeitpunkt = _in_zukunft(120)

    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["anja@example.org"],
            "betreff": "Geplant",
            "html": "<p>x</p>",
            "senden_ab": zeitpunkt.isoformat(),
        },
    )

    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["stand"] == "wartet"
    assert daten["senden_ab"] is not None
    assert smtp.gesendet == []

    # Und die Liste zeigt den Eintrag samt Zeitpunkt.
    liste = klient.get("/api/verfassen/ausgang").json()
    assert len(liste) == 1
    assert liste[0]["betreff"] == "Geplant"
    assert liste[0]["senden_ab"] is not None


def test_senden_ab_in_der_vergangenheit_geht_sofort(klient, db, postausgang):
    """Ein abgelaufener Zeitpunkt ist fällig — kein Fehler, kein Liegenbleiben."""
    konto, smtp, _ = postausgang

    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["anja@example.org"],
            "betreff": "Ueberfaellig",
            "html": "<p>x</p>",
            "senden_ab": _vergangen().isoformat(),
        },
    )

    assert antwort.status_code == 200
    assert antwort.json()["stand"] == "gesendet"
    assert len(smtp.gesendet) == 1


def test_ein_fehlschlag_verschiebt_geplantes_nach_hinten(db, postausgang):
    """⚠️ Der Versandplan greift im Minutentakt. Ohne die Verschiebung von
    ``senden_ab`` waeren alle fuenf Versuche nach fuenf Minuten verbraucht —
    ein zehnminuetiger SMTP-Schluckauf zur Planzeit liesse die Mail dann
    dauerhaft als „gescheitert" liegen."""
    konto, smtp, _ = postausgang
    smtp.scheitert = True

    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_vergangen())
    assert senden.faellige_geplante(db) == 0

    db.refresh(zeile)
    assert zeile.stand == "wartet"
    assert zeile.versuche == 1
    # Nach hinten geschoben: fruehestens in ~2 Minuten wieder dran.
    assert zeile.senden_ab > utcnow() + timedelta(seconds=30)

    # Die naechste Minute des Versandplans fasst ihn deshalb nicht an —
    # genau das verhindert das Verbrennen der Versuche.
    assert senden.faellige_geplante(db) == 0
    db.refresh(zeile)
    assert zeile.versuche == 1


def test_ein_gewoehnlicher_versand_bekommt_keinen_aufschub(db, postausgang):
    """Ohne ``senden_ab`` bleibt alles wie bisher: wiederholt wird beim Start
    oder auf Klick, nicht nach einer Uhr."""
    konto, smtp, _ = postausgang
    smtp.scheitert = True

    zeile = senden.einreihen(db, konto, _entwurf())
    with pytest.raises(senden.SendeFehler):
        senden.versenden(db, zeile)

    db.refresh(zeile)
    assert zeile.stand == "wartet"
    assert zeile.senden_ab is None


# --- „Senden rueckholen": Dauer statt Zeitpunkt ---------------------------- #


def test_rueckholen_rechnet_mit_der_server_uhr(klient, db, postausgang):
    """⚠️ Der Aufschub kommt als **Dauer**. Ein Zeitpunkt vom Client hinge an
    dessen Uhr — ging sie nach, sendete der Server sofort, und „Senden
    rueckholen" waere bei jedem Senden still wirkungslos."""
    konto, smtp, _ = postausgang

    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["anja@example.org"],
            "betreff": "Zurueckholbar",
            "html": "<p>x</p>",
            "rueckhol_sekunden": 30,
        },
    )

    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["stand"] == "wartet"
    assert daten["senden_ab"] is not None
    assert smtp.gesendet == []

    zeile = db.execute(select(Ausgang)).scalars().one()
    # An der Server-Uhr gemessen liegt der Zeitpunkt sicher in der Zukunft.
    assert utcnow() < zeile.senden_ab <= utcnow() + timedelta(seconds=31)


def test_rueckhol_dauer_ist_gedeckelt(klient, postausgang):
    """Positivliste statt freier Zahl — 0 bis 600 Sekunden, mehr ist kein
    Rueckhol-Aufschub mehr, sondern ein verkappter Versandplan."""
    konto, _, _ = postausgang
    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["anja@example.org"],
            "betreff": "Zu lang",
            "html": "<p>x</p>",
            "rueckhol_sekunden": 9999,
        },
    )
    assert antwort.status_code == 422


# --- Abbrechen ------------------------------------------------------------ #


def test_abbrechen_entfernt_und_legt_entwurf_ab(klient, db, postausgang, entwurfsordner):
    """⚠️ Nichts geht verloren: Der Inhalt liegt danach im Entwurfsordner."""
    konto, smtp, server = postausgang

    zeile = senden.einreihen(
        db,
        konto,
        _entwurf(blindkopie=["heimlich@example.org"]),
        senden_ab=_in_zukunft(),
    )
    kennung = zeile.id

    antwort = klient.post(f"/api/verfassen/ausgang/{kennung}/abbrechen")

    assert antwort.status_code == 200
    db.expire_all()
    assert db.get(Ausgang, kennung) is None
    assert not senden._datei(kennung).exists()
    assert smtp.gesendet == []

    # Der Entwurf liegt beim Anbieter …
    abgelegt = [(pfad, roh) for pfad, roh in server.abgelegt if pfad == "Drafts"]
    assert len(abgelegt) == 1
    # … samt der Blindkopie, die in der fertigen Mail absichtlich fehlt.
    assert b"heimlich@example.org" in abgelegt[0][1]

    # … und der Abgleich hat ihn in die eigene Datenbank geholt.
    ordner = db.execute(
        select(Ordner).where(Ordner.konto_id == konto.id, Ordner.rolle == "entwuerfe")
    ).scalars().one()
    drin = db.execute(select(Nachricht).where(Nachricht.ordner_id == ordner.id)).scalars().all()
    assert len(drin) == 1

    # ⚠️ Und die Antwort nennt die UID der abgelegten Fassung. Ohne sie hinge
    # das wieder geoeffnete Fenster an keiner Entwurfs-UID, und jedes
    # „Rueckgaengig" hinterliesse fuer immer eine Sicherheits-Fassung.
    daten = antwort.json()
    assert daten["entwurf_uid"] == drin[0].uid
    assert daten["konto_id"] == konto.id


def test_abbrechen_verliert_gegen_den_versandfaden(db, postausgang, entwurfsordner):
    """⚠️ Das Wettrennen in letzter Sekunde: Der Versandfaden (eigene Session)
    beansprucht die Zeile, waehrend der Router noch „wartet" gelesen hat. Der
    Abbruch darf dann weder einen Entwurf ablegen noch 204 melden — die Mail
    geht hinaus, und genau das muss die Antwort sagen."""
    from sqlalchemy import update

    konto, _, server = postausgang
    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_vergangen())
    assert zeile.stand == "wartet"  # so hat der Router die Zeile gelesen

    # Der Versandfaden kommt dazwischen: bedingtes UPDATE auf „unterwegs",
    # wie in ``versenden`` — nur eben aus einer anderen Session.
    db.execute(update(Ausgang).where(Ausgang.id == zeile.id).values(stand="unterwegs"))
    db.commit()

    with pytest.raises(senden.AbbruchKollision):
        senden.abbrechen(db, zeile)

    db.expire_all()
    assert db.get(Ausgang, zeile.id) is not None
    # Kein Sicherheits-Entwurf: Die Mail ist unterwegs, nicht zurueckgeholt.
    assert [pfad for pfad, _ in server.abgelegt if pfad == "Drafts"] == []


def test_abbrechen_ohne_entwurfsordner_wirft_nichts_weg(klient, db, postausgang):
    """⚠️ Kann der Entwurf nirgends hin, bleibt der Eintrag liegen."""
    konto, _, _ = postausgang
    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_in_zukunft())

    antwort = klient.post(f"/api/verfassen/ausgang/{zeile.id}/abbrechen")

    assert antwort.status_code == 409
    db.expire_all()
    liegt = db.get(Ausgang, zeile.id)
    assert liegt is not None
    # ⚠️ Mit seinem **alten** Stand: Bliebe die Beanspruchung stehen, fasste
    # weder der Versandplan noch ein zweiter Abbruchversuch die Zeile je an.
    assert liegt.stand == "wartet"
    assert senden._datei(zeile.id).is_file()


def test_fremder_kann_nicht_abbrechen(klient, zweiter_klient, db, postausgang, entwurfsordner):
    from conftest import anmelden, zweiten_benutzer_anlegen

    konto, _, _ = postausgang
    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_in_zukunft())

    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    antwort = zweiter_klient.post(f"/api/verfassen/ausgang/{zeile.id}/abbrechen")

    assert antwort.status_code == 404
    db.expire_all()
    assert db.get(Ausgang, zeile.id) is not None


def test_ein_unterbrochener_abbruch_wird_beim_start_sichtbar(db, postausgang):
    """⚠️ „abgebrochen" ist ein Zwischenstand und lebt Sekunden. Steht er nach
    einem Absturz noch da, macht der Start daraus „gescheitert": sichtbar
    liegen bleiben statt stumm verschwinden — und erst recht nicht doch noch
    hinausgehen."""
    from sqlalchemy import update

    konto, smtp, _ = postausgang
    zeile = senden.einreihen(db, konto, _entwurf(), senden_ab=_vergangen())
    db.execute(update(Ausgang).where(Ausgang.id == zeile.id).values(stand="abgebrochen"))
    db.commit()

    senden.warteschlange_abarbeiten(db)

    db.refresh(zeile)
    assert zeile.stand == "gescheitert"
    assert zeile.letzter_fehler
    assert smtp.gesendet == []


def test_gesendetes_laesst_sich_nicht_abbrechen(klient, db, postausgang, entwurfsordner):
    """Was draußen ist, ist draußen — die Antwort sagt es, statt so zu tun."""
    konto, _, _ = postausgang
    zeile = senden.einreihen(db, konto, _entwurf())
    senden.versenden(db, zeile)

    antwort = klient.post(f"/api/verfassen/ausgang/{zeile.id}/abbrechen")

    assert antwort.status_code == 409
    db.expire_all()
    assert db.get(Ausgang, zeile.id) is not None


def test_ein_unerwarteter_fehler_laesst_die_uebrigen_nicht_liegen(db, postausgang, monkeypatch, caplog):
    """⚠️ **Und beim Start wäre er schlimmer als „liegen bleiben".**

    Bis zum 03.09.2026 fing die Schleife nur `SendeFehler`. Eine andere
    Ausnahme bei der k-ten Mail — etwa ein `StaleDataError`, weil jemand
    gerade das Postfach entfernt hat — brach sie ab, und die übrigen blieben
    für 60 Sekunden liegen. Beim Hochfahren ist es mehr als das:
    `warteschlange_abarbeiten` läuft dort im Lebenslauf **ohne eigenes `try`**,
    also wäre nexmail an einem einzigen kaputten Eintrag gar nicht mehr
    hochgekommen.

    Geprüft wird mit zwei Einträgen: Der erste platzt, der zweite muss
    trotzdem hinausgehen. Mit nur einem wäre der Test grün, egal wie der Code
    aussieht.
    """
    import logging

    konto, smtp, _ = postausgang

    erste = senden.einreihen(db, konto, _entwurf())
    zweite = senden.einreihen(db, konto, _entwurf())

    echt = senden.versenden

    def platzt(sitzung, zeile):
        if zeile.id == erste.id:
            raise RuntimeError("Das Postfach gibt es nicht mehr.")
        return echt(sitzung, zeile)

    monkeypatch.setattr(senden, "versenden", platzt)

    with caplog.at_level(logging.ERROR, logger="nexmail.senden"):
        ergebnis = senden.warteschlange_abarbeiten(db)

    assert ergebnis["versucht"] == 2, "Nach dem Fehler kam der zweite Eintrag nicht mehr dran."
    assert ergebnis["gesendet"] == 1
    assert len(smtp.gesendet) == 1, "Die zweite Mail ist nicht hinausgegangen."
    assert any("unexpected error" in e.getMessage() for e in caplog.records), (
        "Der Fehler steht nicht im Protokoll."
    )
