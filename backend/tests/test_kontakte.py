"""Das Adressbuch.

Drei Dinge, die hier still schiefgehen können:

1. **Eingesammeltes überschreibt Gepflegtes.** Wer „Oma" einträgt, bekommt beim
   nächsten Einsammeln „gertrud.mueller@example.org" — weil das im ``From``
   stand.
2. **Aufgeschnapptes lässt sich nicht mehr trennen.** Ohne die Herkunftsspalte
   setzt sich das Adressbuch mit Einmalempfängern zu und ist nicht aufräumbar.
3. **vCard-Sonderzeichen zerlegen die Datei.** „Müller, Gertrud" ist ohne
   Maskierung zwei Felder.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Benutzer, Konto, Nachricht, Ordner, neue_id
from app.services import benutzer as benutzerdienst, kontakte
from conftest import einrichten, zweiten_benutzer_anlegen


@pytest.fixture
def person(db) -> Benutzer:
    return benutzerdienst.anlegen(db, "betreiber", "sehr-geheim-123")


# --- Pflegen -------------------------------------------------------------- #


def test_anlegen_und_finden(db, person):
    kontakte.anlegen(db, person, "Anna@Example.ORG", "Anna Beispiel")
    alle = kontakte.meine(db, person)

    assert len(alle) == 1
    # ⚠️ Kleingeschrieben abgelegt: Ein Adressbuch mit „Anna@" und „anna@"
    # nebeneinander ist kaputt.
    assert alle[0].adresse == "anna@example.org"


def test_dieselbe_adresse_kommt_nicht_zweimal_hinein(db, person):
    kontakte.anlegen(db, person, "anna@example.org", "Anna")
    with pytest.raises(kontakte.KontaktFehler):
        kontakte.anlegen(db, person, "ANNA@example.org", "Anna nochmal")


def test_was_keine_adresse_ist_wird_abgewiesen(db, person):
    for unsinn in ("kein-at-zeichen", "@example.org", "anna@", "anna @ example.org"):
        with pytest.raises(kontakte.KontaktFehler):
            kontakte.anlegen(db, person, unsinn)


# --- Ohne Adresse ---------------------------------------------------------- #


def test_ein_kontakt_ohne_adresse_ist_erlaubt(db, person):
    """⚠️ Seit dem 05.09.2026. Die Werkstatt hat eine Nummer und kein Postfach.
    Anschreiben lässt sie sich nicht, aber sie steht im Buch und geht per
    CardDAV aufs Telefon. Und ein zweiter ohne Adresse steht daneben, statt an
    der Eindeutigkeit zu scheitern."""
    k = kontakte.anlegen(db, person, "", "Werkstatt Beispiel", telefon="030 1234")
    assert k.adresse == ""
    assert k.adressbuch_id is not None
    kontakte.anlegen(db, person, "", "Oma", telefon="030 9999")
    assert len(kontakte.meine(db, person)) == 2


def test_ein_kontakt_ganz_ohne_inhalt_wird_abgewiesen(db, person):
    """Eine Zeile ohne Name, Adresse, Nummer und Firma findet niemand wieder."""
    with pytest.raises(kontakte.KontaktFehler) as f:
        kontakte.anlegen(db, person, "", "", notiz="nur eine Notiz")
    assert str(f.value) == "kontakt_leer"
    assert kontakte.meine(db, person) == []


def test_die_adresse_laesst_sich_wieder_entfernen(db, person):
    k = kontakte.anlegen(db, person, "anna@example.org", "Anna", telefon="0123")
    kontakte.aendern(db, person, k.id, adresse="")
    assert k.adresse == ""
    # Aber nicht, wenn danach nichts mehr übrig bliebe. Und dann bleibt auch
    # der Rest unangefasst.
    with pytest.raises(kontakte.KontaktFehler) as f:
        kontakte.aendern(db, person, k.id, name="", telefon="")
    assert str(f.value) == "kontakt_leer"
    # ⚠️ Der naechste Schreibvorgang eines anderen darf die abgewiesene
    # Aenderung nicht mitnehmen: Geprueft wird, bevor die Zeile angefasst wird.
    kontakte.anlegen(db, person, "b@example.org", "Bernd")
    db.expire_all()
    assert k.name == "Anna" and k.telefon == "0123"


def test_ohne_adresse_wird_nicht_vorgeschlagen(db, person):
    """Die Vorschläge stehen im Adressfeld; wer dort die Werkstatt wählt,
    bekäme ein leeres Feld."""
    kontakte.anlegen(db, person, "", "Werkstatt Beispiel", telefon="030 1234")
    kontakte.anlegen(db, person, "werk@example.org", "Werkstatt Zwei")
    assert [k.name for k in kontakte.vorschlagen(db, person, "werk")] == ["Werkstatt Zwei"]


def test_die_suche_findet_die_nummer(db, person):
    kontakte.anlegen(db, person, "", "Werkstatt", telefon="030 1234")
    kontakte.anlegen(db, person, "anna@example.org", "Anna")
    assert [k.name for k in kontakte.meine(db, person, "1234")] == ["Werkstatt"]


def test_suche_geht_ueber_name_adresse_und_firma(db, person):
    kontakte.anlegen(db, person, "a@example.org", "Anna", firma="Dachdecker Meier")
    kontakte.anlegen(db, person, "b@example.org", "Bernd")

    assert len(kontakte.meine(db, person, "dachdecker")) == 1
    assert len(kontakte.meine(db, person, "bernd")) == 1
    assert len(kontakte.meine(db, person, "b@")) == 1


def test_ein_anderer_sieht_meine_kontakte_nicht(db, person):
    """Dieselbe Trennung wie überall — das Adressbuch ist keine Ausnahme."""
    kontakte.anlegen(db, person, "anna@example.org", "Anna")
    anderer, _ = zweiten_benutzer_anlegen(db)

    assert kontakte.meine(db, anderer) == []


# --- Vorschläge ------------------------------------------------------------ #


def test_vorschlaege_kommen_nach_haeufigkeit(db, person):
    """⚠️ Nicht alphabetisch. Wer „ma" tippt, meint den, dem er ständig schreibt."""
    selten = kontakte.anlegen(db, person, "maier@example.org", "Aaron Maier")
    oft = kontakte.anlegen(db, person, "martin@example.org", "Zacharias Martin")
    oft.verwendet = 40
    selten.verwendet = 1
    db.commit()

    vorschlaege = kontakte.vorschlagen(db, person, "ma")
    assert [v.adresse for v in vorschlaege][0] == "martin@example.org"


