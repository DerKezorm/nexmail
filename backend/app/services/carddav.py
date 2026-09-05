"""CardDAV — Adressbücher bei einem Anbieter.

⚠️ **Dieses Modul kopiert `caldav.py` NICHT, es benutzt es.** Beide sprechen
WebDAV; was dort teuer gelernt wurde, gilt hier wörtlich:

* `_BasicOderDigest` — All-Inkl bietet Basic gar nicht an
* `sitzung` — eine Verbindung je Abgleich statt einer je Aufruf
* `ortsschluessel` — Google meldet `…%40gmail.com` zurück, wo wir `…@…`
  geschrieben haben; wörtlich verglichen ist das ein fremder Eintrag **und**
  eine verschwundene eigene Zeile, und der Abgleich legt bei jeder Runde neu an
* der Doppelgriff nach `current-user-principal` **und** dem Home-Set in einer
  Anfrage — Google beantwortet die erste Frage gar nicht

Eine Kopie hätte bedeutet, dass die nächste Behebung an einer der beiden
Stellen vergessen wird. Der Preis sind ein paar Importe über den Unterstrich
hinweg; sie stehen hier mit Begründung.

⚠️ **Was CardDAV anders macht, ist wenig:** ein anderer Namensraum, ein
`addressbook-home-set` statt `calendar-home-set`, `address-data` statt
`calendar-data` — und die Nutzlast ist vCard statt iCalendar. vCard liest und
schreibt nexmail schon.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from ..meldung import Meldung
from .caldav import (  # noqa: PLC2701  (bewusst: eine Quelle statt zwei Kopien)
    DAV,
    CaldavFehler,
    Zugang,
    _anfragen,
    _anzeigename,
    _baum,
    _entschaerfen,
    _text,
    _verbindung,
    ortsschluessel,
    sitzung,
)

logger = logging.getLogger("nexmail.carddav")

#: Der CardDAV-Namensraum. Das ist praktisch der ganze Unterschied zu CalDAV.
CARD = "urn:ietf:params:xml:ns:carddav"

__all__ = ["CarddavFehler", "FernBuch", "FernKarte", "Zugang", "sitzung",
           "buecher_finden", "ctag_holen", "etags_holen", "inhalte_holen"]


class CarddavFehler(Meldung, RuntimeError):
    """Etwas, das dem Menschen davor gezeigt wird."""


@dataclass
class FernBuch:
    url: str
    name: str
    ctag: str = ""


@dataclass
class FernKarte:
    """Eine Karte beim Anbieter — Ort, ETag und (nach dem Abruf) ihr vCard."""

    url: str
    etag: str
    roh: str = ""


# --- Die Fragen ----------------------------------------------------------- #

#: ⚠️ **Beides auf einmal**, aus demselben Grund wie bei CalDAV: Google
#: beantwortet ``current-user-principal`` mit einem 404 im ``propstat`` und
#: liefert die Adresse direkt. Wer nacheinander fragt, endet dort in „kein
#: Adressbuch-Server", obwohl das Buch einen Schritt weiter liegt.
_PRINCIPAL = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f'<d:propfind xmlns:d="DAV:" xmlns:c="{CARD}"><d:prop>'
    "<d:current-user-principal/><c:addressbook-home-set/>"
    "</d:prop></d:propfind>"
)
_HOME = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f'<d:propfind xmlns:d="DAV:" xmlns:c="{CARD}">'
    "<d:prop><c:addressbook-home-set/></d:prop></d:propfind>"
)
_BUECHER = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f'<d:propfind xmlns:d="DAV:" xmlns:c="{CARD}" '
    'xmlns:cs="http://calendarserver.org/ns/">'
    "<d:prop><d:resourcetype/><d:displayname/><cs:getctag/></d:prop></d:propfind>"
)
_CTAG = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/">'
    "<d:prop><cs:getctag/></d:prop></d:propfind>"
)
_ETAGS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f'<c:addressbook-query xmlns:d="DAV:" xmlns:c="{CARD}">'
    "<d:prop><d:getetag/></d:prop></c:addressbook-query>"
)

CS = "http://calendarserver.org/ns/"


def _anfragen_karte(klient: httpx.Client, verb: str, url: str, **kw) -> httpx.Response:
    """``_anfragen`` aus dem Kalender, mit einer Übersetzung.

    ⚠️ Googles „API nicht eingeschaltet" nennt dort die CalDAV API. Hier heisst
    die eigene Schnittstelle CardDAV API, und wer die Meldung wörtlich nimmt,
    schaltet den falschen Schalter ein und sucht danach tagelang.
    """
    try:
        return _anfragen(klient, verb, url, **kw)
    except CaldavFehler as f:
        if str(f) == "caldav_google_api_aus":
            raise CarddavFehler("carddav_google_api_aus") from f
        raise


def _propfind(klient: httpx.Client, url: str, koerper: str, tiefe: str) -> ET.Element:
    antwort = _anfragen_karte(
        klient, "PROPFIND", url,
        content=koerper.encode("utf-8"),
        headers={"depth": tiefe, "content-type": 'application/xml; charset="utf-8"'},
    )
    if antwort.status_code not in (207, 200):
        logger.info("CardDAV PROPFIND %s answered %s.", url, antwort.status_code)
        raise CarddavFehler("carddav_kein_buchserver")
    return _baum(antwort)


def buecher_finden(zugang: Zugang, klient: httpx.Client | None = None) -> list[FernBuch]:
    """Von der eingetippten Adresse zu den Adressbüchern darunter.

    ⚠️ **Ein Zugang ist nicht EIN Buch, sondern mehrere.** Eine Apple-ID
    liefert „Alle Kontakte" und was der Mensch sonst angelegt hat. Sie blind zu
    übernehmen füllt die Spalte mit Zeug, das niemand sehen will — der Aufrufer
    wählt aus, genau wie beim Kalender.
    """
    with _verbindung(zugang, klient) as klient:
        wurzel = zugang.url.rstrip("/")
        principal = ""
        heim = ""
        # ⚠️ Manche Server antworten nur unter ``/.well-known/carddav``, andere
        # nur unter der Wurzel. Beides zu versuchen ist billiger als zu raten.
        for kandidat in (wurzel, urljoin(wurzel + "/", "/.well-known/carddav")):
            try:
                baum = _propfind(klient, kandidat, _PRINCIPAL, "0")
            except (CarddavFehler, CaldavFehler) as f:
                # ⚠️ **Nur „hier antwortet nichts" wird verschluckt.** Falsche
                # Zugangsdaten sind die häufigste echte Ursache; sie als „kein
                # Adressbuch-Server" zu melden schickt den Betreiber los, eine
                # Adresse zu suchen, die längst stimmt.
                if str(f) not in ("carddav_kein_buchserver", "caldav_kein_kalenderserver"):
                    raise
                continue
            direkt = _text(baum.find(f".//{{{CARD}}}addressbook-home-set/{{{DAV}}}href"))
            if direkt:
                heim = urljoin(kandidat, direkt)
                break
            principal = _text(baum.find(f".//{{{DAV}}}current-user-principal/{{{DAV}}}href"))
            if principal:
                principal = urljoin(kandidat, principal)
                break
        if not principal and not heim:
            raise CarddavFehler("carddav_kein_buchserver")

        if not heim:
            baum = _propfind(klient, principal, _HOME, "0")
            gefunden = _text(baum.find(f".//{{{CARD}}}addressbook-home-set/{{{DAV}}}href"))
            if not gefunden:
                raise CarddavFehler("carddav_kein_buchserver")
            heim = urljoin(principal, gefunden)

        baum = _propfind(klient, heim, _BUECHER, "1")
        raus: list[FernBuch] = []
        for antwort in baum.findall(f"{{{DAV}}}response"):
            href = _text(antwort.find(f"{{{DAV}}}href"))
            if not href:
                continue
            # ⚠️ **Nur was wirklich ein Adressbuch ist.** Unter demselben Heim
            # liegt die Sammlung selbst und bei manchen Anbietern weiteres —
            # als leere Bücher angezeigt wäre das eine Falschaussage.
            art = antwort.find(f".//{{{DAV}}}resourcetype")
            if art is None or art.find(f"{{{CARD}}}addressbook") is None:
                continue
            voll = urljoin(heim, href)
            raus.append(
                FernBuch(
                    url=voll,
                    # ⚠️ Doppelt entmaskiert — iCloud liefert ``&amp;amp;``.
                    # Nur der Anzeigename, nie die Karte selbst.
                    name=_anzeigename(antwort.find(f".//{{{DAV}}}displayname"))
                    or voll.rstrip("/").rsplit("/", 1)[-1],
                    ctag=_text(antwort.find(f".//{{{CS}}}getctag")),
                )
            )
        return raus


def ctag_holen(zugang: Zugang, klient: httpx.Client | None = None) -> str:
    """Das Sammel-ETag des Buches.

    ⚠️ **Ändert es sich nicht, hat sich nichts getan** — dann spart der
    Abgleich den ganzen Abruf. Ein Adressbuch mit tausend Karten wäre sonst bei
    jeder Runde ein Download von Megabyte.
    """
    with _verbindung(zugang, klient) as klient:
        baum = _propfind(klient, zugang.url, _CTAG, "0")
        return _text(baum.find(f".//{{{CS}}}getctag"))


def etags_holen(zugang: Zugang, klient: httpx.Client | None = None) -> list[FernKarte]:
    """Erst die Kennungen, dann die Inhalte.

    ⚠️ **Die Sammlung selbst kann in der Antwort stehen.** iCloud liefert sie
    beim Kalender als erste ``<response>`` — mit eigenem ETag, von einer Karte
    nicht zu unterscheiden. Wer sie mitnimmt, fragt beim nächsten Griff nach
    einer Sammlung als Karte, und iCloud antwortet darauf **gar nicht**: keine
    Absage, keine 404, Stille bis in die Zeitgrenze. Das hat am 03.09.2026
    einen halben Tag gekostet.

    Verglichen wird deshalb über ``ortsschluessel`` — den entschlüsselten Pfad
    ohne Host —, nicht wörtlich.
    """
    with _verbindung(zugang, klient) as klient:
        antwort = _anfragen_karte(
            klient, "REPORT", zugang.url,
            content=_ETAGS.encode("utf-8"),
            headers={"depth": "1", "content-type": 'application/xml; charset="utf-8"'},
        )
        if antwort.status_code not in (207, 200):
            logger.info("CardDAV REPORT %s answered %s.", zugang.url, antwort.status_code)
            raise CarddavFehler("carddav_nicht_lesbar")
        baum = _baum(antwort)

        eigener = ortsschluessel(zugang.url)
        raus: list[FernKarte] = []
        for zeile in baum.findall(f"{{{DAV}}}response"):
            href = _text(zeile.find(f"{{{DAV}}}href"))
            if not href:
                continue
            voll = urljoin(zugang.url, href)
            if ortsschluessel(voll) == eigener:
                continue  # die Sammlung selbst
            # ⚠️ Ohne die Anführungszeichen, wie ``FernTermin`` beim Kalender.
            # ``caldav.schreiben`` setzt sie für ``If-Match`` selbst wieder;
            # zwei Schreibweisen desselben ETags liefen in Lieferung 2 in
            # einen Konflikt, den es gar nicht gibt.
            etag = _text(zeile.find(f".//{{{DAV}}}getetag")).strip('"')
            raus.append(FernKarte(url=voll, etag=etag))
        return raus


#: Wie viele Karten je Griff geholt werden.
#: ⚠️ **Ein Deckel, kein Geschwindigkeitsregler.** Ein Adressbuch mit
#: Portraitfotos hat Karten von hunderten Kilobyte; fünfhundert auf einmal
#: wären ein Griff, den ein NAS nicht übersteht.
BLOCK = 50


def inhalte_holen(
    zugang: Zugang, adressen: list[str], klient: httpx.Client | None = None
) -> dict[str, FernKarte]:
    """Die vCards zu den genannten Adressen, blockweise.

    ⚠️ **Im Rumpf steht der PFAD, nicht die ganze Adresse.** RFC 6352 zeigt es
    so, und manche Server vergleichen wörtlich; mit ``https://…`` findet der
    Abruf dann nichts und meldet trotzdem Erfolg. Dieselbe Falle wie beim
    ``calendar-multiget``.

    ⚠️ **Der Schlüssel der Rückgabe ist der `ortsschluessel`**, nicht die
    Adresse, wie sie hineinging. Der Server darf sie anders kodiert
    zurückgeben — genau das tut Google.
    """
    raus: dict[str, FernKarte] = {}
    if not adressen:
        return raus

    with _verbindung(zugang, klient) as klient:
        for i in range(0, len(adressen), BLOCK):
            teil = adressen[i : i + BLOCK]
            # ⚠️ Der Pfad wandert in XML; ein ``&`` darin bricht den Rumpf.
            hrefs = "".join(f"<d:href>{_entschaerfen(_pfad(a))}</d:href>" for a in teil)
            koerper = (
                '<?xml version="1.0" encoding="utf-8"?>'
                f'<c:addressbook-multiget xmlns:d="DAV:" xmlns:c="{CARD}">'
                f"<d:prop><d:getetag/><c:address-data/></d:prop>{hrefs}"
                "</c:addressbook-multiget>"
            )
            antwort = _anfragen_karte(
                klient, "REPORT", zugang.url,
                content=koerper.encode("utf-8"),
                headers={"depth": "1", "content-type": 'application/xml; charset="utf-8"'},
            )
            if antwort.status_code not in (207, 200):
                logger.info(
                    "CardDAV multiget %s answered %s.", zugang.url, antwort.status_code
                )
                raise CarddavFehler("carddav_nicht_lesbar")
            for zeile in _baum(antwort).findall(f"{{{DAV}}}response"):
                href = _text(zeile.find(f"{{{DAV}}}href"))
                roh = _text(zeile.find(f".//{{{CARD}}}address-data"))
                if not href or not roh:
                    continue
                voll = urljoin(zugang.url, href)
                raus[ortsschluessel(voll)] = FernKarte(
                    url=voll,
                    etag=_text(zeile.find(f".//{{{DAV}}}getetag")).strip('"'),
                    roh=roh,
                )
    return raus


def _pfad(url: str) -> str:
    """Nur der Pfad, wie ihn der Server geschickt hat.

    ⚠️ **Nicht `ortsschluessel`.** Der entschlüsselt die Prozentkodierung, und
    genau die will der Server hier wörtlich zurück — er hat sie ja so geliefert.
    Der Schlüssel ist zum **Vergleichen** da, nicht zum Zurückschicken.
    """
    from urllib.parse import urlsplit

    teile = urlsplit(url)
    return teile.path + (f"?{teile.query}" if teile.query else "")
