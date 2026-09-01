"""Die Verbindung zum Postfach — und vor allem: was schiefgehen kann.

⚠️ **Der Verbindungstest ist die wichtigste Funktion in dieser Datei**, und
zwar nicht wegen des Erfolgsfalls. Ein Postfach, das nicht geht, kann aus fünf
Gründen nicht gehen, und die Antwort „Fehler" hilft bei keinem davon:

| Was ist los | Was der Betreiber tun muss |
|---|---|
| Server nicht erreichbar | Adresse prüfen, Netz prüfen |
| Keine Antwort auf dem Port | anderen Port oder andere Verschlüsselung |
| Verschlüsselung passt nicht | SSL statt STARTTLS oder umgekehrt |
| Anmeldung abgewiesen | Benutzername, Passwort — **oder ein app-spezifisches Passwort** |
| Server antwortet fremd | Ist das überhaupt ein IMAP-Server |

Der vierte Fall ist der teuerste: iCloud und Gmail weisen ein normales
Kontopasswort mit **derselben** Meldung ab wie einen Tippfehler. Wer das nicht
sagt, lässt den Betreiber zehn Minuten sein Passwort anzweifeln.
"""

from __future__ import annotations

import imaplib
import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass, field

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError, LoginError

logger = logging.getLogger("nexmail.imap")

#: Kurz genug, dass niemand vor einem hängenden Formular sitzt.
ZEITGRENZE = 15

#: ⚠️ **Eine Verbindung je Postfach.** Apple begrenzt die Zahl gleichzeitiger
#: IMAP-Verbindungen und wirft darüber hinaus einfach heraus. Der Wert steht
#: hier, damit später niemand „nur mal kurz" eine zweite aufmacht.
VERBINDUNGEN_JE_KONTO = 1


class Fehlerart:
    NICHT_ERREICHBAR = "nicht_erreichbar"
    KEINE_ANTWORT = "keine_antwort"
    VERSCHLUESSELUNG = "verschluesselung"
    ANMELDUNG = "anmeldung"
    UNERWARTET = "unerwartet"
    #: Kein Serverproblem - ein Fehler in nexmail oder seinen Abhaengigkeiten.
    INTERN = "intern"


@dataclass
class Verbindungsfehler(Exception):
    art: str
    #: Ein Satz, der sagt, was zu tun ist - nicht, was schiefging.
    text: str
    #: Die Meldung des Servers, falls es eine gab. Fuer das Protokoll.
    roh: str = ""

    def __str__(self) -> str:
        return self.text


def _deuten(fehler: Exception, server: str, port: int) -> Verbindungsfehler:
    """Aus einer technischen Ausnahme eine brauchbare Auskunft machen."""
    roh = f"{type(fehler).__name__}: {fehler}"

    if isinstance(fehler, socket.gaierror):
        return Verbindungsfehler(
            Fehlerart.NICHT_ERREICHBAR,
            f"Der Server „{server}“ wurde nicht gefunden. Stimmt die Adresse?",
            roh,
        )
    if isinstance(fehler, ssl.SSLError):
        return Verbindungsfehler(
            Fehlerart.VERSCHLUESSELUNG,
            f"Auf Port {port} antwortet etwas, aber nicht in der erwarteten "
            "Verschlüsselung. Meist ist SSL/TLS und STARTTLS vertauscht.",
            roh,
        )
    if isinstance(fehler, (socket.timeout, TimeoutError)):
        return Verbindungsfehler(
            Fehlerart.KEINE_ANTWORT,
            f"„{server}“ antwortet auf Port {port} nicht. Blockiert eine "
            "Firewall, oder ist der Port ein anderer?",
            roh,
        )
    if isinstance(fehler, (ConnectionRefusedError, OSError)):
        return Verbindungsfehler(
            Fehlerart.KEINE_ANTWORT,
            f"„{server}“ nimmt auf Port {port} keine Verbindung an.",
            roh,
        )
    # ⚠️ **Hier landet auch, was gar nichts mit dem Server zu tun hat** - etwa
    # eine Bibliothek, die zur laufenden Python-Fassung nicht passt. Genau das
    # ist passiert: IMAPClient 3.0.1 warf unter Python 3.14 einen
    # AttributeError, und nexmail meldete "Unerwartete Antwort des Servers".
    # Der Betreiber sucht dann beim Anbieter, waehrend der Fehler im eigenen
    # Haus liegt. Deshalb wird hier unterschieden.
    if not isinstance(fehler, (OSError, IMAPClientError, imaplib.IMAP4.error, smtplib.SMTPException)):
        logger.error("Internal error while connecting to %s:%s - %s", server, port, roh)
        return Verbindungsfehler(
            Fehlerart.INTERN,
            "Fehler in nexmail selbst, nicht beim Server. Die Einzelheiten "
            "stehen im Protokoll des Containers.",
            roh,
        )
    return Verbindungsfehler(Fehlerart.UNERWARTET, "Unerwartete Antwort des Servers.", roh)


