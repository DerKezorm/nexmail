"""Der Änderungs-Feed für den Offline-Speicher der App.

⚠️ **Die Tests schreiben absichtlich an der ORM-Schicht vorbei.** Genau so tut
es der Abgleich (``update()``, ``delete()``), und genau deshalb stehen die
Trigger in der Datenbank. Ein Test nur über ORM-Zeilen bestünde auch mit einem
Python-Ereignis, das im Betrieb die Hälfte verpasste.
"""

from __future__ import annotations

import sqlite3
import time

import pytest
from sqlalchemy import delete, update

from app.db import einstellung_schreiben
from app.models import Aenderung, Benutzer, Konto, Nachricht, Ordner
from app.services import abgleich, aenderungen
from app.services import imap as imapdienst
from conftest import einrichten, zweiten_benutzer_anlegen
from test_abgleich import FalscherServer
from test_app_flaeche import PFAD, abholen, koppeln, mail, postfach


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    return db.query(Benutzer).one()


@pytest.fixture
def stand(db, person):
    konto, eingang, archiv = postfach(db, person)
    return {
        "konto": konto,
        "eingang": eingang,
        "archiv": archiv,
        "eins": mail(db, person, konto, eingang, 1, betreff="Erste"),
    }


def seit(db, person, nummer=1, grenze=100):
    return aenderungen.seite(db, person.id, nummer, grenze)


def arten(seite) -> list[tuple[str, str, bool]]:
    return [(z.art, z.kennung, z.weg) for z in seite.eintraege]


def nach(db) -> int:
    """Die Nummer von jetzt: Was danach geschieht, steht auf der nächsten Seite."""
    return aenderungen.stand(db)


# --- Was hineinkommt ------------------------------------------------------- #


def test_eine_neue_mail_steht_im_feed(db, person, stand):
    vorher = nach(db)
    n = mail(db, person, stand["konto"], stand["eingang"], 2)

    assert arten(seit(db, person, vorher)) == [("nachricht", str(n.id), False)]


@pytest.mark.parametrize(
    "spalte, wert",
    [
        ("gelesen", True),
        ("markiert", True),
        ("beantwortet", True),
        ("schlagworte", '["$label1"]'),
        ("wichtigkeit", "hoch"),
        ("uid", 99),
    ],
)
def test_jede_aenderung_an_der_zeile_kommt_auch_am_orm_vorbei(db, person, stand, spalte, wert):
    """⚠️ **Wie ``_flags_uebernehmen`` schreibt:** ein ``update()``. Flags von
    anderen Geräten kommen nur so herein."""
    vorher = nach(db)
    db.execute(update(Nachricht).where(Nachricht.id == stand["eins"].id).values({spalte: wert}))
    db.commit()

    assert arten(seit(db, person, vorher)) == [("nachricht", str(stand["eins"].id), False)]


def test_verschieben_steht_im_feed(db, person, stand):
    vorher = nach(db)
    db.execute(
        update(Nachricht)
        .where(Nachricht.id == stand["eins"].id)
        .values(ordner_id=stand["archiv"].id)
    )
    db.commit()

    assert len(seit(db, person, vorher).eintraege) == 1


def test_was_die_liste_nicht_zeigt_ist_keine_aenderung(db, person, stand):
    """⚠️ **Sonst meldete jede geöffnete Mail sich selbst zurück.**"""
    vorher = nach(db)
    n = stand["eins"]
    n.koerper_text = "neu"
    n.koerper_html = "<p>neu</p>"
    n.anreisser = "neu"
    db.commit()

    assert seit(db, person, vorher).eintraege == []


def test_derselbe_wert_ist_keine_aenderung(db, person, stand):
    """Der Abgleich schreibt Flags nur bei Unterschied, ein ``update()`` mit
    gleichem Wert soll trotzdem nichts melden."""
    vorher = nach(db)
    db.execute(update(Nachricht).where(Nachricht.id == stand["eins"].id).values(gelesen=False))
    db.commit()

    assert seit(db, person, vorher).eintraege == []


