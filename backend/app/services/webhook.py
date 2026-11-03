"""Webhook — eine Aufgabe als POST an eine eigene Adresse, sonst nichts.

Was eine Verbindung ist, wem sie gehoert und wann gesendet wird, steht in
``aufgabenziele.py``. Hier steht nur, wie der POST aussieht und wohin er darf.

Gewuenscht in Issue #17: Ein selbstgebautes Programm soll Aufgaben aus Mails
bekommen, ohne dass nexmail jedes Programm einzeln kennen muss.

⚠️ **Ein Webhook laesst sich nicht fragen.** Bei Todoist sieht nexmail alle
zehn Minuten nach, was dort erledigt wurde. Hier gibt es nichts zu fragen:
Der Haken bleibt in nexmail, und Abhaken hier geht als ``task.completed``
hinaus. Der Empfaenger kann umgekehrt ueber ``/api/v1`` abhaken
(``routers/api_v1.py``), mit einem Schluessel, der das darf.

⚠️ **Unterschrieben, mit Zeitstempel.** ``X-Nexmail-Signature`` ist
``sha256=`` plus HMAC-SHA256 ueber ``<Zeitstempel>.<Rumpf>``, der Zeitstempel
steht in ``X-Nexmail-Timestamp``. Ohne ihn liesse sich ein mitgeschnittener
Aufruf beliebig oft wiederholen.

⚠️ **Die Adresse tippt ein Benutzer ein**, also gilt dieselbe Pruefung wie
bei den Kalendern: nichts im eigenen Netz, solange der Betreiber es nicht
freigibt (``netzfreigabe.py``), und der eigene Rechner nie. Weiterleitungen
werden nicht verfolgt: Sonst zeigte eine gepruefte Adresse per 302 doch ins
Heimnetz.

⚠️ **Der Text der Mail geht nur hinaus, wenn der Betreiber es erlaubt hat**
(``SCHALTER_TEXT``) und der Benutzer es an der Verbindung eingeschaltet hat.
Auf einer geteilten Installation kann jeder Benutzer eine Adresse eintragen;
ob Mailtext das Haus verlaesst, entscheidet der Betreiber.

⚠️ **Kein Rumpf einer Antwort geht ins Protokoll**, nur der Status.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from . import netzfreigabe
from .bildvermittler import Abgelehnt, adresse_pruefen
from ..db import einstellung_lesen, einstellung_schreiben
from ..meldung import Meldung

logger = logging.getLogger("nexmail.webhook")

#: ⚠️ **Kurz.** Hier wartet ein Mensch vor dem Fenster „Zu Aufgabe machen".
ZEITGRENZE = 10.0

#: Mehr als eine Kennung und ein Link steht in einer Antwort nicht. Was
#: groesser ist, wird nicht gelesen.
MAX_ANTWORT = 64_000

MAX_ADRESSE = 500
MAX_GEHEIMNIS = 200

#: Der Riegel des Betreibers fuer den Text der Mail.
SCHALTER_TEXT = "webhook_mailtext_erlaubt"

#: Die Liste, die eine Webhook-Verbindung anbietet. Es gibt nur diese eine.
LISTE = "webhook"

#: Fuer die Tests: ``httpx.MockTransport``. Im Betrieb immer ``None``.
TRANSPORT: httpx.BaseTransport | None = None


class WebhookFehler(Meldung, RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class Zugang:
    url: str
    geheimnis: str


@dataclass
class Antwort:
    """Was der Empfaenger auf ``task.created`` sagt. Beides darf fehlen."""

    id: str = ""
    url: str = ""


def mailtext_erlaubt(db: Session) -> bool:
    return einstellung_lesen(db, SCHALTER_TEXT, "0") == "1"


def mailtext_erlauben(db: Session, ja: bool) -> bool:
    einstellung_schreiben(db, SCHALTER_TEXT, "1" if ja else "0")
    logger.info("The operator %s mail text in webhooks.", "allowed" if ja else "blocked")
    return ja


def neues_geheimnis() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def zugang_lesen(roh: str) -> Zugang:
    try:
        daten = json.loads(roh)
        return Zugang(url=str(daten["url"]), geheimnis=str(daten["geheimnis"]))
    except (ValueError, TypeError, KeyError) as fehler:
        raise WebhookFehler("webhook_zugang_kaputt") from fehler


def zugang_schreiben(zugang: Zugang) -> str:
    return json.dumps({"url": zugang.url, "geheimnis": zugang.geheimnis})


def ziel_name(url: str) -> str:
    """Wie die eine Liste heisst: der Rechner aus der Adresse."""
    return urlsplit(url).hostname or url


# --- Wohin ------------------------------------------------------------------ #


def _eigener_rechner(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        adresse = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if isinstance(adresse, ipaddress.IPv6Address) and adresse.ipv4_mapped is not None:
        adresse = adresse.ipv4_mapped
    return adresse.is_loopback or adresse.is_unspecified


def adresse_bereinigen(url: str) -> str:
    """Die Form pruefen, ohne aufzuloesen. Fuer das Speichern."""
    url = url.strip()
    teile = urlsplit(url)
    if len(url) > MAX_ADRESSE or teile.scheme not in ("http", "https") or not teile.hostname:
        raise WebhookFehler("webhook_adresse_ungueltig")
    if teile.username or teile.password:
        # ⚠️ Zugangsdaten in der Adresse stuenden spaeter im Klartext in der
        # Einstellungsseite. Fuer die Herkunft gibt es die Unterschrift.
        raise WebhookFehler("webhook_adresse_ungueltig")
    # ⚠️ **Eigener Satz fuer localhost.** In Docker ist ``localhost`` der
    # Container selbst, nicht der Rechner, auf dem er laeuft (Issue #17). Wer
    # dafuer „im eigenen Netz gesperrt" liest, sucht den Fehler am Schalter.
    if _eigener_rechner(teile.hostname.lower()):
        raise WebhookFehler("webhook_adresse_localhost")
    return url


def _pruefen(url: str) -> None:
    """⚠️ Dieselbe Pruefung wie bei den Kalendern (``caldav._pruefen``)."""
    adresse_bereinigen(url)
    try:
        adresse_pruefen(url)
        return
    except Abgelehnt as f:
        grund = f
    if str(grund) == "bild_adresse_im_eigenen_netz" and netzfreigabe.erlaubt_jetzt():
        try:
            adresse_pruefen(url, eigenes_netz=True)
            return
        except Abgelehnt as f:
            grund = f
    # ⚠️ Nicht alles auf „im eigenen Netz" abbilden, wie bei den Kalendern:
    # Ein Name, den es nicht gibt, ist ein Tippfehler, kein gesperrtes Netz.
    if str(grund) == "bild_adresse_im_eigenen_netz":
        raise WebhookFehler("webhook_adresse_im_eigenen_netz") from grund
    if str(grund) == "bild_adresse_unerlaubt":
        raise WebhookFehler("webhook_adresse_ungueltig") from grund
    raise WebhookFehler("webhook_nicht_erreichbar") from grund


# --- Senden ------------------------------------------------------------------ #


def unterschrift(geheimnis: str, zeitstempel: str, rumpf: bytes) -> str:
    """``sha256=<hex>`` ueber ``<Zeitstempel>.<Rumpf>`` — so prueft es auch
    der Empfaenger nach (README, Abschnitt Webhook)."""
    nachricht = zeitstempel.encode() + b"." + rumpf
    return "sha256=" + hmac.new(geheimnis.encode(), nachricht, hashlib.sha256).hexdigest()


def senden(zugang: Zugang, ereignis: str, daten: dict) -> Antwort:
    """Ein Ereignis an den Empfaenger. Alles ausser 2xx ist ein Fehler.

    ⚠️ **Die Adresse wird bei jedem Senden neu geprueft**, nicht nur beim
    Speichern: Der Betreiber kann das eigene Netz inzwischen wieder
    gesperrt haben, und ein Name kann heute woandershin zeigen als gestern.
    """
    # ⚠️ Wie bei ``caldav._klient``: Mit eigenem Transport (nur in Tests) gibt
    # es kein Netz, also auch nichts aufzuloesen.
    if TRANSPORT is None:
        _pruefen(zugang.url)
    else:
        adresse_bereinigen(zugang.url)

    rumpf = json.dumps(
        {"event": ereignis, "sent_at": _jetzt_iso(), **daten},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    zeitstempel = str(int(time.time()))
    kopf = {
        "content-type": "application/json",
        "user-agent": "nexmail",
        "x-nexmail-event": ereignis,
        "x-nexmail-delivery": uuid.uuid4().hex,
        "x-nexmail-timestamp": zeitstempel,
        "x-nexmail-signature": unterschrift(zugang.geheimnis, zeitstempel, rumpf),
    }
    try:
        with httpx.Client(
            timeout=ZEITGRENZE, follow_redirects=False, transport=TRANSPORT
        ) as klient:
            with klient.stream("POST", zugang.url, content=rumpf, headers=kopf) as antwort:
                status = antwort.status_code
                inhalt = b""
                if 200 <= status < 300:
                    for stueck in antwort.iter_bytes():
                        inhalt += stueck
                        if len(inhalt) > MAX_ANTWORT:
                            inhalt = b""
                            break
    except httpx.TimeoutException as fehler:
        logger.info("A webhook did not answer in time: %s", type(fehler).__name__)
        raise WebhookFehler("webhook_zeitueberschreitung", sekunden=int(ZEITGRENZE)) from fehler
    except httpx.HTTPError as fehler:
        logger.info("A webhook was unreachable: %s", type(fehler).__name__)
        raise WebhookFehler("webhook_nicht_erreichbar") from fehler

    if not 200 <= status < 300:
        logger.info("A webhook answered HTTP %s to %s.", status, ereignis)
        if 300 <= status < 400:
            raise WebhookFehler("webhook_weiterleitung", status=status)
        raise WebhookFehler("webhook_fehler", status=status)
    return _antwort_lesen(inhalt)


def _antwort_lesen(inhalt: bytes) -> Antwort:
    """``id`` und ``url`` aus der Antwort, wenn der Empfaenger welche nennt.

    ⚠️ **Eine Antwort ohne JSON ist kein Fehler.** Ein schlichtes 204 oder
    ``ok`` reicht; dann gibt es eben keinen Link in nexmail.
    """
    try:
        daten = json.loads(inhalt) if inhalt.strip() else {}
    except ValueError:
        return Antwort()
    if not isinstance(daten, dict):
        return Antwort()
    kennung = daten.get("id")
    kennung = str(kennung)[:64] if isinstance(kennung, (str, int)) and not isinstance(kennung, bool) else ""
    url = daten.get("url")
    # ⚠️ Nur http(s): Der Link steht spaeter als ``href`` in der Oberflaeche,
    # und ``javascript:`` aus einer fremden Antwort gehoert dort nicht hin.
    if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https") or len(url) > 2000:
        url = ""
    return Antwort(id=kennung, url=url)


def _jetzt_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
