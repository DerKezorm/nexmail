"""Wer eine Aufgabe verwaltet: nexmail selbst oder eine verbundene Todo-App.

⚠️ **Eine Mail, eine Aufgabe — ueber alle Ziele hinweg.** Wer eine Mail
zweimal zur Aufgabe macht, bekommt die vorhandene zurueck, egal wo sie liegt.
Dieselbe Regel wie bei „Zu Aufgabe machen" seit jeher: Ein Doppel muesste man
zweimal abhaken, in zwei Programmen sogar.

⚠️ **Liegt die Aufgabe in einer Todo-App, gehoert ihr der Haken.** nexmail
merkt sich die Aufgabe trotzdem (an der Mail und in der Liste) und zieht im
Abgleich nach, was die App sagt: erledigt, wieder offen, geloescht, neues
Datum. Abhaken in nexmail geht zuerst zur App; was sie ablehnt, aendert hier
nichts.

⚠️ **Hinaus geht nur, was der Mensch im Fenster sieht:** Titel, Faelligkeit,
Absender und ein Link zurueck zur Mail. Der Text der Mail bleibt hier.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import crypto
from ..config import get_settings
from ..db import einstellung_lesen
from ..meldung import Meldung
from ..models import Aufgabe, Aufgabenverbindung, Benutzer, Nachricht, neue_id
from . import adresse as adressdienst
from . import aufgaben, todoist

logger = logging.getLogger("nexmail.aufgabenziele")

#: Die Arten, die es gibt. Weitere kommen als eigener Dienst dazu.
ARTEN = ("todoist",)

#: ⚠️ **Erledigte werden noch so lange nachgesehen**, damit ein Wieder-Oeffnen
#: in der App auch hier ankommt. Danach gilt der letzte Stand; sonst fragte
#: jeder Abgleich nach Jahren an Erledigtem.
NACHSEHEN_ERLEDIGTE = timedelta(days=30)

#: Ein Abgleich beim Oeffnen der Liste kommt hoechstens so oft. Der Takt
#: laeuft ohnehin; das hier ist nur der schnelle Blick dazwischen.
OEFFNEN_PAUSE = 15.0
_zuletzt_beim_oeffnen: dict[str, float] = {}


class ZielFehler(Meldung):
    """Mit einer Kennung, die man zeigen kann."""


@dataclass
class Liste:
    #: ``<verbindung>:<liste>``, so wie es beim Anlegen zurueckkommt.
    ziel: str
    name: str


@dataclass
class Gruppe:
    verbindung_id: str
    art: str
    name: str
    #: Leer, wenn die Listen kamen. Sonst die Kennung, warum nicht.
    fehler: str = ""
    listen: list[Liste] = field(default_factory=list)


def _kontext(verbindung_id: str) -> str:
    return f"aufgabenverbindung:{verbindung_id}:zugang"


def _zugang(v: Aufgabenverbindung) -> str:
    return crypto.entschluesseln(v.zugang, _kontext(v.id))


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _fehler_merken(v: Aufgabenverbindung, fehler: todoist.TodoistFehler) -> None:
    v.letzter_fehler = fehler.kennung[:80]


# --- Verbindungen ---------------------------------------------------------- #


def verbindungen(db: Session, person: Benutzer) -> list[Aufgabenverbindung]:
    return list(
        db.scalars(
            select(Aufgabenverbindung)
            .where(Aufgabenverbindung.benutzer_id == person.id)
            .order_by(Aufgabenverbindung.angelegt, Aufgabenverbindung.id)
        )
    )


def eine_verbindung(db: Session, person: Benutzer, verbindung_id: str) -> Aufgabenverbindung:
    v = db.get(Aufgabenverbindung, verbindung_id)
    if v is None or v.benutzer_id != person.id:
        raise ZielFehler("aufgabenverbindung_unbekannt")
    return v


def verbinden(db: Session, person: Benutzer, art: str, zugang: str, name: str = "") -> Aufgabenverbindung:
    """Eine Todo-App verbinden — erst pruefen, dann speichern.

    ⚠️ **Ein Token, den die App ablehnt, wird nie gespeichert.** Sonst stuende
    eine Verbindung da, die beim ersten Handgriff scheitert, und der Fehler
    zeigte sich weit weg von der Stelle, an der er entstand.
    """
    if art not in ARTEN:
        raise ZielFehler("aufgabenart_unbekannt")
    zugang = zugang.strip()
    todoist.listen(zugang)

    v = Aufgabenverbindung(id=neue_id(), benutzer_id=person.id, art=art, name=name.strip()[:80])
    v.zugang = crypto.verschluesseln(zugang, _kontext(v.id))
    db.add(v)
    db.commit()
    logger.info("A to-do app was connected (%s).", art)
    return v


def trennen(db: Session, person: Benutzer, verbindung_id: str) -> None:
    """Die Verbindung loesen. ⚠️ **In der App bleibt alles, wie es ist.**

    Die Aufgaben hier behalten Abzug und Link, nur abgeglichen wird nicht
    mehr. Zeigt der Standard auf diese Verbindung, gilt wieder die eigene
    Liste.
    """
    v = eine_verbindung(db, person, verbindung_id)
    for a in db.scalars(select(Aufgabe).where(Aufgabe.verbindung_id == v.id)):
        a.verbindung_id = None
    if person.aufgaben_standard.split(":", 1)[0] == v.id:
        person.aufgaben_standard = ""
    db.delete(v)
    db.commit()
    logger.info("A to-do app was disconnected.")


# --- Ziele ----------------------------------------------------------------- #


def ziele(db: Session, person: Benutzer) -> list[Gruppe]:
    """Je Verbindung ihre Listen, live geholt.

    ⚠️ **Eine Verbindung, die klemmt, nimmt die anderen nicht mit.** Sie steht
    mit ihrer Kennung da und ohne Listen; die eigene Liste und die anderen Apps
    bleiben waehlbar.
    """
    heraus: list[Gruppe] = []
    for v in verbindungen(db, person):
        gruppe = Gruppe(verbindung_id=v.id, art=v.art, name=v.name)
        try:
            gruppe.listen = [
                Liste(ziel=f"{v.id}:{l.id}", name=l.name) for l in todoist.listen(_zugang(v))
            ]
            v.letzter_fehler = ""
        except todoist.TodoistFehler as fehler:
            gruppe.fehler = fehler.kennung
            _fehler_merken(v, fehler)
        heraus.append(gruppe)
    db.commit()
    return heraus


def _zerlegen(db: Session, person: Benutzer, ziel: str) -> tuple[Aufgabenverbindung, str]:
    verbindung_id, _, liste_id = ziel.partition(":")
    if not verbindung_id or not liste_id:
        raise ZielFehler("aufgabenziel_unbekannt")
    return eine_verbindung(db, person, verbindung_id), liste_id


def standard_von(db: Session, person: Benutzer) -> str:
    ziel = person.aufgaben_standard or ""
    if not ziel:
        return ""
    v = db.get(Aufgabenverbindung, ziel.split(":", 1)[0])
    return ziel if v is not None and v.benutzer_id == person.id else ""


def standard_setzen(db: Session, person: Benutzer, ziel: str) -> str:
    """⚠️ Die Liste selbst wird nicht live geprueft: Das kostete eine Anfrage
    bei der App fuer eine Wahl, die eben aus deren Liste kam. Verschwindet sie
    dort, sagt es der erste Handgriff."""
    ziel = ziel.strip()
    if ziel:
        _zerlegen(db, person, ziel)
    person.aufgaben_standard = ziel
    db.commit()
    return ziel


# --- Anlegen ----------------------------------------------------------------- #


def mail_link(db: Session, message_id: str, vom_browser: str = "") -> str:
    """Der Weg zurueck zur Mail, oder leer.

    ⚠️ **Ueber die ``Message-ID``, nie ueber die Zeilennummer.** Die Zeile
    wechselt, sobald die Mail vom Telefon aus in einen anderen Ordner wandert;
    ein Link, der monatelang in einer Todo-App steht, fuehrte dann ins Leere.

    ⚠️ **Die oeffentliche Adresse geht vor**, wie beim QR-Code der App: Wer
    nexmail zu Hause ueber eine IP aufruft, will in Todoist trotzdem den Link,
    der auch unterwegs geht.
    """
    if not message_id:
        return ""
    eingestellt = adressdienst.fuer_modul(
        einstellung_lesen(db, "oeffentliche_adresse"), get_settings().url_base
    )
    for kandidat in (eingestellt, vom_browser.strip().rstrip("/")):
        teile = urlsplit(kandidat)
        if teile.scheme in ("http", "https") and teile.netloc:
            return f"{kandidat}/?mail={quote(message_id, safe='')}"
    return ""


def _beschreibung(nachricht: Nachricht, link: str) -> str:
    """⚠️ **Ohne Worte in einer Sprache.** Der Text steht in Todoist, das in
    jeder Sprache laufen kann; „Absender:" waere fuer die Haelfte falsch."""
    zeilen = []
    if nachricht.von_name and nachricht.von_adresse:
        zeilen.append(f"{nachricht.von_name} <{nachricht.von_adresse}>")
    elif nachricht.von_adresse or nachricht.von_name:
        zeilen.append(nachricht.von_adresse or nachricht.von_name)
    if link:
        zeilen.append(f"[nexmail ↗]({link})")
    elif nachricht.message_id:
        zeilen.append(f"Message-ID: {nachricht.message_id}")
    return "\n".join(zeilen)


