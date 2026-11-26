"""Ein Anhang als Dokument an nexpaper (Durchgang „Module“, Runde 2, V19: nexmail ist Gast mit ``documents.add``).

Nur über eine per „Verbinden“ gemachte Verbindung (Modul verbinden 0.1.2): nexmail holt Adresse und frisches Token der
Verbindung (``verbinden_store.zugriff``) und lädt die Datei mit eigenem Klient hoch, weil ``nexverbinden.call`` nur JSON
schickt. nexpaper legt das Dokument in den Tresor, den es ab Werk nimmt (bzw. den einzigen, den die Verbindung darf).

⚠️ **Dieselbe Netzprüfung wie beim Verbinden mit nextasks von Hand** (``nextasks._pruefen``): das eigene Netz nur mit der
Freigabe des Betreibers, keine Weiterleitung.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..meldung import Meldung
from . import nextasks, verbinden_store

logger = logging.getLogger("nexmail.nexpaper")

#: Nur für Tests: ein eigener Transport statt eines echten Netzes.
TRANSPORT: httpx.BaseTransport | None = None
ZEITGRENZE = 60.0


class NexpaperFehler(Meldung, RuntimeError):
    """Trägt eine KENNUNG, keinen deutschen Satz."""


def _gelaufen(konto_id: str, problem: str | None = None) -> None:
    try:
        verbinden_store.gelaufen("nexpaper", konto_id, problem)
    except Exception:  # noqa: BLE001 - die Karte ist Nebensache, das Ergebnis zählt
        logger.warning("Telling the connection card how nexpaper answered failed", exc_info=True)


def senden(konto_id: str, dateiname: str, inhalt: bytes) -> dict[str, Any]:
    """Die Datei an nexpaper (``POST /api/v1/documents``, Feld ``file``); nach einem 401 einmal mit frischem Token.
    Gibt das erste Ergebnis nexpapers zurück (``status``: ``created`` oder ``duplicate``)."""
    for versuch in (1, 2):
        try:
            zugang = verbinden_store.zugriff("nexpaper", konto_id, neu=versuch == 2)
        except verbinden_store.Unerreichbar as fehler:
            raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler
        except verbinden_store.Abgelehnt as fehler:
            raise NexpaperFehler("nexpaper_nicht_verbunden") from fehler
        url = f"{zugang.base.rstrip('/')}/api/v1/documents"
        try:
            if TRANSPORT is None:
                nextasks._pruefen(zugang.base.rstrip("/"))  # noqa: SLF001
        except nextasks.NextasksFehler as fehler:
            raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler
        try:
            with httpx.Client(timeout=ZEITGRENZE, follow_redirects=False, transport=TRANSPORT) as klient:
                antwort = klient.post(
                    url,
                    files={"file": (dateiname or "anhang", inhalt, "application/octet-stream")},
                    # ⚠️ Kein ``Origin``: nexpaper lehnt Anfragen aus Webseiten an /api/v1 ab.
                    headers={"Authorization": f"Bearer {zugang.token}", "User-Agent": "nexmail"},
                )
        except httpx.HTTPError as fehler:
            logger.info("nexpaper was unreachable: %s", type(fehler).__name__)
            _gelaufen(konto_id, "unreachable")
            raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler
        if antwort.status_code == 401 and versuch == 1:
            continue
        if antwort.status_code == 401:
            _gelaufen(konto_id, "token_invalid")
            raise NexpaperFehler("nexpaper_nicht_verbunden")
        _gelaufen(konto_id)
        if antwort.status_code >= 300:
            logger.info("nexpaper did not take the file: %s", antwort.status_code)
            raise NexpaperFehler("nexpaper_nimmt_nicht")
        try:
            daten = antwort.json()
            return dict((daten.get("items") or [{}])[0])
        except (ValueError, AttributeError, IndexError, TypeError):
            return {}
    raise NexpaperFehler("nexpaper_nicht_verbunden")  # pragma: no cover - die Schleife endet oben


__all__ = ["NexpaperFehler", "TRANSPORT", "senden"]
