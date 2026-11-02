"""Die Wächter über ``/api/app/1``, die Fläche der eigenen iPhone-App.

Die App im App Store und die Server da draußen werden nie gleichzeitig
aktualisiert. Eine Umbenennung, die im Browser niemand bemerkt, legt dort jede
App still, die schon unterwegs ist.

Passt eine Änderung wirklich, wird der Abdruck neu erzeugt: Datei löschen und
``pytest tests/test_app_zusage.py`` laufen lassen. Ein Feld hinzuzufügen ist
erlaubt; eines wegzunehmen braucht ``/api/app/2`` daneben.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app
from app.routers.app1 import ZUGESAGT

ABDRUCK = Path(__file__).with_name("app1_abdruck.json")
PRAEFIX = "/api/app/1"


def _pfade() -> set[str]:
    return {r.path for r in app.routes if getattr(r, "path", "").startswith(PRAEFIX)}


def _felder(schema: dict, teile: dict, vorne: str = "", gesehen: tuple = ()) -> set[str]:
    """Alle Feldnamen einer Antwort, geschachtelt mit Punkt."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in gesehen:
            return set()
        return _felder(teile[name], teile, vorne, (*gesehen, name))
    for art in ("anyOf", "oneOf", "allOf"):
        if art in schema:
            raus: set[str] = set()
            for teil in schema[art]:
                raus |= _felder(teil, teile, vorne, gesehen)
            return raus
    if schema.get("type") == "array":
        return _felder(schema.get("items", {}), teile, vorne, gesehen)
    raus = set()
    for name, teil in schema.get("properties", {}).items():
        pfad = f"{vorne}{name}"
        raus.add(pfad)
        raus |= _felder(teil, teile, f"{pfad}.", gesehen)
    return raus


def _felder_je_pfad() -> dict[str, list[str]]:
    beschreibung = app.openapi()
    teile = beschreibung.get("components", {}).get("schemas", {})
    raus: dict[str, list[str]] = {}
    for pfad, wege in beschreibung["paths"].items():
        if not pfad.startswith(PRAEFIX):
            continue
        for methode, weg in wege.items():
            felder: set[str] = set()
            for code, antwort in weg.get("responses", {}).items():
                if code.startswith("2"):
                    schema = antwort.get("content", {}).get("application/json", {}).get("schema", {})
                    felder |= _felder(schema, teile)
            raus[f"{methode.upper()} {pfad}"] = sorted(felder)
    return raus


def test_die_flaeche_ist_genau_die_zugesagte():
    da = _pfade()
    zugesagt = set(ZUGESAGT)
    assert da - zugesagt == set(), f"Nicht in ZUGESAGT: {sorted(da - zugesagt)}"
    assert zugesagt - da == set(), f"Zugesagt, aber nicht erreichbar: {sorted(zugesagt - da)}"


def test_jede_zugesagte_adresse_hat_eine_antwortform():
    """Ohne Antwortform gäbe es nichts festzuhalten, und der Abdruck wäre leer.

    Ausgenommen sind Adressen, die einen Statuscode oder eine Datei liefern.
    """
    ohne = {k for k, v in _felder_je_pfad().items() if not v}
    erlaubt_leer = {
        "DELETE /api/app/1/device",
        "DELETE /api/app/1/drafts/{uid}",
        "DELETE /api/app/1/snoozes/{eintrag_id}",
        "DELETE /api/app/1/tasks/{aufgabe_id}",
        "GET /api/app/1/messages/{nachricht_id}/attachments/{anhang_id}",
        "GET /api/app/1/sender-image",
        "POST /api/app/1/tasks/sync",
    }
    assert ohne <= erlaubt_leer, f"Ohne festgehaltene Felder: {sorted(ohne - erlaubt_leer)}"


def test_die_antwortform_bleibt():
    jetzt = _felder_je_pfad()
    if not ABDRUCK.exists():
        ABDRUCK.write_text(
            json.dumps(jetzt, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )

    frueher: dict[str, list[str]] = json.loads(ABDRUCK.read_text(encoding="utf-8"))
    verschwunden: dict[str, list[str]] = {}
    for schluessel, felder in frueher.items():
        if schluessel not in jetzt:
            verschwunden[schluessel] = ["(die ganze Adresse)"]
            continue
        fehlend = [f for f in felder if f not in jetzt[schluessel]]
        if fehlend:
            verschwunden[schluessel] = fehlend

    assert not verschwunden, (
        "Aus einer Antwort der App-Fläche sind Felder verschwunden:\n"
        + "\n".join(f"  {k}: {', '.join(v)}" for k, v in sorted(verschwunden.items()))
        + "\n\nUnter /api/app/1 gilt eine Zusage. Das Feld bleibt, oder es braucht /api/app/2."
    )


def test_der_abdruck_misst_wirklich_etwas():
    """⚠️ Ein leerer Abdruck wäre still grün. Er muss die Kernfelder tragen."""
    frueher = json.loads(ABDRUCK.read_text(encoding="utf-8"))
    assert "faehigkeiten" in frueher["GET /api/app/1/me"]
    assert "key" in frueher["POST /api/app/1/pairing/{pairing_id}/key"]
    assert "eintraege.nachricht.betreff" in frueher["GET /api/app/1/changes"]
    assert "abbestellen.art" in frueher["GET /api/app/1/messages/{nachricht_id}"]
    assert len(frueher) >= len(ZUGESAGT)