def test_leerer_anfang_schlaegt_nichts_vor(db, person):
    kontakte.anlegen(db, person, "anna@example.org", "Anna")
    assert kontakte.vorschlagen(db, person, "  ") == []


# --- Einsammeln ------------------------------------------------------------ #


def _postfach(db, person, rolle: str = "gesendet") -> tuple[Konto, Ordner]:
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
    ordner = Ordner(konto_id=konto.id, pfad=rolle, name=rolle, rolle=rolle)
    db.add(ordner)
    db.commit()
    return konto, ordner


def _mail(db, person, konto, ordner, uid, an_json: str, kopie_json: str = "[]"):
    db.add(
        Nachricht(
            benutzer_id=person.id,
            konto_id=konto.id,
            ordner_id=ordner.id,
            uid=uid,
            betreff=f"Mail {uid}",
            an_json=an_json,
            kopie_json=kopie_json,
            datum=datetime.now(timezone.utc),
        )
    )
    db.commit()


def test_einsammeln_nimmt_empfaenger_aus_gesendet(db, person):
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "Anna Beispiel", "a": "anna@example.org"}]')

    stand = kontakte.einsammeln(db, person)

    assert stand["neu"] == 1
    eintrag = kontakte.meine(db, person)[0]
    assert eintrag.adresse == "anna@example.org"
    assert eintrag.quelle == "gesammelt"


def test_einsammeln_ruehrt_den_posteingang_nicht_an(db, person):
    """⚠️ Sonst steht nach einer Woche jeder Newsletter-Absender im Adressbuch."""
    konto, posteingang = _postfach(db, person, rolle="posteingang")
    _mail(db, person, konto, posteingang, 1, '[{"n": "Werbung", "a": "spam@example.org"}]')

    assert kontakte.einsammeln(db, person)["neu"] == 0
    assert kontakte.meine(db, person) == []


def test_einsammeln_nimmt_die_eigene_adresse_nicht_auf(db, person):
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "Ich", "a": "ich@example.org"}]')

    assert kontakte.einsammeln(db, person)["neu"] == 0


