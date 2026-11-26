"""Bescheid an das Konto, wenn ein KI-Programm auf sein Ja wartet (Modul mcp, Haken ``notify``).

nexmail hat keine Glocke. Der Bauplan („Entwurf MCP-Modul“, Freigaben) sagt: „dazu, wo die App es hat, über ihre
Benachrichtigungswege“; nexmail hat Mitteilungen im Browser (Web Push). Eine wartende Rückfrage geht deshalb als
Mitteilung an die Browser des Kontos, ein Klick öffnet die Seite der Rückfrage (``/mcp/requests/<nr>``). Die Liste
„Wartende Rückfragen“ steht unter Mein Konto › Verbindungen › KI-Werkzeuge (MCP).

⚠️ **Nur an Browser, nicht an die iPhone-App**: Die App kennt diese Meldung nicht und öffnete nichts Sinnvolles. Kein
Inhalt der Anfrage geht hinaus: seit mcp 1.1.1 nennt die Zeile der Rückfrage (``describe``) Betreff, Ordner und
Aufgabe beim Namen; die Mitteilung sagt deshalb nur, welche Art Werkzeug wartet (``WAS``), die Seite zeigt den Rest.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nexmail.mcp")

TITEL = {"de": "Ein Programm wartet auf dein Ja", "en": "A program is waiting for your yes"}
#: Was ein Werkzeug tun will, ohne Namen aus Mails (die Mitteilung geht über den Push-Dienst des Browsers).
WAS = {
    "de": {
        "draft_reply": "eine Antwort als Entwurf ablegen",
        "create_draft": "einen Entwurf ablegen",
        "set_tags": "Schlagworte einer Mail ändern",
        "move_message": "eine Mail verschieben",
        "complete_task": "eine Aufgabe abhaken",
    },
    "en": {
        "draft_reply": "store a reply as a draft",
        "create_draft": "store a draft",
        "set_tags": "change the tags of a message",
        "move_message": "move a message",
        "complete_task": "tick off a task",
    },
}
TEXT = {
    "de": "„{schluessel}“ möchte: {was}",
    "en": "'{schluessel}' would like to: {was}",
}


def melden(ereignis: str, anfrage: Any) -> None:
    """``waiting``: Mitteilung an die Browser des Kontos; ``decided``: nichts (die Seite zeigt es)."""
    if ereignis != "waiting":
        return
    try:
        from ..db import SessionLocal
        from ..models import Benutzer
        from . import push

        with SessionLocal() as db:
            person = db.get(Benutzer, str(anfrage.account_id))
            if person is None or push.draussen(person):
                return
            sprache = "de" if (person.sprache or "").startswith("de") else "en"
            meldung = push.Meldung(
                titel=TITEL[sprache],
                text=TEXT[sprache].format(schluessel=anfrage.key_name, was=WAS[sprache].get(anfrage.tool, anfrage.tool))[:200],
                ziel=f"/mcp/requests/{anfrage.id}",
                marke=f"mcp-{anfrage.id}",
            )
            for anmeldung in list(person.push_anmeldungen):
                try:
                    push.zustellen(db, anmeldung, meldung)
                except push.Zustellfehler as fehler:
                    db.rollback()
                    logger.info("Push delivery of an MCP request failed for one browser: %s", fehler)
    except Exception:  # noqa: BLE001 - ein Bescheid darf die Rückfrage nie aufhalten
        logger.exception("Telling the account about an MCP request failed request=%s", getattr(anfrage, "id", "?"))
