"""Der Kartenleser und der Zeilen-Editor auf der Rohkarte: Er ändert, was
nexmail kennt, und lässt den Rest stehen. Das ist die Zusage, an der das
Zurückschreiben hängt — seit dem Felder-Schritt für alle Felder und die drei
Listen."""

from __future__ import annotations

import re

from app.services import vcard
from app.services.kontakte import felder_aus_vcard

APPLE = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "PRODID:-//Apple Inc.//iOS 26.0//EN\r\n"
    "N:Beispiel;Anna;Lena;Dr.;\r\n"
    "FN:\r\n"
    "NICKNAME:Anni\r\n"
    "ORG:Beispiel GmbH;Vertrieb\r\n"
    "TITLE:Leitung\r\n"
    "TEL;type=HOME;type=VOICE:0241 111\r\n"
    "item1.TEL;type=pref:0170 444\r\n"
    "item1.X-ABLabel:_$!<Mobile>!$_\r\n"
    "item2.EMAIL;type=INTERNET;type=pref:Anna@Example.org\r\n"
    "item2.X-ABLabel:_$!<Home>!$_\r\n"
    "EMAIL;type=INTERNET;type=WORK:anna.arbeit@example.org\r\n"
    "item3.ADR;type=HOME;type=pref:;;Beispielstraße 12;Berlin;;10115;Deutschland\r\n"
    "item3.X-ABADR:de\r\n"
    "BDAY;value=date:1980-04-12\r\n"
    "URL;type=pref:https://example.org/anna\r\n"
    "item4.X-ABDATE;type=pref:2000-06-14\r\n"
    "item4.X-ABLabel:_$!<Anniversary>!$_\r\n"
    "X-SOCIALPROFILE;type=mastodon;x-user=anna:https://example.social/@anna\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD\r\n"
    "X-APPLE-SUBLOCALITY:Beispielstadt\r\n"
    "UID:11111111-2222-3333-4444-555555555555\r\n"
    "END:VCARD\r\n"
)

FREMD = (
    "PRODID:-//Apple Inc.//iOS 26.0//EN",
    "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD",
    "X-APPLE-SUBLOCALITY:Beispielstadt",
    "item4.X-ABDATE;type=pref:2000-06-14",
    "item4.X-ABLabel:_$!<Anniversary>!$_",
    "X-SOCIALPROFILE;type=mastodon;x-user=anna:https://example.social/@anna",
    "item3.X-ABADR:de",
    "UID:11111111-2222-3333-4444-555555555555",
)


def _zeilen(text: str) -> list[str]:
    return [z for z in vcard.entfalten(text) if z]


def _gelesen() -> dict:
    """Der Feldersatz, wie die Zeile ihn nach dem Abgleich trüge."""
    g = vcard.lesen(APPLE)
    return {**{k: g[k] for k in vcard.FELDER}, **{k: g[k] for k in vcard.LISTEN}}


def _nummer(nummer: str, art: str = "", beschriftung: str = "", bevorzugt: bool = False) -> dict:
    return {"nummer": nummer, "art": art, "beschriftung": beschriftung, "bevorzugt": bevorzugt}


# --- Lesen ----------------------------------------------------------------- #


def test_der_leser_kennt_alle_felder_und_listen():
    g = vcard.lesen(APPLE)
    assert (g["vorname"], g["nachname"], g["name"]) == ("Anna", "Beispiel", "Anna Beispiel")
    assert (g["spitzname"], g["firma"], g["abteilung"], g["titel"]) == ("Anni", "Beispiel GmbH", "Vertrieb", "Leitung")
    assert (g["geburtstag"], g["webseite"]) == ("1980-04-12", "https://example.org/anna")
    assert g["nummern"] == [_nummer("0241 111", "home"), _nummer("0170 444", "cell", bevorzugt=True)]
    assert g["adressen"] == [
        {"adresse": "anna@example.org", "art": "home", "beschriftung": "", "bevorzugt": True},
        {"adresse": "anna.arbeit@example.org", "art": "work", "beschriftung": "", "bevorzugt": False},
    ]
    assert g["anschriften"][0]["strasse"] == "Beispielstraße 12"
    assert (g["anschriften"][0]["plz"], g["anschriften"][0]["ort"], g["anschriften"][0]["land"]) == ("10115", "Berlin", "Deutschland")
    assert g["anschriften"][0]["art"] == "home" and g["anschriften"][0]["bevorzugt"] is True
    # Das eine Feld: die Handynummer, die bevorzugte Adresse.
    assert (g["telefon"], g["adresse"]) == ("0170 444", "anna@example.org")


