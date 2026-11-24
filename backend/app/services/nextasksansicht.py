"""nextasks in nexmails Aufgabenansicht (MAIL-2): live lesen, nie kopieren.

Wie nextime bei den Kalendern (MAIL-1): nexmail holt Bereiche, Listen und
Aufgaben bei jedem Blick aus nextasks und speichert davon nichts, ausser was
nexmail selbst entscheidet, die **abgewaehlten** Listen
(``Aufgabenverbindung.ohne``).

⚠️ **Eine Verbindung zaehlt, die zuerst angelegte** (AC-18). Konten aus der
Zeit vor MAIL-2 koennen mehrere haben; die weiteren stehen in ``lage`` als
``weitere`` und werden hier nie gefragt.

⚠️ **Abgewaehlte Listen erscheinen nirgends** (AC-9): nicht in den Listen
(ausser mit ``alle``), nicht unter den Aufgaben, nicht in der Suche, nicht
als Ziel beim Anlegen. Gespeichert sind die Abgewaehlten, nicht die
Gewaehlten, damit eine in nextasks neu angelegte Liste von selbst dabei ist.

⚠️ **Hinaus geht nur, was sich geaendert hat** (AC-4): ``aendern`` bekommt
nur die Felder, die die Oberflaeche wirklich geschickt hat. nextasks entscheidet
je Feld, die spaetere Aenderung gewinnt (EC-4); ein mitgeschicktes, unveraendertes
Feld haette eine Aenderung von nebenan still zurueckgedreht.

⚠️ **Kein Rumpf einer Antwort ins Protokoll** (``nextasks.py``), und der
Token nie.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..meldung import Meldung
from ..models import Aufgabe, Aufgabenverbindung, Benutzer
from . import aufgaben, aufgabenziele, nextasks

logger = logging.getLogger("nexmail.nextasksansicht")

#: Die Sammlungen der Seitenleiste (AC-12) und wie nextasks sie filtert.
SAMMLUNGEN = ("offen", "heute", "datum", "erledigt", "markiert", "mir")

#: Kennungen von nextasks sind UUIDs. ⚠️ **Nichts anderes in einen Pfad**:
#: ``tasks/../me`` erreichte sonst eine andere Adresse mit demselben Token.
_KENNUNG = re.compile(r"^[0-9A-Za-z-]{1,64}$")
_UHRZEIT = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

#: Was der Mensch an der Verbindung beheben muss; steht danach an ihr (EC-2).
ZUGANGSFEHLER = (
    "nextasks_zugang_ungueltig",
    "nextasks_api_aus",
    "nextasks_nur_lesen",
    "nextasks_zu_alt",
    "nextasks_zugang_kaputt",
)


class AnsichtFehler(Meldung):
    """Mit einer Kennung, die man zeigen kann."""


# --- Verbindung ------------------------------------------------------------------ #


def verbindungen(db: Session, person: Benutzer) -> list[Aufgabenverbindung]:
    """Alle nextasks-Verbindungen, die zuerst angelegte vorn."""
    return [v for v in aufgabenziele.verbindungen(db, person) if v.art == "nextasks"]


def verbindung(db: Session, person: Benutzer) -> Aufgabenverbindung | None:
    alle = verbindungen(db, person)
    return alle[0] if alle else None


def gebraucht(db: Session, person: Benutzer) -> tuple[Aufgabenverbindung, nextasks.Zugang]:
    v = verbindung(db, person)
    if v is None:
        raise AnsichtFehler("nextasks_nicht_verbunden")
    return v, aufgabenziele._nextasks_zugang(v)  # noqa: SLF001 - derselbe Dienstkreis


def fehler_merken(db: Session, person: Benutzer, fehler: Meldung) -> None:
    """Ein abgelehnter Zugang steht danach an der Verbindung, wie beim Abgleich."""
    if fehler.kennung not in ZUGANGSFEHLER:
        return
    v = verbindung(db, person)
    if v is not None:
        v.letzter_fehler = fehler.kennung[:80]
        db.commit()


def _kennung(wert: str | None, fehler: str = "nextasks_nicht_gefunden") -> str:
    if not isinstance(wert, str) or not _KENNUNG.match(wert):
        raise AnsichtFehler(fehler)
    return wert


def _ohne(v: Aufgabenverbindung) -> set[str]:
    return aufgabenziele.nextasks_abgewaehlt(v)


def auswahl_setzen(db: Session, person: Benutzer, liste_id: str, gewaehlt: bool) -> None:
    """⚠️ **Nur in nexmail** (AC-9). Ob es die Liste gibt, wird nicht gefragt:
    Eine Liste, die es nicht mehr gibt, stoert in der Menge niemanden."""
    v, _ = gebraucht(db, person)
    liste_id = _kennung(liste_id, "nextasks_liste_unbekannt")
    ohne = _ohne(v)
    if gewaehlt:
        ohne.discard(liste_id)
    else:
        ohne.add(liste_id)
    v.ohne = json.dumps(sorted(ohne))
    db.commit()


# --- Lage ------------------------------------------------------------------------ #


@dataclass
class Weitere:
    id: str
    name: str
    adresse: str


@dataclass
class Lage:
    verbunden: bool
    verbindung_id: str = ""
    name: str = ""
    mitglieder: bool = False
    fehler: str = ""
    zeitzone: str = ""
    weitere: list[Weitere] = field(default_factory=list)


def lage(db: Session, person: Benutzer) -> Lage:
    """Verbunden, mit welchem Konto, und was nextasks kann.

    ⚠️ **Ein nextasks, das gerade klemmt, ist trotzdem verbunden** (EC-1): Die
    Lage sagt es in ``fehler``, statt zu scheitern; die eigenen Aufgaben laden
    davon unberuehrt.
    """
    alle = verbindungen(db, person)
    if not alle:
        return Lage(verbunden=False)
    v = alle[0]
    weitere = []
    for w in alle[1:]:
        try:
            adresse = aufgabenziele._nextasks_zugang(w).url  # noqa: SLF001
        except Meldung:
            adresse = ""
        weitere.append(Weitere(id=w.id, name=w.name, adresse=adresse))
    heraus = Lage(verbunden=True, verbindung_id=v.id, name=v.name, weitere=weitere)
    try:
        ich = nextasks.ich(aufgabenziele._nextasks_zugang(v))  # noqa: SLF001
    except Meldung as fehler:
        heraus.fehler = fehler.kennung
        fehler_merken(db, person, fehler)
        return heraus
    merkmale = ich.get("features")
    merkmale = merkmale if isinstance(merkmale, list) else []
    heraus.mitglieder = nextasks.MITGLIEDER in merkmale
    heraus.zeitzone = ich.get("time_zone") if isinstance(ich.get("time_zone"), str) else ""
    if not heraus.name:
        heraus.name = str(ich.get("display_name") or ich.get("name") or "")
    if v.letzter_fehler in ZUGANGSFEHLER:
        # Der Zugang geht wieder; ein Fehler aus dem Abgleich bleibt stehen.
        v.letzter_fehler = ""
        db.commit()
    return heraus


# --- Listen ---------------------------------------------------------------------- #


@dataclass
class Abschnitt:
    id: str
    name: str


@dataclass
class Liste:
    id: str
    name: str
    farbe: str
    symbol: str
    beschreibbar: bool
    offen: int
    gewaehlt: bool
    abschnitte: list[Abschnitt]
    bereich_id: str = ""
    bereich_name: str = ""


@dataclass
class Bereich:
    id: str
    name: str
    symbol: str
    ausgeblendet: bool
    beschreibbar: bool
    geteilt: bool
    listen: list[Liste] = field(default_factory=list)


def _text(wert: object) -> str:
    return wert if isinstance(wert, str) else ""


def _liste(z: dict, ohne: set[str]) -> Liste:
    abschnitte = [
        Abschnitt(id=s["id"], name=_text(s.get("name")))
        for s in z.get("sections") or []
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]
    ]
    offen = z.get("open")
    return Liste(
        id=z["id"],
        name=_text(z.get("name")),
        farbe=_text(z.get("color")),
        symbol=_text(z.get("icon")),
        beschreibbar=z.get("writable") is True,
        offen=offen if isinstance(offen, int) and not isinstance(offen, bool) else 0,
        gewaehlt=z["id"] not in ohne,
        abschnitte=abschnitte,
        bereich_id=_text(z.get("space_id")),
        bereich_name=_text(z.get("space_name")),
    )


def _listen_index(zugang: nextasks.Zugang, ohne: set[str]) -> dict[str, Liste]:
    """Jede Liste, die der Token sieht, nach Kennung (auch abgewaehlte)."""
    return {z["id"]: _liste(z, ohne) for z in nextasks.alle_listen(zugang)}


def listen(db: Session, person: Benutzer, *, alle: bool = False) -> list[Bereich]:
    """Bereiche mit ihren Listen (AC-1, AC-9).

    ⚠️ **Reihenfolge wie nextasks' Oberflaeche:** ``/lists`` liefert sie so,
    die Bereiche stehen in der Reihenfolge ihrer ersten Liste. ``/spaces`` ist
    nach Namen sortiert und gibt nur die Merkmale (Symbol, geteilt, …) und die
    Bereiche ohne Liste, die dahinter kommen. Ausgeblendete ans Ende, stabil.
    """
    v, zugang = gebraucht(db, person)
    ohne = _ohne(v)
    roh_bereiche = {b["id"]: b for b in nextasks.bereiche(zugang) if isinstance(b.get("id"), str)}
    heraus: dict[str, Bereich] = {}

    def bereich_fuer(kennung: str, ersatzname: str) -> Bereich:
        if kennung not in heraus:
            b = roh_bereiche.get(kennung, {})
            heraus[kennung] = Bereich(
                id=kennung,
                name=_text(b.get("name")) or ersatzname,
                symbol=_text(b.get("icon")),
                ausgeblendet=b.get("hidden") is True,
                beschreibbar=b.get("writable") is True,
                geteilt=b.get("shared") is True,
            )
        return heraus[kennung]

    for z in nextasks.alle_listen(zugang):
        liste = _liste(z, ohne)
        if not liste.gewaehlt and not alle:
            continue
        b = bereich_fuer(liste.bereich_id, liste.bereich_name)
        if z.get("hidden") is True:
            b.ausgeblendet = True
        b.listen.append(liste)
    if alle:
        for kennung, b in roh_bereiche.items():
            bereich_fuer(kennung, _text(b.get("name")))
    return sorted(heraus.values(), key=lambda b: b.ausgeblendet)


# --- Aufgaben -------------------------------------------------------------------- #


@dataclass
class Person:
    id: int
    name: str


@dataclass
class Mailbezug:
    aufgabe_id: int
    nachricht_id: int | None
    konto_id: str
    betreff: str
    von_name: str
    von_adresse: str
    verwaist: bool


@dataclass
class Fernaufgabe:
    id: str
    liste_id: str
    liste_name: str
    bereich_id: str
    bereich_name: str
    abschnitt_id: str | None
    abschnitt_name: str
    eltern_id: str | None
    titel: str
    notiz: str
    notiz_text: str
    url: str | None
    faellig_tag: str | None
    faellig_zeit: str | None
    wiederholung: str | None
    markiert: bool
    prioritaet: int
    schlagworte: list[str]
    zustaendige: list[Person]
    erledigt: bool
    erledigt_am: str | None
    papierkorb: bool
    teilaufgaben: dict[str, int]
    link: str
    beschreibbar: bool
    mail: Mailbezug | None = None
    teilaufgaben_liste: list["Fernaufgabe"] | None = None


def _zahl(wert: object) -> int:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) else 0


def _oder_none(wert: object) -> str | None:
    return wert if isinstance(wert, str) and wert else None


def _person(z: object) -> Person | None:
    """⚠️ **Ein ehemaliges Mitglied hat keinen Namen** (EC-12): nextasks
    liefert ``name`` und ``display_name`` dann als null; der Name bleibt leer,
    die Oberflaeche sagt „ehemaliges Mitglied"."""
    if not isinstance(z, dict) or not isinstance(z.get("id"), int):
        return None
    return Person(id=z["id"], name=_text(z.get("display_name")) or _text(z.get("name")))