def test_eine_entfernte_mail_kommt_als_weg(db, person, stand):
    vorher = nach(db)
    kennung = stand["eins"].id
    db.execute(delete(Nachricht).where(Nachricht.id == kennung))
    db.commit()

    assert arten(seit(db, person, vorher)) == [("nachricht", str(kennung), True)]


def test_je_mail_nur_eine_zeile(db, person, stand):
    """⚠️ **Sonst wächst die Tabelle mit jedem Klick**, und die App arbeitet zehn
    alte Stände ab, von denen neun überholt sind."""
    vorher = nach(db)
    for wert in (True, False, True):
        db.execute(update(Nachricht).where(Nachricht.id == stand["eins"].id).values(gelesen=wert))
        db.commit()

    assert len(seit(db, person, vorher).eintraege) == 1
    assert db.query(Aenderung).filter_by(art="nachricht").count() == 1


def test_ein_neuer_ordner_und_sein_umbenennen(db, person, stand):
    vorher = nach(db)
    neu = Ordner(konto_id=stand["konto"].id, pfad="Neu", name="Neu", rolle="eigen")
    db.add(neu)
    db.commit()
    assert arten(seit(db, person, vorher)) == [("ordner", str(neu.id), False)]
    assert seit(db, person, vorher).eintraege[0].konto_id == stand["konto"].id

    zwischen = nach(db)
    neu.name = "Anders"
    db.commit()
    assert arten(seit(db, person, zwischen)) == [("ordner", str(neu.id), False)]


def test_die_zaehler_eines_ordners_sind_keine_aenderung(db, person, stand):
    vorher = nach(db)
    stand["eingang"].ungelesen = 7
    stand["eingang"].anzahl = 9
    db.commit()

    assert seit(db, person, vorher).eintraege == []


def test_ein_entfernter_ordner_kommt_als_weg(db, person, stand):
    vorher = nach(db)
    kennung = stand["archiv"].id
    db.execute(delete(Ordner).where(Ordner.id == kennung))
    db.commit()

    assert ("ordner", str(kennung), True) in arten(seit(db, person, vorher))


def test_ein_entferntes_postfach_kommt_als_weg_und_nichts_bricht(db, person, stand):
    """⚠️ **Das Ordner-Konto kann schon fort sein.** Bräche der Trigger, ließe sich
    kein Postfach mehr entfernen."""
    vorher = nach(db)
    kennung, mail_id = stand["konto"].id, stand["eins"].id
    db.delete(db.get(Konto, kennung))
    db.commit()

    gefunden = arten(seit(db, person, vorher))
    assert ("postfach", kennung, True) in gefunden
    assert ("nachricht", str(mail_id), True) in gefunden


def test_ein_geaendertes_postfach(db, person, stand):
    vorher = nach(db)
    stand["konto"].stoerung = "anmeldung"
    db.commit()

    assert arten(seit(db, person, vorher)) == [("postfach", stand["konto"].id, False)]


def test_ein_abgleich_holt_flags_von_anderen_geraeten_herein(db, person, stand, monkeypatch):
    """⚠️ **Der eigentliche Fall.** Auf dem Telefon gelesen, hier gemerkt, in der
    App angekommen, über den echten Abgleich."""
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Erste", gelesen=True)
    server.anlegen("Archiv")
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda *_a, **_k: server)
    konto = stand["konto"]
    konto.erstabgleich_durch = True
    db.commit()
    vorher = nach(db)

    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    assert ("nachricht", str(stand["eins"].id), False) in arten(seit(db, person, vorher))


def test_ein_ordner_vom_anderen_geraet_kommt_mit_dem_abgleich(db, person, stand, monkeypatch):
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Erste")
    server.anlegen("Archiv")
    server.anlegen("Vom Telefon")
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda *_a, **_k: server)
    vorher = nach(db)

    abgleich.konto_abgleichen(db, stand["konto"], nur_posteingang=True)

    assert any(a == "ordner" and not w for a, _, w in arten(seit(db, person, vorher)))


