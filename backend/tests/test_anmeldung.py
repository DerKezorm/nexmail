"""Die Anmeldung — der Block, der nicht optional ist.

Jeder Test hier steht für eine Zusage aus FALLSTRICKE.md. Wenn einer rot wird,
ist eine davon gebrochen — und keine davon ist eine Kleinigkeit.
"""

from __future__ import annotations

import time

import pyotp
import pytest

from app.services import anmeldebremse
from conftest import (
    aktueller_code,
    anmelden,
    einrichten,
    zwei_faktor_an,
    zweiten_benutzer_anlegen,
)

PASSWORT = "sehr-geheim-123"


def test_einrichtung_ist_danach_zu(klient):
    """Sobald ein Konto existiert, gibt es den Weg nicht mehr — 404, nicht 403."""
    einrichten(klient)
    zweiter = klient.post(
        "/api/setup/konto", json={"benutzername": "eindringling", "passwort": "auch-lang-genug"}
    )
    assert zweiter.status_code == 404


def test_passwort_allein_kommt_nicht_durch(klient):
    """Richtiges Passwort ohne Code ist **keine** Anmeldung.

    ⚠️ Gilt seit dem 01.09.2026 nur noch für Benutzer, die den zweiten Faktor
    **eingeschaltet** haben — er ist eine Wahl, keine Pflicht. Wer ihn an hat,
    darf sich darauf verlassen: Genau das ist der Sinn des Einschaltens.
    """
    einrichten(klient)
    zwei_faktor_an(klient)
    klient.cookies.clear()

    antwort = klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT}
    )
    assert antwort.status_code == 200
    assert antwort.json()["schritt"] == "code"

    # Das Cookie ist gesetzt - und trotzdem kommt man nirgends hin.
    assert klient.get("/api/auth/ich").status_code == 401
    assert klient.get("/api/sitzungen").status_code == 401
    assert klient.get("/api/einstellungen").status_code == 401


def test_falscher_code_kommt_nicht_durch(klient):
    einrichten(klient)
    zwei_faktor_an(klient)
    klient.cookies.clear()
    klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})

    assert klient.post("/api/auth/code", json={"code": "000000"}).status_code == 401
    assert klient.get("/api/auth/ich").status_code == 401


def test_derselbe_code_gilt_kein_zweites_mal(klient):
    """⚠️ Der Kern des zweiten Faktors.

    Ohne diese Sperre nützt ein abgefangener Code dem Angreifer noch dreißig
    Sekunden — und genau so lange braucht niemand, um ihn weiterzureichen.
    """
    einrichten(klient)
    geheimnis, _ = zwei_faktor_an(klient)
    code = aktueller_code(geheimnis)

    # Der Code aus dem Einschalten ist bereits verbraucht. Ein zweiter Browser
    # mit demselben Code darf nicht hineinkommen.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as zweiter:
        zweiter.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})
        antwort = zweiter.post("/api/auth/code", json={"code": code})
        assert antwort.status_code == 401, "Ein verbrauchter Code wurde ein zweites Mal akzeptiert."


def test_bremse_greift_am_code(klient):
    """Sechs Stellen sind eine Million Möglichkeiten — ohne Bremse kein Schutz."""
    einrichten(klient)
    zwei_faktor_an(klient)
    klient.cookies.clear()
    klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})

    codes = [f"{n:06d}" for n in range(20)]
    gebremst = False
    for code in codes:
        antwort = klient.post("/api/auth/code", json={"code": code})
        if antwort.status_code == 429:
            assert "Retry-After" in antwort.headers
            gebremst = True
            break
    assert gebremst, "Die Bremse hat nach zwanzig Fehlversuchen nicht gegriffen."


def test_bremse_greift_am_passwort(klient):
    einrichten(klient)
    klient.cookies.clear()

    gebremst = False
    for _ in range(20):
        antwort = klient.post(
            "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "falsch-falsch"}
        )
        if antwort.status_code == 429:
            gebremst = True
            break
    assert gebremst, "Die Bremse hat am Passwort nicht gegriffen."


def test_bremse_antwortet_sofort(klient):
    """⚠️ Es wird nicht geschlafen — sonst legt ein Angreifer den Dienst lahm."""
    einrichten(klient)
    klient.cookies.clear()
    for _ in range(12):
        klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "falsch"})

    start = time.monotonic()
    antwort = klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "falsch"})
    dauer = time.monotonic() - start
    assert antwort.status_code == 429
    assert dauer < 0.5, f"Die abgewiesene Anfrage hat {dauer:.1f} s gekostet - wird hier geschlafen?"


