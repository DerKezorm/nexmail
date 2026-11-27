"""nexupdates contract tests: nexmail's adapter (from ``tests-fuer-apps/adapter_template.py`` of updates 0.1.2).

nexmail keeps its switch as text under ``update_pruefen`` (``"0"`` off, ``"1"`` on, nothing stored: on), mounts the
module's routes under ``/api/about`` and keeps its old routes ``/api/ueber`` as a thin shell (tested in
``tests/test_ueber.py``, their form differs).

⚠️ **nexmail has no bell, but paired devices** (U19, since 0.35.0 geraete G18): ``on_newer`` tells the operators'
iPhones, iPads and Macs "nexmail 99.0.0 ist erschienen" (``geraete_store.neue_version``, the words of the bell), once
per version (``update_gemeldet``). ``has_bell = True``: before each look every operator has a paired device that
understands ``update``; the bell is what the relay (a recorder) got for them, unsealed.

Accounts come lazily: the setup test runs nexmail's real setup route on an empty installation, so ``start`` leaves it
empty; the first ``client("operator")`` sets up the operator over that same route without the box (as a script of
before would), the member is added to the database and signs in over the real route.
"""

from __future__ import annotations

from typing import Any

from updates_contract import StandardAdapter

KENNWORT = {"operator": "betreib-geheim-789", "member": "mitglied-geheim-456"}


