"""Welche Nachrichten zu einem Strang gehoeren.

⚠️ **Falsch gruppiert versteckt eine Nachricht.** Sie steckt dann in einem
zugeklappten Strang, und man merkt es erst, wenn man sie sucht. Deshalb ist
hier alles auf Vorsicht gebaut: Die verlaessliche Antwortkette entscheidet, der
Betreff ist nur ein Rueckfall — und der greift erst, wenn **drei** Bedingungen
zugleich stimmen.

⚠️ **Der Schluessel wird beim Schreiben bestimmt, nicht beim Lesen.** Sonst
muesste jede Listenabfrage Ketten aufloesen, und das bei jedem Tastendruck.
Hier kostet es einmal beim Abgleich.

⚠️ **Der alte Schluessel hatte einen Fehler** (bis 01.09.2026): Er nahm bei
einer Nachricht ohne ``References`` den **Betreff-Hash**. Eine Antwort darauf
traegt aber ``References: <kennung-der-ersten>`` — und bekam damit einen
anderen Schluessel als die Nachricht, auf die sie antwortet. Der Strang zerfiel
also genau an der Stelle, an der er entsteht. Die Wurzel ist die eigene
``Message-ID``, nicht ihr Betreff.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Konto, Nachricht

logger = logging.getLogger("nexmail.straenge")

#: ⚠️ **Der Rueckfall ueber den Betreff gilt nur in diesem Fenster.** „Rechnung"
#: schreibt derselbe Absender jeden Monat; ohne Grenze waeren zwei Jahre
#: Rechnungen ein einziger Strang, in dem die aktuelle verschwindet.
FENSTER = timedelta(days=30)


def _beteiligte(nachricht: Nachricht) -> set[str]:
    """Alle Adressen einer Nachricht, klein geschrieben."""
    heraus = {nachricht.von_adresse.lower()} if nachricht.von_adresse else set()
    for feld in (nachricht.an_json, nachricht.kopie_json):
        try:
            for eintrag in json.loads(feld or "[]"):
                adresse = (eintrag.get("adresse") or "").lower()
                if adresse:
                    heraus.add(adresse)
        except (ValueError, AttributeError):
            continue
    return heraus


def schluessel(
    db: Session,
    konto: Konto,
    *,
    message_id: str,
    references: list[str],
    in_reply_to: str,
    betreff_kern: str,
    beteiligte: set[str],
    datum: datetime | None,
) -> str:
    """Den Strang bestimmen, zu dem diese Nachricht gehoert.

    Die Reihenfolge ist die Reihenfolge der Verlaesslichkeit:

    1. **Eine Nachricht aus der Antwortkette, die schon da ist.** Ihr Strang
       gilt. Das faengt auch den Fall, dass die Wurzel selbst fehlt — geloescht
       oder nie in diesem Postfach gewesen.
    2. **Die Wurzel der Kette**, wenn keine davon hier liegt.
    3. **Der Rueckfall ueber den Betreff** — nur mit gemeinsamen Beteiligten
       und innerhalb von 30 Tagen.
    4. **Die eigene Kennung.** Diese Nachricht ist die Wurzel eines neuen
       Strangs.
    """
    kette = [k for k in (list(references) + [in_reply_to]) if k]

    if kette:
        # ⚠️ Ueber ``message_id`` **und** ueber ``thread_key`` suchen: Die
        # Antwort kann auf eine Nachricht zeigen, die selbst schon einem Strang
        # zugeordnet wurde. Nur ueber die Kennung zu suchen risse den Strang
        # bei jeder zweiten Antwort auseinander.
        treffer = db.execute(
            select(Nachricht.thread_key)
            .where(
                Nachricht.benutzer_id == konto.benutzer_id,
                Nachricht.message_id.in_(kette) | Nachricht.thread_key.in_(kette),
            )
            .limit(1)
        ).scalar()
        if treffer:
            return treffer
        return kette[0]

    if betreff_kern and beteiligte and datum is not None:
        grenze = datum - FENSTER
        if grenze.tzinfo is None:
            grenze = grenze.replace(tzinfo=timezone.utc)
        # ⚠️ **Nur im selben Postfach.** Zwei Konten koennen dieselbe
        # „Rechnung" bekommen, und die haben nichts miteinander zu tun.
        kandidaten = db.execute(
            select(Nachricht)
            .where(
                Nachricht.benutzer_id == konto.benutzer_id,
                Nachricht.konto_id == konto.id,
                Nachricht.betreff_kern == betreff_kern,
                Nachricht.datum >= grenze,
            )
            .order_by(Nachricht.datum.desc())
            .limit(20)
        ).scalars().all()
        for k in kandidaten:
            # ⚠️ **Gemeinsame Beteiligte sind die dritte Bedingung.** Ohne sie
            # landen „Rechnung" von drei Absendern in einem Strang — genau der
            # Fall, an dem eine Gruppierung kippt.
            if _beteiligte(k) & beteiligte:
                return k.thread_key
    return message_id or ""


#: Wie viele Zeilen auf einmal gelesen bzw. geschrieben werden.
#:
#: ⚠️ **Nicht groesser waehlen, um „schneller" zu sein.** Der Block ist die
#: Obergrenze fuer den Arbeitsspeicher, und genau darum geht es hier.
BLOCK = 2_000


def neu_aufbauen(db: Session, benutzer_id: str) -> int:
    """Alle Strangschluessel eines Benutzers neu bestimmen.

    ⚠️ **Noetig, weil der alte Schluessel Straenge zerriss** (siehe oben). Ohne
    das zeigte die neue Ansicht bei bestehender Post lauter Einzelstuecke und
    saehe aus, als taete sie nichts.

    Aeltestes zuerst: Der Strang entsteht an seiner Wurzel, und jede Antwort
    haengt sich an das, was schon da ist.

    ⚠️ **Vier Spalten, keine ORM-Objekte.** Bis zum 04.09.2026 stand hier
    ``select(Nachricht) … .all()``: Bei 250.000 Nachrichten landete der ganze
    Bestand als Objekte in einer Sitzung — gemessen 26,2 s und 1.074 MB, und
    das im Lebenslauf, also **bevor** der Server antwortet.

    ⚠️ **Und das ist mehr als Langsamkeit.** Auf einem NAS mit knappem
    Arbeitsspeicher raeumt der Kernel den Container dabei ab. Die Marke
    ``straenge_aufgebaut`` wird dann nie geschrieben, der naechste Start
    versucht es wieder — nexmail kaeme gar nicht mehr hoch, und im Protokoll
    stuende nichts, was darauf zeigt.

    ⚠️ **Geschrieben wird ERST NACH dem Lesen.** Waehrend ein Cursor ueber
    dieselbe Tabelle laeuft, in sie hineinzuschreiben ist der klassische
    Griff ins eigene Knie; SQLite verzeiht es nicht zuverlaessig.

    ⚠️ **Zwei Zeilen hier lassen sich nicht gegen eine Mutation pruefen**, und
    das gehoert dazugesagt: ``order_by(datum)`` und ``bekannt[neuer] = neuer``.
    Beide fallen in keinem Test auf, wenn man sie entfernt — die erste, weil
    SQLite ueber ``ix_nachricht_zeitachse`` ohnehin nach Datum liefert, die
    zweite, weil ``bekannt[message_id]`` daneben denselben Eintrag setzt. Sie
    bleiben trotzdem stehen: Die eine sagt, worauf sich der Aufbau verlaesst,
    die andere kostet nichts. Wer sie streicht, weil „kein Test dagegen
    steht", hat den Satz hier nicht gelesen.
    """
    #: Kennung → Strang, waehrend des Aufbaus. Schneller als je Zeile zu fragen.
    bekannt: dict[str, str] = {}
    zu_setzen: list[dict[str, object]] = []

    zeilen = db.execute(
        select(
            Nachricht.id,
            Nachricht.message_id,
            Nachricht.referenzen,
            Nachricht.thread_key,
        )
        .where(Nachricht.benutzer_id == benutzer_id)
        .order_by(Nachricht.datum, Nachricht.id)
        .execution_options(yield_per=BLOCK)
    )

    for kennung, message_id, referenzen, alter_strang in zeilen:
        kette = [k for k in (referenzen or "").split() if k]
        neuer = ""
        for k in kette:
            if k in bekannt:
                neuer = bekannt[k]
                break
        if not neuer and kette:
            neuer = kette[0]
        if not neuer:
            neuer = message_id or alter_strang or f"zeile:{kennung}"

        if alter_strang != neuer:
            zu_setzen.append({"id": kennung, "thread_key": neuer})
        if message_id:
            bekannt[message_id] = neuer
        bekannt[neuer] = neuer

    # ⚠️ **Ein Schreibvorgang je Block, nicht je Zeile.** Die Form
    # ``execute(update(Modell), [{"id": …, …}, …])`` ist SQLAlchemys
    # Blockschreiben ueber den Primaerschluessel; der Schluessel muss deshalb
    # ``id`` heissen, ein eigener Name wird abgewiesen.
    geaendert = len(zu_setzen)
    for anfang in range(0, geaendert, BLOCK):
        db.execute(update(Nachricht), zu_setzen[anfang : anfang + BLOCK])
    db.commit()
    logger.info("Thread keys rebuilt: %s message(s) changed.", geaendert)
    return geaendert
