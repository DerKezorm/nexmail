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
    for unsinn in ("kein-at-zeichen", "@example.org", "anna@", "anna @ example.org", ""):
        with pytest.raises(kontakte.KontaktFehler):
            kontakte.anlegen(db, person, unsinn)


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


def test_eine_vcard_ohne_adresse_wird_uebersprungen(db, person):
    karte = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Niemand\r\nEND:VCARD\r\n"
    assert kontakte.aus_vcard(db, person, karte) == {"neu": 0, "ergaenzt": 0}
    assert kontakte.meine(db, person) == []


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
