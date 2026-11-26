"""nexschluessel contract tests: the app's adapter. Copied once by the module's ``tools/sync.py copy <app>`` to
``backend/tests/nexschluessel_adapter.py``; from then on it is the app's file.

Fill in every place marked ``APP:``. The contract tests in ``backend/tests/nexschluessel/`` (same in every app, never
edit them) call only what is here and in ``StandardAdapter``. Worked examples: the module's
``tests-fuer-apps/reference/nexschluessel_adapter.py`` (an app like nexnotes) and ``tests/mail_like_adapter.py`` (an
app like nexmail). Run them with ``pytest tests/nexschluessel``. Keys are made at run time; none is written into this
file.

The heart of it is ``legacy_keys`` and ``make_legacy``: every form of key the app made before the module (each kind,
each prefix, the old forms that still work, the connectors of AI tools), written exactly the way the older version
wrote it. The tests present each to the app's real routes before and after the module touched it.
"""

from __future__ import annotations

from typing import Any

import pytest

from schluessel_contract import LegacyKey, StandardAdapter


KENNWORT = {"owner": "eigen-geheim-123", "other": "anders-geheim-456", "operator": "betreib-geheim-789"}


class Adapter(StandardAdapter):
    """nexmail: ``api_schluessel`` (Text-Kennungen, deutsche Spalten), Rechte ``anzahl``/``betreff``, Postfaecher
    Pflicht, Extras Aufgaben und Schlagworte, kein Ablauf; die Wege des Moduls unter ``/api/connections``."""

    package = "app.vendor.nexschluessel"
    prefix = "/api/connections"

    def start(self) -> None:
        from app.db import SessionLocal, einstellung_schreiben
        from app.models import Benutzer, Konto
        from app.services import apischluessel as apidienst
        from app.services import benutzer as benutzerdienst

        self.ids: dict[str, str] = {}
        self.postfach: dict[str, str] = {}
        self._clients: list[Any] = []
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
                self.ids[rolle] = person.id
                self.postfach[rolle] = konto.id
            db.commit()
            # nexmails Schalter steht ab Werk auf aus; die Tests beginnen dort, wo der Betreiber Schluessel erlaubt.
            einstellung_schreiben(db, apidienst.SCHALTER, "1")

    def stop(self) -> None:
        for client in self._clients:
            client.__exit__(None, None, None)

    def config(self) -> Any:
        from app.services.schluessel_store import KONFIGURATION

        return KONFIGURATION

    def client(self, role: str) -> Any:
        """Eine bestaetigte Browser-Sitzung als Cookie, wie nach dem Anmelden. Direkt angelegt, damit sie auch dann
        besteht, wenn der Betreiber danach einen zweiten Faktor verlangt (``owe_factor``): eine laufende Sitzung
        bleibt, nur die Schluessel ruhen."""
        import secrets
        from datetime import timedelta

        from fastapi.testclient import TestClient

        from app.db import SessionLocal
        from app.main import app
        from app.models import Sitzung, utcnow
        from app.services import sitzung as sitzungsdienst

        client = TestClient(app)
        client.__enter__()
        self._clients.append(client)
        if role == "anonymous":
            return client
        token = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            db.add(
                Sitzung(
                    benutzer_id=self.ids[role],
                    token_hash=sitzungsdienst._hash(token),
                    bestaetigt=True,
                    art="browser",
                    gueltig_bis=utcnow() + timedelta(days=1),
                )
            )
            db.commit()
        client.cookies.set(sitzungsdienst.COOKIE_NAME, token)
        return client

    def legacy_keys(self) -> list[LegacyKey]:
        return [
            LegacyKey("API key (count)", "api", "nxm_", "count"),
            LegacyKey("API key (headers)", "api", "nxm_", "headers"),
        ]

    def make_legacy(self, spec: LegacyKey, *, account: str = "owner", expired: bool = False) -> str:
        """Wie nexmail 0.33.0 es tat: ``apischluessel.anlegen`` (vor der Spalte ``gesperrt``)."""
        if expired:
            pytest.skip("nexmail's keys have no end")
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import apischluessel as apidienst

        with SessionLocal() as db:
            person = db.get(Benutzer, self.ids[account])
            _zeile, geheim = apidienst.anlegen(
                db, person, spec.label, {"count": "anzahl", "headers": "betreff"}[spec.right], [self.postfach[account]]
            )
            db.commit()
        return geheim

    def probe(self, kind: str, secret: str) -> int:
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app).get("/api/v1/me", headers={"Authorization": f"Bearer {secret}"}).status_code

    def owe_factor(self) -> None:
        from app.db import SessionLocal, einstellung_schreiben
        from app.services import konten_store

        with SessionLocal() as db:
            einstellung_schreiben(db, konten_store.SCHALTER_FAKTOR_FUER_ALLE, "1")

    def defaults(self, kind: Any) -> dict:
        return {"areas": [self.postfach["owner"]]}

    def foreign_area(self) -> Any:
        return self.postfach["other"]
