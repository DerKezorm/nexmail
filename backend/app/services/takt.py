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

_sicherungsfaden: threading.Thread | None = None
_sicherung_halt = threading.Event()

_versandfaden: threading.Thread | None = None
_versand_halt = threading.Event()

_aufraeumfaden: threading.Thread | None = None
_aufraeumen_halt = threading.Event()

_wiedervorlagefaden: threading.Thread | None = None
_wiedervorlage_halt = threading.Event()

#: Wie oft nach faelligen geplanten Sendungen gesehen wird. Eine Minute:
#: Der Zeitpunkt wird auf die Minute eingestellt - viel spaeter als eine
#: Minute darf „18:00" nicht hinausgehen.
VERSANDPLAN_NACHSEHEN_SEKUNDEN = 60


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


def _sicherungsschleife() -> None:
    """Der Zeitplan für Rücksetzpunkte — ein eigener Faden.

    ⚠️ **Bewusst nicht im Abgleich-Takt.** Der laesst sich mit
    ``NEXMAIL_TAKT_SEKUNDEN=0`` abschalten, und wer das tut, meint „nicht
    dauernd Post holen" — nicht „keine Sicherungen mehr". Haengte der Zeitplan
    daran, verschwaende er lautlos, und man merkte es an dem Tag, an dem man
    eine Sicherung braucht.
    """
    from . import sicherungsliste

    while not _sicherung_halt.wait(sicherungsliste.NACHSEHEN_SEKUNDEN):
        try:
            if sicherungsliste.wenn_faellig():
                logger.info("A scheduled restore point was created.")
        except Exception as fehler:  # noqa: BLE001
            logger.warning("The backup schedule failed a round: %s", fehler)


def sicherungsplan_starten() -> None:
    global _sicherungsfaden

    if _sicherungsfaden is not None and _sicherungsfaden.is_alive():
        return
    _sicherung_halt.clear()
    _sicherungsfaden = threading.Thread(
        target=_sicherungsschleife, name="nexmail-sicherungen", daemon=True
    )
    _sicherungsfaden.start()


def _versandschleife() -> None:
    """Der Versandplan — schickt Geplantes hinaus, sobald es faellig ist.

    ⚠️ **Ein eigener Faden, bewusst nicht im Abgleich-Takt.** Derselbe Grund
    wie beim Sicherungsplan: ``NEXMAIL_TAKT_SEKUNDEN=0`` heisst „nicht dauernd
    Post holen" - nicht „geplante Mails gehen nie hinaus". Hinge der Plan am
    Takt, laege eine fuer 18:00 geplante Mail am naechsten Morgen noch da.
    """
    from ..db import SessionLocal
    from . import senden as sendedienst

    while not _versand_halt.wait(VERSANDPLAN_NACHSEHEN_SEKUNDEN):
        try:
            with SessionLocal() as db:
                sendedienst.faellige_geplante(db)
        except Exception as fehler:  # noqa: BLE001
            # Der Faden darf nie sterben - sonst bleibt Geplantes still
            # liegen, und niemand merkt es vor dem Nachfragen des Empfaengers.
            logger.warning("The scheduled-send check failed a round: %s", fehler)


def versandplan_starten() -> None:
    global _versandfaden

    if _versandfaden is not None and _versandfaden.is_alive():
        return
    _versand_halt.clear()
    _versandfaden = threading.Thread(
        target=_versandschleife, name="nexmail-versandplan", daemon=True
    )
    _versandfaden.start()


def _aufraeumschleife() -> None:
    """Papierkorb und Junk nach der eingestellten Aufbewahrung leeren.

    ⚠️ **Ein eigener Faden, bewusst nicht im Abgleich-Takt** — derselbe Grund
    wie beim Sicherungs- und Versandplan: ``NEXMAIL_TAKT_SEKUNDEN=0`` heisst
    „nicht dauernd Post holen", nicht „der Papierkorb waechst wieder ewig".
    Ob und wie oft je Benutzer geraeumt wird, entscheidet der Dienst selbst
    (hoechstens einmal am Tag, Merker ``aufraeumen_zuletzt``).
    """
    from . import aufraeumen

    while not _aufraeumen_halt.wait(aufraeumen.NACHSEHEN_SEKUNDEN):
        try:
            aufraeumen.runde()
        except Exception as fehler:  # noqa: BLE001
            # Der Faden darf nie sterben - sonst hoert das Aufraeumen still
            # auf, und der Papierkorb waechst, obwohl eine Zahl eingestellt ist.
            logger.warning("The auto-clean check failed a round: %s", fehler)


def aufraeumplan_starten() -> None:
    global _aufraeumfaden

    if _aufraeumfaden is not None and _aufraeumfaden.is_alive():
        return
    _aufraeumen_halt.clear()
    _aufraeumfaden = threading.Thread(
        target=_aufraeumschleife, name="nexmail-aufraeumen", daemon=True
    )
    _aufraeumfaden.start()


def _wiedervorlageschleife() -> None:
    """Die Wiedervorlage — legt Faelliges zurueck, sobald die Zeit da ist.

    ⚠️ **Ein eigener Faden, bewusst nicht im Abgleich-Takt.** Derselbe Grund
    wie beim Versandplan: ``NEXMAIL_TAKT_SEKUNDEN=0`` heisst „nicht dauernd
    Post holen" — nicht „weggelegte Mails kommen nie zurueck". Hinge das
    Aufwachen am Takt, laege eine fuer 18:00 weggelegte Mail am naechsten
    Morgen noch im Wiedervorlage-Ordner.
    """
    from . import wiedervorlage

    while not _wiedervorlage_halt.wait(wiedervorlage.NACHSEHEN_SEKUNDEN):
        try:
            wiedervorlage.runde()
        except Exception as fehler:  # noqa: BLE001
            # Der Faden darf nie sterben - sonst wacht nichts mehr auf, und
            # niemand merkt es, bis eine Mail zu spaet wieder auffaellt.
            logger.warning("The snooze check failed a round: %s", fehler)


def wiedervorlage_starten() -> None:
    global _wiedervorlagefaden

    if _wiedervorlagefaden is not None and _wiedervorlagefaden.is_alive():
        return
    _wiedervorlage_halt.clear()
    _wiedervorlagefaden = threading.Thread(
        target=_wiedervorlageschleife, name="nexmail-wiedervorlage", daemon=True
    )
    _wiedervorlagefaden.start()


def anhalten() -> None:
    _wiedervorlage_halt.set()
    _aufraeumen_halt.set()
    _versand_halt.set()
    _sicherung_halt.set()
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


__all__ = [
    "anhalten",
    "aufraeumplan_starten",
    "einmal",
    "laeuft",
    "starten",
    "versandplan_starten",
    "wiedervorlage_starten",
]
