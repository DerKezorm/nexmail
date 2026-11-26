"""Den Betreiber-Haken weitergeben, und seit konten 1.1.0 mehrere Betreiber.

⚠️ **Mindestens ein Betreiber, immer.** Null sind das Ende: Aus der Anwendung heraus führt dann kein Weg zurück in
die Verwaltung. Seit dem Bauplan „Einstellungen" gibt es mehrere Betreiber; „Betreiber übergeben" fällt weg, sein
alter Weg macht den anderen zum Betreiber, und wer ihn ruft, bleibt es.
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


def test_der_alte_weg_macht_einen_zweiten_betreiber(klient, db, welt):
    ich, anderer = welt

    antwort = klient.post(
        f"/api/benutzer/{anderer.id}/betreiber", json={"passwort": KENNWORT}
    )
    assert antwort.status_code == 204, antwort.text

    db.refresh(ich)
    db.refresh(anderer)
    assert anderer.ist_betreiber is True
    # Seit konten 1.1.0: niemand stuft sich selbst zurück, also gibt es danach zwei.
    assert ich.ist_betreiber is True


def test_zum_mitglied_machen_und_nie_den_letzten(klient, db, welt):
    """``PUT /api/benutzer/{id}/rolle``: zurück zum Mitglied, mit dem eigenen Passwort; am eigenen Konto nie."""
    ich, anderer = welt
    assert klient.put(f"/api/benutzer/{anderer.id}/rolle", json={"betreiber": True, "passwort": KENNWORT}).status_code == 200
    db.refresh(anderer)
    assert anderer.ist_betreiber is True
    zurueck = klient.put(f"/api/benutzer/{anderer.id}/rolle", json={"betreiber": False, "passwort": KENNWORT})
    assert zurueck.status_code == 200, zurueck.text
    assert zurueck.json()["ist_betreiber"] is False
    selbst = klient.put(f"/api/benutzer/{ich.id}/rolle", json={"betreiber": False, "passwort": KENNWORT})
    assert selbst.status_code == 409
    assert selbst.json()["detail"] == "cannot_demote_self"


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

    weg = klient.request("DELETE", f"/api/benutzer/{alte_id}", json={"passwort": KENNWORT})
    assert weg.status_code == 204, weg.text
    # ⚠️ Die eigene Sitzung haelt sonst die alte Kopie im Gedaechtnis.
    db.expire_all()
    # Seit konten 1.1.0: geloescht, 30 Tage zurueckholbar, danach endgueltig weg.
    alt = db.query(Benutzer).filter_by(id=alte_id).one()
    assert alt.geloescht_am is not None
    from datetime import timedelta

    alt.geloescht_am = alt.geloescht_am - timedelta(days=31)
    db.commit()
    from app.services import takt

    assert takt.konten_endgueltig_loeschen() == [alte_id]
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


# --- konten 1.1.0: Sperren, Loeschen mit 30 Tagen, Zurueckholen -------------------------------------------------- #


def _zweiter_angemeldet(db, anderer, zweiter_klient):
    from app.services import benutzer as benutzerdienst

    anderer.passwort_hash = benutzerdienst.hashen("auch-geheim-456")
    db.commit()
    an = zweiter_klient.post("/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": "auch-geheim-456"})
    assert an.status_code == 200, an.text
    assert zweiter_klient.get("/api/auth/ich").status_code == 200


def test_sperren_beendet_die_sitzung_und_entsperren_laesst_wieder_herein(klient, zweiter_klient, db, welt):
    _ich, anderer = welt
    _zweiter_angemeldet(db, anderer, zweiter_klient)

    gesperrt = klient.post(f"/api/benutzer/{anderer.id}/sperren", json={"passwort": KENNWORT})
    assert gesperrt.status_code == 200, gesperrt.text
    assert gesperrt.json()["gesperrt_seit"]
    assert zweiter_klient.get("/api/auth/ich").status_code == 401
    an = zweiter_klient.post("/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": "auch-geheim-456"})
    assert an.status_code != 200

    ohne = klient.post(f"/api/benutzer/{anderer.id}/entsperren", json={"passwort": "falsch-falsch"})
    assert ohne.status_code in (400, 401)
    frei = klient.post(f"/api/benutzer/{anderer.id}/entsperren", json={"passwort": KENNWORT})
    assert frei.status_code == 200, frei.text
    assert frei.json()["gesperrt_seit"] is None
    an = zweiter_klient.post("/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": "auch-geheim-456"})
    assert an.status_code == 200, an.text


def test_loeschen_laesst_dreissig_tage_zum_zurueckholen(klient, zweiter_klient, db, welt):
    _ich, anderer = welt
    _zweiter_angemeldet(db, anderer, zweiter_klient)

    weg = klient.request("DELETE", f"/api/benutzer/{anderer.id}", json={"passwort": KENNWORT})
    assert weg.status_code == 204, weg.text
    assert zweiter_klient.get("/api/auth/ich").status_code == 401
    zeile = next(b for b in klient.get("/api/benutzer").json()["benutzer"] if b["id"] == anderer.id)
    assert zeile["geloescht_am"] and zeile["endgueltig_am"]

    zurueck = klient.post(f"/api/benutzer/{anderer.id}/zurueckholen", json={"passwort": KENNWORT})
    assert zurueck.status_code == 200, zurueck.text
    assert zurueck.json()["geloescht_am"] is None
    an = zweiter_klient.post("/api/auth/anmelden", json={"benutzername": "zweiter", "passwort": "auch-geheim-456"})
    assert an.status_code == 200, an.text


def test_den_letzten_betreiber_loescht_und_sperrt_niemand(klient, db, welt):
    ich, _anderer = welt
    assert klient.request("DELETE", f"/api/benutzer/{ich.id}", json={"passwort": KENNWORT}).json()["detail"] == (
        "sich_selbst_entfernen"
    )
    selbst = klient.post(f"/api/benutzer/{ich.id}/sperren", json={"passwort": KENNWORT})
    assert selbst.status_code == 409 and selbst.json()["detail"] == "cannot_block_self"


def test_ein_api_schluessel_eines_gesperrten_kontos_wirkt_nicht(klient, db, welt):
    """Der Schluessel bleibt stehen (Entsperren bringt ihn zurueck), abgewiesen wird er, solange das Konto gesperrt ist."""
    from app.services import apischluessel as apidienst

    _ich, anderer = welt
    from app.db import einstellung_schreiben

    einstellung_schreiben(db, apidienst.SCHALTER, "1")
    from app.models import Konto

    postfach = Konto(
        benutzer_id=anderer.id, anzeigename="Probe", adresse="zweiter@example.com",
        imap_server="imap.example.com", imap_benutzer="zweiter", smtp_server="smtp.example.com", smtp_benutzer="zweiter",
    )
    db.add(postfach)
    db.commit()
    _eintrag, geheim = apidienst.anlegen(db, anderer, "Probe", stufe="anzahl", konten=[postfach.id], aufgaben=False)
    db.commit()
    kopf = {"Authorization": f"Bearer {geheim}"}
    from fastapi.testclient import TestClient

    from app.main import app

    fremd = TestClient(app)
    vorher = fremd.get("/api/v1/me", headers=kopf).status_code
    assert klient.post(f"/api/benutzer/{anderer.id}/sperren", json={"passwort": KENNWORT}).status_code == 200
    assert fremd.get("/api/v1/me", headers=kopf).status_code == 401
    assert klient.post(f"/api/benutzer/{anderer.id}/entsperren", json={"passwort": KENNWORT}).status_code == 200
    assert fremd.get("/api/v1/me", headers=kopf).status_code == vorher