def test_apples_eigene_zeilen_stehen_unter_weiteres_lesbar():
    g = vcard.lesen(APPLE)
    assert {"art": "datum", "beschriftung": "Anniversary", "text": "2000-06-14"} in g["weiteres"]
    assert {"art": "social", "beschriftung": "mastodon", "text": "anna"} in g["weiteres"]


def test_eine_eigene_beschriftung_kommt_woertlich_an_apples_wort_wird_zur_art():
    karte = APPLE.replace("item1.X-ABLabel:_$!<Mobile>!$_", "item1.X-ABLabel:Zweitbüro")
    g = vcard.lesen(karte)
    assert g["nummern"][1] == _nummer("0170 444", "", "Zweitbüro", True)


def test_ein_geburtstag_ohne_jahr_wird_als_solcher_gelesen():
    """Apple schreibt das Jahr 1604 und sagt daneben, dass es keines ist."""
    karte = APPLE.replace("BDAY;value=date:1980-04-12", "BDAY;value=date:1604-04-12\r\nX-APPLE-OMIT-YEAR:1604")
    assert vcard.lesen(karte)["geburtstag"] == "--04-12"
    assert vcard.lesen(APPLE.replace("BDAY;value=date:1980-04-12", "BDAY:19800412"))["geburtstag"] == "1980-04-12"


def test_ein_firmen_kontakt_hat_keinen_vor_und_nachnamen():
    """⚠️ FN ist die Firma, N ist leer: „Polizei Beispielstadt" ist kein
    Vorname mit Nachnamen."""
    karte = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Polizei Beispielstadt\r\nN:;;;;\r\nORG:Polizei Beispielstadt\r\nTEL:110\r\nEND:VCARD\r\n"
    g = vcard.lesen(karte)
    assert (g["vorname"], g["nachname"], g["name"], g["firma"]) == ("", "", "Polizei Beispielstadt", "Polizei Beispielstadt")


def test_ein_name_nur_im_fn_wird_geteilt_wie_beim_schreiben():
    karte = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Anna Lena Muster\r\nEND:VCARD\r\n"
    g = vcard.lesen(karte)
    assert (g["vorname"], g["nachname"]) == ("Anna Lena", "Muster")


# --- Schreiben: was stehen bleibt ------------------------------------------ #


def test_unbekannte_zeilen_bleiben_in_reihenfolge_stehen():
    """⚠️ Der ganze Sinn: Foto, Jahrestag und Apples Zeilen überleben eine
    Änderung am Namen unverändert und an ihrem Platz."""
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "nachname": "Muster"})
    zeilen = _zeilen(neu)
    for fremd in FREMD:
        assert fremd in zeilen, fremd
    alt_fremd = [z for z in _zeilen(APPLE) if z in FREMD]
    neu_fremd = [z for z in zeilen if z in FREMD]
    assert neu_fremd == alt_fremd


def test_ohne_aenderung_bleibt_jede_zeile_woertlich():
    """⚠️ Nur was sich geändert hat, wird angefasst: Speichern ohne Änderung
    darf drüben keine Karte in Bewegung setzen. Nur FN (bei Apple leer) und
    REV dürfen anders sein."""
    neu = vcard.aktualisieren(APPLE, _gelesen())
    alt = [z for z in _zeilen(APPLE) if not z.startswith("FN:")]
    jetzt = [z for z in _zeilen(neu) if not z.startswith(("FN:", "REV:"))]
    assert jetzt == alt


# --- Name, Firma, Einzelfelder --------------------------------------------- #


def test_vor_und_nachname_schreiben_fn_und_n_und_lassen_apples_uebrige_teile():
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "vorname": "Anna Lena", "nachname": "Muster"})
    zeilen = _zeilen(neu)
    assert "FN:Anna Lena Muster" in zeilen
    assert "N:Muster;Anna Lena;Lena;Dr.;" in zeilen
    assert zeilen.count("FN:Anna Lena Muster") == 1 and sum(z.startswith("N:") for z in zeilen) == 1


def test_ein_unveraenderter_name_laesst_apples_n_stehen():
    """⚠️ Apple teilt den Namen selbst; wer ihn ungefragt neu schreibt, macht
    aus „van der Berg" einen anderen Menschen."""
    apple = APPLE.replace("N:Beispiel;Anna;Lena;Dr.;", "N:van der Berg;Anna;;;")
    g = vcard.lesen(apple)
    felder = {**{k: g[k] for k in vcard.FELDER}, **{k: g[k] for k in vcard.LISTEN}, "notiz": "x"}
    assert "N:van der Berg;Anna;;;" in _zeilen(vcard.aktualisieren(apple, felder))


