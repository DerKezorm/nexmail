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

from sqlalchemy import func
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
    #: Nur gesetzt, wenn der Zug ueber eine Kontogrenze ging. Leer heisst:
    #: dasselbe Postfach, und der Rueckweg ist der einfache.
    ziel_konto_id: str = ""


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
        # Über die Kontogrenze ist ein anderer Vorgang: Der Server kann nicht
        # kopieren, was er nicht hat. Siehe ``ueber_konten``.
        return ueber_konten(db, nachrichten, ziel, text)

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


def ueber_konten(
    db: Session, nachrichten: list[Nachricht], ziel: Ordner, text: str = ""
) -> Rueckweg:
    """Nachrichten in ein **anderes** Postfach schieben.

    ⚠️ **Zwei Server, und keiner von beiden kennt den anderen.** Ein
    ``MOVE`` oder ``COPY`` geht nur innerhalb einer Verbindung. Über die Grenze
    heisst: holen, beim Ziel anhaengen, nachsehen ob es ankam, dann bei der
    Quelle loeschen.

    ⚠️ **Die Reihenfolge ist die ganze Sicherheit.** Wer zuerst loescht und
    dann anhaengt, verliert die Mail, sobald der zweite Schritt scheitert — und
    er scheitert irgendwann, weil zwei Server beteiligt sind. Andersherum ist
    der schlimmste Fall eine Mail, die zweimal da ist. Das sieht man und kann
    es aufraeumen; das andere sieht man nicht.

    ⚠️ **Nachgesehen wird wirklich.** Ein ``APPEND`` ohne Fehler heisst nicht,
    dass die Mail im Ordner liegt: Quotenüberschreitung, ein Filter auf dem
    Zielserver, ein stiller Ablagekorb — es gibt genug Wege, auf denen sie
    unterwegs verschwindet. Gesucht wird nach der ``Message-ID``.

    ⚠️ **Flags und Datum wandern mit.** Ohne sie ist jede verschobene Mail
    plötzlich ungelesen und von heute; nach einem Umzug von tausend Mails ist
    das Postfach unbrauchbar.
    """
    if not nachrichten:
        raise HandelnFehler("Nichts ausgewählt.")

    quelle = nachrichten[0].ordner
    quell_konto = db.get(Konto, nachrichten[0].konto_id)
    ziel_konto = db.get(Konto, ziel.konto_id)
    if quell_konto is None or ziel_konto is None:
        raise HandelnFehler("Das Postfach gibt es nicht mehr.")
    if len({n.ordner_id for n in nachrichten}) != 1:
        raise HandelnFehler("Bitte nur aus einem Ordner auf einmal verschieben.")

    quell_pw, _ = kontendienst.passwoerter_lesen(quell_konto)
    ziel_pw, _ = kontendienst.passwoerter_lesen(ziel_konto)
    uids = [n.uid for n in nachrichten]
    message_ids = [n.message_id for n in nachrichten if n.message_id]

    # ⚠️ **Beide Schloesser, und immer in derselben Reihenfolge.** Zwei Zuege
    # in entgegengesetzter Richtung wuerden sich sonst gegenseitig aussperren.
    erst, dann = sorted((quell_konto.id, ziel_konto.id))
    with abgleich.HALTER.schloss(erst), abgleich.HALTER.schloss(dann):
        quell_klient = imapdienst.verbinden(
            quell_konto.imap_server, quell_konto.imap_port, quell_konto.imap_sicherheit,
            quell_konto.imap_benutzer, quell_pw,
        )
        ziel_klient = None
        try:
            quell_klient.select_folder(quelle.pfad, readonly=True)
            geholt = quell_klient.fetch(
                uids, [abgleich.GANZE_MAIL, "FLAGS", "INTERNALDATE"]
            )

            ziel_klient = imapdienst.verbinden(
                ziel_konto.imap_server, ziel_konto.imap_port, ziel_konto.imap_sicherheit,
                ziel_konto.imap_benutzer, ziel_pw,
            )

            angekommen: list[int] = []
            for uid in uids:
                felder = geholt.get(uid) or {}
                roh = felder.get(abgleich.GANZE_MAIL_SCHLUESSEL)
                if not roh:
                    logger.warning("Message %s is gone from %s; skipped.", uid, quelle.pfad)
                    continue
                # ⚠️ ``\Recent`` gehoert dem Server, nicht der Nachricht — es
                # anzuhaengen weisen manche Server mit einem Fehler ab.
                flags = [
                    f for f in (felder.get(b"FLAGS") or ())
                    if f.lower() not in (b"\\recent",)
                ]
                ziel_klient.append(ziel.pfad, roh, flags, felder.get(b"INTERNALDATE"))
                angekommen.append(uid)

            if not angekommen:
                raise HandelnFehler("Keine der Nachrichten liess sich holen.")

            # Nachsehen, bevor geloescht wird.
            ziel_klient.select_folder(ziel.pfad, readonly=True)
            gefunden = 0
            for kennung in message_ids:
                gefunden += len(ziel_klient.search(["HEADER", "Message-ID", kennung]))
            if message_ids and gefunden < len(message_ids):
                raise HandelnFehler(
                    "Beim Zielpostfach ist nicht alles angekommen. Es wurde nichts "
                    "gelöscht — die Nachrichten liegen unverändert im Ausgangsordner."
                )

            # Erst jetzt bei der Quelle weg.
            quell_klient.select_folder(quelle.pfad, readonly=False)
            quell_klient.add_flags(angekommen, [rb"\Deleted"])
            try:
                quell_klient.uid_expunge(angekommen)
            except Exception:  # noqa: BLE001
                logger.info("Source server has no UID EXPUNGE; the copies stay flagged.")

            abgleich.ordner_abgleichen(ziel_klient, db, ziel_konto, ziel)
        finally:
            for k in (ziel_klient, quell_klient):
                if k is None:
                    continue
                try:
                    k.logout()
                except Exception:  # noqa: BLE001
                    pass

    for nachricht in nachrichten:
        if nachricht.uid in angekommen:
            db.delete(nachricht)
    db.flush()

    quelle.anzahl = max(0, quelle.anzahl - len(angekommen))
    db.commit()

    logger.info(
        "%s message(s) moved to another mailbox (%s -> %s).",
        len(angekommen), quelle.pfad, ziel.pfad,
    )
    return Rueckweg(
        konto_id=quell_konto.id,
        quelle_pfad=quelle.pfad,
        ziel_pfad=ziel.pfad,
        message_ids=message_ids,
        text=text,
        ziel_konto_id=ziel_konto.id,
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


def alte_entfernen(db: Session, ordner: Ordner, stichtag) -> int:
    """Nachrichten, die aelter als der Stichtag sind, endgueltig loeschen.

    Derselbe Weg wie ``ordner_leeren`` — erst der Server, dann die eigene
    Datenbank —, nur mit Datumsgrenze statt Kahlschlag. Benutzt vom
    Aufraeumdienst (``services/aufraeumen.py``), der Papierkorb und Junk nach
    der eingestellten Aufbewahrung leert.

    ⚠️ **Der Rollenfilter sitzt beim Aufrufer, und zwar genau einmal.** Diese
    Funktion loescht in jedem Ordner, den man ihr gibt — sie haengt an keiner
    Route, und ein zweiter Filter hier wuerde die Mutationsprobe des Aufrufers
    hohl machen: Wer dort den Filter entfernt, muss rot sehen, nicht gruen.

    ⚠️ **Erst abgleichen, dann messen.** Der Takt holt nur den Posteingang;
    was ein Telefon in den Papierkorb gelegt hat, kennt die Datenbank sonst
    nicht — und bliebe beim Aufraeumen ewig liegen. Der Abgleich laeuft auf
    derselben Verbindung und unter demselben Schloss, wie bei ``verschieben``.

    ⚠️ **Der Papierkorb misst die Verweildauer, nicht das Absendedatum.**
    ``datum`` ist die ``Date``-Kopfzeile des Absenders — daran gemessen waere
    eine heute geloeschte Januar-Mail sofort und endgueltig weg, mit null
    Rueckholfrist. Gemessen wird deshalb an ``angekommen``: Verschieben legt
    beim naechsten Abgleich eine neue Zeile an, die Uhr beginnt also mit dem
    Eintreffen im Papierkorb. So misst es jeder andere Client auch. Fuer Junk
    bleibt das Absendedatum: Dort trifft die Post direkt ein, und „aelter
    als n Tage" meint genau das.
    """
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
            abgleich.ordner_abgleichen(klient, db, konto, ordner)

            # ``coalesce``: Zeilen von vor der ``angekommen``-Spalte fuellt
            # der Start auf „jetzt" (main.lebenslauf) — der Rueckfall auf
            # ``datum`` faengt nur den Lauf ab, der genau dazwischen kommt.
            alter = (
                func.coalesce(Nachricht.angekommen, Nachricht.datum)
                if ordner.rolle == "papierkorb"
                else Nachricht.datum
            )
            alte = (
                db.query(Nachricht)
                .filter(Nachricht.ordner_id == ordner.id, alter < stichtag)
                .all()
            )
            if not alte:
                return 0

            uids = [n.uid for n in alte]
            # In Bloecken, wie bei ``ordner_als_gelesen``: Ein Befehl mit
            # zehntausend Nummern sprengt bei manchen Servern die Zeilenlaenge.
            for i in range(0, len(uids), 500):
                block = uids[i : i + 500]
                klient.add_flags(block, [rb"\Deleted"])
                try:
                    klient.uid_expunge(block)
                except Exception:  # noqa: BLE001
                    # Kein UIDPLUS. Das blanke EXPUNGE ist hier vertretbar:
                    # Der Ordner ist Papierkorb oder Junk, und alles darin,
                    # was als geloescht markiert ist, soll ohnehin weg.
                    klient.expunge()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    for nachricht in alte:
        db.delete(nachricht)
    # ⚠️ Ausspuelen, bevor gezaehlt wird — dieselbe autoflush-Falle wie bei
    # ``verschieben``: Ohne flush zaehlt die Abfrage die geloeschten Zeilen mit.
    db.flush()

    ordner.anzahl = db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id).count()
    ordner.ungelesen = (
        db.query(Nachricht)
        .filter(Nachricht.ordner_id == ordner.id, Nachricht.gelesen.is_(False))
        .count()
    )
    db.commit()
    logger.info(
        "%s message(s) past the retention limit were removed from %s.", len(alte), ordner.pfad
    )
    return len(alte)
