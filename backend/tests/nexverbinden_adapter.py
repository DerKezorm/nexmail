"""nexverbinden contract tests: nexmail's adapter (from ``tests-fuer-apps/adapter_template.py`` of verbinden 0.1.4, since 0.1.8 with ``shown_names``).

nexmail is only a guest (catalog: it grants nothing), so ``probe`` is ``None``. Its partner in the tests is nextasks,
the pair nexmail had before the module: the older version kept a connection typed in by hand
(``aufgabenverbindung``, art ``nextasks``, address plus key) and an API key of the owner.
"""

from __future__ import annotations


from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from verbinden_contract import StandardAdapter

KENNWORT = {"owner": "eigen-geheim-123", "other": "anders-geheim-456", "operator": "betreib-geheim-789"}
#: Die Namen, die die Partner-App der Tests von den Konten erwartet (``verbinden_partner.ROLES``).
NAME = {"owner": "kim", "other": "sam", "operator": "op"}


class Adapter(StandardAdapter):
    package = "app.vendor.nexverbinden"
    partner = "nextasks"
    base = "https://mail.example.com"
    older_link = True
    #: verbinden 0.1.8 (B1): die Anzeigenamen der Testkonten (``anzeigename`` unten), die ``account_card`` nennt.
    shown_names = {rolle: NAME[rolle].title() for rolle in ("owner", "other")}  # noqa: RUF012 (nur gelesen)

    def start(self, folder: Path, *, older: bool = False) -> None:
        from app import crypto
        from app.db import SessionLocal, einstellung_schreiben
        from app.models import Aufgabenverbindung, Benutzer, Konto
        from app.services import apischluessel as apidienst
        from app.services import benutzer as benutzerdienst
        from app.services import nextasks
        from app.services.verbinden_store import store_fuer

        self.ids: dict[str, str] = {}
        self._clients: dict[str, TestClient] = {}
        with SessionLocal() as db:
            for rolle in ("operator", "owner", "other"):
                person = Benutzer(
                    benutzername=NAME[rolle],
                    anzeigename=NAME[rolle].title(),
                    passwort_hash=benutzerdienst.hashen(KENNWORT[rolle]),
                    ist_betreiber=rolle == "operator",
                )
                db.add(person)
                db.flush()
                self.ids[rolle] = person.id
            db.commit()
            if older:
                owner = db.get(Benutzer, self.ids["owner"])
                konto = Konto(
                    benutzer_id=owner.id, anzeigename="Post", adresse="owner@example.com", imap_server="imap.example.com",
                    imap_benutzer="o", smtp_server="smtp.example.com", smtp_benutzer="o",
                )  # fmt: skip
                db.add(konto)
                db.flush()
                einstellung_schreiben(db, apidienst.SCHALTER, "1")
                _zeile, self.older_key = apidienst.anlegen(db, owner, "Dashboard", "anzahl", [konto.id])
                self.older_key_path = "/api/v1/me"
                v = Aufgabenverbindung(benutzer_id=owner.id, art="nextasks", name="nextasks")
                db.add(v)
                db.flush()
                zugang = nextasks.Zugang(url="https://nextasks.example.com", token="ntk_AbCdEfGh" + "x" * 30)
                v.zugang = crypto.verschluesseln(nextasks.zugang_schreiben(zugang), f"aufgabenverbindung:{v.id}:zugang")
                db.commit()
        self._sitzung = SessionLocal()
        self.store = store_fuer(self._sitzung)
        # verbinden 0.1.4: jeder Ruf von ``on_disconnected``, mitgehört und weitergegeben.
        from app.services import verbinden_store

        self._getrennt: list[tuple[Any, str]] = []
        self._ueber_getrennt = verbinden_store.ueber_getrennt

        def ueber_getrennt(partner: str, store: Any, konto_id: Any) -> None:
            self._getrennt.append((konto_id, partner))
            self._ueber_getrennt(partner, store, konto_id)

        verbinden_store.ueber_getrennt = ueber_getrennt

    def disconnected(self) -> list[tuple[Any, str]]:
        return list(self._getrennt)

    def stop(self) -> None:
        from app.services import verbinden_store

        verbinden_store.ueber_getrennt = self._ueber_getrennt
        for client in self._clients.values():
            client.__exit__(None, None, None)
        self._sitzung.close()

    def asgi(self) -> Any:
        from app.main import app

        return app

    def client(self, role: str | None) -> TestClient:
        from app.main import app

        key = role or "anonymous"
        if key in self._clients:
            return self._clients[key]
        client = TestClient(app, base_url=self.base)
        client.__enter__()
        if role is not None:
            answer = client.post("/api/auth/anmelden", json={"benutzername": NAME[role], "passwort": KENNWORT[role]})
            assert answer.status_code == 200, answer.text
        self._clients[key] = client
        return client

    def config(self) -> Any:
        from app.services.verbinden_store import CONFIG

        return CONFIG

    def account_id(self, role: str) -> Any:
        return self.ids[role]

    def block(self, role: str, blocked: bool = True) -> None:
        from datetime import UTC, datetime

        from app.db import SessionLocal
        from app.models import Benutzer

        with SessionLocal() as db:
            db.get(Benutzer, self.ids[role]).gesperrt_seit = datetime.now(UTC) if blocked else None
            db.commit()
        self._sitzung.expire_all()

    def probe(self, purpose: str) -> str | None:
        return None

    def areas_seen(self, purpose: str, answer: Any) -> set[str]:
        return set()

    def everything(self) -> str:
        from app.db import engine

        roh = engine.raw_connection()
        try:
            return "\n".join(roh.driver_connection.iterdump())
        finally:
            roh.close()

    def own_tables(self) -> dict[str, Any]:
        from app.db import engine

        roh = engine.raw_connection()
        try:
            return {
                name: [tuple(z) for z in roh.driver_connection.execute(f"SELECT * FROM {name} ORDER BY 1")]  # noqa: S608
                for name in ("aufgabenverbindung", "api_schluessel", "nextime_verbindung")
            }
        finally:
            roh.close()
