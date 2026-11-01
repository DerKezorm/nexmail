"""Der Änderungs-Feed: was sich seit einer Nummer getan hat, für die iPhone-App.

Die App hält einen Offline-Speicher. Sie liest ihn einmal über die Listen und
fragt danach, was seit der letzten Nummer neu, geändert oder entfernt ist. Das
schließt ein, was der Abgleich hereinholt: Flags von anderen Geräten und
Ordner, die anderswo angelegt wurden.

⚠️ **Trigger statt Python.** ``_flags_uebernehmen``, das Entfernen beim Abgleich
und die Aufräumwege schreiben mit ``update()`` und ``delete()``; ein
ORM-Ereignis sähe sie nicht, und die fehlende Zeile fiele erst auf dem Telefon
auf. Die Volltextsuche macht es aus demselben Grund genauso.

⚠️ **Je Ziel eine Zeile.** Jeder Trigger löscht die vorige Zeile desselben
Ziels. Wer zehnmal markiert, erzeugt keinen Rückstand, und die Tabelle wächst
mit der Zahl der geänderten Mails, nicht mit der Zahl der Änderungen.

⚠️ **Nur was die Liste zeigt.** Der Körper, der beim Öffnen hereinkommt, ist
keine Änderung; sonst meldete jede gelesene Mail sich selbst zurück.

⚠️ **``since=0`` liefert nichts als die aktuelle Nummer.** Der Feed ist kein
Katalog: Eine Mail von vor der Einführung hat keine Zeile. Die App fragt zuerst
nach der Nummer, liest dann die Listen und setzt mit dieser Nummer auf.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..meldung import Meldung
from ..models import Aenderung

logger = logging.getLogger("nexmail.aenderungen")

#: Wie lange Zeilen bleiben. Eine App, die länger schlief, liest von vorn.
FRIST_TAGE = 90

#: Unter dieser Nummer gibt es keine Auskunft mehr.
SCHLUESSEL_HORIZONT = "aenderung_horizont"

_JETZT = "CAST(strftime('%s', 'now') AS INTEGER)"


def _merken(benutzer: str, art: str, kennung: str, konto: str, weg: int) -> str:
    return f"""
        DELETE FROM aenderung WHERE art = '{art}' AND kennung = {kennung};
        INSERT INTO aenderung (benutzer_id, art, kennung, konto_id, weg, zeit)
        VALUES ({benutzer}, '{art}', {kennung}, {konto}, {weg}, {_JETZT});
    """


def _ueber_konto(art: str, zeile: str, weg: int) -> str:
    """⚠️ **Das Ordner-Konto kann schon fort sein**, wenn ein Postfach entfernt
    wird. Dann trifft das ``SELECT`` nichts, und der Ordner fehlt im Feed; die
    Zeile des Postfachs sagt dasselbe. Ein ``VALUES`` mit leerem Besitzer
    bräche dagegen das Entfernen selbst ab."""
    return f"""
        DELETE FROM aenderung WHERE art = '{art}' AND kennung = {zeile}.id;
        INSERT INTO aenderung (benutzer_id, art, kennung, konto_id, weg, zeit)
        SELECT k.benutzer_id, '{art}', {zeile}.id, {zeile}.konto_id, {weg}, {_JETZT}
        FROM konto k WHERE k.id = {zeile}.konto_id;
    """


def _unterschied(*spalten: str) -> str:
    return " OR ".join(f"NEW.{s} IS NOT OLD.{s}" for s in spalten)


#: Was eine Listenzeile ändert. Nicht ``anreisser``: Der wird beim Öffnen
#: genauer, und das ist keine Nachricht wert.
_NACHRICHT = ("gelesen", "markiert", "beantwortet", "schlagworte", "ordner_id", "uid", "wichtigkeit")
_ORDNER = ("pfad", "name", "rolle", "waehlbar", "abonniert")
_POSTFACH = ("anzeigename", "adresse", "farbe", "aktiv", "tags", "stoerung")


def _spaltenliste(spalten: tuple[str, ...]) -> str:
    return ", ".join(spalten)


_TRIGGER = (
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_nachricht_neu AFTER INSERT ON nachricht BEGIN
        {_merken("NEW.benutzer_id", "nachricht", "NEW.id", "NEW.konto_id", 0)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_nachricht_aend
    AFTER UPDATE OF {_spaltenliste(_NACHRICHT)} ON nachricht
    WHEN {_unterschied(*_NACHRICHT)} BEGIN
        {_merken("NEW.benutzer_id", "nachricht", "NEW.id", "NEW.konto_id", 0)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_nachricht_weg AFTER DELETE ON nachricht BEGIN
        {_merken("OLD.benutzer_id", "nachricht", "OLD.id", "OLD.konto_id", 1)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_ordner_neu AFTER INSERT ON ordner BEGIN
        {_ueber_konto("ordner", "NEW", 0)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_ordner_aend
    AFTER UPDATE OF {_spaltenliste(_ORDNER)} ON ordner
    WHEN {_unterschied(*_ORDNER)} BEGIN
        {_ueber_konto("ordner", "NEW", 0)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_ordner_weg AFTER DELETE ON ordner BEGIN
        {_ueber_konto("ordner", "OLD", 1)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_postfach_neu AFTER INSERT ON konto BEGIN
        {_merken("NEW.benutzer_id", "postfach", "NEW.id", "NEW.id", 0)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_postfach_aend
    AFTER UPDATE OF {_spaltenliste(_POSTFACH)} ON konto
    WHEN {_unterschied(*_POSTFACH)} BEGIN
        {_merken("NEW.benutzer_id", "postfach", "NEW.id", "NEW.id", 0)}
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS aenderung_postfach_weg AFTER DELETE ON konto BEGIN
        {_merken("OLD.benutzer_id", "postfach", "OLD.id", "OLD.id", 1)}
    END
    """,
)


