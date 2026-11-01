"""Von einer Liste abmelden, aus ``List-Unsubscribe`` (RFC 2369 und RFC 8058).

Eine Mail nennt in dieser Kopfzeile bis zu mehrere Wege, in spitzen Klammern
und in der Reihenfolge, die der Absender bevorzugt. Drei Fälle werden daraus:

* **Ein Klick** (``einklick``): Die Mail trägt zusätzlich
  ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``. nexmails Server
  schickt das ``POST`` selbst, der Browser sieht die fremde Seite nie.
* **Eine Seite** (``seite``): Sie geht im Browser auf; ein Mensch bestätigt dort.
* **Eine Mail** (``mail``): Das Verfassen-Fenster geht vorbelegt auf.
  ⚠️ **nexmail verschickt sie nicht von selbst.** Sie trägt die eigene Adresse.

⚠️ **Ein Klick nur nach bestandener Absenderprüfung.** RFC 8058 verlangt eine
gültige DKIM-Unterschrift über beide Kopfzeilen. Ohne sie kann jeder eine Mail
schreiben, die nexmails Server auf Knopfdruck an eine Adresse seiner Wahl
schreiben lässt. Besteht die Mail nicht, bleibt die Seite im Browser, und die
Rückfrage nennt ihre Domain.

⚠️ **Die Adresse kommt aus der gespeicherten Mail, nie aus der Anfrage.** Sonst
wäre die Route ein offener Vermittler für beliebige ``POST``.

⚠️ **Im Junk-Ordner gibt es keinen Knopf.** Eine Abmeldung bestätigt dort dem
Absender, dass die Adresse gelesen wird, und genau das will er wissen.
"""

from __future__ import annotations

import email
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

from ..meldung import Meldung
from ..models import Nachricht
from . import absenderpruefung, bildvermittler

logger = logging.getLogger("nexmail.abbestellen")

#: Der Rumpf, den RFC 8058 wörtlich vorschreibt.
EINKLICK_RUMPF = "List-Unsubscribe=One-Click"

#: Wie lange der fremde Server antworten darf.
ZEITGRENZE = 15.0

#: Wie viele Weiterleitungen mit Beibehaltung des ``POST`` mitgegangen werden.
MAX_SPRUENGE = 3

#: Längere Adressen gibt es hier nicht; was länger ist, ist kein Abmeldeweg.
MAX_ADRESSE = 2000

#: So viele Wege bleiben stehen. Die Kopfzeile schreibt der Absender.
MAX_ZIELE = 4

_ZIEL = re.compile(r"<([^<>\s]+)>")

_SCHEMATA = ("https", "http", "mailto")


class AbbestellFehler(Meldung):
    """Etwas, das dem Menschen davor gezeigt wird."""


@dataclass(frozen=True)
class Weg:
    #: ``einklick`` | ``seite`` | ``mail``
    art: str
    ziel: str
    #: Was die Rückfrage nennt: die Domain oder die Adresse.
    stelle: str


def _kopf(nachricht: email.message.Message, name: str) -> str:
    return " ".join(" ".join(str(w).split()) for w in nachricht.get_all(name, []))


def lesen(kopfteil: bytes) -> str:
    """Aus dem Kopfteil einer Mail die Spalte ``abbestellen`` machen.

    ⚠️ **Nur die drei Schemata.** Die Adresse landet später in einem Link; ein
    ``javascript:`` hat dort nichts zu suchen, und was der Server anruft,
    prüft er ohnehin noch einmal.
    """
    kopf = email.message_from_bytes(kopfteil)
    ziele = [
        ziel
        for ziel in _ZIEL.findall(_kopf(kopf, "List-Unsubscribe"))
        if ziel.partition(":")[0].lower() in _SCHEMATA
        and len(ziel) <= MAX_ADRESSE
        and ziel.isprintable()
    ][:MAX_ZIELE]
    if not ziele:
        return ""
    # ⚠️ **Der genaue Wert, nicht „irgendetwas".** Der Kopf sagt, dass ein
    # blosses POST genügt; ein anderer Wert sagt das nicht.
    einklick = _kopf(kopf, "List-Unsubscribe-Post").lower() == EINKLICK_RUMPF.lower()
    return json.dumps({"ziele": ziele, "einklick": einklick}, ensure_ascii=False)


