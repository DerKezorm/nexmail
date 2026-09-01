"""Die Suche.

⚠️ **Zwei Dinge machen eine Suche unbrauchbar**, und beide sind still:

1. Sie findet die Mail eines **anderen Benutzers**. Der Volltextindex kennt
   keine Benutzer — die Einschränkung muss ausdrücklich davor.
2. Sie **stürzt an einem Bindestrich ab**. „Mayer-Schulz" ist für FTS5 Syntax,
   nicht Text, und der Fehler kommt als Serverfehler zurück.

Dazu die Falle mit den Auslösern: Der Index wird von SQLite gepflegt, nicht von
Python. Wenn ein Auslöser fehlt oder falsch hängt, findet die Suche zu wenig,
ohne dass irgendwo etwas rot wird.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db import engine
from app.models import Benutzer, Konto, Nachricht, Ordner, neue_id
from app.services import benutzer as benutzerdienst, suche
from conftest import zweiten_benutzer_anlegen


@pytest.fixture
def person(db) -> Benutzer:
    return benutzerdienst.anlegen(db, "betreiber", "sehr-geheim-123")


def _postfach(db, person: Benutzer, adresse: str = "ich@example.org") -> tuple[Konto, Ordner]:
    konto = Konto(
        id=neue_id(),
        benutzer_id=person.id,
        anzeigename="Ich",
        adresse=adresse,
        imap_server="imap.example.org",
        imap_port=993,
        imap_sicherheit="ssl",
        imap_benutzer=adresse,
        smtp_server="smtp.example.org",
        smtp_port=465,
        smtp_sicherheit="ssl",
        smtp_benutzer=adresse,
    )
    db.add(konto)
    db.flush()
    ordner = Ordner(konto_id=konto.id, pfad="INBOX", name="INBOX", rolle="posteingang")
    db.add(ordner)
    db.commit()
    return konto, ordner


def _mail(
    db,
    person: Benutzer,
    konto: Konto,
    ordner: Ordner,
    uid: int,
    betreff: str,
    von_name: str = "Absender",
    von_adresse: str = "wer@example.org",
    text_: str = "",
    anreisser: str = "",
) -> Nachricht:
    n = Nachricht(
        benutzer_id=person.id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=uid,
        betreff=betreff,
        von_name=von_name,
        von_adresse=von_adresse,
        anreisser=anreisser,
        koerper_text=text_,
        datum=datetime.now(timezone.utc) - timedelta(minutes=uid),
    )
    db.add(n)
    db.commit()
    return n


@pytest.fixture
def postfach(db, person):
    konto, ordner = _postfach(db, person)
    _mail(db, person, konto, ordner, 1, "Rechnung März", von_name="Müller")
    _mail(db, person, konto, ordner, 2, "Angebot Dachdecker", von_adresse="dach@example.org")
    _mail(db, person, konto, ordner, 3, "Urlaubsfotos", anreisser="Grüße vom Gardasee")
    return person, konto, ordner


# --- Was gefunden werden muss -------------------------------------------- #


def test_findet_ueber_den_betreff(db, postfach):
    person, _, _ = postfach
    treffer = suche.suchen(db, person, "Rechnung")
    assert [n.betreff for n in treffer] == ["Rechnung März"]


def test_findet_ueber_den_absender(db, postfach):
    person, _, _ = postfach
    assert len(suche.suchen(db, person, "dach@example.org")) == 1


def test_findet_im_anreisser(db, postfach):
    """Der Anreißer steht immer da — auch bei Mails, deren Text nie geholt wurde."""
    person, _, _ = postfach
    assert len(suche.suchen(db, person, "Gardasee")) == 1


def test_umlaute_muessen_nicht_getippt_werden(db, postfach):
    """⚠️ „Muller" findet „Müller". Sonst scheitert die Suche im deutschen Alltag."""
    person, _, _ = postfach
    assert len(suche.suchen(db, person, "Muller")) == 1
    assert len(suche.suchen(db, person, "Müller")) == 1


def test_wortanfang_genuegt(db, postfach):
    """Wer „rech" tippt, meint „Rechnung" — so verhält sich jedes Suchfeld."""
    person, _, _ = postfach
    assert len(suche.suchen(db, person, "rech")) == 1


# --- Was nicht umfallen darf --------------------------------------------- #


@pytest.mark.parametrize(
    "eingabe",
    ["Mayer-Schulz", '"Angebot"', "was?!", "^hoch", "a*b", "(klammer)", "[eckig]", "-", '"'],
)
def test_sonderzeichen_werfen_die_suche_nicht_um(db, postfach, eingabe):
    """⚠️ Für FTS5 ist das Syntax, nicht Text. Roh eingesetzt gibt es einen 500er."""
    person, _, _ = postfach
    suche.suchen(db, person, eingabe)  # kein Fehler ist das Ergebnis


def test_leere_eingabe_gibt_nichts_statt_alles(db, postfach):
    person, _, _ = postfach
    assert suche.suchen(db, person, "   ") == []


# --- Trennung ------------------------------------------------------------- #


def test_die_suche_findet_nie_die_post_des_anderen(db, postfach):
    """⚠️ **Der wichtigste Test der Datei.**

    Der Volltextindex geht über die ganze Tabelle und kennt keine Benutzer.
    Ohne die ausdrückliche Einschränkung liefert eine Suche nach einem
    Allerweltswort die Mails aller Benutzer.
    """
    person, _, _ = postfach
    anderer, _ = zweiten_benutzer_anlegen(db)
    konto2, ordner2 = _postfach(db, anderer, "anderer@example.org")
    _mail(db, anderer, konto2, ordner2, 1, "Rechnung März", von_name="Müller")

    meine = suche.suchen(db, person, "Rechnung")
    seine = suche.suchen(db, anderer, "Rechnung")

    assert len(meine) == 1
    assert len(seine) == 1
    assert meine[0].id != seine[0].id
    assert all(n.benutzer_id == person.id for n in meine)


# --- Bereiche -------------------------------------------------------------- #


def test_bereich_ordner_schraenkt_ein(db, postfach):
    person, konto, ordner = postfach
    zweiter = Ordner(konto_id=konto.id, pfad="Archiv", name="Archiv", rolle="archiv")
    db.add(zweiter)
    db.commit()
    _mail(db, person, konto, zweiter, 9, "Rechnung April")

    assert len(suche.suchen(db, person, "Rechnung", bereich="alle")) == 2
    assert len(suche.suchen(db, person, "Rechnung", bereich="ordner", ordner_id=ordner.id)) == 1


def test_bereich_postfach_schraenkt_ein(db, postfach):
    person, konto, _ = postfach
    konto2, ordner2 = _postfach(db, person, "zweites@example.org")
    _mail(db, person, konto2, ordner2, 1, "Rechnung Mai")

    assert len(suche.suchen(db, person, "Rechnung", bereich="alle")) == 2
    treffer = suche.suchen(db, person, "Rechnung", bereich="postfach", konto_id=konto.id)
    assert len(treffer) == 1


# --- Die Auslöser ---------------------------------------------------------- #


def test_ein_nachgeholter_text_wird_auffindbar(db, postfach):
    """⚠️ Texte kommen erst beim Öffnen. Ohne Änderungs-Auslöser blieben sie unsichtbar."""
    person, konto, ordner = postfach
    n = _mail(db, person, konto, ordner, 5, "Ohne Text")

    assert suche.suchen(db, person, "Hebebuehne") == []

    n.koerper_text = "Die Hebebuehne steht bereit."
    db.commit()

    assert len(suche.suchen(db, person, "Hebebuehne")) == 1


def test_gelesen_setzen_laesst_den_index_heil(db, postfach):
    """Der Änderungs-Auslöser hängt an einer Spaltenliste — er darf hier nicht feuern.

    Geprüft wird die Folge, nicht die Innerei: Nach dem Markieren muss dieselbe
    Suche noch dasselbe finden.
    """
    person, konto, ordner = postfach
    for n in db.query(Nachricht).all():
        n.gelesen = True
    db.commit()

    assert len(suche.suchen(db, person, "Rechnung")) == 1


def test_geloeschte_verschwinden_aus_dem_index(db, postfach):
    person, _, _ = postfach
    db.query(Nachricht).filter(Nachricht.betreff == "Rechnung März").delete()
    db.commit()

    assert suche.suchen(db, person, "Rechnung") == []


def test_index_laesst_sich_neu_bauen(db, postfach):
    """Nach einer Wiederherstellung ist das der einzige Weg zurück zur Suche.

    ⚠️ Die Sicherung bringt ``nachricht`` mit, aber kein Auslöser hat dabei
    gefeuert. Der Index ist dann leer, und die Suche findet nichts.
    """
    person, _, _ = postfach
    with engine.begin() as v:
        v.execute(text("INSERT INTO nachricht_fts(nachricht_fts) VALUES ('delete-all')"))

    assert suche.suchen(db, person, "Rechnung") == []

    suche.neu_aufbauen(db)

    assert len(suche.suchen(db, person, "Rechnung")) == 1


def test_ein_leerer_index_wird_beim_start_gefuellt(db, postfach):
    """⚠️ **Beim ersten Lauf genau so aufgefallen.**

    Der Index kam mit einem Update dazu, die Nachrichten waren älter — die
    Auslöser hatten für sie nie gefeuert. Die Suche fand null und sagte dazu
    nichts.
    """
    person, _, _ = postfach
    with engine.begin() as v:
        v.execute(text("INSERT INTO nachricht_fts(nachricht_fts) VALUES ('delete-all')"))
        v.execute(text("DELETE FROM einstellung WHERE schluessel = 'suche_index'"))
    assert suche.suchen(db, person, "Rechnung") == []

    # Das ist, was beim Start passiert.
    suche.schema_anlegen(engine)

    assert len(suche.suchen(db, person, "Rechnung")) == 1


def test_ein_gefuellter_index_wird_beim_start_nicht_neu_gebaut(db, postfach):
    """Sonst kostet jeder Neustart bei 250.000 Nachrichten spürbar Zeit."""
    person, konto, ordner = postfach
    # Eine Zeile am Index vorbei entfernen: Wird neu gebaut, ist sie weg.
    with engine.begin() as v:
        v.execute(text("INSERT INTO nachricht_fts(nachricht_fts, rowid, betreff, von_name, von_adresse, anreisser, koerper_text) VALUES ('delete', (SELECT id FROM nachricht WHERE betreff='Rechnung März'), 'Rechnung März', 'Müller', 'wer@example.org', '', '')"))

    suche.schema_anlegen(engine)

    # Nicht neu gebaut - der Eintrag fehlt weiterhin.
    assert suche.suchen(db, person, "Rechnung") == []
