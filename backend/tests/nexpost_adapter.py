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