def test_wiederherstellungscode_gilt_genau_einmal(klient):
    einrichten(klient)
    _, codes = zwei_faktor_an(klient)
    code = codes[0]
    klient.cookies.clear()

    klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})
    assert klient.post("/api/auth/wiederherstellung", json={"code": code}).status_code == 200
    assert klient.get("/api/auth/ich").status_code == 200

    # Derselbe Code, zweiter Anlauf.
    klient.cookies.clear()
    anmeldebremse.zuruecksetzen()
    klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})
    zweiter = klient.post("/api/auth/wiederherstellung", json={"code": code})
    assert zweiter.status_code == 401, "Ein verbrauchter Wiederherstellungscode wurde akzeptiert."


def test_abgemeldete_sitzung_ist_sofort_tot(klient):
    """Der Gegenwert dafür, dass die Sitzung im Server liegt."""
    einrichten(klient)
    assert klient.get("/api/auth/ich").status_code == 200

    assert klient.post("/api/auth/abmelden").status_code == 204
    assert klient.get("/api/auth/ich").status_code == 401


def test_alle_geraete_abmelden_wirkt_sofort(klient, zweiter_klient):
    einrichten(klient)
    geheimnis, _ = zwei_faktor_an(klient)

    # Zweites Gerät anmelden. Der Code aus der Einrichtung ist verbraucht,
    # also den des *nächsten* Zeitschritts nehmen - die Toleranz von einem
    # Schritt akzeptiert ihn. Eine halbe Minute zu schlafen wäre der
    # naheliegende Weg und würde die Testreihe für nichts verlängern.
    zweiter_klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT}
    )
    naechster = pyotp.TOTP(geheimnis).at(int(time.time()) + 30)
    assert zweiter_klient.post("/api/auth/code", json={"code": naechster}).status_code == 200
    assert zweiter_klient.get("/api/auth/ich").status_code == 200

    ergebnis = klient.post("/api/sitzungen/alle-beenden")
    assert ergebnis.status_code == 200
    assert ergebnis.json()["beendet"] == 1

    assert zweiter_klient.get("/api/auth/ich").status_code == 401
    assert klient.get("/api/auth/ich").status_code == 200, "Die eigene Sitzung wurde mitgerissen."


def test_ohne_zweiten_faktor_kommt_man_direkt_hinein(klient):
    """⚠️ **Der zweite Faktor ist eine Wahl** (01.09.2026).

    Vorher zwang die Ersteinrichtung ihn auf, und die Anmeldung blieb in einem
    Assistenten stehen, aus dem man ohne Telefon nicht herauskam. Das sperrte
    genau die Leute aus, fuer die nexmail gedacht ist: jemanden, der es abends
    im eigenen Netz aufsetzt.
    """
    antwort = klient.post(
        "/api/setup/konto", json={"benutzername": "betreiber", "passwort": PASSWORT}
    )
    assert antwort.status_code == 201, antwort.text
    # Schon angemeldet, ohne Zwischenschritt.
    assert klient.get("/api/auth/ich").json()["zwei_faktor_aktiv"] is False

    klient.cookies.clear()
    weiter = klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT}
    )
    assert weiter.json()["schritt"] == "fertig"
    assert klient.get("/api/auth/ich").status_code == 200


def test_einschalten_geht_nur_mit_probe(klient):
    """⚠️ Ein Faktor, der ohne Probe gilt, sperrt beim naechsten Anmelden aus.

    Falsch gehende Uhr, QR nie angekommen — es faellt erst auf, wenn niemand
    mehr weiss, woran es lag.
    """
    einrichten(klient)
    start = klient.post("/api/auth/zwei-faktor/starten")
    assert start.status_code == 200

    # Falscher Code: nichts wird eingeschaltet.
    assert klient.post("/api/auth/zwei-faktor/bestaetigen", json={"code": "000000"}).status_code == 401
    assert klient.get("/api/auth/ich").json()["zwei_faktor_aktiv"] is False


def test_ohne_qr_code_laesst_sich_nichts_bestaetigen(klient):
    einrichten(klient)
    antwort = klient.post("/api/auth/zwei-faktor/bestaetigen", json={"code": "123456"})
    assert antwort.status_code == 400


