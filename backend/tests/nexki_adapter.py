"""nexki contract tests: nexmail's adapter (from ``tests-fuer-apps/adapter_template.py`` of ki 0.1.2).

nexmail before the module: each account its own AI service (``Benutzer.ki_url``/``ki_modell``/``ki_schluessel``
sealed with ``benutzer:<id>:ki``, ``ki_aktiv``), the operator's main switch ``einstellung.ki_erlaubt``, "KI erlaubt"
per account ``Benutzer.ki_erlaubt``; so its older form is ``own``. The module's routes are mounted under
``/api/server/ai`` and ``/api/me/ai``.

⚠️ **The button tasks run through nexmail's own route** ``POST /api/ki/text`` (the editor's "Rechtschreibung"), which
keeps its German codes as text in ``detail`` and status 400 (E55); ``old_codes`` names them for every code of the
module (``kidienst.ALTE_KENNUNGEN``, a code without an older one stays the module's). nexmail has **no automatic task**
(``has_automatic = False``). The network rules themselves are not bent: every request goes through ``nexki.ask``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from ki_contract import StandardAdapter

KENNWORT = {"owner": "eigen-geheim-123", "other": "anders-geheim-456", "operator": "betreib-geheim-789"}


class Adapter(StandardAdapter):
    package = "app.vendor.nexki"
    server_prefix = "/api/server/ai"
    me_prefix = "/api/me/ai"
    older_forms = ("own",)
    has_automatic = False
    _zuletzt: Any = None

    @property
    def old_codes(self) -> dict[str, tuple[int, str]]:  # type: ignore[override]
        """The codes of before at nexmail's old routes (``kidienst.ALTE_KENNUNGEN``, status 400). ``ai_service_failed``
        had two there: ``ki_dienst_sagt`` (the service said something) and ``ki_dienst_antwortet_nicht``; the one the
        last answer of the route carried counts (``old_codes`` names one per code; see ``einst-fragen`` Nr. 17). A
        code that did not exist before comes with the module's status (``kidienst.als_antwort``)."""
        from app.services import kidienst

        alte = {code: (400, alt) for code, alt in kidienst.ALTE_KENNUNGEN.items()}
        dienst = self._zuletzt if self._zuletzt in ("ki_dienst_sagt", "ki_dienst_antwortet_nicht") else "ki_dienst_antwortet_nicht"
        alte["ai_service_failed"] = (400, dienst)
        return alte

    def _konten(self) -> None:
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import benutzer as benutzerdienst

        self.ids: dict[str, str] = {}
        self._clients: list[Any] = []
        self._angemeldet: dict[str, Any] = {}
        with SessionLocal() as db:
            for rolle in ("operator", "owner", "other"):
                person = Benutzer(
                    benutzername=rolle,
                    anzeigename=rolle.title(),
                    passwort_hash=benutzerdienst.hashen(KENNWORT[rolle]),
                    ist_betreiber=rolle == "operator",
                    # „KI für mich“ steht in nexmail ab Werk aus (ki_aktiv); die Vertragstests beginnen dort, wo die
                    # Person sie eingeschaltet hat (ihr eigener Schalter wird eigens geprüft).
                    ki_aktiv=True,
                )
                db.add(person)
                db.flush()
                self.ids[rolle] = person.id
            db.commit()

    def _starten(self) -> None:
        """As at the app's start (``main.lebenslauf``): ``ki_store.uebernehmen`` on what the database holds."""
        from app.db import SessionLocal
        from app.services import ki_store

        with SessionLocal() as db:
            ki_store.uebernehmen(db)

    def start(self) -> None:
        """A fresh installation: the app starts on an empty database, the accounts come afterwards."""
        self._starten()
        self._konten()

    def start_older(self, form: str, base: str, key: str) -> None:
        """As nexmail 0.33.0 wrote it: the owner's own service, sealed the old way, switched on, the operator's
        main switch open."""
        from app import crypto
        from app.db import SessionLocal, einstellung_schreiben
        from app.models import Benutzer

        assert form in ("own", "own_unset")
        self._konten()
        with SessionLocal() as db:
            person = db.get(Benutzer, self.ids["owner"])
            if form == "own":
                person.ki_url, person.ki_modell = base, "plain"
                person.ki_schluessel = crypto.verschluesseln(key, f"benutzer:{person.id}:ki")
                person.ki_aktiv = True
            einstellung_schreiben(db, "ki_erlaubt", "1")
            db.commit()
        self._starten()

    def stop(self) -> None:
        for client in self._clients:
            client.__exit__(None, None, None)

    def client(self, role: str) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        if role in self._angemeldet:
            return self._angemeldet[role]
        client = TestClient(app)
        client.__enter__()
        self._clients.append(client)
        if role == "anonymous":
            return client
        answer = client.post("/api/auth/anmelden", json={"benutzername": role, "passwort": KENNWORT[role]})
        assert answer.status_code == 200, answer.text
        self._angemeldet[role] = client
        return client

    def config(self) -> Any:
        from app.services import ki_store

        return ki_store.CONFIG

    def store(self) -> Any:
        from app.db import SessionLocal
        from app.services import ki_store

        self._sitzung = SessionLocal()
        return ki_store.store_fuer(self._sitzung)

    def account_id(self, role: str) -> Any:
        return self.ids[role]

    @staticmethod
    def _antwort(ausfuehren: Any) -> httpx.Response:
        """The app's function answered as its old routes answer (``kidienst.als_antwort``: code as text in ``detail``,
        400 for a code of before, the module's status for a new one)."""
        from app.services import kidienst

        try:
            text = ausfuehren()
        except kidienst.KiFehler as fehler:
            antwort = kidienst.als_antwort(fehler)
            return httpx.Response(antwort.status_code, json={"detail": antwort.detail, "werte": antwort.werte},
                                  headers=antwort.headers or {})
        return httpx.Response(200, json={"text": text})

    def manual(self, role: str, text: str) -> Any:
        """nexmail's real route of the editor's button (E55: its codes as text, status 400)."""
        antwort = self.client(role).post("/api/ki/text", json={"text": f"<p>{text}</p>", "auftrag": "rechtschreibung"})
        daten = antwort.json() if antwort.headers.get("content-type", "").startswith("application/json") else {}
        self._zuletzt = daten.get("detail") if isinstance(daten, dict) else None
        return antwort

    def app_refused(self, role: str, text: str) -> Any:
        """nexmail's own check: received mail goes to the AI only with the person's tick for it (the operator's
        switch for received mail open)."""
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import kidienst

        def ausfuehren() -> str:
            with SessionLocal() as db:
                kidienst.fremde_post_erlauben(db, True)
                person = db.get(Benutzer, self.ids[role])
                person.ki_fremde_post = False
                db.commit()
                gefasst, _ = kidienst.zusammenfassen(
                    person, db, absender="Kim <kim@example.com>", betreff="Probe", text=f"{text} " * 3, sprache="en"
                )
                return gefasst

        return self._antwort(ausfuehren)

    def _setzen(self, role: str, **werte: Any) -> None:
        from app.db import SessionLocal
        from app.models import Benutzer

        with SessionLocal() as db:
            person = db.get(Benutzer, self.ids[role])
            for name, wert in werte.items():
                setattr(person, name, wert)
            db.commit()

    def take_ai(self, role: str) -> None:
        self._setzen(role, ki_erlaubt=False)

    def give_ai(self, role: str) -> None:
        self._setzen(role, ki_erlaubt=True)

    def shut_out(self, role: str) -> None:
        self._setzen(role, gesperrt_seit=datetime.now(UTC))

    def let_in(self, role: str) -> None:
        self._setzen(role, gesperrt_seit=None)

    def dump(self) -> str:
        from app.db import engine

        roh = engine.raw_connection()
        try:
            return "\n".join(roh.driver_connection.iterdump())
        finally:
            roh.close()


__all__ = ["Adapter"]
