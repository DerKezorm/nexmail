"""E53: Die Namen der Wege in nexmails Beschreibung bleiben, wie sie vor dem Durchgang „Einstellungen“ waren.

``openapi_namen_konten.json`` hält ``operationId`` und ``summary`` jedes Wegs des Stands ``konten`` (aus
``app.openapi()``, nexmail veröffentlicht keine Beschreibung). Jeder davon steht weiter da, mit denselben Namen; neue
Wege sind Zusätze und erlaubt. Die Sprach- und Sicherungswege der Module halten ihre Namen in deren Vertragstests fest.
Das Schema ``Gefunden`` (zwei gleichnamige Klassen in ``routers/kalender.py`` und ``routers/adressbuecher.py``) steht
nicht hier: welchen langen Namen FastAPI ihm gibt, entschied schon auf ``konten`` die Reihenfolge."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

ALT = json.loads((Path(__file__).parent / "openapi_namen_konten.json").read_text(encoding="utf-8"))


def test_jeder_weg_von_vorher_steht_mit_seinen_namen_da():
    jetzt = app.openapi()["paths"]
    fehlt, anders = [], []
    for weg, namen in ALT.items():
        methode, pfad = weg.split(" ", 1)
        op = jetzt.get(pfad, {}).get(methode.lower())
        if op is None:
            fehlt.append(weg)
            continue
        if op.get("operationId") != namen["operationId"] or op.get("summary") != namen["summary"]:
            anders.append((weg, namen, {"operationId": op.get("operationId"), "summary": op.get("summary")}))
    assert len(ALT) > 300
    assert fehlt == []
    assert anders == []
