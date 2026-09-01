"""Der Systempostausgang — Mail, die **nexmail selbst** verschickt.

Bisher verschickte nexmail nur Post, die jemand geschrieben hat, ueber dessen
eigenes Postfach. Fuer Einladungen braucht es etwas anderes: eine Mail von der
Anwendung an einen Menschen, der noch gar kein Konto hat.

⚠️ **Nicht das Postfach des Betreibers dafuer benutzen.** Das waere schnell
gebaut und dauerhaft falsch: Der Betreiber koennte sein Postfach nicht mehr
entfernen, ohne die Einladungen mitzunehmen; jede Systemmail kaeme von seiner
privaten Adresse; und ein Homelab ohne eingerichtetes Postfach koennte
niemanden einladen. Der Systempostausgang steht deshalb fuer sich.

⚠️ **Er darf fehlen.** Wer allein arbeitet, braucht ihn nie. Alles, was ihn
voraussetzt, sagt das vorher — statt beim Absenden zu scheitern.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from .. import crypto
from ..db import einstellung_lesen, einstellung_schreiben
from . import mailvorlage

logger = logging.getLogger("nexmail.systempost")

#: ⚠️ Ein fester Kontext, kein Datensatz-Schluessel: Der Systempostausgang gibt
#: es genau einmal, er haengt an keiner Zeile mit eigener Kennung.
KONTEXT = "system:smtp_passwort"

S_SERVER = "system_smtp_server"
S_PORT = "system_smtp_port"
S_SICHERHEIT = "system_smtp_sicherheit"
S_BENUTZER = "system_smtp_benutzer"
S_PASSWORT = "system_smtp_passwort"
S_ABSENDER = "system_smtp_absender"
S_ABSENDERNAME = "system_smtp_absendername"

ZEITGRENZE = 30


@dataclass
class Postausgang:
    server: str = ""
    port: int = 587
    sicherheit: str = "starttls"
    benutzer: str = ""
    absender: str = ""
    absendername: str = "nexmail"

    @property
    def eingerichtet(self) -> bool:
        return bool(self.server and self.absender)


class PostFehler(Exception):
    """Der Versand ging nicht — mit einem Satz, den man dem Betreiber zeigt."""


def lesen(db: Session) -> Postausgang:
    roher_port = einstellung_lesen(db, S_PORT)
    return Postausgang(
        server=einstellung_lesen(db, S_SERVER),
        port=int(roher_port) if roher_port.isdigit() else 587,
        sicherheit=einstellung_lesen(db, S_SICHERHEIT) or "starttls",
        benutzer=einstellung_lesen(db, S_BENUTZER),
        absender=einstellung_lesen(db, S_ABSENDER),
        absendername=einstellung_lesen(db, S_ABSENDERNAME) or "nexmail",
    )


def schreiben(db: Session, angaben: Postausgang, passwort: str | None) -> None:
    """Speichern. ``passwort is None`` heisst **unveraendert**, nicht leer.

    ⚠️ Dieselbe Regel wie bei den Postfaechern: Die Oberflaeche kann ein
    gespeichertes Passwort nicht anzeigen und schickt deshalb nichts, wenn
    niemand das Feld angefasst hat. Wuerde das als „leer" gelesen, verloere
    jeder seinen Zugang, der nur den Absendernamen aendert.
    """
    einstellung_schreiben(db, S_SERVER, angaben.server.strip())
    einstellung_schreiben(db, S_PORT, str(angaben.port))
    einstellung_schreiben(db, S_SICHERHEIT, angaben.sicherheit)
    einstellung_schreiben(db, S_BENUTZER, angaben.benutzer.strip())
    einstellung_schreiben(db, S_ABSENDER, angaben.absender.strip())
    einstellung_schreiben(db, S_ABSENDERNAME, angaben.absendername.strip())
    if passwort is not None:
        einstellung_schreiben(
            db, S_PASSWORT, crypto.verschluesseln(passwort, KONTEXT) if passwort else ""
        )


def passwort_lesen(db: Session) -> str:
    roh = einstellung_lesen(db, S_PASSWORT)
    return crypto.entschluesseln(roh, KONTEXT) if roh else ""


def senden(db: Session, an: str, betreff: str, text: str, html: str = "") -> None:
    """Eine Systemmail verschicken. Wirft ``PostFehler`` mit klarem Satz.

    ⚠️ **Der Textteil ist Pflicht, der HTML-Teil eine Zugabe.** Wer seinen
    Client auf Nur-Text stellt — und in dieser Zielgruppe tun das einige —
    bekaeme sonst eine leere Mail. Deshalb ``multipart/alternative``: erst der
    Text, dann das HTML.

    ⚠️ **Was das HTML mitbringt, haengt an der Mail.** Ein Bild von einer
    fremden Adresse waere ein Zaehlpixel — nexmail klinkt genau solche in
    fremder Post aus. Siehe ``mailvorlage``.
    """
    angaben = lesen(db)
    if not angaben.eingerichtet:
        raise PostFehler(
            "Es ist kein Postausgang für nexmail selbst eingerichtet. "
            "Er steht in der Verwaltung unter „Server“."
        )

    mail = EmailMessage()
    mail["From"] = formataddr((angaben.absendername, angaben.absender))
    mail["To"] = an
    mail["Subject"] = betreff
    mail.set_content(text)
    if html:
        mailvorlage.anhaengen(mail, html)

    try:
        if angaben.sicherheit == "ssl":
            verbindung = smtplib.SMTP_SSL(angaben.server, angaben.port, timeout=ZEITGRENZE)
        else:
            verbindung = smtplib.SMTP(angaben.server, angaben.port, timeout=ZEITGRENZE)
            if angaben.sicherheit == "starttls":
                verbindung.starttls(context=ssl.create_default_context())
    except Exception as fehler:  # noqa: BLE001
        logger.warning("System mailer could not connect to %s:%s", angaben.server, angaben.port)
        raise PostFehler(
            f"Der Postausgang {angaben.server}:{angaben.port} ist nicht erreichbar."
        ) from fehler

    try:
        if angaben.benutzer:
            try:
                verbindung.login(angaben.benutzer, passwort_lesen(db))
            except smtplib.SMTPAuthenticationError as fehler:
                raise PostFehler(
                    "Der Postausgang hat Benutzername oder Passwort abgewiesen."
                ) from fehler
        verbindung.send_message(mail)
    except PostFehler:
        raise
    except smtplib.SMTPRecipientsRefused as fehler:
        # ⚠️ **Der haeufigste Fall, und der mit der nutzlosesten Meldung.**
        # Ein Tippfehler in der Adresse sah am 01.09.2026 aus wie „Die Mail
        # liess sich nicht absenden" — also wie ein kaputter Postausgang. Der
        # Server sagt genau, was er nicht mag; das gehoert weitergereicht.
        grund = next(iter(fehler.recipients.values()), (0, b""))
        text = grund[1].decode("utf-8", "replace") if isinstance(grund[1], bytes) else str(grund[1])
        raise PostFehler(
            f"Der Postausgang hat den Empfänger {an} abgelehnt: {text.strip() or 'ohne Angabe'}"
        ) from fehler
    except smtplib.SMTPSenderRefused as fehler:
        raise PostFehler(
            f"Der Postausgang hat die Absenderadresse {angaben.absender} abgelehnt. "
            "Meist gehört sie nicht zu dem Konto, mit dem sich nexmail anmeldet."
        ) from fehler
    except smtplib.SMTPResponseException as fehler:
        # ⚠️ **Der Satz des Servers, nicht sein Python-Abbild.** Ohne das steht
        # in der Oberflaeche „(554, b'5.7.1 Your email was rejected …')" — mit
        # Klammern, Praefix und Anfuehrungszeichen. Der Betreiber soll den Satz
        # lesen, nicht ihn aus einem Tupel herausschaelen.
        roh = fehler.smtp_error
        satz = roh.decode("utf-8", "replace") if isinstance(roh, bytes) else str(roh)
        raise PostFehler(
            f"Der Postausgang hat abgelehnt ({fehler.smtp_code}): {satz.strip()}"
        ) from fehler
    except Exception as fehler:  # noqa: BLE001
        logger.warning("System mailer failed while sending: %s", type(fehler).__name__)
        raise PostFehler(f"Die Mail ließ sich nicht absenden: {fehler}") from fehler
    finally:
        try:
            verbindung.quit()
        except Exception:  # noqa: BLE001
            pass

    # ⚠️ Die Adresse gehoert **nicht** ins Protokoll — auch nicht auf der
    # ausfuehrlichsten Stufe. Wer eingeladen wurde, ist eine persoenliche
    # Angabe, und ein Protokoll wandert in Fehlerberichte.
    logger.info("A system mail was sent.")
