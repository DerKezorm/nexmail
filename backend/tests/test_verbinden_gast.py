"""V18: was nexmail heute über eine von Hand eingetragene Verbindung mit nextasks und nextime tut, tut es genauso über
eine per „Verbinden“ gemachte (Modul verbinden 0.1.1). Je Partner dieselbe Nutzung zweimal: über den alten Zugang
(Adresse plus API-Schlüssel, ``TRANSPORT`` der App) und über die Klick-Verbindung (``nexverbinden.call``), gegen einen
Ersatz, der antwortet wie nextasks bzw. nextime und sich merkt, mit welchem Schlüssel gefragt wurde.

Die Verbindung selbst entsteht über die echten Wege beider Seiten (Start, Zustimmung bei der Partner-App der
Vertragstests, Rücksprung); der Ersatz beantwortet nur die ``/api/v1``-Wege, die die Partner-App der Tests nicht hat.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent / "nexverbinden"))

import verbinden_contract as contract  # noqa: E402
from nexverbinden_adapter import Adapter  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Aufgabenverbindung, Benutzer, NextimeVerbindung  # noqa: E402
from app.services import aufgabenziele, nextasks, nextime, nextimeverbindung  # noqa: E402

LISTEN = {"lists": [{"id": "l1", "name": "Einkauf", "space_name": "Zuhause", "writable": True, "sections": []}]}
ICH_TASKS = {"display_name": "Kim", "level": "write", "features": ["tasks", "external_ref"]}


def _antwort(pfad: str) -> Any:
    if pfad.endswith("/me"):
        return ICH_TASKS
    if pfad.endswith("/lists"):
        return LISTEN
    return None


class Ersatz:
    """Antwortet auf ``/api/v1/me`` und ``/api/v1/lists`` und merkt sich die Schlüssel."""

    def __init__(self) -> None:
        self.gesehen: list[tuple[str, str]] = []

    def antworten(self, anfrage: httpx.Request) -> httpx.Response | None:
        pfad = anfrage.url.path
        daten = _antwort(pfad)
        if daten is None:
            return None
        self.gesehen.append((pfad, anfrage.headers.get("authorization", "")))
        return httpx.Response(200, json=daten)


@pytest.fixture
def welt(tmp_path: Path):
    adapter = Adapter()
    ersatz = Ersatz()
    for gefunden in contract.world(contract.package(adapter), adapter, tmp_path):
        original = gefunden._handle

        def handle(anfrage: httpx.Request, original=original, gefunden=gefunden) -> httpx.Response:
            if anfrage.headers.get("host", "") in gefunden.down:
                raise httpx.ConnectError("down", request=anfrage)
            return ersatz.antworten(anfrage) or original(anfrage)

        gefunden._handle = handle  # type: ignore[method-assign]
        contract.package(adapter).reach.TRANSPORT = httpx.MockTransport(handle)
        yield gefunden, ersatz


def _person(rolle: str = "kim") -> Benutzer:
    with SessionLocal() as db:
        person = db.query(Benutzer).filter_by(benutzername=rolle).one()
        db.expunge(person)
        return person


def test_nextasks_von_hand_und_per_klick_gleich(welt, monkeypatch):
    gefunden, ersatz = welt
    # Von Hand: Adresse plus Schlüssel, über nexmails eigenen Weg hinaus.
    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(lambda a: ersatz.antworten(a) or httpx.Response(404)))
    hand = nextasks.Zugang(url="https://nextasks.example.com", token="ntk_" + "h" * 40)
    von_hand = nextasks.listen(hand)
    assert ersatz.gesehen[-1] == ("/api/v1/lists", f"Bearer {hand.token}")

    # Per Klick: die Verbindung über die echten Wege, dann dieselbe Liste über ``nexverbinden.call``.
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        v = db.query(Aufgabenverbindung).filter_by(art="nextasks").one()
        zugang = aufgabenziele._nextasks_zugang(v)  # noqa: SLF001
    assert zugang.ueber and not zugang.token
    per_klick = nextasks.listen(zugang)
    assert [(l.id, l.name) for l in per_klick] == [(l.id, l.name) for l in von_hand]
    pfad, schluessel = ersatz.gesehen[-1]
    assert pfad == "/api/v1/lists" and schluessel.startswith("Bearer ") and hand.token not in schluessel
    # Die Karte des Moduls steht danach auf „verbunden“.
    assert gefunden.card("app")["state"] == "connected"


def test_nextasks_nicht_erreichbar_ueber_den_klick_heisst_wie_vorher(welt):
    gefunden, _ = welt
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        zugang = aufgabenziele._nextasks_zugang(db.query(Aufgabenverbindung).filter_by(art="nextasks").one())  # noqa: SLF001
    gefunden.down.add(gefunden.host(gefunden.partner.base))
    with pytest.raises(nextasks.NextasksFehler) as fehler:
        nextasks.listen(zugang)
    assert fehler.value.kennung == "nextasks_nicht_erreichbar"


def test_nextime_zugang_ueber_den_klick(welt, monkeypatch):
    """nextime geht denselben Weg (``nextime._anfrage``); der Zugang trägt ``ueber`` und keinen Schlüssel."""
    gefunden, ersatz = welt
    gesehen: list[tuple[str, str, str]] = []

    def anfragen(partner, konto, methode, pfad, *, params=None, rumpf=None):
        gesehen.append((partner, konto, pfad))
        return httpx.Response(200, json={"ok": True})

    from app.services import verbinden_store

    monkeypatch.setattr(verbinden_store, "anfragen", anfragen)
    zugang = nextime.Zugang(url="https://time.example.com", token="", ueber="konto-1")
    assert nextime.zugang_lesen(nextime.zugang_schreiben(zugang)) == zugang
    nextime._anfrage(zugang, "GET", "me")  # noqa: SLF001
    assert gesehen == [("nextime", "konto-1", "/api/v1/me")]
    with SessionLocal() as db:
        assert db.query(NextimeVerbindung).count() == 0
    assert json.loads(nextime.zugang_schreiben(nextime.Zugang(url="u", token="t")))["token"] == "t"
    _ = nextimeverbindung