def _anmeldefehler(app_passwort_wo: str) -> Verbindungsfehler:
    """⚠️ Der teuerste Fall, deshalb mit Wegbeschreibung."""
    text = "Benutzername oder Passwort wurde abgewiesen."
    if app_passwort_wo:
        text += (
            f" Dieser Anbieter lässt fremde Programme **nur mit einem "
            f"app-spezifischen Passwort** herein — ein normales Kontopasswort "
            f"weist er mit genau dieser Meldung ab. Erzeuge eines auf "
            f"{app_passwort_wo} und trage es hier ein."
        )
    return Verbindungsfehler(Fehlerart.ANMELDUNG, text)


def verbinden(
    server: str, port: int, sicherheit: str, benutzer: str, passwort: str, app_passwort_wo: str = ""
) -> IMAPClient:
    """Anmelden und die offene Verbindung zurueckgeben. Der Aufrufer schliesst."""
    try:
        klient = IMAPClient(
            host=server, port=port, ssl=(sicherheit == "ssl"), timeout=ZEITGRENZE
        )
        if sicherheit == "starttls":
            klient.starttls()
    except Exception as fehler:  # noqa: BLE001 - hier wird bewusst alles gedeutet
        raise _deuten(fehler, server, port) from fehler

    try:
        klient.login(benutzer, passwort)
    except LoginError as fehler:
        klient.shutdown()
        raise _anmeldefehler(app_passwort_wo) from fehler
    except Exception as fehler:  # noqa: BLE001
        klient.shutdown()
        raise _deuten(fehler, server, port) from fehler

    return klient


def smtp_pruefen(
    server: str, port: int, sicherheit: str, benutzer: str, passwort: str, app_passwort_wo: str = ""
) -> None:
    """Nur anmelden und wieder auflegen — nichts senden."""
    try:
        if sicherheit == "ssl":
            verbindung = smtplib.SMTP_SSL(server, port, timeout=ZEITGRENZE)
        else:
            verbindung = smtplib.SMTP(server, port, timeout=ZEITGRENZE)
            verbindung.starttls(context=ssl.create_default_context())
    except Exception as fehler:  # noqa: BLE001
        raise _deuten(fehler, server, port) from fehler

    try:
        verbindung.login(benutzer, passwort)
    except smtplib.SMTPAuthenticationError as fehler:
        raise _anmeldefehler(app_passwort_wo) from fehler
    except Exception as fehler:  # noqa: BLE001
        raise _deuten(fehler, server, port) from fehler
    finally:
        try:
            verbindung.quit()
        except Exception:  # noqa: BLE001 - beim Auflegen ist alles verzeihlich
            pass


# --- Ordner ------------------------------------------------------------- #

#: Die Kennzeichen aus RFC 6154. **Das ist der erste Weg**, weil er
#: sprachunabhaengig ist.
KENNZEICHEN = {
    rb"\Sent": "gesendet",
    rb"\Drafts": "entwuerfe",
    rb"\Trash": "papierkorb",
    rb"\Junk": "junk",
    rb"\Archive": "archiv",
}

#: ⚠️ **Die Namensliste ist die Rueckfallebene, und sie ist der Grund, warum
#: iCloud hier ueberhaupt auftaucht:** Dort heissen die Ordner „Sent Messages"
#: und „Deleted Messages", nicht „Sent" und „Trash". Wer nur auf die englischen
#: Kurzformen prueft, zeigt bei iCloud fuenf Ordner als „eigen" an.
NAMEN: dict[str, tuple[str, ...]] = {
    "gesendet": ("sent", "sent messages", "sent items", "gesendet", "gesendete objekte"),
    "entwuerfe": ("drafts", "draft", "entwürfe", "entwuerfe"),
    "papierkorb": ("trash", "deleted messages", "deleted items", "papierkorb", "gelöschte objekte"),
    "junk": ("junk", "spam", "junk e-mail", "bulk mail"),
    "archiv": ("archive", "archiv", "archives"),
}


