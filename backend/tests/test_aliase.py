"""Absender-Aliasse: zweite Adressen im selben Postfach.

⚠️ **Die eine Stelle, an der es weh tut, ist die Prüfung beim Senden.** Die
gewünschte Adresse kommt aus dem Browser. Ohne Prüfung könnte jeder angemeldete
Benutzer eine Mail unter **jeder beliebigen** Adresse verschicken — der
Mailserver sieht nur unsere Anmeldung, nicht wer davorsitzt.
"""

from __future__ import annotations

import json

import pytest

from app.models import Konto
from app.services import aliase
from app.services.aliase import Alias, AliasFehler


def _konto(adresse: str = "anna@example.com", roh: str = "[]") -> Konto:
    """Ein Konto ohne Datenbank — geprüft wird der Dienst, nicht SQLAlchemy.

    ⚠️ Über den gewöhnlichen Konstruktor, nicht über ``__new__``: Der umgeht
    die Instrumentierung von SQLAlchemy, und schon das Setzen eines Feldes
    scheitert dann.
    """
    return Konto(id="abc", adresse=adresse, aliase=roh)


# --- Lesen und Schreiben -------------------------------------------------- #


def test_ohne_eintrag_gibt_es_keine_aliasse():
    assert aliase.lesen(_konto()) == []


def test_geschriebenes_kommt_zurueck():
    konto = _konto()
    aliase.schreiben(konto, [Alias("zweit@example.com", "Anna Zweit")])
    assert aliase.lesen(konto) == [Alias("zweit@example.com", "Anna Zweit")]


def test_kaputtes_json_kostet_nicht_das_postfach():
    """⚠️ Es kommt aus der eigenen Datenbank, aber ein halb eingespieltes
    Archiv ist denkbar. Dann gilt „keine Aliasse" statt einer Seite, die
    nicht lädt."""
    assert aliase.lesen(_konto(roh="{kaputt")) == []
    assert aliase.lesen(_konto(roh='"kein array"')) == []
    assert aliase.lesen(_konto(roh='[{"name": "ohne Adresse"}]')) == []


def test_die_adresse_wird_klein_gespeichert():
    """⚠️ Sonst stünden ``Max@…`` und ``max@…`` als zwei Zeilen da, die
    dasselbe tun — und die Wahl beim Antworten fiele auf gut Glück."""
    konto = _konto()
    aliase.schreiben(konto, [Alias("Zweit@Example.COM", "")])
    assert aliase.lesen(konto)[0].adresse == "zweit@example.com"


def test_die_hauptadresse_ist_kein_alias():
    """Sie steht ohnehin zur Wahl; zweimal in der Liste wären zwei gleiche
    Einträge."""
    konto = _konto("anna@example.com")
    aliase.schreiben(konto, [Alias("ANNA@example.com", "Doppelt")])
    assert aliase.lesen(konto) == []


def test_doppelte_fallen_weg():
    konto = _konto()
    aliase.schreiben(konto, [Alias("z@example.com", "Eins"), Alias("z@example.com", "Zwei")])
    assert [a.name for a in aliase.lesen(konto)] == ["Eins"]


def test_eine_kaputte_adresse_wird_abgewiesen():
    with pytest.raises(AliasFehler) as fehler:
        aliase.schreiben(_konto(), [Alias("kein-at-zeichen", "")])
    assert fehler.value.kennung == "alias_adresse_ungueltig"


def test_zu_viele_werden_abgewiesen():
    """⚠️ Gedeckelt, weil es mit dem Bestand wächst — dieselbe Regel wie
    überall in nexmail."""
    zu_viele = [Alias(f"a{i}@example.com", "") for i in range(aliase.MAX_ALIASE + 1)]
    with pytest.raises(AliasFehler) as fehler:
        aliase.schreiben(_konto(), zu_viele)
    assert fehler.value.kennung == "alias_zu_viele"


# --- Die Prüfung beim Senden ---------------------------------------------- #


def test_leer_heisst_hauptadresse():
    assert aliase.absender_pruefen(_konto(), "").adresse == "anna@example.com"


def test_ein_hinterlegter_alias_geht_durch():
    konto = _konto()
    aliase.schreiben(konto, [Alias("zweit@example.com", "Zweitname")])
    gewaehlt = aliase.absender_pruefen(konto, "Zweit@example.com")
    assert gewaehlt.adresse == "zweit@example.com"
    assert gewaehlt.name == "Zweitname"


