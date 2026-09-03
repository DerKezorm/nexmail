"""Die eingestellte Zeitzone — an einer Stelle, und nie stillschweigend falsch.

⚠️ **Diese Datei ist aus Schaden entstanden.** Am 02.09.2026 kannte die
Entwicklungsumgebung keine einzige Zeitzone: Python bringt unter Windows keine
Zeitzonendatenbank mit, im Container liegt sie im System. Jede Auflösung
scheiterte, und drei Stellen wichen daraufhin **stumm** auf UTC aus — die
Uhrzeit im Ausdruck, der Zeitraum der Abwesenheitsnotiz und die Zeit einer
Termin-Einladung. Alles um Stunden verschoben, ohne dass irgendwo etwas stand.

Behoben ist die Ursache (``tzdata`` in den Abhängigkeiten). Hier steht die
Vorsorge gegen die Wiederholung: **Wer ausweicht, sagt es.** Ein Ausdruck in
UTC ist besser als gar keiner — aber niemand soll je wieder rätseln, warum die
Uhrzeit um zwei Stunden danebenliegt.
"""

from __future__ import annotations

import logging
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo

logger = logging.getLogger("nexmail.zeit")

#: Wovor schon gewarnt wurde. Eine Warnung je Zonenname reicht — sonst füllt
#: eine Ordnerspalte mit hundert Ordnern das Protokoll.
_gewarnt: set[str] = set()


def zone(name: str) -> tzinfo:
    """Die Zone zu diesem Namen — oder UTC, und dann steht es im Protokoll."""
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        if name not in _gewarnt:
            _gewarnt.add(name)
            logger.warning(
                "Time zone %r is unknown here; falling back to UTC. Every time "
                "shown may be off by hours. Is the tzdata package missing?",
                name,
            )
        return timezone.utc


def zone_der_anwendung(db) -> tzinfo:
    """Die eingestellte Zone des Betreibers."""
    from ..config import get_settings
    from ..db import einstellung_lesen
    from ..routers.einstellungen import SCHLUESSEL_ZEITZONE

    return zone(einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone)


def zonenname_der_anwendung(db) -> str:
    """Der **Name** der eingestellten Zone, nicht das Objekt.

    ⚠️ **Ein Termin speichert den Namen, nicht die Zone.** „Jeden Montag um 9"
    muss auch in zehn Jahren neun Uhr heissen — und ob das dann 09:00+01:00
    oder +02:00 ist, entscheidet die Zeitzonendatenbank, nicht wir. Wer den
    Versatz speichert statt des Namens, friert die Sommerzeit von heute ein.
    """
    from ..config import get_settings
    from ..db import einstellung_lesen
    from ..routers.einstellungen import SCHLUESSEL_ZEITZONE

    return einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone
