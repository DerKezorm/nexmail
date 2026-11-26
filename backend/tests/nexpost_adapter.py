"""nexpost contract tests: nexmail's adapter (copied once from the module's template, now nexmail's file).

The contract tests in ``backend/tests/nexpost/`` run the module against nexmail's real store
(``app.services.post_store``) over nexmail's tables: the system outbox settings in ``einstellung`` (``system_smtp_*``,
password sealed with ``system:smtp_passwort``) and the outbox ``post_ausgang``. The database is the one of the test
session (``tests/conftest.py`` empties it before every test).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from post_contract import Legacy, StandardAdapter, password


class Adapter(StandardAdapter):
    package = "app.vendor.nexpost"
    mail_prefix = "/api/server/mail"

    def start(self) -> None:
        from app.services import post_store

        post_store.einrichten()

    def stop(self) -> None:
        from app.db import engine

        engine.dispose()

    @contextmanager
    def store(self) -> Iterator[Any]:
        from app.db import SessionLocal
        from app.services.post_store import PostStore

        with SessionLocal() as db:
            yield PostStore(db)

    def raw_text(self) -> str:
        from sqlalchemy import text

        from app.db import engine

        teile: list[str] = []
        with engine.connect() as verbindung:
            for abfrage in (
                "SELECT * FROM einstellung WHERE schluessel LIKE 'system_smtp_%' OR schluessel LIKE 'post_%'",
                "SELECT * FROM post_ausgang",
            ):
                teile += [repr(tuple(zeile)) for zeile in verbindung.execute(text(abfrage))]
        return "\n".join(teile)

    def legacy(self) -> Legacy:
        """The mail server as nexmail's own page of 0.33.0 saved it (``systempost.schreiben``: ``ssl``, a sealed
        password, a sender name); 0.33.0 had no outbox."""
        from app.db import SessionLocal
        from app.services import systempost
        from app.vendor.nexpost.model import MailSettings

        geheim = password()
        with SessionLocal() as db:
            systempost.schreiben(
                db,
                systempost.Postausgang(
                    server="smtp.example.com",
                    port=465,
                    sicherheit="ssl",
                    benutzer="post@example.com",
                    absender="nexmail@example.com",
                    absendername="Haus Beispiel",
                ),
                geheim,
            )
            db.commit()
        return Legacy(
            settings=MailSettings(
                host="smtp.example.com",
                port=465,
                security="tls",
                user="post@example.com",
                password=geheim,
                sender="nexmail@example.com",
                sender_name="Haus Beispiel",
            ),
            queued=0,
        )

    def new_sign_in_letter(self, where: str, sender: str) -> Any:
        """post 1.0.0: an account with a confirmed address signs in through ``POST /api/auth/anmelden`` from a browser
        it does not know (User-Agent ``where``, from ``sender`` with ``NEXMAIL_CLIENT_IP=direct``); the letter
        "New sign-in" is caught on its way into the outbox (``nexpost.testing.catch_mail``)."""
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.db import SessionLocal, einstellung_schreiben
        from app.main import app
        from app.models import Benutzer
        from app.services import anmeldebremse, systempost
        from app.services import benutzer as benutzerdienst
        from app.vendor.nexpost import testing

        geheim = password()
        with SessionLocal() as db:
            einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
            einstellung_schreiben(db, systempost.S_SERVER, "smtp.example.com")
            einstellung_schreiben(db, systempost.S_ABSENDER, "nexmail@example.com")
            db.add(
                Benutzer(
                    benutzername="kim",
                    anzeigename="Kim",
                    passwort_hash=benutzerdienst.hashen(geheim),
                    kontaktadresse="kim@example.com",
                    kontaktadresse_zaehlt=True,
                )
            )
            db.commit()
        anmeldebremse.zuruecksetzen()
        einstellungen = get_settings()
        vorher = einstellungen.client_ip
        object.__setattr__(einstellungen, "client_ip", "direct")
        try:
            with testing.catch_mail() as gefangen:
                klient = TestClient(app, base_url="https://mail.example.com", client=(sender, 50000))
                antwort = klient.post(
                    "/api/auth/anmelden",
                    json={"benutzername": "kim", "passwort": geheim},
                    headers={"User-Agent": where},
                )
        finally:
            object.__setattr__(einstellungen, "client_ip", vorher)
        assert antwort.status_code == 200, antwort.text
        briefe = [brief for brief in gefangen.letters if brief.kind == "new_sign_in"]
        assert briefe, [brief.kind for brief in gefangen.letters]
        return briefe[0]

    # --- post 1.1.0 ---------------------------------------------------------------------------------------------------

    def account(self, address: str, *, language: str, name: str, confirmed: bool) -> Any:
        from app.db import SessionLocal
        from app.models import Benutzer

        with SessionLocal() as db:
            person = Benutzer(
                benutzername=f"konto{len(db.query(Benutzer).all()) + 1}",
                anzeigename=name,
                passwort_hash="",
                kontaktadresse=address,
                kontaktadresse_zaehlt=confirmed,
                sprache=language,
            )
            db.add(person)
            db.commit()
            return person.id

    def client(self, role: str) -> Any:
        """nexmails TestClient: ``anonymous`` ohne Sitzung, ``member`` und ``operator`` angemeldet (Sitzung als
        Cookie). Das Mailmodul haengt dort unter ``/api/server/mail`` (``main.py``)."""
        import secrets
        from datetime import timedelta

        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.models import Benutzer, Sitzung, utcnow
        from app.services import sitzung as sitzungsdienst

        klient = TestClient(app)
        if role == "anonymous":
            return klient
        token = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            person = Benutzer(
                benutzername=f"{role}{secrets.token_hex(3)}",
                anzeigename=role,
                passwort_hash="",
                ist_betreiber=role == "operator",
            )
            db.add(person)
            db.flush()
            db.add(
                Sitzung(
                    benutzer_id=person.id,
                    token_hash=sitzungsdienst._hash(token),
                    bestaetigt=True,
                    art="browser",
                    gueltig_bis=utcnow() + timedelta(days=1),
                )
            )
            db.commit()
        klient.cookies.set(sitzungsdienst.COOKIE_NAME, token)
        return klient

