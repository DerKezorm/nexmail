"""Wiedervorlage — eine Mail bis zu einem Zeitpunkt weglegen, dann wieder oben.

Die weggelegte Mail wandert in einen **echten** IMAP-Ordner „Wiedervorlage"
auf oberster Ebene des Kontos. Sie bleibt damit von jedem Client aus sichtbar
— nichts verschwindet in einer Nur-nexmail-Logik. nexmail merkt sich nur,
wann sie zurueckkommt und wohin (Tabelle ``wiedervorlage``).

⚠️ **Erst der Server, dann der Eintrag.** Das Weglegen ist ein Verschieben
ueber ``handeln.verschieben`` — geteilte Verbindung, Schloss, lokales
Nachziehen inklusive. Scheitert das Verschieben, entsteht **kein** Eintrag:
Ein Merker ohne weggelegte Mail wuerde beim Aufwachen ins Leere greifen und
bis dahin eine Wiedervorlage behaupten, die es nicht gibt.

⚠️ **Wiedergefunden wird ueber die ``Message-ID``, nie ueber die
Zeilennummer** — dieselbe Begruendung wie bei den Aufgaben: Beim Verschieben
stirbt die lokale Zeile, und im Zielordner traegt die Mail eine neue UID.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Benutzer, Konto, Nachricht, Ordner, Wiedervorlage, utcnow
from . import abgleich, handeln, imap as imapdienst, konten as kontendienst
from ..meldung import Meldung

logger = logging.getLogger("nexmail.wiedervorlage")

#: Der Ordner auf dem Mailserver, oberste Ebene. Ein fester Name, damit jedes
#: Geraet denselben Ordner sieht. ⚠️ Kein Ebenentrenner noetig: Der Ordner
#: liegt an der Wurzel, und der Name selbst enthaelt keinen der ueblichen
#: Trenner — die Pruefung dafuer sitzt beim freien Anlegen (services/ordner).
ORDNER_NAME = "Wiedervorlage"

#: Wie oft der Aufwach-Faden nachsieht. Eine Minute, wie beim Versandplan:
#: Der Zeitpunkt wird auf die Minute gewaehlt — viel spaeter darf „18:00"
#: nicht hinausgehen.
NACHSEHEN_SEKUNDEN = 60

#: Der wachsende Abstand nach Fehlschlaegen, gedeckelt bei einer Stunde.
#: Ohne Deckel und Rueckstau machte ein dauerhaft klemmender Eintrag 1440
#: frische IMAP-Anmeldungen am Tag. Aufgegeben wird nie — der Eintrag gehoert
#: dem Benutzer, und wegnehmen kann er ihn selbst (``entfernen``).
RUECKSTAU_DECKEL_MINUTEN = 60

#: Zeichen, die ein SEARCH-Argument aus der Bahn werfen: imapclient schickt
#: ein Kriterium ohne Leerzeichen, Anfuehrungszeichen und Backslash
#: UNzitiert hinaus — eine rohe Klammer oder ein Prozentzeichen stuende dann
#: mitten im Befehl. Und Nicht-ASCII (etwa U+FFFD aus dem Abgleich) wirft
#: schon beim Kodieren. Solche Kennungen bleiben draussen.
_VERBOTEN_IM_SUCHKRITERIUM = frozenset('(){%*"\\')


def _suchbare_kennung(message_id: str) -> bool:
    """Ob sich diese Message-ID gefahrlos in ein IMAP-SEARCH stecken laesst.

    Erlaubt ist druckbares ASCII ohne Leerzeichen und ohne die Zeichen oben —
    eine RFC-5322-Message-ID erfuellt das immer; was es nicht erfuellt, ist
    kaputt oder boesartig und wuerde die Suche zum Scheitern oder zu falschen
    Treffern bringen.
    """
    if not message_id:
        return False
    return all(
        32 < ord(zeichen) < 127 and zeichen not in _VERBOTEN_IM_SUCHKRITERIUM
        for zeichen in message_id
    )


class WiedervorlageFehler(Meldung, RuntimeError):
    """Mit einer KENNUNG als Text — die Oberflaeche uebersetzt."""


@dataclass
class Sicht:
    """Ein Eintrag, wie die Oberflaeche ihn braucht.

    ``nachricht_id`` ist die **aktuelle** lokale Zeile der Mail, frisch ueber
    die ``Message-ID`` nachgeschlagen — nicht eine gespeicherte: Die Liste im
    Wiedervorlage-Ordner soll ihre Aufwach-Marke an der richtigen Zeile
    tragen, auch nachdem der Abgleich die Mail neu angelegt hat.
    """

    eintrag: Wiedervorlage
    nachricht_id: int | None


def alle(db: Session, benutzer: Benutzer) -> list[Sicht]:
    """Alle wartenden Eintraege dieses Benutzers, frueheste zuerst."""
    zeilen = (
        db.execute(
            select(Wiedervorlage)
            .where(Wiedervorlage.benutzer_id == benutzer.id)
            .order_by(Wiedervorlage.aufwachen, Wiedervorlage.id)
        )
        .scalars()
        .all()
    )
    heraus: list[Sicht] = []
    for eintrag in zeilen:
        mail = (
            db.execute(
                select(Nachricht)
                .join(Ordner, Nachricht.ordner_id == Ordner.id)
                .where(
                    Nachricht.benutzer_id == benutzer.id,
                    Nachricht.konto_id == eintrag.konto_id,
                    Nachricht.message_id == eintrag.message_id,
                )
                # ⚠️ Bei Duplikaten (dieselbe Message-ID in zwei Ordnern —
                # etwa die an sich selbst gesendete Mail samt Kopie in
                # „Gesendet") soll die Aufwach-Marke an der Kopie im
                # Wiedervorlage-Ordner haengen, nicht an einer beliebigen.
                .order_by((Ordner.pfad == ORDNER_NAME).desc(), Nachricht.id.desc())
            )
            .scalars()
            .first()
        )
        heraus.append(Sicht(eintrag=eintrag, nachricht_id=mail.id if mail else None))
    return heraus


def weglegen(
    db: Session, benutzer: Benutzer, nachricht_id: int, aufwachen: datetime
) -> Wiedervorlage:
    """Eine Mail in den Wiedervorlage-Ordner legen und den Merker setzen.

    ⚠️ **Erst das Verschieben, dann der Eintrag.** ``handeln.verschieben``
    laeuft ueber die geteilte Verbindung samt Schloss und zieht den Zielordner
    lokal nach; wirft es, kommt dieser Aufruf nie bis zum Eintrag.
    """
    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != benutzer.id:
        raise WiedervorlageFehler("wiedervorlage_nachricht_fehlt")
    if not nachricht.message_id:
        # Ohne Message-ID gibt es keinen Weg zurueck zur Mail — der Merker
        # waere beim Aufwachen blind. Es gibt solche Mails; sie bleiben aussen.
        raise WiedervorlageFehler("wiedervorlage_ohne_kennung")
    if not _suchbare_kennung(nachricht.message_id):
        # Eine Kennung, die sich nicht gefahrlos suchen laesst (Nicht-ASCII,
        # Klammern, Anfuehrungszeichen), faende die Mail beim Aufwachen nie —
        # oder braechte das SEARCH zum Scheitern. Lieber gleich sagen.
        raise WiedervorlageFehler("wiedervorlage_kennung_unbrauchbar")

    konto = db.get(Konto, nachricht.konto_id)
    quelle = nachricht.ordner
    message_id = nachricht.message_id
    betreff = nachricht.betreff

    bestehend = (
        db.execute(
            select(Wiedervorlage).where(
                Wiedervorlage.benutzer_id == benutzer.id,
                Wiedervorlage.konto_id == konto.id,
                Wiedervorlage.message_id == message_id,
            )
        )
        .scalars()
        .first()
    )

    if quelle.pfad == ORDNER_NAME:
        # Die Mail liegt schon im Wiedervorlage-Ordner — zweimal weggelegt
        # heisst: neues Aufwachen, kein zweiter Zug auf dem Server. Der
        # Rueckweg bleibt der gemerkte; fehlt der Merker (von einem anderen
        # Geraet hineingelegt), geht es spaeter in den Posteingang.
        zurueck_pfad = bestehend.zurueck_pfad if bestehend else _posteingang_pfad(konto)
    else:
        ziel = _ordner_sicherstellen(db, konto)
        handeln.verschieben(db, [nachricht], ziel)
        zurueck_pfad = quelle.pfad

    if bestehend is None:
        bestehend = Wiedervorlage(
            benutzer_id=benutzer.id, konto_id=konto.id, message_id=message_id
        )
        db.add(bestehend)
    bestehend.aufwachen = aufwachen
    bestehend.zurueck_pfad = zurueck_pfad
    bestehend.betreff_abzug = betreff
    # Neu weggelegt heisst: alter Rueckstau zaehlt nicht mehr.
    bestehend.fehlversuche = 0
    bestehend.naechster_versuch = None
    db.commit()
    logger.info("A message was snoozed until %s.", aufwachen.isoformat())
    return bestehend


def _posteingang_pfad(konto: Konto) -> str:
    posteingang = next((o for o in konto.ordner if o.rolle == "posteingang"), None)
    return posteingang.pfad if posteingang is not None else "INBOX"


def _ordner_sicherstellen(db: Session, konto: Konto) -> Ordner:
    """Den Wiedervorlage-Ordner beim Anbieter anlegen, falls er fehlt.

    Dasselbe Muster wie ``ordner.anlegen`` — ``CREATE`` plus ``SUBSCRIBE``,
    danach die ganze Ordnerliste neu lesen statt eine Zeile zu erfinden.
    ⚠️ **Ein schon vorhandener Ordner ist hier kein Fehler:** Ein anderes
    Geraet kann ihn angelegt haben, waehrend nexmail ihn nur noch nicht
    kennt. Deshalb wird das ``CREATE`` toleriert und die Wahrheit aus der
    frisch gelesenen Liste genommen.
    """
    vorhanden = next((o for o in konto.ordner if o.pfad == ORDNER_NAME), None)
    if vorhanden is not None:
        return vorhanden

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            try:
                klient.create_folder(ORDNER_NAME)
            except Exception as fehler:  # noqa: BLE001
                logger.info("The snooze folder may already exist on the server: %s", fehler)
            try:
                klient.subscribe_folder(ORDNER_NAME)
            except Exception as fehler:  # noqa: BLE001
                # Kein Abbruch: Manche Server kennen Abonnements gar nicht.
                logger.info("The snooze folder could not be subscribed: %s", fehler)
            kontendienst.ordner_uebernehmen(db, konto, imapdienst.ordner_lesen(klient))
            db.commit()
            # Ohne das sieht ``konto.ordner`` den neuen Ordner nicht — die
            # Sitzung laeuft mit ``expire_on_commit=False``, dieselbe Falle
            # wie in ``ordner.anlegen``.
            db.refresh(konto)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    neuer = next((o for o in konto.ordner if o.pfad == ORDNER_NAME), None)
    if neuer is None:
        raise WiedervorlageFehler("wiedervorlage_ordner_fehlt")
    return neuer


def entfernen(db: Session, benutzer: Benutzer, eintrag_id: int) -> None:
    """Einen Merker von Hand wegnehmen — die Mail bleibt, wo sie liegt.

    ⚠️ Der eine Ausweg fuer einen Eintrag, dessen Aufwecken dauerhaft
    scheitert: Ohne diesen Weg saesse der Benutzer auf einem Merker, den nur
    noch die Datenbank loswuerde.
    """
    eintrag = db.get(Wiedervorlage, eintrag_id)
    if eintrag is None or eintrag.benutzer_id != benutzer.id:
        # Fremder Besitz und „gibt es nicht" antworten gleich.
        raise WiedervorlageFehler("wiedervorlage_eintrag_fehlt")
    db.delete(eintrag)
    db.commit()
    logger.info("A snooze entry was removed by its owner.")


def runde() -> int:
    """Eine Aufwach-Runde: alle faelligen Eintraege zurueckholen.

    ⚠️ **Ein klemmender Server toetet die Runde nicht.** Jeder Eintrag wird
    einzeln gefangen — sonst hielte ein falsch eingetragenes Postfach die
    Wiedervorlage aller anderen an. Ein gescheiterter Eintrag bleibt liegen
    und kommt spaeter wieder dran — mit wachsendem Abstand, damit ein
    dauerhaft klemmender nicht jede Minute eine frische IMAP-Anmeldung macht.
    """
    zurueck = 0
    with SessionLocal() as db:
        jetzt = utcnow()
        faellige = (
            db.execute(
                select(Wiedervorlage).where(
                    Wiedervorlage.aufwachen <= jetzt,
                    or_(
                        Wiedervorlage.naechster_versuch.is_(None),
                        Wiedervorlage.naechster_versuch <= jetzt,
                    ),
                )
            )
            .scalars()
            .all()
        )
        for eintrag in faellige:
            try:
                if _aufwecken(db, eintrag):
                    zurueck += 1
            except Exception as fehler:  # noqa: BLE001
                # ⚠️ Erst aufraeumen: Ein mitten im Abgleich abgerissener
                # Eintrag laesst halb geschriebene Zeilen in der geteilten
                # Session liegen — ohne rollback wuerde der Commit des
                # naechsten Eintrags sie stillschweigend festschreiben.
                db.rollback()
                _fehlschlag_merken(db, eintrag)
                logger.warning("Waking a snoozed message failed: %s", fehler)
    if zurueck:
        logger.info("%s snoozed message(s) went back to their folder.", zurueck)
    return zurueck


def _fehlschlag_merken(db: Session, eintrag: Wiedervorlage) -> None:
    """Den Rueckstau setzen: 2, 4, 8 … Minuten, gedeckelt bei einer Stunde."""
    try:
        eintrag.fehlversuche = (eintrag.fehlversuche or 0) + 1
        minuten = min(2**eintrag.fehlversuche, RUECKSTAU_DECKEL_MINUTEN)
        eintrag.naechster_versuch = utcnow() + timedelta(minutes=minuten)
        db.commit()
    except Exception:  # noqa: BLE001
        # Ist selbst die Datenbank gerade nicht zu haben, bleibt der alte
        # Stand — die naechste Runde versucht es ohnehin wieder.
        db.rollback()


def _aufwecken(db: Session, eintrag: Wiedervorlage) -> bool:
    """Einen faelligen Eintrag abarbeiten. ``True`` heisst: Mail zurueckgelegt.

    ⚠️ **Nicht gefunden heisst: Der Mensch hat entschieden.** Wer die Mail von
    einem anderen Geraet aus woandershin geschoben hat, wollte sie dort —
    nexmail raeumt dann nur seinen Merker weg (Info-Log), es sucht ihr nicht
    hinterher.
    """
    konto = db.get(Konto, eintrag.konto_id)
    if konto is None:
        # Das Postfach wurde entfernt — der Merker hat nichts mehr zu merken.
        db.delete(eintrag)
        db.commit()
        logger.info("A snooze entry was dropped: its mailbox is gone.")
        return False

    if not _suchbare_kennung(eintrag.message_id):
        # Altbestand von vor der Pruefung beim Weglegen: Diese Kennung findet
        # ihre Mail nie — ewig weiterprobieren machte den Eintrag unsterblich.
        # Der Merker faellt; die Mail bleibt sichtbar im Wiedervorlage-Ordner.
        db.delete(eintrag)
        db.commit()
        logger.warning("A snooze entry was dropped: its Message-ID cannot be searched safely.")
        return False

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    wv_ordner = next((o for o in konto.ordner if o.pfad == ORDNER_NAME), None)

    gefunden: list[int] = []
    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            # ⚠️ **Kein breiter except um SELECT und SEARCH.** Hier stand
            # einer — und deutete jeden Timeout und jedes BAD als „Ordner
            # weg", worauf der Merker unten endgueltig fiel. Stattdessen
            # wird die eine Frage, um die es geht, ausdruecklich gestellt;
            # jeder echte Fehler laeuft zu ``runde()`` hinauf, wo der
            # Eintrag liegen bleibt und spaeter erneut drankommt.
            if klient.folder_exists(ORDNER_NAME):
                klient.select_folder(ORDNER_NAME, readonly=False)
                gefunden = _mail_suchen(klient, eintrag.message_id)

            if gefunden:
                zurueck_pfad = eintrag.zurueck_pfad
                if not klient.folder_exists(zurueck_pfad):
                    # Der Rueckweg wurde geloescht oder umbenannt. Nicht
                    # ewig dagegen anrennen: Die Mail geht in den
                    # Posteingang — zurueckkommen ist der Sinn der Sache.
                    zurueck_pfad = _posteingang_pfad(konto)
                    logger.info(
                        "The snooze return folder is gone; the message goes to the inbox instead."
                    )
                ziel = next((o for o in konto.ordner if o.pfad == zurueck_pfad), None)
                # ⚠️ **Ungelesen VOR dem Verschieben.** Flags reisen mit der
                # Mail; nach dem Zug kennen wir ihre neue UID nicht mehr
                # (ohne UIDPLUS nennt der Server sie nie). So faellt sie im
                # Zielordner wieder auf — das ist der Sinn der Wiedervorlage.
                klient.remove_flags(gefunden, [rb"\Seen"])
                handeln._verschieben_auf_dem_server(klient, gefunden, zurueck_pfad)
                # Beide Ordner nachziehen, auf derselben Verbindung und unter
                # demselben Schloss — die Oberflaeche liest nur die eigene
                # Datenbank, und die soll nicht luegen.
                if wv_ordner is not None:
                    abgleich.ordner_abgleichen(klient, db, konto, wv_ordner)
                if ziel is not None:
                    abgleich.ordner_abgleichen(klient, db, konto, ziel)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    if not gefunden:
        logger.info("A snoozed message was moved by hand; only the reminder was dropped.")
    db.delete(eintrag)
    db.commit()
    return bool(gefunden)


def _mail_suchen(klient, message_id: str) -> list[int]:
    """Die UIDs dieser Mail im gewaehlten Ordner — exakt, nicht als Teilstring.

    ⚠️ ``SEARCH HEADER`` ist nach RFC 3501 ein **Teilstring**-Vergleich: Eine
    Kennung, die in einer anderen enthalten ist, traefe beide Mails — und
    beide wanderten in den Rueckkehr-Ordner dieses einen Eintrags. Deshalb
    wird jede Fundstelle am tatsaechlichen Kopf nachgeprueft.
    """
    treffer = list(klient.search(["HEADER", "Message-ID", message_id]))
    if not treffer:
        return []
    antworten = klient.fetch(treffer, [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])
    schluessel = b"BODY[HEADER.FIELDS (MESSAGE-ID)]"
    genau: list[int] = []
    for uid in treffer:
        roh = (antworten.get(uid) or {}).get(schluessel, b"") or b""
        wert = roh.decode(errors="replace").partition(":")[2]
        # Gefaltete Kopfzeilen zusammenziehen — eine Message-ID selbst
        # enthaelt keine Leerraeume.
        if "".join(wert.split()) == message_id:
            genau.append(uid)
    return genau


__all__ = [
    "NACHSEHEN_SEKUNDEN",
    "ORDNER_NAME",
    "RUECKSTAU_DECKEL_MINUTEN",
    "Sicht",
    "WiedervorlageFehler",
    "alle",
    "entfernen",
    "runde",
    "weglegen",
]
