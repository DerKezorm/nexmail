"""nexoidc contract tests: nexmail's adapter (from the module's adapter template).

The contract tests in ``tests/nexoidc/`` are the same in every app and never edited here. Everything nexmail does its
own way is answered below: accounts in ``benutzer`` (the module knows them by ``nummer``), invitations in
``einladung``, a session in the cookie ``nexmail_sitzung``, the second factor as TOTP with a half session in between,
refusals as ``{"detail": <code>, "werte": {...}}``.

nexmail had a provider list before the module (0.21, ``legacy_model = "list"``); its providers know the redirect
address ``/api/oidc/<slug>/zurueck``. nexmail's provider list is never coupled to a central directory. Its invitations carry no rights (every
account is a member), so the parts of the invitation tests that grant "editor" rights do not apply; ``make_invite("editor")``
skips them, and ``tests/test_oidc_app.py`` checks the invitation through a provider in nexmail's own terms.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from oidc_contract import StandardAdapter
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, einstellung_lesen, einstellung_schreiben
from app.main import app
from app.models import Benutzer
from app.services import anmeldebremse, zwei_faktor
from app.services import benutzer as benutzerdienst
from app.services import einladung as einladungsdienst
from app.services.oidc_store import SqlStore

OPERATOR = "operator"


class Adapter(StandardAdapter):
    package = "app.vendor.nexoidc"
    api = "/api"
    single_account = False
    only_authentik = False
    # nexmail's provider list is never coupled to a central directory.
    supports_coupling = False
    has_second_factor = True
    legacy_model = "list"
    trusted_before = True
    old_callback_paths: tuple[str, ...] = ("/api/oidc/{slug}/zurueck",)
    operator_name = OPERATOR
    origin = "http://testserver"
    anonymous_status: tuple[int, ...] = (401,)
    member_status: tuple[int, ...] = (403,)
    home = "/"
    login_page = "/anmelden"
    account_page = "/konto/sicherheit"

    def start(self) -> None:
        # The database is emptied by ``frische_datenbank`` in ``tests/conftest.py`` before every test.
        self._operator: TestClient | None = None
        self.totp: dict[str, str] = {}
        # nexmail counts the brake per sender only when it knows the sender (``NEXMAIL_CLIENT_IP``); the test
        # browser is ``testclient``.
        self._client_ip = get_settings().client_ip
        get_settings().client_ip = "direct"
        made = self.browser().post(
            "/api/setup/konto", json={"benutzername": OPERATOR, "passwort": self.password_for(OPERATOR)}
        )
        assert made.status_code == 201, made.text

    def stop(self) -> None:
        get_settings().client_ip = self._client_ip

    def browser(self) -> TestClient:
        return TestClient(app, base_url="http://testserver", follow_redirects=False)

    def operator(self) -> TestClient:
        if self._operator is None:
            self._operator = self.browser()
            self.sign_in_with_password(self._operator, OPERATOR)
        return self._operator

    def make_account(self, name: str, *, password: bool = True, second_factor: bool = False) -> int:
        with SessionLocal() as db:
            # Straight into the table: the contract names accounts "pw" too, shorter than a name chosen in nexmail.
            person = Benutzer(
                benutzername=name,
                anzeigename=name,
                passwort_hash=benutzerdienst.hashen(self.password_for(name)) if password else "",
            )
            db.add(person)
            db.commit()
            if second_factor:
                geheimnis = zwei_faktor.geheimnis_erzeugen()
                zwei_faktor.geheimnis_speichern(person, geheimnis)
                person.totp_bestaetigt = True
                self.totp[name] = geheimnis
                db.commit()
            return SqlStore(db).konto_nummer(person)

    def sign_in_with_password(self, client: Any, name: str) -> None:
        response = client.post(
            "/api/auth/anmelden", json={"benutzername": name, "passwort": self.password_for(name)}
        )
        assert response.status_code == 200, response.text
        if response.json()["schritt"] != "fertig":
            with SessionLocal() as db:
                # A code counts once per time step; a second sign-in within 30 seconds would be refused.
                person = db.scalar(select(Benutzer).where(Benutzer.benutzername == name))
                person.totp_letzter_schritt = 0
                db.commit()
            import pyotp

            code = client.post("/api/auth/code", json={"code": pyotp.TOTP(self.totp[name]).now()})
            assert code.status_code == 200, code.text

    def who(self, client: Any) -> str | None:
        me = client.get("/api/auth/ich")
        return me.json()["benutzername"] if me.status_code == 200 else None

    def second_factor_asked(self, client: Any, response: httpx.Response) -> bool:
        location = response.headers.get("location", "")
        return "schritt=code" in location and self.who(client) is None

    def make_invite(self, rights: str) -> str:
        if rights != "member":
            pytest.skip("nexmail's invitations carry no rights (every account is a member); see test_oidc_app.py")
        with SessionLocal() as db:
            _, key = einladungsdienst.aussprechen(
                db, benutzername=f"invited{secrets.token_hex(3)}", adresse=f"invited-{secrets.token_hex(3)}@example.com"
            )
        return key

    def rights_of(self, name: str) -> str | None:
        with SessionLocal() as db:
            return "member" if benutzerdienst.finden(db, name) is not None else None

    def account_names(self) -> list[str]:
        with SessionLocal() as db:
            return sorted(db.scalars(select(Benutzer.benutzername)))

    def store(self) -> AbstractContextManager[Any]:
        @contextmanager
        def opened() -> Iterator[SqlStore]:
            with SessionLocal() as db:
                yield SqlStore(db)

        return opened()

    def trip_throttle(self, client: Any) -> None:
        # The brake at start and return counts per sender; every TestClient comes from "testclient".
        for _ in range(anmeldebremse.SPERRE_AB_VERSUCH):
            anmeldebremse.Torwaechter(schluessel=["oidc:adresse:testclient"]).fehlgeschlagen()

    def set_public_url(self, url: str) -> None:
        with SessionLocal() as db:
            einstellung_schreiben(db, "oeffentliche_adresse", url)

    def read_public_url(self) -> str:
        with SessionLocal() as db:
            return einstellung_lesen(db, "oeffentliche_adresse")

    def save_public_url_route(self, url: str, *, confirm: bool = False) -> httpx.Response:
        """Verwaltung → Server saves the public address through ``PUT /api/einstellungen``, which asks first."""
        return self.operator().put(
            "/api/einstellungen", json={"oeffentliche_adresse": url, "zeitzone": "", "adresse_bestaetigt": confirm}
        )

    def error_detail(self, response: httpx.Response) -> dict[str, Any]:
        """nexmail answers ``{"detail": <code>, "werte": {...}}`` (``meldung.MeldungHttp``)."""
        werte = response.json().get("werte")
        return werte if isinstance(werte, dict) else {}
