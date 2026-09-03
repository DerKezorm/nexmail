"""Suche — im Zwischenspeicher und, auf Wunsch, beim Anbieter.

nexmail hält **alle Kopfdaten** vor, aber die Texte nur von dem, was einmal
geöffnet wurde. Daraus folgt der Zuschnitt der Suche:

* **Betreff und Absender** findet sie immer, auch in zwanzig Jahre alter Post.
* **Im Text** findet sie nur, was schon einmal geholt wurde.
* Wer mehr will, schickt die Suche ausdrücklich zum Anbieter (``IMAP SEARCH``).
  Das dauert und wird deshalb nie von selbst getan.

⚠️ **Der Unterschied muss in der Oberfläche stehen.** Eine Suche, die still
weniger durchsucht, als der Betreiber annimmt, ist schlimmer als gar keine: Er
schließt aus null Treffern, dass es die Mail nicht gibt.

Der Index
=========

FTS5 mit ``content='nachricht'`` — der Text liegt also **einmal** da, nicht
zweimal. Gepflegt wird er von Auslösern in SQLite selbst, nicht von Python:
Der Abgleich schreibt an mehreren Stellen in ``nachricht``, und eine davon
würde man vergessen.

⚠️ **Der Auslöser beim Ändern hängt an einer Spaltenliste** (``UPDATE OF …``).
Ohne sie feuerte er bei **jedem** Setzen von „gelesen" mit — und das passiert
im Abgleich für Tausende Zeilen auf einmal. Der Index würde dabei jedes Mal
neu geschrieben, ohne dass sich ein Wort geändert hätte.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from ..models import Benutzer, Konto, Nachricht, Ordner

logger = logging.getLogger("nexmail.suche")

#: Die durchsuchten Felder. Reihenfolge = Spaltenreihenfolge im Index; wer sie
#: ändert, muss den Index neu bauen.
FELDER = ("betreff", "von_name", "von_adresse", "anreisser", "koerper_text")

_SPALTEN = ", ".join(FELDER)
_NEU = ", ".join(f"new.{f}" for f in FELDER)
_ALT = ", ".join(f"old.{f}" for f in FELDER)

SCHEMA = [
    # ``remove_diacritics 2``: „Muller" findet „Müller" und umgekehrt. Ohne das
    # muss man den Namen buchstabengenau treffen, und genau daran scheitert
    # eine Suche im deutschen Alltag.
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS nachricht_fts USING fts5(
        {_SPALTEN},
        content='nachricht',
        content_rowid='id',
        tokenize="unicode61 remove_diacritics 2"
    )
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS nachricht_fts_neu AFTER INSERT ON nachricht BEGIN
        INSERT INTO nachricht_fts(rowid, {_SPALTEN}) VALUES (new.id, {_NEU});
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS nachricht_fts_weg AFTER DELETE ON nachricht BEGIN
        INSERT INTO nachricht_fts(nachricht_fts, rowid, {_SPALTEN})
        VALUES ('delete', old.id, {_ALT});
    END
    """,
    # ⚠️ ``UPDATE OF`` ist hier kein Feinschliff - siehe Kopf der Datei.
    f"""
    CREATE TRIGGER IF NOT EXISTS nachricht_fts_aend
    AFTER UPDATE OF {_SPALTEN} ON nachricht BEGIN
        INSERT INTO nachricht_fts(nachricht_fts, rowid, {_SPALTEN})
        VALUES ('delete', old.id, {_ALT});
        INSERT INTO nachricht_fts(rowid, {_SPALTEN}) VALUES (new.id, {_NEU});
    END
    """,
]


#: Woran nexmail erkennt, ob der Index zum Code passt. Ändert sich die
#: Feldliste, ändert sich die Kennung - und der Index wird einmal neu gebaut.
KENNUNG = "fts5:" + ",".join(FELDER)


def schema_anlegen(engine: Engine) -> None:
    """Index und Auslöser anlegen — und ihn füllen, wenn er noch nicht passt.

    ⚠️ **Ein frisch angelegter Index ist leer, auch wenn Nachrichten da sind.**
    Die Auslöser feuern nur bei neuen Zeilen; alles, was vor ihnen da war,
    bleibt unsichtbar. Das trifft jede bestehende Installation, die ein Update
    bekommt — die Suche fände dort **nichts** und würde dabei nicht einmal
    murren. Genau so beim ersten Lauf aufgefallen: Index stand, Postfach voll,
    Suche fand null.

    ⚠️ **Nicht über ``count(*)`` prüfen.** Bei ``content='nachricht'`` zählt
    das die **Inhaltstabelle**, nicht den Index: Die Prüfung meldet „voll",
    auch wenn kein einziges Wort indiziert ist. Nachgemessen, nicht vermutet.
    Deshalb steht der Stand als eigener Eintrag in ``einstellung``.

    Eine **Wiederherstellung** braucht das übrigens nicht: Die Schattentabellen
    von FTS5 sind gewöhnliche Tabellen in derselben Datei und werden
    mitkopiert. Auch das ist nachgemessen.
    """
    with engine.begin() as verbindung:
        for anweisung in SCHEMA:
            verbindung.execute(text(anweisung))

        stand = verbindung.execute(
            text("SELECT wert FROM einstellung WHERE schluessel = 'suche_index'")
        ).scalar()
        if stand == KENNUNG:
            return

        nachrichten = verbindung.execute(text("SELECT count(*) FROM nachricht")).scalar() or 0
        if nachrichten:
            verbindung.execute(text("INSERT INTO nachricht_fts(nachricht_fts) VALUES ('rebuild')"))
            logger.info("The full-text index was built for %s existing messages.", nachrichten)
        verbindung.execute(
            text(
                "INSERT INTO einstellung (schluessel, wert) VALUES ('suche_index', :k) "
                "ON CONFLICT(schluessel) DO UPDATE SET wert = :k"
            ),
            {"k": KENNUNG},
        )


