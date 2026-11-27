"""Die Netzregeln des Moduls ki in nexmail, über nexmails eigene Wege (Entwurf KI-Anbieter, K1 und K4).

⚠️ **Das war nexmails offene Stelle.** Bis zum Modul prüfte nexmail an der KI-Adresse eines Kontos nur ``http``/``https``:
es folgte Weiterleitungen, erreichte jedes Gerät im eigenen Netz und die Metadaten-Adresse 169.254.169.254, nahm einen
Proxy aus der Umgebung und gab bis zu 300 Zeichen der Antwort zurück. Das große Release darf nicht ohne diese Regeln
hinaus (K1). Jede Regel steht hier einmal, über ``PUT /api/ki`` (Zugang speichern) und ``POST /api/ki/text`` (der Knopf
im Editor), mit echten Servern auf 127.0.0.1 und einem Zähler, der jede Anfrage merkt, die ihn erreicht:

1. ein Ziel im eigenen Netz ohne Erlaubnis des Betreibers (beim Speichern und bei jeder Anfrage);
2. Link-local und Metadaten, auch hinter einem Namen und in IPv6 versteckt;
3. eine Weiterleitung (an einen Rechner im eigenen Netz);
4. ein Proxy aus der Umgebung.

Je Regel einmal gegen eine Mutation des Moduls geprüft (Rückgabecode 1), siehe ``docs/konten-anbindung.md``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "nexki"))

from nexki_service import Recorder, ReferenceService  # noqa: E402

from app.db import SessionLocal, einstellung_schreiben  # noqa: E402
from app.services import anmeldebremse  # noqa: E402
from app.vendor import nexki  # noqa: E402
from conftest import einrichten, ki_aufloesen  # noqa: E402

TEXT = {"text": "<p>Bitte diesen Satz glätten, danke dir</p>", "auftrag": "rechtschreibung"}


@pytest.fixture(autouse=True)
def frei():
    anmeldebremse.zuruecksetzen()
    nexki.brake.BRAKE.forget()
    yield
    anmeldebremse.zuruecksetzen()
    nexki.brake.BRAKE.forget()


@pytest.fixture
def dienst():
    gefunden = ReferenceService()
    gefunden.serve()
    yield gefunden
    gefunden.stop()


@pytest.fixture
def zaehler():
    gefunden = Recorder()
    yield gefunden
    gefunden.stop()


@pytest.fixture
def konto(klient, monkeypatch):
    """Der Betreiber mit erlaubter KI, Weg „Jedes Konto selbst“ (wie jede nexmail-Installation von vorher), ohne
    Rechner auf der Liste; das DNS der Tests kennt nur ``*.example.com`` und die Namen unten."""
    monkeypatch.setattr(
        nexki.client,
        "resolver",
        ki_aufloesen({"metadaten.example.com": ["169.254.169.254"], "nas.example.com": ["172.16.0.20"]}),
    )
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "ki_erlaubt", "1")
        einstellung_schreiben(db, "ki_mode", json.dumps("own"))
        einstellung_schreiben(db, "ki_hosts", json.dumps([]))
    return klient


def _liste(*rechner: str) -> None:
    with SessionLocal() as db:
        einstellung_schreiben(db, "ki_hosts", json.dumps(list(rechner)))


def _rechner(dienst: ReferenceService) -> str:
    return dienst.base.split("//", 1)[1].split("/", 1)[0]


def _zugang(klient, url: str, modell: str = "plain"):
    return klient.put("/api/ki", json={"url": url, "modell": modell})


def test_ein_ziel_im_eigenen_netz_braucht_die_liste_des_betreibers(konto, dienst):
    """Regel 1, beim Speichern und bei jeder Anfrage: von der Liste genommen, scheitert derselbe Zugang beim nächsten
    Mal, ohne dass etwas hinausgeht."""
    for url in (dienst.base, "http://172.16.0.20:11434/v1/", "http://nas.example.com:11434/v1/", "http://[fd00::20]/v1/"):
        abgelehnt = _zugang(konto, url)
        assert abgelehnt.status_code == nexki.errors.CODES["ai_address_private"][0] and abgelehnt.json()["detail"] == "ai_address_private", url
    assert dienst.seen == []

    _liste(_rechner(dienst))
    assert _zugang(konto, dienst.base).status_code == 200
    assert konto.put("/api/ki", json={"aktiv": True}).status_code == 200
    gelungen = konto.post("/api/ki/text", json=TEXT)
    assert gelungen.status_code == 200, gelungen.text
    gesehen = len(dienst.seen)
    assert gesehen >= 1

    _liste()
    wieder = konto.post("/api/ki/text", json=TEXT)
    # Eine Kennung, die es vorher nicht gab, kommt mit dem Status des Moduls (``kidienst.als_antwort``, ki 0.1.2).
    assert wieder.status_code == nexki.errors.CODES["ai_address_private"][0] and wieder.json()["detail"] == "ai_address_private"
    assert len(dienst.seen) == gesehen


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/v1/",
        "http://[::ffff:169.254.169.254]/v1/",
        "http://[fe80::1]/v1/",
        "http://metadaten.example.com/v1/",
        "http://100.100.100.200/v1/",
    ],
)
def test_link_local_und_metadaten_nie(konto, url):
    """Regel 2: auch wenn der Betreiber den Rechner auf die Liste setzt."""
    _liste("169.254.169.254", "[fe80::1]", "metadaten.example.com", "100.100.100.200", "[::ffff:169.254.169.254]")
    abgelehnt = _zugang(konto, url)
    assert abgelehnt.status_code == nexki.errors.CODES["ai_address_refused"][0] and abgelehnt.json()["detail"] == "ai_address_refused", url


def test_eine_weiterleitung_wird_nicht_verfolgt(konto, dienst, zaehler):
    """Regel 3: der Dienst antwortet 307 auf einen Rechner im eigenen Netz; nexmail folgt nicht, und das Ziel bekommt
    nichts."""
    dienst.redirect_to = zaehler.address + "v1/chat/completions"
    _liste(_rechner(dienst))
    assert _zugang(konto, dienst.base, modell="redirect").status_code == 200
    konto.put("/api/ki", json={"aktiv": True})
    antwort = konto.post("/api/ki/text", json=TEXT)
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "ki_dienst_antwortet_nicht" and antwort.json()["werte"]["code"] == 307
    assert zaehler.hits == []


def test_kein_proxy_aus_der_umgebung(konto, dienst, zaehler, monkeypatch):
    """Regel 4: ein Proxy in der Umgebung bekommt nichts zu sehen, die Anfrage geht geradewegs an den Dienst."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, zaehler.address)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    _liste(_rechner(dienst))
    assert _zugang(konto, dienst.base).status_code == 200
    konto.put("/api/ki", json={"aktiv": True})
    antwort = konto.post("/api/ki/text", json=TEXT)
    assert antwort.status_code == 200, antwort.text
    assert zaehler.hits == [] and dienst.seen


def test_die_modellliste_geht_dieselben_wege(konto, dienst):
    """Auch die Modellliste (``POST /api/ki/modelle``) erreicht kein Ziel im eigenen Netz ohne Liste."""
    abgelehnt = konto.post("/api/ki/modelle", json={"url": dienst.base})
    assert abgelehnt.status_code == nexki.errors.CODES["ai_address_private"][0] and abgelehnt.json()["detail"] == "ai_address_private"
    assert dienst.seen == []
