"""Farbe und Symbol am Postfach wie in nextasks (24.11.2026, gewünscht: „Farbwahl wie
nextasks“, „kein Icon“ heißt: der Punkt bleibt).

⚠️ ``farbe`` (1..6) bleibt immer gesetzt, die iPhone-App liest sie; ``farbton``
leer heißt „diese automatische Farbe“, ``symbol`` leer heißt „kein Symbol“.
"""

import pytest

from tests.test_konten import _eingabe, einrichten, ohne_netz  # noqa: F401 (Fixture)


def _anlegen(klient, **mehr):
    antwort = klient.post("/api/konten", json={**_eingabe(), **mehr})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_ab_werk_ohne_symbol_und_mit_automatischer_farbe(klient, ohne_netz):
    einrichten(klient)
    daten = _anlegen(klient)
    assert (daten["farbe"], daten["farbton"], daten["symbol"]) == (1, "", "")


def test_farbe_und_symbol_werden_gespeichert_und_bleiben_beim_aendern(klient, ohne_netz):
    einrichten(klient)
    konto = _anlegen(klient, farbton="#aa3377", symbol="briefcase")
    assert (konto["farbton"], konto["symbol"]) == ("#aa3377", "briefcase")

    # Nicht mitgeschickt heißt unverändert …
    ohne = {k: v for k, v in _eingabe().items() if not k.endswith("passwort")}
    daten = klient.put(f"/api/konten/{konto['id']}", json=ohne).json()
    assert (daten["farbton"], daten["symbol"]) == ("#aa3377", "briefcase")

    # … leer heißt zurück auf automatische Farbe und Punkt.
    daten = klient.put(f"/api/konten/{konto['id']}", json={**ohne, "farbton": "teal", "symbol": ""}).json()
    assert (daten["farbton"], daten["symbol"]) == ("teal", "")
    assert daten["farbe"] == 1
    assert klient.get("/api/konten").json()[0]["farbton"] == "teal"


@pytest.mark.parametrize(
    "feld, wert",
    [("farbton", "lila"), ("farbton", "#AA3377"), ("farbton", "#abc"), ("symbol", "Briefcase"), ("symbol", "a" * 41),
     ("symbol", "<b>")],
)
def test_unbekannte_werte_werden_abgewiesen(klient, ohne_netz, feld, wert):
    einrichten(klient)
    antwort = klient.post("/api/konten", json={**_eingabe(), feld: wert})
    assert antwort.status_code == 422, antwort.text
