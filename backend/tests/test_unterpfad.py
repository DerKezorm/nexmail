"""Betrieb unter einem Unterpfad — ``https://mail.example.org/nexmail``.

⚠️ **Bis zum 01.09.2026 war davon nichts geprueft.** Die Middleware stand, der
Cookie-Pfad stand — und die ausgelieferte ``index.html`` verwies weiter mit
absoluten Pfaden auf sich selbst. Unter einem Vorbau haette der Browser
``/assets/…`` an der **Wurzel der Domain** gesucht, wohin der Proxy gar nicht
zeigt. Getestet war der halbe Weg.

⚠️ **Hier wird die Anwendung nicht neu geladen.** Der erste Anlauf tat das
(``importlib.reload``), um die Umgebungsvariable wirken zu lassen — und riss
damit fuenf fremde Tests um: ``conftest`` bindet ``app`` beim Import, und nach
einem Neuladen halten die Testdateien ein anderes Objekt als das Modul. Statt
dessen wird die **bestehende** Anwendung in die Middleware gewickelt und die
Umschreibung als reine Funktion geprueft. Beides ohne Nebenwirkung.

Den ganzen Weg durch einen **echten nginx** prueft
``pruefstand/unterpfad/`` — was hier schiefgeht, geht im Browser schief.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import _css_mit_vorbau, _index_mit_vorbau, app
from app.middleware import BasisPfadMiddleware

VORBAU = "/nexmail"


@pytest.fixture
def hinter_proxy(monkeypatch):
    """Die bestehende Anwendung hinter einem Proxy, der den Vorbau mitschickt.

    ⚠️ **Die Einstellung gehoert dazu, nicht nur die Middleware.** Ohne sie
    setzt der Server das Sitzungs-Cookie mit ``Path=/api`` — und der Browser
    schickt es unter ``/nexmail/api/...`` nicht mit. Beim ersten Anlauf sah
    das aus wie eine kaputte Anmeldung; in Wahrheit fehlte dem Test die halbe
    Aufstellung.

    ``cookie_pfad()`` liest die Einstellung bei **jedem** Aufruf — deshalb
    genuegt der geleerte Zwischenspeicher, und die Anwendung muss nicht neu
    geladen werden.
    """
    from app.config import get_settings

    monkeypatch.setenv("NEXMAIL_URL_BASE", VORBAU)
    get_settings.cache_clear()
    try:
        with TestClient(BasisPfadMiddleware(app, VORBAU)) as klient:
            yield klient
    finally:
        get_settings.cache_clear()


def test_jede_adresse_antwortet_doppelt(hinter_proxy):
    """⚠️ Mit **und** ohne Vorbau.

    Ein durchreichender Proxy schickt ihn mit — der Normalfall. Ein
    abschneidender entfernt ihn vorher, und der Docker-Healthcheck ruft
    ohnehin direkt an der Wurzel an.
    """
    assert hinter_proxy.get("/nexmail/api/health").status_code == 200
    assert hinter_proxy.get("/api/health").status_code == 200


def test_ein_nur_scheinbarer_vorbau_bleibt_unangetastet(hinter_proxy):
    """``/nexmailfoo`` traegt ihn nicht — dort darf nichts abgeschnitten werden."""
    antwort = hinter_proxy.get("/nexmailfoo/api/health")
    assert antwort.status_code != 200 or "status" not in antwort.text


def test_die_anwendung_bleibt_unter_dem_vorbau_bedienbar(hinter_proxy):
    """Der ganze Weg: einrichten, angemeldet bleiben — alles mit Vorbau."""
    angelegt = hinter_proxy.post(
        "/nexmail/api/setup/konto",
        json={"benutzername": "betreiber", "passwort": "sehr-geheim-123"},
    )
    assert angelegt.status_code == 201, angelegt.text
    assert hinter_proxy.get("/nexmail/api/auth/ich").status_code == 200


def test_das_sitzungscookie_traegt_den_vorbau(monkeypatch):
    """⚠️ **Ohne das faehrt es bei keiner Anfrage mit.**

    Ein Cookie mit ``Path=/api`` schickt der Browser unter
    ``/nexmail/api/...`` nicht — und die Anmeldung wirkt, als ginge sie nicht.
    """
    from app.config import get_settings
    from app.services import sitzung

    monkeypatch.setenv("NEXMAIL_URL_BASE", VORBAU)
    get_settings.cache_clear()
    try:
        assert sitzung.cookie_pfad() == "/nexmail/api"
    finally:
        get_settings.cache_clear()


# --- Die Umschreibung, als reine Funktion -------------------------------- #


@pytest.fixture
def gebaute_seite(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><script type="module" src="/assets/x.js"></script>'
        '<link rel="stylesheet" href="/assets/x.css">'
        '<link rel="icon" href="//fremder.example/f.ico"></head><body></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "assets" / "x.css").write_text(
        "@font-face{src:url(/assets/schrift.woff2) format('woff2')}", encoding="utf-8"
    )
    return tmp_path


def test_die_seite_verweist_mit_vorbau_auf_sich_selbst(gebaute_seite):
    """⚠️ **Der Teil, der gefehlt hat.**

    Ohne ihn sucht der Browser ``/assets/…`` an der Wurzel der Domain, findet
    nichts und zeigt eine weisse Seite — ohne eine einzige Meldung, die auf
    den Unterpfad zeigt.
    """
    html = _index_mit_vorbau(gebaute_seite / "index.html", VORBAU)
    assert 'src="/nexmail/assets/x.js"' in html
    assert 'href="/nexmail/assets/x.css"' in html
    assert 'src="/assets/x.js"' not in html


def test_fremde_adressen_bekommen_keinen_vorbau(gebaute_seite):
    """``//fremder.example`` zeigt auf einen anderen Host."""
    html = _index_mit_vorbau(gebaute_seite / "index.html", VORBAU)
    assert 'href="//fremder.example/f.ico"' in html


