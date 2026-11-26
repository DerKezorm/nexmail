"""nexmcp contract tests: nexmail's adapter (from ``tests-fuer-apps/adapter_template.py`` of mcp 1.1.1).

nexmail is new to MCP (decision 1): no older keys, no connected programs, MCP was never on, so ``legacy_keys`` and
``legacy_program`` stay empty and ``start_older`` is a fresh start (the older version had nothing of MCP to leave).
The operator can take AI from an account ("KI erlaubt"), so ``has_ai``.

⚠️ **Mailboxes are required on an MCP key made by hand** (plan: "Bereiche = Postfächer (Pflicht wie heute)",
``KeyKind.areas_required``), while the contract's ``mcp_key`` sends none. The clients here add the account's mailboxes
to a new MCP key that names none, the way nexmail's page makes one (TODO mcp 1.1.1, open since 1.1.0, see ``einst-fragen``). Every other
request goes to the real routes unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp_contract import LegacyKey, LegacyProgram, StandardAdapter

KENNWORT = {"owner": "eigen-geheim-123", "other": "anders-geheim-456", "operator": "betreib-geheim-789"}


def _klient_klasse():
    from fastapi.testclient import TestClient

    class Klient(TestClient):
        """nexmail's browser for one account: a new MCP key gets the account's mailboxes when it names none."""

        postfaecher: list[str] = []

        def post(self, url: Any, *args: Any, **kwargs: Any) -> Any:
            body = kwargs.get("json")
            if (
                str(url).endswith("/api/connections/keys")
                and isinstance(body, dict)
                and body.get("kind") == "mcp"
                and "areas" not in body
            ):
                kwargs["json"] = {**body, "areas": list(self.postfaecher)}
            return super().post(url, *args, **kwargs)

    return Klient


class Adapter(StandardAdapter):
    package = "app.vendor.nexmcp"
    keys_prefix = "/api/connections"
    prefix = "/api/connections/mcp"
    has_ai = True
    older_had_mcp_on = False

    def start(self) -> None:
        """Three accounts over nexmail's tables (operator, owner, other), each with a mailbox, an inbox and a message;
        the owner with a task. nexmail's test run (conftest) has a fresh database for every test."""
        from app.db import SessionLocal
        from app.models import Aufgabe, Benutzer, Konto, Nachricht, Ordner
        from app.services import benutzer as benutzerdienst

        self.ids: dict[str, str] = {}
        self.postfach: dict[str, str] = {}
        self.mail: dict[str, int] = {}
        self._clients: list[Any] = []
        self._angemeldet: dict[str, Any] = {}
        # MCP 14: jeder Ruf von ``notify`` (``mcp_hinweis.melden``), mitgehört und weitergegeben.
        from app.services import mcp_hinweis

        self._gemeldet: list[tuple[str, Any]] = []
        self._melden = mcp_hinweis.melden

        def melden(ereignis: str, anfrage: Any) -> None:
            self._gemeldet.append((ereignis, anfrage.id))
            self._melden(ereignis, anfrage)

        mcp_hinweis.melden = melden
        with SessionLocal() as db:
            for rolle in ("operator", "owner", "other"):
                person = Benutzer(
                    benutzername=rolle,
                    anzeigename=rolle.title(),
                    passwort_hash=benutzerdienst.hashen(KENNWORT[rolle]),
                    ist_betreiber=rolle == "operator",
                )
                db.add(person)
                db.flush()
                konto = Konto(
                    benutzer_id=person.id,
                    anzeigename=f"Post {rolle}",
                    adresse=f"{rolle}@example.com",
                    imap_server="imap.example.com",
                    imap_benutzer=rolle,
                    smtp_server="smtp.example.com",
                    smtp_benutzer=rolle,
                )
                db.add(konto)
                db.flush()
                ordner = Ordner(konto_id=konto.id, pfad="INBOX", name="INBOX", rolle="posteingang")
                db.add(ordner)
                db.flush()
                mail = Nachricht(
                    benutzer_id=person.id,
                    konto_id=konto.id,
                    ordner_id=ordner.id,
                    uid=1,
                    betreff=f"Einkaufsliste von {rolle}",
                    von_name="Absender",
                    von_adresse="absender@example.com",
                    datum=datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc),
                    koerper_text="Milch",
                )
                db.add(mail)
                db.flush()
                self.ids[rolle] = person.id
                self.postfach[rolle] = konto.id
                self.mail[rolle] = mail.id
            owner_mail = db.get(Nachricht, self.mail["owner"])
            aufgabe = Aufgabe(
                benutzer_id=self.ids["owner"],
                konto_id=self.postfach["owner"],
                nachricht_id=owner_mail.id,
                betreff=owner_mail.betreff,
            )
            db.add(aufgabe)
            db.commit()
            self.aufgabe = aufgabe.id
        for rolle in ("operator", "owner", "other"):
            self.client(rolle)

    def start_older(self) -> None:
        """nexmail before the module had no MCP at all: its database holds nothing MCP could keep."""
        self.start()

    def stop(self) -> None:
        from app.services import mcp_hinweis

        mcp_hinweis.melden = self._melden
        for client in self._clients:
            client.__exit__(None, None, None)

    def client(self, role: str) -> Any:
        """A confirmed browser session over nexmail's real sign-in (``/api/auth/anmelden``), once per role."""
        from app.main import app

        if role in self._angemeldet:
            return self._angemeldet[role]
        client = _klient_klasse()(app)
        client.__enter__()
        self._clients.append(client)
        if role == "anonymous":
            return client
        client.postfaecher = [self.postfach[role]]
        answer = client.post("/api/auth/anmelden", json={"benutzername": role, "passwort": KENNWORT[role]})
        assert answer.status_code == 200, answer.text
        self._angemeldet[role] = client
        return client

    def config(self) -> Any:
        from app.services.mcp_werkzeuge import MCP

        return MCP

    def keys_config(self) -> Any:
        from app.services.schluessel_store import KONFIGURATION

        return KONFIGURATION

    def change_arguments(self, request_id: Any, arguments: str) -> None:
        from sqlalchemy import text

        from app.db import engine

        with engine.begin() as verbindung:
            verbindung.execute(text("UPDATE mcp_anfrage SET argumente = :a WHERE id = :i"), {"a": arguments, "i": request_id})

    def notified(self) -> list[tuple[str, Any]]:
        return list(self._gemeldet)

    def read_call(self) -> tuple[str, dict[str, Any]]:
        return "search_messages", {"subject": "Einkaufsliste", "limit": 5}

    def change_call(self) -> tuple[str, dict[str, Any]]:
        return "complete_task", {"task_id": self.aufgabe}

    def foreign_call(self) -> tuple[str, dict[str, Any]]:
        return "search_messages", {"mailbox_id": self.postfach["other"]}

    def legacy_keys(self) -> list[LegacyKey]:
        return []

    def legacy_program(self) -> LegacyProgram | None:
        return None

    def _ki(self, account: str, an: bool) -> None:
        from app.db import SessionLocal
        from app.models import Benutzer

        with SessionLocal() as db:
            db.get(Benutzer, self.ids[account]).ki_erlaubt = an
            db.commit()

    def take_ai(self, account: str = "owner") -> None:
        self._ki(account, False)

    def give_ai(self, account: str = "owner") -> None:
        self._ki(account, True)


__all__ = ["Adapter", "LegacyKey", "LegacyProgram"]