def test_ein_unveraenderter_name_laesst_auch_apples_leerzeichen_in_n_stehen():
    """⚠️ Die Mutationsprobe „N immer neu schreiben" lief zuerst durch: Bei
    sauber geteilten Teilen sieht ein Neuschreiben genauso aus wie Stehen-
    lassen. Apple laesst Leerzeichen am Ende der Teile stehen; der Leser
    streift sie ab, und genau daran ist ein ungefragtes Neuschreiben zu
    erkennen."""
    apple = APPLE.replace("N:Beispiel;Anna;Lena;Dr.;", "N:Beispiel ;Anna ;;;")
    g = vcard.lesen(apple)
    assert (g["vorname"], g["nachname"]) == ("Anna", "Beispiel")
    felder = {**{k: g[k] for k in vcard.FELDER}, **{k: g[k] for k in vcard.LISTEN}, "notiz": "x"}
    assert "N:Beispiel ;Anna ;;;" in _zeilen(vcard.aktualisieren(apple, felder))


def test_ein_alter_aufrufer_mit_name_wird_am_letzten_leerzeichen_geteilt():
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "vorname": "", "nachname": "", "name": "Anna Lena Muster"})
    assert "N:Muster;Anna Lena;Lena;Dr.;" in _zeilen(neu)
    assert vcard.name_teilen("Werkstatt") == ("Werkstatt", "")


def test_ein_leeres_fn_wird_gefuellt_auch_ohne_namensaenderung():
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "notiz": "x"})
    assert "FN:Anna Beispiel" in _zeilen(neu)
    assert "FN:" not in _zeilen(neu)


def test_firma_und_abteilung_teilen_sich_org_der_rest_bleibt():
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "firma": "Muster AG"})
    assert "ORG:Muster AG;Vertrieb" in _zeilen(neu)
    # Ein dritter Teil (Apple: Team, Untergruppe) bleibt, wie er war.
    drei = APPLE.replace("ORG:Beispiel GmbH;Vertrieb", "ORG:Beispiel GmbH;Vertrieb;Team Nord")
    assert "ORG:Muster AG;Vertrieb;Team Nord" in _zeilen(vcard.aktualisieren(drei, {**_gelesen(), "firma": "Muster AG"}))
    ohne = vcard.aktualisieren(APPLE, {**_gelesen(), "firma": "Muster AG", "abteilung": ""})
    assert "ORG:Muster AG" in _zeilen(ohne)
    leer = vcard.aktualisieren(APPLE, {**_gelesen(), "firma": "", "abteilung": ""})
    assert not any(z.startswith("ORG") for z in _zeilen(leer))


def test_spitzname_position_geburtstag_und_webseite_werden_gesetzt_und_entfernt():
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "spitzname": "", "titel": "Vorstand", "geburtstag": "1981-01-02", "webseite": ""})
    zeilen = _zeilen(neu)
    assert not any(z.startswith("NICKNAME") for z in zeilen)
    assert "TITLE:Vorstand" in zeilen
    # Der Wert wechselt, Apples Parameter bleibt.
    assert "BDAY;value=date:1981-01-02" in zeilen
    assert not any(z.startswith("URL") for z in zeilen)
    frisch = vcard.aktualisieren("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:X\r\nEND:VCARD\r\n", {"vorname": "X", "geburtstag": "1990-05-06", "webseite": "https://example.org"})
    assert "BDAY;value=date:1990-05-06" in _zeilen(frisch) and "URL:https://example.org" in _zeilen(frisch)


# --- Die Listen ------------------------------------------------------------ #


def test_eine_geaenderte_nummer_ersetzt_ihre_zeile_die_andere_bleibt_woertlich():
    """⚠️ Wiedererkannt am Wert: Die Zeile des Festnetzes bleibt samt
    Parametern, die Handynummer geht als neue Zeile hinaus und die alte fällt
    samt Gruppe."""
    g = _gelesen()
    g["nummern"] = [_nummer("0241 111", "home"), _nummer("0170 999", "cell", bevorzugt=True)]
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen
    assert "TEL;type=CELL;type=VOICE:0170 999" in zeilen
    assert not any("0170 444" in z for z in zeilen)
    assert "item1.X-ABLabel:_$!<Mobile>!$_" not in zeilen
    assert sum(vcard._name_von(z) == "TEL" for z in zeilen) == 2
    assert felder_aus_vcard("\r\n".join(zeilen))["telefon"] == "0170 999"


