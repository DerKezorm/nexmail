"""nexlog contract tests: nexmail's adapter (copied once from the module's template, now nexmail's file).

The contract tests in ``backend/tests/nexlog/`` run the module inside nexmail: its start (``main.lebenslauf``:
``protokoll.einrichten``, the level stored under ``protokoll_stufe`` and ``protokoll_stufe_bis`` with German names),
its middleware (request numbers of eight characters in ``x-nexmail-vorgang``, who acts from ``deps``), its check of
operators (``nur_betreiber``) and the module's routes under ``/api/logs``. The database and data folder are those of the
test session (``tests/conftest.py`` empties the database before every test).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from log_contract import LegacyLine, Secret, StandardAdapter

OPERATOR_NAME = "betreiber"
OPERATOR_PASSWORD = "sehr-geheim-123"
MEMBER_NAME = "mitglied"
MEMBER_PASSWORD = "auch-geheim-444"


class Adapter(StandardAdapter):
    package = "app.vendor.nexlog"
    prefix = "/api/logs"
    request_id_header = "x-nexmail-vorgang"
    #: Behind the sign-in, so the line names who asked.
    probe_path = "/api/auth/ich"

    def start(self) -> None:
        """nexmail started as in production: its lifespan (``protokoll.einrichten``, the stored level)."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services import protokoll

        self._clients: list[Any] = []
        # A fresh log folder, as on a new server: the session's own log holds the lines of every test before.
        self._folder = Path(tempfile.mkdtemp(prefix="nexmail-log-"))
        protokoll.ORDNER = self._folder
        self._main = TestClient(app)
        self._main.__enter__()
        self._operator: Any = None

    def stop(self) -> None:
        from app.services import protokoll

        for client in self._clients:
            client.__exit__(None, None, None)
        self._main.__exit__(None, None, None)
        protokoll.ORDNER = None
        protokoll.einrichten()
        shutil.rmtree(self._folder, ignore_errors=True)

    def client(self, role: str) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        client.__enter__()
        self._clients.append(client)
        if role == "operator":
            if self._operator is None:
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
                self._operator = True
            else:
                self._sign_in(client, OPERATOR_NAME, OPERATOR_PASSWORD)
        elif role == "member":
            from app.db import SessionLocal
            from app.services import benutzer as benutzerdienst

            if self._operator is None:
                # The first account is the operator: set one up in a client of its own.
                self.client("operator")
            with SessionLocal() as db:
                benutzerdienst.anlegen(db, MEMBER_NAME, MEMBER_PASSWORD)
                db.commit()
            self._sign_in(client, MEMBER_NAME, MEMBER_PASSWORD)
        return client

    @staticmethod
    def _sign_in(client: Any, name: str, password: str) -> None:
        answer = client.post("/api/auth/anmelden", json={"benutzername": name, "passwort": password})
        assert answer.status_code == 200, answer.text
        assert answer.json()["schritt"] == "fertig", answer.text

    def operator_name(self) -> str:
        return OPERATOR_NAME

    def stored(self) -> tuple[Any, Any]:
        from app.db import SessionLocal, einstellung_lesen

        with SessionLocal() as db:
            return einstellung_lesen(db, "protokoll_stufe"), einstellung_lesen(db, "protokoll_stufe_bis")

    def store_legacy(self, deep: bool, minutes_from_now: int) -> None:
        """As nexmail 0.33.0 stored it (``protokoll.stufe_setzen``): German names, the end as ISO text in UTC or
        ``""``."""
        from app.db import SessionLocal, einstellung_schreiben

        with SessionLocal() as db:
            if deep:
                until = datetime.now(UTC) + timedelta(minutes=minutes_from_now)
                einstellung_schreiben(db, "protokoll_stufe", "ausfuehrlich")
                einstellung_schreiben(db, "protokoll_stufe_bis", until.isoformat())
            else:
                einstellung_schreiben(db, "protokoll_stufe", "leise")
                einstellung_schreiben(db, "protokoll_stufe_bis", "")

    @contextmanager
    def environment(self, value: str) -> Iterator[None]:
        from app.config import get_settings

        settings = get_settings()
        before = settings.log_stufe
        settings.log_stufe = value
        try:
            yield
        finally:
            settings.log_stufe = before

    def legacy_lines(self) -> list[LegacyLine]:
        """Lines in the form nexmail 0.33.0 wrote them (``services/protokoll.py`` before the module), in UTC."""
        return [
            LegacyLine(
                raw="2026-11-20 08:15:02 INFO     nexmail.abgleich [0a1b2c3d] | Folder INBOX synced in 312 ms.",
                level="INFO",
                logger="nexmail.abgleich",
                message="Folder INBOX synced in 312 ms.",
                request_id="0a1b2c3d",
                at="2026-11-20T08:15:02+00:00",
            ),
            LegacyLine(
                raw="2026-11-20 08:15:03 WARNING  nexmail.auth [4e5f6a7b u:kim] | Sign-in refused.",
                level="WARNING",
                logger="nexmail.auth",
                message="Sign-in refused.",
                request_id="4e5f6a7b",
                user="kim",
                at="2026-11-20T08:15:03+00:00",
            ),
            LegacyLine(
                raw="2026-11-20 08:15:04 INFO     nexmail.main [-] | nexmail 0.33.0 is ready.",
                level="INFO",
                logger="nexmail.main",
                message="nexmail 0.33.0 is ready.",
                at="2026-11-20T08:15:04+00:00",
            ),
        ]

    def secrets(self) -> list[Secret]:
        made = os.urandom(9).hex()
        return [
            *(
                Secret(f"Key used {prefix}{made}", hidden=made, kept=[f"{prefix}…"])
                for prefix in ("nxm_", "nxa_")
            ),
            Secret(f"GET /einladung/{made}x -> 200", hidden=made, kept=["/einladung/…"]),
            # nexmail's own rule takes the word "kennwort" and what follows it, so here even the module's "…" goes.
            Secret(f"GET /kennwort/{made}x -> 200", hidden=made, kept=["GET /kennwort/"]),
            Secret(f"GET /adresse/{made}x -> 200", hidden=made, kept=["/adresse/…"]),
            Secret(f"GET /api/auth/kennwort-neu/{made}x -> 200", hidden=made, kept=["GET /api/auth/kennwort-"]),
            Secret(f"IMAP LOGIN kim {made}", hidden=made, kept=["LOGIN kim ***"]),
            Secret(f"Kennwort {made} abgelehnt", hidden=made),
        ]