def test_einsammeln_ueberschreibt_keinen_gepflegten_namen(db, person):
    """⚠️ **Der teure Fall.**

    Wer „Oma" einträgt, will nicht, dass daraus beim nächsten Einsammeln
    „Gertrud Müller" wird, weil das zufällig im ``From`` stand.
    """
    kontakte.anlegen(db, person, "oma@example.org", "Oma")
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "Gertrud Müller", "a": "oma@example.org"}]')

    kontakte.einsammeln(db, person)

    eintrag = kontakte.meine(db, person)[0]
    assert eintrag.name == "Oma"
    assert eintrag.quelle == "hand"


def test_einsammeln_zaehlt_beim_zweiten_mal_hoch_statt_zu_verdoppeln(db, person):
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "Anna", "a": "anna@example.org"}]')
    _mail(db, person, konto, ordner, 2, '[{"n": "Anna", "a": "anna@example.org"}]')

    kontakte.einsammeln(db, person)

    assert len(kontakte.meine(db, person)) == 1
    assert kontakte.meine(db, person)[0].verwendet >= 2


def test_gesammelte_lassen_sich_in_einem_zug_wegwerfen(db, person):
    """⚠️ Ohne das setzt sich das Adressbuch zu und lässt sich nicht aufräumen."""
    kontakte.anlegen(db, person, "gepflegt@example.org", "Wichtig")
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "Einmal", "a": "einmal@example.org"}]')
    kontakte.einsammeln(db, person)
    assert len(kontakte.meine(db, person)) == 2

    assert kontakte.gesammelte_entfernen(db, person) == 1

    uebrig = kontakte.meine(db, person)
    assert [k.adresse for k in uebrig] == ["gepflegt@example.org"]


def test_ein_angefasster_eintrag_gilt_als_gepflegt(db, person):
    """Wer einen aufgeschnappten Eintrag bearbeitet, will ihn behalten."""
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "", "a": "anna@example.org"}]')
    kontakte.einsammeln(db, person)
    eintrag = kontakte.meine(db, person)[0]

    kontakte.aendern(db, person, eintrag.id, name="Anna Beispiel")

    assert kontakte.gesammelte_entfernen(db, person) == 0
    assert kontakte.meine(db, person)[0].name == "Anna Beispiel"


# --- vCard ----------------------------------------------------------------- #


def test_vcard_maskiert_komma_und_semikolon(db, person):
    """⚠️ Ohne Maskierung zerfällt „Müller, Gertrud" in zwei Felder."""
    kontakte.anlegen(db, person, "g@example.org", "Müller, Gertrud", firma="Meier; Söhne")

    karte = kontakte.als_vcard(kontakte.meine(db, person))

    assert "FN:Müller\\, Gertrud" in karte
    assert "ORG:Meier\\; Söhne" in karte


def test_vcard_endet_mit_crlf(db, person):
    """RFC 6350 schreibt CRLF vor. Manche Programme sind nachsichtig, Outlook nicht."""
    kontakte.anlegen(db, person, "a@example.org", "Anna")
    assert kontakte.als_vcard(kontakte.meine(db, person)).endswith("\r\n")


def test_hin_und_zurueck_verliert_nichts(db, person):
    """Der Rundlauf: ausgeführt und wieder eingelesen muss dasselbe herauskommen."""
    kontakte.anlegen(
        db, person, "g@example.org", "Müller, Gertrud", firma="Meier; Söhne", telefon="0123 456"
    )
    karte = kontakte.als_vcard(kontakte.meine(db, person))

    anderer, _ = zweiten_benutzer_anlegen(db)
    kontakte.aus_vcard(db, anderer, karte)

    seiner = kontakte.meine(db, anderer)[0]
    assert seiner.name == "Müller, Gertrud"
    assert seiner.firma == "Meier; Söhne"
    assert seiner.telefon == "0123 456"


def test_gefaltete_zeilen_werden_zusammengesetzt(db, person):
    """⚠️ vCard bricht lange Werte um. Zeilenweise gelesen sind Namen abgeschnitten."""
    karte = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "FN:Ein sehr langer Name der umgebrochen\r\n"
        "  wurde\r\n"
        "EMAIL:lang@example.org\r\n"
        "END:VCARD\r\n"
    )
    kontakte.aus_vcard(db, person, karte)

    assert kontakte.meine(db, person)[0].name == "Ein sehr langer Name der umgebrochen wurde"


