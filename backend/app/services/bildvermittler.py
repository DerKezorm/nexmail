"""Bilder aus fremden Mails holen — der Server, nicht der Browser.

Der Knopf „Bilder anzeigen" hat von 0.1.0 bis 0.3.0 sichtbar nichts getan.
Die Ursache war die Inhaltsregel, nicht der Knopf: Der Lesebereich zeigt die
Mail in einem ``<iframe sandbox="" srcdoc>``, dieser Rahmen erbt die Regel der
Anwendung, und dort steht ``img-src 'self' data: blob:``. Der Knopf hat die
echten ``https``-Adressen wieder eingehaengt, und der Browser hat sie
abgewiesen — ohne Meldung, weil aus einem abgeschotteten Rahmen keine
Verstossmeldung herauskommt.

⚠️ **Die Regel zu lockern waere die falsche Behebung gewesen.** Sie gaebe
genau die Zaehlpixel frei, die nexmail blockt. Stattdessen holt der Server die
Bilder und legt sie unter einer eigenen Adresse ab; die ist ``'self'``, und
damit ist die Regel zufrieden.

**Gemessen am 02.09.2026 im echten Chromium**, weil beide Annahmen haetten
falsch sein koennen:

* Ein Bild auf **eigener** Adresse laedt im ``sandbox=""``-Rahmen. ``'self'``
  greift dort, obwohl der Rahmen eine undurchsichtige Herkunft hat.
* Das Sitzungs-Cookie faehrt beim Bildabruf **nicht** mit — ``SameSite=Strict``
  und fremde Herkunft. Die signierte Adresse ist deshalb keine Kuer, sondern
  der einzige Weg: Der Abruf muss sich selbst ausweisen.

⚠️ **In der Entwicklungsumgebung gibt es die Inhaltsregel gar nicht.** Vite
liefert das Dokument, den Kopf setzt nur das Backend. Wer den Fehler dort
suchte, fand ihn nie. Seit dem 02.09.2026 setzt der Vite-Server dieselbe Regel
— siehe ``frontend/vite.config.ts``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("nexmail.bildvermittler")

#: Wie lange eine ausgestellte Bildadresse gilt.
#:
#: ⚠️ **Eine Stunde ist ein Tausch, kein Zufallswert.** Kuerzer hiesse: Wer
#: eine Mail zweimal oeffnet, funkt den Absender zweimal an, weil der Browser
#: die Adresse nicht wiedererkennt. Laenger hiesse: Eine abgefangene Adresse
#: laesst sich laenger benutzen — allerdings nur fuer *dieses eine Bild*, denn
#: die Unterschrift bindet die Adresse mit.
GUELTIG_SEKUNDEN = 3600

#: Obergrenze je Bild. ⚠️ Ohne sie macht ein Absender aus einer Mail einen
#: Dauerdownload, den nexmail brav mitlaeuft.
MAX_BYTES = 5 * 1024 * 1024

#: Wie lange auf den fremden Server gewartet wird. Kurz, denn es haengt ein
#: Mensch davor, der auf einen Knopf gedrueckt hat.
ZEITGRENZE = 10.0

#: Wie viele Weiterleitungen mitgegangen werden. Bildadressen in Newslettern
#: sind fast immer Zaehl-Weiterleitungen; ohne das laedt kein Newsletter.
#: ⚠️ **Jeder Sprung wird neu geprueft** — sonst waere die Pruefung des ersten
#: Sprungs eine Zierde.
MAX_SPRUENGE = 5

#: ⚠️ **SVG nicht.** Es ist das einzige Bildformat mit einem XML-Parser
#: dahinter, und Mails brauchen es praktisch nie. In einem ``<img>`` fuehrt
#: auch ein SVG nichts aus — aber der Gewinn ist so klein, dass die Flaeche
#: sich nicht lohnt.
VERBOTENE_TYPEN = {"image/svg+xml", "image/svg"}


class Abgelehnt(Exception):
    """Der Abruf ist nicht zustande gekommen — mit einer KENNUNG als Grund.

    ⚠️ **Kennung, kein deutscher Satz.** Der Server benennt, die Oberflaeche
    uebersetzt — wie bei OIDC und den Schlagworten. Ein deutscher ``detail``
    bleibt auf Englisch deutsch.
    """

    def __init__(self, kennung: str) -> None:
        super().__init__(kennung)
        self.kennung = kennung


# --- Die signierte Adresse ------------------------------------------------ #


def _schluessel() -> bytes:
    """Zum Signieren der Bildadressen — aus dem Datenschluessel abgeleitet.

    Dasselbe Muster wie beim OIDC-Anlaufcookie: ein eigener Kontext, damit
    eine Unterschrift aus dem einen Bereich im anderen nichts wert ist.
    """
    from .. import crypto

    return hashlib.sha256(b"bild-vermittler" + crypto._dek()).digest()


def marke_ausstellen(bild_url: str, jetzt: float | None = None) -> str:
    """Eine Adresse in eine signierte Marke packen.

    ⚠️ **Signiert, nicht verschluesselt.** Die Adresse ist kein Geheimnis —
    sie steht in der Mail. Sie darf nur nicht **veraendert** werden: Wer sie
    faelschen koennte, haette aus nexmail einen offenen Vermittler gemacht,
    der jede beliebige Adresse abruft.

    ⚠️ **Die Marke haengt nicht am Benutzer.** Sie kann es nicht: Der Abruf
    kommt aus dem abgeschotteten Rahmen und bringt kein Sitzungs-Cookie mit.
    Das ist vertretbar, weil eine Marke genau *ein* Bild oeffnet und nichts
    ueber den Bestand verraet — und weil sie ohnehin nur ausgestellt wird, wer
    angemeldet ist und die Mail lesen darf.
    """
    inhalt = json.dumps(
        {"u": bild_url, "ab": int(jetzt if jetzt is not None else time.time())},
        separators=(",", ":"),
    ).encode()
    koerper = base64.urlsafe_b64encode(inhalt).decode().rstrip("=")
    unterschrift = hmac.new(_schluessel(), koerper.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{koerper}.{unterschrift}"


def marke_pruefen(marke: str, jetzt: float | None = None) -> str:
    """Die Adresse zurueck — oder ``Abgelehnt``.

    Abgelaufen und gefaelscht bekommen **dieselbe** Antwort. Der Unterschied
    hilft nur dem, der probiert.
    """
    if "." not in marke:
        raise Abgelehnt("bild_marke_ungueltig")
    koerper, _, unterschrift = marke.rpartition(".")
    erwartet = hmac.new(_schluessel(), koerper.encode(), hashlib.sha256).hexdigest()[:32]
    # ⚠️ Zeitunabhaengiger Vergleich — ein ``==`` verraet ueber die Laufzeit,
    # wie viele Zeichen stimmen.
    if not hmac.compare_digest(unterschrift, erwartet):
        raise Abgelehnt("bild_marke_ungueltig")
    try:
        fehlt = "=" * (-len(koerper) % 4)
        daten = json.loads(base64.urlsafe_b64decode(koerper + fehlt))
        adresse = str(daten["u"])
        ab = int(daten["ab"])
    except (ValueError, TypeError, KeyError):
        raise Abgelehnt("bild_marke_ungueltig") from None
    if (jetzt if jetzt is not None else time.time()) - ab > GUELTIG_SEKUNDEN:
        raise Abgelehnt("bild_marke_ungueltig")
    return adresse


# --- Wohin nexmail greifen darf ------------------------------------------ #


def _ist_erreichbar_von_aussen(roh: str) -> bool:
    """Eine IP, die im Internet steht — und nicht im Wohnzimmer.

    ``is_global`` allein reicht nicht: Es sagt bei manchen Sonderbereichen
    (etwa ``0.0.0.0/8``) nicht das, was man erwartet. Deshalb zusaetzlich die
    ausdruecklichen Fragen.
    """
    try:
        adresse = ipaddress.ip_address(roh)
    except ValueError:
        return False
    if isinstance(adresse, ipaddress.IPv6Address) and adresse.ipv4_mapped is not None:
        adresse = adresse.ipv4_mapped
    return not (
        adresse.is_private
        or adresse.is_loopback
        or adresse.is_link_local
        or adresse.is_multicast
        or adresse.is_reserved
        or adresse.is_unspecified
    )


def adresse_pruefen(url: str) -> None:
    """Darf nexmail hier hingreifen?

    ⚠️ **Der Vermittler waere sonst eine Fernbedienung fuers Heimnetz.** Eine
    Mail mit ``<img src="http://192.168.x.x/…">`` loest beim Klick auf „Bilder
    anzeigen" einen Abruf dorthin aus — nexmail steht im selben Netz, der
    Absender nicht. Die Antwort sieht er nie, aber der Abruf passiert, und das
    genuegt bei einem Geraet, das auf ein blosses GET reagiert.

    Am 02.09.2026 entschieden: blocken. Der Preis ist bekannt und steht in
    SPAETER.md — Mails aus dem eigenen Netz (Radarr, Home Assistant) zeigen
    ihre Bilder nicht.

    ⚠️ **Ein Restrisiko bleibt und soll hier stehen, statt verschwiegen zu
    werden:** Zwischen dieser Pruefung und dem Abruf loest httpx den Namen ein
    zweites Mal auf. Wer beide Antworten steuert, kann dazwischen umschalten
    (DNS-Rebinding). Das sauber zu schliessen hiesse, die Verbindung selbst an
    die gepruefte IP zu binden — ein eigener Transport, mit eigenen Fallen bei
    TLS. Gemessen am Gewinn (ein blindes GET ins eigene Netz) ist das hier
    nicht bezahlt worden.
    """
    teile = urlsplit(url)
    if teile.scheme not in ("http", "https"):
        raise Abgelehnt("bild_adresse_unerlaubt")
    host = teile.hostname
    if not host:
        raise Abgelehnt("bild_adresse_unerlaubt")

    # Eine IP direkt in der Adresse wird direkt geprueft — getaddrinfo wuerde
    # sie nur zurueckreichen, aber der Weg ueber den Namensdienst kann
    # scheitern, und dann saehe eine verbotene IP wie ein Netzfehler aus.
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        if not _ist_erreichbar_von_aussen(host.strip("[]")):
            raise Abgelehnt("bild_adresse_im_eigenen_netz")
        return

    try:
        aufloesung = socket.getaddrinfo(host, None)
    except OSError:
        raise Abgelehnt("bild_nicht_erreichbar") from None
    if not aufloesung:
        raise Abgelehnt("bild_nicht_erreichbar")
    # ⚠️ **Alle Antworten, nicht die erste.** Ein Name darf auf mehrere
    # Adressen zeigen; wer nur die erste prueft, laesst sich mit einer
    # zweiten ins Heimnetz schicken.
    for eintrag in aufloesung:
        if not _ist_erreichbar_von_aussen(eintrag[4][0]):
            raise Abgelehnt("bild_adresse_im_eigenen_netz")


# --- Der Abruf ------------------------------------------------------------ #


def holen(url: str) -> tuple[bytes, str]:
    """Ein Bild holen. Rueckgabe: Inhalt und MIME-Typ.

    ⚠️ **Ohne Kopfzeilen aus der Mail.** Kein Verweis auf die Herkunft, kein
    Keks, keine Kennung des Lesers. Was der Absender erfaehrt, ist die IP
    dieses Servers und der Zeitpunkt — und dass jemand auf einen Knopf
    gedrueckt hat. Genau das steht im Hinweisbalken.
    """
    ziel = url
    with httpx.Client(
        timeout=ZEITGRENZE,
        follow_redirects=False,
        headers={"user-agent": "nexmail", "accept": "image/*"},
    ) as klient:
        for _ in range(MAX_SPRUENGE + 1):
            adresse_pruefen(ziel)
            try:
                with klient.stream("GET", ziel) as antwort:
                    if antwort.is_redirect:
                        weiter = antwort.headers.get("location")
                        if not weiter:
                            raise Abgelehnt("bild_nicht_erreichbar")
                        ziel = str(httpx.URL(ziel).join(weiter))
                        continue
                    if antwort.status_code >= 400:
                        raise Abgelehnt("bild_nicht_erreichbar")
                    typ = antwort.headers.get("content-type", "").split(";")[0].strip().lower()
                    if not typ.startswith("image/") or typ in VERBOTENE_TYPEN:
                        raise Abgelehnt("bild_kein_bild")
                    inhalt = bytearray()
                    for stueck in antwort.iter_bytes():
                        inhalt += stueck
                        # ⚠️ **Waehrend des Lesens abbrechen, nicht danach.**
                        # ``content-length`` ist eine Behauptung des fremden
                        # Servers; wer ihr glaubt, hat die Grenze nicht.
                        if len(inhalt) > MAX_BYTES:
                            raise Abgelehnt("bild_zu_gross")
                    return bytes(inhalt), typ
            except httpx.HTTPError:
                raise Abgelehnt("bild_nicht_erreichbar") from None
    raise Abgelehnt("bild_nicht_erreichbar")
