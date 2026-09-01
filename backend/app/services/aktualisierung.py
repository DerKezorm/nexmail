"""Nachsehen, ob es eine neuere Fassung von nexmail gibt.

Hoechstens einmal am Tag wird die oeffentliche GitHub-Schnittstelle nach der
neuesten Veroeffentlichung gefragt. Uebertragen wird nichts ausser der Anfrage
selbst — keine Adressen, keine Einstellungen, keine Betreffzeilen.

⚠️ **Das ist die einzige Stelle, an der nexmail von sich aus hinausruft**, und
sie widerspricht dem eigenen Grundsatz: Die Schriften liegen im Abbild, damit
die Anwendung beim Oeffnen niemanden anfunkt. Deshalb steht der Schalter auf
der Ueber-Seite selbst — dort, wo auch das Ergebnis erscheint — und deshalb
sagt die Seite in einem Satz, was hinausgeht. Wer ihn ausschaltet, sieht nur
noch den Knopf „Jetzt pruefen".

⚠️ **Die Pruefung ist Beiwerk.** Faellt GitHub aus, fehlt das Netz oder
antwortet die Schnittstelle mit einem Fehler, darf davon nichts in der
Oberflaeche kaputtgehen — dann steht dort einfach nichts. Uebernommen aus
Nexview (``services/updates.py``), samt dieser Regel.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .. import __version__

logger = logging.getLogger("nexmail.aktualisierung")

REPO = "DerKezorm/nexmail"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
PROJEKTSEITE = "https://nexmail.nexapps.dev"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

#: Hoechstens einmal am Tag. GitHub erlaubt ohne Anmeldung 60 Anfragen je
#: Stunde und Adresse — davon sind wir damit weit entfernt.
ABSTAND = timedelta(hours=24)

#: Kurze Zeitgrenze: Die Ueber-Seite soll nicht auf GitHub warten muessen.
ZEITGRENZE = httpx.Timeout(6.0, connect=4.0)

_MUSTER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Stand:
    jetzige: str
    neueste: str | None = None
    neuer_da: bool = False
    geprueft_am: datetime | None = None
    release_adresse: str = RELEASES_URL


#: Zwischenspeicher im Arbeitsspeicher. Ein Neustart fuehrt zu einer neuen
#: Abfrage — das ist selten genug und spart eine Tabelle.
_gemerkt: Stand | None = None
_schloss = asyncio.Lock()


def zerlegen(text: str) -> tuple[int, int, int] | None:
    """``"v1.2.3"`` -> ``(1, 2, 3)``; alles Unverstaendliche -> ``None``."""
    treffer = _MUSTER.match((text or "").strip())
    if not treffer:
        return None
    return int(treffer.group(1)), int(treffer.group(2)), int(treffer.group(3))


def ist_neuer(neueste: str, jetzige: str) -> bool:
    """⚠️ Verglichen werden Zahlen, nicht Zeichenketten.

    ``"0.10.0" > "0.9.0"`` ist als Text **falsch** — und der Fehler faellt
    genau einmal auf, naemlich bei der zehnten Nebenfassung.
    """
    a, b = zerlegen(neueste), zerlegen(jetzige)
    if a is None or b is None:
        return False
    return a > b


async def _abfragen() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=ZEITGRENZE) as klient:
            antwort = await klient.get(
                API_URL, headers={"accept": "application/vnd.github+json"}
            )
            antwort.raise_for_status()
            return str(antwort.json().get("tag_name") or "") or None
    except Exception as fehler:  # noqa: BLE001
        # ⚠️ **Jede Ausnahme**, nicht eine Liste von Namen. In Nexview lief
        # ``httpx.InvalidURL`` an einem ``httpx.HTTPError`` vorbei und riss
        # eine ganze Seite mit. Eine misslungene Nebensache darf nichts
        # kaputtmachen.
        logger.info("The update check did not get through: %s", fehler)
        return None


async def stand(*, an: bool = True, erzwingen: bool = False) -> Stand:
    """Der letzte bekannte Stand — bei Bedarf frisch geholt."""
    global _gemerkt

    if not an and not erzwingen:
        return Stand(jetzige=__version__)

    jetzt = datetime.now(timezone.utc)
    async with _schloss:
        frisch_genug = (
            _gemerkt is not None
            and _gemerkt.geprueft_am is not None
            and jetzt - _gemerkt.geprueft_am < ABSTAND
        )
        if frisch_genug and not erzwingen:
            return _gemerkt  # type: ignore[return-value]

        neueste = await _abfragen()
        _gemerkt = Stand(
            jetzige=__version__,
            neueste=neueste,
            neuer_da=bool(neueste) and ist_neuer(neueste or "", __version__),
            geprueft_am=jetzt,
        )
        return _gemerkt


def zuruecksetzen() -> None:
    """Nur fuer Tests."""
    global _gemerkt
    _gemerkt = None