def test_vcard_ergaenzt_statt_zu_verdoppeln(db, person):
    kontakte.anlegen(db, person, "anna@example.org", "Anna")
    karte = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Anna Anders\r\n"
        "EMAIL:ANNA@example.org\r\nTEL:0123\r\nEND:VCARD\r\n"
    )

    stand = kontakte.aus_vcard(db, person, karte)

    assert stand == {"neu": 0, "ergaenzt": 1}
    eintrag = kontakte.meine(db, person)[0]
    # Der eigene Name bleibt: Eine fremde Datei weiß es nicht besser.
    assert eintrag.name == "Anna"
    # Was leer war, wird gefüllt.
    assert eintrag.telefon == "0123"


def test_eine_vcard_ohne_adresse_kommt_trotzdem_an(db, person):
    """⚠️ Bis zum 05.09.2026 wurde sie übersprungen. Die Werkstatt hat eine
    Nummer und kein Postfach; wer sie übergeht, hat ein Adressbuch, dem ein
    Drittel der Telefonliste fehlt."""
    karte = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:w1\r\nFN:Werkstatt Beispiel\r\n"
        "TEL:030 1234\r\nEND:VCARD\r\n"
    )
    assert kontakte.aus_vcard(db, person, karte) == {"neu": 1, "ergaenzt": 0}
    eintrag = kontakte.meine(db, person)[0]
    assert eintrag.adresse == "" and eintrag.telefon == "030 1234"
    assert eintrag.uid == "w1"


def test_dieselbe_datei_zweimal_verdoppelt_auch_ohne_adresse_nichts(db, person):
    """⚠️ Ohne Adresse gibt es keinen Schlüssel. Wiedererkannt wird an der UID
    der Karte, und ohne UID an Name und Nummer. Dieselbe Regel wie die
    Message-ID beim mbox-Import: Der zweite Anlauf darf nichts verdoppeln."""
    datei = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:w1\r\nFN:Werkstatt\r\nTEL:030 1234\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Oma\r\nTEL:030 9999\r\nEND:VCARD\r\n"
    )
    assert kontakte.aus_vcard(db, person, datei) == {"neu": 2, "ergaenzt": 0}
    assert kontakte.aus_vcard(db, person, datei) == {"neu": 0, "ergaenzt": 2}
    assert len(kontakte.meine(db, person)) == 2


def test_ein_leeres_fn_sperrt_den_namen_aus_n_nicht(db, person):
    """⚠️ **Apple schreibt ``FN:`` leer und den Namen nur in ``N``.** An 185
    echten iCloud-Karten gesehen; 149 kamen ohne Namen an, weil das leere FN
    den Namen setzte und das N danach uebersprungen wurde."""
    karte = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:\r\nN:Beispiel-Keller;Vera ;;;\r\n"
        "PRODID:-//Apple Inc.//iOS 18.0//EN\r\nORG:;\r\nTEL:+49 30 1234\r\nEND:VCARD\r\n"
    )
    felder = kontakte.felder_aus_vcard(karte)
    assert felder["name"] == "Vera Beispiel-Keller"
    assert felder.get("firma", "") == ""
    # ⚠️ Und andersherum: Steht das leere FN HINTER dem N, darf es den Namen
    # nicht wieder wegwischen. Beide Reihenfolgen kommen vor.
    hinten = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Keller;Jonas;;;\r\nFN:\r\nEND:VCARD\r\n"
    assert kontakte.felder_aus_vcard(hinten)["name"] == "Jonas Keller"


def test_n_wird_nach_stellung_gelesen_nicht_nach_fuellung(db, person):
    """``;Vorname;;;`` ist ein Vorname ohne Nachnamen, kein Nachname. Und ein
    Zweitname an dritter Stelle rückt nicht an die Stelle des Nachnamens."""
    assert kontakte.felder_aus_vcard("BEGIN:VCARD\r\nN:;Vera;;;\r\nEND:VCARD\r\n")["name"] == "Vera"
    assert kontakte.felder_aus_vcard("BEGIN:VCARD\r\nN:Keller;;;;\r\nEND:VCARD\r\n")["name"] == "Keller"
    assert kontakte.felder_aus_vcard("BEGIN:VCARD\r\nN:;Vera;Maria;;\r\nEND:VCARD\r\n")["name"] == "Vera"
    # Ein FN mit Inhalt gewinnt weiterhin, egal wo es steht.
    assert (
        kontakte.felder_aus_vcard("BEGIN:VCARD\r\nN:Keller;Jonas;;;\r\nFN:Dr. Jonas Keller\r\nEND:VCARD\r\n")["name"]
        == "Dr. Jonas Keller"
    )


