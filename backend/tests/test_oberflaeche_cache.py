"""Wie die gebaute Oberfläche ausgeliefert wird.

⚠️ **Der Fehler, gegen den das hier steht, macht eine weisse Seite.** Die
``index.html`` ging nur mit ``ETag`` und ``Last-Modified`` hinaus. Ein Browser
rechnet sich die Haltbarkeit dann selbst aus und fragt bis dahin gar nicht
nach — nach einem Update zeigt er die alte Seite, und die verweist auf
``assets/index-<pruefsumme>.js``, die es nicht mehr gibt.

⚠️ **Die Anwendung wird dafür neu geladen.** ``_frontend`` entsteht beim
Import; ohne ein gesetztes ``NEXMAIL_STATIC_DIR`` gibt es die Route gar nicht,
und der Test prüfte dann nichts. Danach wird zurückgeladen, damit die übrigen
Dateien dieselbe Anwendung sehen wie vorher.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mit_oberflaeche(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><script type="module" src="/assets/x.js">'
        "</script></head><body></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "assets" / "x.js").write_text("console.log(1)", encoding="utf-8")

    import app.config
    import app.main

    monkeypatch.setenv("NEXMAIL_STATIC_DIR", str(tmp_path))
    app.config.get_settings.cache_clear()
    neu = importlib.reload(app.main)
    try:
        yield TestClient(neu.app)
    finally:
        monkeypatch.undo()
        app.config.get_settings.cache_clear()
        importlib.reload(app.main)


def test_die_seite_muss_jedes_mal_nachgefragt_werden(mit_oberflaeche):
    antwort = mit_oberflaeche.get("/")
    assert antwort.status_code == 200
    assert antwort.headers.get("cache-control") == "no-cache"


def test_auch_eine_adresse_der_anwendung_selbst(mit_oberflaeche):
    """``/einstellungen`` kennt nur die Oberfläche — der Server liefert dort
    dieselbe ``index.html`` und darf sie genauso wenig einfrieren."""
    antwort = mit_oberflaeche.get("/einstellungen")
    assert antwort.status_code == 200
    assert antwort.headers.get("cache-control") == "no-cache"


def test_die_stuecke_bleiben_zwischenspeicherbar(mit_oberflaeche):
    """⚠️ **Nicht mitverbieten.** Ihr Name trägt die Prüfsumme des Inhalts;
    eine geänderte Datei heißt anders und wird schon deshalb neu geholt. Wer
    ihnen dasselbe ``no-cache`` gäbe, machte jeden Seitenaufruf teurer, ohne
    irgendetwas zu gewinnen."""
    antwort = mit_oberflaeche.get("/assets/x.js")
    assert antwort.status_code == 200
    assert antwort.headers.get("cache-control") != "no-cache"
