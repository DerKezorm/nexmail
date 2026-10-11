"""Der Wächter über alle Adressen.

⚠️ **Dieser Test ist der Grund, warum die Rechte eine Erlaubnisliste sind.**
Er läuft über die ganze Routentabelle. Wer eine Adresse hinzufügt und die
Abhängigkeit vergisst, bekommt hier einen roten Lauf — nicht irgendwann ein
Datenleck.

In Nexview hat genau so ein Test Seitentüren gefunden, an die niemand gedacht
hatte. Siehe FALLSTRICKE.md §5.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.main import OEFFENTLICHE_PFADE, app
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen


def _api_routen() -> list[APIRoute]:
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api")
    ]


def test_jede_adresse_ist_entschieden():
    """Jede Adresse ist entweder geschützt oder steht begründet auf der Liste."""
    # ⚠️ **Alle drei zaehlen als Schutz.** Beim ersten Lauf fehlte
    # ``angemeldete_sitzung``, und der Test meldete /api/auth/abmelden als
    # ungeschuetzt - obwohl es das nicht war. Ein Waechter, der falschen Alarm
    # schlaegt, wird abgeschaltet; deshalb steht die Liste hier vollstaendig.
    from app.deps import angemeldet, angemeldete_sitzung, api_zugriff, halbe_sitzung

    # ``api_zugriff`` ist der vierte: ``/api/v1`` nimmt einen API-Schluessel
    # statt einer Sitzung. Er ist kein schwaecherer Schutz, sondern ein
    # anderer - und nur lesend, siehe routers/api_v1.py.
    geschuetzt = {angemeldet, angemeldete_sitzung, halbe_sitzung, api_zugriff}
    unentschieden: list[str] = []

    for route in _api_routen():
        abhaengigkeiten = {d.call for d in route.dependant.dependencies}
        # Verschachtelte Abhängigkeiten mitzählen: 'angemeldet' hängt selbst
        # an 'angemeldete_sitzung'.
        def sammeln(dep, gesehen=None):
            gesehen = gesehen or set()
            for unter in dep.dependencies:
                gesehen.add(unter.call)
                sammeln(unter, gesehen)
            return gesehen

        abhaengigkeiten |= sammeln(route.dependant)

        if abhaengigkeiten & geschuetzt:
            continue
        if route.path in OEFFENTLICHE_PFADE:
            continue
        unentschieden.append(f"{sorted(route.methods)} {route.path}")

    assert not unentschieden, (
        "Diese Adressen sind weder geschützt noch als öffentlich begründet:\n  "
        + "\n  ".join(unentschieden)
        + "\n\nEntweder Depends(angemeldet) setzen oder mit Begründung in "
        "OEFFENTLICHE_PFADE eintragen."
    )


def test_jeder_eintrag_auf_der_liste_hat_einen_grund():
    """Ein „später" ohne Begründung altert zur Ausrede — hier genauso."""
    ohne_grund = [pfad for pfad, grund in OEFFENTLICHE_PFADE.items() if len(grund.strip()) < 30]
    assert not ohne_grund, f"Ohne brauchbare Begründung öffentlich: {ohne_grund}"


def test_die_liste_beschreibt_vorhandene_adressen():
    """Eine Ausnahme für eine Adresse, die es nicht mehr gibt, ist ein Irrtum."""
    vorhandene = {r.path for r in _api_routen()}
    verwaist = sorted(set(OEFFENTLICHE_PFADE) - vorhandene)
    assert not verwaist, f"Diese Ausnahmen zeigen ins Leere: {verwaist}"


@pytest.mark.parametrize(
    "methode,pfad",
    [
        ("get", "/api/auth/ich"),
        ("get", "/api/sitzungen"),
        ("post", "/api/sitzungen/alle-beenden"),
        ("get", "/api/einstellungen"),
        ("put", "/api/einstellungen"),
        ("post", "/api/auth/abmelden"),
    ],
)
def test_ohne_anmeldung_kommt_nichts_heraus(klient, methode, pfad):
    einrichten(klient)
    klient.cookies.clear()
    # GET nimmt kein json= - der TestClient weist es mit TypeError ab.
    if methode in ("put", "post"):
        antwort = getattr(klient, methode)(pfad, json={})
    else:
        antwort = getattr(klient, methode)(pfad)
    assert antwort.status_code == 401, f"{pfad} antwortet ohne Anmeldung mit {antwort.status_code}."