def neu_aufbauen(db: Session) -> int:
    """Den Index aus der Tabelle neu befüllen.

    Der Notnagel von Hand. Im Regelfall macht das ``schema_anlegen`` beim
    Start selbst; hier steht es für den Fall, dass ein Index nachweislich
    nicht mehr zu den Nachrichten passt.
    """
    db.execute(text("INSERT INTO nachricht_fts(nachricht_fts) VALUES ('rebuild')"))
    db.commit()
    # ⚠️ **Zaehlen, nicht holen.** Hier stand ``select(Nachricht.id)`` samt
    # ``len()`` darauf — bei 250.000 Nachrichten eine Python-Liste mit
    # 250.000 Ganzzahlen, nur um sie zu zaehlen.
    anzahl = db.execute(select(func.count(Nachricht.id))).scalar_one()
    logger.info("Full-text index rebuilt for %s messages.", anzahl)
    return anzahl


def index_verdichten(db: Session) -> None:
    """Den Volltextindex zusammenschieben, nachdem geloescht wurde.

    ⚠️ **Ein Loeschen macht den Index groesser, nicht kleiner.** FTS5 traegt
    die Loeschung als eigenen Eintrag nach; die alten Segmente bleiben stehen,
    bis sie jemand zusammenschiebt. Am 03.09.2026 gemessen: Nach dem Loeschen
    aller 2.717 Nachrichten war ``nachricht_fts_data`` von 492.588 auf 497.759
    Byte **gewachsen**. Erst ``optimize`` holte es auf 30 Byte herunter, also
    rund 291 Byte toter Index je geloeschter Nachricht.

    ⚠️ **Nur wenn wirklich etwas wegfiel**, und darum vom Aufraeumdienst
    gerufen: Der laeuft hoechstens einmal am Tag. ``optimize`` liest den ganzen
    Index; bei jedem Loeschen waere das teurer als der Gewinn.

    ⚠️ **Das ist nicht ``VACUUM``.** Die Datenbankdatei selbst schrumpft
    dabei nicht — der frei gewordene Platz steht in der Freiliste und wird
    wiederverwendet. Ein ``VACUUM`` braucht kurzzeitig den doppelten Platz und
    sperrt die Datei; das gehoert dem Betreiber in die Hand gegeben und nicht
    in einen Hintergrundfaden.
    """
    db.execute(text("INSERT INTO nachricht_fts(nachricht_fts) VALUES ('optimize')"))
    db.commit()


# --- Die Anfrage --------------------------------------------------------- #

#: Zeichen, die FTS5 als Syntax liest. Ein Betreff mit einem davon darf die
#: Suche nicht zum Fehler machen.
_SYNTAX = re.compile(r'[":^*(){}\[\]-]')


def begriff_bauen(eingabe: str) -> str:
    """Aus dem, was jemand tippt, eine FTS5-Anfrage machen.

    ⚠️ **Die Eingabe geht nie roh in die Anfrage.** Ein Anführungszeichen
    oder ein Bindestrich ist für FTS5 Syntax, nicht Text — die Suche nach
    ``Mayer-Schulz`` oder ``"Angebot"`` bräche mit einem Fehler ab, den
    niemand deuten kann. Jedes Wort wird deshalb in Anführungszeichen gefasst
    und die Syntaxzeichen darin entfernt.

    Angehängtes ``*`` beim letzten Wort: Wer „rech" tippt, meint „Rechnung".
    Das ist die Erwartung aus jedem anderen Suchfeld.
    """
    woerter = [_SYNTAX.sub(" ", w).strip() for w in eingabe.split()]
    woerter = [w for w in woerter if w]
    if not woerter:
        return ""
    *anfang, letztes = woerter
    teile = [f'"{w}"' for w in anfang]
    teile.append(f'"{letztes}"*')
    return " ".join(teile)


