"""CalDAV — Kalender bei iCloud, Nextcloud und anderen Servern.

CalDAV ist WebDAV mit Kalenderverstand: XML über HTTP, mit eigenen Verben
(``PROPFIND``, ``REPORT``) und ``.ics``-Dateien als Inhalt. Die vier Schritte,
die nexmail braucht:

1. **Finden** — von der eingetippten Adresse zum Kalender. Der Weg ist
   vorgeschrieben: ``/.well-known/caldav`` → ``current-user-principal`` →
   ``calendar-home-set`` → die Kalender darin.
2. **Holen** — welche Termine liegen dort, und haben sie sich geändert.
3. **Schreiben** — ``PUT`` einer ``.ics`` unter ihre Adresse.
4. **Löschen** — ``DELETE`` derselben Adresse.

⚠️ **Das ETag ist der ganze Konfliktschutz.** Beim Schreiben fährt es als
``If-Match`` mit. Antwortet der Server **412**, hat jemand denselben Termin
woanders geändert — dann wird gefragt, nicht überschrieben. Ohne ``If-Match``
verschwindet die Änderung vom Telefon spurlos, und niemand erfährt davon.

⚠️ **``xml.etree`` genügt, ``defusedxml`` ist nicht nötig.** Am 02.09.2026
gegen Python 3.14 und 3.13 im Container gemessen: Billion Laughs, XXE auf eine
Datei und XXE auf eine Adresse werden alle drei abgewiesen. Der Wächter dazu
steht in ``tests/test_umgebung.py``, weil die Bremse an der Patch-Fassung
hängt.

⚠️ **Nur https, und keine Adressen im eigenen Netz.** Ein Kalender-Server ist
etwas, das der Betreiber einträgt — aber ein Tippfehler oder eine übernommene
Konfiguration machten nexmail sonst zur Fernbedienung fürs Heimnetz. Dieselbe
Prüfung wie beim Bildvermittler, und aus demselben Grund.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlparse

import html
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from .bildvermittler import Abgelehnt, adresse_pruefen
from ..meldung import Meldung

logger = logging.getLogger("nexmail.caldav")

DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"
APPLE = "http://apple.com/ns/ical/"
CS = "http://calendarserver.org/ns/"

#: Wie lange auf den Server gewartet wird. iCloud antwortet meist in
#: Millisekunden; ein Server, der eine halbe Minute braucht, ist kaputt.
ZEITGRENZE = 30.0

#: Wie viele Termine ein Abruf höchstens holt. ⚠️ Ohne Deckel zieht ein
#: Kalender mit zwanzig Jahren Bestand den Container leer.
MAX_TERMINE = 5_000

#: Wie viele Adressen ein ``calendar-multiget`` auf einmal erfragt. Eine
#: Speichergrenze, kein Geschwindigkeitsregler.
BLOCK = 50

#: Kalender, die keine Termine führen (Aufgaben, Kontakte), fallen weg.
GEWOLLT = "VEVENT"


class CaldavFehler(Meldung, RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class FernKalender:
    """Ein Kalender, wie der Server ihn beschreibt."""

    url: str
    name: str
    ctag: str = ""
    #: Die Farbe, die der Server nennt (``#RRGGBB``). nexmail teilt seine
    #: eigene zu — die sechs geprueften Toene —, aber die Reihenfolge folgt
    #: dem Server, damit „Arbeit" nicht ploetzlich rosa ist.
    farbe: str = ""


@dataclass
class FernTermin:
    """Eine ``.ics`` auf dem Server."""

    href: str
    etag: str
    roh: str = ""


@dataclass
class Zugang:
    url: str
    benutzer: str
    passwort: str
    #: Gesetzt heisst: angemeldet wird mit ``Authorization: Bearer``, nicht mit
    #: Benutzer und Passwort. ⚠️ **Google laesst nur das zu** — Basic Auth an
    #: ``apidata.googleusercontent.com`` wird abgewiesen.
    token: str = ""
    #: Nur fuer Tests: ein eigener Transport statt eines echten Netzes.
    transport: object | None = field(default=None, repr=False)


# --- HTTP ----------------------------------------------------------------- #


#: Was der Bildvermittler meldet, und was daraus hier wird.
#: ⚠️ **Nicht alles auf „im eigenen Netz" abbilden.** Ein Name, den es nicht
#: gibt, ist ein Tippfehler in der Adresse — wer dem Betreiber dafuer „dein
#: Heimnetz ist gesperrt" sagt, schickt ihn in die falsche Richtung.
_GRUENDE = {
    "bild_adresse_unerlaubt": "caldav_adresse_ungueltig",
    "bild_adresse_im_eigenen_netz": "caldav_adresse_im_eigenen_netz",
    "bild_nicht_erreichbar": "caldav_nicht_erreichbar",
}


def _pruefen(url: str) -> None:
    """⚠️ Nur ``http(s)``, und nichts im eigenen Netz."""
    teile = urlparse(url)
    if teile.scheme not in ("https", "http") or not teile.hostname:
        raise CaldavFehler("caldav_adresse_ungueltig")
    try:
        # ⚠️ Dieselbe Pruefung wie beim Bildvermittler — sie nimmt die ganze
        # Adresse und sieht jede Antwort des Namensdienstes an, nicht die erste.
        adresse_pruefen(url)
    except Abgelehnt as f:
        raise CaldavFehler(_GRUENDE.get(str(f), "caldav_nicht_erreichbar")) from f


class _BasicOderDigest(httpx.Auth):
    """Erst Basic, bei Bedarf Digest.

    ⚠️ **Nicht jeder CalDAV-Server nimmt Basic.** All-Inkl antwortet auf seinem
    Kalender-Endpunkt mit ``WWW-Authenticate: Digest realm="NMMDav"`` und
    **bietet Basic gar nicht an** — am 03.09.2026 gemessen. Ein Client, der nur
    Basic kann, bekommt dort ein 401 und meldet „abgewiesen": dieselbe Meldung
    wie bei einem falschen Passwort, und der Betreiber tippt es zehnmal neu.

    Der Ablauf kostet im Digest-Fall **eine** zusaetzliche Runde, und nur beim
    ersten Mal: ``httpx.DigestAuth`` merkt sich die Aufforderung und haengt sie
    danach gleich an. Wer Basic annimmt, merkt von alldem nichts.
    """

    def __init__(self, benutzer: str, passwort: str) -> None:
        self._basic = httpx.BasicAuth(benutzer, passwort)
        self._digest = httpx.DigestAuth(benutzer, passwort)
        self._digest_gilt = False

    def auth_flow(self, request):  # type: ignore[override]
        if self._digest_gilt:
            yield from self._digest.auth_flow(request)
            return

        fluss = self._basic.auth_flow(request)
        antwort = yield next(fluss)
        if antwort.status_code != 401:
            return

        # Vielleicht will der Server Digest. ``DigestAuth`` baut den Kopf aus
        # genau dieser Aufforderung — dafuer muss ihm der erste Versuch samt
        # Antwort untergeschoben werden.
        #
        # ⚠️ **Hier steht bewusst keine eigene Pruefung auf „Digest".**
        # ``DigestAuth.auth_flow`` steigt selbst aus, wenn die Antwort keine
        # Digest-Aufforderung traegt — ein zweiter Waechter daneben liesse sich
        # nicht gegen eine Mutation pruefen und rostete vor sich hin.
        digest_fluss = self._digest.auth_flow(request)
        next(digest_fluss)
        try:
            zweiter = digest_fluss.send(antwort)
        except StopIteration:
            return
        self._digest_gilt = True
        yield zweiter


def _klient(zugang: Zugang) -> httpx.Client:
    # ⚠️ **Die Naht fuer Tests, und nur fuer sie.** Ein eigener Transport kommt
    # ausschliesslich aus dem Code; ueber die Adressen laesst er sich nicht
    # setzen. Mit ihm gibt es kein Netz, also auch nichts aufzuloesen — die
    # Pruefung liefe sonst gegen einen Namen, den es absichtlich nicht gibt,
    # und jeder Test meldete „nicht erreichbar" statt dessen, was er prueft.
    if zugang.transport is None:
        _pruefen(zugang.url)
    kopf = {"user-agent": "nexmail"}
    if zugang.token:
        kopf["authorization"] = f"Bearer {zugang.token}"
    return httpx.Client(
        auth=None if zugang.token else _BasicOderDigest(zugang.benutzer, zugang.passwort),
        timeout=ZEITGRENZE,
        follow_redirects=True,
        transport=zugang.transport,  # type: ignore[arg-type]
        headers=kopf,
    )


@contextmanager
def sitzung(zugang: Zugang) -> Iterator[httpx.Client]:
    """Eine Verbindung fuer einen ganzen Abgleich statt einer je Aufruf.

    ⚠️ **iCloud laesst je Konto nur eine Verbindung zu.** Fuer IMAP steht
    das seit jeher in CLAUDE.md; bei CalDAV verhaelt es sich genauso. Bis zum
    03.09.2026 baute jede einzelne Funktion hier ihren eigenen Klienten auf:
    Der Erstabgleich von sechs iCloud-Kalendern mit zusammen 429 Terminen kam
    so auf **25 TLS-Handschlaege in einem Schwung**. Apple beantwortet die
    ueberzaehligen nicht mit einer Absage, sondern **gar nicht** — und das
    sieht aus wie ein Lesetimeout nach 30 Sekunden.

    Gemeldet wurde es als „er hat sie zwar gefunden, aber beim Verbinden kam
    das": Alle sechs iCloud-Kalender scheiterten reihum, exakt 31 Sekunden
    auseinander, waehrend der einzelne Google-Kalender durchlief.

    ⚠️ **Wer eine Sitzung uebergibt, haelt sie auch offen.** Die Funktionen
    hier schliessen einen uebergebenen Klienten nicht — sonst waere die zweite
    Anfrage im selben Abgleich wieder eine neue Verbindung.
    """
    with _klient(zugang) as klient:
        yield klient


@contextmanager
def _verbindung(zugang: Zugang, klient: httpx.Client | None) -> Iterator[httpx.Client]:
    """Die uebergebene Sitzung, oder eine eigene fuer diesen einen Aufruf."""
    if klient is not None:
        yield klient
        return
    with _klient(zugang) as eigener:
        yield eigener


def _anfragen(klient: httpx.Client, verb: str, url: str, **kw) -> httpx.Response:
    try:
        antwort = klient.request(verb, url, **kw)
    except httpx.HTTPError as f:
        logger.info("CalDAV request to %s failed: %s", url, f)
        raise CaldavFehler("caldav_nicht_erreichbar") from f
    if antwort.status_code in (401, 403):
        # ⚠️ **Der Grund gehoert ins Protokoll.** „Abgewiesen" sieht bei
        # jedem Anbieter gleich aus; ob ein Bereich fehlt oder die Adresse
        # falsch steht, sagt nur die Antwort selbst.
        logger.info(
            "CalDAV %s %s was refused (%d): %s",
            verb, url, antwort.status_code, antwort.text[:300],
        )
        # ⚠️ **Googles haeufigster Grund ist kein Zugangsproblem.** Die
        # „CalDAV API" ist im Cloud-Projekt eine EIGENE Schnittstelle; wer nur
        # „Google Calendar API" eingeschaltet hat, bekommt hier ein 403, das
        # aussieht wie eine fehlende Zustimmung — und sucht dann tagelang an
        # der falschen Stelle. Am 03.09.2026 an einem echten Konto gemessen.
        if "accessNotConfigured" in antwort.text:
            raise CaldavFehler("caldav_google_api_aus")
        raise CaldavFehler("caldav_abgewiesen")
    return antwort


def _baum(antwort: httpx.Response) -> ET.Element:
    try:
        return ET.fromstring(antwort.content)
    except ET.ParseError as f:
        logger.info("CalDAV server answered with unreadable XML: %s", f)
        raise CaldavFehler("caldav_antwort_unlesbar") from f


def _text(knoten: ET.Element | None) -> str:
    return (knoten.text or "").strip() if knoten is not None else ""


def _anzeigename(knoten: ET.Element | None) -> str:
    """Der Anzeigename einer Sammlung — einmal mehr entmaskiert als üblich.

    ⚠️ **iCloud maskiert den Namen doppelt.** Ein Kalender, der „D&M"
    heißt, steht im XML als ``D&amp;amp;M``; der XML-Leser löst die äußere
    Maskierung auf, und übrig bleibt ``D&amp;M``. Genau so stand er am
    03.09.2026 in der Oberfläche — gemessen mit nexmails Code **und** mit
    httpx pur, es liegt also nicht an uns.

    ⚠️ **Nur auf den Anzeigenamen, nie auf ``calendar-data``.** Das ICS ist
    kein HTML; ein ``&`` in einer Beschreibung ist dort ein ``&``, und wer es
    hier durchschickte, veränderte fremde Termininhalte.

    ⚠️ **Der Preis ist benannt:** Ein Kalender, der wörtlich ``R&amp;D``
    heißen soll, erscheint als ``R&D``. Das ist der seltenere Fall von beiden,
    und der harmlosere.
    """
    return html.unescape(_text(knoten))


# --- Finden --------------------------------------------------------------- #

#: ⚠️ **Beides auf einmal, nicht nacheinander.** Der Weg laut RFC 6764 ist
#: „wer bin ich" und dann „wo liegen meine Kalender". Google beantwortet die
#: erste Frage **gar nicht** — es meldet ``current-user-principal`` mit
#: ``404 Not Found`` im ``propstat`` und liefert die Kalenderadresse direkt.
#: Am 03.09.2026 an einem echten Konto gemessen; vorher endete die Suche dort
#: in „kein Kalender-Server", obwohl der Kalender einen Schritt weiter lag.
#: Wer beides zugleich erfragt, kommt bei beiden Sorten Server an — und spart
#: bei Google eine Runde ueber das Netz.
_PRINCIPAL = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
    "<d:current-user-principal/><c:calendar-home-set/>"
    "</d:prop></d:propfind>"
)
_HOME = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
)
_KALENDER = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
    'xmlns:cs="http://calendarserver.org/ns/" xmlns:a="http://apple.com/ns/ical/">'
    "<d:prop><d:resourcetype/><d:displayname/><cs:getctag/>"
    "<c:supported-calendar-component-set/><a:calendar-color/></d:prop></d:propfind>"
)


def _propfind(klient: httpx.Client, url: str, koerper: str, tiefe: str) -> ET.Element:
    antwort = _anfragen(
        klient, "PROPFIND", url,
        content=koerper.encode("utf-8"),
        headers={"depth": tiefe, "content-type": 'application/xml; charset="utf-8"'},
    )
    if antwort.status_code not in (207, 200):
        logger.info("CalDAV PROPFIND %s answered %s.", url, antwort.status_code)
        raise CaldavFehler("caldav_kein_kalenderserver")
    return _baum(antwort)


def kalender_finden(zugang: Zugang, klient: httpx.Client | None = None) -> list[FernKalender]:
    """Von der eingetippten Adresse zu den Kalendern darunter.

    ⚠️ **Ein Zugang ist nicht EIN Kalender, sondern mehrere.** Eine Apple-ID
    liefert „Privat", „Arbeit", „Geburtstage" — sie alle blind zu uebernehmen
    fuellt die Spalte mit Zeug, das niemand sehen will. Der Aufrufer waehlt aus.

    ⚠️ **Was keine Termine fuehrt, faellt weg.** Unter demselben Zugang liegen
    auch Aufgabenlisten (``VTODO``); sie als leere Kalender anzuzeigen waere
    eine Falschaussage.
    """
    with _verbindung(zugang, klient) as klient:
        wurzel = zugang.url.rstrip("/")
        # Schritt 1: Wer bin ich — und wo liegen meine Kalender? ⚠️ Manche
        # Server antworten darauf nur unter ``/.well-known/caldav``, andere nur
        # unter der Wurzel; beides zu versuchen ist billiger als zu raten.
        principal = ""
        heim = ""
        for kandidat in (wurzel, urljoin(wurzel + "/", "/.well-known/caldav")):
            try:
                baum = _propfind(klient, kandidat, _PRINCIPAL, "0")
            except CaldavFehler as f:
                # ⚠️ **Nur „hier antwortet nichts" wird verschluckt.** Falsche
                # Zugangsdaten sind die haeufigste echte Ursache; sie als „kein
                # Kalenderserver" zu melden schickt den Betreiber los, die
                # Adresse zu suchen, die stimmt.
                if str(f) != "caldav_kein_kalenderserver":
                    raise
                continue
            # ⚠️ **Die Kalenderadresse zuerst.** Steht sie schon hier, ist die
            # Frage nach dem Principal beantwortet, bevor sie gestellt wurde —
            # so macht es Google, und ein zweiter Anlauf ginge dort ins Leere.
            direkt = _text(baum.find(f".//{{{CAL}}}calendar-home-set/{{{DAV}}}href"))
            if direkt:
                heim = urljoin(kandidat, direkt)
                break
            principal = _text(baum.find(f".//{{{DAV}}}current-user-principal/{{{DAV}}}href"))
            if principal:
                principal = urljoin(kandidat, principal)
                break
        if not principal and not heim:
            raise CaldavFehler("caldav_kein_kalenderserver")

        # Schritt 2: Wo liegen meine Kalender? — sofern es noch offen ist.
        if not heim:
            baum = _propfind(klient, principal, _HOME, "0")
            gefunden = _text(baum.find(f".//{{{CAL}}}calendar-home-set/{{{DAV}}}href"))
            if not gefunden:
                raise CaldavFehler("caldav_kein_kalenderserver")
            heim = urljoin(principal, gefunden)

        # Schritt 3: Welche sind es?
        baum = _propfind(klient, heim, _KALENDER, "1")
        raus: list[FernKalender] = []
        for antwort in baum.findall(f"{{{DAV}}}response"):
            href = _text(antwort.find(f"{{{DAV}}}href"))
            if not href:
                continue
            art = antwort.find(f".//{{{DAV}}}resourcetype")
            if art is None or art.find(f"{{{CAL}}}calendar") is None:
                continue
            teile = antwort.find(f".//{{{CAL}}}supported-calendar-component-set")
            if teile is not None:
                namen = {k.get("name", "").upper() for k in teile}
                if namen and GEWOLLT not in namen:
                    continue
            voll = urljoin(heim, href)
            raus.append(
                FernKalender(
                    url=voll,
                    name=_anzeigename(antwort.find(f".//{{{DAV}}}displayname")) or voll.rstrip("/").rsplit("/", 1)[-1],
                    ctag=_text(antwort.find(f".//{{{CS}}}getctag")),
                    farbe=_text(antwort.find(f".//{{{APPLE}}}calendar-color")),
                )
            )
        return raus


def ctag_holen(zugang: Zugang, klient: httpx.Client | None = None) -> str:
    """Das Sammel-ETag der Sammlung.

    ⚠️ **Aendert es sich nicht, hat sich nichts getan** — dann spart der
    Abgleich den ganzen Abruf. Bei einem Postfach macht das die ``UIDNEXT``.
    """
    with _verbindung(zugang, klient) as klient:
        baum = _propfind(klient, zugang.url, _KALENDER, "0")
        return _text(baum.find(f".//{{{CS}}}getctag"))


# --- Holen ---------------------------------------------------------------- #

_ETAGS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><d:getetag/></d:prop>"
    '<c:filter><c:comp-filter name="VCALENDAR">'
    '<c:comp-filter name="VEVENT"/></c:comp-filter></c:filter></c:calendar-query>'
)


def ortsschluessel(href: str) -> str:
    """Zwei Adressen, die denselben Termin meinen, auf einen Wert bringen.

    ⚠️ **Wörtlich vergleichen geht schief.** Google nimmt ein ``PUT`` auf
    ``…/events/<uid>@nexmail.ics`` an und meldet denselben Termin danach als
    ``…/events/<uid>%40nexmail.ics``. Als Zeichenketten sind das zwei Adressen:
    Der Abgleich hielt den Server-Eintrag für neu und die eigene Zeile für
    gelöscht — **bei jeder Runde**. Der gerade angelegte Termin verschwand
    also, und an seiner Stelle stand eine neue Zeile mit neuer Kennung.
    Am 03.09.2026 an einem echten Google-Kalender gemessen.

    Verglichen wird deshalb der **entschlüsselte Pfad**: ohne Host (manche
    Server antworten mit absoluter Adresse, andere mit dem Pfad) und ohne
    Prozentkodierung.
    """
    return unquote(urlparse(href).path).rstrip("/")


def etags_holen(zugang: Zugang, klient: httpx.Client | None = None) -> list[FernTermin]:
    """Welche Termine liegen dort, und in welcher Fassung.

    ⚠️ **Erst die Kennungen, dann die Inhalte.** Ein Kalender mit
    fuenftausend Terminen waere sonst bei jedem Abgleich ein Download von
    Megabyte — geholt wird nur, was sich wirklich geaendert hat.
    """
    with _verbindung(zugang, klient) as klient:
        antwort = _anfragen(
            klient, "REPORT", zugang.url,
            content=_ETAGS.encode("utf-8"),
            headers={"depth": "1", "content-type": 'application/xml; charset="utf-8"'},
        )
        if antwort.status_code not in (207, 200):
            raise CaldavFehler("caldav_abfrage_gescheitert")
        baum = _baum(antwort)
        # ⚠️ **Die Sammlung selbst steht mit in der Antwort.** iCloud liefert
        # bei ``Depth: 1`` als erste ``<response>`` den Kalender — samt eigenem
        # ETag, sie sieht also aus wie ein Termin. Wer sie mitnimmt, fragt beim
        # naechsten Schritt per ``calendar-multiget`` nach einem Kalender, als
        # waere er ein Termin, und **iCloud antwortet darauf gar nicht**: kein
        # 404, keine Absage, einfach Stille bis in die Zeitgrenze.
        #
        # Am 03.09.2026 aus dem Betrieb gemeldet und Schritt fuer Schritt
        # eingekreist. Es traf **jede** Runde, deshalb heilte es nie von selbst.
        # Google faellt nicht auf, weil es die Sammlung nicht mitschickt.
        eigen = ortsschluessel(zugang.url)
        raus: list[FernTermin] = []
        for eintrag in baum.findall(f"{{{DAV}}}response"):
            href = _text(eintrag.find(f"{{{DAV}}}href"))
            etag = _text(eintrag.find(f".//{{{DAV}}}getetag"))
            if href and ortsschluessel(href) != eigen:
                raus.append(FernTermin(href=urljoin(zugang.url, href), etag=etag.strip('"')))
            if len(raus) >= MAX_TERMINE:
                logger.warning("Calendar has more than %s events; cut off.", MAX_TERMINE)
                break
        return raus


def inhalte_holen(
    zugang: Zugang, hrefs: list[str], klient: httpx.Client | None = None
) -> list[FernTermin]:
    """Die ``.ics`` zu bestimmten Adressen — blockweise."""
    raus: list[FernTermin] = []
    if not hrefs:
        return raus
    with _verbindung(zugang, klient) as klient:
        for i in range(0, len(hrefs), BLOCK):
            teil = hrefs[i : i + BLOCK]
            koerper = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
                # ⚠️ **Der Pfad, nicht die ganze Adresse.** RFC 4791 zeigt es
                # so, und manche Server vergleichen woertlich — mit „https://…"
                # findet der Abruf dann nichts und meldet trotzdem Erfolg.
                + "".join(f"<d:href>{_entschaerfen(urlparse(h).path or h)}</d:href>" for h in teil)
                + "</c:calendar-multiget>"
            )
            antwort = _anfragen(
                klient, "REPORT", zugang.url,
                content=koerper.encode("utf-8"),
                headers={"depth": "1", "content-type": 'application/xml; charset="utf-8"'},
            )
            if antwort.status_code not in (207, 200):
                raise CaldavFehler("caldav_abfrage_gescheitert")
            for eintrag in _baum(antwort).findall(f"{{{DAV}}}response"):
                href = _text(eintrag.find(f"{{{DAV}}}href"))
                daten = _text(eintrag.find(f".//{{{CAL}}}calendar-data"))
                if href and daten:
                    raus.append(
                        FernTermin(
                            href=urljoin(zugang.url, href),
                            etag=_text(eintrag.find(f".//{{{DAV}}}getetag")).strip('"'),
                            roh=daten,
                        )
                    )
    return raus


def _entschaerfen(wert: str) -> str:
    """⚠️ Eine Adresse wandert in XML — ein ``&`` darin bricht den Rumpf."""
    return (
        wert.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


# --- Schreiben ------------------------------------------------------------ #


class Konflikt(CaldavFehler):
    """Der Server hat eine neuere Fassung. ⚠️ **Nicht überschreiben.**"""


def schreiben(
    zugang: Zugang, href: str, ics: str, etag: str = "",
    klient: httpx.Client | None = None,
) -> str:
    """Eine ``.ics`` ablegen. Gibt das neue ETag zurück.

    ⚠️ **``If-Match`` bei einem vorhandenen Termin, ``If-None-Match: *`` bei
    einem neuen.** Ohne das Erste überschreibt nexmail stillschweigend die
    Änderung vom Telefon; ohne das Zweite überschreibt ein zweiter Anlauf
    einen Termin, den ein anderer gerade unter derselben Adresse angelegt hat.
    """
    kopf = {"content-type": "text/calendar; charset=utf-8"}
    kopf["if-match"] = f'"{etag}"' if etag else "*"
    if not etag:
        kopf.pop("if-match")
        kopf["if-none-match"] = "*"

    with _verbindung(zugang, klient) as klient:
        antwort = _anfragen(klient, "PUT", href, content=ics.encode("utf-8"), headers=kopf)
        if antwort.status_code == 412:
            raise Konflikt("caldav_konflikt")
        if antwort.status_code not in (200, 201, 204):
            logger.info("CalDAV PUT %s answered %s.", href, antwort.status_code)
            raise CaldavFehler("caldav_schreiben_gescheitert")
        neu = antwort.headers.get("etag", "").strip('"')
        if neu:
            return neu

    # ⚠️ **Nicht jeder Server schickt ein ETag zurueck.** Nextcloud nicht
    # immer — und **Google nie**, gemessen am 03.09.2026: 201 ohne ``ETag``.
    # Dann muss es nachgeschlagen werden, sonst faehrt der naechste
    # Schreibvorgang mit einem veralteten ``If-Match`` und scheitert an einem
    # Konflikt, den es gar nicht gibt.
    gesucht = ortsschluessel(href)
    for termin in etags_holen(zugang):
        if ortsschluessel(termin.href) == gesucht:
            return termin.etag
    return ""


def loeschen(
    zugang: Zugang, href: str, etag: str = "", klient: httpx.Client | None = None
) -> None:
    with _verbindung(zugang, klient) as klient:
        kopf = {"if-match": f'"{etag}"'} if etag else {}
        antwort = _anfragen(klient, "DELETE", href, headers=kopf)
        if antwort.status_code == 412:
            raise Konflikt("caldav_konflikt")
        # ⚠️ 404 ist kein Fehler: Der Termin sollte weg sein, und er ist es.
        if antwort.status_code not in (200, 204, 404):
            raise CaldavFehler("caldav_loeschen_gescheitert")


# --- ICS-Abo -------------------------------------------------------------- #


@dataclass
class Abo:
    """Was ein Abruf ergab. ``roh`` leer heisst: unveraendert (HTTP 304)."""

    roh: str
    marke: str = ""
    unveraendert: bool = False


def abo_holen(url: str, transport: object | None = None, marke: str = "") -> Abo:
    """Eine veröffentlichte ``.ics`` herunterladen.

    ⚠️ **Ohne Zugangsdaten, und deshalb mit denselben Vorsichten wie beim
    Bildvermittler**: nur eine erreichbare öffentliche Adresse, und eine
    Grenze für die Größe. Ein Feiertagskalender hat Kilobyte; wer eine
    Gigabyte-Datei verlinkt, soll den Container nicht umbringen.

    ⚠️ **Mit ``marke`` wird nur gefragt, nicht geholt.** Ein Abo hat kein
    ``ctag``; ohne diese Frage lädt nexmail bei **jedem** Takt die ganze Datei
    neu — und schrieb bis zum 03.09.2026 jeden Termin darin neu, obwohl sich
    nichts getan hatte. Was der Server als ``ETag`` oder ``Last-Modified``
    mitgibt, faehrt beim naechsten Mal als Bedingung zurueck; antwortet er
    **304**, ist die Runde vorbei, bevor sie angefangen hat.
    """
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    # Siehe ``_klient``: ein eigener Transport kommt nur aus dem Code.
    if transport is None:
        _pruefen(url)
    kopf = {"user-agent": "nexmail"}
    if marke:
        # ⚠️ Beide Formen: Manche Server fuehren ein ETag, andere nur ein
        # Datum. Woran man es erkennt, steht in der Marke selbst.
        if marke.startswith("dat:"):
            kopf["if-modified-since"] = marke[4:]
        else:
            kopf["if-none-match"] = marke
    try:
        with httpx.Client(
            timeout=ZEITGRENZE, follow_redirects=True, transport=transport  # type: ignore[arg-type]
        ) as klient:
            with klient.stream("GET", url, headers=kopf) as antwort:
                if antwort.status_code == 304:
                    return Abo(roh="", marke=marke, unveraendert=True)
                if antwort.status_code != 200:
                    raise CaldavFehler("abo_nicht_erreichbar")
                neue_marke = antwort.headers.get("etag", "").strip()
                if not neue_marke and antwort.headers.get("last-modified"):
                    neue_marke = f"dat:{antwort.headers['last-modified']}"
                stuecke: list[bytes] = []
                gesamt = 0
                for block in antwort.iter_bytes(1 << 16):
                    gesamt += len(block)
                    if gesamt > MAX_ABO_BYTES:
                        raise CaldavFehler("abo_zu_gross")
                    stuecke.append(block)
    except httpx.HTTPError as f:
        raise CaldavFehler("abo_nicht_erreichbar") from f
    return Abo(roh=b"".join(stuecke).decode("utf-8", errors="replace"), marke=neue_marke)


#: Wie groß eine abonnierte ``.ics`` höchstens sein darf.
MAX_ABO_BYTES = 25 * 1024 * 1024
