"""Die Postfachwache: neue Post sofort sehen, über IMAP IDLE (RFC 2177).

⚠️ **Eine bewusste Ausnahme von „eine Verbindung je Postfach".** ``takt.py``
legt dar, warum nexmail sonst kurz aufmacht und wieder auflegt. Die Wache hält
dagegen eine zweite Verbindung offen, und mancher Anbieter wirft ab einer
bestimmten Zahl heraus. Deshalb gilt:

* **Je Postfach und ab Werk aus** (``Konto.idle_aktiv``). Wer es nicht
  einschaltet, hat keine zweite Verbindung.
* **Die Wache holt keine Post.** Sie meldet nur, dass etwas da ist. Geholt wird
  über ``abgleich.konto_abgleichen``, also derselbe Weg mit Schloss, Regeln und
  Meldungen. Zuvor legt sie auf, damit dabei nicht zwei Verbindungen offen sind.
* **Der Takt bleibt das Netz darunter.** Stirbt die Wache oder kann der Server
  kein IDLE, kommt die Post mit dem nächsten Takt wie immer.
* ``NEXMAIL_TAKT_SEKUNDEN=0`` heißt „nicht dauernd Post holen", also keine Wache.

⚠️ **Nur ``EXISTS``.** Eine geänderte Markierung (``FETCH``) oder ein Löschen
(``EXPUNGE``) ist keine neue Post, und jede eigene Handlung löste es aus. Das
zieht der Takt nach.
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import Konto
from . import abgleich, imap as imapdienst
from .protokoll import adresse_kuerzen as kurz

logger = logging.getLogger("nexmail.wache")

#: Nach so vielen Sekunden wird IDLE erneuert. RFC 2177 erlaubt knapp 30 Minuten.
#: ⚠️ **Neun, nicht 29.** Eine Verbindung, die ein Router still gekappt hat,
#: meldet nichts. Erst das Erneuern zeigt es, und Heimrouter vergessen ruhige
#: Verbindungen oft nach zehn Minuten.
ERNEUERN_SEKUNDEN = 9 * 60

#: Wie lange ein Blick auf die Leitung dauert: so schnell hört die Wache auf.
LAUSCHEN_SEKUNDEN = 5.0

#: Mehrere Mails kommen oft zusammen. So lange wird nach der ersten gesammelt.
SAMMELN_SEKUNDEN = 2.0

#: ⚠️ **Der Abstand zwischen zwei Abgleichen.** Jeder kostet eine Anmeldung;
#: ein Postfach, das minütlich Post bekommt, soll den Server nicht beschäftigen.
MINDESTABSTAND_SEKUNDEN = 20.0

#: Warten nach einem Fehlschlag, verdoppelt bis zur Obergrenze.
PAUSE_SEKUNDEN = 30.0
PAUSE_HOECHSTENS = 15 * 60.0

#: So oft sieht die Wache nach, welche Postfächer sie halten soll.
RUNDBLICK_SEKUNDEN = 60.0

#: Was ``_lauschen`` als Grund zurückgibt.
NEUE_POST = "neue_post"
ERNEUERN = "erneuern"
KEIN_IDLE = "kein_idle"
NICHT_MEHR = "nicht_mehr"

#: Was die Oberfläche zu einem Postfach zeigt. Leer heißt: keine Wache.
LAUSCHT = "lauscht"
GETRENNT = "getrennt"

_halt = threading.Event()
_nachsehen = threading.Event()
_rundblick: threading.Thread | None = None
_faeden: dict[str, tuple[threading.Thread, threading.Event]] = {}
_zustaende: dict[str, str] = {}


class LeitungWeg(Exception):
    """Die Verbindung ist tot, ohne dass ein Befehl gescheitert wäre."""


def zustand(konto_id: str) -> str:
    return _zustaende.get(konto_id, "")


def _neue_post(antworten: list) -> bool:
    """``(12, b"EXISTS")`` unter den Antworten des Servers?"""
    return any(
        isinstance(a, tuple) and len(a) >= 2 and a[1] == b"EXISTS" for a in antworten
    )


def _kann_idle(klient) -> bool:
    return any(k.upper() == "IDLE" for k in imapdienst.faehigkeiten(klient))


def _lauschen(konto_id: str, halt: threading.Event) -> str:
    """Einmal anmelden und warten, bis es einen Grund gibt aufzuhören.

    ⚠️ **Keine Sitzung während des Wartens.** Sie gälte Stunden, und eine
    offene Transaktion hielte SQLites Protokolldatei am Wachsen.
    """
    with SessionLocal() as db:
        konto = db.get(Konto, konto_id)
        if konto is None or not (konto.aktiv and konto.idle_aktiv):
            return NICHT_MEHR
        eingang = next((o.pfad for o in konto.ordner if o.rolle == "posteingang"), "")
        if not eingang:
            # Der erste Abgleich steht noch aus; der Takt legt die Ordner an.
            raise LeitungWeg("no inbox yet")
        klient = imapdienst.fuer_konto(db, konto)

    try:
        if not _kann_idle(klient):
            return KEIN_IDLE
        klient.select_folder(eingang, readonly=True)
        klient.idle()
        _zustaende[konto_id] = LAUSCHT
        try:
            ende = time.monotonic() + ERNEUERN_SEKUNDEN
            while not halt.is_set() and time.monotonic() < ende:
                beginn = time.monotonic()
                antworten = klient.idle_check(timeout=LAUSCHEN_SEKUNDEN)
                if _neue_post(antworten):
                    klient.idle_check(timeout=SAMMELN_SEKUNDEN)
                    return NEUE_POST
                # ⚠️ **Eine leere Antwort vor der Zeit heißt: Leitung zu.**
                # ``idle_check`` schluckt das Dateiende und kehrt sofort
                # zurück. Ohne diese Prüfung kreiste die Schleife neun Minuten
                # lang mit voller Last.
                if not antworten and time.monotonic() - beginn < LAUSCHEN_SEKUNDEN / 2:
                    raise LeitungWeg("connection closed")
            return ERNEUERN
        finally:
            # Scheitert das, ist die Leitung ohnehin hin: Es wird neu verbunden.
            try:
                klient.idle_done()
            except Exception:  # noqa: BLE001
                logger.debug("IDLE could not be ended cleanly.")
    finally:
        try:
            klient.logout()
        except Exception:  # noqa: BLE001
            try:
                klient.shutdown()
            except Exception:  # noqa: BLE001
                pass


def _abgleichen(konto_id: str) -> None:
    """Die neue Post holen, auf dem gewöhnlichen Weg, nur den Posteingang."""
    with SessionLocal() as db:
        konto = db.get(Konto, konto_id)
        if konto is not None:
            abgleich.konto_abgleichen(db, konto, nur_posteingang=True)


def _wachen(konto_id: str, adresse: str, halt: threading.Event) -> None:
    """Der Faden eines Postfachs.

    ⚠️ **Er darf nicht sterben, und er darf nicht drängeln.** Jeder Fehlschlag
    verdoppelt die Pause: Ein Server, der eine Anmeldung abweist, sperrt
    Absender, die es im Sekundentakt wieder versuchen.
    """
    pause = PAUSE_SEKUNDEN
    while not halt.is_set():
        try:
            grund = _lauschen(konto_id, halt)
            if grund == NICHT_MEHR:
                break
            if grund == KEIN_IDLE:
                # ⚠️ **Der Merker bleibt stehen**, damit der Rundblick es nicht
                # jede Minute neu versucht und die Oberfläche es sagen kann.
                logger.info("%s does not support IDLE; the regular sync stays.", kurz(adresse))
                _zustaende[konto_id] = KEIN_IDLE
                return
            pause = PAUSE_SEKUNDEN
            if grund == NEUE_POST:
                _abgleichen(konto_id)
                halt.wait(MINDESTABSTAND_SEKUNDEN)
        except Exception as fehler:  # noqa: BLE001
            _zustaende[konto_id] = GETRENNT
            logger.info(
                "IDLE on %s stopped (%s); trying again in %.0f s.",
                kurz(adresse),
                type(fehler).__name__,
                pause,
            )
            halt.wait(pause)
            pause = min(pause * 2, PAUSE_HOECHSTENS)
    if _zustaende.get(konto_id) != KEIN_IDLE:
        _zustaende.pop(konto_id, None)


def rundblick() -> None:
    """Fäden starten und stoppen, wie es die Datenbank sagt."""
    with SessionLocal() as db:
        gewollt = {
            konto.id: konto.adresse
            for konto in db.scalars(
                select(Konto).where(Konto.aktiv.is_(True), Konto.idle_aktiv.is_(True))
            )
        }

    for konto_id in [k for k in _zustaende if k not in gewollt]:
        if _zustaende.get(konto_id) == KEIN_IDLE:
            del _zustaende[konto_id]
    for konto_id, (faden, halt) in list(_faeden.items()):
        if konto_id not in gewollt:
            halt.set()
        if not faden.is_alive():
            del _faeden[konto_id]

    for konto_id, adresse in gewollt.items():
        if konto_id in _faeden or _zustaende.get(konto_id) == KEIN_IDLE:
            continue
        halt = threading.Event()
        faden = threading.Thread(
            target=_wachen,
            args=(konto_id, adresse, halt),
            name=f"nexmail-wache-{konto_id[:8]}",
            daemon=True,
        )
        _faeden[konto_id] = (faden, halt)
        faden.start()


def _rundblick_schleife() -> None:
    while not _halt.is_set():
        try:
            rundblick()
        except Exception:  # noqa: BLE001
            logger.exception("The mailbox watch could not be updated.")
        _nachsehen.wait(RUNDBLICK_SEKUNDEN)
        _nachsehen.clear()


def nachsehen() -> None:
    """Nach einer Änderung am Postfach sofort, nicht erst in einer Minute."""
    _nachsehen.set()


def starten() -> None:
    global _rundblick

    if get_settings().takt_sekunden <= 0:
        return
    if _rundblick is not None and _rundblick.is_alive():
        return
    _halt.clear()
    _rundblick = threading.Thread(target=_rundblick_schleife, name="nexmail-wache", daemon=True)
    _rundblick.start()


def anhalten() -> None:
    _halt.set()
    _nachsehen.set()
    for _, halt in list(_faeden.values()):
        halt.set()


__all__ = ["anhalten", "nachsehen", "rundblick", "starten", "zustand"]
