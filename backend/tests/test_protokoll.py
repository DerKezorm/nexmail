"""Das Protokoll.

⚠️ **Ein Protokoll wird weitergegeben** — an einen Fehlerbericht, in ein Forum,
an jemanden, der beim Suchen hilft. In nexmail liegen aber Postfach-Passwörter,
fremde Adressen und der Inhalt fremder Post. Was hier durchrutscht, rutscht
weiter.
"""

from __future__ import annotations

import logging

import pytest

from app.services import protokoll


# --- Was nie in der Datei stehen darf -------------------------------------- #


@pytest.mark.parametrize(
    "zeile",
    [
        'A001 LOGIN contact@example.org "sehr-geheim"',
        "AUTH PLAIN AGNvbnRhY3QAZ2VoZWlt",
        "password=sehr-geheim",
        "Kennwort: sehr-geheim",
        "token = abc123def",
    ],
)
def test_kein_passwort_kommt_durch(zeile):
    """⚠️ Der letzte Fangzaun. Richtig ist, es gar nicht erst zu schreiben."""
    sauber = protokoll.zensieren(zeile)

    assert "geheim" not in sauber, f"Passwort steht noch in der Zeile: {sauber}"
    assert "abc123def" not in sauber
    assert "***" in sauber


def test_der_zensor_haengt_an_jedem_handler(tmp_path, monkeypatch):
    """Nicht nur die Funktion — der Filter muss auch wirklich hängen."""
    protokoll.einrichten()
    wurzel = logging.getLogger()
    unsere = [h for h in wurzel.handlers if getattr(h, "_nexmail", False)]

    assert unsere, "Kein eigener Handler eingerichtet."
    for handler in unsere:
        arten = {type(f).__name__ for f in handler.filters}
        assert "_Zensor" in arten, "Ein Handler ohne Zensor — dort käme ein Passwort durch."


def test_ein_passwort_landet_nicht_in_der_datei():
    """Der Rundlauf: schreiben, lesen, nachsehen."""
    protokoll.einrichten()
    protokoll.leeren()

    logging.getLogger("nexmail.test").warning("A001 LOGIN wer@example.org %s", "streng-geheim")
    for handler in logging.getLogger().handlers:
        handler.flush()

    inhalt = protokoll.datei().read_text(encoding="utf-8", errors="replace")
    assert "streng-geheim" not in inhalt, "Das Passwort steht in der Protokolldatei."


def test_fremde_adressen_werden_gekuerzt():
    """⚠️ Mit wem der Betreiber schreibt, geht niemanden etwas an."""
    assert protokoll.adresse_kuerzen("anna.beispiel@example.org") == "a***@example.org"
    # Die Domäne bleibt: An ihr hängt fast jede Fehlersuche.
    assert protokoll.adresse_kuerzen("x@gmx.de").endswith("@gmx.de")
    assert protokoll.adresse_kuerzen("keine-adresse") == "***"


# --- Stufen ---------------------------------------------------------------- #


def test_die_vier_stufen_gibt_es():
    assert set(protokoll.STUFEN) == {"leise", "normal", "ausfuehrlich", "alles"}


def test_tiefe_stufen_bekommen_immer_einen_ablauf(db):
    """⚠️ **Sonst überschreibt sie binnen eines Tages, was man behalten wollte.**

    Die Datei ist ein Ringpuffer, und niemand denkt daran, die Stufe
    zurückzustellen.
    """
    protokoll.einrichten()

    stand = protokoll.stufe_setzen(db, "alles", minuten=0)

    assert stand.stufe == "alles"
    assert stand.bis, "Eine tiefe Stufe ohne Ablauf — die bleibt für immer an."


def test_normal_braucht_keinen_ablauf(db):
    protokoll.einrichten()
    stand = protokoll.stufe_setzen(db, "normal", minuten=0)
    assert stand.bis is None


def test_eine_abgelaufene_stufe_faellt_zurueck(db):
    from datetime import datetime, timedelta, timezone

    from app.db import einstellung_schreiben

    protokoll.einrichten()
    protokoll.stufe_setzen(db, "alles", minuten=30)
    # Ablauf in die Vergangenheit legen.
    einstellung_schreiben(
        db,
        protokoll.SCHLUESSEL_BIS,
        (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )

    assert protokoll.ablauf_pruefen(db) is True
    assert protokoll.aktuelle_stufe() == "normal"


def test_eine_laufende_stufe_bleibt(db):
    protokoll.einrichten()
    protokoll.stufe_setzen(db, "ausfuehrlich", minuten=120)

    assert protokoll.ablauf_pruefen(db) is False
    assert protokoll.aktuelle_stufe() == "ausfuehrlich"


def test_unbekannte_stufe_wird_abgewiesen(db):
    protokoll.einrichten()
    with pytest.raises(ValueError):
        protokoll.stufe_setzen(db, "sehr-laut")


# --- Lesen ------------------------------------------------------------------ #


def test_die_stufe_beim_lesen_meint_diese_und_hoeher():
    """⚠️ Die häufigste Falle: Wer „WARNING" wählt, sucht die Fehler — und
    bekäme sie bei einem Gleichheitsvergleich nicht zu sehen."""
    protokoll.einrichten()
    protokoll.stufe_anwenden("normal")
    protokoll.leeren()

    logging.getLogger("nexmail.test").warning("Eine Warnung.")
    logging.getLogger("nexmail.test").error("Ein Fehler.")
    for handler in logging.getLogger().handlers:
        handler.flush()

    zeilen = protokoll.lesen(stufe="WARNING")
    stufen = {z.stufe for z in zeilen}
    assert "ERROR" in stufen, "Die Fehler fehlen — genau die, die gesucht werden."
    assert "WARNING" in stufen


def test_die_vorgangsnummer_steht_in_der_zeile():
    """⚠️ Der Unterschied zwischen „irgendwann heute" und „bei diesem Klick"."""
    protokoll.einrichten()
    protokoll.leeren()

    marke = protokoll.vorgang_beginnen("abc12345")
    try:
        protokoll.wer_setzen("betreiber")
        logging.getLogger("nexmail.test").warning("Etwas ist passiert.")
    finally:
        protokoll.vorgang_beenden(marke)
    for handler in logging.getLogger().handlers:
        handler.flush()

    zeilen = protokoll.lesen()
    passend = [z for z in zeilen if z.meldung == "Etwas ist passiert."]
    assert passend, "Die Zeile fehlt."
    assert passend[0].vorgang == "abc12345"
    assert passend[0].benutzer == "betreiber"


def test_eine_anfrage_bekommt_eine_vorgangsnummer(klient):
    """Die Nummer geht auch zurück — die Oberfläche zeigt sie im Fehlerfall."""
    antwort = klient.get("/api/health")
    assert "x-nexmail-vorgang" in antwort.headers
    assert len(antwort.headers["x-nexmail-vorgang"]) == 8
