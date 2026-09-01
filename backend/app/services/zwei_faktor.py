"""Der zweite Faktor: TOTP und Wiederherstellungscodes.

⚠️ **Verpflichtend, nicht angeboten.** Wer in einen Mail-Client kommt, kann
bei jedem anderen Dienst "Passwort vergessen" druecken. Deshalb entsteht der
zweite Faktor bei der Einrichtung und nicht in einer Einstellung, die man
spaeter vielleicht anfasst.

⚠️ **Der QR-Code entsteht im eigenen Server** (``segno``), nie ueber einen
fremden QR-Dienst. Ein Geheimnis, das man zum Zeichnen an einen fremden
Server schickt, ist keins mehr.
"""

from __future__ import annotations

import hashlib
import io
import logging
import secrets
import time

import pyotp
import segno
from sqlalchemy.orm import Session

from .. import crypto
from ..models import Benutzer, Wiederherstellungscode

logger = logging.getLogger("nexmail.zwei_faktor")

#: Wie viele Zeitschritte Toleranz. 1 heisst: der vorige und der naechste
#: gelten auch - genug fuer eine schiefe Uhr, wenig genug, um das Fenster
#: nicht auf anderthalb Minuten aufzureissen.
TOLERANZ = 1

SCHRITT_SEKUNDEN = 30

#: Zehn Stueck. Genug fuer mehrere Notfaelle, wenig genug, dass man sie
#: tatsaechlich ausdruckt oder in den Passwortspeicher legt.
ANZAHL_CODES = 10


def _kontext(benutzer: Benutzer) -> str:
    return f"benutzer:{benutzer.id}:totp"


def geheimnis_erzeugen() -> str:
    return pyotp.random_base32()


def geheimnis_speichern(benutzer: Benutzer, geheimnis: str) -> None:
    benutzer.totp_geheimnis = crypto.verschluesseln(geheimnis, _kontext(benutzer))
    benutzer.totp_bestaetigt = False
    benutzer.totp_letzter_schritt = 0


def geheimnis_lesen(benutzer: Benutzer) -> str:
    return crypto.entschluesseln(benutzer.totp_geheimnis, _kontext(benutzer))


def otpauth_adresse(benutzer: Benutzer, geheimnis: str, ausgeber: str = "nexmail") -> str:
    return pyotp.TOTP(geheimnis).provisioning_uri(name=benutzer.benutzername, issuer_name=ausgeber)


def qr_svg(adresse: str) -> str:
    """Der QR-Code als SVG-Zeichenkette, fertig zum Einbetten.

    ``BytesIO`` und nicht ``StringIO``: segno schreibt auch bei SVG Bytes -
    es legt einen Kodierer davor und erwartet einen binaeren Behaelter. Mit
    einem StringIO scheitert es mit "string argument expected, got 'bytes'".

    ``xmldecl=False``: Die Ausgabe wird in eine HTML-Seite eingebettet, und
    dort hat eine XML-Deklaration nichts zu suchen.
    """
    puffer = io.BytesIO()
    segno.make(adresse, error="m").save(
        puffer, kind="svg", scale=5, border=2, dark="#0d1614", xmldecl=False
    )
    return puffer.getvalue().decode("utf-8")


def code_pruefen(db: Session, benutzer: Benutzer, code: str) -> bool:
    """Einen TOTP-Code pruefen und - wenn er stimmt - verbrauchen.

    ⚠️ **Ein angenommener Code gilt kein zweites Mal.** Der zuletzt
    akzeptierte Zeitschritt wird gespeichert; alles, was nicht darueber liegt,
    wird abgelehnt. Ohne das nuetzt ein abgefangener Code dem Angreifer noch
    dreissig Sekunden lang - und genau so lange braucht niemand, um ihn
    weiterzureichen.
    """
    geheimnis = geheimnis_lesen(benutzer)
    if not geheimnis:
        return False

    totp = pyotp.TOTP(geheimnis, interval=SCHRITT_SEKUNDEN)
    jetzt = int(time.time())
    aktueller_schritt = jetzt // SCHRITT_SEKUNDEN

    for versatz in range(-TOLERANZ, TOLERANZ + 1):
        schritt = aktueller_schritt + versatz
        if schritt <= benutzer.totp_letzter_schritt:
            continue
        if secrets.compare_digest(totp.at(schritt * SCHRITT_SEKUNDEN), code):
            benutzer.totp_letzter_schritt = schritt
            db.commit()
            return True
    return False


# --- Wiederherstellungscodes ------------------------------------------- #


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").upper().encode("ascii")).hexdigest()


def _code_erzeugen() -> str:
    """Zehn Zeichen aus einem Alphabet ohne Verwechslungen, in zwei Gruppen.

    Ohne 0/O und 1/I/L: Diese Codes werden abgeschrieben, oft von Papier, oft
    in einem Moment, in dem man ohnehin schon Aerger hat.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    roh = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{roh[:5]}-{roh[5:]}"


def codes_neu(db: Session, benutzer: Benutzer) -> list[str]:
    """Neue Codes erzeugen, alte verwerfen. Rueckgabe **einmalig** im Klartext."""
    for alt in list(benutzer.codes):
        db.delete(alt)

    klartexte = [_code_erzeugen() for _ in range(ANZAHL_CODES)]
    for code in klartexte:
        db.add(Wiederherstellungscode(benutzer_id=benutzer.id, code_hash=_hash(code)))
    db.commit()
    logger.info("New recovery codes were generated for a user.")
    return klartexte


def code_einloesen(db: Session, benutzer: Benutzer, eingabe: str) -> bool:
    """Einen Wiederherstellungscode pruefen und verbrauchen.

    ⚠️ Verbraucht heisst verbraucht - der Eintrag bleibt stehen und wird
    markiert. Ihn zu loeschen waere bequemer und verschenkte die Auskunft,
    wie viele noch da sind.
    """
    gesucht = _hash(eingabe)
    for zeile in benutzer.codes:
        if zeile.verbraucht is None and secrets.compare_digest(zeile.code_hash, gesucht):
            from ..models import utcnow

            zeile.verbraucht = utcnow()
            db.commit()
            logger.info("A recovery code was used.")
            return True
    return False


def offene_codes(benutzer: Benutzer) -> int:
    return sum(1 for c in benutzer.codes if c.verbraucht is None)


def abschalten(db: Session, benutzer: Benutzer) -> None:
    """Den zweiten Faktor entfernen - Geheimnis, Codes und Zeitschritt.

    ⚠️ **Nicht nur den Haken umlegen.** Bliebe das Geheimnis liegen, waere der
    alte QR-Code nach dem Wiedereinschalten weiter gueltig - samt allem, was
    ihn inzwischen abfotografiert hat. Und ein alter Wiederherstellungscode
    aus einem Zettel von vor einem Jahr wuerde wieder gelten.

    ⚠️ **Der Zeitschritt muss ebenfalls zurueck.** Sonst weist der neu
    eingerichtete Faktor jeden Code ab, dessen Zeitschritt kleiner ist als der
    zuletzt gemerkte - beim naechsten Einschalten also bis zu einer halben
    Minute lang jeden. Das sieht aus wie ein kaputter QR-Code.
    """
    benutzer.totp_geheimnis = ""
    benutzer.totp_bestaetigt = False
    benutzer.totp_letzter_schritt = 0
    for code in list(benutzer.codes):
        db.delete(code)
    db.commit()
