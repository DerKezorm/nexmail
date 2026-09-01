"""Gemeinsame Vorbereitung für die Tests.

⚠️ **Die Umgebung wird gesetzt, bevor ``app`` importiert wird.** Die
Einstellungen sind zwischengespeichert (``lru_cache``) und die Datenbank-Engine
entsteht beim Import des Moduls — wer danach setzt, setzt ins Leere und wundert
sich, warum die Tests auf die echte Datenbank gehen.

⚠️ **Es gibt immer zwei Benutzer.** Auch wenn die Oberfläche in v1 nur einen
zeigt. Eine Trennung, die nie gegen einen zweiten geprüft wurde, ist nur
behauptet — und das merkt man erst beim Öffnen, wenn es teuer ist.
Siehe FALLSTRICKE.md §5.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TESTORDNER = Path(tempfile.mkdtemp(prefix="nexmail-test-"))

os.environ["NEXMAIL_DATA_DIR"] = str(_TESTORDNER)
os.environ["NEXMAIL_SECRET_KEY"] = "nur-fuer-tests-nicht-geheim"
os.environ["NEXMAIL_ZWEI_FAKTOR_AUS"] = "false"
os.environ["NEXMAIL_URL_BASE"] = ""
os.environ["NEXMAIL_CLIENT_IP"] = ""
# ⚠️ Kein Hintergrundabgleich in Tests. Ein Faden, der nebenher IMAP-
# Verbindungen aufmacht, waere die unangenehmste Sorte Flackern: Er schlaegt
# irgendwo zu, wo niemand ihn erwartet.
os.environ["NEXMAIL_TAKT_SEKUNDEN"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import crypto  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import anmeldebremse  # noqa: E402
from app.services import benutzer as benutzerdienst  # noqa: E402
from app.services import zwei_faktor  # noqa: E402


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    engine.dispose()
    shutil.rmtree(_TESTORDNER, ignore_errors=True)


@pytest.fixture(autouse=True)
def frische_datenbank():
    """Jeder Test bekommt eine leere Datenbank, ein leeres Blob-Verzeichnis
    und eine leere Bremse.

    ⚠️ **Die Anhänge müssen mit weg.** Ohne das schleppt ein Test die Dateien
    des vorigen mit - und ein Test, der zählt, wie viele Blobs entstanden
    sind, zählt die des Nachbarn mit. Genau so ist er hier beim ersten Lauf
    fehlgeschlagen.
    """
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as verbindung:
        # ⚠️ **``drop_all`` kennt nur die ORM-Tabellen.** Der Volltextindex
        # entsteht per rohem SQL und blieb deshalb ueber **jeden** Test hinweg
        # stehen — mitsamt seinen Eintraegen. Er zeigt bei
        # ``content='nachricht'`` nur Zeilennummern; die naechste Testdatei
        # legt Nachrichten mit denselben Nummern an, und die Suche liefert
        # dann fremde Treffer.
        #
        # Am 01.09.2026 aufgefallen, als eine neue Testdatei die Nummernfolge
        # verschob: Sieben Suchtests schlugen fehl, einzeln liefen sie alle.
        # Der Fehler lag seit Beginn hier und war nur nie sichtbar.
        verbindung.execute(text("DROP TABLE IF EXISTS nachricht_fts"))
        verbindung.execute(text("PRAGMA foreign_keys=ON"))

    blobs = _TESTORDNER / "blobs"
    if blobs.is_dir():
        shutil.rmtree(blobs, ignore_errors=True)

    # ⚠️ **Und die Ruecksetzpunkte.** Sie liegen als Dateien neben der
    # Datenbank, ``drop_all`` sieht sie nicht — jeder Test erbte damit die des
    # vorigen. Ein Test, der zaehlt, wie viele angelegt wurden, zaehlt dann die
    # der Nachbarn mit. Dieselbe Sorte Fehler wie beim Suchindex und bei den
    # Anhaengen, und sie faellt genauso spaet auf: erst, wenn jemand zaehlt.
    ruecksetzpunkte = _TESTORDNER / "sicherungen"
    if ruecksetzpunkte.is_dir():
        shutil.rmtree(ruecksetzpunkte, ignore_errors=True)

    init_db()
    anmeldebremse.zuruecksetzen()
    yield
    engine.dispose()


@pytest.fixture
def db():
    with SessionLocal() as sitzung:
        yield sitzung


@pytest.fixture
def klient():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def zweiter_klient():
    """Ein zweiter Browser — für alles, was mit Sitzungen zu tun hat."""
    with TestClient(app) as c:
        yield c


# --- Hilfen ------------------------------------------------------------- #


def einrichten(klient: TestClient, benutzername: str = "betreiber", passwort: str = "sehr-geheim-123"):
    """Erstes Konto anlegen. Danach ist man angemeldet.

    ⚠️ **Ohne zweiten Faktor** — seit dem 01.09.2026 ist er eine Wahl, keine
    Pflicht, und die Ersteinrichtung erzwingt ihn nicht mehr. Wer ihn im Test
    braucht, schaltet ihn mit ``zwei_faktor_an`` ein.
    """
    antwort = klient.post(
        "/api/setup/konto",
        json={"benutzername": benutzername, "passwort": passwort},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def zwei_faktor_an(klient: TestClient) -> tuple[str, list[str]]:
    """Den zweiten Faktor für den angemeldeten Benutzer einschalten.

    Gibt Geheimnis und Wiederherstellungscodes zurück — beides gibt es im
    Leben genau einmal.
    """
    start = klient.post("/api/auth/zwei-faktor/starten")
    assert start.status_code == 200, start.text
    geheimnis = start.json()["geheimnis"]

    fertig = klient.post(
        "/api/auth/zwei-faktor/bestaetigen", json={"code": aktueller_code(geheimnis)}
    )
    assert fertig.status_code == 200, fertig.text
    return geheimnis, fertig.json()["codes"]


def aktueller_code(geheimnis: str) -> str:
    import pyotp

    return pyotp.TOTP(geheimnis).now()


def zweiten_benutzer_anlegen(db, benutzername: str = "zweiter", passwort: str = "auch-geheim-456"):
    """Ein zweites Konto, direkt in der Datenbank — mit fertigem zweitem Faktor."""
    person = benutzerdienst.anlegen(db, benutzername, passwort)
    geheimnis = zwei_faktor.geheimnis_erzeugen()
    zwei_faktor.geheimnis_speichern(person, geheimnis)
    person.totp_bestaetigt = True
    db.commit()
    return person, geheimnis


def anmelden(klient: TestClient, benutzername: str, passwort: str, geheimnis: str) -> None:
    antwort = klient.post(
        "/api/auth/anmelden", json={"benutzername": benutzername, "passwort": passwort}
    )
    assert antwort.status_code == 200, antwort.text
    if antwort.json()["schritt"] != "fertig":
        zweiter = klient.post("/api/auth/code", json={"code": aktueller_code(geheimnis)})
        assert zweiter.status_code == 200, zweiter.text


__all__ = [
    "aktueller_code",
    "anmelden",
    "zwei_faktor_an",
    "crypto",
    "einrichten",
    "zweiten_benutzer_anlegen",
]