def test_schreibweisen_einer_nummer_zaehlen_nicht_als_aenderung():
    g = _gelesen()
    g["nummern"][0]["nummer"] = "0241/111"
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen


def test_der_stern_bleibt_bei_nexmail_und_bewegt_die_karte_nicht():
    """⚠️ Apples ``pref`` traegt die zuerst eingetragene Nummer; nexmails
    Stern sagt, was die Liste zeigt. Wandert der Stern, aendert sich an der
    Karte nichts — sonst wanderte bei jedem Speichern ein Parameter, den
    niemand gesetzt hat."""
    g = _gelesen()
    g["nummern"] = [_nummer("0241 111", "home", bevorzugt=True), _nummer("0170 444", "cell")]
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen
    assert "item1.TEL;type=pref:0170 444" in zeilen
    # Und eine Zeile, deren Art wechselt, behaelt ihr pref.
    g["nummern"] = [_nummer("0241 111", "home"), _nummer("0170 444", "work", bevorzugt=True)]
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "item1.TEL;type=WORK;type=VOICE;type=pref:0170 444" in zeilen


def test_eine_eigene_beschriftung_bekommt_apples_gruppe():
    g = _gelesen()
    g["nummern"].append(_nummer("030 999", "", "Zweitbüro"))
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    i = next(i for i, z in enumerate(zeilen) if z.endswith(":030 999"))
    assert zeilen[i].startswith("item5.TEL;type=VOICE")
    assert zeilen[i + 1] == "item5.X-ABLabel:Zweitbüro"
    assert vcard.lesen("\r\n".join(zeilen))["nummern"][2] == _nummer("030 999", "", "Zweitbüro")


def test_sonstige_und_apples_woerter_gehen_in_apples_form_hinaus():
    g = _gelesen()
    g["nummern"].append(_nummer("030 1", "other"))
    g["nummern"].append(_nummer("030 2", "", "School"))
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "item5.X-ABLabel:_$!<Other>!$_" in zeilen
    assert "item6.X-ABLabel:_$!<School>!$_" in zeilen
    assert vcard.lesen("\r\n".join(zeilen))["nummern"][3] == _nummer("030 2", "", "School")


def test_eine_geloeschte_nummer_nimmt_ihre_gruppe_mit():
    g = _gelesen()
    g["nummern"] = [_nummer("0241 111", "home", bevorzugt=True)]
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert not any(z.startswith("item1.") for z in zeilen)
    assert "TEL;type=HOME;type=VOICE:0241 111" in zeilen


def test_adressen_werden_ohne_gross_klein_erkannt_und_die_arbeitsadresse_bleibt():
    g = _gelesen()
    g["adressen"] = [
        {"adresse": "anna.neu@example.org", "art": "home", "beschriftung": "", "bevorzugt": True},
        {"adresse": "ANNA.ARBEIT@example.org", "art": "work", "beschriftung": "", "bevorzugt": False},
    ]
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "EMAIL;type=INTERNET;type=WORK:anna.arbeit@example.org" in zeilen
    assert "EMAIL;type=INTERNET;type=HOME:anna.neu@example.org" in zeilen
    assert not any("Anna@Example.org" in z for z in zeilen)
    assert not any(z.startswith("item2.") for z in zeilen)


def test_eine_neue_anschrift_und_eine_geaenderte():
    g = _gelesen()
    g["anschriften"][0]["plz"] = "10117"
    g["anschriften"].append({**vcard.leere_anschrift(), "strasse": "Werkweg 1", "ort": "Hamburg", "plz": "20095", "land": "Deutschland", "art": "work"})
    zeilen = _zeilen(vcard.aktualisieren(APPLE, g))
    assert "ADR;type=HOME:;;Beispielstraße 12;Berlin;;10117;Deutschland" in zeilen
    assert "ADR;type=WORK:;;Werkweg 1;Hamburg;;20095;Deutschland" in zeilen
    # Die alte Anschrift fiel samt ihrer Gruppe, X-ABADR eingeschlossen.
    assert not any(z.startswith("item3.") for z in zeilen)
    assert len(vcard.lesen("\r\n".join(zeilen))["anschriften"]) == 2


