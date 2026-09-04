"""Adressbücher — wo ein Kontakt liegt.

⚠️ **Der teuerste Fehler hier wäre ein Kontakt ohne Buch.** Die Bücherspalte
zeigt ihn dann gar nicht: unsichtbar, ohne gelöscht zu sein. Das sieht aus wie
Datenverlust, und genau davor steht `nachtragen` beim Start.
"""

from __future__ import annotations

import pytest

from app.models import Adressbuch, Benutzer, Kontakt
from app.services import adressbuecher as dienst
from conftest import einrichten


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    return db.query(Benutzer).one()


def _kontakt(db, person, name="Vera Beispiel", **felder):
    k = Kontakt(benutzer_id=person.id, name=name, adresse=f"{name[0].lower()}@example.org", **felder)
    db.add(k)
    db.commit()
    return k


# --- Das lokale Buch ------------------------------------------------------ #


def test_es_entsteht_beim_ersten_zugriff(db, person):
    """⚠️ **Anlegen statt Fehler werfen.** Ein Benutzer ohne lokales Buch ist
    ein Zustand, den es nicht geben soll."""
    assert db.query(Adressbuch).count() == 0
    buch = dienst.lokales(db, person)
    assert buch.ist_lokal is True
    assert buch.benutzer_id == person.id


def test_es_entsteht_nur_einmal(db, person):
    erst = dienst.lokales(db, person)
    zweit = dienst.lokales(db, person)
    assert erst.id == zweit.id
    assert db.query(Adressbuch).count() == 1


def test_das_lokale_buch_steht_oben(db, person):
    """Es hält alles, was nur hier lebt — es gehört an den Anfang."""
    dienst.lokales(db, person)
    db.add(Adressbuch(benutzer_id=person.id, name="iCloud", art="carddav", reihenfolge=0))
    db.commit()
    assert dienst.meine(db, person)[0].ist_lokal is True


def test_das_lokale_buch_laesst_sich_nicht_entfernen(db, person):
    """⚠️ Danach hätten die Kontakte, die nur hier leben, keinen Ort mehr."""
    buch = dienst.lokales(db, person)
    with pytest.raises(dienst.BuchFehler) as f:
        dienst.entfernen(db, person, buch.id)
    assert str(f.value) == "adressbuch_lokal_bleibt"
    assert db.query(Adressbuch).count() == 1


# --- Der Nachtrag beim Start ---------------------------------------------- #


def test_der_nachtrag_ordnet_heimatlose_kontakte_ein(db, person):
    """Der Fall beim Update: Kontakte gibt es, Bücher noch nicht."""
    for name in ("Vera Beispiel", "Jonas Keller", "Alexandra Bergmann"):
        _kontakt(db, person, name)
    assert db.query(Kontakt).filter(Kontakt.adressbuch_id.is_(None)).count() == 3

    assert dienst.nachtragen(db) == 3

    buch = dienst.lokales(db, person)
    assert db.query(Kontakt).filter(Kontakt.adressbuch_id == buch.id).count() == 3
    assert db.query(Kontakt).filter(Kontakt.adressbuch_id.is_(None)).count() == 0


def test_der_nachtrag_fasst_eingeordnete_nicht_an(db, person):
    """⚠️ **Sonst risse ein zweiter Lauf verbundene Kontakte ins lokale Buch.**
    Er läuft zwar nur einmal — aber die Marke fällt bei jeder Wiederherstellung
    aus einer Sicherung, und dann liefe er wieder."""
    fremd = Adressbuch(benutzer_id=person.id, name="iCloud", art="carddav")
    db.add(fremd)
    db.commit()
    k = _kontakt(db, person, adressbuch_id=fremd.id)

    dienst.nachtragen(db)
    db.refresh(k)
    assert k.adressbuch_id == fremd.id


def test_der_nachtrag_trifft_jeden_benutzer(db, person):
    """⚠️ **Mit ZWEI Benutzern.** Mit einem sieht „alle" genauso aus wie
    „meiner", und die Mutationsprobe liefe durch."""
    zweiter = Benutzer(
        id="z" * 32, benutzername="zweiter", anzeigename="Zweiter", passwort_hash="x"
    )
    db.add(zweiter)
    db.commit()
    _kontakt(db, person, "Einer")
    _kontakt(db, zweiter, "Anderer")

    dienst.nachtragen(db)

    for wer in (person, zweiter):
        buch = dienst.lokales(db, wer)
        assert db.query(Kontakt).filter(Kontakt.adressbuch_id == buch.id).count() == 1


# --- Verschieben ---------------------------------------------------------- #


