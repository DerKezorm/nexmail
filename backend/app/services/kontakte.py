"""Das Adressbuch — gepflegt, eingesammelt, ein- und ausgeführt.

Drei Wege hinein, und nur der erste ist Arbeit:

1. **Von Hand** angelegt.
2. **Eingesammelt** aus „Gesendet": Wem man geschrieben hat, den kennt man.
3. **vCard** aus einem anderen Programm.

⚠️ **Eingesammeltes bleibt als solches erkennbar.** Sonst kann man es nie
wieder in einem Zug loswerden — und ein Adressbuch, das sich mit den Jahren
mit Einmalempfängern zusetzt und sich nicht aufräumen lässt, benutzt niemand
mehr.

⚠️ **Ein eingesammelter Eintrag überschreibt niemals einen gepflegten.** Wer
„Oma" einträgt, will nicht, dass der nächste Versand daraus
„gertrud.mueller@example.org" macht, weil im ``From`` zufällig das stand.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Adressbuch,
    Benutzer,
    Kontakt,
    Kontaktgruppe,
    KontaktgruppeMitglied,
    Nachricht,
    Ordner,
)
from ..meldung import Meldung
from . import adressbuecher, caldav, carddav, vcard
# Die vCard-Textregeln, der Leser und der Zeilen-Editor wohnen in ``vcard.py``;
# hier steht, was daraus in die Datenbank geht und wieder heraus.
from .vcard import entfalten

logger = logging.getLogger("nexmail.kontakte")


class KontaktFehler(Meldung, RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


_ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def adresse_pruefen(adresse: str) -> str:
    sauber = adresse.strip().lower()
    if not _ADRESSE.match(sauber):
        raise KontaktFehler("kontakt_adresse_ungueltig", adresse=sauber)
    return sauber


def _adresse_oder_leer(adresse: str | None) -> str:
    """Leer heisst „keine Adresse"; alles andere muss eine sein.

    ⚠️ **Seit dem 05.09.2026 darf ein Kontakt ohne Adresse leben.** Mit
    CardDAV ist nexmail der zweite Client einer Kontaktliste, und die hat
    Menschen ohne Postfach. Anschreiben lassen die sich nicht; Vorschlaege
    und Gruppen lassen sie aus.
    """
    sauber = (adresse or "").strip()
    return adresse_pruefen(sauber) if sauber else ""


def _etwas_muss_da_sein(adresse: str, name: str, telefon: str, firma: str) -> None:
    """⚠️ Ohne Adresse wenigstens Name, Nummer oder Firma. Eine Zeile, die
    nichts davon traegt, findet niemand wieder, und sie steht trotzdem im
    Buch."""
    if not (adresse or name.strip() or telefon.strip() or firma.strip()):
        raise KontaktFehler("kontakt_leer")


# --- Die Felder einer Zeile ------------------------------------------------ #
# Seit dem Felder-Schritt (11.09.2026) traegt ein Kontakt Vor- und Nachname,
# Spitzname, Abteilung, Position, Geburtstag, Webseite und die drei Listen
# (Nummern, Adressen, Anschriften), jeder Eintrag mit Art, eigener
# Beschriftung und Stern. ``name``, ``adresse`` und ``telefon`` bleiben als
# abgeleitete Spalten: der Anzeigename und je der Eintrag mit Stern. Die Regel
# aus CLAUDE.md gilt: nur Felder, die iCloud und Google beide kennen.

LISTEN = vcard.LISTEN
#: Mehr Nummern hat kein Mensch; wer mehr braucht, hat einen Verteiler.
GRENZE_LISTE = 20
_LAENGE = {"vorname": 160, "nachname": 160, "spitzname": 160, "firma": 320, "abteilung": 160,
           "titel": 160, "geburtstag": 32, "webseite": 320}
_GEBURTSTAG = re.compile(r"(\d{4}|-)-\d{2}-\d{2}")


def _json_liste(text) -> list[dict]:
    """Eine JSON-Spalte als Liste von Woerterbuechern; Kaputtes ist leer, nicht
    tot — es kommt aus der eigenen Datenbank, aber ein halb eingespieltes
    Archiv ist denkbar."""
    try:
        wert = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return [e for e in wert if isinstance(e, dict)] if isinstance(wert, list) else []


def felder_der_zeile(k: Kontakt) -> dict:
    """Alles, was nexmail an einer Zeile pflegt, als Feldersatz — fuer den
    Schreiber, den Export und die Schnittstelle.

    ⚠️ **Ohne ``name``.** Der ist abgeleitet; wer ihn mitgaebe, liesse
    ``vcard.felder_normieren`` einen Firmen-Kontakt („Polizei Beispielstadt",
    ohne Vor- und Nachname) beim naechsten Speichern in Vor- und Nachname
    teilen.
    """
    felder = {f: getattr(k, f) or "" for f in vcard.FELDER}
    felder["adresse"] = k.adresse
    felder["telefon"] = k.telefon
    for liste in LISTEN:
        felder[liste] = _json_liste(getattr(k, liste))
    return felder


def felder_anwenden(k: Kontakt, felder: dict) -> None:
    """Einen normierten Feldersatz in die Zeile schreiben. Ohne ``commit``."""
    for f in vcard.FELDER:
        setattr(k, f, (felder.get(f) or "")[: _LAENGE.get(f, 5000)])
    k.name = (felder.get("name") or "")[:320]
    k.adresse = (felder.get("adresse") or "")[:320]
    k.telefon = (felder.get("telefon") or "")[:120]
    for liste in LISTEN:
        # ⚠️ ``ensure_ascii=False``, sonst steht „Zweitbüro" als ``\u00fc``
        # in der Spalte, und die Suche mit LIKE findet es nie.
        setattr(k, liste, json.dumps(felder.get(liste) or [], ensure_ascii=False))


def felder_pruefen_lose(felder: dict) -> dict:
    """Der Feldersatz einer Karte vom Anbieter: normiert, ohne zu werfen.
    Eine kaputte Adresse in der Liste faellt heraus, statt die Karte
    abzuweisen — der Rest ist etwas wert."""
    neu = vcard.felder_normieren(felder)
    neu["adressen"] = [a for a in neu["adressen"] if _ADRESSE.match(a["adresse"])]
    neu["adresse"] = vcard.bevorzugte(neu["adressen"], "adresse")
    for liste in LISTEN:
        neu[liste] = neu[liste][:GRENZE_LISTE]
    # Der Anzeigename der Karte gilt auch ohne Vor- und Nachname (Firma).
    neu["name"] = neu["name"] or (felder.get("name") or "")
    return neu


def felder_pruefen(felder: dict, alt: dict | None = None) -> dict:
    """Eingaben normieren und pruefen: Adressen echt, Listen gedeckelt,
    Geburtstag in Form. ``alt`` ist der bisherige Feldersatz; was darin schon
    so stand, wird nicht erneut geprueft — eine Karte vom Anbieter darf
    Eigenheiten tragen, an denen ein Mensch sonst beim Speichern scheiterte."""
    neu = vcard.felder_normieren(felder)
    alt = alt or {}
    for liste in LISTEN:
        if len(neu[liste]) > GRENZE_LISTE:
            raise KontaktFehler("kontakt_zu_viele_eintraege", max=GRENZE_LISTE)
    bekannt = {a.get("adresse") for a in alt.get("adressen", [])}
    for a in neu["adressen"]:
        if a["adresse"] not in bekannt:
            a["adresse"] = adresse_pruefen(a["adresse"])
    if neu["geburtstag"] != alt.get("geburtstag", "") and neu["geburtstag"] and not _GEBURTSTAG.fullmatch(neu["geburtstag"]):
        raise KontaktFehler("kontakt_geburtstag_ungueltig")
    if neu["webseite"] and neu["webseite"] != alt.get("webseite", "") and " " in neu["webseite"]:
        raise KontaktFehler("kontakt_webseite_ungueltig")
    _etwas_muss_da_sein(neu["adresse"], neu["name"], neu["telefon"], neu["firma"])
    return neu


# --- Lesen ---------------------------------------------------------------- #


def meine(db: Session, person: Benutzer, suche: str = "") -> list[Kontakt]:
    frage = select(Kontakt).where(Kontakt.benutzer_id == person.id)
    if suche.strip():
        muster = f"%{suche.strip().lower()}%"
        frage = frage.where(
            or_(
                func.lower(Kontakt.name).like(muster),
                func.lower(Kontakt.spitzname).like(muster),
                func.lower(Kontakt.adresse).like(muster),
                func.lower(Kontakt.firma).like(muster),
                # Ein Kontakt ohne Adresse ist oft nur eine Nummer mit Namen —
                # und seit dem Felder-Schritt steht jede Nummer in der Liste.
                Kontakt.telefon.like(muster),
                Kontakt.nummern.like(muster),
                func.lower(Kontakt.adressen).like(muster),
            )
        )
    return list(db.execute(frage.order_by(Kontakt.name, Kontakt.adresse)).scalars().all())


def vorschlagen(
    db: Session, person: Benutzer, anfang: str, grenze: int = 8
) -> list[tuple[Kontakt, str]]:
    """Vorschläge beim Tippen einer Adresse, je Adresse einer.

    ⚠️ **Sortiert nach Häufigkeit, nicht alphabetisch.** Wer „ma" tippt, meint
    fast immer den, dem er ständig schreibt — nicht den, der zufällig vorne im
    Alphabet steht.

    ⚠️ **Alle Adressen eines Kontakts, nicht nur die mit Stern.** Wer
    „arbeit" tippt, meint die Arbeitsadresse; passt der Name, kommen alle,
    die bevorzugte zuerst.
    """
    kern = anfang.strip().lower()
    if not kern:
        return []
    muster = f"%{kern}%"
    frage = (
        select(Kontakt)
        .where(
            Kontakt.benutzer_id == person.id,
            or_(
                func.lower(Kontakt.name).like(muster),
                func.lower(Kontakt.adresse).like(muster),
                func.lower(Kontakt.adressen).like(muster),
            ),
        )
        .order_by(Kontakt.verwendet.desc(), Kontakt.name, Kontakt.adresse)
        .limit(grenze * 3)
    )
    aus: list[tuple[Kontakt, str]] = []
    for k in db.execute(frage).scalars().all():
        # ⚠️ Nur, wem man schreiben kann. Ein Vorschlag ohne Adresse setzte
        # ein leeres Feld ein.
        kandidaten = [k.adresse] if k.adresse else []
        kandidaten += [a["adresse"] for a in _json_liste(k.adressen) if a.get("adresse") and a["adresse"] not in kandidaten]
        if kern not in k.name.lower():
            kandidaten = [a for a in kandidaten if kern in a]
        for adresse in kandidaten:
            aus.append((k, adresse))
            if len(aus) >= grenze:
                return aus
    return aus


# --- Schreiben ------------------------------------------------------------ #


def anlegen(
    db: Session,
    person: Benutzer,
    adresse: str = "",
    name: str = "",
    firma: str = "",
    telefon: str = "",
    notiz: str = "",
    quelle: str = "hand",
    adressbuch_id: str | None = None,
    **weitere,
) -> Kontakt:
    """Einen Kontakt anlegen, im lokalen Buch oder in einem verbundenen.

    ``weitere`` sind die Felder seit dem Felder-Schritt (Vor- und Nachname,
    Listen …); ``name``, ``telefon`` und ``adresse`` einzeln bleiben der alte
    Weg und werden zu Listen mit einem Eintrag.

    ⚠️ **In einem verbundenen Buch geht die Karte zuerst zum Anbieter.** Was
    der ablehnt, steht hier gar nicht erst; die Zeile fällt mit dem Rollback.
    """
    if adresse:
        adresse = _adresse_oder_leer(adresse)
    neu = felder_pruefen(
        {"adresse": adresse, "name": name, "firma": firma, "telefon": telefon, "notiz": notiz, **weitere}
    )
    if neu["adresse"]:
        vorhanden = db.execute(
            select(Kontakt).where(Kontakt.benutzer_id == person.id, Kontakt.adresse == neu["adresse"])
        ).scalar_one_or_none()
        if vorhanden is not None:
            raise KontaktFehler("adresse_schon_da", adresse=neu["adresse"])

    buch = _zielbuch(db, person, adressbuch_id)
    eintrag = Kontakt(benutzer_id=person.id, quelle=quelle, adressbuch_id=buch.id)
    felder_anwenden(eintrag, neu)
    db.add(eintrag)
    if buch.art:
        from . import adressbuchabgleich

        db.flush()
        try:
            adressbuchabgleich.hochschieben(db, eintrag)
        except _ANBIETERFEHLER as f:
            db.rollback()
            _anbieterfehler(f)
    db.commit()
    return eintrag


def _zielbuch(db: Session, person: Benutzer, adressbuch_id: str | None) -> Adressbuch:
    if not adressbuch_id:
        return adressbuecher.lokales(db, person)
    try:
        return adressbuecher.meines(db, person, adressbuch_id)
    except adressbuecher.BuchFehler as f:
        raise KontaktFehler("adressbuch_nicht_gefunden") from f


def _ist_verbunden(db: Session, eintrag: Kontakt) -> bool:
    if not eintrag.adressbuch_id:
        return False
    buch = db.get(Adressbuch, eintrag.adressbuch_id)
    return buch is not None and bool(buch.art)


#: Was beim Anbieter schiefgehen kann. ``caldav`` steht mit dabei, weil
#: ``carddav`` dessen Verbindung benutzt und dessen Kennungen weiterreicht.
_ANBIETERFEHLER = (carddav.CarddavFehler, caldav.CaldavFehler)


def _anbieterfehler(f: Exception) -> None:
    """Was der Anbieter gesagt hat, als Kennung für die Oberfläche weiterwerfen.

    ⚠️ **Ein Konflikt ist keine Fehlermeldung, sondern eine Frage.** Er bekommt
    seine eigene Kennung, an der die Oberfläche das Fenster mit beiden
    Fassungen aufmacht; alles andere trägt die Kennung des Protokolls weiter.
    """
    if isinstance(f, carddav.KonfliktFehler):
        raise KontaktFehler("kontakt_konflikt") from f
    raise KontaktFehler(str(f)) from f


def aendern(
    db: Session, person: Benutzer, kontakt_id: int, erzwingen: bool = False, **felder
) -> Kontakt:
    """Einen Kontakt ändern; bei einem verbundenen geht die Karte zuerst hinaus.

    Nicht mitgeschickte Felder bleiben, wie sie sind. Ein einzelnes
    ``telefon`` oder ``adresse`` (der alte Weg) meint den Eintrag mit Stern;
    ein ``name`` ohne Vor- und Nachname wird geteilt.

    ``erzwingen`` ist die Antwort auf die Rückfrage im Konfliktfenster: „meine
    Fassung gewinnt". Dann wird auf der **frischen** fremden Karte geschrieben,
    nicht auf der alten — sonst sässe die eigene Änderung auf einem veralteten
    Original und holte fremde Zeilen zurück, die drüben längst weg sind.
    """
    eintrag = _meiner(db, person, kontakt_id)
    # ⚠️ Erst pruefen, dann anfassen. Wer die Zeile schon geaendert hat, wenn
    # die Pruefung wirft, laesst sie schmutzig in der Sitzung liegen, und der
    # naechste ``commit`` eines anderen schreibt sie mit.
    alt = felder_der_zeile(eintrag)
    eingabe = {k: v for k, v in felder.items() if v is not None}
    if "nummern" not in eingabe and "telefon" in eingabe:
        eingabe["nummern"] = vcard.einzel_einmischen(
            alt["nummern"], "nummer", str(eingabe.pop("telefon")).strip(), vcard.nummer_kern
        )
    if "adressen" not in eingabe and "adresse" in eingabe:
        eingabe["adressen"] = vcard.einzel_einmischen(
            alt["adressen"], "adresse", _adresse_oder_leer(str(eingabe.pop("adresse"))), str.lower
        )
    if "name" in eingabe and "vorname" not in eingabe and "nachname" not in eingabe:
        eingabe["vorname"], eingabe["nachname"] = vcard.name_teilen(str(eingabe.pop("name")))
    neu = felder_pruefen({**alt, **eingabe}, alt)

    # Eine leere Adresse heisst „keine mehr", eine andere darf keinem anderen gehoeren.
    if neu["adresse"] and neu["adresse"] != eintrag.adresse:
        doppelt = db.execute(
            select(Kontakt).where(
                Kontakt.benutzer_id == person.id,
                Kontakt.adresse == neu["adresse"],
                Kontakt.id != eintrag.id,
            )
        ).scalar_one_or_none()
        if doppelt is not None:
            raise KontaktFehler("adresse_bei_anderem", adresse=neu["adresse"])

    if _ist_verbunden(db, eintrag):
        from . import adressbuchabgleich

        # Erst der Server, dann die eigene Datenbank. Die geänderte Karte
        # entsteht auf der Rohkarte: geändert werden nur die Zeilen der
        # Felder, die nexmail pflegt, erkannt an ihren Werten.
        try:
            if erzwingen and not adressbuchabgleich.frisch_machen(db, eintrag):
                # ⚠️ Drüben gelöscht. „Meine Fassung" heisst dann: wieder
                # anlegen, unter derselben Adresse. Mit dem alten ETag
                # ginge ``If-Match`` hinaus, und das ist auf eine Karte,
                # die es nicht mehr gibt, ein zweiter Konflikt ohne Ende.
                eintrag.etag = ""
            roh_neu = vcard.aktualisieren(eintrag.roh, neu, eintrag.uid)
            adressbuchabgleich.hochschieben(db, eintrag, roh_neu)
        except _ANBIETERFEHLER as f:
            db.rollback()
            _anbieterfehler(f)

    felder_anwenden(eintrag, neu)
    # Wer einen Eintrag anfasst, hat ihn gepflegt - er ist nicht mehr
    # Aufgeschnapptes und darf beim Aufraeumen nicht mitgehen.
    eintrag.quelle = "hand"
    db.commit()
    return eintrag


def mitgliedschaften_loesen(db: Session, kontakt_ids) -> None:
    """Die Zuordnungen dieser Kontakte zu ihren Gruppen wegräumen. Ohne ``commit``.

    ⚠️ **Vor JEDEM Löschen eines Kontakts, egal auf welchem Weg.** Eine
    Zuordnung auf einen gelöschten Kontakt ist eine Leiche: unsichtbar in der
    Oberfläche, aber die Mitgliederzahl der Gruppe zählt sie weiter mit. Vier
    Wege löschen Kontakte: von Hand, das Aufgeschnappte in einem Zug, ein
    getrenntes Buch und der Abgleich, wenn eine Karte drüben verschwunden ist.
    Der dritte hatte das bis zum 05.09.2026 vergessen.

    ``kontakt_ids`` ist eine Liste oder ein ``select(Kontakt.id)``.
    """
    db.query(KontaktgruppeMitglied).filter(
        KontaktgruppeMitglied.kontakt_id.in_(kontakt_ids)
    ).delete(synchronize_session=False)


def entfernen(db: Session, person: Benutzer, kontakt_id: int) -> None:
    """Einen Kontakt löschen; bei einem verbundenen zuerst beim Anbieter.

    ⚠️ **Ein 412 beim Löschen ist ein Konflikt wie jeder andere:** Jemand hat
    die Karte inzwischen geändert. Sie trotzdem zu löschen hiesse, eine
    Änderung zu verwerfen, die nie jemand gesehen hat. Der nächste Abgleich
    holt sie; danach lässt sich noch einmal entscheiden.
    """
    eintrag = _meiner(db, person, kontakt_id)
    if _ist_verbunden(db, eintrag):
        from . import adressbuchabgleich

        try:
            adressbuchabgleich.wegnehmen(db, eintrag)
        except _ANBIETERFEHLER as f:
            _anbieterfehler(f)
    mitgliedschaften_loesen(db, [eintrag.id])
    db.delete(eintrag)
    db.commit()


def verschieben(db: Session, person: Benutzer, kontakt_id: int, buch_id: str) -> Kontakt:
    """Einen Kontakt in ein anderes Buch legen und, wenn das Buch verbunden
    ist, gleich zum Anbieter bringen.

    ⚠️ **Erst suchen, dann anlegen.** Kennt der Anbieter die Adresse schon,
    hängt sich die Zeile an seine Karte (der erzwungene Abgleich erkennt sie
    an der Adresse, und die Karte gewinnt); sonst entsteht die Karte aus der
    Zeile. Ohne diese Reihenfolge stünde derselbe Mensch drüben zweimal,
    sobald jemand einen Aufgeschnappten „ins Buch" schiebt, der dort längst
    steht.

    ⚠️ **Aus einem verbundenen Buch heraus heisst: dort löschen.** Ein Kontakt,
    der iCloud verlässt, soll bei iCloud nicht weiterleben; sonst käme er beim
    nächsten Abgleich als neue Zeile zurück, und der Umzug wäre eine Kopie.
    """
    from . import adressbuchabgleich

    eintrag = _meiner(db, person, kontakt_id)
    if eintrag.adressbuch_id == buch_id:
        return eintrag
    try:
        if _ist_verbunden(db, eintrag):
            adressbuchabgleich.wegnehmen(db, eintrag)
    except _ANBIETERFEHLER as f:
        _anbieterfehler(f)
    try:
        eintrag = adressbuecher.verschieben(db, person, kontakt_id, buch_id)
    except adressbuecher.BuchFehler as f:
        raise KontaktFehler(str(f)) from f
    ziel = db.get(Adressbuch, eintrag.adressbuch_id)
    if ziel is None or not ziel.art:
        return eintrag
    # Der Abgleich erkennt eine wartende Zeile an ihrer Adresse und hängt sie
    # an die vorhandene Karte; was danach noch wartet, bringt er hinaus.
    runde = adressbuchabgleich.abgleichen(db, ziel, erzwingen=True)
    db.refresh(eintrag)
    if eintrag.schmutzig or not eintrag.href:
        # Der Abgleich hat es nicht geschafft (das Buch klemmt); der Grund
        # steht am Buch, hier kommt er als Kennung zurück.
        raise KontaktFehler(ziel.letzter_fehler or "carddav_schreiben_gescheitert")
    logger.info(
        "A contact moved into a connected book: %s adopted, %s pushed.",
        runde.neu + runde.geaendert, runde.hochgeschoben,
    )
    return eintrag


def gesammelte_entfernen(db: Session, person: Benutzer) -> int:
    """Alles Aufgeschnappte in einem Zug loswerden."""
    betroffene = select(Kontakt.id).where(
        Kontakt.benutzer_id == person.id, Kontakt.quelle == "gesammelt"
    )
    mitgliedschaften_loesen(db, betroffene)
    anzahl = (
        db.query(Kontakt)
        .filter(Kontakt.benutzer_id == person.id, Kontakt.quelle == "gesammelt")
        .delete()
    )
    db.commit()
    logger.info("Removed %s collected contacts.", anzahl)
    return anzahl


def _meiner(db: Session, person: Benutzer, kontakt_id: int) -> Kontakt:
    eintrag = db.get(Kontakt, kontakt_id)
    if eintrag is None or eintrag.benutzer_id != person.id:
        raise KontaktFehler("eintrag_unbekannt")
    return eintrag


# --- Einsammeln ----------------------------------------------------------- #


def einsammeln(db: Session, person: Benutzer) -> dict[str, int]:
    """Empfänger aus „Gesendet" ins Adressbuch übernehmen.

    ⚠️ **Nur aus „Gesendet", nie aus dem Posteingang.** Wer einem geschrieben
    hat, ist noch lange kein Kontakt — sonst steht nach einer Woche jeder
    Newsletter-Absender im Adressbuch. Wem *man selbst* geschrieben hat, schon.
    """
    ordner = (
        db.execute(select(Ordner.id).join(Nachricht, Nachricht.ordner_id == Ordner.id).where(
            Ordner.rolle == "gesendet", Nachricht.benutzer_id == person.id
        ).distinct())
        .scalars()
        .all()
    )
    if not ordner:
        return {"neu": 0, "gesehen": 0}

    # ⚠️ **Einmal geholt, nicht je Kontakt.** Aufgeschnapptes landet immer im
    # lokalen Buch und geht nie von selbst zu einem Anbieter hinaus — sonst
    # stuenden nach zwei Monaten dreihundert ungepflegte Eintraege auf dem
    # Telefon. Der Weg dorthin ist „In ein Buch uebernehmen", von Hand.
    lokal_id = adressbuecher.lokales(db, person).id

    bekannt = {
        k.adresse: k
        for k in db.execute(select(Kontakt).where(Kontakt.benutzer_id == person.id))
        .scalars()
        .all()
        if k.adresse
    }
    eigene = _eigene_adressen(db, person)

    neu = 0
    gesehen = 0
    zeilen = (
        db.execute(
            select(Nachricht.an_json, Nachricht.kopie_json).where(
                Nachricht.benutzer_id == person.id, Nachricht.ordner_id.in_(ordner)
            )
        )
        .all()
    )
    for an_json, kopie_json in zeilen:
        for name, adresse in _personen(an_json) + _personen(kopie_json):
            if not adresse or adresse in eigene:
                continue
            gesehen += 1
            vorhanden = bekannt.get(adresse)
            if vorhanden is not None:
                vorhanden.verwendet += 1
                # ⚠️ Kein Ueberschreiben des Namens. Siehe Kopf der Datei.
                if not vorhanden.name and name:
                    vorhanden.vorname, vorhanden.nachname = vcard.name_teilen(name)
                    vorhanden.name = name
                continue
            eintrag = Kontakt(
                benutzer_id=person.id, quelle="gesammelt", verwendet=1, adressbuch_id=lokal_id
            )
            felder_anwenden(eintrag, vcard.felder_normieren({"name": name, "adresse": adresse}))
            db.add(eintrag)
            bekannt[adresse] = eintrag
            neu += 1

    db.commit()
    logger.info("Collected %s new contacts from sent mail.", neu)
    return {"neu": neu, "gesehen": gesehen}


def _eigene_adressen(db: Session, person: Benutzer) -> set[str]:
    from ..models import Konto

    return {
        a.lower()
        for a in db.execute(select(Konto.adresse).where(Konto.benutzer_id == person.id))
        .scalars()
        .all()
    }


def _personen(roh: str) -> list[tuple[str, str]]:
    try:
        eintraege = json.loads(roh or "[]")
    except (ValueError, TypeError):
        return []
    ergebnis = []
    for e in eintraege:
        if not isinstance(e, dict):
            continue
        adresse = str(e.get("a", "")).strip().lower()
        if _ADRESSE.match(adresse):
            ergebnis.append((str(e.get("n", "")).strip(), adresse))
    return ergebnis


# --- Gruppen ---------------------------------------------------------------- #
#
# Ein Verteiler ist ein Eingabehelfer beim Adressieren, kein Mailbegriff:
# In der Mail stehen nur die Einzeladressen. Deshalb gibt es hier auch keine
# "Gruppenadresse" - nur Name und Mitglieder.


def gruppen(db: Session, person: Benutzer) -> list[dict]:
    """Alle Gruppen des Benutzers, mit Mitgliedern.

    Die Mitgliederzahl, die Kennungen und die Adressen kommen in einem Zug
    mit: Die Oberflaeche braucht alle drei (Zahl in der Liste, Kennungen im
    Bearbeiten, Adressen beim Adressieren), und es geht um eine Handvoll
    Gruppen je Benutzer - drei Abfragen dafuer waeren Zeremonie.
    """
    zeilen = db.execute(
        select(Kontaktgruppe)
        .where(Kontaktgruppe.benutzer_id == person.id)
        .order_by(func.lower(Kontaktgruppe.name))
    ).scalars().all()

    mitglieder: dict[int, list[tuple[int, str]]] = {}
    for gruppe_id, kontakt_id, adresse in db.execute(
        select(KontaktgruppeMitglied.gruppe_id, Kontakt.id, Kontakt.adresse)
        .join(Kontakt, Kontakt.id == KontaktgruppeMitglied.kontakt_id)
        .where(KontaktgruppeMitglied.benutzer_id == person.id)
        .order_by(Kontakt.name, Kontakt.adresse)
    ).all():
        mitglieder.setdefault(gruppe_id, []).append((kontakt_id, adresse))

    return [
        {
            "id": g.id,
            "name": g.name,
            "mitglieder": len(mitglieder.get(g.id, [])),
            "mitglied_ids": [k for k, _ in mitglieder.get(g.id, [])],
            # ⚠️ Ein Mitglied ohne Adresse zaehlt mit, wird aber nicht
            # adressiert: In der Mail staende sonst ein leerer Empfaenger.
            "adressen": [a for _, a in mitglieder.get(g.id, []) if a],
        }
        for g in zeilen
    ]


def _gruppenname_pruefen(
    db: Session, person: Benutzer, name: str, ausser_id: int | None = None
) -> str:
    sauber = name.strip()
    if not sauber:
        raise KontaktFehler("gruppe_name_fehlt")
    # Gross/klein trennt keine Gruppen - dieselbe Regel wie bei den
    # Postfach-Schlagworten. Verglichen wird klein, behalten die Schreibweise.
    frage = select(Kontaktgruppe).where(
        Kontaktgruppe.benutzer_id == person.id,
        func.lower(Kontaktgruppe.name) == sauber.lower(),
    )
    if ausser_id is not None:
        frage = frage.where(Kontaktgruppe.id != ausser_id)
    if db.execute(frage).scalar_one_or_none() is not None:
        raise KontaktFehler("gruppe_schon_da", name=sauber)
    return sauber


def gruppe_anlegen(db: Session, person: Benutzer, name: str) -> Kontaktgruppe:
    gruppe = Kontaktgruppe(
        benutzer_id=person.id, name=_gruppenname_pruefen(db, person, name)
    )
    db.add(gruppe)
    db.commit()
    return gruppe


def gruppe_umbenennen(
    db: Session, person: Benutzer, gruppe_id: int, name: str
) -> Kontaktgruppe:
    gruppe = _meine_gruppe(db, person, gruppe_id)
    gruppe.name = _gruppenname_pruefen(db, person, name, ausser_id=gruppe.id)
    db.commit()
    return gruppe


def gruppe_entfernen(db: Session, person: Benutzer, gruppe_id: int) -> None:
    """⚠️ Loescht die Gruppe und ihre Zuordnungen - **keinen** Kontakt."""
    gruppe = _meine_gruppe(db, person, gruppe_id)
    db.query(KontaktgruppeMitglied).filter(
        KontaktgruppeMitglied.benutzer_id == person.id,
        KontaktgruppeMitglied.gruppe_id == gruppe.id,
    ).delete()
    db.delete(gruppe)
    db.commit()


def mitglieder_setzen(
    db: Session, person: Benutzer, gruppe_id: int, kontakt_ids: list[int]
) -> None:
    """Den Mitgliederbestand einer Gruppe ersetzen.

    Setzen statt einzeln hinzufuegen/entfernen: Die Oberflaeche zeigt eine
    Mehrfachauswahl, und deren Ergebnis ist der neue Bestand - zwei Wege fuer
    dieselbe Sache waeren nur mehr Adressen.
    """
    gruppe = _meine_gruppe(db, person, gruppe_id)

    gewuenscht = list(dict.fromkeys(kontakt_ids))  # Reihenfolge egal, Doppel weg
    # ⚠️ Nur eigene Kontakte. Eine fremde Kennung ist kein Versehen, das man
    # still wegfiltert - sie ist ein Fehler, der ankommen soll.
    meine_ids = set(
        db.execute(
            select(Kontakt.id).where(
                Kontakt.benutzer_id == person.id, Kontakt.id.in_(gewuenscht)
            )
        ).scalars()
    )
    fremde = [k for k in gewuenscht if k not in meine_ids]
    if fremde:
        raise KontaktFehler("eintrag_fremd")

    db.query(KontaktgruppeMitglied).filter(
        KontaktgruppeMitglied.benutzer_id == person.id,
        KontaktgruppeMitglied.gruppe_id == gruppe.id,
    ).delete()
    for kontakt_id in gewuenscht:
        db.add(
            KontaktgruppeMitglied(
                benutzer_id=person.id, gruppe_id=gruppe.id, kontakt_id=kontakt_id
            )
        )
    db.commit()


def _meine_gruppe(db: Session, person: Benutzer, gruppe_id: int) -> Kontaktgruppe:
    gruppe = db.get(Kontaktgruppe, gruppe_id)
    if gruppe is None or gruppe.benutzer_id != person.id:
        raise KontaktFehler("gruppe_unbekannt")
    return gruppe


# --- vCard ----------------------------------------------------------------- #


def als_vcard(
    kontakte: list[Kontakt], verbundene: set[str] | frozenset[str] = frozenset()
) -> str:
    """vCard 3.0 — die Fassung, die Outlook, Apple und Thunderbird alle lesen.

    ⚠️ **Ein Kontakt aus einem verbundenen Buch geht als Original hinaus.**
    Seine Karte liegt in ``roh``, mit Foto, allen Nummern und allem, was
    nexmail nicht kennt; ein Nachbau aus den Feldern waere die halbe Karte.
    Dieselbe Zusage wie beim Kalender und bei mboxrd. Lokale Kontakte werden
    aus ihren Feldern gebaut — auf ihrer Rohkarte, wenn sie eine haben (aus
    einem Import), sonst frisch; so gehen auch dort Foto und Geburtstag mit.
    """
    zeilen: list[str] = []
    for k in kontakte:
        if k.roh and k.adressbuch_id in verbundene:
            zeilen.extend(z for z in k.roh.replace("\r\n", "\n").split("\n") if z)
            continue
        # ⚠️ Ohne eigene UID keine erfundene: Die Kennung ist beim zweiten
        # Einlesen der Schluessel fuer Kontakte ohne Adresse, und eine, die
        # sich bei jedem Export aendert, legte jeden davon doppelt an.
        karte = vcard.aktualisieren(k.roh or "", felder_der_zeile(k), k.uid, uid_ergaenzen=bool(k.uid))
        zeilen.extend(z for z in karte.replace("\r\n", "\n").split("\n") if z)
    # ⚠️ CRLF ist in RFC 6350 vorgeschrieben. Manche Programme sind nachsichtig,
    # Outlook ist es nicht.
    return "\r\n".join(zeilen) + "\r\n"


def felder_aus_vcard(inhalt: str) -> dict:
    """Alles, was nexmail kennt, aus **einer** Karte — der Leser aus
    ``vcard.lesen``, unter dem Namen, den Abgleich und Import seit Lieferung 1
    benutzen.

    ⚠️ **Eine Karte, nicht eine Datei.** Für eine Datei mit mehreren gibt es
    ``aus_vcard``; hier kommt genau das an, was CardDAV je Adresse liefert.

    ⚠️ **Was nexmail nicht kennt, bleibt in der Karte liegen — und muss
    anderswo aufgehoben werden.** Foto, Social-Profile, ``X-APPLE-…``: Der
    Abgleich speichert die Karte deshalb zusätzlich als ``kontakt.roh``. Wer
    sich auf diesen Rückgabewert allein verlässt, hat beim ersten
    Zurückschreiben die Hälfte des Kontakts gelöscht.
    """
    return vcard.lesen(inhalt)


def aus_vcard(db: Session, person: Benutzer, inhalt: str) -> dict[str, int]:
    """Eine vCard-Datei einlesen. Vorhandene Adressen werden ergänzt, nicht
    verdoppelt.

    ⚠️ **Der Feldleser steht in ``felder_aus_vcard``**, nicht hier. Der
    CardDAV-Abgleich braucht denselben; zwei Kopien liefen auseinander, und die
    eine Seite läse dann ein Feld, das die andere übergeht.
    """
    neu = 0
    ergaenzt = 0
    karte: list[str] = []
    for zeile in entfalten(inhalt):
        oben = zeile.strip().upper()
        if oben == "BEGIN:VCARD":
            karte = []
            continue
        if oben == "END:VCARD":
            stand = _uebernehmen(db, person, felder_aus_vcard("\n".join(karte)), karte)
            neu += stand == "neu"
            ergaenzt += stand == "ergaenzt"
            karte = []
            continue
        karte.append(zeile)

    db.commit()
    logger.info("vCard import: %s new, %s updated.", neu, ergaenzt)
    return {"neu": neu, "ergaenzt": ergaenzt}


def _uebernehmen(
    db: Session, person: Benutzer, felder: dict, karte: list[str] | None = None
) -> str:
    # ⚠️ Die Karte bleibt liegen, wie sie kam: die Rueckfahrkarte, auch beim
    # Import. Was nexmail nicht kennt, waere sonst mit dem Einlesen weg.
    roh = "BEGIN:VCARD\r\n" + "\r\n".join(karte) + "\r\nEND:VCARD\r\n" if karte else ""
    neu = vcard.felder_normieren(felder)
    # Eine kaputte Adresse ist keine; der Rest der Karte ist trotzdem etwas wert.
    neu["adressen"] = [a for a in neu["adressen"] if _ADRESSE.match(a["adresse"])]
    neu["adresse"] = vcard.bevorzugte(neu["adressen"], "adresse")
    adresse = neu["adresse"]
    name, telefon, firma = neu["name"], neu["telefon"], neu["firma"]
    if not (adresse or name or telefon or firma):
        return "uebersprungen"

    if adresse:
        vorhanden = db.execute(
            select(Kontakt).where(Kontakt.benutzer_id == person.id, Kontakt.adresse == adresse)
        ).scalar_one_or_none()
    else:
        vorhanden = _ohne_adresse_wiedererkennen(db, person, felder.get("uid", ""), name, telefon)
    if vorhanden is not None:
        # ⚠️ Ein Eintrag aus einem verbundenen Buch bleibt unangetastet:
        # Hundert Karten einzeln hochzuschieben ist ein eigener Vorgang mit
        # Fortschritt und Abbruch, wie der ICS-Import in einen CalDAV-Kalender.
        if vorhanden.adressbuch_id:
            heim = db.get(Adressbuch, vorhanden.adressbuch_id)
            if heim is not None and heim.art:
                return "uebersprungen"
        # Nur fuellen, was leer ist. Eine Datei aus einem anderen Programm
        # weiss nicht besser, wie jemand heisst, als der eigene Eintrag.
        for schluessel in vcard.FELDER:
            if not getattr(vorhanden, schluessel) and neu.get(schluessel):
                setattr(vorhanden, schluessel, neu[schluessel][: _LAENGE.get(schluessel, 5000)])
        if not vorhanden.name and neu["name"]:
            vorhanden.name = neu["name"][:320]
        for liste in LISTEN:
            if not _json_liste(getattr(vorhanden, liste)) and neu[liste]:
                setattr(vorhanden, liste, json.dumps(neu[liste], ensure_ascii=False))
        if not vorhanden.telefon and telefon:
            vorhanden.telefon = telefon[:120]
        vorhanden.quelle = "hand"
        return "ergaenzt"

    eintrag = Kontakt(
        benutzer_id=person.id,
        uid=felder.get("uid", "")[:255],
        roh=roh,
        quelle="hand",
        adressbuch_id=adressbuecher.lokales(db, person).id,
    )
    felder_anwenden(eintrag, neu)
    db.add(eintrag)
    return "neu"


def _ohne_adresse_wiedererkennen(
    db: Session, person: Benutzer, uid: str, name: str, telefon: str
) -> Kontakt | None:
    """Einen Kontakt ohne Adresse in einer Datei wiederfinden.

    ⚠️ **Ohne Adresse gibt es keinen Schluessel.** Dieselbe Datei zweimal
    einlesen, weil der erste Anlauf abbrach oder weil man es nicht mehr weiss,
    legte sonst jeden solchen Eintrag doppelt an. Dieselbe Regel wie die
    ``Message-ID`` beim mbox-Import. Wiedererkannt wird an der UID der Karte,
    und ohne UID an Name und Nummer zusammen.
    """
    frage = select(Kontakt).where(Kontakt.benutzer_id == person.id)
    if uid:
        return db.scalar(frage.where(Kontakt.uid == uid))
    if not (name or telefon):
        return None
    return db.scalar(
        frage.where(Kontakt.adresse == "", Kontakt.name == name, Kontakt.telefon == telefon)
    )


def felder_nachtragen(db: Session) -> int:
    """Die Felder des Felder-Schritts fuer den Bestand einmal fuellen.

    Bis 0.13.0 kannte eine Zeile einen Namen, eine Nummer, eine Adresse.
    Was ein Kontakt aus einem verbundenen Buch wirklich hat, steht in seiner
    Karte — die wird gelesen, so wie der Abgleich sie beim naechsten Mal laese.
    Ein lokaler Kontakt bekommt seinen Namen geteilt und seine Nummer und
    Adresse als Liste mit einem Eintrag; hat er eine Karte (aus einem Import),
    kommen deren Listen dazu. ⚠️ Nur Zeilen, die noch nichts davon tragen:
    Laeuft es aus einer Sicherung ein zweites Mal, ueberschreibt es nichts.
    """
    verbundene = {b.id for b in db.scalars(select(Adressbuch).where(Adressbuch.art != ""))}
    zahl = 0
    for k in db.scalars(select(Kontakt)).all():
        if k.vorname or k.nachname or _json_liste(k.nummern) or _json_liste(k.adressen):
            continue
        if k.roh and k.adressbuch_id in verbundene:
            felder = vcard.lesen(k.roh)
        else:
            basis = vcard.lesen(k.roh) if k.roh else {}
            felder = {
                **{f: basis.get(f, "") for f in vcard.FELDER},
                "nummern": basis.get("nummern", []),
                "adressen": basis.get("adressen", []),
                "anschriften": basis.get("anschriften", []),
                "firma": k.firma or basis.get("firma", ""),
                "notiz": k.notiz or basis.get("notiz", ""),
            }
            felder["vorname"], felder["nachname"] = vcard.name_teilen(k.name) if k.name else (basis.get("vorname", ""), basis.get("nachname", ""))
            felder["nummern"] = vcard.einzel_einmischen(felder["nummern"], "nummer", k.telefon, vcard.nummer_kern)
            felder["adressen"] = vcard.einzel_einmischen(felder["adressen"], "adresse", k.adresse, str.lower)
        neu = vcard.felder_normieren(felder)
        # Ein Firmen-Kontakt ohne Vor- und Nachname behaelt seinen Anzeigenamen.
        neu["name"] = neu["name"] or felder.get("name") or k.name
        # Die Adresse der Zeile ist der Schluessel und bleibt, was sie war.
        neu["adresse"] = k.adresse
        felder_anwenden(k, neu)
        zahl += 1
    db.commit()
    if zahl:
        logger.info("Filled in the extended fields for %s contact(s).", zahl)
    return zahl


__all__ = [
    "KontaktFehler",
    "aendern",
    "adresse_pruefen",
    "als_vcard",
    "anlegen",
    "aus_vcard",
    "einsammeln",
    "entfernen",
    "felder_anwenden",
    "felder_aus_vcard",
    "felder_der_zeile",
    "felder_nachtragen",
    "felder_pruefen",
    "gesammelte_entfernen",
    "gruppe_anlegen",
    "gruppe_entfernen",
    "gruppe_umbenennen",
    "gruppen",
    "meine",
    "mitglieder_setzen",
    "mitgliedschaften_loesen",
    "verschieben",
    "vorschlagen",
]
