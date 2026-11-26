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
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .. import crypto
from ..db import einstellung_lesen, einstellung_schreiben
from ..meldung import Meldung

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


class PostFehler(Meldung):
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


def senden(db: Session, an: str, betreff: str, text: str, html: str = "") -> None:  # noqa: ARG001
    """⚠️ **Seit post 1.1.0 verschickt nexmail hier nichts mehr.** Jede Systemmail geht ueber das Mailmodul
    (``services/post_store``, ``services/kontenpost``), samt Probemail (die Testmail des Moduls, mit Logo und in der
    Sprache der Seite). Der Name bleibt als der Punkt, an dem die Tests die Post abfangen (``tests/conftest.py``,
    ``post_bruecke``: das SMTP des Moduls endet in Tests hier; der Test „Bestand" faengt dort seine Post)."""
    logger.debug("A system mail reached the test sink.")
