"""Senden — und die Warteschlange, die einen Neustart übersteht.

Der Ablauf ist absichtlich in dieser Reihenfolge:

    1. Mail bauen und **auf die Platte legen**
    2. Zeile im Ausgang anlegen
    3. senden
    4. in „Gesendet" ablegen **und den Ordner abgleichen**
    5. Zeile auf „gesendet" setzen

⚠️ **Erst ablegen, dann senden.** Wer zuerst sendet und dann speichert,
verliert bei einem Absturz dazwischen keine Mail — sondern weiß nur nicht mehr,
dass sie draußen ist, und schickt sie beim nächsten Lauf ein zweites Mal.
Umgekehrt ist der schlimmste Fall eine Mail, die im Ausgang liegt und noch
einmal versucht wird.

⚠️ **``APPEND`` in „Gesendet" ist nicht optional.** Ohne ihn steht die
gesendete Mail nur in nexmail und in keinem anderen Client — auf dem Telefon
sieht es aus, als hätte man nie geantwortet.
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Ausgang, Konto, neue_id, utcnow
from . import abgleich, imap as imapdienst, konten as kontendienst
from .verfassen import Entwurf, bauen

logger = logging.getLogger("nexmail.senden")

#: Wie oft ein Versand wiederholt wird, bevor er als gescheitert gilt. Danach
#: bleibt die Mail im Ausgang stehen und wartet auf eine Hand.
MAX_VERSUCHE = 5


class SendeFehler(RuntimeError):
    pass


def ausgangsordner() -> Path:
    ordner = get_settings().data_dir / "ausgang"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _datei(kennung: str) -> Path:
    return ausgangsordner() / f"{kennung}.eml"


def einreihen(db: Session, konto: Konto, entwurf: Entwurf) -> Ausgang:
    """Bauen, ablegen, in die Warteschlange stellen — noch nichts senden."""
    roh, message_id = bauen(entwurf)

    kennung = neue_id()
    _datei(kennung).write_bytes(roh)

    alle_empfaenger = [
        *entwurf.an,
        *entwurf.kopie,
        *entwurf.blindkopie,
    ]
    zeile = Ausgang(
        id=kennung,
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        stand="wartet",
        an_json=json.dumps(alle_empfaenger, ensure_ascii=False),
        betreff=entwurf.betreff,
        message_id=message_id,
    )
    db.add(zeile)
    db.commit()
    logger.info("A message was queued for sending.")
    return zeile


def _in_gesendet_ablegen(db: Session, konto: Konto, roh: bytes) -> bool:
    """Die gesendete Mail ins Postfach legen — **und gleich zurückholen**.

    Findet sich kein „Gesendet"-Ordner, wird nichts abgelegt und ``False``
    gemeldet — das ist kein Grund, den Versand als gescheitert zu behandeln.
    Die Mail ist draußen; sie fehlt nur in der Ablage.

    ⚠️ **Der Abgleich danach ist kein Beiwerk.** ``APPEND`` legt die Mail beim
    Anbieter ab, nicht in nexmails Datenbank. Ohne den Abgleich bleibt
    „Gesendet" leer, bis jemand von Hand aktualisiert — und wer gerade
    geantwortet hat, sieht seine Antwort nirgends und schickt sie ein zweites
    Mal. Genau das ist am 31.08.2026 passiert.

    Der Abgleich läuft **auf derselben Verbindung und unter demselben
    Schloss** wie der ``APPEND``. Das ist Vorgabe, nicht Bequemlichkeit: Apple
    erlaubt nur eine IMAP-Verbindung je Postfach.
    """
    gesendet = next((o for o in konto.ordner if o.rolle == "gesendet"), None)
    if gesendet is None:
        logger.info("No sent folder for this mailbox; the copy is skipped.")
        return False

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
            klient.append(gesendet.pfad, roh, [rb"\Seen"], datetime.now(timezone.utc))
            abgleich.ordner_abgleichen(klient, db, konto, gesendet)
            db.commit()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass
    return True


def versenden(db: Session, zeile: Ausgang) -> None:
    """Einen Eintrag der Warteschlange tatsächlich hinausschicken."""
    datei = _datei(zeile.id)
    if not datei.is_file():
        zeile.stand = "gescheitert"
        zeile.letzter_fehler = "Die vorbereitete Nachricht liegt nicht mehr auf der Platte."
        db.commit()
        raise SendeFehler(zeile.letzter_fehler)

    konto = db.get(Konto, zeile.konto_id)
    if konto is None:
        zeile.stand = "gescheitert"
        zeile.letzter_fehler = "Das Postfach gibt es nicht mehr."
        db.commit()
        raise SendeFehler(zeile.letzter_fehler)

    roh = datei.read_bytes()
    empfaenger = json.loads(zeile.an_json or "[]")
    _, smtp_pw = kontendienst.passwoerter_lesen(konto)

    zeile.stand = "unterwegs"
    zeile.versuche += 1
    db.commit()

    try:
        _smtp_senden(konto, smtp_pw, empfaenger, roh)
    except Exception as fehler:  # noqa: BLE001
        zeile.stand = "gescheitert" if zeile.versuche >= MAX_VERSUCHE else "wartet"
        zeile.letzter_fehler = str(fehler)[:500]
        db.commit()
        logger.warning("Sending failed (attempt %s): %s", zeile.versuche, fehler)
        raise SendeFehler(str(fehler)) from fehler

    # Ab hier ist die Mail draußen. Alles Weitere darf sie nicht mehr
    # zurückholen - deshalb wird der Stand **zuerst** gesetzt.
    zeile.stand = "gesendet"
    zeile.gesendet = utcnow()
    zeile.letzter_fehler = ""
    db.commit()

    try:
        _in_gesendet_ablegen(db, konto, roh)
    except Exception as fehler:  # noqa: BLE001
        # ⚠️ Kein Fehler nach außen: Die Mail ist versandt. Wer hier abbricht,
        # bringt den Benutzer dazu, sie ein zweites Mal zu schicken.
        logger.warning("The message was sent but could not be filed in Sent: %s", fehler)

    datei.unlink(missing_ok=True)


def _smtp_senden(konto: Konto, passwort: str, empfaenger: list[str], roh: bytes) -> None:
    import ssl

    if konto.smtp_sicherheit == "ssl":
        verbindung = smtplib.SMTP_SSL(konto.smtp_server, konto.smtp_port, timeout=30)
    else:
        verbindung = smtplib.SMTP(konto.smtp_server, konto.smtp_port, timeout=30)
        verbindung.starttls(context=ssl.create_default_context())
    try:
        verbindung.login(konto.smtp_benutzer, passwort)
        # ⚠️ Die Empfängerliste kommt hier her, nicht aus den Kopfzeilen -
        # sonst bekäme eine Blindkopie nie etwas.
        verbindung.sendmail(konto.adresse, empfaenger, roh)
    finally:
        try:
            verbindung.quit()
        except Exception:  # noqa: BLE001
            pass


def warteschlange_abarbeiten(db: Session) -> dict[str, int]:
    """Alles Wartende noch einmal versuchen. Beim Start und nach Bedarf.

    ⚠️ Auch „unterwegs" wird wieder aufgenommen: Dieser Stand bedeutet, dass
    der Prozess mitten im Versand abgebrochen ist. Die Mail könnte draußen
    sein - deshalb zählt der Versuch mit, und nach MAX_VERSUCHE bleibt sie
    liegen, statt endlos wiederholt zu werden.
    """
    offen = (
        db.execute(select(Ausgang).where(Ausgang.stand.in_(["wartet", "unterwegs"])))
        .scalars()
        .all()
    )
    ergebnis = {"versucht": 0, "gesendet": 0, "liegen": 0}
    for zeile in offen:
        ergebnis["versucht"] += 1
        try:
            versenden(db, zeile)
            ergebnis["gesendet"] += 1
        except SendeFehler:
            ergebnis["liegen"] += 1
    return ergebnis


def aufraeumen(db: Session) -> int:
    """Verwaiste Dateien im Ausgang wegwerfen.

    Eine ``.eml`` ohne Zeile in der Datenbank gehört zu nichts mehr - etwa
    nach einer Wiederherstellung aus einer älteren Sicherung.
    """
    bekannt = {
        f"{kennung}.eml"
        for kennung in db.execute(select(Ausgang.id)).scalars().all()
    }
    weg = 0
    for datei in ausgangsordner().glob("*.eml"):
        if datei.name not in bekannt:
            datei.unlink(missing_ok=True)
            weg += 1
    if weg:
        logger.info("Removed %s orphaned message file(s) from the outbox.", weg)
    return weg
