"""Serverdaten finden, statt sie zu pflegen.

⚠️ **Eine handgeschriebene Anbietertabelle ist die falsche Antwort.** Sie
altert, deckt nie alle ab, und der Betreiber merkt es erst, wenn sein Postfach
nicht geht. Deshalb fragt nexmail zuerst dieselben Quellen ab wie Thunderbird:

1. ``https://autoconfig.<domaene>/mail/config-v1.1.xml`` — der Anbieter selbst
2. ``https://<domaene>/.well-known/autoconfig/...`` — dasselbe an der
   genormten Stelle
3. ``https://autoconfig.thunderbird.net/v1.1/<domaene>`` — die gepflegte
   Sammlung von Mozilla

Erst wenn alles drei nichts liefert, greift die kleine eingebaute Tabelle. Und
wenn auch die nichts weiss, traegt man die Daten von Hand ein — **das ist der
Hauptweg, nicht der Notausgang.** Jedes IMAP-Postfach muss ohne Vorwissen von
nexmail funktionieren.

⚠️ **Warum ``%EMAILLOCALPART%`` wichtig ist.** Autoconfig sagt nicht nur, wo
der Server steht, sondern auch, **was als Benutzername hineingehoert** - und
bei iCloud ist das beim Posteingang nur der Namensteil und beim Postausgang
die vollstaendige Adresse. Wer diese Felder ignoriert und ueberall die Adresse
eintraegt, kann bei iCloud lesen aber nicht senden, und die Fehlermeldung ist
in beiden Faellen dieselbe wie bei einem Tippfehler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

logger = logging.getLogger("nexmail.anbieter")

#: Kurz. Wer ein Postfach anlegt, wartet davor - und ein Anbieter, der nach
#: fuenf Sekunden nicht geantwortet hat, antwortet auch nach dreissig nicht.
ZEITGRENZE = 5.0


@dataclass
class Serverdaten:
    server: str
    port: int
    #: "ssl" oder "starttls"
    sicherheit: str
    #: "volle_adresse" oder "nur_name"
    benutzerform: str


@dataclass
class Vorschlag:
    imap: Serverdaten
    smtp: Serverdaten
    #: Woher die Angaben kommen - steht so in der Oberflaeche.
    quelle: str
    anbietername: str = ""
    #: Braucht dieser Anbieter zwingend ein app-spezifisches Passwort?
    app_passwort_noetig: bool = False
    app_passwort_wo: str = ""


def domaene_von(adresse: str) -> str:
    return adresse.split("@")[-1].strip().lower()


def benutzer_bilden(adresse: str, form: str) -> str:
    return adresse.split("@")[0] if form == "nur_name" else adresse


# --- Autoconfig ---------------------------------------------------------- #


def _socket_typ(text: str | None) -> str:
    """``SSL`` oder ``STARTTLS`` aus dem Dokument in unsere zwei Woerter."""
    wert = (text or "").strip().upper()
    if wert == "SSL":
        return "ssl"
    if wert == "STARTTLS":
        return "starttls"
    # "plain" gibt es auch. nexmail bietet es nicht an: Ein Postfach ohne
    # Verschluesselung schickt das Passwort im Klartext ueber das Netz.
    return ""


def _benutzerform(text: str | None) -> str:
    wert = (text or "").strip().upper()
    if wert == "%EMAILLOCALPART%":
        return "nur_name"
    return "volle_adresse"


def _aus_xml(roh: bytes) -> Vorschlag | None:
    """Ein Autoconfig-Dokument auswerten.

    Genommen wird der **erste** Eintrag, der verschluesselt ist. Anbieter
    listen oft mehrere; die Reihenfolge ist ihre Empfehlung.
    """
    try:
        baum = ElementTree.fromstring(roh)
    except ElementTree.ParseError:
        return None

    anbieter = baum.find(".//emailProvider")
    if anbieter is None:
        return None

    imap = None
    for knoten in anbieter.findall("incomingServer"):
        if knoten.get("type") != "imap":
            continue
        sicherheit = _socket_typ(knoten.findtext("socketType"))
        if not sicherheit:
            continue
        imap = Serverdaten(
            server=(knoten.findtext("hostname") or "").strip(),
            port=int(knoten.findtext("port") or 993),
            sicherheit=sicherheit,
            benutzerform=_benutzerform(knoten.findtext("username")),
        )
        break

    smtp = None
    for knoten in anbieter.findall("outgoingServer"):
        if knoten.get("type") != "smtp":
            continue
        sicherheit = _socket_typ(knoten.findtext("socketType"))
        if not sicherheit:
            continue
        smtp = Serverdaten(
            server=(knoten.findtext("hostname") or "").strip(),
            port=int(knoten.findtext("port") or 587),
            sicherheit=sicherheit,
            benutzerform=_benutzerform(knoten.findtext("username")),
        )
        break

    if imap is None or smtp is None or not imap.server or not smtp.server:
        return None

    return Vorschlag(
        imap=imap,
        smtp=smtp,
        quelle="autoconfig",
        anbietername=(anbieter.findtext("displayName") or anbieter.get("id") or "").strip(),
    )


def _holen(adresse_url: str) -> bytes | None:
    """Ein Dokument holen. Eigene Funktion, damit die Tests sie ersetzen koennen.

    ⚠️ Tests duerfen nicht ins Netz. Sie tauschen diese Funktion aus - und
    genau deshalb macht sie **nur** das Holen und keine Auswertung.
    """
    try:
        antwort = httpx.get(
            adresse_url,
            timeout=ZEITGRENZE,
            follow_redirects=True,
            headers={"user-agent": "nexmail-autoconfig"},
        )
    except httpx.HTTPError:
        return None
    if antwort.status_code != 200:
        return None
    return antwort.content


def autoconfig(adresse: str) -> Vorschlag | None:
    """Die drei Quellen der Reihe nach abfragen."""
    domaene = domaene_von(adresse)
    if not domaene or "." not in domaene:
        return None

    quellen = [
        f"https://autoconfig.{domaene}/mail/config-v1.1.xml?emailaddress={adresse}",
        f"https://{domaene}/.well-known/autoconfig/mail/config-v1.1.xml?emailaddress={adresse}",
        f"https://autoconfig.thunderbird.net/v1.1/{domaene}",
    ]

    for url in quellen:
        roh = _holen(url)
        if roh is None:
            continue
        vorschlag = _aus_xml(roh)
        if vorschlag is not None:
            # ⚠️ **Ohne den Abfrageteil.** Zwei der drei Adressen tragen die
            # Mailadresse als Parameter (``?emailaddress=…``), und das Protokoll
            # wird weitergereicht. Welche der drei Quellen geantwortet hat,
            # steht weiterhin da — mehr braucht die Fehlersuche nicht.
            logger.info(
                "Autoconfig found settings for %s at %s.", domaene, url.split("?")[0]
            )
            return vorschlag
    return None


# --- Die kleine Rueckfallebene ------------------------------------------- #

#: ⚠️ **Das ist die Rueckfallebene, nicht die Wahrheit.** Nur iCloud ist
#: belegt: Apples eigene Anleitung, support.apple.com/102525, nachgesehen am
#: 31.08.2026. Die uebrigen stehen aus dem Gedaechtnis und sind als solche
#: gekennzeichnet - sie werden nur benutzt, wenn Autoconfig nichts liefert,
#: und die Oberflaeche sagt dann, woher die Werte kommen.
TABELLE: dict[str, dict] = {
    "icloud.com": {
        "name": "iCloud",
        "auch": ["me.com", "mac.com"],
        # Die beiden Benutzerformen sind der Grund, warum dieser Eintrag
        # ueberhaupt noch dasteht.
        "imap": ("imap.mail.me.com", 993, "ssl", "nur_name"),
        "smtp": ("smtp.mail.me.com", 587, "starttls", "volle_adresse"),
        "app_passwort": "account.apple.com",
        "quelle": "support.apple.com/102525, nachgesehen 31.08.2026",
    },
    "gmail.com": {
        "name": "Gmail",
        "auch": ["googlemail.com"],
        "imap": ("imap.gmail.com", 993, "ssl", "volle_adresse"),
        "smtp": ("smtp.gmail.com", 587, "starttls", "volle_adresse"),
        "app_passwort": "myaccount.google.com",
        "quelle": "ungeprueft",
    },
    "gmx.de": {
        "name": "GMX",
        "auch": ["gmx.net", "gmx.at", "gmx.ch"],
        "imap": ("imap.gmx.net", 993, "ssl", "volle_adresse"),
        "smtp": ("mail.gmx.net", 587, "starttls", "volle_adresse"),
        "quelle": "ungeprueft",
    },
    "web.de": {
        "name": "WEB.DE",
        "auch": [],
        "imap": ("imap.web.de", 993, "ssl", "volle_adresse"),
        "smtp": ("smtp.web.de", 587, "starttls", "volle_adresse"),
        "quelle": "ungeprueft",
    },
    "mailbox.org": {
        "name": "mailbox.org",
        "auch": [],
        "imap": ("imap.mailbox.org", 993, "ssl", "volle_adresse"),
        "smtp": ("smtp.mailbox.org", 587, "starttls", "volle_adresse"),
        "quelle": "ungeprueft",
    },
}


def aus_tabelle(adresse: str) -> Vorschlag | None:
    domaene = domaene_von(adresse)
    for haupt, eintrag in TABELLE.items():
        if domaene == haupt or domaene in eintrag["auch"]:
            i = eintrag["imap"]
            s = eintrag["smtp"]
            return Vorschlag(
                imap=Serverdaten(i[0], i[1], i[2], i[3]),
                smtp=Serverdaten(s[0], s[1], s[2], s[3]),
                quelle=f"eingebaut ({eintrag['quelle']})",
                anbietername=eintrag["name"],
                app_passwort_noetig=bool(eintrag.get("app_passwort")),
                app_passwort_wo=eintrag.get("app_passwort", ""),
            )
    return None


def vorschlagen(adresse: str) -> Vorschlag | None:
    """Autoconfig zuerst, Tabelle danach. Nichts davon ist Pflicht."""
    gefunden = autoconfig(adresse)
    if gefunden is not None:
        # Die Tabelle weiss zusaetzlich, ob ein app-spezifisches Passwort
        # noetig ist - das steht in keinem Autoconfig-Dokument, kostet den
        # Betreiber aber sonst einen Abend.
        ergaenzung = aus_tabelle(adresse)
        if ergaenzung is not None and ergaenzung.app_passwort_noetig:
            gefunden.app_passwort_noetig = True
            gefunden.app_passwort_wo = ergaenzung.app_passwort_wo
            if not gefunden.anbietername:
                gefunden.anbietername = ergaenzung.anbietername
        return gefunden
    return aus_tabelle(adresse)