def test_alle_nummern_kommen_mit_typen_und_beschriftung(db, person):
    """⚠️ Das Modell kennt eine Nummer, die Karte viele. Bis die Felder mehrere
    tragen, zeigt die Oberfläche die übrigen aus der Rohkarte."""
    karte = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jonas Keller\r\n"
        "TEL;type=HOME;type=VOICE;type=pref:0241 111\r\n"
        "item1.TEL;type=CELL;type=VOICE:+49 170 222\r\n"
        "item1.X-ABLabel:_$!<Mobile>!$_\r\n"
        "item2.TEL;type=VOICE:0241 333\r\n"
        "item2.X-ABLabel:Werkstatt\r\n"
        "TEL;CELL;VOICE:0170 444\r\n"
        "EMAIL;type=INTERNET;type=WORK:b@example.org\r\n"
        "item3.EMAIL;type=INTERNET;type=pref:Jonas@Example.org\r\n"
        "item3.X-ABLabel:Privat\r\n"
        "END:VCARD\r\n"
    )
    daten = kontakte.kontaktdaten_aus_vcard(karte)
    assert [(n["nummer"], n["typen"], n["beschriftung"]) for n in daten["nummern"]] == [
        ("0241 111", "home,voice,pref", ""),
        ("+49 170 222", "cell,voice", "Mobile"),
        ("0241 333", "voice", "Werkstatt"),
        ("0170 444", "cell,voice", ""),  # vCard 2.1: Typen ohne TYPE=
    ]
    assert [(a["adresse"], a["beschriftung"]) for a in daten["adressen"]] == [
        ("b@example.org", ""),
        ("jonas@example.org", "Privat"),
    ]


def test_das_eine_feld_bekommt_die_handynummer(db, person):
    """⚠️ Vorher gewann die erste Zeile der Karte, und bei Apple steht dort
    gern das Festnetz: „angezeigt wird nur seine normale Nummer"."""
    karte = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jonas Keller\r\n"
        "TEL;type=HOME;type=VOICE;type=pref:0241 111\r\n"
        "TEL;type=CELL;type=VOICE:+49 170 222\r\n"
        "EMAIL;type=INTERNET:erste@example.org\r\n"
        "EMAIL;type=INTERNET;type=pref:lieber@example.org\r\n"
        "END:VCARD\r\n"
    )
    felder = kontakte.felder_aus_vcard(karte)
    assert felder["telefon"] == "+49 170 222"
    # Ohne Handy die vom Anbieter markierte, sonst die erste.
    assert felder["adresse"] == "lieber@example.org"
    # ⚠️ Die markierte muss an ZWEITER Stelle stehen, sonst unterscheidet der
    # Test „pref gewinnt" nicht von „die erste gewinnt".
    nur_festnetz = karte.replace(
        "TEL;type=CELL;type=VOICE:+49 170 222\r\n", "TEL;type=WORK;type=VOICE:0241 999\r\n"
    ).replace(
        "TEL;type=HOME;type=VOICE;type=pref:0241 111\r\nTEL;type=WORK;type=VOICE:0241 999\r\n",
        "TEL;type=WORK;type=VOICE:0241 999\r\nTEL;type=HOME;type=VOICE;type=pref:0241 111\r\n",
    )
    assert kontakte.felder_aus_vcard(nur_festnetz)["telefon"] == "0241 111"


def test_der_import_hebt_die_karte_auf(db, person):
    """Die Rückfahrkarte gilt auch beim Einlesen: Was nexmail nicht kennt,
    wäre sonst mit dem Import weg."""
    karte = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Vera\r\nEMAIL:vera@example.org\r\nBDAY:1980-01-01\r\nEND:VCARD\r\n"
    kontakte.aus_vcard(db, person, karte)
    eintrag = kontakte.meine(db, person)[0]
    assert eintrag.roh.startswith("BEGIN:VCARD") and "BDAY:1980-01-01" in eintrag.roh


