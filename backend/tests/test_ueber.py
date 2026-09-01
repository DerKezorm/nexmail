"""Die Ueber-Seite und die Update-Nachfrage.

⚠️ **Der wichtigste Test hier ist ``test_ein_ausfall_bei_github_reisst_nichts_mit``.**
Die Nachfrage ist Beiwerk. Faellt sie aus, soll dort einfach nichts stehen —
eine Ueber-Seite, die mit 500 antwortet, weil GitHub gerade langsam ist, waere
ein selbstgemachter Fehler an der Stelle, an der man nachsieht, warum etwas
nicht geht.
"""

from __future__ import annotations

import httpx
import pytest

from app import __version__
from app.services import aktualisierung
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen


@pytest.fixture(autouse=True)
def ohne_gedaechtnis():
    aktualisierung.zuruecksetzen()
    yield
    aktualisierung.zuruecksetzen()


@pytest.fixture
def ohne_netz(monkeypatch):
    """Kein Test ruft GitHub an — sonst haengt der Lauf am fremden Dienst."""

    async def nichts():
        return None

    monkeypatch.setattr(aktualisierung, "_abfragen", nichts)
    yield


def _antwortet_mit(monkeypatch, tag: str | None):
    async def gibt():
        return tag

    monkeypatch.setattr(aktualisierung, "_abfragen", gibt)


# --- Versionsvergleich ---------------------------------------------------- #


@pytest.mark.parametrize(
    "neueste,jetzige,erwartet",
    [
        ("v0.2.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("v0.1.0", "0.2.0", False),
        # ⚠️ Der Fall, den ein Textvergleich falsch macht — und zwar genau
        # einmal, naemlich bei der zehnten Nebenfassung.
        ("v0.10.0", "0.9.0", True),
        ("v0.9.0", "0.10.0", False),
        ("kein-tag", "0.1.0", False),
        ("", "0.1.0", False),
    ],
)
def test_verglichen_werden_zahlen_keine_zeichenketten(neueste, jetzige, erwartet):
    assert aktualisierung.ist_neuer(neueste, jetzige) is erwartet


# --- Die Seite ------------------------------------------------------------ #


def test_die_seite_nennt_fassung_lizenz_und_herkunft(klient, ohne_netz):
    einrichten(klient)
    daten = klient.get("/api/ueber").json()

    assert daten["version"] == __version__
    assert daten["lizenz"] == "AGPL-3.0-or-later"
    assert daten["repo_adresse"].endswith("/nexmail")
    assert daten["projektseite"].startswith("https://")


def test_nur_der_betreiber_sieht_sie(klient, db, ohne_netz):
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    klient.post("/api/auth/abmelden")
    anmelden(klient, "zweiter", "auch-geheim-456", geheimnis)

    assert klient.get("/api/ueber").status_code == 403
    assert klient.put("/api/ueber/pruefen", json={"update_pruefen": False}).status_code == 403


def test_die_nachfrage_ist_ab_werk_an(klient, ohne_netz):
    """So entschieden am 01.09.2026, „wie bei nexview"."""
    einrichten(klient)
    assert klient.get("/api/ueber").json()["update_pruefen"] is True


def test_ausschalten_wird_gemerkt(klient, ohne_netz):
    einrichten(klient)
    assert (
        klient.put("/api/ueber/pruefen", json={"update_pruefen": False}).json()["update_pruefen"]
        is False
    )
    assert klient.get("/api/ueber").json()["update_pruefen"] is False


def test_ausgeschaltet_geht_nichts_hinaus(klient, monkeypatch):
    """⚠️ Der Grund fuer den Schalter — nicht nur ein leeres Feld in der Anzeige."""
    gerufen: list[int] = []

    async def zaehlen():
        gerufen.append(1)
        return "v9.9.9"

    monkeypatch.setattr(aktualisierung, "_abfragen", zaehlen)

    einrichten(klient)
    klient.put("/api/ueber/pruefen", json={"update_pruefen": False})
    gerufen.clear()

    daten = klient.get("/api/ueber").json()
    assert gerufen == [], "Trotz ausgeschalteter Nachfrage ging eine Anfrage hinaus."
    assert daten["geprueft"] is False
    assert daten["neueste"] is None


def test_von_hand_geht_auch_ausgeschaltet(klient, monkeypatch):
    """Ausgeschaltet heisst „nicht **von selbst**". Ein Klick ist eine Entscheidung."""
    _antwortet_mit(monkeypatch, "v9.9.9")

    einrichten(klient)
    klient.put("/api/ueber/pruefen", json={"update_pruefen": False})

    daten = klient.post("/api/ueber/pruefen").json()
    assert daten["neueste"] == "v9.9.9"
    assert daten["neuer_da"] is True
    # Und der Schalter bleibt trotzdem aus.
    assert daten["update_pruefen"] is False


def test_eine_neuere_fassung_wird_gemeldet(klient, monkeypatch):
    _antwortet_mit(monkeypatch, "v99.0.0")
    einrichten(klient)

    daten = klient.get("/api/ueber").json()
    assert daten["neueste"] == "v99.0.0"
    assert daten["neuer_da"] is True
    assert daten["geprueft_am"] is not None


def test_dieselbe_fassung_meldet_nichts(klient, monkeypatch):
    _antwortet_mit(monkeypatch, f"v{__version__}")
    einrichten(klient)

    daten = klient.get("/api/ueber").json()
    assert daten["neuer_da"] is False
    assert daten["geprueft"] is True


def test_ein_ausfall_bei_github_reisst_nichts_mit(klient, monkeypatch):
    """⚠️ **Der Kern.** Auch ``httpx.InvalidURL`` — in Nexview lief genau die
    an einem ``httpx.HTTPError`` vorbei und riss eine ganze Seite mit."""

    einrichten(klient)

    for fehler in (
        httpx.ConnectTimeout("zu langsam"),
        httpx.InvalidURL("kaputte Adresse"),
        ValueError("etwas ganz anderes"),
    ):

        class Attrappe:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                raise fehler

        monkeypatch.setattr(httpx, "AsyncClient", Attrappe)
        aktualisierung.zuruecksetzen()

        antwort = klient.get("/api/ueber")
        assert antwort.status_code == 200, f"{fehler!r} hat die Seite mitgerissen."
        assert antwort.json()["neueste"] is None
        assert antwort.json()["version"] == __version__


def test_hoechstens_einmal_am_tag(klient, monkeypatch):
    """GitHub erlaubt ohne Anmeldung 60 Anfragen je Stunde und Adresse."""
    gerufen: list[int] = []

    async def zaehlen():
        gerufen.append(1)
        return "v0.1.0"

    monkeypatch.setattr(aktualisierung, "_abfragen", zaehlen)

    einrichten(klient)
    for _ in range(4):
        klient.get("/api/ueber")

    assert len(gerufen) == 1, f"Es gingen {len(gerufen)} Anfragen hinaus statt einer."