def _stelle(ziel: str) -> str:
    if ziel.lower().startswith("mailto:"):
        return unquote(ziel[7:].partition("?")[0])
    return urlsplit(ziel).hostname or ""


def weg(nachricht: Nachricht, vertraut: dict[str, str]) -> Weg | None:
    """Welcher Weg für diese Mail gilt, oder keiner."""
    if not nachricht.abbestellen or nachricht.ordner.rolle == "junk":
        return None
    try:
        daten = json.loads(nachricht.abbestellen)
        ziele = [str(z) for z in daten["ziele"]]
        einklick = bool(daten["einklick"])
    except (ValueError, KeyError, TypeError):
        return None
    if not ziele:
        return None

    sicher = next((z for z in ziele if z.lower().startswith("https:")), "")
    if einklick and sicher and absenderpruefung.geprueft(nachricht, vertraut):
        return Weg("einklick", sicher, _stelle(sicher))
    # Sonst der erste, den der Absender nennt: RFC 2369 legt die Reihenfolge
    # in seine Hand.
    erster = ziele[0]
    art = "mail" if erster.lower().startswith("mailto:") else "seite"
    return Weg(art, erster, _stelle(erster))


def einklick_weg(nachricht: Nachricht, vertraut: dict[str, str]) -> Weg:
    """Der Weg für das ``POST``, oder eine Absage."""
    gefunden = weg(nachricht, vertraut)
    if gefunden is None or gefunden.art != "einklick":
        raise AbbestellFehler("abbestellen_nicht_moeglich")
    return gefunden


def einklick_senden(url: str, transport: object | None = None) -> None:
    """Das ``POST`` nach RFC 8058.

    ⚠️ **Ohne Keks, ohne Kopfzeilen aus der Mail**, wie beim Bildvermittler:
    Der fremde Server erfährt die IP dieses Servers und sonst nichts.

    ⚠️ **Dieselbe Wache vor jedem Sprung.** Eine Adresse aus einer fremden Mail
    darf nicht ins eigene Netz zeigen, auch nicht über eine Weiterleitung. Nur
    307 und 308 werden verfolgt, weil nur sie das ``POST`` behalten. Alle
    anderen Weiterleitungen führen auf eine Dankeseite: Die Abmeldung ist dann
    angekommen.

    ⚠️ **Der Rumpf der Antwort wird nicht gelesen.** Niemand braucht ihn, und
    ein fremder Server soll den Speicher nicht füllen können.
    """
    ziel = url
    with httpx.Client(
        timeout=ZEITGRENZE,
        follow_redirects=False,
        transport=transport,
        headers={"user-agent": "nexmail"},
    ) as klient:
        for _ in range(MAX_SPRUENGE + 1):
            if urlsplit(ziel).scheme != "https":
                raise AbbestellFehler("abbestellen_adresse_unerlaubt")
            try:
                bildvermittler.adresse_pruefen(ziel)
            except bildvermittler.Abgelehnt as fehler:
                raise AbbestellFehler("abbestellen_adresse_unerlaubt") from fehler
            try:
                with klient.stream(
                    "POST",
                    ziel,
                    content=EINKLICK_RUMPF,
                    headers={"content-type": "application/x-www-form-urlencoded"},
                ) as antwort:
                    code = antwort.status_code
                    weiter = antwort.headers.get("location")
            except httpx.HTTPError as fehler:
                logger.info("An unsubscribe request failed: %s", type(fehler).__name__)
                raise AbbestellFehler("abbestellen_nicht_erreichbar") from fehler
            if code in (307, 308) and weiter:
                ziel = str(httpx.URL(ziel).join(weiter))
                continue
            if code < 400:
                return
            raise AbbestellFehler("abbestellen_abgewiesen", code=code)
    raise AbbestellFehler("abbestellen_nicht_erreichbar")


__all__ = ["AbbestellFehler", "Weg", "einklick_senden", "einklick_weg", "lesen", "weg"]
