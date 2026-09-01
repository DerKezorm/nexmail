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

from sqlalchemy import select
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


def neu_aufbauen(db: Session, benutzer_id: str) -> int:
    """Alle Strangschluessel eines Benutzers neu bestimmen.

    ⚠️ **Noetig, weil der alte Schluessel Straenge zerriss** (siehe oben). Ohne
    das zeigte die neue Ansicht bei bestehender Post lauter Einzelstuecke und
    saehe aus, als taete sie nichts.

    Aeltestes zuerst: Der Strang entsteht an seiner Wurzel, und jede Antwort
    haengt sich an das, was schon da ist.
    """
    zeilen = db.execute(
        select(Nachricht)
        .where(Nachricht.benutzer_id == benutzer_id)
        .order_by(Nachricht.datum, Nachricht.id)
    ).scalars().all()

    #: Kennung → Strang, waehrend des Aufbaus. Schneller als je Zeile zu fragen.
    bekannt: dict[str, str] = {}
    geaendert = 0

    for n in zeilen:
        kette = [k for k in (n.referenzen or "").split() if k]
        neuer = ""
        for k in kette:
            if k in bekannt:
                neuer = bekannt[k]
                break
        if not neuer and kette:
            neuer = kette[0]
        if not neuer:
            neuer = n.message_id or n.thread_key or f"zeile:{n.id}"

        if n.thread_key != neuer:
            n.thread_key = neuer
            geaendert += 1
        if n.message_id:
            bekannt[n.message_id] = neuer
        bekannt[neuer] = neuer

    db.commit()
    logger.info("Thread keys rebuilt: %s message(s) changed.", geaendert)
    return geaendert
