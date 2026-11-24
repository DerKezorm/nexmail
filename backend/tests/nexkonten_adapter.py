"""nexkonten contract tests: nexmail's adapter (copied once from the module's template, now nexmail's file).

The contract tests in ``backend/tests/nexkonten/`` run the module's flows against nexmail's real ``Store``
(``app.services.konten_store``) over nexmail's real tables, and sign in through nexmail's own route
``POST /api/auth/anmelden`` with its field names (``benutzername``, ``passwort``).

The database is the one of the test session (``tests/conftest.py`` empties it before every test and runs
``init_db``). ``legacy()`` loads the database that 0.33.0 itself built (``tests/bestand``).

⚠️ **What nexmail does not have is skipped, not faked:** nexmail blocks no accounts (an account is there or removed)
and requires no second factor of anybody. A contract test that seeds such an account is skipped with that reason;
``lock_after`` is None because the brake against guessing lives in memory (``services/anmeldebremse``), not at the
account.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from konten_contract import Legacy, StandardAdapter, png

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER / "bestand"))


class Adapter(StandardAdapter):
    package = "app.vendor.nexkonten"
    lock_after: int | None = None

    def start(self) -> None:
        from app.services import anmeldebremse, konten_store

        konten_store.einrichten()
        anmeldebremse.zuruecksetzen()

    def stop(self) -> None:
        from app.db import engine

        engine.dispose()

    @contextmanager
    def store(self) -> Iterator[Any]:
        from app.db import SessionLocal
        from app.services.konten_store import KontenStore

        with SessionLocal() as db:
            yield KontenStore(db)

    def seed(
        self,
        username: str,
        *,
        display_name: str = "",
        email: str = "",
        email_confirmed: bool = True,
        email_proven: bool = False,
        email_source: str = "",
        password: str | None = None,
        operator: bool = False,
        blocked: bool = False,
        picture: bool = False,
        second_factor: str = "none",
    ) -> Any:
        if blocked:
            pytest.skip("nexmail blocks no accounts (an account is there or removed)")
        if second_factor == "required":
            pytest.skip("nexmail requires no second factor of anybody")
        from app.db import SessionLocal
        from app.models import Benutzer, utcnow
        from app.services import benutzer as benutzerdienst

        with SessionLocal() as db:
            person = Benutzer(
                benutzername=username,
                anzeigename=display_name,
                passwort_hash=benutzerdienst.hashen(password) if password else "",
                ist_betreiber=operator,
                kontaktadresse=email,
                kontaktadresse_zaehlt=email_confirmed,
                kontaktadresse_bewiesen=email_proven,
                kontaktadresse_herkunft=email_source,
                profilbild=png() if picture else None,
                profilbild_am=utcnow() if picture else None,
                totp_bestaetigt=second_factor == "active",
            )
            db.add(person)
            db.commit()
            return person.id

    def make_invite(
        self,
        *,
        email: str = "",
        display_name: str = "",
        username: str = "",
        expired: bool = False,
        reusable: bool = False,
    ) -> str:
        """As ``POST /api/benutzer/einladungen`` makes it (``services/einladung.aussprechen``); ``username`` only
        for an invitation of 0.33.0, which fixed one. nexmail has no reusable invitations."""
        if reusable:
            pytest.skip("nexmail has no invitations several people may follow")
        from app.db import SessionLocal
        from app.services import einladung as einladungsdienst

        ende = datetime.now(timezone.utc) + (timedelta(minutes=-5) if expired else timedelta(days=7))
        with SessionLocal() as db:
            einladung, schluessel = einladungsdienst.aussprechen(
                db, adresse=email, anzeigename=display_name, laeuft_ab=ende
            )
            if username:
                einladung.benutzername = username
                db.commit()
        return schluessel

    def open_session(self, account_id: Any, kind: str = "browser") -> Any:
        """``browser`` a signed-in browser, ``waiting`` a browser waiting for the code of its second factor (also
        ``art = browser``, not confirmed), ``device`` the paired iPhone app. nexmail keeps no mark of a known
        browser: it has no lock at the account that such a mark would get past."""
        if kind == "known_browser":
            pytest.skip("nexmail has no lock at the account, so no mark of a known browser")
        from app.db import SessionLocal
        from app.models import Sitzung, utcnow

        with SessionLocal() as db:
            sitzung = Sitzung(
                benutzer_id=str(account_id),
                token_hash=f"probe-{kind}-{datetime.now(timezone.utc).timestamp()}-{account_id}",
                bestaetigt=kind != "waiting",
                art="geraet" if kind == "device" else "browser",
                geraet="Probe",
                gueltig_bis=utcnow() + timedelta(days=30),
            )
            db.add(sitzung)
            db.commit()
            return sitzung.id

    def session_alive(self, handle: Any) -> bool:
        from app.db import SessionLocal
        from app.models import Sitzung

        with SessionLocal() as db:
            return db.get(Sitzung, handle) is not None

    def delete_account(self, account_id: Any) -> None:
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import benutzer as benutzerdienst

        with SessionLocal() as db:
            benutzerdienst.entfernen(db, db.get(Benutzer, str(account_id)))

    def raw_text(self) -> str:
        from sqlalchemy import text

        from app.db import engine

        teile: list[str] = []
        with engine.connect() as verbindung:
            for tabelle in ("benutzer", "einladung", "ruecksetzung", "adresswechsel", "frueherer_name", "sitzung"):
                teile += [repr(tuple(zeile)) for zeile in verbindung.execute(text(f"SELECT * FROM {tabelle}"))]
        return "\n".join(teile)

    def legacy(self) -> Legacy:
        """The database 0.33.0 built (``tests/bestand``), then nexmail's start (``init_db``)."""
        from bauen import dump_datei, manifest_datei

        from app.config import get_settings
        from app.db import engine, init_db

        engine.dispose()
        ziel = get_settings().db_path
        for rest in ("", "-wal", "-shm"):
            Path(str(ziel) + rest).unlink(missing_ok=True)
        verbindung = sqlite3.connect(str(ziel))
        try:
            verbindung.executescript(gzip.decompress(dump_datei().read_bytes()).decode("utf-8"))
            verbindung.execute("UPDATE sitzung SET gueltig_bis = datetime('now', '+30 days')")
            verbindung.execute("UPDATE einladung SET laeuft_ab = datetime('now', '+7 days') WHERE eingeloest IS NULL")
            verbindung.commit()
        finally:
            verbindung.close()
        init_db()

        manifest = json.loads(manifest_datei().read_text(encoding="utf-8"))
        zahl: dict[str, int] = {}
        for konto in manifest["konten"]:
            if konto["adresse"]:
                zahl[konto["adresse"].lower()] = zahl.get(konto["adresse"].lower(), 0) + 1
        logins: list[tuple[str, str, bool]] = []
        for konto in manifest["konten"]:
            name, passwort, adresse = konto["benutzername"], konto.get("passwort") or "", konto["adresse"]
            if not passwort:
                logins.append((name, "", False))
                continue
            logins += [(name, passwort, True), (name.swapcase(), passwort, True)]
            if adresse:
                logins.append((adresse.upper(), passwort, zahl[adresse.lower()] == 1))
        offen = manifest["offene_einladung"]
        self.manifest = manifest
        anbieter = [konto["anbieter"]["sub"] for konto in manifest["konten"] if konto.get("anbieter")]
        return Legacy(
            logins=logins,
            invites=[offen["schluessel"]],
            fixed_names={offen["schluessel"]: offen["benutzername"]},
            provider_logins=[(sub, True) for sub in anbieter] + [("bestand-niemand", False)],
        )

    @contextmanager
    def oidc_store(self) -> Iterator[Any]:
        from app.db import SessionLocal
        from app.services.oidc_store import SqlStore

        with SessionLocal() as db:
            yield SqlStore(db)

    def account_of(self, oidc_account_id: Any) -> Any:
        """The OIDC module counts accounts by ``benutzer.nummer``; the konten store by ``benutzer.id``."""
        from app.db import SessionLocal
        from app.models import Benutzer

        with SessionLocal() as db:
            return db.query(Benutzer.id).filter(Benutzer.nummer == oidc_account_id).scalar()

    def provider_sign_in(self, subject: str) -> Any:
        """Through nexmail's OIDC routes and the fake provider of ``tests/nexoidc``, with the provider the database
        of 0.33.0 holds (``tests/bestand``)."""
        from urllib.parse import parse_qs, urlencode, urlsplit

        from fastapi.testclient import TestClient

        sys.path.insert(0, str(HIER / "nexoidc"))
        import oidc_fakes as fakes

        from app.main import app
        from app.services import anmeldebremse
        from app.vendor import nexoidc
        from app.vendor.nexoidc import attempt, protocol

        manifest = getattr(self, "manifest", None) or json.loads(
            __import__("bauen").manifest_datei().read_text(encoding="utf-8")
        )
        daten = manifest["anbieter"]
        person = next(
            (k["anbieter"] for k in manifest["konten"] if k.get("anbieter", {}).get("sub") == subject),
            {"sub": subject, "preferred_username": "niemand", "name": "", "email": ""},
        )
        netz = fakes.Network()
        nexoidc.use_transport(netz.transport())
        protocol.clear_caches()
        attempt.forget_used_states()
        anmeldebremse.zuruecksetzen()
        try:
            fake = netz.add(
                fakes.FakeProvider(daten["issuer"], client_id=daten["client_id"], client_secret=daten["client_geheimnis"])
            )
            fake.person = dict(person)
            klient = TestClient(app, base_url=manifest["oeffentliche_adresse"], follow_redirects=False)
            start = klient.get(f"/api/oidc/{daten['kuerzel']}/start")
            ziel = start.headers.get("location", "")
            pfad = urlsplit(parse_qs(urlsplit(ziel).query)["redirect_uri"][0]).path
            zurueck = klient.get(f"{pfad}?{urlencode(fake.authorize(ziel))}")
            if "error" in zurueck.headers.get("location", ""):
                return None
            ich = klient.get("/api/auth/ich")
            return ich.json()["id"] if ich.status_code == 200 else None
        finally:
            nexoidc.use_transport(None)
            protocol.clear_caches()
            attempt.forget_used_states()

    def sign_in(self, typed: str, password: str) -> Any:
        """Through ``POST /api/auth/anmelden`` (field ``benutzername``) up to the session or the code of the second
        factor. The brake is emptied first: it counts in memory and would answer 429 in a test that tries many."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services import anmeldebremse

        anmeldebremse.zuruecksetzen()
        # Ohne ``with``: kein Start der Hintergrundfaeden fuer jede Anmeldung.
        klient = TestClient(app, base_url="https://mail.example.com")
        antwort = klient.post("/api/auth/anmelden", json={"benutzername": typed, "passwort": password})
        if antwort.status_code != 200:
            return None
        package = __import__(self.package, fromlist=["login"])
        with self.store() as store:
            konto = package.login.resolve_login(store, typed)
        return konto.id if konto is not None else None
