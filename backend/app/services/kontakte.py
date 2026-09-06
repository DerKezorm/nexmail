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
from . import adressbuecher

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


# --- Lesen ---------------------------------------------------------------- #


def meine(db: Session, person: Benutzer, suche: str = "") -> list[Kontakt]:
    frage = select(Kontakt).where(Kontakt.benutzer_id == person.id)
    if suche.strip():
        muster = f"%{suche.strip().lower()}%"
        frage = frage.where(
            or_(
                func.lower(Kontakt.name).like(muster),
                func.lower(Kontakt.adresse).like(muster),
                func.lower(Kontakt.firma).like(muster),
                # Ein Kontakt ohne Adresse ist oft nur eine Nummer mit Namen.
                Kontakt.telefon.like(muster),
            )
        )
    return list(db.execute(frage.order_by(Kontakt.name, Kontakt.adresse)).scalars().all())


def vorschlagen(db: Session, person: Benutzer, anfang: str, grenze: int = 8) -> list[Kontakt]:
    """Vorschläge beim Tippen einer Adresse.

    ⚠️ **Sortiert nach Häufigkeit, nicht alphabetisch.** Wer „ma" tippt, meint
    fast immer den, dem er ständig schreibt — nicht den, der zufällig vorne im
    Alphabet steht.
    """
    kern = anfang.strip().lower()
    if not kern:
        return []
    muster = f"%{kern}%"
    frage = (
        select(Kontakt)
        .where(
            Kontakt.benutzer_id == person.id,
            # ⚠️ Nur, wem man schreiben kann. Ein Vorschlag ohne Adresse
            # setzte ein leeres Feld ein.
            Kontakt.adresse != "",
            or_(func.lower(Kontakt.name).like(muster), func.lower(Kontakt.adresse).like(muster)),
        )
        .order_by(Kontakt.verwendet.desc(), Kontakt.name, Kontakt.adresse)
        .limit(grenze)
    )
    return list(db.execute(frage).scalars().all())


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
) -> Kontakt:
    sauber = _adresse_oder_leer(adresse)
    _etwas_muss_da_sein(sauber, name, telefon, firma)
    if sauber:
        vorhanden = db.execute(
            select(Kontakt).where(Kontakt.benutzer_id == person.id, Kontakt.adresse == sauber)
        ).scalar_one_or_none()
        if vorhanden is not None:
            raise KontaktFehler("adresse_schon_da", adresse=sauber)

    eintrag = Kontakt(
        benutzer_id=person.id,
        adresse=sauber,
        name=name.strip(),
        firma=firma.strip(),
        telefon=telefon.strip(),
        notiz=notiz,
        quelle=quelle,
        adressbuch_id=adressbuecher.lokales(db, person).id,
    )
    db.add(eintrag)
    db.commit()
    return eintrag


def _nur_lesen(db: Session, eintrag: Kontakt) -> None:
    """⚠️ **Lieferung 1 liest nur.** Ein Kontakt aus einem verbundenen Buch wird
    hier weder geändert noch gelöscht: Geändert würde er beim nächsten Abgleich
    überschrieben, gelöscht käme er wieder, und beides sähe aus wie ein Fehler.
    Bearbeiten und Löschen gehen beim Anbieter; hierher kommt es mit Lieferung
    2, mit ``If-Match``. Bis dahin ist das die Zusage der Beta: Nichts, was in
    nexmail passiert, erreicht iCloud oder Google."""
    if not eintrag.adressbuch_id:
        return
    buch = db.get(Adressbuch, eintrag.adressbuch_id)
    if buch is not None and buch.art:
        raise KontaktFehler("kontakt_nur_lesen")