def test_keine_adresse_gibt_daten_des_anderen_heraus(klient, zweiter_klient, db):
    """Die zweite Hälfte der Trennung: angemeldet, aber nicht berechtigt."""
    einrichten(klient)
    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    ich_eins = klient.get("/api/auth/ich").json()
    ich_zwei = zweiter_klient.get("/api/auth/ich").json()

    assert ich_eins["id"] != ich_zwei["id"]
    assert ich_eins["benutzername"] == "betreiber"
    assert ich_zwei["benutzername"] == "zweiter"

    # Der erste ist Betreiber, der zweite nicht - der Haken wird nicht vererbt.
    assert ich_eins["ist_betreiber"] is True
    assert ich_zwei["ist_betreiber"] is False


def test_keine_route_wird_mit_fehlenden_abhaengigkeiten_aufgerufen():
    """Eine Routenfunktion, die eine andere direkt aufruft, muss alle ihre
    Parameter selbst mitgeben: FastAPI fuellt sie nur bei einer Anfrage.

    ⚠️ **Warum es den Test gibt:** ``ich`` bekam mit 0.10.0 einen zweiten
    Parameter (``db``); ``kontaktadresse_setzen`` rief ``ich(person)`` weiter
    auf, und jedes Speichern der Adresse endete bis 0.22.0 mit einem 500. Kein
    Test fuehrte die Route aus. Der Wächter liest den Quelltext aller Router:
    gleiche Datei oder ``from .x import route``.
    """
    import ast
    from pathlib import Path

    wurzel = Path(__file__).resolve().parent.parent / "app" / "routers"
    methoden = {"get", "post", "put", "patch", "delete", "websocket", "api_route"}
    baeume = {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in wurzel.glob("*.py")}

    def ist_route(f) -> bool:
        return any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr in methoden
            for d in f.decorator_list
        )

    routen: dict[str, dict[str, ast.arguments]] = {}
    for name, baum in baeume.items():
        for f in baum.body:
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and ist_route(f):
                routen.setdefault(name, {})[f.name] = f.args

    fehler: list[str] = []
    for name, baum in baeume.items():
        sichtbar = dict(routen.get(name, {}))
        for n in ast.walk(baum):
            if isinstance(n, ast.ImportFrom) and n.module and n.level:
                quelle = n.module.split(".")[-1]
                for alias in n.names:
                    if alias.name in routen.get(quelle, {}):
                        sichtbar[alias.asname or alias.name] = routen[quelle][alias.name]
        for n in ast.walk(baum):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)):
                continue
            a = sichtbar.get(n.func.id)
            if a is None:
                continue
            positional = a.posonlyargs + a.args
            pflicht = [x.arg for x in positional[: len(positional) - len(a.defaults)]]
            gegeben = {x.arg for x in positional[: len(n.args)]} | {
                k.arg for k in n.keywords
            }
            fehlt = [p for p in pflicht if p not in gegeben]
            if fehlt:
                fehler.append(f"{name}.py:{n.lineno} {n.func.id}() ohne {fehlt}")

    assert not fehler, fehler


@pytest.mark.parametrize("pfad", ["/openapi.json", "/api/openapi.json", "/docs", "/redoc"])
def test_keine_schnittstellenbeschreibung_ohne_anmeldung(klient, pfad):
    """FastAPIs eingebaute Beschreibung bleibt aus, auch ohne Anmeldung.

    ⚠️ **Der Wächter oben sieht sie nicht**, er läuft nur über ``/api``. Bis
    zum 11.10.2026 lieferte ``/openapi.json`` jedem die ganze Routentabelle samt
    Docstrings und Fassung. Was dort jetzt antwortet, ist höchstens die
    Oberfläche, nie die Beschreibung.
    """
    antwort = klient.get(pfad)
    assert '"openapi"' not in antwort.text
    assert '"paths"' not in antwort.text