def _mails(db: Session, person: Benutzer, ids: list[str]) -> dict[str, Mailbezug]:
    """Die Aufgaben-Zeilen hier zu diesen Fernaufgaben (AC-8)."""
    if not ids:
        return {}
    zeilen = db.scalars(
        select(Aufgabe).where(
            Aufgabe.benutzer_id == person.id,
            Aufgabe.fern_art == "nextasks",
            Aufgabe.fern_id.in_(ids),
        )
    ).all()
    heraus: dict[str, Mailbezug] = {}
    for a in zeilen:
        mail = aufgaben._wiederfinden(db, person, a)  # noqa: SLF001 - derselbe Weg wie die Liste
        heraus[a.fern_id] = Mailbezug(
            aufgabe_id=a.id,
            nachricht_id=mail.id if mail else None,
            konto_id=a.konto_id,
            betreff=a.betreff,
            von_name=a.von_name,
            von_adresse=a.von_adresse,
            verwaist=mail is None,
        )
    return heraus


def _fern(z: dict, index: dict[str, Liste], mails: dict[str, Mailbezug]) -> Fernaufgabe:
    liste = index.get(_text(z.get("list_id")))
    abschnitt_id = _oder_none(z.get("section_id"))
    abschnitt_name = ""
    if liste is not None and abschnitt_id:
        abschnitt_name = next((s.name for s in liste.abschnitte if s.id == abschnitt_id), "")
    teil = z.get("subtasks") if isinstance(z.get("subtasks"), dict) else {}
    schlagworte = z.get("tags") if isinstance(z.get("tags"), list) else []
    personen = z.get("assignees") if isinstance(z.get("assignees"), list) else []
    url = nextasks._link(z.get("url")) or None  # noqa: SLF001 - nur http(s), EC-8
    return Fernaufgabe(
        id=z["id"],
        liste_id=_text(z.get("list_id")),
        liste_name=liste.name if liste else "",
        bereich_id=liste.bereich_id if liste else "",
        bereich_name=liste.bereich_name if liste else "",
        abschnitt_id=abschnitt_id,
        abschnitt_name=abschnitt_name,
        eltern_id=_oder_none(z.get("parent_id")),
        titel=_text(z.get("title")),
        notiz=_text(z.get("notes")),
        notiz_text=_text(z.get("notes_text")),
        url=url,
        faellig_tag=_oder_none(z.get("due_date")),
        faellig_zeit=_oder_none(z.get("due_time")),
        wiederholung=_oder_none(z.get("repeat")),
        markiert=z.get("flagged") is True,
        prioritaet=_zahl(z.get("priority")),
        schlagworte=[s for s in schlagworte if isinstance(s, str)],
        zustaendige=[p for p in (_person(x) for x in personen) if p is not None],
        erledigt=z.get("completed") is True,
        erledigt_am=_oder_none(z.get("completed_at")),
        papierkorb=z.get("trashed") is True,
        teilaufgaben={"offen": _zahl(teil.get("open")), "gesamt": _zahl(teil.get("total"))},
        link=nextasks._link(z.get("link")),  # noqa: SLF001
        beschreibbar=bool(liste and liste.beschreibbar),
        mail=mails.get(z["id"]),
    )