def test_verschieben_legt_den_kontakt_ins_andere_buch(db, person):
    fremd = Adressbuch(benutzer_id=person.id, name="iCloud", art="carddav")
    db.add(fremd)
    db.commit()
    k = _kontakt(db, person, adressbuch_id=dienst.lokales(db, person).id, quelle="gesammelt")

    dienst.verschieben(db, person, k.id, fremd.id)
    db.refresh(k)
    assert k.adressbuch_id == fremd.id


def test_verschieben_wirft_die_kennungen_des_anbieters_weg(db, person):
    """⚠️ Sie zeigen auf eine Karte beim alten Anbieter. Mitgenommen zeigten
    sie beim nächsten Abgleich auf etwas Fremdes."""
    a = Adressbuch(benutzer_id=person.id, name="A", art="carddav")
    b = Adressbuch(benutzer_id=person.id, name="B", art="carddav")
    db.add_all([a, b])
    db.commit()
    k = _kontakt(
        db, person, adressbuch_id=a.id, uid="abc", href="/a/abc.vcf", etag='"7"',
        roh="BEGIN:VCARD\r\nPHOTO:xyz\r\nEND:VCARD\r\n",
    )

    dienst.verschieben(db, person, k.id, b.id)
    db.refresh(k)
    assert k.uid == "" and k.href == "" and k.etag == ""
    # ⚠️ **`roh` bleibt.** Foto und Geburtstag gehören dem Menschen, nicht dem
    # Ort; wer sie beim Verschieben wegwirft, verliert sie für immer.
    assert "PHOTO:xyz" in k.roh


def test_ein_fremder_kontakt_laesst_sich_nicht_verschieben(db, person):
    zweiter = Benutzer(
        id="z" * 32, benutzername="zweiter", anzeigename="Zweiter", passwort_hash="x"
    )
    db.add(zweiter)
    db.commit()
    fremd = _kontakt(db, zweiter, "Fremder")

    with pytest.raises(dienst.BuchFehler) as f:
        dienst.verschieben(db, person, fremd.id, dienst.lokales(db, person).id)
    assert str(f.value) == "kontakt_nicht_gefunden"


def test_ein_fremdes_buch_ist_kein_ziel(db, person):
    zweiter = Benutzer(
        id="z" * 32, benutzername="zweiter", anzeigename="Zweiter", passwort_hash="x"
    )
    db.add(zweiter)
    db.commit()
    fremdes_buch = dienst.lokales(db, zweiter)
    k = _kontakt(db, person, adressbuch_id=dienst.lokales(db, person).id)

    with pytest.raises(dienst.BuchFehler) as f:
        dienst.verschieben(db, person, k.id, fremdes_buch.id)
    assert str(f.value) == "adressbuch_nicht_gefunden"


# --- Entfernen ------------------------------------------------------------ #


def test_ein_verbundenes_buch_nimmt_seine_kontakte_mit(db, person):
    fremd = Adressbuch(benutzer_id=person.id, name="iCloud", art="carddav")
    db.add(fremd)
    db.commit()
    _kontakt(db, person, "Drin", adressbuch_id=fremd.id)
    _kontakt(db, person, "Lokal", adressbuch_id=dienst.lokales(db, person).id)

    assert dienst.entfernen(db, person, fremd.id) == 1
    # ⚠️ Und der lokale bleibt stehen.
    assert db.query(Kontakt).count() == 1


def test_ein_fremdes_buch_laesst_sich_nicht_entfernen(db, person):
    zweiter = Benutzer(
        id="z" * 32, benutzername="zweiter", anzeigename="Zweiter", passwort_hash="x"
    )
    db.add(zweiter)
    db.commit()
    with pytest.raises(dienst.BuchFehler):
        dienst.entfernen(db, person, dienst.lokales(db, zweiter).id)


# --- Ändern --------------------------------------------------------------- #


def test_nicht_mitgeschickt_heisst_unveraendert(db, person):
    buch = dienst.aendern(db, person, dienst.lokales(db, person).id, name="Privat", farbe=3)
    dienst.aendern(db, person, buch.id, sichtbar=False)
    db.refresh(buch)
    assert buch.name == "Privat" and buch.farbe == 3 and buch.sichtbar is False


def test_die_farbe_bleibt_in_der_palette(db, person):
    """⚠️ Nie eine Farbe erfinden — dieselbe geprüfte Palette wie überall."""
    buch = dienst.lokales(db, person)
    assert dienst.aendern(db, person, buch.id, farbe=99).farbe == dienst.FARBEN
    assert dienst.aendern(db, person, buch.id, farbe=0).farbe == 1


def test_ein_leerer_name_wird_abgewiesen(db, person):
    with pytest.raises(dienst.BuchFehler) as f:
        dienst.aendern(db, person, dienst.lokales(db, person).id, name="   ")
    assert str(f.value) == "adressbuch_name_fehlt"