class Adapter(StandardAdapter):
    package = "app.vendor.nexupdates"
    prefix = "/api/about"
    also: tuple[str, ...] = ()
    has_bell = True

    def start(self) -> None:
        """nexmail's test run (conftest) has a fresh database and data folder for every test; the module is set up as
        at the app's start, nothing is stored and nobody is set up yet."""
        from app.services import geraete_store

        self._clients: list[Any] = []
        self._rollen: dict[str, Any] = {}
        self._gesendet: list[dict[str, Any]] = []
        self._geraete: dict[str, tuple[str, str]] = {}
        self._senden = geraete_store.senden

        def aufzeichnen(_url: str, rumpf: dict[str, Any]) -> int:
            self._gesendet.append(rumpf)
            return 200

        geraete_store.senden = aufzeichnen  # type: ignore[assignment]
        self.restart()

    def stop(self) -> None:
        from app.services import geraete_store

        geraete_store.senden = self._senden  # type: ignore[assignment]
        for client in self._clients:
            client.__exit__(None, None, None)
        self._clients.clear()

    def look(self) -> None:
        """The background's look as nexmail runs it (``aktualisierung.im_hintergrund``), after giving every operator a
        paired device that understands ``update``."""
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import aktualisierung, geraete_store
        from app.vendor.nexgeraete import VIA_QR, PushState, devices, seal

        with SessionLocal() as db:
            store = geraete_store.store_fuer(db)
            for person in db.query(Benutzer).filter_by(ist_betreiber=True):
                if person.id in self._geraete:
                    continue
                inhaber = store.holder(person.id)
                geraet, _ = devices.add(store, geraete_store.KONFIGURATION, inhaber, name="Probe", kind="ios", via=VIA_QR)
                privat, oeffentlich = seal.key_pair()
                ticket = f"betreiber-{person.id}"
                store.set_push(geraet.id, PushState(ticket, oeffentlich, ("update",)))
                self._geraete[person.id] = (ticket, privat)
            db.commit()
        aktualisierung.im_hintergrund()

    def _gehoert(self) -> list[tuple[str, str, str]]:
        """(language of the operator's account, version as the tag, title) of every notice, oldest first."""
        import json

        from app.db import SessionLocal
        from app.services import geraete_store
        from app.vendor.nexgeraete import seal

        raus = []
        with SessionLocal() as db:
            store = geraete_store.store_fuer(db)
            for rumpf in self._gesendet:
                for konto, (ticket, privat) in self._geraete.items():
                    if rumpf.get("ticket") != ticket:
                        continue
                    nachricht = json.loads(seal.unseal(rumpf["enc"], privat, geraete_store.KONFIGURATION.push_info))
                    inhaber = store.holder(konto)
                    raus.append((inhaber.language if inhaber else "en", f"v{nachricht['version']}", nachricht["title"]))
        return raus

    def bell(self) -> list[str]:
        """What one operator's devices were told about (the first operator)."""
        erster = next(iter(self._geraete.values()), None)
        if erster is None:
            return []
        return [f"v{n}" for n in self._versionen(erster)]

    def _versionen(self, geraet: tuple[str, str]) -> list[str]:
        import json

        from app.services import geraete_store
        from app.vendor.nexgeraete import seal

        ticket, privat = geraet
        return [
            json.loads(seal.unseal(r["enc"], privat, geraete_store.KONFIGURATION.push_info))["version"]
            for r in self._gesendet
            if r.get("ticket") == ticket
        ]

    def bell_notices(self) -> list[tuple[str, str, str]]:
        return self._gehoert()

    def restart(self) -> None:
        from app.services import aktualisierung

        aktualisierung.konfigurieren()

    def _neu(self) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        client.__enter__()
        self._clients.append(client)
        return client

    def _einrichten(self, client: Any, **mehr: Any) -> None:
        import os

        antwort = client.post(
            "/api/setup/konto",
            json={
                "benutzername": "betreiber",
                "passwort": KENNWORT["operator"],
                "anzeigename": "Betreiber",
                "einrichtungscode": os.environ["NEXMAIL_SETUP_TOKEN"],
                **mehr,
            },
        )
        assert antwort.status_code == 201, antwort.text

    def client(self, role: str) -> Any:
        if role == "anonymous":
            return self._neu()
        if role in self._rollen:
            return self._rollen[role]
        from app.db import SessionLocal, hat_benutzer

        with SessionLocal() as db:
            leer = not hat_benutzer(db)
        if leer:
            # Without the box, as a script of before: the switch stays unstored.
            self._einrichten(self._neu())
        if role == "operator":
            client = self._neu()
            self._anmelden(client, "betreiber", KENNWORT["operator"])
        else:
            from app.models import Benutzer
            from app.services import benutzer as benutzerdienst

            with SessionLocal() as db:
                if db.query(Benutzer).filter_by(benutzername="mitglied").first() is None:
                    db.add(
                        Benutzer(
                            benutzername="mitglied",
                            anzeigename="Mitglied",
                            passwort_hash=benutzerdienst.hashen(KENNWORT["member"]),
                            ist_betreiber=False,
                        )
                    )
                    db.commit()
            client = self._neu()
            self._anmelden(client, "mitglied", KENNWORT["member"])
        self._rollen[role] = client
        return client

    @staticmethod
    def _anmelden(client: Any, name: str, passwort: str) -> None:
        antwort = client.post("/api/auth/anmelden", json={"benutzername": name, "passwort": passwort})
        assert antwort.status_code == 200, antwort.text

    def stored_switch(self) -> Any:
        from app.db import SessionLocal
        from app.models import Einstellung

        with SessionLocal() as db:
            zeile = db.get(Einstellung, "update_pruefen")
            return None if zeile is None else zeile.wert

    def store_legacy_switch(self, on: bool) -> None:
        """As 0.33.0 wrote it (``routers/ueber.py``): ``"1"`` or ``"0"``."""
        from app.db import SessionLocal, einstellung_schreiben

        with SessionLocal() as db:
            einstellung_schreiben(db, "update_pruefen", "1" if on else "0")

    def setup(self, on: bool) -> None:
        """nexmail's real setup route with the box (``update_check``)."""
        self._einrichten(self._neu(), update_check=on)

    def description(self) -> dict[str, Any]:
        """nexmail publishes no description (``openapi_url=None``); the contract tests get the app's own."""
        from app.main import app

        return app.openapi()
