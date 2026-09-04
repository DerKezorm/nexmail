"""Den Betreiber-Haken weitergeben.

⚠️ **Genau ein Betreiber, immer.** Zwei wären nicht schlimm, aber null sind das
Ende: Aus der Anwendung heraus führt dann kein Weg zurück in die Verwaltung.
"""

from __future__ import annotations

import pytest

from app.models import Benutzer
from app.services import anmeldebremse
from conftest import einrichten

KENNWORT = "sehr-geheim-123"


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.commit()
    return db.query(Benutzer).filter_by(benutzername="betreiber").one(), anderer


def test_der_haken_wandert(klient, db, welt):
    ich, anderer = welt

    antwort = klient.post(
        f"/api/benutzer/{anderer.id}/betreiber", json={"passwort": KENNWORT}
    )
    assert antwort.status_code == 204, antwort.text

    db.refresh(ich)
    db.refresh(anderer)
    assert anderer.ist_betreiber is True
    # ⚠️ **Er wandert, er wird nicht vergeben.** Sonst gäbe es zwei.
    assert ich.ist_betreiber is False


def test_danach_laesst_sich_der_alte_entfernen(klient, db, welt):
    """⚠️ Genau dafür gibt es diesen Weg: Wer die Wohnung wechselt,
    hinterlässt sonst eine Installation, an die niemand mehr herankommt."""
    ich, anderer = welt
    alte_id = ich.id

    klient.post(f"/api/benutzer/{anderer.id}/betreiber", json={"passwort": KENNWORT})

    # Der neue Betreiber meldet sich an und entfernt den alten.
    klient.post("/api/auth/abmelden")
    from app.services import benutzer as benutzerdienst

    anderer.passwort_hash = benutzerdienst.hashen(KENNWORT)
    db.commit()
    an = klient.post(
        "/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": KENNWORT}
    )
    assert an.status_code == 200, an.text

    weg = klient.delete(f"/api/benutzer/{alte_id}")
    assert weg.status_code == 204, weg.text
    # ⚠️ Die eigene Sitzung haelt sonst die alte Kopie im Gedaechtnis.
    db.expire_all()
    assert db.query(Benutzer).filter_by(id=alte_id).one_or_none() is None


def test_ohne_das_eigene_kennwort_geht_es_nicht(klient, db, welt):
    """⚠️ Der teuerste Knopf der Verwaltung. Eine geklaute Sitzung genügt
    nicht — dieselbe Überlegung wie beim Abschalten des zweiten Faktors."""
    ich, anderer = welt

    antwort = klient.post(
        f"/api/benutzer/{anderer.id}/betreiber", json={"passwort": "falsch-falsch"}
    )
    assert antwort.status_code == 401

    db.refresh(ich)
    db.refresh(anderer)
    assert ich.ist_betreiber is True
    assert anderer.ist_betreiber is False


def test_an_sich_selbst_geht_nicht(klient, db, welt):
    ich, anderer = welt
    antwort = klient.post(f"/api/benutzer/{ich.id}/betreiber", json={"passwort": KENNWORT})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "betreiber_an_sich_selbst"
    db.refresh(ich)
    assert ich.ist_betreiber is True


def test_an_niemanden_geht_nicht(klient, db, welt):
    ich, anderer = welt
    antwort = klient.post("/api/benutzer/gibtesnicht/betreiber", json={"passwort": KENNWORT})
    assert antwort.status_code == 404
    db.refresh(ich)
    assert ich.ist_betreiber is True


def test_wer_kein_betreiber_ist_kann_nicht_uebergeben(klient, db, welt):
    """⚠️ Sonst reicht sich jeder den Haken selbst."""
    ich, anderer = welt
    from app.services import benutzer as benutzerdienst

    anderer.passwort_hash = benutzerdienst.hashen(KENNWORT)
    db.commit()
    klient.post("/api/auth/abmelden")
    klient.post("/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": KENNWORT})

    antwort = klient.post(f"/api/benutzer/{anderer.id}/betreiber", json={"passwort": KENNWORT})
    assert antwort.status_code == 403

    db.refresh(ich)
    db.refresh(anderer)
    assert ich.ist_betreiber is True
    assert anderer.ist_betreiber is False


def test_die_bremse_haengt_auch_hier_dran(klient, db, welt):
    ich, anderer = welt
    codes = [
        klient.post(
            f"/api/benutzer/{anderer.id}/betreiber", json={"passwort": "falsch-falsch"}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in codes