def suchen(
    db: Session,
    person: Benutzer,
    eingabe: str,
    bereich: str = "alle",
    ordner_id: int | None = None,
    konto_id: str | None = None,
    grenze: int = 200,
) -> list[Nachricht]:
    """Im Zwischengespeicherten suchen.

    ``bereich`` ist ``ordner``, ``postfach`` oder ``alle``. Die Einschränkung
    auf den eigenen Benutzer läuft **immer** mit, unabhängig vom Bereich —
    „alle" heißt alle **meine**.
    """
    begriff = begriff_bauen(eingabe)
    if not begriff:
        return []

    treffer = db.execute(
        text(
            "SELECT rowid FROM nachricht_fts WHERE nachricht_fts MATCH :b "
            "ORDER BY rank LIMIT :n"
        ),
        {"b": begriff, "n": grenze * 4},
    ).scalars().all()
    if not treffer:
        return []

    frage = select(Nachricht).where(
        Nachricht.id.in_(treffer),
        # ⚠️ Nie ohne das. Der Volltextindex kennt keine Benutzer.
        Nachricht.benutzer_id == person.id,
    )
    if bereich == "ordner" and ordner_id is not None:
        frage = frage.where(Nachricht.ordner_id == ordner_id)
    elif bereich == "postfach" and konto_id:
        frage = frage.where(Nachricht.konto_id == konto_id)

    return list(
        db.execute(frage.order_by(Nachricht.datum.desc()).limit(grenze)).scalars().all()
    )


def ordner_fuer_bereich(
    db: Session, person: Benutzer, bereich: str, ordner_id: int | None, konto_id: str | None
) -> list[Ordner]:
    """Welche Ordner eine Serversuche abklappern müsste."""
    frage = select(Ordner).join(Konto, Konto.id == Ordner.konto_id).where(
        Konto.benutzer_id == person.id, Ordner.waehlbar.is_(True)
    )
    if bereich == "ordner" and ordner_id is not None:
        frage = frage.where(Ordner.id == ordner_id)
    elif bereich == "postfach" and konto_id:
        frage = frage.where(Ordner.konto_id == konto_id)
    return list(db.execute(frage).scalars().all())


def beim_anbieter_suchen(
    db: Session,
    person: Benutzer,
    eingabe: str,
    bereich: str = "alle",
    ordner_id: int | None = None,
    konto_id: str | None = None,
    grenze: int = 200,
) -> list[Nachricht]:
    """``IMAP SEARCH`` — findet auch in Texten, die nie geholt wurden.

    ⚠️ **Das dauert, und zwar sichtbar.** Der Server durchsucht jeden Ordner
    einzeln, und bei einem großen Postfach sind das Sekunden. Deshalb passiert
    es nur, wenn der Betreiber es ausdrücklich verlangt — nie nebenbei.

    ⚠️ **Zurück kommen nur Nachrichten, die nexmail schon kennt.** Der Server
    liefert UIDs; die Kopfdaten dazu stehen bereits in der Datenbank, weil der
    Erstabgleich alle geholt hat. Findet der Server eine UID, die hier fehlt,
    wird sie übergangen statt einzeln nachgeladen: Das wäre eine Abfrage je
    Treffer.
    """
    from . import abgleich, imap as imapdienst, konten as kontendienst

    begriffe = eingabe.strip()
    if not begriffe:
        return []

    gefunden: list[Nachricht] = []
    ordner = ordner_fuer_bereich(db, person, bereich, ordner_id, konto_id)

    # Nach Postfach gruppieren: eine Verbindung je Konto, nicht je Ordner.
    nach_konto: dict[str, list[Ordner]] = {}
    for o in ordner:
        nach_konto.setdefault(o.konto_id, []).append(o)

    for kid, seine in nach_konto.items():
        konto = db.get(Konto, kid)
        if konto is None:
            continue
        imap_pw, _ = kontendienst.passwoerter_lesen(konto)
        try:
            with abgleich.HALTER.schloss(konto.id):
                klient = imapdienst.fuer_konto(db, konto)
                try:
                    for o in seine:
                        gefunden.extend(_ordner_absuchen(db, klient, o, begriffe, grenze))
                finally:
                    try:
                        klient.logout()
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as fehler:  # noqa: BLE001
            # ⚠️ Ein Postfach, das gerade nicht antwortet, darf die Suche in
            # den anderen nicht abwerfen. Der Betreiber bekommt lieber
            # Teiltreffer als eine Fehlermeldung statt Ergebnissen.
            logger.warning("Server search failed for one mailbox: %s", fehler)

    gefunden.sort(key=lambda n: n.datum, reverse=True)
    return gefunden[:grenze]


def _ordner_absuchen(db: Session, klient, ordner: Ordner, begriffe: str, grenze: int):
    try:
        klient.select_folder(ordner.pfad, readonly=True)
        # ``TEXT`` sucht in Kopfzeilen **und** Rumpf - das ist, was jemand
        # erwartet, der etwas in ein Suchfeld tippt.
        uids = klient.search(["TEXT", begriffe])
    except Exception as fehler:  # noqa: BLE001
        logger.info("Server search skipped folder %s: %s", ordner.pfad, fehler)
        return []
    if not uids:
        return []
    return (
        db.execute(
            select(Nachricht)
            .where(Nachricht.ordner_id == ordner.id, Nachricht.uid.in_(list(uids)[-grenze:]))
        )
        .scalars()
        .all()
    )


__all__ = [
    "begriff_bauen",
    "beim_anbieter_suchen",
    "neu_aufbauen",
    "ordner_fuer_bereich",
    "schema_anlegen",
    "suchen",
]