def schema_anlegen(engine) -> None:
    """Die Trigger anlegen. ``create_all`` kennt sie nicht, wie den Suchindex."""
    with engine.begin() as verbindung:
        for anweisung in _TRIGGER:
            verbindung.exec_driver_sql(anweisung)


class AenderungFehler(Meldung):
    """Etwas, das die App wissen muss."""


@dataclass
class Seite:
    eintraege: list[Aenderung]
    #: Damit fragt die App als Nächstes.
    weiter: int
    mehr: bool
    #: Die neueste Nummer überhaupt.
    stand: int


def stand(db: Session) -> int:
    """Die höchste je vergebene Nummer.

    ⚠️ **Aus ``sqlite_sequence``, nicht aus der Tabelle.** Nach dem Aufräumen
    kann sie leer sein, und ein ``max()`` finge dann bei null wieder an.
    """
    return db.execute(
        text("SELECT seq FROM sqlite_sequence WHERE name = 'aenderung'")
    ).scalar() or 0


def seite(db: Session, benutzer_id: str, seit: int, grenze: int) -> Seite:
    """Die Änderungen nach ``seit``, älteste zuerst.

    ⚠️ **Zu alt und zu neu sind derselbe Fall.** Eine Nummer über dem Stand
    heißt, dass eine Sicherung eingespielt wurde: Was die App weiß, gibt es hier
    nicht mehr. Sie liest von vorn, statt auf Nummern zu warten, die nie kommen.
    """
    jetzt = stand(db)
    if seit == 0:
        return Seite([], jetzt, False, jetzt)
    horizont = int(einstellung_lesen(db, SCHLUESSEL_HORIZONT, "0") or 0)
    if seit < horizont or seit > jetzt:
        raise AenderungFehler("app_von_vorn")

    zeilen = list(
        db.scalars(
            select(Aenderung)
            .where(Aenderung.benutzer_id == benutzer_id, Aenderung.seq > seit)
            .order_by(Aenderung.seq)
            .limit(grenze + 1)
        )
    )
    mehr = len(zeilen) > grenze
    zeilen = zeilen[:grenze]
    # ⚠️ **Ohne Treffer gilt der Stand, nicht ``seit``.** Die Nummern gehören
    # allen Benutzern zusammen; sonst stünde eine ruhige App bald unter dem
    # Horizont, und ihr Speicher fiele weg, obwohl nichts verpasst wurde.
    weiter = zeilen[-1].seq if mehr else jetzt
    return Seite(zeilen, weiter, mehr, jetzt)


def aufraeumen(db: Session, jetzt: float | None = None) -> int:
    """Was älter als die Frist ist, fällt, und der Horizont rückt nach."""
    stichtag = int((jetzt if jetzt is not None else time.time()) - FRIST_TAGE * 86_400)
    hoechste = db.scalar(select(func.max(Aenderung.seq)).where(Aenderung.zeit < stichtag))
    if hoechste is None:
        return 0
    anzahl = db.execute(delete(Aenderung).where(Aenderung.zeit < stichtag)).rowcount
    bisher = int(einstellung_lesen(db, SCHLUESSEL_HORIZONT, "0") or 0)
    einstellung_schreiben(db, SCHLUESSEL_HORIZONT, str(max(bisher, hoechste)))
    db.commit()
    logger.info("Removed %s change record(s) older than %s days.", anzahl, FRIST_TAGE)
    return anzahl


__all__ = [
    "AenderungFehler",
    "FRIST_TAGE",
    "SCHLUESSEL_HORIZONT",
    "Seite",
    "aufraeumen",
    "schema_anlegen",
    "seite",
    "stand",
]
