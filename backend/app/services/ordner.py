"""Ordner anlegen — auf dem Server, nicht nur in nexmail.

⚠️ **Ein Ordner, den nur nexmail kennt, ist kein Ordner.** Er wäre auf dem
Telefon nicht da, und beim nächsten Abgleich verschwände er wieder, weil die
Ordnerliste vom Server die Wahrheit ist. Deshalb geht der Weg immer über
``CREATE`` beim Anbieter.

⚠️ **``SUBSCRIBE`` gehört dazu.** nexmail zeigt nur abonnierte Ordner — ein
frisch angelegter wäre sonst sofort wieder unsichtbar, und der Betreiber legt
ihn ein zweites Mal an.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models import Konto, Nachricht, Ordner
from . import imap as imapdienst, konten as kontendienst
from .abgleich import HALTER

logger = logging.getLogger("nexmail.ordner")

#: Genug für jede Ablage und kurz genug, dass die Ordnerspalte lesbar bleibt.
MAX_NAME = 100


class OrdnerFehler(RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


def name_pruefen(name: str, trenner: str) -> str:
    """Was ein Ordnername nicht sein darf.

    ⚠️ **Der Trenner ist verboten.** Wer „Haus/Rechnungen" als *einen* Namen
    eingibt, bekommt beim Server zwei Ebenen — oder eine Fehlermeldung, je
    nach Anbieter. Unterordner entstehen über die Auswahl des Elternordners,
    nicht durch Tippen eines Pfads.
    """
    sauber = name.strip()
    if not sauber:
        raise OrdnerFehler("Der Ordner braucht einen Namen.")
    if len(sauber) > MAX_NAME:
        raise OrdnerFehler(f"Der Name ist länger als {MAX_NAME} Zeichen.")
    for zeichen in (trenner, "/", "\\"):
        if zeichen and zeichen in sauber:
            raise OrdnerFehler(
                f"„{zeichen}“ darf im Namen nicht vorkommen — der Server liest es "
                "als Ebenentrenner. Für einen Unterordner wähle oben den "
                "übergeordneten Ordner aus."
            )
    return sauber


def anlegen(db: Session, konto: Konto, name: str, eltern: Ordner | None = None) -> Ordner:
    """Einen Ordner beim Anbieter anlegen und übernehmen."""
    imap_pw, _ = kontendienst.passwoerter_lesen(konto)

    with HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            trenner = _trenner(klient)
            sauber = name_pruefen(name, trenner)
            pfad = f"{eltern.pfad}{trenner}{sauber}" if eltern is not None else sauber

            if any(o.pfad == pfad for o in konto.ordner):
                raise OrdnerFehler(f"„{sauber}“ gibt es in diesem Postfach schon.")

            try:
                klient.create_folder(pfad)
            except Exception as fehler:  # noqa: BLE001
                # ⚠️ Die Meldung des Servers weiterreichen, nicht ersetzen.
                # „Ging nicht" hilft niemandem; „Mailbox already exists" schon.
                raise OrdnerFehler(
                    f"Der Server hat den Ordner nicht angelegt: {str(fehler)[:200]}"
                ) from fehler

            try:
                klient.subscribe_folder(pfad)
            except Exception as fehler:  # noqa: BLE001
                # Kein Abbruch: Der Ordner ist da. Manche Server kennen
                # Abonnements gar nicht und melden hier trotzdem einen Fehler.
                logger.info("The new folder could not be subscribed: %s", fehler)

            # Die ganze Liste neu lesen statt eine Zeile zu erfinden - so
            # stimmen Rolle, Name und Waehlbarkeit mit dem Server ueberein.
            kontendienst.ordner_uebernehmen(db, konto, imapdienst.ordner_lesen(klient))
            db.commit()
            # ⚠️ **Ohne das sieht ``konto.ordner`` den neuen Ordner nicht.**
            # Die Sitzung läuft mit ``expire_on_commit=False``; die geladene
            # Sammlung bleibt also stehen, wie sie war. ``ordner_uebernehmen``
            # legt die Zeile über ``db.add`` an, nicht über die Beziehung -
            # der Unterschied fällt genau hier auf die Füße.
            db.refresh(konto)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    neuer = next((o for o in konto.ordner if o.pfad == pfad), None)
    if neuer is None:
        raise OrdnerFehler(
            "Der Ordner wurde angelegt, taucht aber nicht in der Ordnerliste des "
            "Servers auf. Ein Abgleich sollte ihn nachliefern."
        )
    logger.info("A folder was created.")
    return neuer


def _trenner(klient) -> str:
    """Womit dieser Server Ebenen trennt — meist ``/``, bei manchen ``.``.

    ⚠️ **Nicht raten.** All-Inkl trennt mit ``.``, Gmail mit ``/``; wer den
    falschen nimmt, legt einen Ordner an, der wörtlich „Haus/Rechnungen"
    heißt, statt einen Unterordner.
    """
    try:
        for _kennzeichen, trenner, _pfad in klient.list_folders():
            if trenner:
                return trenner.decode() if isinstance(trenner, bytes) else str(trenner)
    except Exception:  # noqa: BLE001
        pass
    return "/"


#: Ordner, die nexmail braucht. ⚠️ Wer seinen Papierkorb löscht, hat danach
#: keinen — und jedes Löschen einer Mail scheitert mit einer Meldung, die
#: niemand mit dieser Handlung in Verbindung bringt.
GESCHUETZTE_ROLLEN = ("posteingang", "gesendet", "entwuerfe", "papierkorb", "junk", "archiv")


def entfernen(db: Session, konto: Konto, ordner: Ordner) -> int:
    """Einen Ordner beim Anbieter löschen — mit allem, was darin liegt.

    ⚠️ **Ohne Rückweg.** Anders als beim Verschieben gibt es hier keine
    Wiederherstellung: Der Server wirft den Ordner samt Inhalt weg. Die
    Oberfläche fragt deshalb nach und nennt die Zahl der Nachrichten.

    Gibt zurück, wie viele Nachrichten mitgegangen sind.
    """
    if ordner.rolle in GESCHUETZTE_ROLLEN:
        raise OrdnerFehler(
            f"„{ordner.name}“ ist ein Ordner, den nexmail braucht. Er lässt sich "
            "nicht entfernen."
        )

    unterordner = [o for o in konto.ordner if o.pfad.startswith(ordner.pfad) and o.id != ordner.id]
    if unterordner:
        raise OrdnerFehler(
            f"„{ordner.name}“ hat noch Unterordner. Entferne die zuerst — sonst "
            "verschwinden sie mit, ohne dass jemand danach gefragt hat."
        )

    anzahl = db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id).count()
    pfad = ordner.pfad

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            try:
                klient.unsubscribe_folder(pfad)
            except Exception as fehler:  # noqa: BLE001
                logger.info("The folder could not be unsubscribed: %s", fehler)
            try:
                klient.delete_folder(pfad)
            except Exception as fehler:  # noqa: BLE001
                raise OrdnerFehler(
                    f"Der Server hat den Ordner nicht entfernt: {str(fehler)[:200]}"
                ) from fehler

            kontendienst.ordner_uebernehmen(db, konto, imapdienst.ordner_lesen(klient))
            db.commit()
            db.refresh(konto)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    logger.warning("Folder %s was deleted with %s message(s).", pfad, anzahl)
    return anzahl


def umbenennen(db: Session, konto: Konto, ordner: Ordner, name: str) -> Ordner:
    """Einen Ordner beim Anbieter umbenennen.

    ⚠️ **``RENAME`` nimmt die Unterordner mit.** Das ist im IMAP-Protokoll so
    vorgesehen und richtig — aber es heißt, dass sich hier mehr ändert als die
    eine Zeile. Deshalb wird danach die ganze Ordnerliste neu gelesen statt
    ein Feld überschrieben.

    ⚠️ **Sonderordner nicht.** Ihre Rolle hängt bei manchen Servern am Namen;
    ein umbenannter „Papierkorb" wäre danach ein gewöhnlicher Ordner, und das
    Löschen einer Mail fände sein Ziel nicht mehr.
    """
    if ordner.rolle in GESCHUETZTE_ROLLEN:
        raise OrdnerFehler(
            f"„{ordner.name}“ ist ein Ordner, den nexmail braucht. Sein Name liegt fest."
        )

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            trenner = _trenner(klient)
            sauber = name_pruefen(name, trenner)
            if sauber == ordner.name:
                return ordner

            # Der Ordner bleibt, wo er ist - nur der letzte Teil des Pfades
            # wechselt. Verschieben ist eine andere Handlung.
            teile = ordner.pfad.split(trenner)
            neuer_pfad = trenner.join([*teile[:-1], sauber]) if len(teile) > 1 else sauber

            if any(o.pfad == neuer_pfad for o in konto.ordner):
                raise OrdnerFehler(f"„{sauber}“ gibt es an dieser Stelle schon.")

            try:
                klient.rename_folder(ordner.pfad, neuer_pfad)
            except Exception as fehler:  # noqa: BLE001
                raise OrdnerFehler(
                    f"Der Server hat den Ordner nicht umbenannt: {str(fehler)[:200]}"
                ) from fehler

            try:
                klient.subscribe_folder(neuer_pfad)
            except Exception as fehler:  # noqa: BLE001
                logger.info("The renamed folder could not be subscribed: %s", fehler)

            kontendienst.ordner_uebernehmen(db, konto, imapdienst.ordner_lesen(klient))
            db.commit()
            db.refresh(konto)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    neuer = next((o for o in konto.ordner if o.pfad == neuer_pfad), None)
    if neuer is None:
        raise OrdnerFehler(
            "Der Ordner wurde umbenannt, taucht aber nicht in der Ordnerliste des "
            "Servers auf. Ein Abgleich sollte ihn nachliefern."
        )
    logger.info("A folder was renamed.")
    return neuer


__all__ = [
    "GESCHUETZTE_ROLLEN",
    "MAX_NAME",
    "OrdnerFehler",
    "anlegen",
    "entfernen",
    "name_pruefen",
    "umbenennen",
]