def test_ein_verbundener_kontakt_geht_als_original_hinaus(db, person):
    """⚠️ Ein Nachbau aus fünf Feldern wäre die halbe Karte. Ein lokaler
    Kontakt wird dagegen nachgebaut: Seine Felder dürfen geändert sein."""
    from app.models import Adressbuch

    buch = Adressbuch(benutzer_id=person.id, name="iCloud", art="carddav")
    db.add(buch)
    db.commit()
    original = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Vera\r\nEMAIL:vera@example.org\r\nPHOTO;ENCODING=b:abc\r\nEND:VCARD\r\n"
    kontakte.anlegen(db, person, "vera@example.org", "Vera")
    verbunden = kontakte.meine(db, person)[0]
    verbunden.adressbuch_id = buch.id
    verbunden.roh = original
    kontakte.anlegen(db, person, "jonas@example.org", "Jonas")
    lokal = [k for k in kontakte.meine(db, person) if k.name == "Jonas"][0]
    lokal.roh = "BEGIN:VCARD\r\nFN:Jonas alt\r\nEND:VCARD\r\n"
    db.commit()

    karte = kontakte.als_vcard(kontakte.meine(db, person), {buch.id})

    assert "PHOTO;ENCODING=b:abc" in karte
    assert "FN:Jonas\r\n" in karte and "Jonas alt" not in karte


def test_apples_gruppenzeilen_werden_gelesen(db, person):
    """⚠️ ``item1.TEL`` gehört zu ``item1.X-ABLabel``. Wer die Gruppe mitliest,
    findet weder Nummer noch Adresse. An einem echten iCloud-Buch aufgefallen."""
    karte = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Beispiel;Vera;;;\r\nFN:Vera Beispiel\r\n"
        "item1.EMAIL;type=INTERNET;type=pref:vera@example.org\r\n"
        "item1.X-ABLabel:Privat\r\n"
        "item2.TEL;type=pref:030 1234\r\n"
        "item2.X-ABLabel:Mutter\r\n"
        "END:VCARD\r\n"
    )
    felder = kontakte.felder_aus_vcard(karte)
    assert felder["adresse"] == "vera@example.org"
    assert felder["telefon"] == "030 1234"
    assert felder["name"] == "Vera Beispiel"


def test_eine_leere_vcard_wird_uebersprungen(db, person):
    karte = "BEGIN:VCARD\r\nVERSION:3.0\r\nNOTE:nur eine Notiz\r\nEND:VCARD\r\n"
    assert kontakte.aus_vcard(db, person, karte) == {"neu": 0, "ergaenzt": 0}
    assert kontakte.meine(db, person) == []


def test_ohne_adresse_schreibt_die_vcard_keine_email_zeile(db, person):
    kontakte.anlegen(db, person, "", "Werkstatt", telefon="030 1234")
    kontakte.anlegen(db, person, "", "", telefon="030 5555")
    karte = kontakte.als_vcard(kontakte.meine(db, person))
    assert "EMAIL" not in karte
    assert "FN:Werkstatt" in karte and "TEL:030 1234" in karte
    # Ohne Namen benennt die Nummer den Eintrag; FN ist Pflicht.
    assert "FN:030 5555" in karte


def test_ein_firmen_kontakt_heisst_in_der_vcard_nach_der_firma(db, person):
    """⚠️ Ein Firmen-Kontakt von Apple trägt seinen Namen in ORG und sonst
    keinen. Als Nummer betitelt findet ihn drüben niemand wieder."""
    kontakte.anlegen(db, person, "", "", firma="Beispiel GmbH", telefon="030 7777")
    karte = kontakte.als_vcard(kontakte.meine(db, person))
    assert "FN:Beispiel GmbH" in karte
    assert "FN:030 7777" not in karte


def test_die_uid_geht_mit_hinaus_und_kommt_wieder(db, person):
    """Die Rückfahrkarte für Einträge ohne Adresse: ausgeführt, beim anderen
    zweimal eingelesen, und es bleibt bei zwei Einträgen."""
    kontakte.anlegen(db, person, "", "Werkstatt", telefon="030 1234")
    kontakte.aus_vcard(
        db, person, "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:w1\r\nFN:Oma\r\nTEL:1\r\nEND:VCARD\r\n"
    )
    karte = kontakte.als_vcard(kontakte.meine(db, person))
    assert "UID:w1" in karte

    anderer, _ = zweiten_benutzer_anlegen(db)
    kontakte.aus_vcard(db, anderer, karte)
    kontakte.aus_vcard(db, anderer, karte)
    assert len(kontakte.meine(db, anderer)) == 2


def test_muell_wirft_den_import_nicht_um(db, person):
    """Eine kaputte Datei darf keinen Serverfehler geben."""
    kontakte.aus_vcard(db, person, "das ist\nkeine vcard\n:::\n")
    assert kontakte.meine(db, person) == []