def aendern(db: Session, person: Benutzer, kontakt_id: int, **felder) -> Kontakt:
    eintrag = _meiner(db, person, kontakt_id)
    _nur_lesen(db, eintrag)
    # ⚠️ Erst pruefen, dann anfassen. Wer die Zeile schon geaendert hat, wenn
    # die Pruefung wirft, laesst sie schmutzig in der Sitzung liegen, und der
    # naechste ``commit`` eines anderen schreibt sie mit.
    neu = {
        schluessel: felder[schluessel]
        if schluessel in felder and felder[schluessel] is not None
        else getattr(eintrag, schluessel)
        for schluessel in ("name", "firma", "telefon", "notiz")
    }
    # Eine leere Adresse heisst „keine mehr", eine fehlende „unveraendert".
    neue_adresse = eintrag.adresse
    if "adresse" in felder and felder["adresse"] is not None:
        neue_adresse = _adresse_oder_leer(felder["adresse"])
        if neue_adresse and neue_adresse != eintrag.adresse:
            doppelt = db.execute(
                select(Kontakt).where(
                    Kontakt.benutzer_id == person.id,
                    Kontakt.adresse == neue_adresse,
                    Kontakt.id != eintrag.id,
                )
            ).scalar_one_or_none()
            if doppelt is not None:
                raise KontaktFehler("adresse_bei_anderem", adresse=neue_adresse)
    _etwas_muss_da_sein(neue_adresse, neu["name"], neu["telefon"], neu["firma"])

    eintrag.adresse = neue_adresse
    for schluessel, wert in neu.items():
        setattr(eintrag, schluessel, wert)
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
    eintrag = _meiner(db, person, kontakt_id)
    _nur_lesen(db, eintrag)
    mitgliedschaften_loesen(db, [eintrag.id])
    db.delete(eintrag)
    db.commit()


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
                    vorhanden.name = name
                continue
            eintrag = Kontakt(
                benutzer_id=person.id,
                adresse=adresse,
                name=name,
                quelle="gesammelt",
                verwendet=1,
                adressbuch_id=lokal_id,
            )
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


