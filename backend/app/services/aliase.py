"""Absender-Aliasse je Postfach.

Eine zweite Adresse, die im selben Postfach landet: empfangen auf ``x@``,
antworten als ``x@``. Ohne das antwortet nexmail immer als Hauptadresse, und
wer sich eine Zweitadresse eingerichtet hat, verrät sie bei jeder Antwort.

⚠️ **Eine Spalte, keine Nebentabelle.** Es sind eine Handvoll je Postfach, und
keine Abfrage sucht nach einem Alias — beim Antworten wird in Python über die
paar Adressen des Kontos gegangen. Dieselbe Überlegung wie bei ``konto.tags``
und ``nachricht.schlagworte``.

⚠️ **Der Server entscheidet, was hinausgeht, nicht der Browser.** Die gewählte
Absenderadresse kommt aus der Oberfläche und wird gegen das Konto geprüft. Ohne
diese Prüfung könnte jeder Benutzer eine Mail unter **jeder beliebigen** Adresse
verschicken — der Mailserver sieht nur unsere Anmeldung, nicht wer im Browser
sitzt. Das ist die einzige sicherheitsrelevante Stelle dieser Funktion.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ..meldung import Meldung
from ..models import Konto
from .kontakte import _ADRESSE

logger = logging.getLogger("nexmail.aliase")


class AliasFehler(Meldung, RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


#: ⚠️ **Gedeckelt, weil es mit dem Bestand wächst.** Wer wirklich mehr braucht,
#: hat kein Postfach mehr, sondern einen Verteiler.
MAX_ALIASE = 20
MAX_NAME = 120


@dataclass(frozen=True)
class Alias:
    """Eine zusätzliche Absenderadresse dieses Postfachs."""

    adresse: str
    #: Leer heißt: der Absendername des Kontos gilt weiter.
    name: str = ""


def lesen(konto: Konto) -> list[Alias]:
    """Die Aliasse des Kontos.

    ⚠️ **Kaputtes JSON darf das Postfach nicht kosten.** Es kommt aus der
    eigenen Datenbank, aber ein halb eingespieltes Archiv oder ein Eingriff von
    Hand sind denkbar; dann gilt „keine Aliasse" statt einer Seite, die nicht
    lädt. Dieselbe Haltung wie bei den Teilnehmern eines Termins.
    """
    try:
        roh = json.loads(konto.aliase or "[]")
    except ValueError:
        logger.warning("Account %s has unreadable aliases; ignoring them", konto.id)
        return []
    if not isinstance(roh, list):
        return []
    raus: list[Alias] = []
    for eintrag in roh:
        if isinstance(eintrag, dict) and isinstance(eintrag.get("adresse"), str):
            name = eintrag.get("name")
            raus.append(Alias(eintrag["adresse"], name if isinstance(name, str) else ""))
    return raus


def schreiben(konto: Konto, eintraege: list[Alias]) -> None:
    """Die Aliasse ersetzen — geprüft und normiert.

    ⚠️ **Klein verglichen, klein gespeichert.** ``Max@example.com`` und
    ``max@example.com`` sind dieselbe Adresse; zwei Einträge dafür wären zwei
    Zeilen in der Liste, die dasselbe tun, und die Wahl beim Antworten fiele
    dann auf gut Glück.
    """
    sauber: list[Alias] = []
    gesehen = {konto.adresse.strip().lower()}
    for eintrag in eintraege:
        adresse = eintrag.adresse.strip().lower()
        if not _ADRESSE.match(adresse):
            raise AliasFehler("alias_adresse_ungueltig", adresse=adresse)
        # ⚠️ Die Hauptadresse ist kein Alias — sie steht ohnehin zur Wahl.
        # Sie hier zuzulassen ergäbe zwei gleiche Einträge in der Liste.
        if adresse in gesehen:
            continue
        gesehen.add(adresse)
        sauber.append(Alias(adresse, eintrag.name.strip()[:MAX_NAME]))
    if len(sauber) > MAX_ALIASE:
        raise AliasFehler("alias_zu_viele", max=MAX_ALIASE)
    konto.aliase = json.dumps([{"adresse": a.adresse, "name": a.name} for a in sauber])


def absender_pruefen(konto: Konto, gewuenscht: str) -> Alias:
    """Welcher Absender wirklich hinausgeht.

    ⚠️ **Nie die Adresse aus der Anfrage übernehmen.** Sie wird gegen die
    Hauptadresse und die hinterlegten Aliasse gehalten; was nicht dazugehört,
    wird abgewiesen. Leer heißt „die Hauptadresse", damit alte Oberflächen und
    jeder andere Aufrufer weiterlaufen.
    """
    haupt = konto.adresse.strip().lower()
    wunsch = (gewuenscht or "").strip().lower()
    if not wunsch or wunsch == haupt:
        return Alias(konto.adresse, "")
    for alias in lesen(konto):
        if alias.adresse == wunsch:
            return alias
    raise AliasFehler("alias_unbekannt", adresse=wunsch)


def passend(konto: Konto, empfaenger: list[str]) -> Alias | None:
    """Der Alias, an den eine Nachricht ging — für die Antwort.

    ⚠️ **Das ist der ganze Zweck.** Wer auf eine Mail an ``x@`` antwortet, will
    als ``x@`` antworten; sonst erfährt der andere die Hauptadresse, und die
    Trennung, für die man sich die Zweitadresse geholt hat, ist dahin.

    ⚠️ **Die Hauptadresse gewinnt.** Stand sie unter den Empfängern, bleibt es
    bei ihr — sie ist die Vorgabe, und ein Alias soll sie nicht verdrängen,
    bloß weil beide angeschrieben waren.
    """
    dabei = {a.strip().lower() for a in empfaenger if a and a.strip()}
    if konto.adresse.strip().lower() in dabei:
        return None
    for alias in lesen(konto):
        if alias.adresse in dabei:
            return alias
    return None
