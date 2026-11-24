"""nexpost contract tests: the app's adapter. Copied once by the module's ``tools/sync.py copy <app>`` to
``backend/tests/nexpost_adapter.py``; from then on it is the app's file.

Fill in every place marked ``APP:``. The contract tests in ``backend/tests/nexpost/`` (same in every app, never edit
them) call only what is here and in ``StandardAdapter``. A worked example is the module's
``tests-fuer-apps/reference/nexpost_adapter.py`` (SQLAlchemy, SQLite). Run them with ``pytest tests/nexpost``. Test
values are made at run time; no password is written into this file, and no mail leaves the machine.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from post_contract import Legacy, StandardAdapter


class Adapter(StandardAdapter):
    # APP: where the vendored package lives.
    package = "app.vendor.nexpost"

    def start(self) -> None:
        # APP: an empty app with a fresh database (the app's own migration), nexpost configured as at start-up.
        raise NotImplementedError("APP: start")

    def stop(self) -> None:
        # APP: close the database, remove temporary folders.
        pass

    def store(self) -> AbstractContextManager[Any]:
        # APP: the app's Store over one session, closed afterwards (a context manager).
        raise NotImplementedError("APP: store")

    def raw_text(self) -> str:
        # APP: every value of the tables of settings and outbox, as one text.
        raise NotImplementedError("APP: raw_text")

    def legacy(self) -> Legacy:
        # APP: the older version's database with its mail server saved by its own page (and waiting mails where it
        # had an outbox), then the app's start; the settings as they must read now.
        raise NotImplementedError("APP: legacy")
