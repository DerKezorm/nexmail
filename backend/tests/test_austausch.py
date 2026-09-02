"""mbox lesen und schreiben — der Umzug von und zu Thunderbird.

⚠️ **mbox ist ein Format ohne Norm.** Vier Varianten, und sie unterscheiden
sich genau an der Stelle, die weh tut: wie eine Zeile maskiert wird, die im
Nachrichtentext mit ``From `` beginnt. Wer das falsch macht, zerschneidet eine
Mail mitten im Satz oder verfälscht ein Zitat — und sieht es erst, wenn der
Umzug schon gelaufen ist.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services import austausch


def _mbox(*teile: bytes) -> io.BufferedReader:
    return io.BytesIO(b"".join(teile))


def _eintrag(kopf: bytes, rumpf: bytes) -> bytes:
    return b"From wer@example.org Mon Sep  1 10:00:00 2026\r\n" + kopf + b"\r\n\r\n" + rumpf


# --- Lesen ---------------------------------------------------------------- #


def test_zwei_nachrichten_werden_getrennt():
    strom = _mbox(
        _eintrag(b"Subject: Eins", b"Inhalt eins.\r\n"),
        _eintrag(b"Subject: Zwei", b"Inhalt zwei.\r\n"),
    )
    raus = list(austausch.mbox_lesen(strom))
    assert len(raus) == 2
    assert b"Subject: Eins" in raus[0]
    assert b"Inhalt zwei." in raus[1]


def test_eine_from_zeile_im_text_zerschneidet_nichts():
    """⚠️ **Der Fehler, den jeder selbstgebaute mbox-Leser einmal macht.**

    Eine Zeile im Text, die mit ``From `` beginnt, sieht aus wie eine
    Trennzeile. mboxrd maskiert sie mit ``>``; wer beim Lesen nicht
    entmaskiert, zerschneidet die Mail mitten im Satz.
    """
    strom = _mbox(
        _eintrag(b"Subject: Eins", b"Zeile eins.\r\n>From hier geht es weiter.\r\nZeile drei.\r\n")
    )
    raus = list(austausch.mbox_lesen(strom))
    assert len(raus) == 1, "Die Mail wurde zerschnitten"
    assert b"\r\nFrom hier geht es weiter." in raus[0]


def test_ein_zitiertes_from_bleibt_zitiert():
    """⚠️ Es faellt genau EIN ``>`` weg, nie mehr.

    Wer alle entfernt, macht aus einem zitierten ``>From `` ein ``From `` und
    verfaelscht damit den Text der Mail.
    """
    strom = _mbox(_eintrag(b"Subject: Eins", b">>From Anja kam die Antwort.\r\n"))
    raus = list(austausch.mbox_lesen(strom))
    assert b">From Anja kam die Antwort." in raus[0]


def test_ein_wort_das_mit_from_anfaengt_trennt_nicht():
    """„Fromage" am Zeilenanfang ist keine Trennzeile."""
    strom = _mbox(_eintrag(b"Subject: Eins", b"Fromage steht hier.\r\nUnd weiter.\r\n"))
    assert len(list(austausch.mbox_lesen(strom))) == 1


def test_eine_leere_datei_gibt_nichts():
    assert list(austausch.mbox_lesen(_mbox(b""))) == []


def test_ein_block_darf_mitten_in_einer_zeile_enden(monkeypatch):
    """⚠️ **Gelesen wird in Bloecken, nicht in Zeilen.**

    Ein Block endet irgendwo — womoeglich mitten in ``From ``. Wer dann schon
    trennt, erzeugt aus einer Mail zwei. Der Test zwingt winzige Bloecke.
    """
    daten = b"".join(
        (
            _eintrag(b"Subject: Eins", b"Inhalt eins.\r\n"),
            _eintrag(b"Subject: Zwei", b"Inhalt zwei.\r\n"),
        )
    )

    class Zaeh(io.BytesIO):
        def read(self, _n=-1):  # noqa: ARG002
            return super().read(7)

    raus = list(austausch.mbox_lesen(Zaeh(daten)))
    assert len(raus) == 2
    assert b"Subject: Zwei" in raus[1]


# --- Kopfzeilen ----------------------------------------------------------- #


