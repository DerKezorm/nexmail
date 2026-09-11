"""Der Zeilen-Editor auf der Rohkarte: Er ändert, was nexmail kennt, und lässt
den Rest stehen. Das ist die Zusage, an der das Zurückschreiben hängt."""

from __future__ import annotations

import re

from app.services import vcard
from app.services.kontakte import felder_aus_vcard, kontaktdaten_aus_vcard

APPLE = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "PRODID:-//Apple Inc.//iOS 26.0//EN\r\n"
    "N:Beispiel;Anna;;;\r\n"
    "FN:\r\n"
    "ORG:Beispiel GmbH;Vertrieb\r\n"
    "TEL;type=HOME;type=VOICE:0241 111\r\n"
    "item1.TEL;type=pref:0170 444\r\n"
    "item1.X-ABLabel:_$!<Mobile>!$_\r\n"
    "item2.EMAIL;type=INTERNET;type=pref:Anna@Example.org\r\n"
    "item2.X-ABLabel:_$!<Home>!$_\r\n"
    "EMAIL;type=INTERNET:anna.arbeit@example.org\r\n"
    "BDAY:1980-04-12\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD\r\n"
    "X-APPLE-SUBLOCALITY:Beispielstadt\r\n"
    "UID:11111111-2222-3333-4444-555555555555\r\n"
    "END:VCARD\r\n"
)

VORHER = {
    "name": "Anna Beispiel",
    "adresse": "anna@example.org",
    "firma": "Beispiel GmbH",
    "telefon": "0170 444",
    "notiz": "",
}


def _zeilen(text: str) -> list[str]:
    return [z for z in vcard.entfalten(text) if z]


def test_unbekannte_zeilen_bleiben_in_reihenfolge_stehen():
    """⚠️ Der ganze Sinn: Foto, Geburtstag und Apples Zeilen überleben eine
    Änderung am Namen unverändert und an ihrem Platz."""
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "name": "Anna Muster"})
    zeilen = _zeilen(neu)
    for fremd in (
        "PRODID:-//Apple Inc.//iOS 26.0//EN",
        "BDAY:1980-04-12",
        "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD",
        "X-APPLE-SUBLOCALITY:Beispielstadt",
        "item1.X-ABLabel:_$!<Mobile>!$_",
        "UID:11111111-2222-3333-4444-555555555555",
    ):
        assert fremd in zeilen, fremd
    # Die Reihenfolge der fremden Zeilen ist die alte.
    alt_fremd = [z for z in _zeilen(APPLE) if z.split(":")[0].split(";")[0] in ("PRODID", "BDAY", "PHOTO", "X-APPLE-SUBLOCALITY")]
    neu_fremd = [z for z in zeilen if z.split(":")[0].split(";")[0] in ("PRODID", "BDAY", "PHOTO", "X-APPLE-SUBLOCALITY")]
    assert neu_fremd == alt_fremd


def test_der_name_schreibt_fn_und_n_nach_dem_letzten_leerzeichen():
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "name": "Anna Lena Muster"})
    zeilen = _zeilen(neu)
    assert "FN:Anna Lena Muster" in zeilen
    assert "N:Muster;Anna Lena;;;" in zeilen
    assert zeilen.count("FN:Anna Lena Muster") == 1 and sum(z.startswith("N:") for z in zeilen) == 1


def test_ein_einzelnes_wort_ist_ein_vorname():
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "name": "Werkstatt"})
    assert "N:;Werkstatt;;;" in _zeilen(neu)


def test_ein_unveraenderter_name_laesst_apples_n_stehen():
    """⚠️ Apple teilt den Namen selbst; wer ihn ungefragt neu teilt, macht aus
    „van der Berg" einen anderen Menschen."""
    apple = APPLE.replace("N:Beispiel;Anna;;;", "N:van der Berg;Anna;;;")
    neu = vcard.aktualisieren(apple, {**VORHER, "name": "Anna van der Berg"}, {**VORHER, "name": "Anna van der Berg", "notiz": "x"})
    assert "N:van der Berg;Anna;;;" in _zeilen(neu)


def test_ein_leeres_fn_wird_gefuellt_auch_ohne_namensaenderung():
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "notiz": "x"})
    assert "FN:Anna Beispiel" in _zeilen(neu)
    assert "FN:" not in _zeilen(neu)


def test_die_richtige_tel_zeile_wird_geaendert_die_andere_bleibt():
    """⚠️ Das Feld zeigt die Handynummer; geändert wird genau ihre Zeile, samt
    Gruppe und Parametern. Das Festnetz bleibt, wie es war."""
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "telefon": "0170 999"})
    zeilen = _zeilen(neu)
    assert "item1.TEL;type=pref:0170 999" in zeilen
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen
    assert sum(vcard._name_von(z) == "TEL" for z in zeilen) == 2
    # Und der Leser sieht die neue als bevorzugte.
    assert felder_aus_vcard(neu)["telefon"] == "0170 999"


def test_eine_leere_nummer_nimmt_nur_ihre_zeile_heraus():
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "telefon": ""})
    zeilen = _zeilen(neu)
    assert not any("0170 444" in z for z in zeilen)
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen


def test_eine_nummer_ohne_alte_zeile_kommt_dazu_statt_eine_fremde_zu_treffen():
    """Steht der alte Wert nicht mehr in der Karte (drüben geändert), darf die
    neue Nummer keine beliebige TEL-Zeile überschreiben."""
    neu = vcard.aktualisieren(APPLE, {**VORHER, "telefon": "0999 000"}, {**VORHER, "telefon": "0170 999"})
    zeilen = _zeilen(neu)
    assert "TEL:0170 999" in zeilen
    assert "item1.TEL;type=pref:0170 444" in zeilen
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen


def test_die_adresse_wird_ohne_gross_klein_gefunden():
    """Die Karte schreibt „Anna@Example.org", das Feld ist klein. Getroffen wird
    trotzdem die richtige Zeile, die Arbeitsadresse bleibt."""
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "adresse": "anna.neu@example.org"})
    zeilen = _zeilen(neu)
    assert "item2.EMAIL;type=INTERNET;type=pref:anna.neu@example.org" in zeilen
    assert "EMAIL;type=INTERNET:anna.arbeit@example.org" in zeilen
    assert not any("Anna@Example.org" in z for z in zeilen)


def test_eine_neue_adresse_bei_einer_karte_ohne_bekommt_eine_email_zeile():
    ohne = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Werkstatt\r\nN:;Werkstatt;;;\r\nTEL:030 1\r\nEND:VCARD\r\n"
    neu = vcard.aktualisieren(ohne, {"name": "Werkstatt", "telefon": "030 1"}, {"name": "Werkstatt", "telefon": "030 1", "adresse": "werkstatt@example.org"})
    assert "EMAIL;TYPE=INTERNET:werkstatt@example.org" in _zeilen(neu)


def test_die_firma_ersetzt_nur_den_ersten_teil_von_org():
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "firma": "Muster AG"})
    assert "ORG:Muster AG;Vertrieb" in _zeilen(neu)


def test_eine_leere_firma_ohne_abteilung_nimmt_org_heraus():
    einfach = APPLE.replace("ORG:Beispiel GmbH;Vertrieb", "ORG:Beispiel GmbH")
    neu = vcard.aktualisieren(einfach, VORHER, {**VORHER, "firma": ""})
    assert not any(z.startswith("ORG") for z in _zeilen(neu))


def test_trennzeichen_werden_maskiert_und_lesen_sich_zurueck():
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "firma": "Meier; Söhne", "notiz": "Zeile eins\nZeile zwei, mit Komma"})
    zeilen = _zeilen(neu)
    assert "ORG:Meier\\; Söhne;Vertrieb" in zeilen
    assert "NOTE:Zeile eins\\nZeile zwei\\, mit Komma" in zeilen
    felder = felder_aus_vcard(neu)
    assert felder["firma"] == "Meier; Söhne"
    assert felder["notiz"] == "Zeile eins\nZeile zwei, mit Komma"


def test_eine_lange_notiz_wird_gefaltet_und_entfaltet_ganz():
    """⚠️ Zeilen über 75 Oktett müssen umbrechen, und ein Umlaut darf dabei
    nicht zerschnitten werden."""
    notiz = "ä" * 120
    neu = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "notiz": notiz})
    for zeile in neu.split("\r\n"):
        assert len(zeile.encode("utf-8")) <= 75, zeile
    assert felder_aus_vcard(neu)["notiz"] == notiz


def test_uid_und_rev_werden_ergaenzt_eine_vorhandene_uid_bleibt():
    ohne = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Werkstatt\r\nN:;Werkstatt;;;\r\nEND:VCARD\r\n"
    neu = vcard.aktualisieren(ohne, {"name": "Werkstatt"}, {"name": "Werkstatt", "notiz": "x"}, uid="abc@nexmail")
    zeilen = _zeilen(neu)
    assert zeilen[2] == "UID:abc@nexmail"
    assert any(re.fullmatch(r"REV:\d{8}T\d{6}Z", z) for z in zeilen)
    mit = vcard.aktualisieren(APPLE, VORHER, {**VORHER, "notiz": "x"}, uid="anders")
    assert "UID:11111111-2222-3333-4444-555555555555" in _zeilen(mit)
    assert "UID:anders" not in _zeilen(mit)


def test_eine_neue_karte_traegt_alle_fuenf_felder_und_endet_richtig():
    neu = vcard.neu_bauen(
        {"name": "Jonas Keller", "adresse": "jonas@example.org", "firma": "Beispiel e.V.", "telefon": "0170 1", "notiz": "Vorstand"},
        uid="neu@nexmail",
    )
    assert neu.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:neu@nexmail\r\n")
    assert neu.endswith("END:VCARD\r\n")
    zeilen = _zeilen(neu)
    assert "FN:Jonas Keller" in zeilen and "N:Keller;Jonas;;;" in zeilen
    assert "EMAIL;TYPE=INTERNET:jonas@example.org" in zeilen
    assert "ORG:Beispiel e.V." in zeilen and "TEL:0170 1" in zeilen and "NOTE:Vorstand" in zeilen
    daten = kontaktdaten_aus_vcard(neu)
    assert [n["nummer"] for n in daten["nummern"]] == ["0170 1"]


def test_eine_neue_karte_ohne_namen_nennt_die_firma_im_fn():
    neu = vcard.neu_bauen({"firma": "Polizei Beispielstadt", "telefon": "110"})
    zeilen = _zeilen(neu)
    assert "FN:Polizei Beispielstadt" in zeilen
    assert "N:;;;;" in zeilen
