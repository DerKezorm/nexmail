"""nexwasneu contract tests: nexmail's adapter (from ``tests-fuer-apps/adapter_template.py`` of wasneu 0.1.0).

nexmail keeps the version an account read as ``benutzer.wasneu_gesehen``, names it in ``/api/auth/ich`` and keeps its
route of before ``POST /api/auth/ich/wasneu-gesehen``; the module's routes are under ``/api/whats-new``. The texts lie
in ``backend/app/wasneu/`` (German and English).

Accounts as in the adapter of ``updates``: nexmail's test run (conftest) has a fresh database and data folder for every
test; the operator is set up over the real setup route, the member is added to the database, both sign in over the
real route.
"""

from __future__ import annotations

from typing import Any

from wasneu_contract import StandardAdapter

KENNWORT = {"operator": "betreib-geheim-789", "member": "mitglied-geheim-456"}
NAME = {"operator": "betreiber", "member": "mitglied"}


class Adapter(StandardAdapter):
    package = "app.vendor.nexwasneu"
    root_package = "app"
    prefix = "/api/whats-new"
    old_seen: tuple[str, ...] = ("/api/auth/ich/wasneu-gesehen",)
    me = "/api/auth/ich"
    me_field = "wasneu_gesehen"

    def start(self) -> None:
        from app.services import wasneu

        wasneu.konfigurieren()
        self._clients: list[Any] = []
        self._rollen: dict[str, Any] = {}
        self._neue = 0

    def stop(self) -> None:
        for client in self._clients:
            client.__exit__(None, None, None)
        self._clients.clear()

    def _neu(self) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        client.__enter__()
        self._clients.append(client)
        return client

    def _konten(self) -> None:
        import os

        from app.db import SessionLocal, hat_benutzer
        from app.models import Benutzer
        from app.services import benutzer as benutzerdienst

        with SessionLocal() as db:
            leer = not hat_benutzer(db)
        if leer:
            antwort = self._neu().post(
                "/api/setup/konto",
                json={
                    "benutzername": NAME["operator"],
                    "passwort": KENNWORT["operator"],
                    "anzeigename": "Betreiber",
                    "einrichtungscode": os.environ["NEXMAIL_SETUP_TOKEN"],
                },
            )
            assert antwort.status_code == 201, antwort.text
        with SessionLocal() as db:
            if db.query(Benutzer).filter_by(benutzername=NAME["member"]).first() is None:
                benutzerdienst.anlegen(db, NAME["member"], KENNWORT["member"], anzeigename="Mitglied")

    def client(self, role: str) -> Any:
        if role == "anonymous":
            return self._neu()
        if role not in self._rollen:
            self._konten()
            client = self._neu()
            antwort = client.post(
                "/api/auth/anmelden", json={"benutzername": NAME[role], "passwort": KENNWORT[role]}
            )
            assert antwort.status_code == 200, antwort.text
            self._rollen[role] = client
        return self._rollen[role]

    def _zeile(self, role: str, version: str | None = None) -> str:
        from app.db import SessionLocal
        from app.models import Benutzer

        self._konten()
        with SessionLocal() as db:
            person = db.query(Benutzer).filter_by(benutzername=NAME[role]).one()
            if version is not None:
                person.wasneu_gesehen = version
                db.commit()
            return person.wasneu_gesehen or ""

    def stored_seen(self, role: str) -> str:
        return self._zeile(role)

    def set_seen(self, role: str, version: str) -> None:
        self._zeile(role, version)

    def new_account_seen(self) -> str:
        """As the setup and the operator make one (``services.benutzer.anlegen``); the ways over the module konten and
        a sign-in provider are in ``tests/test_wasneu.py``."""
        from app.db import SessionLocal
        from app.services import benutzer as benutzerdienst

        self._neue += 1
        with SessionLocal() as db:
            person = benutzerdienst.anlegen(db, f"neu{self._neue}", "neu-geheim-123456", anzeigename="Neu")
            return person.wasneu_gesehen or ""