def test_abschalten_braucht_das_kennwort(klient):
    """⚠️ Sonst genuegt ein unbeaufsichtigter Bildschirm."""
    einrichten(klient)
    zwei_faktor_an(klient)

    falsch = klient.post("/api/auth/zwei-faktor/aus", json={"passwort": "danebengetippt"})
    assert falsch.status_code == 401
    assert klient.get("/api/auth/ich").json()["zwei_faktor_aktiv"] is True

    richtig = klient.post("/api/auth/zwei-faktor/aus", json={"passwort": PASSWORT})
    assert richtig.status_code == 204
    assert klient.get("/api/auth/ich").json()["zwei_faktor_aktiv"] is False


def test_abschalten_raeumt_geheimnis_und_codes_weg(klient, db):
    """⚠️ **Der alte QR-Code darf nicht weitergelten.**

    Blieben Geheimnis und Wiederherstellungscodes liegen, waere nach dem
    Wiedereinschalten alles gueltig, was den alten Code je abfotografiert hat —
    und ein Zettel von vor einem Jahr ebenso.
    """
    from app.models import Benutzer, Wiederherstellungscode

    einrichten(klient)
    altes_geheimnis, _ = zwei_faktor_an(klient)
    assert db.query(Wiederherstellungscode).count() > 0

    assert klient.post("/api/auth/zwei-faktor/aus", json={"passwort": PASSWORT}).status_code == 204

    db.expire_all()
    person = db.query(Benutzer).one()
    assert person.totp_geheimnis == ""
    assert person.totp_letzter_schritt == 0
    assert db.query(Wiederherstellungscode).count() == 0

    # Und der alte Code oeffnet nichts mehr.
    klient.cookies.clear()
    klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})
    neues, _ = zwei_faktor_an(klient)
    assert neues != altes_geheimnis


def test_zwei_benutzer_sehen_nur_ihre_sitzungen(klient, zweiter_klient, db):
    """⚠️ Die Trennung, geprüft statt behauptet."""
    einrichten(klient)
    _, geheimnis2 = zweiten_benutzer_anlegen(db)

    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    meine = klient.get("/api/sitzungen").json()
    seine = zweiter_klient.get("/api/sitzungen").json()

    assert len(meine) == 1 and len(seine) == 1
    assert {s["id"] for s in meine}.isdisjoint({s["id"] for s in seine})

    # Und die fremde Kennung lässt sich nicht kündigen.
    fremd = seine[0]["id"]
    assert klient.delete(f"/api/sitzungen/{fremd}").status_code == 404
    assert zweiter_klient.get("/api/auth/ich").status_code == 200


def test_notausgang_ueberspringt_den_faktor(klient, monkeypatch):
    """``NEXMAIL_2FA_AUS`` — der Weg zurück, wenn Telefon und Codes weg sind."""
    einrichten(klient)
    klient.cookies.clear()

    from app.config import get_settings

    einstellungen = get_settings()
    monkeypatch.setattr(einstellungen, "zwei_faktor_aus", True)

    antwort = klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT}
    )
    assert antwort.json()["schritt"] == "fertig"
    assert klient.get("/api/auth/ich").status_code == 200


@pytest.mark.parametrize("zu_kurz", ["", "kurz", "neunzeich"])
def test_passwortlaenge_wird_geprueft(klient, zu_kurz):
    antwort = klient.post("/api/setup/konto", json={"benutzername": "betreiber", "passwort": zu_kurz})
    assert antwort.status_code in (400, 422)


def test_totp_geheimnis_liegt_verschluesselt_in_der_datenbank(klient, db):
    """Ein Geheimnis im Klartext in der Datei wäre der ganze Aufwand umsonst."""
    einrichten(klient)
    geheimnis, _ = zwei_faktor_an(klient)
    from sqlalchemy import text

    roh = db.execute(text("select totp_geheimnis from benutzer")).scalar_one()
    assert roh.startswith("v1:")
    assert geheimnis not in roh


def test_verschluesselung_haengt_am_kontext(klient, db):
    """⚠️ Ein Wert lässt sich nicht an eine andere Stelle kopieren.

    Das ist der Unterschied zwischen AES-GCM mit Zusatzdaten und Fernet.
    """
    einrichten(klient)
    zwei_faktor_an(klient)
    from app import crypto
    from app.models import Benutzer

    person = db.query(Benutzer).one()
    with pytest.raises(crypto.SchluesselFehler):
        crypto.entschluesseln(person.totp_geheimnis, "benutzer:jemand-anderes:totp")


