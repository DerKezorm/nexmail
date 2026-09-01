"""Entwürfe — im Postfach, nicht nur im Browser.

⚠️ **Ein Entwurf, der nur im Browser lebt, ist kein Entwurf.** Er überlebt kein
geschlossenes Fenster, keinen Neustart und ist auf dem Telefon nie zu sehen.
Wer eine halbe Mail zurücklässt und sie abends auf dem Sofa weiterschreiben
will, findet nichts. Deshalb geht jeder Entwurf denselben Weg wie eine
gesendete Mail: ``APPEND`` in den Entwurfsordner des Anbieters, danach
Abgleich in die eigene Datenbank.

Die Reihenfolge beim Ersetzen ist absichtlich so:

    1. neue Fassung **anlegen**
    2. alte Fassung wegwerfen
    3. Ordner abgleichen

⚠️ **Erst anlegen, dann wegwerfen.** Umgekehrt kostet ein Absturz dazwischen
den ganzen Text. So ist der schlimmste Fall eine Fassung zu viel — ärgerlich,
aber nichts ist weg.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Konto, Nachricht, Ordner
from . import abgleich, imap as imapdienst, konten as kontendienst
from .verfassen import Entwurf, bauen

logger = logging.getLogger("nexmail.entwuerfe")


class EntwurfFehler(RuntimeError):
    """Etwas, das der Betreiber lesen soll — kein Programmfehler."""


def _ordner(konto: Konto) -> Ordner:
    ordner = next((o for o in konto.ordner if o.rolle == "entwuerfe"), None)
    if ordner is None:
        raise EntwurfFehler(
            "Dieses Postfach hat keinen Entwurfsordner. Lege ihn auf dem Server "
            "an — dann bewahrt nexmail angefangene Nachrichten dort auf."
        )
    return ordner


def ablegen(
    db: Session, konto: Konto, entwurf: Entwurf, ersetzt_uid: int | None = None
) -> int:
    """Einen Entwurf im Postfach ablegen und die alte Fassung wegräumen.

    Gibt die UID der neuen Fassung zurück — die Oberfläche gibt sie beim
    nächsten Speichern als ``ersetzt_uid`` wieder mit, sonst sammeln sich
    Fassungen an.
    """
    ordner = _ordner(konto)
    roh, _ = bauen(entwurf)

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.verbinden(
            konto.imap_server,
            konto.imap_port,
            konto.imap_sicherheit,
            konto.imap_benutzer,
            imap_pw,
        )
        try:
            # ⚠️ ``\Draft`` ist das, woran jeder andere Client erkennt, dass
            # das kein fertiger Brief ist. Ohne die Kennzeichnung zeigt
            # Thunderbird einen Entwurf als gewoehnliche Nachricht und bietet
            # kein Weiterschreiben an.
            klient.append(ordner.pfad, roh, [rb"\Draft", rb"\Seen"], datetime.now(timezone.utc))

            if ersetzt_uid:
                _alte_fassung_wegwerfen(klient, ordner, ersetzt_uid)

            abgleich.ordner_abgleichen(klient, db, konto, ordner)
            db.commit()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    # Die neue UID steht jetzt in der Datenbank - der Abgleich hat sie geholt.
    # Sie aus der APPEND-Antwort zu lesen waere schoener, aber laengst nicht
    # jeder Server schickt eine (das braucht UIDPLUS).
    neue = db.execute(
        select(func.max(Nachricht.uid)).where(Nachricht.ordner_id == ordner.id)
    ).scalar()
    logger.info("A draft was stored in the mailbox.")
    return int(neue or 0)


def _alte_fassung_wegwerfen(klient, ordner: Ordner, uid: int) -> None:
    """Die vorige Fassung entfernen — und scheitern, ohne alles mitzureißen.

    ⚠️ **Ein Fehler hier darf den Entwurf nicht kosten.** Die neue Fassung
    liegt zu diesem Zeitpunkt schon auf dem Server. Bleibt die alte stehen,
    sieht der Betreiber eine Fassung zu viel; wer hier abbricht, nimmt ihm
    stattdessen den gerade geschriebenen Text.
    """
    try:
        klient.select_folder(ordner.pfad)
        klient.add_flags([uid], [rb"\Deleted"])
        try:
            klient.uid_expunge([uid])
        except Exception:  # noqa: BLE001
            logger.info("Server has no UID EXPUNGE; the old draft stays flagged as deleted.")
    except Exception as fehler:  # noqa: BLE001
        logger.warning("The previous draft version could not be removed: %s", fehler)


def wegwerfen(db: Session, konto: Konto, uid: int) -> None:
    """Einen Entwurf endgültig entfernen — beim Senden oder beim Verwerfen.

    ⚠️ **Das gehört ans Ende eines erfolgreichen Versands.** Sonst steht die
    Mail zweimal im Postfach: einmal in „Gesendet" und einmal als Entwurf, den
    niemand mehr braucht.
    """
    ordner = _ordner(konto)
    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.verbinden(
            konto.imap_server,
            konto.imap_port,
            konto.imap_sicherheit,
            konto.imap_benutzer,
            imap_pw,
        )
        try:
            _alte_fassung_wegwerfen(klient, ordner, uid)
            abgleich.ordner_abgleichen(klient, db, konto, ordner)
            db.commit()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["EntwurfFehler", "ablegen", "wegwerfen"]
