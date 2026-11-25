"""nexsicherung contract tests: nexmail's adapter (copied once from the module's template, now nexmail's file).

The contract tests in ``backend/tests/nexsicherung/`` run the module against nexmail's real hooks
(``services/sicherung_haken.py``), its routes under ``/api/server/storage`` and its data. nexmail restores at once
(``restore = "now"``): ``restart`` does nothing, ``start_again`` is nexmail's start on the same data folder. Its old
routes are its own (``/api/sicherung/*``, tested in ``test_sicherung*.py``), not the module's ``legacy_router``. The
database and data folder are those of the test session (``tests/conftest.py`` empties both before every test).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from sicherung_contract import StandardAdapter

OPERATOR_NAME = "betreiber"
OPERATOR_PASSWORD = "sehr-geheim-123"
MEMBER_NAME = "mitglied"
MEMBER_PASSWORD = "auch-geheim-444"


class Adapter(StandardAdapter):
    package = "app.vendor.nexsicherung"
    prefix = "/api/server/storage"
    #: nexmail's old routes are its own, with their own shapes (``/api/sicherung``), not the module's legacy routes.
    legacy_prefix = ""
    legacy_header = ""

    def start(self) -> None:
        from app.config import get_settings

        self._clients: list[Any] = []
        folder = get_settings().data_dir / "sicherungen"
        shutil.rmtree(folder, ignore_errors=True)
        self._operator_made = False
        self._member_made = False
        self.start_again()

    def stop(self) -> None:
        for client in self._clients:
            client.__exit__(None, None, None)
        self._clients.clear()

    @property
    def password(self) -> str:
        return OPERATOR_PASSWORD

    def _client(self) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        client.__enter__()
        self._clients.append(client)
        return client

    @staticmethod
    def _sign_in(client: Any, name: str, password: str) -> None:
        answer = client.post("/api/auth/anmelden", json={"benutzername": name, "passwort": password})
        assert answer.status_code == 200, answer.text
        assert answer.json()["schritt"] == "fertig", answer.text

    def operator(self) -> Any:
        client = self._client()
        if not self._operator_made:
            answer = client.post(
                "/api/setup/konto",
                json={
                    "benutzername": OPERATOR_NAME,
                    "passwort": OPERATOR_PASSWORD,
                    "anzeigename": OPERATOR_NAME,
                    "einrichtungscode": os.environ["NEXMAIL_SETUP_TOKEN"],
                },
            )
            assert answer.status_code == 201, answer.text
            self._operator_made = True
        else:
            self._sign_in(client, OPERATOR_NAME, OPERATOR_PASSWORD)
        return client

    def member(self) -> Any:
        from app.db import SessionLocal
        from app.services import benutzer as benutzerdienst

        if not self._operator_made:
            self.operator()
        if not self._member_made:
            with SessionLocal() as db:
                benutzerdienst.anlegen(db, MEMBER_NAME, MEMBER_PASSWORD)
                db.commit()
            self._member_made = True
        client = self._client()
        self._sign_in(client, MEMBER_NAME, MEMBER_PASSWORD)
        return client

    def restart(self) -> None:
        """nexmail restores at once; nothing waits for the next start."""

    def start_again(self) -> None:
        """nexmail's start on the same data folder: the module configured, what a stopped copy left tidied away, the
        database (``main.lebenslauf`` does the same, in this order)."""
        from app.db import init_db
        from app.services import sicherung_haken
        from app.vendor import nexsicherung

        sicherung_haken.konfigurieren()
        nexsicherung.archives.tidy_at_start()
        init_db()

    def _operator_id(self) -> str:
        from app.db import SessionLocal
        from app.models import Benutzer

        if not self._operator_made:
            self.operator()
        with SessionLocal() as db:
            return db.query(Benutzer).filter_by(benutzername=OPERATOR_NAME).one().id

    def add_content(self, label: str) -> None:
        """A text template of the operator (a row nexmail keeps; nexmail keeps no files in a backup: the
        attachments come back from the mailbox)."""
        from app.db import SessionLocal
        from app.models import Textvorlage

        owner = self._operator_id()
        with SessionLocal() as db:
            db.add(Textvorlage(benutzer_id=owner, name=label, inhalt_html=f"<p>{label}</p>"))
            db.commit()

    def content(self) -> Any:
        from app.db import SessionLocal
        from app.models import Textvorlage

        with SessionLocal() as db:
            return sorted((row.name, row.inhalt_html) for row in db.query(Textvorlage).all())

    def legacy_archive(self) -> tuple[Path, Any]:
        """A restore point exactly as nexmail 0.33.0 made one (``sicherungsliste.anlegen``): ``nexmail-YYYYMMDD-HHMMSS
        .db`` with its ``.json`` beside it."""
        from app.services import sicherungsliste

        self.add_content("in the old restore point")
        held = self.content()
        made = sicherungsliste.anlegen("manuell", "made by 0.33.0")
        return sicherungsliste._ordner() / made["name"], held  # noqa: SLF001

    def settings_schedule(self) -> tuple[str, int]:
        from app.services import sicherung_haken

        answer = self.operator().get("/api/sicherung/liste")
        assert answer.status_code == 200, answer.text
        plan = answer.json()["zeitplan"]
        return sicherung_haken.TAKT_ZU_EVERY[plan["takt"]], plan["behalten"]
