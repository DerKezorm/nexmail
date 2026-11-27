"""Ein Anhang als Dokument an nexpaper (Durchgang „Module“, Runde 2, V19: nexmail ist Gast mit ``documents.add``).

Nur über eine per „Verbinden“ gemachte Verbindung (Modul verbinden 0.1.2): nexmail holt Adresse und frisches Token der
Verbindung (``verbinden_store.zugriff``) und lädt die Datei mit eigenem Klient hoch, weil ``nexverbinden.call`` nur JSON
schickt. nexpaper legt das Dokument in den Tresor, den es ab Werk nimmt (bzw. den einzigen, den die Verbindung darf).

⚠️ **Netzprüfung wie die Verbindung selbst** (``_pruefen``): das eigene Netz mit dem Haken „Verbindungen ins eigene
Netz“, mit dem auch das Verbinden ging, oder mit der Freigabe für Kalender und Webhooks; keine Weiterleitung. Bis
0.35.0 galt nur die zweite, dann klappte das Verbinden und das Ablegen meldete „nicht erreichbar“.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..meldung import Meldung
from . import nextasks, verbinden_store
from .bildvermittler import Abgelehnt, adresse_pruefen

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


def _pruefen(url: str) -> None:
    """Darf nexmail diese Adresse von nexpaper erreichen? Wie beim Verbinden von Hand (``nextasks._pruefen``), und
    zusätzlich das eigene Netz, wenn der Betreiber „Verbindungen ins eigene Netz“ erlaubt hat."""
    try:
        nextasks._pruefen(url)  # noqa: SLF001
        return
    except nextasks.NextasksFehler as fehler:
        if str(fehler) != "nextasks_adresse_im_eigenen_netz" or not verbinden_store.eigenes_netz_erlaubt():
            raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler
    try:
        adresse_pruefen(url, eigenes_netz=True)
    except Abgelehnt as fehler:
        raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler


def _anfrage(konto_id: str, methode: str, pfad: str, **mit: Any) -> httpx.Response:
    """Eine Anfrage an ``<nexpaper>/api/v1/<pfad>`` mit dem Token der Klick-Verbindung; nach einem 401 einmal mit
    frischem Token. Sagt der Karte der Verbindung, wie es ausging."""
    abgewiesen: str | None = None
    for versuch in (1, 2):
        try:
            zugang = verbinden_store.zugriff("nexpaper", konto_id, neu=versuch == 2, abgewiesen=abgewiesen)
        except verbinden_store.Unerreichbar as fehler:
            raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler
        except verbinden_store.Abgelehnt as fehler:
            raise NexpaperFehler("nexpaper_nicht_verbunden") from fehler
        try:
            if TRANSPORT is None:
                _pruefen(zugang.base.rstrip("/"))
        except NexpaperFehler:
            raise
        try:
            with httpx.Client(timeout=ZEITGRENZE, follow_redirects=False, transport=TRANSPORT) as klient:
                antwort = klient.request(
                    methode,
                    f"{zugang.base.rstrip('/')}/api/v1/{pfad}",
                    # ⚠️ Kein ``Origin``: nexpaper lehnt Anfragen aus Webseiten an /api/v1 ab.
                    headers={"Authorization": f"Bearer {zugang.token}", "User-Agent": "nexmail"},
                    **mit,
                )
        except httpx.HTTPError as fehler:
            logger.info("nexpaper was unreachable: %s", type(fehler).__name__)
            _gelaufen(konto_id, "unreachable")
            raise NexpaperFehler("nexpaper_nicht_erreichbar") from fehler
        if antwort.status_code == 401 and versuch == 1:
            abgewiesen = zugang.token  # verbinden 0.2.1 (BS1): erneuert wird nur, wenn es noch das gehaltene ist
            continue
        if antwort.status_code == 401:
            _gelaufen(konto_id, "token_invalid")
            raise NexpaperFehler("nexpaper_nicht_verbunden")
        _gelaufen(konto_id)
        return antwort
    raise NexpaperFehler("nexpaper_nicht_verbunden")  # pragma: no cover - die Schleife endet oben


def tresore(konto_id: str) -> list[dict[str, Any]]:
    """V38: die Tresore, in die die Verbindung Dokumente legen darf (``GET /api/v1/vaults``, nur die freigegebenen,
    nur mit Recht zum Ändern), als ``{"id", "name"}``."""
    antwort = _anfrage(konto_id, "GET", "vaults")
    if antwort.status_code >= 300:
        raise NexpaperFehler("nexpaper_nimmt_nicht")
    try:
        daten = antwort.json()
    except ValueError as fehler:
        raise NexpaperFehler("nexpaper_nimmt_nicht") from fehler
    raus: list[dict[str, Any]] = []
    for tresor in daten if isinstance(daten, list) else []:
        if not isinstance(tresor, dict) or not isinstance(tresor.get("id"), int):
            continue
        if tresor.get("my_right", "edit") not in ("edit", "manage"):
            continue
        raus.append({"id": tresor["id"], "name": str(tresor.get("name") or f"#{tresor['id']}")[:120]})
    return raus


def senden(konto_id: str, dateiname: str, inhalt: bytes, tresor: int | None = None) -> dict[str, Any]:
    """Die Datei an nexpaper (``POST /api/v1/documents``, Feld ``file``), in ``tresor`` oder den, den nexpaper ab Werk
    nimmt. Gibt das erste Ergebnis nexpapers zurück (``status``: ``created`` oder ``duplicate``)."""
    antwort = _anfrage(
        konto_id,
        "POST",
        "documents",
        params={"vault_id": tresor} if tresor is not None else None,
        files={"file": (dateiname or "anhang", inhalt, "application/octet-stream")},
    )
    if antwort.status_code >= 300:
        logger.info("nexpaper did not take the file: %s", antwort.status_code)
        raise NexpaperFehler("nexpaper_nimmt_nicht")
    try:
        daten = antwort.json()
        return dict((daten.get("items") or [{}])[0])
    except (ValueError, AttributeError, IndexError, TypeError):
        return {}


__all__ = ["NexpaperFehler", "TRANSPORT", "senden", "tresore"]