# --- Die Adressen ---------------------------------------------------------- #


def test_gesammelte_wegwerfen_ist_erreichbar(klient):
    """⚠️ **Selbst hineingelaufen.**

    ``DELETE /gesammelte`` stand hinter ``DELETE /{kontakt_id}``. Starlette
    prüft die Regeln der Reihe nach, und ``{kontakt_id}`` passt auf **jedes**
    Wegstück — „gesammelte" landete dort, scheiterte an der Zahl und gab 422.
    Die eigentliche Adresse wurde nie erreicht, und der Fehler sah nach
    kaputter Eingabe aus.

    ⚠️ **Angemeldet geprüft, und das ist der Punkt.** Unangemeldet kommt in
    **beiden** Reihenfolgen 401: Die Anmeldeprüfung greift vor der
    Adressprüfung. Der erste Anlauf dieses Tests bestand deshalb hohl — die
    Mutationsprobe hat es gezeigt.
    """
    einrichten(klient)

    antwort = klient.delete("/api/kontakte/gesammelte")

    assert antwort.status_code == 200, (
        f"Erwartet 200, bekommen {antwort.status_code}. Bei 422 hat die "
        "Zahlen-Regel gegriffen und diese Adresse ist tot."
    )
    assert antwort.json() == {"entfernt": 0}


def test_vcard_ausfuehren_ist_erreichbar(klient):
    """Dieselbe Falle für ``GET /vcard`` — heute harmlos, morgen nicht."""
    einrichten(klient)

    antwort = klient.get("/api/kontakte/vcard")

    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("text/vcard")


# --- Gruppen ---------------------------------------------------------------- #


def _gruppe_mit_mitgliedern(db, person, name="Verein"):
    a = kontakte.anlegen(db, person, "anna@example.org", "Anna")
    b = kontakte.anlegen(db, person, "jonas@example.org", "Bernd")
    gruppe = kontakte.gruppe_anlegen(db, person, name)
    kontakte.mitglieder_setzen(db, person, gruppe.id, [a.id, b.id])
    return gruppe, a, b


def test_gruppe_anlegen_umbenennen_entfernen(db, person):
    gruppe, _, _ = _gruppe_mit_mitgliedern(db, person)

    stand = kontakte.gruppen(db, person)
    assert [g["name"] for g in stand] == ["Verein"]
    assert stand[0]["mitglieder"] == 2
    assert stand[0]["adressen"] == ["anna@example.org", "jonas@example.org"]

    kontakte.gruppe_umbenennen(db, person, gruppe.id, "Vorstand")
    assert kontakte.gruppen(db, person)[0]["name"] == "Vorstand"

    kontakte.gruppe_entfernen(db, person, gruppe.id)
    assert kontakte.gruppen(db, person) == []
    # Auch die Zuordnungen sind weg, nicht nur die Gruppe davor.
    assert _mitgliedszeilen(db, person) == 0


def test_ein_mitglied_ohne_adresse_zaehlt_mit_und_wird_nicht_adressiert(db, person):
    """⚠️ In der Mail stünde sonst ein leerer Empfänger."""
    anna = kontakte.anlegen(db, person, "anna@example.org", "Anna")
    werkstatt = kontakte.anlegen(db, person, "", "Werkstatt", telefon="1")
    gruppe = kontakte.gruppe_anlegen(db, person, "Verein")
    kontakte.mitglieder_setzen(db, person, gruppe.id, [anna.id, werkstatt.id])

    (eintrag,) = kontakte.gruppen(db, person)
    assert eintrag["mitglieder"] == 2
    assert eintrag["adressen"] == ["anna@example.org"]


def test_gruppe_loeschen_loescht_keine_kontakte(db, person):
    """⚠️ Die Gruppe zeigt auf ihre Mitglieder, sie besitzt sie nicht."""
    gruppe, _, _ = _gruppe_mit_mitgliedern(db, person)

    kontakte.gruppe_entfernen(db, person, gruppe.id)

    assert len(kontakte.meine(db, person)) == 2


def test_derselbe_gruppenname_kommt_nicht_zweimal_hinein(db, person):
    """Groß/klein trennt keine Gruppen — dieselbe Regel wie bei den Schlagworten."""
    kontakte.gruppe_anlegen(db, person, "Verein")
    with pytest.raises(kontakte.KontaktFehler):
        kontakte.gruppe_anlegen(db, person, "verein")
    with pytest.raises(kontakte.KontaktFehler):
        kontakte.gruppe_anlegen(db, person, "   ")


