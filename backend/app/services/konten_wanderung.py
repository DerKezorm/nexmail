"""Was das Kontenmodul beim Start an der Datenbank braucht und ``init_db`` nicht von selbst anlegt.

Spalten und Tabellen kommen ueber die Schemapflege in ``db.init_db`` (nur hinzufuegen, mit der Vorgabe, die den
Stand von vorher beschreibt; davor sichert sie, weil neue Tabellen fehlen). Hier steht nur der eine Index, der nicht
blind angelegt werden darf.

⚠️ **Der eindeutige Index auf den kleingeschriebenen Benutzernamen kommt erst nach dem Zaehlen.** Die Vorfassung
verglich zwar beim Anlegen ohne Gross/Klein, die Datenbank selbst aber nur mit: Zwei Konten ``Anna`` und ``anna``
koennen durch einen Wettlauf entstanden sein. Dann scheiterte ``CREATE UNIQUE INDEX``, und mit ihm der Start. Statt
dessen wartet der Index (eine Zeile im Protokoll, bei jedem Start), und beide melden sich weiter mit ihrem genau
geschriebenen Namen an (``nexkonten.login.by_username``).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("nexmail.konten")

INDEX = "uq_benutzer_benutzername_klein"


def doppelte_namen(engine: Engine) -> list[str]:
    with engine.connect() as verbindung:
        return [
            z[0]
            for z in verbindung.execute(
                text("SELECT lower(benutzername) FROM benutzer GROUP BY lower(benutzername) HAVING count(*) > 1")
            )
        ]


def laufen(engine: Engine) -> list[str]:
    """Legt den Index an, wenn es keine Doppel gibt; gibt die Doppel zurueck (leer: alles da)."""
    with engine.connect() as verbindung:
        da = verbindung.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :n"), {"n": INDEX}
        ).first()
    if da:
        return []
    doppel = doppelte_namen(engine)
    if doppel:
        logger.warning(
            "%s usernames differ only in case; the unique index on the lower-case name waits until one is renamed.",
            len(doppel),
        )
        return doppel
    with engine.begin() as verbindung:
        verbindung.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON benutzer (lower(benutzername))"))
    logger.info("Schema updated, index added: %s", INDEX)
    return []
