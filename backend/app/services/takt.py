"""Der Takt — nexmail sieht von selbst nach neuer Post.

⚠️ **Kurz aufmachen, nicht offen halten.** ``IDLE`` wäre schneller, hielte
aber je Postfach eine Verbindung dauerhaft belegt — bei iCloud ist das die
einzige, die es überhaupt gibt, und jede Handlung des Betreibers müsste sie
erst unterbrechen. Der Takt macht die Verbindung auf, gleicht ab und legt
wieder auf; dieselbe Verbindung, die auch ein Klick auf „Aktualisieren"
benutzt, und dasselbe Schloss.

⚠️ **Nur der Posteingang.** Ein voller Durchlauf über alle Ordner kostet bei
einem großen Postfach Sekunden — alle zwei Minuten wäre das eine dauerhafte
Last für nichts. Neue Post kommt in den Posteingang; alles andere holt der
Abgleich von Hand oder beim Öffnen des Ordners.

⚠️ **Ein Postfach, das klemmt, hält den Takt nicht auf.** Sonst bringt ein
falsch eingetragener Server alle anderen zum Stillstand.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import Konto

logger = logging.getLogger("nexmail.takt")

_faden: threading.Thread | None = None
_halt = threading.Event()


def laeuft() -> bool:
    return _faden is not None and _faden.is_alive()


def starten() -> None:
    """Den Takt anwerfen. Bei ``takt_sekunden = 0`` passiert nichts."""
    global _faden

    takt = get_settings().takt_sekunden
    if takt <= 0:
        logger.info("Background sync is off (NEXMAIL_TAKT=0).")
        return
    if laeuft():
        return

    _halt.clear()
    _faden = threading.Thread(target=_schleife, args=(takt,), name="nexmail-takt", daemon=True)
    _faden.start()
    logger.info("Background sync every %s seconds.", takt)


def anhalten() -> None:
    _halt.set()


def _schleife(takt: int) -> None:
    # ⚠️ **Erst warten, dann arbeiten.** Beim Start läuft ohnehin schon genug
    # (Schemapflege, Warteschlange); ein Abgleich obendrauf verzögert die
    # erste Antwort des Servers.
    while not _halt.wait(takt):
        try:
            einmal()
        except Exception as fehler:  # noqa: BLE001
            # Der Faden darf nie sterben - sonst hört nexmail still auf,
            # nach Post zu sehen, und niemand merkt es.
            logger.warning("A background sync round failed: %s", fehler)


def einmal() -> dict[str, int]:
    """Eine Runde: jedes Postfach einmal, nur der Posteingang."""
    from . import abgleich

    from . import protokoll

    stand = {"postfaecher": 0, "neu": 0, "gescheitert": 0}
    with SessionLocal() as db:
        # ⚠️ **Hier läuft die Selbstabschaltung der Protokollstufe.** Sie
        # braucht einen regelmäßigen Puls; einen eigenen Faden dafür wäre ein
        # zweiter, der dasselbe tut.
        protokoll.ablauf_pruefen(db)

        konten = db.execute(select(Konto).where(Konto.aktiv.is_(True))).scalars().all()
        for konto in konten:
            if _halt.is_set():
                break
            stand["postfaecher"] += 1
            try:
                runden = abgleich.konto_abgleichen(db, konto, nur_posteingang=True)
                stand["neu"] += sum(r.neu for r in runden.values())
            except Exception as fehler:  # noqa: BLE001
                stand["gescheitert"] += 1
                logger.info("Background sync skipped %s: %s", konto.adresse, fehler)
    if stand["neu"]:
        logger.info("Background sync brought %s new message(s).", stand["neu"])
    return stand


__all__ = ["anhalten", "einmal", "laeuft", "starten"]