def test_mitglieder_setzen_ersetzt_den_bestand(db, person):
    gruppe, a, b = _gruppe_mit_mitgliedern(db, person)
    c = kontakte.anlegen(db, person, "clara@example.org", "Clara")

    kontakte.mitglieder_setzen(db, person, gruppe.id, [c.id, b.id, b.id])

    stand = kontakte.gruppen(db, person)[0]
    # b und c, ohne Doppel — a ist draußen, obwohl er vorher drin war.
    assert stand["mitglieder"] == 2
    assert sorted(stand["mitglied_ids"]) == sorted([b.id, c.id])
    assert a.id not in stand["mitglied_ids"]


def test_ein_fremder_kontakt_wird_kein_mitglied(db, person):
    """Eine fremde Kennung ist ein Fehler, kein Versehen zum Wegfiltern."""
    gruppe = kontakte.gruppe_anlegen(db, person, "Verein")
    anderer, _ = zweiten_benutzer_anlegen(db)
    fremder = kontakte.anlegen(db, anderer, "fremd@example.org", "Fremd")

    with pytest.raises(kontakte.KontaktFehler):
        kontakte.mitglieder_setzen(db, person, gruppe.id, [fremder.id])

    assert kontakte.gruppen(db, person)[0]["mitglieder"] == 0


def test_ein_anderer_sieht_meine_gruppen_nicht(db, person):
    """Die Trennung — Gruppen sind so persönlich wie das Adressbuch selbst."""
    gruppe, _, _ = _gruppe_mit_mitgliedern(db, person)
    anderer, _ = zweiten_benutzer_anlegen(db)

    assert kontakte.gruppen(db, anderer) == []
    # Und auch nicht anfassen: weder umbenennen noch löschen noch füllen.
    with pytest.raises(kontakte.KontaktFehler):
        kontakte.gruppe_umbenennen(db, anderer, gruppe.id, "meins jetzt")
    with pytest.raises(kontakte.KontaktFehler):
        kontakte.gruppe_entfernen(db, anderer, gruppe.id)
    with pytest.raises(kontakte.KontaktFehler):
        kontakte.mitglieder_setzen(db, anderer, gruppe.id, [])


def _mitgliedszeilen(db, person) -> int:
    """⚠️ In die Tabelle sehen, nicht in ``gruppen()``.

    ``gruppen()`` verknüpft mit ``kontakt`` — eine Zuordnung auf einen
    gelöschten Kontakt fällt dort aus dem Join und ist unsichtbar. Genau so
    bestand die erste Fassung dieses Tests **hohl**: Die Mutationsprobe
    (Aufräumen entfernt) blieb grün, weil der Join die Leiche versteckte.
    """
    from sqlalchemy import func, select

    from app.models import KontaktgruppeMitglied

    return (
        db.execute(
            select(func.count())
            .select_from(KontaktgruppeMitglied)
            .where(KontaktgruppeMitglied.benutzer_id == person.id)
        ).scalar()
        or 0
    )


def test_kontakt_loeschen_raeumt_die_mitgliedschaft(db, person):
    """⚠️ Sonst bleibt die Zuordnung als Leiche in der Tabelle stehen."""
    gruppe, a, _ = _gruppe_mit_mitgliedern(db, person)

    kontakte.entfernen(db, person, a.id)

    stand = kontakte.gruppen(db, person)[0]
    assert stand["mitglieder"] == 1
    assert a.id not in stand["mitglied_ids"]
    assert _mitgliedszeilen(db, person) == 1


def test_gesammelte_wegwerfen_raeumt_die_mitgliedschaften(db, person):
    """Derselbe Fall über den Sammel-Weg: Aufgeräumtes bleibt nicht in Gruppen."""
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, '[{"n": "Einmal", "a": "einmal@example.org"}]')
    kontakte.einsammeln(db, person)
    aufgeschnappt = kontakte.meine(db, person)[0]
    gruppe = kontakte.gruppe_anlegen(db, person, "Verein")
    kontakte.mitglieder_setzen(db, person, gruppe.id, [aufgeschnappt.id])

    kontakte.gesammelte_entfernen(db, person)

    assert kontakte.gruppen(db, person)[0]["mitglieder"] == 0
    assert _mitgliedszeilen(db, person) == 0
