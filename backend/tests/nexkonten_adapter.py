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
    #: Seit Teil 2 hat nexmail eine Kontosperre: 10 Fehlversuche, 15 Minuten (``konten_store.SPERRE_NACH``).
    lock_after: int | None = 10
    #: Was nexmail nicht hat (konten 0.3.2): keine gesperrten Konten (ein Konto ist da oder entfernt), kein zweiter
    #: Faktor je Konto (nur der Schalter fuer alle), keine Einladungen fuer mehrere.
    #: Seit konten 1.1.0 sperrt der Betreiber Konten (``gesperrt_seit``) und loescht sie mit 30 Tagen zum Zurueckholen.
    blocking = True
    required_second_factor = False
    reusable_invites = False

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
                gesperrt_seit=utcnow() if blocked else None,
            )
            db.add(person)
            db.flush()
            if second_factor == "active":
                from app.services import zwei_faktor

                zwei_faktor.geheimnis_speichern(person, zwei_faktor.geheimnis_erzeugen())
                person.totp_bestaetigt = True  # speichern setzt ein neues Geheimnis auf unbestaetigt
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
        ``art = browser``, not confirmed), ``device`` the paired iPhone app, ``known_browser`` the mark in the cookie
        ``nexmail_bekannt`` (``services/sitzung.bekannt_merken``): a tuple of account and cookie, no row."""
        if kind == "known_browser":
            from app.db import SessionLocal
            from app.services import konten_store
            from app.services import sitzung as sitzungsdienst
            from app.vendor.nexkonten import sessions

            with SessionLocal() as db:
                store = konten_store.store_fuer(db)
                marke = sessions.mark(sitzungsdienst._markengeheimnis(), store.device_key(account_id))
                db.commit()
            return ("bekannt", str(account_id), sessions.add_mark("", marke))
        if kind == "program":
            return None
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

    def switch(self, name: str, on: bool) -> None:
        """The operator's switches of part 2: ``factor_required`` and ``passkeys_allowed``."""
        from app.db import SessionLocal, einstellung_schreiben
        from app.services import konten_store

        schluessel = {
            "factor_required": konten_store.SCHALTER_FAKTOR_FUER_ALLE,
            "passkeys_allowed": konten_store.SCHALTER_PASSKEYS,
        }[name]
        with SessionLocal() as db:
            einstellung_schreiben(db, schluessel, "1" if on else "0")

    def session_alive(self, handle: Any) -> bool:
        if handle is None:
            return False
        from app.db import SessionLocal
        from app.models import Sitzung

        if isinstance(handle, tuple):
            from app.models import Benutzer
            from app.services import sitzung as sitzungsdienst
            from app.vendor.nexkonten import sessions

            _, konto, cookie = handle
            with SessionLocal() as db:
                zeile = db.get(Benutzer, konto)
                schluessel = zeile.geraete_schluessel if zeile is not None else ""
            return bool(schluessel) and sessions.is_known(cookie, sitzungsdienst._markengeheimnis(), schluessel)

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
        from bauen import dump_datei, manifest_datei, totp_geheimnis

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
            # Die Authenticator-Apps und Wiederherstellungscodes von 0.33.0 (Teil 2): Geheimnis wie in bauen.py.
            factors=[
                (konto["benutzername"], totp_geheimnis(konto["zweiter_faktor"]), list(konto["wiederherstellungscodes"]))
                for konto in manifest["konten"]
                if konto.get("zweiter_faktor")
            ],
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

    def sign_in_from(self, typed: str, password: str, sender: str) -> tuple[int, Any]:
        """konten 0.3.10: through ``POST /api/auth/anmelden`` from the address ``sender``, without emptying the brake.
        nexmail reads a sender only with ``NEXMAIL_CLIENT_IP``; here ``direct`` (the peer's address) for this one
        request. 200 in or at the second factor, 401 refused like a wrong password, 429 too many attempts."""
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import app

        einstellungen = get_settings()
        vorher = einstellungen.client_ip
        object.__setattr__(einstellungen, "client_ip", "direct")
        try:
            klient = TestClient(app, base_url="https://mail.example.com", client=(sender, 50000))
            antwort = klient.post("/api/auth/anmelden", json={"benutzername": typed, "passwort": password})
        finally:
            object.__setattr__(einstellungen, "client_ip", vorher)
        if antwort.status_code != 200:
            return antwort.status_code, None
        package = __import__(self.package, fromlist=["login"])
        with self.store() as store:
            konto = package.login.resolve_login(store, typed)
        return 200, konto.id if konto is not None else None

    def listed_invites(self) -> list[dict[str, Any]]:
        """konten 0.3.10: the open invitations as the route ``GET /api/benutzer`` (``routers/benutzer.liste``) gives
        them to the operator's list, ``adresse`` as ``email`` next to ``expired``."""
        from app.db import SessionLocal
        from app.routers.benutzer import liste

        with SessionLocal() as db:
            bestand = liste(None, db)
        return [{**zeile.model_dump(), "email": zeile.adresse} for zeile in bestand.einladungen]

    def forgot_through_route(self, typed: str, *, mail_fails: bool) -> tuple[list[str], int]:
        """konten 1.0.0: "Forgot your password?" through ``POST /api/auth/kennwort-vergessen`` with a mail server and the
        public address set up; the background work runs in the ``TestClient``. The mail is caught with
        ``nexpost.testing.catch_mail`` (``fail=True``: the mail server cannot be reached)."""
        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.models import PostAusgang
        from app.services import anmeldebremse
        from app.vendor.nexpost import testing

        _postausgang_einrichten()
        anmeldebremse.zuruecksetzen()
        with SessionLocal() as db:
            vorher = db.query(PostAusgang).count()
        with testing.catch_mail(fail=mail_fails) as gefangen:
            antwort = TestClient(app, base_url="https://mail.example.com").post(
                "/api/auth/kennwort-vergessen", json={"benutzername": typed}
            )
        assert antwort.status_code == 202, antwort.text
        with SessionLocal() as db:
            neu = db.query(PostAusgang).count() - vorher
        return [brief.to for brief in gefangen.sent], neu

    def picture_status(self, owner: Any, viewer: Any | None) -> int:
        """konten 1.0.0: ``GET /api/auth/profilbild/{owner}``, signed in as ``viewer`` (a browser session of
        nexmail's table) or as nobody."""
        import secrets

        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.models import Sitzung, utcnow
        from app.services import sitzung as sitzungsdienst

        klient = TestClient(app, base_url="https://mail.example.com")
        if viewer is not None:
            token = secrets.token_urlsafe(24)
            with SessionLocal() as db:
                db.add(
                    Sitzung(
                        benutzer_id=str(viewer),
                        token_hash=sitzungsdienst._hash(token),
                        bestaetigt=True,
                        art="browser",
                        geraet="Probe",
                        gueltig_bis=utcnow() + timedelta(days=1),
                    )
                )
                db.commit()
            klient.cookies.set(sitzungsdienst.COOKIE_NAME, token)
        return klient.get(f"/api/auth/profilbild/{owner}").status_code

    # --- konten 1.1.0 -----------------------------------------------------------------------------------------------

    def age_deletion(self, account_id: Any, days: int) -> None:
        from app.db import SessionLocal
        from app.models import Benutzer

        with SessionLocal() as db:
            zeile = db.get(Benutzer, str(account_id))
            zeile.geloescht_am = zeile.geloescht_am - timedelta(days=days)
            db.commit()

    def push_ready(self, account_id: Any) -> bool | None:
        """Ob eine Meldung jetzt an ``account_id`` hinausginge (konten 1.1.0, E38): ein Browser-Abo des Kontos (beim
        ersten Mal angelegt, danach dasselbe), dann ``push.an_benutzer`` mit einer Zustellung, die nur mitzaehlt. Wahr,
        wenn sie versucht wurde."""
        from app.db import SessionLocal
        from app.models import Benutzer, PushAnmeldung
        from app.services import push

        endpunkt = f"https://push.example.com/{account_id}"
        versucht: list[str] = []
        echt = push.zustellen
        push.zustellen = lambda _db, anmeldung, _meldung: versucht.append(anmeldung.endpunkt)
        try:
            with SessionLocal() as db:
                if db.query(PushAnmeldung).filter_by(endpunkt=endpunkt).first() is None:
                    db.add(PushAnmeldung(benutzer_id=str(account_id), endpunkt=endpunkt, p256dh="p", auth="a"))
                    db.commit()
                person = db.get(Benutzer, str(account_id))
                db.refresh(person)
                push.an_benutzer(db, person, push.Meldung(titel="Probe", text="Probe", ziel="/", marke="probe"))
        finally:
            push.zustellen = echt
        return endpunkt in versucht

    def provider_active(self, on: bool) -> None:
        """Ein Anbieter in ``oidc_anbieter`` (aktiv oder aus), wie ihn der Betreiber anlegt."""
        from app.db import SessionLocal
        from app.models import OidcAnbieter

        with SessionLocal() as db:
            for zeile in db.query(OidcAnbieter).all():
                db.delete(zeile)
            db.flush()
            db.add(
                OidcAnbieter(
                    kuerzel="probe",
                    anzeigename="Probe",
                    issuer="https://auth.example.com/application/o/nexmail/",
                    client_id="nexmail",
                    aktiv=on,
                    eingeschaltet=on,
                )
            )
            db.commit()

    def readiness(self, operator: Any) -> dict[str, Any]:
        """Ueber ``GET /api/server/sign-in/readiness``, angemeldet als dieser Betreiber, ueber https."""
        from fastapi.testclient import TestClient

        from app.main import app

        klient = TestClient(app, base_url="https://testserver")
        self._anmelden_als(klient, operator)
        antwort = klient.get("/api/server/sign-in/readiness")
        assert antwort.status_code == 200, antwort.text
        return antwort.json()

    @staticmethod
    def _anmelden_als(klient: Any, account_id: Any) -> None:
        """Eine bestaetigte Browser-Sitzung fuer das Konto, als Cookie dieses Klienten (wie nach dem Anmelden)."""
        import secrets

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


def _postausgang_einrichten() -> None:
    """Ein Postausgang und die oeffentliche Adresse sind eingetragen (verschickt wird nichts: ``catch_mail``)."""
    from app.db import SessionLocal, einstellung_schreiben
    from app.services import systempost

    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
        einstellung_schreiben(db, systempost.S_SERVER, "smtp.example.com")
        einstellung_schreiben(db, systempost.S_ABSENDER, "nexmail@example.com")
