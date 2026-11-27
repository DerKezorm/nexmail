"""nexgeraete contract tests: nexmail's adapter (copied once from the module's template, now nexmail's file).

The contract tests in ``backend/tests/nexgeraete/`` run the module inside nexmail: nexmail's app (``app.main``), its
browser sessions (cookie ``nexmail_sitzung``), its operators, its ``Store`` over ``sitzung art = 'geraet'``,
``app_kopplung`` and ``app_codes`` (``services/geraete_store.py``), its own device route ``GET /api/app/1/me``, the
module's routes as nexmail mounts them (``routers/geraete.py``, ``routers/app1.py``, ``routers/app_kopplung.py``).

The database is the one of the test session (``tests/conftest.py`` empties it before every test and runs ``init_db``).
The relay is a recorder and the clock moves: ``services/geraete_store.senden`` and ``.jetzt`` are replaced while a test
runs, as is the hook after pairing (``nach_kopplung``, recorded, then nexmail's own). Devices of before are written
by nexmail's own function of before (``services/sitzung.geraet_anlegen``) with the push columns as
``push.geraet_merken`` wrote them (0.34).
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from geraete_contract import LegacyDevice, Made, Relay, StandardAdapter

ROLLEN = {
    "owner": ("kim", "Kim Example", False),
    "other": ("mila", "Mila Example", False),
    "operator": ("olli", "Olli Example", True),
}


class Adapter(StandardAdapter):
    package = "app.vendor.nexgeraete"
    app_prefix = "/api/app/1"
    browser_prefix = "/api"

    def start(self) -> None:
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import anmeldebremse, geraete_store
        from app.services import benutzer as benutzerdienst

        anmeldebremse.zuruecksetzen()
        self.relay = Relay()
        self.offset = timedelta(0)
        self.paired: list[tuple[Any, str]] = []
        self.clients: dict[str, Any] = {}
        self.passwort = secrets.token_urlsafe(16)
        self.ids: dict[str, str] = {}
        with SessionLocal() as db:
            for rolle, (login, name, betreiber) in ROLLEN.items():
                person = Benutzer(
                    benutzername=login,
                    anzeigename=name,
                    passwort_hash=benutzerdienst.hashen(self.passwort),
                    ist_betreiber=betreiber,
                    kontaktadresse=f"{login}@example.com",
                    sprache="de",
                )
                db.add(person)
                db.flush()
                self.ids[rolle] = person.id
            db.commit()

        self._vorher = {
            "senden": geraete_store.senden,
            "jetzt": geraete_store.jetzt,
            "nach_kopplung": geraete_store.nach_kopplung,
        }
        eigene = self._vorher["nach_kopplung"]

        def nach_kopplung(inhaber: Any, geraet: Any) -> None:
            self.paired.append((inhaber.id, geraet.name))
            eigene(inhaber, geraet)

        geraete_store.senden = self.relay  # type: ignore[assignment]
        geraete_store.jetzt = lambda: geraete_store.utcnow() + self.offset  # type: ignore[assignment]
        geraete_store.nach_kopplung = nach_kopplung  # type: ignore[assignment]

    def stop(self) -> None:
        from app.db import engine
        from app.services import geraete_store

        for name, wert in getattr(self, "_vorher", {}).items():
            setattr(geraete_store, name, wert)
        for client in getattr(self, "clients", {}).values():
            client.close()
        engine.dispose()

    def restart(self) -> None:
        """nexmail keeps nothing of devices in memory: new clients on the same database."""
        for client in self.clients.values():
            client.close()
        self.clients = {}

    def config(self) -> Any:
        from app.services import geraete_store

        return geraete_store.KONFIGURATION

    def client(self, role: str) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        if role not in self.clients:
            # Ohne ``with``: kein Start der Hintergrundfaeden.
            klient = TestClient(app, base_url="http://testserver")
            if role != "anonymous":
                self._anmelden_als(klient, self.ids[role])
            self.clients[role] = klient
        return self.clients[role]

    def account_id(self, role: str) -> Any:
        return self.ids[role]

    def legacy_devices(self) -> list[LegacyDevice]:
        """0.34 paired by QR code and by the short code (both ``app_kopplung._einloesen`` → ``geraet_anlegen``) and by
        ``POST /api/app/1/devices`` (iCloud, also ``geraet_anlegen``); push was ``PUT /api/app/1/push`` with
        ``schluessel`` at the same row."""
        return [
            LegacyDevice("QR code"),
            LegacyDevice("iCloud sibling"),
            LegacyDevice("with push", push=True),
        ]

    def make_legacy(self, spec: LegacyDevice, *, account: str = "owner") -> Made:
        from app.db import SessionLocal
        from app.models import Benutzer, Sitzung
        from app.services import sitzung as sitzungsdienst
        from app.vendor.nexgeraete import seal

        with SessionLocal() as db:
            person = db.get(Benutzer, self.ids[account])
            token = sitzungsdienst.geraet_anlegen(db, person, spec.label, "")
            made = Made(token)
            if spec.push:
                made.private_key, oeffentlich = seal.key_pair()
                made.ticket = f"legacy-{secrets.token_urlsafe(6)}"
                zeile = db.query(Sitzung).filter_by(art="geraet", geraet=spec.label, benutzer_id=person.id).one()
                zeile.push_ticket = made.ticket
                zeile.push_schluessel = oeffentlich
                db.commit()
        return made

    def probe(self, token: str | None, headers: dict[str, str] | None = None) -> Any:
        gesendet = dict(headers or {})
        if token is not None:
            gesendet["Authorization"] = f"Bearer {token}"
        return self.device_client().get(f"{self.app_prefix}/me", headers=gesendet)

    def database_text(self) -> bytes:
        from pathlib import Path

        from app.db import engine

        with engine.connect() as verbindung:
            verbindung.exec_driver_sql("PRAGMA wal_checkpoint(FULL)")
        pfad = Path(str(engine.url.database))
        teile = [pfad.read_bytes()]
        for nebendatei in (pfad.with_name(pfad.name + "-wal"),):
            if nebendatei.exists():
                teile.append(nebendatei.read_bytes())
        return b"".join(teile)

    # --- Konten, über nexmails Kontenmodul ---------------------------------------------------------------------

    def _manage(self, aktion: str, account: str) -> None:
        from app.db import SessionLocal
        from app.services import konten_store
        from app.vendor import nexkonten

        # geraete 0.1.3 (G63): der Vertrag sperrt keinen Betreiber mehr, es handelt immer der Betreiber.
        handelnd = self.ids["operator"]
        with SessionLocal() as db:
            getattr(nexkonten.manage, aktion)(
                konten_store.store_fuer(db), self.ids[account], actor_id=handelnd, password=self.passwort
            )
        # Sperren und Löschen beenden die Browser-Sitzungen des Kontos (``shut_out``): danach meldet sich der
        # Browser neu an, wenn der Test ihn wieder braucht.
        gegangen = self.clients.pop(account, None)
        if gegangen is not None:
            gegangen.close()

    def block(self, account: str = "owner") -> None:
        self._manage("block", account)

    def unblock(self, account: str = "owner") -> None:
        self._manage("unblock", account)

    def remove(self, account: str = "owner") -> None:
        self._manage("remove", account)

    def restore(self, account: str = "owner") -> None:
        self._manage("restore", account)

    def purge(self, account: str = "owner") -> None:
        """Gelöscht, die 30 Tage um, endgültig weg (``manage.purge_due``, wie der Aufräumfaden)."""
        from app.db import SessionLocal
        from app.models import Benutzer, utcnow
        from app.services import konten_store
        from app.vendor import nexkonten

        self.remove(account)
        with SessionLocal() as db:
            db.get(Benutzer, self.ids[account]).geloescht_am = utcnow() - timedelta(
                days=nexkonten.manage.DELETE_DAYS + 1
            )
            db.commit()
            nexkonten.manage.purge_due(konten_store.store_fuer(db))

    def owe_factor(self, account: str = "owner") -> None:
        """Der Betreiber verlangt einen zweiten Faktor für alle; ``account`` hat keinen, die anderen eine App."""
        from app.db import SessionLocal, einstellung_schreiben
        from app.models import Benutzer
        from app.services import konten_store, zwei_faktor

        with SessionLocal() as db:
            for rolle, kennung in self.ids.items():
                if rolle == account:
                    continue
                person = db.get(Benutzer, kennung)
                zwei_faktor.geheimnis_speichern(person, zwei_faktor.geheimnis_erzeugen())
                person.totp_bestaetigt = True
            db.commit()
            einstellung_schreiben(db, konten_store.SCHALTER_FAKTOR_FUER_ALLE, "1")

    def switch(self, name: str, on: bool) -> None:
        """nexmail hat nur ``app`` (``app_geraete_erlaubt``, Server › Verbindungen)."""
        from app.db import SessionLocal
        from app.services import app_kopplung

        assert name == "app", name
        with SessionLocal() as db:
            app_kopplung.erlauben(db, on)

    def travel(self, delta: timedelta) -> None:
        self.offset += delta

    def tell(self, account: str, kind: str) -> None:
        from app.db import SessionLocal
        from app.services import geraete_store
        from app.vendor.nexgeraete import push

        with SessionLocal() as db:
            push.tell(
                geraete_store.store_fuer(db),
                geraete_store.KONFIGURATION,
                self.ids[account],
                kind,
                {"type": kind, "title": "Kim Example", "text": "changed something"},
                send=self.relay,
            )

    def announce(self, version: str) -> None:
        """Der Weg von ``updates.on_devices`` (``aktualisierung._neue_version``) mit der laufenden Fassung."""
        from app.services import aktualisierung

        aktualisierung._neue_version(version)

    def update_wanted(self) -> bool:
        """Was nexmail ``nexupdates`` als ``devices_want`` gibt (``geraete_store.update_gewollt``), G56."""
        from app.services import geraete_store

        return geraete_store.update_gewollt()

    def running(self) -> str:
        from app import __version__

        return __version__

    def sweep(self) -> int:
        from app.services import geraete_store

        return geraete_store.taeglich()

    def paired_mails(self) -> list[tuple[Any, str]]:
        return list(self.paired)

    @staticmethod
    def _anmelden_als(klient: Any, account_id: Any) -> None:
        """Eine bestätigte Browser-Sitzung für das Konto, als Cookie dieses Klienten (wie nach dem Anmelden)."""
        from app.db import SessionLocal
        from app.models import Sitzung, utcnow
        from app.services import sitzung as sitzungsdienst

        token = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            db.add(
                Sitzung(
                    benutzer_id=str(account_id),
                    token_hash=sitzungsdienst._hash(token),
                    bestaetigt=True,
                    art="browser",
                    gueltig_bis=utcnow() + timedelta(days=1),
                )
            )
            db.commit()
        klient.cookies.set(sitzungsdienst.COOKIE_NAME, token)