def _zeitzone(zugang: nextasks.Zugang) -> ZoneInfo:
    name = nextasks.ich(zugang).get("time_zone")
    try:
        return ZoneInfo(name if isinstance(name, str) and name else "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _filter(sammlung: str, zugang: nextasks.Zugang) -> dict[str, str]:
    """Was nextasks je Sammlung bekommt.

    ⚠️ **„Heute" im Tag des nextasks-Kontos** (EC-16): ``due_before`` ist
    morgen dort, nicht hier. ⚠️ **„Mit Datum"** kennt nextasks nicht als
    Filter; ``due_after`` vor jedem denkbaren Tag nimmt genau die mit Datum
    (nextasks vergleicht nur Aufgaben, die eines haben).
    """
    if sammlung == "erledigt":
        return {"state": "completed"}
    params = {"state": "open"}
    if sammlung == "heute":
        morgen = datetime.now(_zeitzone(zugang)).date() + timedelta(days=1)
        params["due_before"] = morgen.isoformat()
    elif sammlung == "datum":
        params["due_after"] = "1900-01-01"
    elif sammlung == "markiert":
        params["flagged"] = "true"
    elif sammlung == "mir":
        params["assigned"] = "me"
    return params


@dataclass
class Seite:
    aufgaben: list[Fernaufgabe]
    weiter: str | None


def aufgaben_lesen(
    db: Session,
    person: Benutzer,
    *,
    liste: str | None = None,
    sammlung: str | None = None,
    suche: str = "",
    cursor: str = "",
) -> Seite:
    """Eine Seite Aufgaben aus den gewaehlten Listen (AC-2, AC-11, AC-12).

    ⚠️ **Nur oberste Aufgaben**; Teilaufgaben stehen im Einzelabruf.

    ⚠️ **Die Suche kann nextasks nicht**: nexmail holt die Seiten (bis
    ``MAX_SEITEN``) und filtert auf Titel und Notiz, ohne Gross und klein. Dann
    gibt es keinen Cursor.
    """
    sammlung = sammlung or "offen"
    if sammlung not in SAMMLUNGEN:
        raise AnsichtFehler("nextasks_sammlung_unbekannt")
    v, zugang = gebraucht(db, person)
    ohne = _ohne(v)
    index = _listen_index(zugang, ohne)
    params = _filter(sammlung, zugang)
    params["limit"] = str(nextasks.SEITE)
    if liste:
        liste = _kennung(liste, "nextasks_liste_unbekannt")
        if liste not in index or liste in ohne:
            raise AnsichtFehler("nextasks_liste_unbekannt")
        params["list_id"] = liste

    def passt(z: dict) -> bool:
        if _text(z.get("list_id")) in ohne or z.get("parent_id"):
            return False
        if sammlung == "datum" and not z.get("due_date"):
            return False
        return True

    gesammelt: list[dict] = []
    weiter = cursor.strip()
    muster = " ".join(suche.split()).casefold()
    # ⚠️ Ein Deckel wie ueberall: Ein Cursor, der nie leer wird, liefe sonst ewig.
    for _ in range(nextasks.MAX_SEITEN):
        if weiter:
            params["cursor"] = weiter
        zeilen, weiter = nextasks.aufgaben_seite(zugang, params)
        for z in zeilen:
            if not passt(z):
                continue
            if muster and muster not in (
                _text(z.get("title")).casefold() + "\n" + _text(z.get("notes_text")).casefold()
            ):
                continue
            gesammelt.append(z)
        if not weiter:
            break
        # Ohne Suche reicht eine Seite, sobald sie etwas traegt; eine Seite, die
        # nur Abgewaehltes hatte, wird uebersprungen statt leer gezeigt.
        if not muster and gesammelt:
            break
    mails = _mails(db, person, [z["id"] for z in gesammelt])
    return Seite(
        aufgaben=[_fern(z, index, mails) for z in gesammelt],
        weiter=(weiter or None) if not muster else None,
    )


def aufgabe_lesen(db: Session, person: Benutzer, fern_id: str) -> Fernaufgabe:
    """Eine Aufgabe samt Teilaufgaben (AC-4). Eine Aufgabe aus einer
    abgewaehlten Liste gibt es hier nicht (AC-9)."""
    v, zugang = gebraucht(db, person)
    fern_id = _kennung(fern_id)
    ohne = _ohne(v)
    z = nextasks.aufgabe_lesen(zugang, fern_id)
    if _text(z.get("list_id")) in ohne:
        raise AnsichtFehler("nextasks_nicht_gefunden")
    index = _listen_index(zugang, ohne)
    teile = z.get("subtasks") if isinstance(z.get("subtasks"), dict) else {}
    items = [t for t in teile.get("items") or [] if isinstance(t, dict) and isinstance(t.get("id"), str)]
    mails = _mails(db, person, [fern_id, *(t["id"] for t in items)])
    heraus = _fern(z, index, mails)
    heraus.teilaufgaben_liste = [_fern(t, index, mails) for t in items]
    return heraus


# --- Schreiben ------------------------------------------------------------------- #


def _uhrzeit(wert: str | None) -> str | None:
    if wert is None:
        return None
    if not _UHRZEIT.match(wert):
        raise AnsichtFehler("nextasks_eingabe_ungueltig")
    return wert


def _gewaehlte_liste(zugang: nextasks.Zugang, v: Aufgabenverbindung, liste_id: str | None) -> Liste:
    """⚠️ **Abgewaehlt oder unbekannt ist dasselbe** (AC-9): 404."""
    liste_id = _kennung(liste_id, "nextasks_liste_unbekannt")
    ohne = _ohne(v)
    index = _listen_index(zugang, ohne)
    liste = index.get(liste_id)
    if liste is None or not liste.gewaehlt:
        raise AnsichtFehler("nextasks_liste_unbekannt")
    return liste


def anlegen(
    db: Session,
    person: Benutzer,
    *,
    liste_id: str,
    titel: str,
    abschnitt_id: str | None = None,
    eltern_id: str | None = None,
    notiz: str | None = None,
    faellig_tag: date | None = None,
    faellig_zeit: str | None = None,
    prioritaet: int | None = None,
    markiert: bool | None = None,
    zustaendige: list[int] | None = None,
    anfrage: str = "",
) -> Fernaufgabe:
    """Eine Aufgabe ohne Mail (AC-6), oder eine Teilaufgabe ueber ``eltern_id``.

    ``anfrage``: ein eigener Schluessel der Oberflaeche je Wunsch. Derselbe
    zweimal (Doppelklick, EC-10) gibt die Aufgabe vom ersten Mal, ueber
    nextasks' ``external_ref``.
    """
    v, zugang = gebraucht(db, person)
    titel = " ".join(titel.split())
    if not titel:
        raise AnsichtFehler("nextasks_eingabe_ungueltig")
    faellig_zeit = _uhrzeit(faellig_zeit)
    if faellig_zeit and faellig_tag is None:
        raise AnsichtFehler("nextasks_eingabe_ungueltig")
    liste = _gewaehlte_liste(zugang, v, liste_id)
    rumpf: dict = {"list_id": liste.id, "title": titel[:500]}
    if abschnitt_id:
        rumpf["section_id"] = _kennung(abschnitt_id, "nextasks_liste_unbekannt")
    if eltern_id:
        rumpf["parent_id"] = _kennung(eltern_id)
    if notiz:
        rumpf["notes"] = notiz[: nextasks.MAX_NOTIZ]
    if faellig_tag is not None:
        rumpf["due_date"] = faellig_tag.isoformat()
        if faellig_zeit:
            rumpf["due_time"] = faellig_zeit
    if prioritaet:
        rumpf["priority"] = prioritaet
    if markiert:
        rumpf["flagged"] = True
    if zustaendige:
        rumpf["assignees"] = list(zustaendige)
    if anfrage:
        rumpf["external_ref"] = f"nexmail:neu:{anfrage}"[: nextasks.MAX_SCHLUESSEL]
    z = nextasks.aufgabe_neu(zugang, rumpf)
    logger.info("A task was made in nextasks from the task view.")
    index = _listen_index(zugang, _ohne(v))
    return _fern(z, index, _mails(db, person, [z["id"]]))


#: Feldname hier → Feldname in nextasks. ⚠️ ``papierkorb`` nur ``false``.
FELDER = {
    "titel": "title",
    "notiz": "notes",
    "faellig_tag": "due_date",
    "faellig_zeit": "due_time",
    "prioritaet": "priority",
    "markiert": "flagged",
    "schlagworte": "tags",
    "zustaendige": "assignees",
    "liste_id": "list_id",
    "abschnitt_id": "section_id",
    "erledigt": "completed",
    "papierkorb": "trashed",
}
#: Was sich nicht leeren laesst: ``null`` dort ist eine kaputte Eingabe.
NICHT_LEERBAR = ("titel", "prioritaet", "markiert", "liste_id", "erledigt", "papierkorb")


def _zeile_nachziehen(db: Session, person: Benutzer, z: dict, index: dict[str, Liste]) -> None:
    """⚠️ **Der Abzug hier bleibt stimmig**: Gibt es eine Aufgabe-Zeile zu
    dieser Fernaufgabe (aus einer Mail), zieht sie Haken, Datum, Papierkorb
    und Liste gleich nach, statt bis zum naechsten Abgleich zu luegen."""
    for a in db.scalars(
        select(Aufgabe).where(
            Aufgabe.benutzer_id == person.id,
            Aufgabe.fern_art == "nextasks",
            Aufgabe.fern_id == z["id"],
        )
    ):
        stand = nextasks._stand(z)  # noqa: SLF001 - dieselbe Lesart wie der Abgleich
        a.fern_geloescht = stand.papierkorb
        if stand.erledigt is None:
            a.erledigt = None
        elif a.erledigt is None:
            a.erledigt = stand.erledigt
        a.faellig = aufgabenziele._als_zeitpunkt(stand.faellig)  # noqa: SLF001
        if stand.url:
            a.fern_url = stand.url
        liste = index.get(_text(z.get("list_id")))
        if liste is not None:
            a.fern_liste = " › ".join(t for t in (liste.bereich_name, liste.name) if t)[:200]
    db.commit()


def aendern(db: Session, person: Benutzer, fern_id: str, felder: dict) -> Fernaufgabe:
    """Nur die Felder in ``felder`` gehen hinaus (AC-4); ``None`` leert.

    ⚠️ **Eine neue Liste muss gewaehlt sein**, wie beim Anlegen.
    """
    v, zugang = gebraucht(db, person)
    fern_id = _kennung(fern_id)
    rumpf: dict = {}
    for name, wert in felder.items():
        if name not in FELDER:
            continue
        if wert is None and name in NICHT_LEERBAR:
            raise AnsichtFehler("nextasks_eingabe_ungueltig")
        if name == "papierkorb" and wert is not False:
            # Hinein geht es ueber DELETE; hier nur zurueck.
            raise AnsichtFehler("nextasks_eingabe_ungueltig")
        if name == "titel":
            wert = " ".join(str(wert).split())[:500]
            if not wert:
                raise AnsichtFehler("nextasks_eingabe_ungueltig")
        if name == "notiz" and wert is not None:
            wert = str(wert)[: nextasks.MAX_NOTIZ]
        if name == "faellig_tag" and isinstance(wert, date):
            wert = wert.isoformat()
        if name == "faellig_zeit":
            wert = _uhrzeit(wert)
        if name == "liste_id":
            wert = _gewaehlte_liste(zugang, v, wert).id
        if name == "abschnitt_id" and wert is not None:
            wert = _kennung(wert, "nextasks_liste_unbekannt")
        rumpf[FELDER[name]] = wert
    if not rumpf:
        z = nextasks.aufgabe_lesen(zugang, fern_id)
    else:
        z = nextasks.aufgabe_aendern(zugang, fern_id, rumpf)
    index = _listen_index(zugang, _ohne(v))
    _zeile_nachziehen(db, person, z, index)
    return _fern(z, index, _mails(db, person, [z["id"]]))


def loeschen(db: Session, person: Benutzer, fern_id: str) -> None:
    """In nextasks' Papierkorb (AC-5). Die Zeile hier sagt es (``fern_geloescht``)."""
    _v, zugang = gebraucht(db, person)
    fern_id = _kennung(fern_id)
    nextasks.aufgabe_loeschen(zugang, fern_id)
    for a in db.scalars(
        select(Aufgabe).where(
            Aufgabe.benutzer_id == person.id,
            Aufgabe.fern_art == "nextasks",
            Aufgabe.fern_id == fern_id,
        )
    ):
        a.fern_geloescht = True
    db.commit()
    logger.info("A task went to the nextasks trash from the task view.")


def mitglieder(db: Session, person: Benutzer, bereich_id: str) -> list[Person]:
    """Wer in diesem Bereich zustaendig sein kann.

    ⚠️ **Erst fragen, ob nextasks das kann** (EC-3): Ohne ``members`` in
    ``features`` fehlt nur die Wahl der Zustaendigen, nichts sonst.
    """
    _v, zugang = gebraucht(db, person)
    bereich_id = _kennung(bereich_id)
    merkmale = nextasks.ich(zugang).get("features")
    if not isinstance(merkmale, list) or nextasks.MITGLIEDER not in merkmale:
        raise AnsichtFehler("nextasks_ohne_mitglieder")
    return [p for p in (_person(z) for z in nextasks.mitglieder(zugang, bereich_id)) if p is not None]
