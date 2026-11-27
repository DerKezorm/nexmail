"""Mails mit einer Person: nexfolks Karte „In den anderen Apps“ (verbinden 0.1.13, Zweck ``mails.about``, V49 bis V53).

nexfolk fragt mit dem Zugang der Verbindung ``GET /api/connect/about/mails.about?name=…&mail=…&phone=…``; das Modul
prüft Frage, Zweck und Bremse und ruft ``ueber_person``. Die Antwort ist klein: wie viele Mails, wann die letzte kam,
wohin „öffnen“ führt. Nie, was eine Mail sagt (das Modul wirft jeden Titel weg, ``titles=False``; hier steht ohnehin
keiner drin).

**Die Regel:** Gezählt wird jede Mail des Kontos in den Postfächern, die die Verbindung bekam, deren Absender, Empfänger
(An) oder Kopie (Cc) eine der Mailadressen der Person ist (ohne Groß/klein), außer in Papierkorb, Entwürfen und
Werbung; der Name allein zählt nicht (zu ungenau), dieselbe Mail in zwei Ordnern (Gmail: Posteingang und „Alle
Nachrichten“) einmal. Gelesen wird nur nexmails eigener Stand (``nachricht``), nie der Server des Postfachs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.sql.elements import ColumnElement

from ..models import Benutzer, Konto, Nachricht, Ordner

#: Ordner, deren Mails nicht „mit der Person“ sind: Weggeworfenes, nie Gesendetes, Werbung.
NICHT_GEZAEHLT = ("papierkorb", "entwuerfe", "junk")


def _in_liste(feld: Any, adressen: list[str]) -> ColumnElement[bool]:
    """Ob die Personenliste ``feld`` (JSON ``[{"n", "a"}]``, wie der Abgleich sie schreibt) eine der Adressen trägt.
    Erst ein billiger Blick in den Text, dann genau über ``json_each``; kaputtes JSON zählt als leer."""
    eintraege = func.json_each(case((func.json_valid(feld), feld), else_=literal("[]"))).table_valued("value")
    genau = (
        select(literal(1))
        .select_from(eintraege)
        .where(func.lower(func.json_extract(eintraege.c.value, "$.a")).in_(adressen))
        .exists()
    )
    grob = or_(*(func.instr(func.lower(feld), a) > 0 for a in adressen))
    return grob & genau


def mit_adresse(adressen: list[str]) -> ColumnElement[bool]:
    """Die Bedingung „Absender, An oder Cc ist eine dieser Adressen“ (klein geschrieben übergeben)."""
    return or_(
        func.lower(Nachricht.von_adresse).in_(adressen),
        _in_liste(Nachricht.an_json, adressen),
        _in_liste(Nachricht.kopie_json, adressen),
    )


def zaehlen(db: Any, benutzer_id: str, konto_ids: list[str] | None, adressen: list[str]) -> tuple[int, Any]:
    """Wie viele Mails mit einer der ``adressen`` in den Postfächern ``konto_ids`` (``None``: alle des Kontos), und das
    Datum der neuesten. Nur Postfächer, die dem Konto gehören."""
    adressen = sorted({a.strip().lower() for a in adressen if a and a.strip()})
    if not adressen:
        return 0, None
    eigene = select(Konto.id).where(Konto.benutzer_id == benutzer_id)
    if konto_ids is not None:
        eigene = eigene.where(Konto.id.in_([str(k) for k in konto_ids]))
    eine = case((Nachricht.message_id != "", Nachricht.message_id), else_=literal("#") + cast(Nachricht.id, String))
    frage = (
        select(func.count(func.distinct(eine)), func.max(Nachricht.datum))
        .join(Ordner, Ordner.id == Nachricht.ordner_id)
        .where(
            Nachricht.benutzer_id == benutzer_id,
            Nachricht.konto_id.in_(eigene),
            Ordner.rolle.not_in(NICHT_GEZAEHLT),
            mit_adresse(adressen),
        )
    )
    anzahl, neueste = db.execute(frage).one()
    return int(anzahl or 0), neueste


def ueber_person(store: Any, caller: Any, purpose: str, person: Any) -> dict[str, Any]:
    """Der Haken ``about`` des Moduls (``router(about=…)``) für ``mails.about``."""
    leer: dict[str, Any] = {"count": 0, "next": None, "last": None, "open": None}
    db = store.db
    benutzer = db.get(Benutzer, str(caller.account_id))
    if purpose != "mails.about" or benutzer is None or not person.mails:
        return leer
    anzahl, neueste = zaehlen(db, benutzer.id, caller.areas, list(person.mails))
    if not anzahl:
        return leer
    return {
        "count": anzahl,
        "next": None,
        # Nie der Betreff: nur, wann die letzte kam.
        "last": {"title": "", "at": neueste.isoformat()} if neueste is not None else None,
        # Die Suche nach der ersten Adresse (``App.tsx`` liest ``?suche=``); ein Pfad, die Adresse setzt das Modul davor.
        "open": "/?suche=" + quote(person.mails[0].lower(), safe="@"),
    }