def _vorhanden(db: Session, person: Benutzer, nachricht: Nachricht) -> Aufgabe | None:
    if not nachricht.message_id:
        return None
    return db.scalars(
        select(Aufgabe).where(
            Aufgabe.benutzer_id == person.id, Aufgabe.message_id == nachricht.message_id
        )
    ).first()


def _als_zeitpunkt(tag: date | None) -> datetime | None:
    # Dieselbe Form, in der die Oberflaeche ein Datum schickt: Mitternacht UTC.
    return datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc) if tag else None


def anlegen(
    db: Session,
    person: Benutzer,
    nachricht_id: int,
    *,
    ziel: str,
    titel: str = "",
    liste_name: str = "",
    faellig: date | None = None,
    vom_browser: str = "",
) -> tuple[Aufgabe, bool]:
    """Eine Aufgabe aus einer Mail, dort, wo der Mensch sie haben will.

    Gibt die Aufgabe zurueck und ob sie neu ist. ⚠️ **Gibt es zu dieser Mail
    schon eine, kommt die zurueck** — auch wenn sie woanders liegt als das
    gewaehlte Ziel. Kein Fehler, kein Doppel.
    """
    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != person.id:
        raise aufgaben.AufgabenFehler("nachricht_unbekannt")

    schon = _vorhanden(db, person, nachricht)
    if schon is not None:
        return schon, False

    titel = " ".join(titel.split())[:500] or nachricht.betreff or ""

    if not ziel:
        aufgabe = aufgaben.anlegen(db, person, nachricht_id)
        aufgabe.betreff = titel
        aufgabe.faellig = _als_zeitpunkt(faellig)
        db.commit()
        return aufgabe, True

    v, liste_id = _zerlegen(db, person, ziel)
    try:
        stand = todoist.anlegen(
            _zugang(v),
            titel=titel or "(no subject)",
            beschreibung=_beschreibung(nachricht, mail_link(db, nachricht.message_id, vom_browser)),
            liste_id=liste_id,
            faellig=faellig,
        )
    except todoist.TodoistFehler as fehler:
        _fehler_merken(v, fehler)
        db.commit()
        raise

    kleinste = db.scalar(
        select(Aufgabe.reihenfolge)
        .where(Aufgabe.benutzer_id == person.id)
        .order_by(Aufgabe.reihenfolge)
        .limit(1)
    )
    aufgabe = Aufgabe(
        benutzer_id=person.id,
        konto_id=nachricht.konto_id,
        nachricht_id=nachricht.id,
        message_id=nachricht.message_id,
        betreff=titel,
        von_name=nachricht.von_name,
        von_adresse=nachricht.von_adresse,
        mail_datum=nachricht.datum,
        faellig=_als_zeitpunkt(stand.faellig),
        reihenfolge=(kleinste if kleinste is not None else 0) - 1,
        fern_art=v.art,
        verbindung_id=v.id,
        fern_id=stand.id,
        fern_url=stand.url,
        fern_liste=liste_name.strip()[:200],
    )
    v.letzter_fehler = ""
    db.add(aufgabe)
    try:
        db.commit()
    except IntegrityError:
        # ⚠️ Zwei Anfragen zugleich fuer dieselbe Mail: Die zweite verliert
        # hier und bekommt die erste zurueck. In der App steht dann ein Doppel;
        # das sagt das Protokoll, denn wegraeumen kann es nur der Mensch.
        db.rollback()
        logger.warning("A to-do app got the same message twice; one task there is a duplicate.")
        schon = _vorhanden(db, person, nachricht)
        if schon is None:
            raise
        return schon, False
    logger.info("A message was turned into a task in a to-do app (%s).", v.art)
    return aufgabe, True


