"""Regeln und Signaturen.

⚠️ **Zwei Fehler machen ein Regelwerk unbrauchbar**, und beide sind still:

1. Eine Regel **ohne Bedingung trifft auf alles zu** — dann räumt sie über
   Nacht den ganzen Posteingang leer.
2. Regeln laufen **bei jedem Abgleich über alles** statt nur über Neues — dann
   schieben sie Post zurück, die jemand von Hand woandershin geräumt hat.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.models import Benutzer, Konto, Nachricht, Ordner, Regel, neue_id
from app.services import benutzer as benutzerdienst, regeln, signaturen
from conftest import zweiten_benutzer_anlegen


@pytest.fixture
def person(db) -> Benutzer:
    return benutzerdienst.anlegen(db, "betreiber", "sehr-geheim-123")


@pytest.fixture
def postfach(db, person):
    konto = Konto(
        id=neue_id(),
        benutzer_id=person.id,
        anzeigename="Ich",
        adresse="ich@example.org",
        imap_server="imap.example.org",
        imap_port=993,
        imap_sicherheit="ssl",
        imap_benutzer="ich@example.org",
        smtp_server="smtp.example.org",
        smtp_port=465,
        smtp_sicherheit="ssl",
        smtp_benutzer="ich@example.org",
    )
    db.add(konto)
    db.flush()
    posteingang = Ordner(konto_id=konto.id, pfad="INBOX", name="INBOX", rolle="posteingang")
    archiv = Ordner(konto_id=konto.id, pfad="Archiv", name="Archiv", rolle="archiv")
    db.add_all([posteingang, archiv])
    db.commit()
    return person, konto, posteingang, archiv


def _mail(db, person, konto, ordner, uid, **felder) -> Nachricht:
    n = Nachricht(
        benutzer_id=person.id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=uid,
        betreff=felder.get("betreff", "Ohne"),
        von_name=felder.get("von_name", "Wer"),
        von_adresse=felder.get("von_adresse", "wer@example.org"),
        anreisser=felder.get("anreisser", ""),
        datum=datetime.now(timezone.utc),
    )
    db.add(n)
    db.commit()
    return n


def _regel(db, person, bedingungen, aktionen, **felder) -> Regel:
    r = Regel(
        benutzer_id=person.id,
        name=felder.get("name", "Test"),
        aktiv=felder.get("aktiv", True),
        reihenfolge=felder.get("reihenfolge", 0),
        konto_id=felder.get("konto_id", ""),
        verknuepfung=felder.get("verknuepfung", "und"),
        bedingungen_json=json.dumps(bedingungen),
        aktionen_json=json.dumps(aktionen),
        stopp=felder.get("stopp", False),
    )
    db.add(r)
    db.commit()
    return r


# --- Treffen --------------------------------------------------------------- #


def test_trifft_auf_den_absender(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, von_adresse="werbung@shop.example")
    r = _regel(db, person, [{"feld": "von", "vergleich": "enthaelt", "wert": "shop.example"}], [])

    assert regeln.regel_trifft(n, r) is True


def test_gross_und_klein_ist_egal(db, postfach):
    """Eine Regel, die an einem großen A scheitert, ist eine Falle."""
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="RECHNUNG Nr. 5")
    r = _regel(db, person, [{"feld": "betreff", "vergleich": "enthaelt", "wert": "rechnung"}], [])

    assert regeln.regel_trifft(n, r) is True


def test_und_verlangt_alle_bedingungen(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Rechnung", von_adresse="a@b.example")
    r = _regel(
        db,
        person,
        [
            {"feld": "betreff", "vergleich": "enthaelt", "wert": "Rechnung"},
            {"feld": "von", "vergleich": "enthaelt", "wert": "gibtesnicht"},
        ],
        [],
    )

    assert regeln.regel_trifft(n, r) is False


def test_oder_genuegt_eine(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Rechnung")
    r = _regel(
        db,
        person,
        [
            {"feld": "betreff", "vergleich": "enthaelt", "wert": "Rechnung"},
            {"feld": "von", "vergleich": "enthaelt", "wert": "gibtesnicht"},
        ],
        [],
        verknuepfung="oder",
    )

    assert regeln.regel_trifft(n, r) is True


def test_eine_regel_ohne_bedingung_trifft_auf_nichts(db, postfach):
    """⚠️ **Der gefährlichste Fall.**

    „Keine Bedingung" darf nicht „alles" heißen — sonst räumt eine halb
    angelegte Regel über Nacht den ganzen Posteingang leer.
    """
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1)
    r = _regel(db, person, [], [{"art": "loeschen"}])

    assert regeln.regel_trifft(n, r) is False


# --- Anwenden --------------------------------------------------------------- #


def test_gelesen_und_markiert(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Newsletter")
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "gelesen"}, {"art": "markieren"}],
    )

    regeln.anwenden(db, person, [n])

    assert n.gelesen is True
    assert n.markiert is True


def test_eine_abgeschaltete_regel_tut_nichts(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Newsletter")
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "gelesen"}],
        aktiv=False,
    )

    regeln.anwenden(db, person, [n])

    assert n.gelesen is False


def test_stopp_beendet_den_lauf(db, postfach):
    """⚠️ Ohne ``stopp`` macht die zweite Regel die erste wieder zunichte."""
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Newsletter")
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "gelesen"}],
        reihenfolge=1,
        stopp=True,
    )
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "markieren"}],
        reihenfolge=2,
    )

    regeln.anwenden(db, person, [n])

    assert n.gelesen is True
    assert n.markiert is False, "Die zweite Regel hätte nicht laufen dürfen."


def test_die_reihenfolge_entscheidet(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Newsletter")
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "markieren"}],
        reihenfolge=2,
        stopp=True,
    )
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "gelesen"}],
        reihenfolge=1,
        stopp=True,
    )

    regeln.anwenden(db, person, [n])

    assert n.gelesen is True
    assert n.markiert is False


def test_eine_regel_fuer_ein_anderes_postfach_greift_nicht(db, postfach):
    person, konto, posteingang, _ = postfach
    n = _mail(db, person, konto, posteingang, 1, betreff="Newsletter")
    _regel(
        db,
        person,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "gelesen"}],
        konto_id="ein-anderes",
    )

    regeln.anwenden(db, person, [n])

    assert n.gelesen is False


def test_regeln_eines_anderen_benutzers_greifen_nicht(db, postfach):
    """Die übliche Trennung — auch hier."""
    person, konto, posteingang, _ = postfach
    anderer, _ = zweiten_benutzer_anlegen(db)
    n = _mail(db, person, konto, posteingang, 1, betreff="Newsletter")
    _regel(
        db,
        anderer,
        [{"feld": "betreff", "vergleich": "enthaelt", "wert": "Newsletter"}],
        [{"art": "gelesen"}],
    )

    regeln.anwenden(db, person, [n])

    assert n.gelesen is False


# --- Prüfen der Eingabe ------------------------------------------------------ #


def test_eine_regel_ohne_bedingung_wird_abgewiesen():
    with pytest.raises(regeln.RegelFehler):
        regeln.pruefen([], [{"art": "gelesen"}])


def test_eine_regel_ohne_aktion_wird_abgewiesen():
    with pytest.raises(regeln.RegelFehler):
        regeln.pruefen([{"feld": "von", "vergleich": "enthaelt", "wert": "a"}], [])


def test_verschieben_ohne_ziel_wird_abgewiesen():
    with pytest.raises(regeln.RegelFehler):
        regeln.pruefen(
            [{"feld": "von", "vergleich": "enthaelt", "wert": "a"}], [{"art": "verschieben"}]
        )


def test_eine_leere_bedingung_wird_abgewiesen():
    with pytest.raises(regeln.RegelFehler):
        regeln.pruefen([{"feld": "von", "vergleich": "enthaelt", "wert": "   "}], [{"art": "gelesen"}])


# --- Signaturen --------------------------------------------------------------- #


def test_die_signatur_des_postfachs_schlaegt_die_allgemeine(db, postfach):
    """⚠️ Sonst steht die Firmenanschrift unter der Mail an die Familie."""
    person, konto, _, _ = postfach
    signaturen.anlegen(db, person, "Allgemein", "<p>Viele Grüße</p>", "", standard=True)
    signaturen.anlegen(db, person, "Firma", "<p>Mit freundlichen Grüßen</p>", konto.id, True)

    gefunden = signaturen.fuer_konto(db, person, konto.id)

    assert gefunden is not None
    assert gefunden.name == "Firma"


def test_ohne_eigene_greift_die_allgemeine(db, postfach):
    person, _konto, _, _ = postfach
    signaturen.anlegen(db, person, "Allgemein", "<p>Viele Grüße</p>", "", standard=True)

    assert signaturen.fuer_konto(db, person, "irgendein-konto").name == "Allgemein"


def test_es_gibt_immer_nur_eine_vorgabe(db, postfach):
    """⚠️ Zwei Vorgaben für dasselbe Postfach heißt: Es entscheidet der Zufall."""
    person, konto, _, _ = postfach
    erste = signaturen.anlegen(db, person, "Eins", "<p>A</p>", konto.id, standard=True)
    signaturen.anlegen(db, person, "Zwei", "<p>B</p>", konto.id, standard=True)

    db.refresh(erste)
    assert erste.standard is False


def test_eine_signatur_wird_bereinigt(db, postfach):
    """Sie geht denselben Weg hinaus wie eine Mail."""
    person, _konto, _, _ = postfach

    eintrag = signaturen.anlegen(
        db, person, "Böse", '<p>Hallo<script>alert(1)</script></p>', ""
    )

    assert "script" not in eintrag.html


def test_eine_fremde_signatur_gehoert_mir_nicht(db, postfach):
    person, _konto, _, _ = postfach
    anderer, _ = zweiten_benutzer_anlegen(db)
    seine = signaturen.anlegen(db, anderer, "Seine", "<p>X</p>", "")

    with pytest.raises(signaturen.SignaturFehler):
        signaturen.entfernen(db, person, seine.id)