@dataclass
class Ordnerangabe:
    pfad: str
    name: str
    rolle: str
    waehlbar: bool = True
    kennzeichen: list[str] = field(default_factory=list)


def _rolle_bestimmen(pfad: str, kennzeichen: list[bytes]) -> str:
    if pfad.upper() == "INBOX":
        return "posteingang"

    for kennung, rolle in KENNZEICHEN.items():
        if kennung in kennzeichen:
            return rolle

    letzter = pfad.split("/")[-1].split(".")[-1].strip().lower()
    for rolle, namen in NAMEN.items():
        if letzter in namen:
            return rolle
    return "eigen"


def ordner_lesen(klient: IMAPClient) -> list[Ordnerangabe]:
    """Die Ordner des Postfachs, mit erkannten Sonderrollen.

    ⚠️ **Nur abonnierte Ordner.** iCloud und Gmail legen Ordner an, die
    niemand sehen will (Gmails „All Mail" doppelt jede Nachricht). Was der
    Betreiber vermisst, kann er einblenden - was ihn beim ersten Blick
    erschlaegt, kommt nicht wieder weg.

    ⚠️ **Der Posteingang ist von dieser Regel ausgenommen** - siehe unten.
    """
    try:
        roh = klient.list_folders()
        abonniert = {name for _, _, name in klient.list_sub_folders()}
    except IMAPClientError as fehler:
        raise Verbindungsfehler(
            Fehlerart.UNERWARTET,
            "Die Ordnerliste ließ sich nicht lesen.",
            str(fehler),
        ) from fehler

    ergebnis: list[Ordnerangabe] = []
    for kennzeichen, trenner, pfad in roh:
        # Reine Zwischenknoten tragen nur Unterordner und lassen sich nicht
        # oeffnen. Sie kommen mit, damit der Baum stimmt - aber als nicht
        # waehlbar.
        waehlbar = rb"\Noselect" not in kennzeichen
        teil = trenner.decode() if isinstance(trenner, bytes) else (trenner or "/")
        name = pfad.split(teil)[-1] if teil else pfad
        ergebnis.append(
            Ordnerangabe(
                pfad=pfad,
                name=name or pfad,
                rolle=_rolle_bestimmen(pfad, list(kennzeichen)),
                waehlbar=waehlbar,
                kennzeichen=[k.decode(errors="replace") for k in kennzeichen],
            )
        )

    # Posteingang immer zuerst, danach Sonderordner, dann der Rest.
    rang = {
        "posteingang": 0,
        "gesendet": 1,
        "entwuerfe": 2,
        "archiv": 3,
        "junk": 4,
        "papierkorb": 5,
        "eigen": 6,
    }
    ergebnis.sort(key=lambda o: (rang[o.rolle], o.pfad.lower()))

    # Abonnement-Angabe anhaengen, ohne die Liste zu kuerzen: Die Entscheidung,
    # was angezeigt wird, faellt in der Oberflaeche.
    #
    # ⚠️ **Der Posteingang gilt immer als abonniert.** Viele Server fuehren
    # ``INBOX`` gar nicht erst in ``LSUB`` - er ist immer da und laesst sich
    # nicht abonnieren. Wer die Abonnementliste woertlich nimmt, blendet
    # ausgerechnet den einen Ordner aus, wegen dem die Anwendung existiert.
    # Bei All-Inkl ist genau das passiert: Gesendet, Entwuerfe, Archiv, Spam
    # und Papierkorb standen da, der Posteingang fehlte.
    for eintrag in ergebnis:
        ist_dabei = eintrag.pfad in abonniert or eintrag.rolle == "posteingang"
        eintrag.kennzeichen.append("abonniert" if ist_dabei else "nicht_abonniert")

    return ergebnis


def faehigkeiten(klient: IMAPClient) -> list[str]:
    """Was der Server kann. Gebraucht wird davon spaeter vor allem ``MOVE``."""
    return [k.decode(errors="replace") for k in klient.capabilities()]


__all__ = [
    "Fehlerart",
    "Ordnerangabe",
    "Verbindungsfehler",
    "faehigkeiten",
    "ordner_lesen",
    "smtp_pruefen",
    "verbinden",
]