# --- Blättern und Grenzen -------------------------------------------------- #


def test_since_null_nennt_nur_die_nummer(db, person, stand):
    """⚠️ **Der Feed ist kein Katalog.** Die App liest danach die Listen."""
    seite = aenderungen.seite(db, person.id, 0, 100)
    assert seite.eintraege == []
    assert seite.weiter == seite.stand == nach(db)
    assert seite.mehr is False


def test_seitenweise_ohne_luecke(db, person, stand):
    vorher = nach(db)
    neue = [mail(db, person, stand["konto"], stand["eingang"], i) for i in range(10, 15)]

    gesehen: list[str] = []
    nummer = vorher
    runden = 0
    while True:
        seite = seit(db, person, nummer, grenze=2)
        gesehen += [z.kennung for z in seite.eintraege]
        nummer = seite.weiter
        runden += 1
        if not seite.mehr:
            break

    assert gesehen == [str(n.id) for n in neue]
    assert runden == 3


def test_die_letzte_seite_ist_nicht_mehr(db, person, stand):
    vorher = nach(db)
    mail(db, person, stand["konto"], stand["eingang"], 10)
    mail(db, person, stand["konto"], stand["eingang"], 11)

    assert seit(db, person, vorher, grenze=2).mehr is False


def test_ohne_eigene_aenderung_rueckt_die_nummer_trotzdem_vor(db, person, stand):
    """⚠️ **Die Nummern gehören allen.** Bliebe eine ruhige App stehen, fiele sie
    irgendwann unter den Horizont und verlöre ihren Speicher, ohne etwas
    verpasst zu haben."""
    zweiter, _ = zweiten_benutzer_anlegen(db)
    konto, eingang, _ = postfach(db, zweiter, "b@example.com")
    jetzt = nach(db)
    mail(db, zweiter, konto, eingang, 1)

    seite = seit(db, person, jetzt)

    assert seite.eintraege == []
    assert seite.weiter == nach(db) > jetzt


def test_fremde_aenderungen_bleiben_fremd(db, person, stand):
    zweiter, _ = zweiten_benutzer_anlegen(db)
    konto, eingang, _ = postfach(db, zweiter, "b@example.com")
    vorher = nach(db)
    n = mail(db, zweiter, konto, eingang, 1)

    assert seit(db, person, vorher).eintraege == []
    assert arten(seit(db, zweiter, vorher)) == [("nachricht", str(n.id), False)]


def test_eine_nummer_unter_dem_horizont_liest_von_vorn(db, person, stand):
    einstellung_schreiben(db, aenderungen.SCHLUESSEL_HORIZONT, str(nach(db)))

    with pytest.raises(aenderungen.AenderungFehler) as f:
        seit(db, person, nach(db) - 1)

    assert str(f.value) == "app_von_vorn"
    assert seit(db, person, nach(db)).eintraege == [], "Genau am Horizont fehlt nichts."


def test_eine_nummer_ueber_dem_stand_liest_von_vorn(db, person, stand):
    """⚠️ **Eine eingespielte Sicherung.** Sonst wartete die App auf Nummern, die
    es erst in Monaten gibt, und hielte Mails, die fort sind."""
    with pytest.raises(aenderungen.AenderungFehler):
        seit(db, person, nach(db) + 1)


# --- Aufräumen ------------------------------------------------------------- #


def test_altes_faellt_und_der_horizont_rueckt_nach(db, person, stand):
    alt = nach(db)
    spaeter = time.time() + (aenderungen.FRIST_TAGE + 1) * 86_400
    mail_danach = alt

    assert aenderungen.aufraeumen(db, jetzt=spaeter) > 0

    assert db.query(Aenderung).count() == 0
    with pytest.raises(aenderungen.AenderungFehler):
        seit(db, person, mail_danach - 1)
    assert seit(db, person, alt).eintraege == []


