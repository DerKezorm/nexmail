"""Gemeinsame Vorbereitung für die Tests.

⚠️ **Die Umgebung wird gesetzt, bevor ``app`` importiert wird.** Die
Einstellungen sind zwischengespeichert (``lru_cache``) und die Datenbank-Engine
entsteht beim Import des Moduls — wer danach setzt, setzt ins Leere und wundert
sich, warum die Tests auf die echte Datenbank gehen.

⚠️ **Es gibt immer zwei Benutzer.** Auch wenn die Oberfläche in v1 nur einen
zeigt. Eine Trennung, die nie gegen einen zweiten geprüft wurde, ist nur
behauptet — und das merkt man erst beim Öffnen, wenn es teuer ist.
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
#: Der Einrichtungscode der Tests (Kontenmodul): fest, damit ``einrichten`` ihn kennt.
EINRICHTUNGSCODE = "test-einrichtung-code"
os.environ["NEXMAIL_SETUP_TOKEN"] = EINRICHTUNGSCODE

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import crypto  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import anmeldebremse  # noqa: E402
from app.services import benutzer as benutzerdienst  # noqa: E402
from app.services import zwei_faktor  # noqa: E402


# --- Zwei ``conftest`` unter einem Namen ---------------------------------- #
#
# ⚠️ **Die Vertragstests des Anmeldemoduls (``tests/nexoidc/``) bringen ihre
# eigene ``conftest.py`` mit**, unveraendert vom Anmeldemodul uebernommen und per
# Pruefsumme bewacht. pytest laedt beide unter dem Namen ``conftest``; wer
# zuletzt geladen wurde, steht in ``sys.modules``. nexmails Tests holen ihre
# Hilfen mit ``from conftest import ...`` (beim Sammeln), die Vertragstests
# mit ``import conftest`` (beim Laufen). Damit jeder die eigene bekommt, zeigt
# ``sys.modules["conftest"]`` beim Sammeln und vor jedem Test auf die
# ``conftest.py``, die dem Test am naechsten liegt.

_CONFTESTS: dict[Path, object] = {}


def pytest_plugin_registered(plugin, manager) -> None:
    datei = getattr(plugin, "__file__", None)
    if datei and Path(datei).name == "conftest.py":
        _CONFTESTS[Path(datei).resolve().parent] = plugin


def _naechste_conftest(pfad: Path) -> None:
    import sys

    pfad = Path(pfad).resolve()
    for ordner in [pfad, *pfad.parents]:
        modul = _CONFTESTS.get(ordner)
        if modul is not None:
            sys.modules["conftest"] = modul  # type: ignore[assignment]
            return


def pytest_collectstart(collector) -> None:
    if isinstance(collector, pytest.Module):
        _naechste_conftest(collector.path)


def pytest_runtest_setup(item) -> None:
    _naechste_conftest(item.path)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    engine.dispose()
    shutil.rmtree(_TESTORDNER, ignore_errors=True)


@pytest.fixture(autouse=True)
def ziel_sofort_nachziehen(monkeypatch):
    """Nach einem Zug zieht der Server den Zielordner im eigenen Faden nach
    (``handeln.ziel_nachziehen``). In Tests sofort und in derselben Sitzung,
    sonst hinge jede Zusicherung über den Zielordner am Zufall der Fäden."""
    from app.services import handeln

    monkeypatch.setattr(handeln, "NACHZIEHEN_IM_FADEN", False)


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


@pytest.fixture(autouse=True)
def post_sofort(monkeypatch):
    """post 1.1.0 stoesst nach dem Commit eine Runde der Outbox in einem eigenen Faden an; in Tests geht eine
    eingereihte Mail sofort in der Anfrage hinaus (``post_store.IM_FADEN``), sonst hinge jede Zusicherung ueber
    verschickte Post am Zufall der Faeden."""
    from app.services import post_store

    monkeypatch.setattr(post_store, "IM_FADEN", False)


@pytest.fixture(autouse=True)
def post_bruecke():
    """Das Mailmodul verschickt ueber ``smtplib``; in Tests geht jede Mail stattdessen an ``systempost.senden``
    (Empfaenger, Betreff, Text, HTML), das viele Tests abfangen. Nichts geht ins Netz."""
    from app.services import systempost
    from app.vendor import nexpost

    class Verbindung:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def send_message(self, nachricht) -> None:
            text = nachricht.get_body(("plain",))
            html = nachricht.get_body(("html",))
            systempost.senden(
                None,
                str(nachricht["To"]),
                str(nachricht["Subject"]),
                text.get_content() if text is not None else "",
                html.get_content() if html is not None else "",
            )

        def login(self, *args) -> None:
            pass

        def quit(self) -> None:
            pass

    nexpost.config.use_smtp(lambda *args, **kwargs: Verbindung())
    yield
    nexpost.config.use_smtp(None)


@pytest.fixture(autouse=True)
def verbinden_ohne_warten(monkeypatch):
    """verbinden 0.2.1 (BS6): ``ueber_klick`` wartet auf einen Partner, der die neue Verbindung noch speichert. Im
    ``TestClient`` speichert er erst, wenn der Haken fertig ist; Warten brächte nichts als Zeit."""
    from app.services import verbinden_store

    monkeypatch.setattr(verbinden_store, "NACH_ABSAGE", ())


@pytest.fixture(autouse=True)
def anbieterbild_sofort(monkeypatch):
    """Das Bild vom Anmeldeanbieter holt der Server in einem eigenen Faden; in Tests sofort und in derselben Runde."""
    from app.services import konten_store

    monkeypatch.setattr(konten_store, "BILD_IM_FADEN", False)


#: Ein Name „im Internet" für die KI-Tests: das DNS der Tests gibt ihn für ``*.example.com`` und ``*.example``.
KI_OEFFENTLICH = "93.184.215.14"

#: Rechner im eigenen Netz, die KI-Tests von vorher als eigenen Zugang nutzen; das Update setzt solche Rechner auf die
#: Liste des Betreibers (Modul ki, K4), also stehen sie in einer Installation von vorher dort.
KI_RECHNER = ["localhost:11434", "127.0.0.1:11434", "[::1]:11434", "10.0.0.20:11434", "[fd00::20]:11434",
              "172.16.5.9:1234", "100.101.102.103:11434", "ollama:11434", "nas.local:11434", "ki.intern.example"]


def ki_aufloesen(tabelle: dict[str, list[str]] | None = None):
    """Das DNS der KI-Tests (``nexki.client.resolver``): Adressen bleiben, wie sie sind, ``localhost`` ist 127.0.0.1,
    ``*.example(.com)`` liegt im Internet, sonst die ``tabelle``; Unbekanntes ist nicht auflösbar."""
    import ipaddress

    from app.vendor.nexki.net import Unreachable

    def aufloesen(host: str, port: int) -> list[str]:
        name = host.strip("[]")
        if tabelle and name in tabelle:
            return list(tabelle[name])
        try:
            return [str(ipaddress.ip_address(name))]
        except ValueError:
            pass
        if name == "localhost":
            return ["127.0.0.1"]
        if tabelle is None and (name.endswith(".example.com") or name.endswith(".example")):
            return [KI_OEFFENTLICH]
        raise Unreachable(name)

    return aufloesen


def ohne_rahmen(text: str) -> str:
    """Der Text zwischen den zwei Zeilen der Zufallsmarke, mit denen das Modul ki Material rahmt (``nexki.frame``)."""
    zeilen = text.splitlines()
    assert len(zeilen) >= 3 and zeilen[0] == zeilen[-1] and zeilen[0].startswith("TEXT-"), text[:80]
    return "\n".join(zeilen[1:-1])


@pytest.fixture
def ki_wie_vorher(monkeypatch):
    """KI-Tests aus der Zeit vor dem Modul ki 0.1.0: eine nexmail-Installation von vorher, also „Jedes Konto selbst"
    (das Update schreibt das fest, K2), die bisher genutzten Rechner im eigenen Netz auf der Liste (K4), und ein DNS,
    das keine Leitung braucht."""
    import json

    from app.db import SessionLocal, einstellung_schreiben
    from app.vendor import nexki

    monkeypatch.setattr(nexki.client, "resolver", ki_aufloesen())
    nexki.brake.BRAKE.forget()
    with SessionLocal() as sitzung:
        einstellung_schreiben(sitzung, "ki_mode", json.dumps("own"))
        einstellung_schreiben(sitzung, "ki_hosts", json.dumps(KI_RECHNER))
    yield
    nexki.brake.BRAKE.forget()


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


def einrichten(
    klient: TestClient,
    benutzername: str = "betreiber",
    passwort: str = "sehr-geheim-123",
    anzeigename: str = "",
):
    """Erstes Konto anlegen, mit Einrichtungscode und Anzeigenamen (Kontenmodul). Danach ist man angemeldet.

    ⚠️ **Ohne zweiten Faktor** — seit dem 01.09.2026 ist er eine Wahl, keine
    Pflicht, und die Ersteinrichtung erzwingt ihn nicht mehr. Wer ihn im Test
    braucht, schaltet ihn mit ``zwei_faktor_an`` ein.
    """
    antwort = klient.post(
        "/api/setup/konto",
        json={
            "benutzername": benutzername,
            "passwort": passwort,
            "anzeigename": anzeigename or benutzername,
            "einrichtungscode": EINRICHTUNGSCODE,
        },
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
    "EINRICHTUNGSCODE",
    "einrichten",
    "zweiten_benutzer_anlegen",
]