def test_totp_toleranz_akzeptiert_den_vorigen_schritt(klient):
    """Eine leicht nachgehende Uhr darf niemanden aussperren."""
    einrichten(klient)
    geheimnis, _ = zwei_faktor_an(klient)
    klient.cookies.clear()
    anmeldebremse.zuruecksetzen()

    totp = pyotp.TOTP(geheimnis)
    naechster = totp.at(int(time.time()) + 30)

    klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": PASSWORT})
    assert klient.post("/api/auth/code", json={"code": naechster}).status_code == 200


# --- Eigenes Kennwort ändern ------------------------------------------------ #


def test_kennwort_aendern_und_damit_anmelden(klient):
    """Der Rundlauf: ändern, altes geht nicht mehr, neues geht."""
    einrichten(klient)

    antwort = klient.put(
        "/api/auth/passwort",
        json={"altes": "sehr-geheim-123", "neues": "noch-geheimer-456"},
    )
    assert antwort.status_code == 200, antwort.text

    klient.post("/api/auth/abmelden")
    alt = klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "sehr-geheim-123"}
    )
    assert alt.status_code == 401, "Das alte Kennwort funktioniert noch."

    neu = klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "noch-geheimer-456"}
    )
    assert neu.status_code == 200


def test_ohne_das_bisherige_kennwort_geht_es_nicht(klient):
    """⚠️ **Sonst genügt eine geklaute Sitzung**, um den Zugang zu übernehmen.

    Ein offener Rechner, ein mitgelesenes Cookie — und der Eigentümer ist
    ausgesperrt. Das alte Kennwort ist der Beweis, dass der Richtige sitzt.
    """
    einrichten(klient)

    antwort = klient.put(
        "/api/auth/passwort", json={"altes": "falsch-geraten", "neues": "noch-geheimer-456"}
    )

    assert antwort.status_code == 400
    # Und das alte gilt weiterhin.
    klient.post("/api/auth/abmelden")
    assert (
        klient.post(
            "/api/auth/anmelden",
            json={"benutzername": "betreiber", "passwort": "sehr-geheim-123"},
        ).status_code
        == 200
    )


def test_ein_zu_kurzes_kennwort_wird_abgewiesen(klient):
    einrichten(klient)
    antwort = klient.put("/api/auth/passwort", json={"altes": "sehr-geheim-123", "neues": "kurz"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "passwort_zu_kurz"
    assert antwort.json()["werte"]["min"]


def test_dasselbe_kennwort_noch_einmal_ist_kein_wechsel(klient):
    einrichten(klient)
    antwort = klient.put(
        "/api/auth/passwort", json={"altes": "sehr-geheim-123", "neues": "sehr-geheim-123"}
    )
    assert antwort.status_code == 400


def test_ein_wechsel_wirft_die_anderen_geraete_hinaus(klient, zweiter_klient):
    """⚠️ **Der Punkt der Übung.**

    Wer sein Kennwort ändert, tut das meist, weil er jemanden im Verdacht hat.
    Ein Wechsel, nach dem der andere angemeldet bleibt, hilft nicht.
    """
    einrichten(klient)
    _, codes = zwei_faktor_an(klient)
    # ⚠️ Mit einem Wiederherstellungscode, nicht mit dem TOTP-Code: Derselbe
    # Zeitschritt gilt nur einmal - genau das prüft
    # ``test_derselbe_code_kein_zweites_mal``. Zwei Anmeldungen in derselben
    # halben Minute scheitern also zu Recht.
    zweiter_klient.post(
        "/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "sehr-geheim-123"}
    )
    zweiter_klient.post("/api/auth/wiederherstellung", json={"code": codes[0]})
    assert zweiter_klient.get("/api/auth/ich").status_code == 200

    antwort = klient.put(
        "/api/auth/passwort",
        json={"altes": "sehr-geheim-123", "neues": "noch-geheimer-456"},
    )
    assert antwort.status_code == 200
    assert antwort.json()["abgemeldet"] >= 1

    assert zweiter_klient.get("/api/auth/ich").status_code == 401, (
        "Das andere Gerät ist noch angemeldet."
    )
    # Das eigene bleibt drin - sonst wirft man sich selbst hinaus.
    assert klient.get("/api/auth/ich").status_code == 200
