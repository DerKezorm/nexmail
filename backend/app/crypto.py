"""Verschluesselung der Geheimnisse, die in der Datenbank liegen.

Postfach-Passwoerter, TOTP-Geheimnisse, spaeter OIDC-Client-Secrets: Nichts
davon darf im Klartext in der SQLite-Datei stehen.

Zwei Stufen, und das ist der Kern
---------------------------------
**KEK** (Schluessel-Schluessel) kommt aus ``NEXMAIL_SECRET_KEY`` oder aus
``data/secret.key``. **DEK** (Daten-Schluessel) sind 32 zufaellige Bytes, die
einmal erzeugt und **mit dem KEK verpackt in der Datenbank** abgelegt werden.
Verschluesselt wird ausschliesslich mit dem DEK.

⚠️ **Warum nicht einfach ein Schluessel wie in Nexview.** Dort wird direkt mit
dem KEK verschluesselt, und der Preis steht als laute Warnung im Code: Wer ihn
aendert oder verliert, kann keinen einzigen gespeicherten Zugang mehr lesen und
muss alles neu eintragen. Zwei Betreiber haben genau das als Raetsel gemeldet.
Hier kostet ein Wechsel des KEK **eine Umverpackung** - der DEK bleibt, alle
verschluesselten Werte bleiben gueltig.

⚠️ **AES-GCM mit Zusatzdaten, nicht Fernet.** Fernet kann keine Zusatzdaten.
Ohne sie liesse sich ein verschluesseltes Passwort in der Datenbank von einem
Postfach auf ein anderes kopieren, und die Entschluesselung merkte nichts. Der
Kontext (``konto:<id>:imap_passwort``) faehrt deshalb als AAD mit: Er wird nicht
gespeichert, aber jede Entschluesselung prueft ihn mit.

⚠️ **Was das alles nicht leistet.** Wer Dateizugriff auf ``/data`` **und** den
KEK hat, hat die Postfaecher. Daran aendert kein Schluesselaufbau etwas,
solange der Abgleich unbeaufsichtigt laufen soll. Wirksam ist nur, den KEK per
``NEXMAIL_SECRET_KEY`` aus dem Datenverzeichnis herauszuziehen.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings
from .meldung import Meldung

logger = logging.getLogger("nexmail.crypto")

#: Kennzeichnet das Format. Ein spaeterer Wechsel bekommt "v2:" und kann
#: beide lesen, statt alles auf einmal umschreiben zu muessen.
PRAEFIX = "v1:"

#: Zusatzdaten beim Verpacken des DEK. Fest, weil es nur einen gibt.
_DEK_AAD = b"nexmail-dek"

_NONCE_LAENGE = 12

_sperre = threading.Lock()
_dek_zwischenspeicher: bytes | None = None


class SchluesselFehler(Meldung, RuntimeError):
    """Der KEK passt nicht zum verpackten DEK in dieser Datenbank."""


def _kek() -> bytes:
    """32 Bytes aus dem eingestellten Geheimnis.

    Das Geheimnis darf alles sein - ein erzeugter Zufallswert oder eine von
    Hand eingetragene Zeichenkette. SHA-256 macht daraus die feste Laenge, die
    AES braucht. Das eigene Praefix trennt diesen Schluessel von allem
    anderen, was jemals aus demselben Geheimnis abgeleitet wird.
    """
    geheimnis = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexmail-kek:" + geheimnis).digest()


def dek_verpacken(dek: bytes) -> str:
    """Den Daten-Schluessel mit dem KEK verpacken - so kommt er in die Datenbank."""
    nonce = os.urandom(_NONCE_LAENGE)
    kiste = AESGCM(_kek()).encrypt(nonce, dek, _DEK_AAD)
    return PRAEFIX + base64.b64encode(nonce + kiste).decode("ascii")


def dek_auspacken(verpackt: str) -> bytes:
    """Den Daten-Schluessel wieder herausholen.

    ⚠️ Schlaegt das fehl, ist die Lage eindeutig **und benennbar**: Diese
    Datenbank traegt einen Schluessel, den dieser Server nicht oeffnen kann.
    Genau das konnte Nexview nicht sagen - dort kam bei jedem einzelnen Wert
    still eine leere Zeichenkette zurueck, und nirgends stand, warum.
    """
    if not verpackt.startswith(PRAEFIX):
        raise SchluesselFehler("schluessel_format_unbekannt")
    roh = base64.b64decode(verpackt[len(PRAEFIX) :])
    try:
        return AESGCM(_kek()).decrypt(roh[:_NONCE_LAENGE], roh[_NONCE_LAENGE:], _DEK_AAD)
    except (InvalidTag, ValueError) as fehler:
        # ⚠️ **Hier steht bewusst ein ganzer Satz statt einer Kennung, und der
        # Wächter kennt die Ausnahme.** Diese Meldung erreicht nie eine
        # Oberfläche: Sie bricht den Start ab, bevor es eine gibt, und ein
        # Betreiber liest sie in `docker logs`. Dort gilt „englisch", nicht
        # „übersetzbar" — und sie muss ausführlich sein, weil sie den
        # teuersten Fall der ganzen Anwendung erklärt: Ohne diesen Schlüssel
        # ist jedes gespeicherte Postfach-Passwort unlesbar.
        raise SchluesselFehler(  # noqa: NXM001 - Startabbruch, siehe test_meldungen.py
            "The stored data key cannot be unwrapped with the current "
            "NEXMAIL_SECRET_KEY. Was the key changed, or was data/secret.key "
            "lost when the container was rebuilt? Restore the key file or the "
            "matching backup - the stored credentials are unreadable without it."
        ) from fehler


def dek_erzeugen() -> bytes:
    return os.urandom(32)


def dek_setzen(dek: bytes | None) -> None:
    """Den Daten-Schluessel fuer diesen Prozess merken (oder vergessen).

    Wird von ``db.init_db`` beim Start gesetzt. Getrennt gehalten, damit die
    Tests ihn austauschen koennen, ohne eine Datenbank zu brauchen.
    """
    global _dek_zwischenspeicher
    with _sperre:
        _dek_zwischenspeicher = dek


def _dek() -> bytes:
    with _sperre:
        if _dek_zwischenspeicher is None:
            raise SchluesselFehler(
                "datenschluessel_fehlt"
            )
        return _dek_zwischenspeicher


def verschluesseln(klartext: str, kontext: str) -> str:
    """Einen Wert verschluesseln.

    ``kontext`` beschreibt, wo der Wert hingehoert - ``konto:<id>:imap_passwort``.
    Er wird nicht gespeichert, faehrt aber als Zusatzdaten mit: Ein Wert, den
    jemand an eine andere Stelle kopiert, laesst sich dort nicht entschluesseln.
    """
    nonce = os.urandom(_NONCE_LAENGE)
    kiste = AESGCM(_dek()).encrypt(nonce, klartext.encode("utf-8"), kontext.encode("utf-8"))
    return PRAEFIX + base64.b64encode(nonce + kiste).decode("ascii")


def entschluesseln(wert: str, kontext: str) -> str:
    """Einen Wert entschluesseln. Leerer Eingabewert bleibt leer."""
    if not wert:
        return ""
    if not wert.startswith(PRAEFIX):
        raise SchluesselFehler("wert_unverschluesselt")
    roh = base64.b64decode(wert[len(PRAEFIX) :])
    try:
        klar = AESGCM(_dek()).decrypt(
            roh[:_NONCE_LAENGE], roh[_NONCE_LAENGE:], kontext.encode("utf-8")
        )
    except (InvalidTag, ValueError) as fehler:
        # Hier hilft kein stiller Rueckfall. Entweder der Schluessel passt
        # nicht, oder der Wert steht an einer anderen Stelle als beim
        # Verschluesseln - beides muss laut sein.
        logger.warning("A stored value in %s could not be decrypted.", kontext)
        raise SchluesselFehler("wert_unlesbar") from fehler
    return klar.decode("utf-8")


def maskiert(wert: str) -> str:
    """Darstellung fuer die Oberflaeche, z. B. ``••••3f2a``."""
    if not wert:
        return ""
    if len(wert) <= 4:
        return "••••"
    return "••••" + wert[-4:]