def test_eine_fremde_adresse_wird_abgewiesen():
    """⚠️ **Die sicherheitsrelevante Zusicherung dieser Funktion.** Ohne sie
    verschickt nexmail Post unter jeder Adresse, die jemand in die Anfrage
    schreibt."""
    with pytest.raises(AliasFehler) as fehler:
        aliase.absender_pruefen(_konto(), "chef@fremde-firma.example")
    assert fehler.value.kennung == "alias_unbekannt"


def test_ein_geloeschter_alias_geht_nicht_mehr_durch():
    konto = _konto()
    aliase.schreiben(konto, [Alias("zweit@example.com", "")])
    aliase.schreiben(konto, [])
    with pytest.raises(AliasFehler):
        aliase.absender_pruefen(konto, "zweit@example.com")


# --- Die Wahl beim Antworten ---------------------------------------------- #


def test_die_antwort_kommt_von_der_angeschriebenen_adresse():
    konto = _konto()
    aliase.schreiben(konto, [Alias("verein@example.com", "Vorstand")])
    treffer = aliase.passend(konto, ["verein@example.com", "wer-anders@example.org"])
    assert treffer is not None
    assert treffer.adresse == "verein@example.com"


def test_die_hauptadresse_gewinnt():
    """⚠️ Waren beide angeschrieben, bleibt es bei der Vorgabe. Ein Alias soll
    sie nicht verdrängen, bloß weil er auch im Verteiler stand."""
    konto = _konto()
    aliase.schreiben(konto, [Alias("verein@example.com", "")])
    assert aliase.passend(konto, ["anna@example.com", "verein@example.com"]) is None


def test_ohne_treffer_bleibt_es_bei_der_hauptadresse():
    konto = _konto()
    aliase.schreiben(konto, [Alias("verein@example.com", "")])
    assert aliase.passend(konto, ["jemand@example.org"]) is None


def test_gross_und_klein_trennt_nicht():
    konto = _konto()
    aliase.schreiben(konto, [Alias("verein@example.com", "")])
    treffer = aliase.passend(konto, ["Verein@EXAMPLE.com"])
    assert treffer is not None


def test_die_gespeicherte_form_ist_eine_liste_von_objekten():
    """Damit ein späterer Leser weiß, was in der Spalte steht."""
    konto = _konto()
    aliase.schreiben(konto, [Alias("z@example.com", "Name")])
    assert json.loads(konto.aliase) == [{"adresse": "z@example.com", "name": "Name"}]


# --- Der Umschlag --------------------------------------------------------- #


def _mail(von: str) -> bytes:
    return f"From: {von}\r\nTo: wer@example.org\r\nSubject: x\r\n\r\nText\r\n".encode()


def test_der_umschlag_traegt_den_alias():
    """⚠️ **Umschlag und ``From`` müssen zusammenpassen.** Sonst geht ein
    Rückläufer an die falsche Adresse, und DMARC prüft die Ausrichtung beider
    Angaben — laufen sie auseinander, landet die Mail im Spamordner."""
    from app.services import senden

    konto = _konto()
    aliase.schreiben(konto, [Alias("verein@example.com", "Vorstand")])
    assert senden._umschlagabsender(konto, _mail("Vorstand <verein@example.com>")) == (
        "verein@example.com"
    )


def test_der_umschlag_bleibt_bei_der_hauptadresse():
    from app.services import senden

    konto = _konto()
    assert senden._umschlagabsender(konto, _mail("anna@example.com")) == "anna@example.com"


def test_ein_manipulierter_umschlag_faellt_auf_die_hauptadresse_zurueck():
    """⚠️ Die Datei liegt auf der Platte. Wer sie ändert, dürfte sonst über
    unsere Anmeldung unter fremdem Namen senden. Kein Fehler, sondern ein
    Rückfall — eine eingereihte Mail darf nicht steckenbleiben."""
    from app.services import senden

    konto = _konto()
    assert senden._umschlagabsender(konto, _mail("chef@fremde-firma.example")) == (
        "anna@example.com"
    )


def test_eine_mail_ohne_absenderkopf_bleibt_bei_der_hauptadresse():
    from app.services import senden

    konto = _konto()
    assert senden._umschlagabsender(konto, b"To: x@y.example\r\n\r\nText") == "anna@example.com"