def test_alte_einzelfelder_werden_zur_liste():
    """Der alte Weg: ``telefon`` und ``adresse`` einzeln, ohne Listen."""
    neu = vcard.felder_normieren({"name": "Jonas Keller", "telefon": "0170 1", "adresse": "Jonas@Example.org"})
    assert neu["nummern"] == [_nummer("0170 1", bevorzugt=True)]
    assert neu["adressen"] == [{"adresse": "jonas@example.org", "art": "", "beschriftung": "", "bevorzugt": True}]
    assert (neu["vorname"], neu["nachname"], neu["name"], neu["adresse"]) == ("Jonas", "Keller", "Jonas Keller", "jonas@example.org")
    # In eine bestehende Liste ersetzt das Einzelfeld den Eintrag mit Stern.
    liste = [_nummer("1", "home"), _nummer("2", "cell", bevorzugt=True)]
    assert vcard.einzel_einmischen(liste, "nummer", "3", vcard.nummer_kern)[1] == _nummer("3", "cell", bevorzugt=True)
    assert vcard.einzel_einmischen(liste, "nummer", "", vcard.nummer_kern) == [_nummer("1", "home")]


def test_genau_ein_stern_je_liste():
    neu = vcard.felder_normieren({"nummern": [_nummer("1"), _nummer("2")]})
    assert [n["bevorzugt"] for n in neu["nummern"]] == [True, False]
    zwei = vcard.felder_normieren({"nummern": [_nummer("1", bevorzugt=True), _nummer("2", bevorzugt=True)]})
    assert [n["bevorzugt"] for n in zwei["nummern"]] == [True, False]


# --- Text, Faltung, Kennung ------------------------------------------------ #


def test_trennzeichen_werden_maskiert_und_lesen_sich_zurueck():
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "firma": "Meier; Söhne", "notiz": "Zeile eins\nZeile zwei, mit Komma"})
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
    neu = vcard.aktualisieren(APPLE, {**_gelesen(), "notiz": notiz})
    for zeile in neu.split("\r\n"):
        assert len(zeile.encode("utf-8")) <= 75, zeile
    assert felder_aus_vcard(neu)["notiz"] == notiz


def test_uid_und_rev_werden_ergaenzt_eine_vorhandene_uid_bleibt():
    ohne = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Werkstatt\r\nN:;Werkstatt;;;\r\nEND:VCARD\r\n"
    neu = vcard.aktualisieren(ohne, {"vorname": "Werkstatt", "notiz": "x"}, uid="abc@nexmail")
    zeilen = _zeilen(neu)
    assert zeilen[2] == "UID:abc@nexmail"
    assert any(re.fullmatch(r"REV:\d{8}T\d{6}Z", z) for z in zeilen)
    mit = vcard.aktualisieren(APPLE, {**_gelesen(), "notiz": "x"}, uid="anders")
    assert "UID:11111111-2222-3333-4444-555555555555" in _zeilen(mit)
    assert "UID:anders" not in _zeilen(mit)
    # ⚠️ Der Export will keine erfundene Kennung: Sie wäre bei jedem Mal eine andere.
    ohne_uid = vcard.aktualisieren(ohne, {"vorname": "Werkstatt"}, uid_ergaenzen=False)
    assert not any(z.startswith("UID:") for z in _zeilen(ohne_uid))


def test_eine_neue_karte_traegt_alle_felder_und_endet_richtig():
    neu = vcard.neu_bauen(
        {
            "vorname": "Jonas", "nachname": "Keller", "firma": "Beispiel e.V.", "abteilung": "Vorstand",
            "notiz": "Vorstand", "geburtstag": "1990-01-02",
            "nummern": [_nummer("0170 1", "cell", bevorzugt=True)],
            "adressen": [{"adresse": "jonas@example.org", "art": "work", "beschriftung": "", "bevorzugt": True}],
        },
        uid="neu@nexmail",
    )
    assert neu.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:neu@nexmail\r\n")
    assert neu.endswith("END:VCARD\r\n")
    zeilen = _zeilen(neu)
    assert "FN:Jonas Keller" in zeilen and "N:Keller;Jonas;;;" in zeilen
    assert "EMAIL;type=INTERNET;type=WORK:jonas@example.org" in zeilen
    assert "ORG:Beispiel e.V.;Vorstand" in zeilen and "TEL;type=CELL;type=VOICE:0170 1" in zeilen
    assert "NOTE:Vorstand" in zeilen and "BDAY;value=date:1990-01-02" in zeilen
    g = vcard.lesen(neu)
    assert [n["nummer"] for n in g["nummern"]] == ["0170 1"] and g["telefon"] == "0170 1"


def test_eine_neue_karte_ohne_namen_nennt_die_firma_im_fn():
    neu = vcard.neu_bauen({"firma": "Polizei Beispielstadt", "telefon": "110"})
    zeilen = _zeilen(neu)
    assert "FN:Polizei Beispielstadt" in zeilen
    assert "N:;;;;" in zeilen
