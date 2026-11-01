"""Hat sich im Postfach etwas getan? Für offene Browserfenster.

Bis 0.24.7 lud ein offenes Fenster nur nach einer eigenen Handlung neu. Der
Takt holte die Post in die Datenbank, und niemand sagte es der Oberfläche.

⚠️ **Ein Zähler je Benutzer im Arbeitsspeicher, keine Nachricht.** Das Fenster
erfährt nur, *dass* sich etwas geändert hat, und holt sich den Rest über die
gewöhnlichen Adressen, samt ihrer Rechteprüfung. So gibt es keinen zweiten Weg,
auf dem Inhalte hinausgehen.

⚠️ **Der Zähler beginnt bei der Uhrzeit des Starts.** Nach einem Neustart
unterscheidet er sich von dem, was ein offenes Fenster kennt. Das kostet einmal
Neuladen und deckt ab, was während des Neustarts geschah.

⚠️ **Das gilt nur mit einem Prozess.** Das Abbild startet genau einen
(``--workers 1``), und Takt und Fäden gibt es ohnehin nur einmal.
"""

from __future__ import annotations

import threading
import time

_schloss = threading.Lock()
_beginn = int(time.time())
_staende: dict[str, int] = {}


def melden(benutzer_id: str) -> None:
    with _schloss:
        _staende[benutzer_id] = _staende.get(benutzer_id, _beginn) + 1


def stand(benutzer_id: str) -> int:
    with _schloss:
        return _staende.get(benutzer_id, _beginn)


__all__ = ["melden", "stand"]
