"""Nachrichten verschieben, archivieren, löschen.

⚠️ **Alles hier verändert etwas auf dem Server.** Eine Anwendung, die eine
Mail nur lokal wegräumt, macht ihrem Besitzer etwas vor: Auf dem Telefon liegt
sie weiter im Posteingang, und beim nächsten Abgleich springt sie hier zurück.
Deshalb gilt durchgehend: **erst der Server, dann die eigene Datenbank.**

⚠️ **``MOVE`` ist nicht überall da.** Der Befehl stammt aus RFC 6851 und fehlt
in älteren Servern. Ohne Rückfallebene funktioniert das Verschieben dann bei
manchen Postfächern und bei anderen nicht — deshalb wird die Fähigkeitenliste
gefragt und sonst der alte Weg gegangen: kopieren, das Original als gelöscht
markieren, aufräumen.

⚠️ **Verschoben wird nur innerhalb eines Postfachs.** Eine Mail aus dem
GMX-Konto in den iCloud-Papierkorb zu schieben, ginge auf einem echten Server
gar nicht — und in einer Oberfläche, die es anbietet, sähe es aus, als ginge
es.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Konto, Nachricht, Ordner, utcnow
from . import abgleich, imap as imapdienst, konten as kontendienst

logger = logging.getLogger("nexmail.handeln")


class HandelnFehler(RuntimeError):
    pass


@dataclass
class Rueckweg:
    """Was nötig ist, um einen Zug zurückzunehmen.

    ⚠️ **Gemerkt wird die ``Message-ID``, nicht die UID.** Beim Verschieben
    vergibt der Zielordner eine neue Nummer, und die alte gilt dort nicht.
    Über die ``Message-ID`` findet sich die Nachricht auch dann wieder, wenn
    der Server kein UIDPLUS spricht und uns die neue Nummer nie genannt hat.
    """

    konto_id: str
    quelle_pfad: str
    ziel_pfad: str
    message_ids: list[str] = field(default_factory=list)
    text: str = ""


def _kann_move(klient) -> bool:
    return any(k.upper() == "MOVE" for k in imapdienst.faehigkeiten(klient))


def _verschieben_auf_dem_server(klient, uids: list[int], ziel_pfad: str) -> None:
    """Der eigentliche Zug — mit Rückfall für Server ohne ``MOVE``."""
    if _kann_move(klient):
        klient.move(uids, ziel_pfad)
        return

    # Der alte Weg. ⚠️ ``UID EXPUNGE`` statt ``EXPUNGE``: Ein blankes EXPUNGE
    # räumt **alle** als gelöscht markierten Nachrichten des Ordners ab, auch
    # solche, die jemand anders gerade markiert hat.
    klient.copy(uids, ziel_pfad)
    klient.add_flags(uids, [rb"\Deleted"])
    try:
        klient.uid_expunge(uids)
    except Exception:  # noqa: BLE001
        # Kein UIDPLUS. Dann bleibt die Nachricht als gelöscht markiert
        # liegen, bis der Server aufräumt - das ist unschön, aber besser als
        # ein EXPUNGE, das fremde Nachrichten mitnimmt.
        logger.info("Server has no UID EXPUNGE; the copies stay flagged as deleted.")


def _ziel_finden(db: Session, konto: Konto, rolle: str) -> Ordner:
    ordner = next((o for o in konto.ordner if o.rolle == rolle), None)
    if ordner is None:
        raise HandelnFehler(
            f"Dieses Postfach hat keinen Ordner für „{rolle}“. Lege ihn auf dem "
            "Server an oder verschiebe von Hand."
        )
    return ordner


def verschieben(
    db: Session, nachrichten: list[Nachricht], ziel: Ordner, text: str = ""
) -> Rueckweg:
    """Nachrichten in einen anderen Ordner desselben Postfachs schieben."""
    if not nachrichten:
        raise HandelnFehler("Nichts ausgewählt.")

    konto_ids = {n.konto_id for n in nachrichten}
    if len(konto_ids) != 1:
        raise HandelnFehler("Nachrichten aus mehreren Postfächern lassen sich nicht zusammen verschieben.")
    if ziel.konto_id != nachrichten[0].konto_id:
        raise HandelnFehler("Der Zielordner gehört zu einem anderen Postfach.")

    quelle_ids = {n.ordner_id for n in nachrichten}
    if len(quelle_ids) != 1:
        raise HandelnFehler("Bitte nur aus einem Ordner auf einmal verschieben.")
    if nachrichten[0].ordner_id == ziel.id:
        raise HandelnFehler("Die Nachricht liegt schon dort.")

    konto = db.get(Konto, nachrichten[0].konto_id)
    quelle = nachrichten[0].ordner
    uids = [n.uid for n in nachrichten]
    message_ids = [n.message_id for n in nachrichten if n.message_id]

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
            klient.select_folder(quelle.pfad, readonly=False)
            _verschieben_auf_dem_server(klient, uids, ziel.pfad)

            # ⚠️ **Den Zielordner gleich nachziehen.** Der Zug ist auf dem
            # Server erledigt, aber nexmails Datenbank weiß nichts davon - und
            # die Oberfläche liest nur von dort. Ohne diesen Abgleich
            # verschwindet die Nachricht aus der Liste und taucht im
            # Papierkorb erst auf, wenn jemand von Hand aktualisiert. Wer eine
            # Mail löscht und sie nirgends wiederfindet, hält das für
            # Datenverlust - zu Recht.
            #
            # Auf derselben Verbindung und unter demselben Schloss: Apple
            # erlaubt nur eine IMAP-Verbindung je Postfach.
            abgleich.ordner_abgleichen(klient, db, konto, ziel)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    # ⚠️ Erst jetzt lokal. Die Zeilen werden **entfernt**, nicht umgehängt:
    # Im Zielordner hat die Nachricht eine neue Nummer, und die kennen wir
    # nicht. Der nächste Abgleich holt sie dort als neu.
    for nachricht in nachrichten:
        db.delete(nachricht)

    # ⚠️ **Ausspülen, bevor gezählt wird.** Die Sitzung läuft mit
    # ``autoflush=False`` - ohne dieses ``flush`` sieht die Zählung unten die
    # gerade entfernten Zeilen noch und meldet einen Ungelesen-Stand, der eine
    # Nachricht zu hoch ist. Genau so ist der erste Testlauf gescheitert.
    db.flush()

    quelle.anzahl = max(0, quelle.anzahl - len(nachrichten))
    quelle.ungelesen = (
        db.query(Nachricht)
        .filter(Nachricht.ordner_id == quelle.id, Nachricht.gelesen.is_(False))
        .count()
    )
    konto.zuletzt_geprueft = utcnow()
    db.commit()

    logger.info("%s message(s) moved from %s to %s.", len(uids), quelle.pfad, ziel.pfad)
    return Rueckweg(
        konto_id=konto.id,
        quelle_pfad=quelle.pfad,
        ziel_pfad=ziel.pfad,
        message_ids=message_ids,
        text=text,
    )


def in_rolle(db: Session, nachrichten: list[Nachricht], rolle: str, text: str = "") -> Rueckweg:
    """In den Papierkorb, ins Archiv oder in den Junk-Ordner."""
    if not nachrichten:
        raise HandelnFehler("Nichts ausgewählt.")
    konto = db.get(Konto, nachrichten[0].konto_id)
    return verschieben(db, nachrichten, _ziel_finden(db, konto, rolle), text)


def zurueck(db: Session, weg: Rueckweg) -> int:
    """Einen Zug zurücknehmen.

    Gesucht wird im Zielordner nach der ``Message-ID`` — die überlebt das
    Verschieben, die Nummer nicht.
    """
    if not weg.message_ids:
        raise HandelnFehler("Für diesen Zug gibt es keinen Rückweg.")

    konto = db.get(Konto, weg.konto_id)
    if konto is None:
        raise HandelnFehler("Das Postfach gibt es nicht mehr.")

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    zurueckgeholt = 0

    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.verbinden(
            konto.imap_server,
            konto.imap_port,
            konto.imap_sicherheit,
            konto.imap_benutzer,
            imap_pw,
        )
        try:
            klient.select_folder(weg.ziel_pfad, readonly=False)
            gefunden: list[int] = []
            for kennung in weg.message_ids:
                gefunden.extend(klient.search(["HEADER", "Message-ID", kennung]))
            if gefunden:
                _verschieben_auf_dem_server(klient, gefunden, weg.quelle_pfad)
                zurueckgeholt = len(gefunden)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    logger.info("%s message(s) moved back to %s.", zurueckgeholt, weg.quelle_pfad)
    return zurueckgeholt


def ordner_als_gelesen(db: Session, konto: Konto, ordner: Ordner) -> int:
    """Alles Ungelesene in einem Ordner als gelesen markieren.

    ⚠️ **Ein IMAP-Befehl für alle, nicht einer je Nachricht.** Bei einem
    Posteingang mit dreihundert Ungelesenen wären das dreihundert Umläufe —
    der Betreiber sitzt derweil vor einer Anwendung, die nichts tut.

    ⚠️ **Erst der Server, dann hier.** Andersherum stünde die Zahl auf null,
    während das Telefon weiter dreihundert zeigt.
    """
    offen = (
        db.query(Nachricht)
        .filter(Nachricht.ordner_id == ordner.id, Nachricht.gelesen.is_(False))
        .all()
    )
    if not offen:
        return 0

    uids = [n.uid for n in offen]
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
            klient.select_folder(ordner.pfad, readonly=False)
            # In Blöcken: Ein einzelner Befehl mit zehntausend Nummern
            # sprengt bei manchen Servern die Zeilenlänge.
            for i in range(0, len(uids), 500):
                klient.add_flags(uids[i : i + 500], [rb"\Seen"])
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    for nachricht in offen:
        nachricht.gelesen = True
    ordner.ungelesen = 0
    db.commit()
    logger.info("%s message(s) marked as read in %s.", len(uids), ordner.pfad)
    return len(uids)


def ordner_leeren(db: Session, ordner: Ordner) -> int:
    """Papierkorb oder Junk-Ordner endgültig leeren.

    ⚠️ **Das ist der einzige Vorgang ohne Rückweg.** Deshalb nur für genau
    diese beiden Ordner, und die Oberfläche fragt vorher.
    """
    if ordner.rolle not in ("papierkorb", "junk"):
        raise HandelnFehler("Nur Papierkorb und Junk lassen sich leeren.")

    konto = db.get(Konto, ordner.konto_id)
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
            klient.select_folder(ordner.pfad, readonly=False)
            uids = klient.search(["ALL"])
            if uids:
                klient.add_flags(uids, [rb"\Deleted"])
                try:
                    klient.uid_expunge(uids)
                except Exception:  # noqa: BLE001
                    klient.expunge()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    anzahl = db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id).delete()
    ordner.anzahl = 0
    ordner.ungelesen = 0
    db.commit()
    logger.warning("Folder %s was emptied (%s messages).", ordner.pfad, anzahl)
    return anzahl
