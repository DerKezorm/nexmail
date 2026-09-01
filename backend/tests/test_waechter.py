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
    from app.deps import angemeldet, angemeldete_sitzung, halbe_sitzung

    geschuetzt = {angemeldet, angemeldete_sitzung, halbe_sitzung}
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