def test_junges_bleibt(db, person, stand):
    assert aenderungen.aufraeumen(db) == 0
    assert db.query(Aenderung).count() > 0


def test_die_nummern_fangen_nach_dem_aufraeumen_nicht_von_vorn_an(db, person, stand):
    alt = nach(db)
    aenderungen.aufraeumen(db, jetzt=time.time() + (aenderungen.FRIST_TAGE + 1) * 86_400)

    n = mail(db, person, stand["konto"], stand["eingang"], 2)

    assert nach(db) > alt
    assert db.query(Aenderung).filter_by(kennung=str(n.id)).one().seq > alt


def test_die_schlanke_sicherung_nimmt_den_feed_nicht_mit(db, person, stand, tmp_path):
    """⚠️ **Die Mails kommen nach dem Einspielen mit neuen Kennungen zurück.** Eine
    App darf ihre alten Nummern dann nicht mehr benutzen."""
    from app.services import sicherung

    kopie = tmp_path / "kopie.db"
    verbindung = db.connection().connection
    ziel = sqlite3.connect(kopie)
    verbindung.backup(ziel)
    ziel.close()
    stand_vorher = nach(db)

    sicherung._schlank_machen(kopie)

    pruefung = sqlite3.connect(kopie)
    zeilen = pruefung.execute("select count(*) from aenderung").fetchone()[0]
    horizont = pruefung.execute(
        "select wert from einstellung where schluessel = 'aenderung_horizont'"
    ).fetchone()[0]
    pruefung.close()
    assert zeilen == 0
    assert int(horizont) >= stand_vorher


# --- Über die Adresse ------------------------------------------------------ #


@pytest.fixture
def bearer(klient, person):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://testserver") as c:
        token = abholen(c, koppeln(klient)).json()["key"]
        yield c, {"Authorization": f"Bearer {token}"}


def test_die_adresse_bringt_die_listenzeile(db, person, stand, bearer):
    c, kopf = bearer
    start = c.get(f"{PFAD}/changes", headers=kopf).json()
    assert start["eintraege"] == []

    db.execute(update(Nachricht).where(Nachricht.id == stand["eins"].id).values(gelesen=True))
    db.commit()

    antwort = c.get(f"{PFAD}/changes", headers=kopf, params={"since": start["weiter"]}).json()

    eintrag = antwort["eintraege"][0]
    assert eintrag["art"] == "nachricht"
    assert eintrag["nachricht"]["betreff"] == "Erste"
    assert eintrag["nachricht"]["gelesen"] is True
    assert antwort["mehr"] is False
    assert antwort["weiter"] == antwort["stand"]


def test_die_adresse_sagt_von_vorn(person, stand, bearer):
    c, kopf = bearer
    antwort = c.get(f"{PFAD}/changes", headers=kopf, params={"since": 10**9})
    assert antwort.status_code == 410
    assert antwort.json()["detail"] == "app_von_vorn"


def test_eine_weg_zeile_traegt_keinen_inhalt(db, person, stand, bearer):
    c, kopf = bearer
    start = c.get(f"{PFAD}/changes", headers=kopf).json()["weiter"]
    kennung = stand["eins"].id
    db.execute(delete(Nachricht).where(Nachricht.id == kennung))
    db.commit()

    eintrag = c.get(f"{PFAD}/changes", headers=kopf, params={"since": start}).json()["eintraege"][0]

    assert eintrag == {
        "seq": eintrag["seq"],
        "art": "nachricht",
        "kennung": str(kennung),
        "konto_id": stand["konto"].id,
        "weg": True,
        "nachricht": None,
    }


def test_die_grenze_wird_geprueft(person, bearer):
    c, kopf = bearer
    assert c.get(f"{PFAD}/changes", headers=kopf, params={"limit": 501}).status_code == 422


