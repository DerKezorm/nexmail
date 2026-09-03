"""Die Adressen des Kalenders.

⚠️ **Die Termin-Adressen stehen vor ``/{kalender_id}``.** FastAPI nimmt die
erste passende Route — ohne die Reihenfolge läse es ``termine`` als
Kalender-Kennung, und die Meldung wäre „gibt es nicht".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Benutzer, Kalender
from conftest import einrichten


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    antwort = klient.post("/api/kalender", json={"name": "Privat"})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _wann(tag: int, stunde: int = 9) -> str:
    return datetime(2026, 9, tag, stunde, tzinfo=timezone.utc).isoformat()


def _fenster(klient, von: int = 1, bis: int = 30, **frage) -> list[dict]:
    antwort = klient.get(
        "/api/kalender/termine", params={"von": _wann(von, 0), "bis": _wann(bis, 0), **frage}
    )
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# --- Kalender ------------------------------------------------------------- #


def test_ein_neuer_kalender_steht_in_der_liste(klient, welt):
    liste = klient.get("/api/kalender").json()
    assert [k["name"] for k in liste] == ["Privat"]
    assert liste[0]["farbe"] == 1
    assert liste[0]["nur_lesen"] is False


def test_umbenennen_und_ausblenden(klient, welt):
    antwort = klient.patch(f"/api/kalender/{welt['id']}", json={"name": "Familie", "sichtbar": False})
    assert antwort.status_code == 200
    assert antwort.json()["name"] == "Familie"
    assert antwort.json()["sichtbar"] is False


def test_nicht_mitgeschickt_heisst_unveraendert(klient, welt):
    """⚠️ Dieselbe Regel wie beim Passwort — sonst verliert jeder seine Farbe,
    der nur den Namen ändert."""
    klient.patch(f"/api/kalender/{welt['id']}", json={"farbe": 4})
    antwort = klient.patch(f"/api/kalender/{welt['id']}", json={"name": "Neu"})
    assert antwort.json()["farbe"] == 4


def test_entfernen_nennt_die_zahl(klient, welt):
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Eins", "beginn": _wann(2)},
    )
    antwort = klient.delete(f"/api/kalender/{welt['id']}")
    assert antwort.status_code == 200
    assert antwort.json() == {"termine": 1}


def test_ein_fremder_kalender_gibt_404(klient, db, welt):
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.flush()
    seiner = Kalender(benutzer_id=anderer.id, name="Privat", farbe=1)
    db.add(seiner)
    db.commit()

    assert klient.patch(f"/api/kalender/{seiner.id}", json={"name": "X"}).status_code == 404
    assert klient.delete(f"/api/kalender/{seiner.id}").status_code == 404


# --- Termine -------------------------------------------------------------- #


def test_ein_termin_laesst_sich_anlegen_und_wiederfinden(klient, welt):
    antwort = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Zahnarzt", "beginn": _wann(2, 8)},
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["titel"] == "Zahnarzt"

    raus = _fenster(klient)
    assert [t["titel"] for t in raus] == ["Zahnarzt"]


def test_die_adresse_termine_wird_nicht_als_kalender_gelesen(klient, welt):
    """⚠️ **Der Reihenfolge-Fallstrick.** Ohne sie käme hier „gibt es nicht"."""
    antwort = klient.get(
        "/api/kalender/termine", params={"von": _wann(1, 0), "bis": _wann(30, 0)}
    )
    assert antwort.status_code == 200


def test_eine_reihe_kommt_ausgerechnet_zurueck(klient, welt):
    klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"], "titel": "Wochenstart",
            "beginn": _wann(7), "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    )
    raus = _fenster(klient)
    assert len(raus) == 4
    assert all(t["aus_reihe"] for t in raus)
    # ⚠️ Die Regel kommt als KENNUNG, nicht als deutscher Satz — und die
    # Wochentage als Liste, damit die Oberfläche daraus einen Satz baut.
    assert raus[0]["wiederholung"] == "woechentlich"
    assert raus[0]["wiederholung_tage"] == ["MO"]


def test_nur_dieser_aendert_genau_einen(klient, welt):
    neu = klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"], "titel": "Wochenstart",
            "beginn": _wann(7), "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    ).json()

    antwort = klient.patch(
        f"/api/kalender/termine/{neu['id']}",
        json={"titel": "Ausnahmsweise", "umfang": "dieser", "vorkommen": _wann(14)},
    )
    assert antwort.status_code == 200, antwort.text

    titel = {t["beginn"][:10]: t["titel"] for t in _fenster(klient)}
    assert titel["2026-09-14"] == "Ausnahmsweise"
    assert titel["2026-09-07"] == "Wochenstart"


def test_nur_diesen_loeschen_klinkt_ihn_aus(klient, welt):
    neu = klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"], "titel": "Wochenstart",
            "beginn": _wann(7), "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    ).json()

    antwort = klient.delete(
        f"/api/kalender/termine/{neu['id']}",
        params={"umfang": "dieser", "vorkommen": _wann(14)},
    )
    assert antwort.status_code == 204

    assert [t["beginn"][:10] for t in _fenster(klient)] == [
        "2026-09-07", "2026-09-21", "2026-09-28",
    ]


def test_ein_unbekannter_umfang_gibt_400_mit_kennung(klient, welt):
    neu = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "X", "beginn": _wann(2)},
    ).json()
    antwort = klient.patch(
        f"/api/kalender/termine/{neu['id']}", json={"umfang": "vielleicht", "titel": "Y"}
    )
    assert antwort.status_code == 400
    # ⚠️ Eine Kennung, kein deutscher Satz — die Oberflaeche uebersetzt.
    assert antwort.json()["detail"] == "umfang_unbekannt"


def test_ein_riesiges_fenster_wird_abgewiesen(klient, welt):
    antwort = klient.get(
        "/api/kalender/termine",
        params={
            "von": _wann(1, 0),
            "bis": (datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=3000)).isoformat(),
        },
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "fenster_zu_gross"


def test_ein_abo_weist_das_anlegen_ab(klient, db, welt):
    abo = Kalender(
        benutzer_id=db.query(Benutzer).first().id, name="Feiertage", farbe=5,
        art="ics", url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()

    antwort = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": abo.id, "titel": "Geht nicht", "beginn": _wann(2)},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "kalender_nur_lesen"


def test_auf_kalender_einschraenken(klient, welt):
    zweiter = klient.post("/api/kalender", json={"name": "Arbeit"}).json()
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Privat", "beginn": _wann(2)},
    )
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": zweiter["id"], "titel": "Arbeit", "beginn": _wann(2, 11)},
    )

    raus = _fenster(klient, kalender=[zweiter["id"]])
    assert [t["titel"] for t in raus] == ["Arbeit"]
