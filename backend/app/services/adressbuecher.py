"""Adressbücher — wo ein Kontakt liegt.

⚠️ **Ein Buch ist keine Gruppe.** Gruppen sind quer: Ein Mensch steht in
„Familie" und in „Verein". Ein Buch ist der **Ort** — davon genau eines. Wer
beides vermengt, macht „löschen" mehrdeutig, und man sieht es dem Eintrag nicht
an. Dieselbe Klasse Fehler wie die zwei Quellen bei den Ungelesen-Zahlen.

⚠️ **Jeder Benutzer hat mindestens ein Buch**, und es lässt sich nicht
entfernen. Es hält die Kontakte, die nur hier leben, und alles Aufgeschnappte.
Ohne es hinterliesse ein gelöschtes Buch heimatlose Kontakte — und die zeigt
die Spalte links dann gar nicht mehr an.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..meldung import Meldung
from ..models import Adressbuch, Benutzer, Kontakt

logger = logging.getLogger("nexmail.adressbuecher")


class BuchFehler(Meldung):
    """Etwas, das dem Menschen davor gezeigt wird."""


#: Wie das lokale Buch heisst, wenn es angelegt wird.
#:
#: ⚠️ **Ein fester Name, keine Übersetzung.** Er steht als Datenbankzeile und
#: wird vom Benutzer umbenannt, wenn er will — eine Zeile, die sich mit der
#: Spracheinstellung ändert, wäre in einer Sicherung nicht wiederzuerkennen.
#: Dieselbe Entscheidung wie bei den Ordnerrollen.
LOKAL_NAME = "Meine Kontakte"

#: Dieselbe geprüfte Palette wie bei Postfächern, Kalendern und Schlagworten.
#: ⚠️ Nie eine Farbe erfinden.
FARBEN = 6


def naechste_farbe(vorhanden: list[Adressbuch]) -> int:
    """Die erste Farbe der Palette, die noch kein Buch trägt; sonst reihum."""
    belegt = {b.farbe for b in vorhanden}
    for farbe in range(1, FARBEN + 1):
        if farbe not in belegt:
            return farbe
    return len(vorhanden) % FARBEN + 1


def lokales(db: Session, person: Benutzer) -> Adressbuch:
    """Das lokale Buch dieses Benutzers — und legt es an, wenn es fehlt.

    ⚠️ **Anlegen statt Fehler werfen.** Ein Benutzer ohne lokales Buch ist ein
    Zustand, den es nicht geben soll; ihn beim ersten Zugriff zu heilen ist
    billiger als jeden Aufrufer prüfen zu lassen.
    """
    buch = db.execute(
        select(Adressbuch).where(
            Adressbuch.benutzer_id == person.id, Adressbuch.ist_lokal.is_(True)
        )
    ).scalar_one_or_none()
    if buch is not None:
        return buch

    buch = Adressbuch(
        benutzer_id=person.id, name=LOKAL_NAME, ist_lokal=True, farbe=1, reihenfolge=0
    )
    db.add(buch)
    db.commit()
    logger.info("A local address book was created for one account.")
    return buch


def meine(db: Session, person: Benutzer) -> list[Adressbuch]:
    """Alle Bücher dieses Benutzers, das lokale zuerst."""
    lokales(db, person)
    return list(
        db.execute(
            select(Adressbuch)
            .where(Adressbuch.benutzer_id == person.id)
            .order_by(Adressbuch.ist_lokal.desc(), Adressbuch.reihenfolge, Adressbuch.name)
        ).scalars()
    )


def meines(db: Session, person: Benutzer, buch_id: str) -> Adressbuch:
    """Ein Buch, das wirklich diesem Benutzer gehört."""
    buch = db.get(Adressbuch, buch_id)
    if buch is None or buch.benutzer_id != person.id:
        raise BuchFehler("adressbuch_nicht_gefunden")
    return buch


def aendern(db: Session, person: Benutzer, buch_id: str, **felder) -> Adressbuch:
    """Name, Farbe und Sichtbarkeit. Mehr gehört dem Benutzer nicht.

    ⚠️ **Nicht mitgeschickt heisst unverändert** — dieselbe Regel wie beim
    Passwort, den Schlagworten und den Aliassen.
    """
    buch = meines(db, person, buch_id)
    if (name := felder.get("name")) is not None:
        sauber = " ".join(str(name).split())[:120]
        if not sauber:
            raise BuchFehler("adressbuch_name_fehlt")
        buch.name = sauber
    if (farbe := felder.get("farbe")) is not None:
        buch.farbe = max(1, min(FARBEN, int(farbe)))
    if (sichtbar := felder.get("sichtbar")) is not None:
        buch.sichtbar = bool(sichtbar)
    db.commit()
    return buch


def entfernen(db: Session, person: Benutzer, buch_id: str) -> int:
    """Ein verbundenes Buch trennen. Seine Kontakte fallen mit.

    ⚠️ **Das lokale Buch geht nicht.** Danach hätten die Kontakte, die nur hier
    leben, keinen Ort mehr — und die aufgeschnappten auch nicht. Dieselbe Regel
    wie „der Betreiber lässt sich nicht entfernen".

    ⚠️ **Beim Anbieter wird nichts gelöscht.** Die Rückfrage sagt das; ohne den
    Satz klingt „entfernen" nach „weg". Dieselbe Zusage wie beim Kalender.
    """
    from . import kontakte as kontaktdienst  # unten, weil kontakte.py dieses Modul lädt

    buch = meines(db, person, buch_id)
    if buch.ist_lokal:
        raise BuchFehler("adressbuch_lokal_bleibt")
    # ⚠️ Erst die Mitgliedschaften, sonst zählen die Gruppen Gelöschte weiter.
    kontaktdienst.mitgliedschaften_loesen(
        db, select(Kontakt.id).where(Kontakt.adressbuch_id == buch.id)
    )
    anzahl = (
        db.query(Kontakt)
        .filter(Kontakt.adressbuch_id == buch.id)
        .delete(synchronize_session=False)
    )
    db.delete(buch)
    db.commit()
    logger.info("An address book was disconnected (%s contact(s) removed here).", anzahl)
    return anzahl


def verschieben(db: Session, person: Benutzer, kontakt_id: int, buch_id: str) -> Kontakt:
    """Einen Kontakt in ein anderes Buch legen.

    ⚠️ **Der Weg für das Aufgeschnappte.** Was aus „Gesendet" eingesammelt
    wurde, bleibt lokal und geht nie von selbst hinaus; wer es behalten will,
    schiebt es hier in ein verbundenes Buch. Ein Automatismus hätte nach zwei
    Monaten dreihundert ungepflegte Einträge auf dem Telefon.

    ⚠️ **Die Kennungen des Anbieters fallen dabei.** Ein Kontakt, der das Buch
    wechselt, ist beim alten Anbieter nicht mehr derselbe Eintrag; ``uid``,
    ``href`` und ``etag`` mitzunehmen hiesse, beim nächsten Abgleich auf eine
    fremde Karte zu zeigen.
    """
    kontakt = db.get(Kontakt, kontakt_id)
    if kontakt is None or kontakt.benutzer_id != person.id:
        raise BuchFehler("kontakt_nicht_gefunden")
    ziel = meines(db, person, buch_id)
    if kontakt.adressbuch_id == ziel.id:
        return kontakt

    kontakt.adressbuch_id = ziel.id
    kontakt.uid = ""
    kontakt.href = ""
    kontakt.etag = ""
    # ⚠️ **``roh`` bleibt stehen.** Es ist die Rückfahrkarte: Foto, Geburtstag
    # und alles, was nexmail nicht kennt, gehören dem Menschen und nicht dem
    # Ort. Wer sie beim Verschieben wegwirft, verliert sie unwiederbringlich.
    #
    # Wartend ist die Zeile nur in einem verbundenen Buch: Dort holt sie der
    # Abgleich an ihre Karte oder bringt sie hinaus. Im lokalen Buch gibt es
    # niemanden, auf den sie warten könnte — und ein wartendes Zeichen, das
    # nie fällt, sähe aus wie ein Fehler.
    kontakt.schmutzig = bool(ziel.art)
    db.commit()
    return kontakt


def neu_lesen_erzwingen(db: Session) -> int:
    """Alle Karten verbundener Bücher beim nächsten Abgleich neu holen lassen.

    ⚠️ **Für den Fall, dass der Leser besser geworden ist.** 0.10.0 las Apples
    leeres ``FN`` als Namen und liess das ``N`` danach liegen; 149 von 185
    Karten kamen ohne Namen an. Die Felder entstehen beim Holen aus der Karte,
    und geholt wird nur, was sich drüben geändert hat. Ohne diesen Griff
    blieben die Namen leer, bis jemand am Telefon jeden Kontakt einmal
    anfasst. Deshalb fallen ``etag`` je Karte und ``ctag`` je Buch; der
    nächste Takt vergleicht voll und holt alles noch einmal, durch dieselben
    Regeln wie sonst. ``roh`` bleibt, es ist die Rückfahrkarte.

    Läuft einmal beim Start, gemerkt an ``karten_neu_gelesen``, wie
    ``nachtragen``.
    """
    verbundene = select(Adressbuch.id).where(Adressbuch.art == "carddav")
    karten = (
        db.query(Kontakt)
        .filter(Kontakt.adressbuch_id.in_(verbundene), Kontakt.etag != "")
        .update({"etag": ""}, synchronize_session=False)
    )
    db.query(Adressbuch).filter(Adressbuch.art == "carddav").update(
        {"ctag": ""}, synchronize_session=False
    )
    if karten:
        db.commit()
        logger.info("%s connected contact card(s) will be fetched again on the next sync.", karten)
    return karten


def nachtragen(db: Session) -> int:
    """Jedem Benutzer sein lokales Buch geben und heimatlose Kontakte einordnen.

    ⚠️ **Einmal beim Start, gemerkt an einem Schlüssel** — dasselbe Muster wie
    der Strang-Neuaufbau und das Nachtragen von ``angekommen``. Ohne die Marke
    liefe bei jedem Hochfahren ein ``UPDATE`` über die ganze Kontakttabelle.

    ⚠️ **Und es muss laufen, bevor irgendwer die Kontaktseite öffnet.** Ein
    Kontakt ohne Buch ist einer, den die Spalte links nicht zeigen kann — er
    wäre unsichtbar, ohne gelöscht zu sein. Genau die Sorte Fehler, die wie
    Datenverlust aussieht.
    """
    geordnet = 0
    for person in db.execute(select(Benutzer)).scalars().all():
        buch = lokales(db, person)
        geordnet += (
            db.query(Kontakt)
            .filter(Kontakt.benutzer_id == person.id, Kontakt.adressbuch_id.is_(None))
            .update({"adressbuch_id": buch.id}, synchronize_session=False)
        )
    if geordnet:
        db.commit()
        logger.info("Sorted %s contact(s) into their local address book.", geordnet)
    return geordnet