def _vcard_maskieren(wert: str) -> str:
    """⚠️ Komma, Semikolon und Zeilenumbruch sind in vCard **Trennzeichen**.

    Ein Name wie „Müller, Gertrud" zerlegt die Datei sonst in Felder, die
    niemand mehr zusammensetzt.
    """
    return (
        wert.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def als_vcard(
    kontakte: list[Kontakt], verbundene: set[str] | frozenset[str] = frozenset()
) -> str:
    """vCard 3.0 — die Fassung, die Outlook, Apple und Thunderbird alle lesen.

    ⚠️ **Ein Kontakt aus einem verbundenen Buch geht als Original hinaus.**
    Seine Karte liegt in ``roh``, mit Foto, allen Nummern und allem, was
    nexmail nicht kennt; ein Nachbau aus fuenf Feldern waere die halbe Karte.
    Dieselbe Zusage wie beim Kalender und bei mboxrd. Lokale Kontakte werden
    nachgebaut: Ihre Felder duerfen hier geaendert sein, und ``roh`` waere
    dann veraltet. Das zeilenweise Nachziehen ist Lieferung 2.
    """
    zeilen: list[str] = []
    for k in kontakte:
        if k.roh and k.adressbuch_id in verbundene:
            zeilen.extend(z for z in k.roh.replace("\r\n", "\n").split("\n") if z)
            continue
        # ``FN`` ist Pflicht: der Name, sonst das Naechste, was den Eintrag
        # benennt. ⚠️ Die Firma vor Adresse und Nummer: Ein Firmen-Kontakt
        # von Apple traegt den Namen in ``ORG`` und sonst nichts; als Nummer
        # betitelt findet ihn niemand wieder.
        anzeige = k.name or k.firma or k.adresse or k.telefon
        zeilen.append("BEGIN:VCARD")
        zeilen.append("VERSION:3.0")
        if k.uid:
            # Die Kennung der Karte, damit ein zweites Einlesen sie
            # wiedererkennt; ohne Adresse ist sie der einzige Schluessel.
            zeilen.append(f"UID:{_vcard_maskieren(k.uid)}")
        zeilen.append(f"FN:{_vcard_maskieren(anzeige)}")
        zeilen.append(f"N:{_vcard_maskieren(anzeige)};;;;")
        if k.adresse:
            zeilen.append(f"EMAIL;TYPE=INTERNET:{_vcard_maskieren(k.adresse)}")
        if k.firma:
            zeilen.append(f"ORG:{_vcard_maskieren(k.firma)}")
        if k.telefon:
            zeilen.append(f"TEL:{_vcard_maskieren(k.telefon)}")
        if k.notiz:
            zeilen.append(f"NOTE:{_vcard_maskieren(k.notiz)}")
        zeilen.append("END:VCARD")
    # ⚠️ CRLF ist in RFC 6350 vorgeschrieben. Manche Programme sind nachsichtig,
    # Outlook ist es nicht.
    return "\r\n".join(zeilen) + "\r\n"


def _entmaskieren(wert: str) -> str:
    ergebnis = []
    schraege = False
    for zeichen in wert:
        if schraege:
            ergebnis.append({"n": "\n", "N": "\n"}.get(zeichen, zeichen))
            schraege = False
        elif zeichen == "\\":
            schraege = True
        else:
            ergebnis.append(zeichen)
    return "".join(ergebnis)


def _felder_trennen(roh: str) -> list[str]:
    r"""Einen strukturierten vCard-Wert an den **unmaskierten** Semikola teilen.

    ⚠️ **Die Reihenfolge ist der ganze Punkt.** ``ORG`` und ``N`` bestehen aus
    mehreren Teilen, getrennt durch ``;`` — aber ein Semikolon *im* Wert steht
    als ``\;`` da. Wer zuerst entmaskiert und dann trennt, zerschneidet genau
    das Zeichen, das die Maskierung schützen sollte: Aus „Meier; Söhne" wird
    „Meier". Beim Rundlauf-Test aufgefallen, nicht beim Nachdenken.
    """
    teile: list[str] = []
    aktuell: list[str] = []
    schraege = False
    for zeichen in roh:
        if schraege:
            aktuell.append("\n" if zeichen in ("n", "N") else zeichen)
            schraege = False
        elif zeichen == "\\":
            schraege = True
        elif zeichen == ";":
            teile.append("".join(aktuell))
            aktuell = []
        else:
            aktuell.append(zeichen)
    teile.append("".join(aktuell))
    return teile


def entfalten(inhalt: str) -> list[str]:
    """Gefaltete Zeilen zusammensetzen.

    ⚠️ **Zuerst, immer.** vCard bricht lange Werte nach 75 Zeichen um und
    rückt die Fortsetzung ein — wer Zeile für Zeile liest, bekommt
    abgeschnittene Namen und verliert lange Notizen.
    """
    zeilen: list[str] = []
    for roh in inhalt.replace("\r\n", "\n").split("\n"):
        if roh[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += roh[1:]
        else:
            zeilen.append(roh)
    return zeilen


_APPLE_MARKE = re.compile(r"^_\$!<(.+)>!\$_$")


def kontaktdaten_aus_vcard(inhalt: str) -> dict[str, list[dict[str, str]]]:
    """Alle Nummern und Adressen einer Karte, jede mit Typen und Beschriftung.

    ⚠️ **Das Modell kennt eine Nummer, die Karte viele.** Bis die Felder
    mehrere tragen (der naechste Schritt, mit Maske vorher), zeigt die
    Oberflaeche die uebrigen aus der Rohkarte, nur lesend. Ein Kontakt mit
    Handy und Festnetz, von dem nur eines zu sehen war, sah aus wie halb
    geholt; am 05.09.2026 genau so aus der Pruefinstanz gemeldet.

    Typen kommen als ``TEL;type=CELL;type=pref`` (vCard 3), ``TEL;TYPE=cell``
    (vCard 4) oder ``TEL;CELL`` (vCard 2.1). Apple beschriftet ueber Gruppen:
    ``item1.TEL`` gehoert zu ``item1.X-ABLabel``; eigene Beschriftungen
    stehen dort im Klartext, Apples eigene als ``_$!<Mobile>!$_``.
    """
    nummern: list[dict[str, str]] = []
    adressen: list[dict[str, str]] = []
    beschriftungen: dict[str, str] = {}
    for zeile in entfalten(inhalt):
        if ":" not in zeile:
            continue
        kopf, wert = zeile.split(":", 1)
        teile = kopf.split(";")
        name = teile[0].strip()
        gruppe = ""
        if "." in name:
            gruppe, name = name.rsplit(".", 1)
        name = name.upper()
        typen: list[str] = []
        for parameter in teile[1:]:
            schluessel, _, werte = parameter.partition("=")
            if not werte:
                typen.append(schluessel.strip().lower())
            elif schluessel.strip().upper() == "TYPE":
                typen.extend(t.strip().lower() for t in werte.split(","))
        wert = wert.strip()
        if name == "X-ABLABEL" and gruppe:
            marke = _APPLE_MARKE.match(wert)
            beschriftungen[gruppe] = marke.group(1) if marke else _entmaskieren(wert)
        elif name == "TEL" and wert:
            nummern.append(
                {"gruppe": gruppe, "typen": ",".join(typen), "nummer": _entmaskieren(wert)}
            )
        elif name == "EMAIL" and wert:
            adressen.append(
                {"gruppe": gruppe, "typen": ",".join(typen), "adresse": _entmaskieren(wert).lower()}
            )
    for eintrag in nummern + adressen:
        eintrag["beschriftung"] = beschriftungen.get(eintrag.pop("gruppe"), "")
    return {"nummern": nummern, "adressen": adressen}


def _bevorzugt(eintraege: list[dict[str, str]], feld: str, lieber: tuple[str, ...]) -> str:
    """Welche von mehreren das eine Feld bekommt.

    ⚠️ Erst die Sorte, die der Aufrufer lieber hat (bei Nummern das Handy),
    dann die vom Anbieter als ``pref`` markierte, sonst die erste. Vorher
    gewann die erste Zeile der Karte, und bei Apple steht dort gern das
    Festnetz: Ein Kontakt mit Handy und Festnetz zeigte nur das Festnetz.
    """
    if not eintraege:
        return ""
    for sorte in (lieber, ("pref",)):
        for eintrag in eintraege:
            if any(t in sorte for t in eintrag["typen"].split(",")):
                return eintrag[feld]
    return eintraege[0][feld]


def felder_aus_vcard(inhalt: str) -> dict[str, str]:
    """Die acht Felder, die nexmail kennt, aus **einer** Karte.

    ⚠️ **Eine Karte, nicht eine Datei.** Für eine Datei mit mehreren gibt es
    ``aus_vcard``; hier kommt genau das an, was CardDAV je Adresse liefert.

    ⚠️ **Was nexmail nicht kennt, bleibt hier liegen — und muss anderswo
    aufgehoben werden.** Foto, Geburtstag, weitere Anschriften, ``X-APPLE-…``:
    Diese Funktion wirft sie weg, deshalb speichert der Abgleich die Karte
    zusätzlich als ``kontakt.roh``. Wer sich auf diesen Rückgabewert allein
    verlässt, hat beim ersten Zurückschreiben die Hälfte des Kontakts
    gelöscht.
    """
    felder: dict[str, str] = {}
    for zeile in entfalten(inhalt):
        oben = zeile.strip().upper()
        if oben in ("BEGIN:VCARD", "END:VCARD") or ":" not in zeile:
            continue
        kopf, roh_wert = zeile.split(":", 1)
        # Parameter abtrennen: EMAIL;TYPE=INTERNET -> EMAIL
        feld = kopf.split(";")[0].strip().upper()
        # ⚠️ **Apple gruppiert beschriftete Zeilen:** ``item1.TEL`` gehoert
        # zu ``item1.X-ABLabel:Mutter``. Der Name der Eigenschaft steht
        # hinter dem Punkt; wer die Gruppe mitliest, findet weder Nummer noch
        # Adresse. Am 05.09.2026 an einem echten iCloud-Buch aufgefallen.
        if "." in feld:
            feld = feld.rsplit(".", 1)[1]
        roh_wert = roh_wert.strip()
        if feld == "FN" and roh_wert:
            # ⚠️ **Apple schreibt ``FN:`` leer und den Namen nur in ``N``.**
            # Am 05.09.2026 an 185 echten iCloud-Karten gesehen: ``FN:`` ohne
            # Wert, dahinter ``N:Nachname;Vorname;;;``. Ein leeres FN darf
            # weder den Namen setzen noch das N danach sperren; vorher kamen
            # 149 von 185 Karten ohne Namen an.
            felder["name"] = _entmaskieren(roh_wert)
        elif feld == "N" and "name" not in felder:
            # N ist Nachname;Vorname;Zusatz;Anrede;Titel, nach Stellung, nicht
            # nach Fuellung: ``;Vorname;;;`` ist ein Vorname ohne Nachnamen.
            # Zusammengesetzt als „Vorname Nachname", weil FN fehlt oder leer
            # ist. Apple laesst Leerzeichen am Ende der Teile stehen.
            teile = [t.strip() for t in _felder_trennen(roh_wert)] + ["", ""]
            felder["name"] = " ".join(t for t in (teile[1], teile[0]) if t)
        elif feld == "ORG":
            # ORG ist Firma;Abteilung - nur die Firma wird gebraucht.
            felder["firma"] = _felder_trennen(roh_wert)[0]
        elif feld == "NOTE":
            felder["notiz"] = _entmaskieren(roh_wert)
        elif feld == "UID" and "uid" not in felder:
            felder["uid"] = roh_wert
    # Nummern und Adressen kommen aus dem Leser, der alle kennt, samt Typen;
    # das eine Feld bekommt die Handynummer, sonst die markierte, sonst die erste.
    daten = kontaktdaten_aus_vcard(inhalt)
    telefon = _bevorzugt(daten["nummern"], "nummer", ("cell", "iphone", "mobile"))
    if telefon:
        felder["telefon"] = telefon
    adresse = _bevorzugt(daten["adressen"], "adresse", ("pref",))
    if adresse:
        felder["adresse"] = adresse
    return felder


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
    db: Session, person: Benutzer, felder: dict[str, str], karte: list[str] | None = None
) -> str:
    # ⚠️ Die Karte bleibt liegen, wie sie kam: die Rueckfahrkarte, auch beim
    # Import. Was nexmail nicht kennt, waere sonst mit dem Einlesen weg.
    roh = "BEGIN:VCARD\r\n" + "\r\n".join(karte) + "\r\nEND:VCARD\r\n" if karte else ""
    adresse = felder.get("adresse", "").strip().lower()
    if adresse and not _ADRESSE.match(adresse):
        # Eine kaputte Adresse ist keine; der Rest der Karte ist trotzdem
        # etwas wert.
        adresse = ""
    name = felder.get("name", "").strip()
    telefon = felder.get("telefon", "").strip()
    firma = felder.get("firma", "").strip()
    if not (adresse or name or telefon or firma):
        return "uebersprungen"

    if adresse:
        vorhanden = db.execute(
            select(Kontakt).where(Kontakt.benutzer_id == person.id, Kontakt.adresse == adresse)
        ).scalar_one_or_none()
    else:
        vorhanden = _ohne_adresse_wiedererkennen(db, person, felder.get("uid", ""), name, telefon)
    if vorhanden is not None:
        # ⚠️ Ein Eintrag aus einem verbundenen Buch bleibt unangetastet: Was
        # hier ergaenzt wuerde, ueberschriebe der naechste Abgleich, ohne dass
        # es jemand saehe. Lieferung 1 liest nur.
        if vorhanden.adressbuch_id:
            heim = db.get(Adressbuch, vorhanden.adressbuch_id)
            if heim is not None and heim.art:
                return "uebersprungen"
        # Nur fuellen, was leer ist. Eine Datei aus einem anderen Programm
        # weiss nicht besser, wie jemand heisst, als der eigene Eintrag.
        for schluessel in ("name", "firma", "telefon", "notiz"):
            if not getattr(vorhanden, schluessel) and felder.get(schluessel):
                setattr(vorhanden, schluessel, felder[schluessel])
        vorhanden.quelle = "hand"
        return "ergaenzt"

    db.add(
        Kontakt(
            benutzer_id=person.id,
            adresse=adresse,
            name=name,
            firma=firma,
            telefon=telefon,
            notiz=felder.get("notiz", ""),
            uid=felder.get("uid", "")[:255],
            roh=roh,
            quelle="hand",
            adressbuch_id=adressbuecher.lokales(db, person).id,
        )
    )
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


__all__ = [
    "KontaktFehler",
    "aendern",
    "adresse_pruefen",
    "als_vcard",
    "anlegen",
    "aus_vcard",
    "einsammeln",
    "entfernen",
    "felder_aus_vcard",
    "gesammelte_entfernen",
    "gruppe_anlegen",
    "gruppe_entfernen",
    "gruppe_umbenennen",
    "gruppen",
    "meine",
    "mitglieder_setzen",
    "mitgliedschaften_loesen",
    "vorschlagen",
]