def test_die_kennung_wird_gefunden():
    roh = b"Subject: X\r\nMessage-ID: <abc@example.org>\r\n\r\nText"
    assert austausch.kennung_lesen(roh) == "<abc@example.org>"


def test_ohne_kennung_kommt_leer_zurueck():
    assert austausch.kennung_lesen(b"Subject: X\r\n\r\nText") == ""


def test_eine_kennung_im_RUMPF_zaehlt_nicht():
    """Sonst zieht ein zitierter Kopf die falsche Kennung."""
    roh = b"Subject: X\r\n\r\nMessage-ID: <falsch@example.org>"
    assert austausch.kennung_lesen(roh) == ""


@pytest.mark.parametrize(
    "kopf,erwartet",
    [
        (b"X-Mozilla-Status: 0001", [rb"\Seen"]),
        (b"X-Mozilla-Status: 0005", [rb"\Seen", rb"\Flagged"]),
        (b"X-Mozilla-Status: 0000", []),
        (b"Status: RO", [rb"\Seen"]),
        (b"Status: O", []),
        (b"Subject: ohne", []),
    ],
)
def test_gelesen_und_markiert_wandern_mit(kopf, erwartet):
    """⚠️ Ohne das ist nach dem Umzug alles ungelesen.

    Bei zehntausend Mails ist das Postfach damit unbrauchbar, und niemand
    liest sie einzeln nach.
    """
    roh = b"Subject: X\r\n" + kopf + b"\r\n\r\nText"
    assert austausch.flags_lesen(roh) == erwartet


# --- Schreiben ------------------------------------------------------------ #


def test_geschriebenes_laesst_sich_wieder_lesen():
    """Der eigentliche Beweis: hinaus und wieder herein, ohne Verlust."""
    urspruenglich = [
        b"Subject: Eins\r\n\r\nZeile.\r\nFrom hier weiter.\r\n",
        b"Subject: Zwei\r\n\r\n>From zitiert.\r\n",
    ]
    geschrieben = b"".join(austausch.als_mbox(iter(urspruenglich)))
    wieder = list(austausch.mbox_lesen(io.BytesIO(geschrieben)))

    assert len(wieder) == 2
    assert wieder[0].rstrip() == urspruenglich[0].rstrip()
    assert wieder[1].rstrip() == urspruenglich[1].rstrip()


def test_die_trennzeile_traegt_ein_datum():
    """Ohne Datum lesen manche Programme die Datei gar nicht ein."""
    erste = next(iter(austausch.als_mbox(iter([b"Subject: X\r\n\r\nText"]))))
    assert erste.startswith(b"From nexmail ")
    assert len(erste.split(b" ", 2)[2].strip()) > 10


# --- ZIP ------------------------------------------------------------------ #


def test_zip_traegt_je_eine_eml():
    daten = austausch.als_zip(iter([("Rechnung", b"Subject: Rechnung\r\n\r\nX")]))
    with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
        assert archiv.namelist() == ["Rechnung.eml"]
        assert archiv.read("Rechnung.eml").startswith(b"Subject: Rechnung")


def test_gleiche_betreffe_ueberschreiben_sich_nicht():
    """⚠️ Sonst fehlt im Archiv eine Mail, ohne dass irgendwo etwas steht."""
    daten = austausch.als_zip(
        iter([("Rechnung", b"eins"), ("Rechnung", b"zwei"), ("Rechnung", b"drei")])
    )
    with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
        assert len(archiv.namelist()) == 3
        assert len(set(archiv.namelist())) == 3


def test_ein_betreff_mit_schraegstrich_wird_kein_verzeichnis():
    """``Rechnung 1/2026`` darf im Archiv keinen Ordner aufmachen."""
    daten = austausch.als_zip(iter([("Rechnung 1/2026", b"x"), ("../../weg", b"y")]))
    with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
        for name in archiv.namelist():
            assert "/" not in name and "\\" not in name
            assert not name.startswith("..")


def test_ein_leerer_betreff_bekommt_einen_namen():
    daten = austausch.als_zip(iter([("", b"x")]))
    with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
        assert archiv.namelist() == ["Nachricht.eml"]
