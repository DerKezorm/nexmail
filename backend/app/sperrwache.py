"""Wer hält SQLites Schreibsperre, und wie lange?

⚠️ **Der Anlass ist Issue #9.** Ein Betreiber bekam wiederholt „database is
locked": Irgendwer hielt die einzige Schreibsperre länger als
``busy_timeout`` (10 s), und alle anderen Schreiber gaben auf. Im Protokoll
standen nur die, die gewartet hatten. Wer die Sperre hielt, sagte nichts, und
weder der Code noch eine Messung an 300.000 Nachrichten fand einen Kandidaten.

Deshalb zwei Meldungen, beide auf WARNING:

1. **Eine lange gehaltene Sperre**, sobald sie fällt: wie lange, welche
   Anweisung sie genommen hat, an welcher Stelle im Code und in welchem
   Faden.
2. **Ein Schreiber, der aufgeben musste**, samt allen, die die Sperre in
   diesem Moment halten. Das ist die Antwort auf die Frage, die das Issue
   offen ließ, und sie steht direkt neben dem Fehler.

⚠️ **Nur die Anweisung, nie ihre Werte.** Die Parameter tragen Betreffzeilen,
Adressen und Mailtext; die Anweisung trägt nur Tabellen- und Spaltennamen.

⚠️ **Die Sperre beginnt mit der ersten schreibenden Anweisung**, nicht mit
der Transaktion: ``pysqlite`` öffnet sie erst vor einem INSERT, UPDATE oder
DELETE. Lesen nimmt in WAL keine Sperre, also zählt es hier nicht.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("nexmail.db")

#: Ab wann eine gehaltene Sperre gemeldet wird. Gemessen am 12.10.2026: Ein
#: Abgleichblock aus 200 Mails hält sie bei 300.000 Nachrichten höchstens
#: 0,63 s, ``optimize`` des Volltextindex 4,3 s. Drei Sekunden lassen den
#: Alltag still und melden alles, was einem anderen Schreiber gefährlich wird.
SCHWELLE = 3.0

_SCHREIBEND = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")

#: Die offenen Schreibvorgänge, je DBAPI-Verbindung: seit wann, was, wo, wer.
_offen: dict[int, tuple[float, str, str, str]] = {}
_zugriff = threading.Lock()

_APP = str(Path(__file__).resolve().parent)
_HIER = str(Path(__file__).resolve())


def _kurz(anweisung: str) -> str:
    """Die Anweisung auf einer Zeile, gekürzt. Werte stehen nie darin."""
    return " ".join(anweisung.split())[:120]


#: Wie viele Stellen der Aufrufkette genannt werden. Eine allein sagt bei
#: Hilfsfunktionen wie ``einstellung_schreiben`` nicht, wer sie gerufen hat.
TIEFE = 3


def _stelle() -> str:
    """Die innersten Stellen in nexmails eigenem Code, die gerade schreiben.

    Ohne sie hieße es bei jedem Fund nur „AnyIO worker thread": Die
    Anfragen laufen alle in Fäden mit demselben Namen.
    """
    stellen: list[str] = []
    rahmen = sys._getframe(2)
    while rahmen is not None and len(stellen) < TIEFE:
        datei = rahmen.f_code.co_filename
        if datei.startswith(_APP) and datei != _HIER:
            pfad = Path(datei).relative_to(_APP).as_posix()
            stellen.append(f"{pfad}:{rahmen.f_lineno} {rahmen.f_code.co_name}")
        rahmen = rahmen.f_back
    return " < ".join(stellen) or "?"


def _schluessel(verbindung) -> int:
    return id(verbindung.connection.dbapi_connection)


def _beginn(verbindung, _cursor, anweisung, _parameter, _kontext, _mehrfach) -> None:
    if not anweisung.lstrip()[:7].upper().startswith(_SCHREIBEND):
        return
    schluessel = _schluessel(verbindung)
    with _zugriff:
        if schluessel in _offen:
            return
        _offen[schluessel] = (
            time.monotonic(),
            _kurz(anweisung),
            _stelle(),
            threading.current_thread().name,
        )


def _ende(schluessel: int) -> None:
    with _zugriff:
        eintrag = _offen.pop(schluessel, None)
    if eintrag is None:
        return
    seit, anweisung, stelle, faden = eintrag
    dauer = time.monotonic() - seit
    if dauer >= SCHWELLE:
        logger.warning(
            "A write held the database for %.1f s: %s, from %s (thread %s).",
            dauer,
            anweisung,
            stelle,
            faden,
        )


def _festgeschrieben(verbindung) -> None:
    _ende(_schluessel(verbindung))


def _gescheitert(kontext) -> None:
    if "database is locked" not in str(kontext.original_exception):
        return
    eigene = None
    if kontext.connection is not None:
        try:
            eigene = _schluessel(kontext.connection)
        except Exception:  # noqa: BLE001 - eine geschlossene Verbindung hat keine
            eigene = None
    jetzt = time.monotonic()
    with _zugriff:
        halter = [e for k, e in _offen.items() if k != eigene]
    if not halter:
        logger.warning(
            "A write gave up on a locked database (%s, from %s); no other write of "
            "this process held it, so the lock came from outside nexmail's connections.",
            _kurz(kontext.statement or ""),
            _stelle(),
        )
        return
    for seit, anweisung, stelle, faden in halter:
        logger.warning(
            "A write gave up on a locked database (%s, from %s). Holding it for %.1f s: "
            "%s, from %s (thread %s).",
            _kurz(kontext.statement or ""),
            _stelle(),
            jetzt - seit,
            anweisung,
            stelle,
            faden,
        )


def einrichten(engine: Engine) -> None:
    event.listen(engine, "before_cursor_execute", _beginn)
    event.listen(engine, "commit", _festgeschrieben)
    # ⚠️ **Kein eigener Hörer für ``checkin``.** Auch eine Sitzung, die mit
    # offenem Schreibvorgang geschlossen wird, geht über ``rollback``; die
    # Mutationsprobe am 13.10.2026 fand keinen Weg, auf dem ``checkin`` allein
    # etwas beendet hätte.
    event.listen(engine, "rollback", _festgeschrieben)
    event.listen(engine, "handle_error", _gescheitert)