def test_die_oberflaeche_erfaehrt_ihren_vorbau(gebaute_seite):
    """⚠️ Als ``<meta>``, nicht als Inline-Skript.

    Die CSP sagt ``script-src 'self'`` und verwirft eine eingespritzte Zeile
    stumm — die Seite lud dann ohne Vorbau und zeigte gar keine Anmeldemaske.
    Am 01.09.2026 vom Pruefstand gefunden, nicht von Hand.
    """
    html = _index_mit_vorbau(gebaute_seite / "index.html", VORBAU)
    assert '<meta name="nexmail-basis" content="/nexmail">' in html
    assert "<script>window." not in html


def test_die_stilvorlage_verweist_mit_vorbau_auf_die_schriften(gebaute_seite):
    """⚠️ **Die ``index.html`` allein reicht nicht.**

    In der gebauten CSS stehen die Schriften als ``url(/assets/…)`` — ebenfalls
    absolut. Unter einem Unterpfad bekommt der Browser vierzehn 404er und
    faellt still auf Systemschriften zurueck. Die Seite sieht dabei fast
    richtig aus; genau deshalb faellt es von Hand nicht auf.
    """
    umgeschrieben = _css_mit_vorbau(gebaute_seite, VORBAU)
    assert "x.css" in umgeschrieben
    assert "url(/nexmail/assets/schrift.woff2)" in umgeschrieben["x.css"]


def test_ohne_vorbau_wird_nichts_angefasst(gebaute_seite):
    """⚠️ Der Regelfall darf durch die Vorbau-Arbeit nichts abbekommen."""
    assert _index_mit_vorbau(gebaute_seite / "index.html", "") is None
    assert _css_mit_vorbau(gebaute_seite, "") == {}


def test_eingebettete_schriften_sind_erlaubt(klient):
    """⚠️ **Betraf auch die gewoehnliche Installation.**

    Der Schriftsatz bringt einzelne Schnitte als ``data:``-URI mit. Mit
    ``font-src 'self'`` verwarf der Browser sie stumm, und die Oberflaeche fiel
    bei diesen Schnitten auf Systemschriften zurueck — auf **jeder**
    Installation, nicht nur unter einem Unterpfad.
    """
    regeln = klient.get("/api/health").headers.get("content-security-policy", "")
    assert "font-src 'self' data:" in regeln
