"""Regeln — was mit einer Nachricht geschehen soll, bevor man sie sieht.

Der Lauf ist absichtlich schlicht: Regeln von oben nach unten, jede prüft ihre
Bedingungen, die erste mit ``stopp`` beendet den Lauf.

⚠️ **Ohne ``stopp`` ist eine Regelkette schwer zu deuten.** Eine Nachricht
läuft sonst durch alle Regeln, und die letzte schiebt sie dorthin, wo die
erste sie gerade weggeholt hat. „Meine Regeln tun nichts" heißt fast immer:
Sie tun zu viel.

⚠️ **Regeln laufen im Abgleich, nicht beim Anzeigen.** Sonst hinge das
Ergebnis davon ab, ob jemand hinsieht — und auf dem Telefon läge die Mail
noch im Posteingang, während sie hier schon einsortiert ist.

⚠️ **Im Text wird nur gesucht, was schon da ist.** Der Abgleich holt Kopfdaten,
nicht Texte; eine Bedingung auf den Inhalt trifft deshalb auf den Anreißer zu,
nicht auf die ganze Mail. Das steht auch in der Oberfläche — eine Bedingung,
die stiller weniger prüft als angenommen, ist schlimmer als keine.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Nachricht, Ordner, Regel

logger = logging.getLogger("nexmail.regeln")

#: Worauf sich eine Bedingung beziehen kann.
FELDER = ("von", "an", "betreff", "inhalt")
#: Wie verglichen wird. Alles ohne Rücksicht auf Groß- und Kleinschreibung —
#: eine Regel, die an einem großen A scheitert, ist eine Falle.
VERGLEICHE = ("enthaelt", "enthaelt_nicht", "ist", "beginnt", "endet")
#: Was geschehen kann.
AKTIONEN = ("verschieben", "gelesen", "markieren", "loeschen")


class RegelFehler(RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


def _liste(roh: str) -> list[dict]:
    try:
        wert = json.loads(roh or "[]")
        return [e for e in wert if isinstance(e, dict)]
    except (ValueError, TypeError):
        return []


def pruefen(bedingungen: list[dict], aktionen: list[dict]) -> None:
    """Was die Oberfläche schickt, bevor es in die Datenbank geht."""
    if not bedingungen:
        raise RegelFehler("Eine Regel ohne Bedingung würde auf jede Nachricht zutreffen.")
    if not aktionen:
        raise RegelFehler("Eine Regel ohne Aktion tut nichts.")

    for b in bedingungen:
        if b.get("feld") not in FELDER:
            raise RegelFehler(f"Unbekanntes Feld: {b.get('feld')!r}")
        if b.get("vergleich") not in VERGLEICHE:
            raise RegelFehler(f"Unbekannter Vergleich: {b.get('vergleich')!r}")
        if not str(b.get("wert", "")).strip():
            raise RegelFehler("Eine Bedingung ohne Wert trifft auf nichts zu.")

    for a in aktionen:
        if a.get("art") not in AKTIONEN:
            raise RegelFehler(f"Unbekannte Aktion: {a.get('art')!r}")
        if a.get("art") == "verschieben" and not str(a.get("wert", "")).strip():
            raise RegelFehler("„Verschieben“ braucht einen Zielordner.")


# --- Prüfen ---------------------------------------------------------------- #


def _feldwert(nachricht: Nachricht, feld: str) -> str:
    if feld == "von":
        return f"{nachricht.von_name} {nachricht.von_adresse}"
    if feld == "an":
        return nachricht.an_json + " " + nachricht.kopie_json
    if feld == "betreff":
        return nachricht.betreff or ""
    # „inhalt": Was da ist. Siehe Kopf der Datei.
    return f"{nachricht.anreisser or ''} {nachricht.koerper_text or ''}"


def _trifft_zu(nachricht: Nachricht, bedingung: dict) -> bool:
    haystack = _feldwert(nachricht, bedingung.get("feld", "")).lower()
    nadel = str(bedingung.get("wert", "")).strip().lower()
    if not nadel:
        return False
    vergleich = bedingung.get("vergleich")
    if vergleich == "enthaelt":
        return nadel in haystack
    if vergleich == "enthaelt_nicht":
        return nadel not in haystack
    if vergleich == "ist":
        return haystack.strip() == nadel
    if vergleich == "beginnt":
        return haystack.strip().startswith(nadel)
    if vergleich == "endet":
        return haystack.strip().endswith(nadel)
    return False


def regel_trifft(nachricht: Nachricht, regel: Regel) -> bool:
    bedingungen = _liste(regel.bedingungen_json)
    if not bedingungen:
        # ⚠️ Eine Regel ohne Bedingung trifft **nicht** auf alles zu. Sie ist
        # kaputt, und kaputt heißt hier: tut nichts. Alles andere wäre ein
        # Postfach, das sich über Nacht selbst leert.
        return False
    treffer = (_trifft_zu(nachricht, b) for b in bedingungen)
    return all(treffer) if regel.verknuepfung != "oder" else any(treffer)


# --- Anwenden -------------------------------------------------------------- #


def meine(db: Session, person: Benutzer, konto_id: str = "") -> list[Regel]:
    frage = select(Regel).where(Regel.benutzer_id == person.id)
    return sorted(
        (
            r
            for r in db.execute(frage).scalars().all()
            if not konto_id or not r.konto_id or r.konto_id == konto_id
        ),
        key=lambda r: (r.reihenfolge, r.id),
    )


def anwenden(db: Session, person: Benutzer, nachrichten: list[Nachricht]) -> dict[str, int]:
    """Die Regeln auf eine Handvoll Nachrichten anwenden.

    Gibt zurück, wie oft welche Aktion gegriffen hat. Das Verschieben läuft
    über ``handeln`` — also mit IMAP-Befehl und Abgleich, nicht nur lokal.
    """
    from . import handeln as handelndienst

    stand = {"geprueft": 0, "getroffen": 0, "verschoben": 0, "gelesen": 0, "markiert": 0}
    if not nachrichten:
        return stand

    regeln = [r for r in meine(db, person) if r.aktiv]
    if not regeln:
        return stand

    # ⚠️ **Nach Zielordner sammeln, dann einmal verschieben.** Je Nachricht
    # einzeln hieße: je Nachricht eine IMAP-Verbindung. Bei zwanzig neuen
    # Mails dauert der Abgleich dann Minuten.
    zu_verschieben: dict[int, list[Nachricht]] = {}

    for nachricht in nachrichten:
        stand["geprueft"] += 1
        getroffen = False
        for regel in regeln:
            if regel.konto_id and regel.konto_id != nachricht.konto_id:
                continue
            if not regel_trifft(nachricht, regel):
                continue
            getroffen = True

            for aktion in _liste(regel.aktionen_json):
                art = aktion.get("art")
                if art == "gelesen":
                    nachricht.gelesen = True
                    stand["gelesen"] += 1
                elif art == "markieren":
                    nachricht.markiert = True
                    stand["markiert"] += 1
                elif art in ("verschieben", "loeschen"):
                    ziel = _ziel_bestimmen(db, nachricht, aktion, art)
                    if ziel is not None and ziel.id != nachricht.ordner_id:
                        zu_verschieben.setdefault(ziel.id, []).append(nachricht)

            if regel.stopp:
                break
        if getroffen:
            stand["getroffen"] += 1

    db.commit()

    for ordner_id, gruppe in zu_verschieben.items():
        ziel = db.get(Ordner, ordner_id)
        if ziel is None:
            continue
        # Eine Nachricht kann durch zwei Regeln in zwei Ordner gewiesen
        # werden. Der erste Treffer gewinnt; alles andere wäre ein Zug ins
        # Nichts, weil die Zeile nach dem ersten Verschieben nicht mehr da ist.
        frisch = [n for n in gruppe if db.get(Nachricht, n.id) is not None]
        if not frisch:
            continue
        try:
            handelndienst.verschieben(db, frisch, ziel)
            stand["verschoben"] += len(frisch)
        except handelndienst.HandelnFehler as fehler:
            # ⚠️ Eine Regel, die nicht greift, darf den Abgleich nicht
            # abbrechen - sonst kommt wegen einer krummen Regel gar keine Post
            # mehr an.
            logger.warning("A rule could not move messages: %s", fehler)

    if stand["getroffen"]:
        logger.info("Rules matched %s of %s message(s).", stand["getroffen"], stand["geprueft"])
    return stand


def _ziel_bestimmen(db: Session, nachricht: Nachricht, aktion: dict, art: str) -> Ordner | None:
    if art == "loeschen":
        return (
            db.execute(
                select(Ordner).where(
                    Ordner.konto_id == nachricht.konto_id, Ordner.rolle == "papierkorb"
                )
            )
            .scalars()
            .first()
        )
    try:
        ordner = db.get(Ordner, int(str(aktion.get("wert", "")).strip()))
    except (TypeError, ValueError):
        return None
    # ⚠️ Nie in ein fremdes Postfach. Eine Regel mit einem alten Zielordner
    # würde sonst Post quer über Konten schieben.
    if ordner is None or ordner.konto_id != nachricht.konto_id:
        return None
    return ordner


def rueckwirkend(db: Session, person: Benutzer, ordner: Ordner) -> dict[str, int]:
    """Die Regeln auf einen bestehenden Ordner anwenden.

    ⚠️ **Das ist der Grund, warum Regeln überhaupt benutzt werden.** Wer sie
    anlegt, hat schon dreitausend Mails im Posteingang - eine Regel, die erst
    ab morgen gilt, räumt nichts auf.
    """
    nachrichten = (
        db.execute(select(Nachricht).where(Nachricht.ordner_id == ordner.id)).scalars().all()
    )
    return anwenden(db, person, list(nachrichten))


__all__ = [
    "AKTIONEN",
    "FELDER",
    "RegelFehler",
    "VERGLEICHE",
    "anwenden",
    "meine",
    "pruefen",
    "regel_trifft",
    "rueckwirkend",
]