# --- Haken und Datum ----------------------------------------------------------- #


def _verwaltet(db: Session, aufgabe: Aufgabe) -> Aufgabenverbindung | None:
    """Die Verbindung, wenn die Aufgabe noch ueber eine App laeuft."""
    if not aufgabe.fern_art or not aufgabe.verbindung_id or aufgabe.fern_geloescht:
        return None
    return db.get(Aufgabenverbindung, aufgabe.verbindung_id)


def abhaken(db: Session, person: Benutzer, aufgabe_id: int, erledigt: bool) -> Aufgabe:
    """⚠️ **Erst die App, dann hier.** Lehnt sie ab, bleibt der Haken, wie er
    war — ein Haken, der hier sitzt und dort nicht, waere die eine Luege, die
    der Abgleich beim naechsten Mal still zuruecknaehme."""
    aufgabe = aufgaben.eine(db, person, aufgabe_id)
    v = _verwaltet(db, aufgabe)
    if v is not None and erledigt != (aufgabe.erledigt is not None):
        try:
            if erledigt:
                todoist.schliessen(_zugang(v), aufgabe.fern_id)
            else:
                todoist.oeffnen(_zugang(v), aufgabe.fern_id)
        except todoist.TodoistFehler as fehler:
            _fehler_merken(v, fehler)
            db.commit()
            raise
    return aufgaben.abhaken(db, person, aufgabe_id, erledigt)


