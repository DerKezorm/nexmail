"""nexsprachen contract tests: the app's adapter. Copied once by the module's ``tools/sync.py copy <app>`` to
``backend/tests/nexsprachen_adapter.py``; from then on it is the app's file.

Fill in every place marked ``APP:``. The contract tests in ``backend/tests/nexsprachen/`` (same in every app, never
edit them) call only what is here and in ``StandardAdapter``. Worked examples: the module's
``tests-fuer-apps/reference/nexsprachen_adapter.py`` (an app like nexnotes) and ``tests/private_like_adapter.py`` (an
app that reads only for who is signed in, under two prefixes, with its own form of a refusal). Run them with
``pytest tests/nexsprachen``.
"""

from __future__ import annotations

from typing import Any

from sprachen_contract import StandardAdapter


class Adapter(StandardAdapter):
    # APP: where the vendored package lives, where the routes are mounted (and further prefixes of the same routes),
    # the languages the app ships (code -> name in itself, as in AppConfig.built_in), whether anybody reads, whether
    # the server hands out the template.
    package = "app.vendor.nexsprachen"
    prefix = "/api/locales"
    also: tuple[str, ...] = ()
    built_in = {"de": "Deutsch", "en": "English"}
    public_read = True
    #: nexmail: die Seite macht die Vorlage aus ihren englischen Texten; der Server kennt sie nicht.
    has_template = False
    # nexmail hatte vor dem Modul keine eigenen Sprach-Wege, also keine alten Namen in einer Beschreibung.
    openapi_path = "/openapi.json"
    operation_ids: dict[str, str] = {}
    summaries: dict[str, str] = {}
    schema_names: dict[str, str] = {}

    def start(self) -> None:
        """nexmails Testlauf (conftest) hat Datenbank und Datenordner schon frisch; hier nur der Ordner der Sprachen
        leer, der Betreiber eingerichtet und ein Mitglied angelegt, beide über die echten Wege angemeldet."""
        import shutil

        from fastapi.testclient import TestClient

        from app.main import app
        from app.vendor import nexsprachen

        shutil.rmtree(nexsprachen.locales_dir(), ignore_errors=True)
        nexsprachen.forget()
        self._clients: list[Any] = []
        from app.db import SessionLocal
        from app.models import Benutzer
        from app.services import benutzer as benutzerdienst

        kennwort = {"operator": "betreib-geheim-789", "member": "mitglied-geheim-456"}
        with SessionLocal() as db:
            for rolle, name in (("operator", "betreiber"), ("member", "mitglied")):
                db.add(
                    Benutzer(
                        benutzername=name,
                        anzeigename=name.title(),
                        passwort_hash=benutzerdienst.hashen(kennwort[rolle]),
                        ist_betreiber=rolle == "operator",
                    )
                )
                db.flush()
            db.commit()

        def angemeldet(name: str, passwort: str) -> Any:
            client = TestClient(app)
            client.__enter__()
            self._clients.append(client)
            antwort = client.post("/api/auth/anmelden", json={"benutzername": name, "passwort": passwort})
            assert antwort.status_code == 200, antwort.text
            return client

        betreiber = angemeldet("betreiber", kennwort["operator"])
        mitglied = angemeldet("mitglied", kennwort["member"])
        self._rollen = {"operator": betreiber, "member": mitglied}

    def stop(self) -> None:
        import shutil

        from app.vendor import nexsprachen

        for client in self._clients:
            client.__exit__(None, None, None)
        shutil.rmtree(nexsprachen.locales_dir(), ignore_errors=True)
        nexsprachen.forget()

    def client(self, role: str) -> Any:
        from fastapi.testclient import TestClient

        from app.main import app

        if role == "anonymous":
            client = TestClient(app)
            client.__enter__()
            self._clients.append(client)
            return client
        return self._rollen[role]

    def refusal(self, response: Any) -> tuple[str, dict[str, Any]]:
        """nexmails Form: ``{"detail": "<kennung>", "werte": {...}}`` (``meldung.MeldungHttp``)."""
        body = response.json()
        return str(body["detail"]), dict(body.get("werte") or {})