def faelligkeit(db: Session, person: Benutzer, aufgabe_id: int, wann: datetime | None) -> Aufgabe:
    """⚠️ **Das Datum einer App-Aufgabe aendert man in der App.** Hier ist es
    nur ihr letzter Stand; eine Aenderung hier haette der Abgleich gleich
    wieder ueberschrieben."""
    aufgabe = aufgaben.eine(db, person, aufgabe_id)
    if _verwaltet(db, aufgabe) is not None:
        raise ZielFehler("aufgabe_datum_in_der_app")
    return aufgaben.faelligkeit(db, person, aufgabe_id, wann)


# --- Abgleich ------------------------------------------------------------------ #


def _eine_abgleichen(db: Session, v: Aufgabenverbindung) -> None:
    grenze = _jetzt() - NACHSEHEN_ERLEDIGTE
    zeilen = [
        a
        for a in db.scalars(
            select(Aufgabe).where(
                Aufgabe.verbindung_id == v.id,
                Aufgabe.fern_geloescht.is_(False),
                Aufgabe.fern_id != "",
            )
        )
        if a.erledigt is None or a.erledigt >= grenze
    ]
    if not zeilen:
        return
    zugang = _zugang(v)
    offen = todoist.offene(zugang, [a.fern_id for a in zeilen])
    for a in zeilen:
        stand = offen.get(a.fern_id)
        if stand is not None:
            a.erledigt = None
            a.faellig = _als_zeitpunkt(stand.faellig)
            continue
        if a.erledigt is not None:
            # ⚠️ Erledigt und weiter nicht offen: nichts zu fragen. Sonst
            # kostete jede erledigte Aufgabe bei jedem Lauf eine Anfrage.
            continue
        einzeln = todoist.eine(zugang, a.fern_id)
        if einzeln is None:
            a.fern_geloescht = True
        elif einzeln.erledigt is not None:
            a.erledigt = einzeln.erledigt
            a.faellig = _als_zeitpunkt(einzeln.faellig)


def abgleichen(db: Session, person: Benutzer, *, beim_oeffnen: bool = False) -> None:
    """Was die Apps zu den Aufgaben sagen, hier nachziehen.

    ⚠️ **Eine Verbindung, die scheitert, haelt die anderen nicht auf**, und
    ihr Fehler steht an ihr, nicht im Protokoll allein. Der Stand der Aufgaben
    bleibt dann der letzte bekannte.
    """
    if beim_oeffnen:
        jetzt = time.monotonic()
        if jetzt - _zuletzt_beim_oeffnen.get(person.id, -OEFFNEN_PAUSE) < OEFFNEN_PAUSE:
            return
        _zuletzt_beim_oeffnen[person.id] = jetzt

    for v in verbindungen(db, person):
        try:
            _eine_abgleichen(db, v)
            v.letzter_fehler = ""
            v.zuletzt_abgeglichen = _jetzt()
        except (todoist.TodoistFehler, crypto.SchluesselFehler) as fehler:
            v.letzter_fehler = fehler.kennung[:80]
            logger.info("A to-do app could not be checked: %s", fehler.kennung)
        db.commit()


def alle_abgleichen(db: Session) -> None:
    """Fuer den Takt: jeder Benutzer mit mindestens einer Verbindung."""
    leute = db.scalars(
        select(Benutzer).where(
            Benutzer.id.in_(select(Aufgabenverbindung.benutzer_id).distinct())
        )
    )
    for person in list(leute):
        abgleichen(db, person)
