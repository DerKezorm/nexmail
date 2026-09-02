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

from ..models import Benutzer, Kontakt, Kontaktgruppe, KontaktgruppeMitglied, Nachricht, Ordner

logger = logging.getLogger("nexmail.kontakte")


class KontaktFehler(RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


_ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def adresse_pruefen(adresse: str) -> str:
    sauber = adresse.strip().lower()
    if not _ADRESSE.match(sauber):
        raise KontaktFehler(f"„{sauber}“ sieht nicht wie eine E-Mail-Adresse aus.")
    return sauber


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
    adresse: str,
    name: str = "",
    firma: str = "",
    telefon: str = "",
    notiz: str = "",
    quelle: str = "hand",
) -> Kontakt:
    sauber = adresse_pruefen(adresse)
    vorhanden = db.execute(
        select(Kontakt).where(Kontakt.benutzer_id == person.id, Kontakt.adresse == sauber)
    ).scalar_one_or_none()
    if vorhanden is not None:
        raise KontaktFehler(f"„{sauber}“ steht schon im Adressbuch.")

    eintrag = Kontakt(
        benutzer_id=person.id,
        adresse=sauber,
        name=name.strip(),
        firma=firma.strip(),
        telefon=telefon.strip(),
        notiz=notiz,
        quelle=quelle,
    )
    db.add(eintrag)
    db.commit()
    return eintrag


def aendern(db: Session, person: Benutzer, kontakt_id: int, **felder) -> Kontakt:
    eintrag = _meiner(db, person, kontakt_id)
    if "adresse" in felder and felder["adresse"]:
        neue = adresse_pruefen(felder.pop("adresse"))
        if neue != eintrag.adresse:
            doppelt = db.execute(
                select(Kontakt).where(
                    Kontakt.benutzer_id == person.id,
                    Kontakt.adresse == neue,
                    Kontakt.id != eintrag.id,
                )
            ).scalar_one_or_none()
            if doppelt is not None:
                raise KontaktFehler(f"„{neue}“ steht schon bei einem anderen Eintrag.")
            eintrag.adresse = neue
    for schluessel in ("name", "firma", "telefon", "notiz"):
        if schluessel in felder and felder[schluessel] is not None:
            setattr(eintrag, schluessel, felder[schluessel])
    # Wer einen Eintrag anfasst, hat ihn gepflegt - er ist nicht mehr
    # Aufgeschnapptes und darf beim Aufraeumen nicht mitgehen.
    eintrag.quelle = "hand"
    db.commit()
    return eintrag


def entfernen(db: Session, person: Benutzer, kontakt_id: int) -> None:
    eintrag = _meiner(db, person, kontakt_id)
    # ⚠️ Die Mitgliedschaften gehen mit. Eine Zuordnung auf einen geloeschten
    # Kontakt waere eine Leiche: unsichtbar in der Oberflaeche, aber die
    # Mitgliederzahl der Gruppe zaehlte sie weiter mit.
    db.query(KontaktgruppeMitglied).filter(
        KontaktgruppeMitglied.benutzer_id == person.id,
        KontaktgruppeMitglied.kontakt_id == eintrag.id,
    ).delete()
    db.delete(eintrag)
    db.commit()


def gesammelte_entfernen(db: Session, person: Benutzer) -> int:
    """Alles Aufgeschnappte in einem Zug loswerden."""
    # Auch hier: erst die Mitgliedschaften der betroffenen Kontakte, sonst
    # bleiben sie als Leichen in den Gruppen stehen.
    betroffene = select(Kontakt.id).where(
        Kontakt.benutzer_id == person.id, Kontakt.quelle == "gesammelt"
    )
    db.query(KontaktgruppeMitglied).filter(
        KontaktgruppeMitglied.benutzer_id == person.id,
        KontaktgruppeMitglied.kontakt_id.in_(betroffene),
    ).delete(synchronize_session=False)
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
        raise KontaktFehler("Diesen Eintrag gibt es nicht.")
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

    bekannt = {
        k.adresse: k
        for k in db.execute(select(Kontakt).where(Kontakt.benutzer_id == person.id))
        .scalars()
        .all()
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
            "adressen": [a for _, a in mitglieder.get(g.id, [])],
        }
        for g in zeilen
    ]


def _gruppenname_pruefen(
    db: Session, person: Benutzer, name: str, ausser_id: int | None = None
) -> str:
    sauber = name.strip()
    if not sauber:
        raise KontaktFehler("Die Gruppe braucht einen Namen.")
    # Gross/klein trennt keine Gruppen - dieselbe Regel wie bei den
    # Postfach-Schlagworten. Verglichen wird klein, behalten die Schreibweise.
    frage = select(Kontaktgruppe).where(
        Kontaktgruppe.benutzer_id == person.id,
        func.lower(Kontaktgruppe.name) == sauber.lower(),
    )
    if ausser_id is not None:
        frage = frage.where(Kontaktgruppe.id != ausser_id)
    if db.execute(frage).scalar_one_or_none() is not None:
        raise KontaktFehler(f"„{sauber}“ gibt es schon als Gruppe.")
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
        raise KontaktFehler("Mindestens ein gewählter Eintrag steht nicht in deinem Adressbuch.")

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
        raise KontaktFehler("Diese Gruppe gibt es nicht.")
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


def als_vcard(kontakte: list[Kontakt]) -> str:
    """vCard 3.0 — die Fassung, die Outlook, Apple und Thunderbird alle lesen."""
    zeilen: list[str] = []
    for k in kontakte:
        zeilen.append("BEGIN:VCARD")
        zeilen.append("VERSION:3.0")
        zeilen.append(f"FN:{_vcard_maskieren(k.name or k.adresse)}")
        zeilen.append(f"N:{_vcard_maskieren(k.name or k.adresse)};;;;")
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


def aus_vcard(db: Session, person: Benutzer, inhalt: str) -> dict[str, int]:
    """vCard einlesen. Vorhandene Adressen werden ergänzt, nicht verdoppelt.

    ⚠️ **Gefaltete Zeilen zuerst zusammensetzen.** vCard bricht lange Werte
    nach 75 Zeichen um und rückt die Fortsetzung ein — wer Zeile für Zeile
    liest, bekommt abgeschnittene Namen und verliert lange Notizen.
    """
    zeilen: list[str] = []
    for roh in inhalt.replace("\r\n", "\n").split("\n"):
        if roh[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += roh[1:]
        else:
            zeilen.append(roh)

    neu = 0
    ergaenzt = 0
    aktuell: dict[str, str] = {}
    for zeile in zeilen:
        oben = zeile.strip().upper()
        if oben == "BEGIN:VCARD":
            aktuell = {}
            continue
        if oben == "END:VCARD":
            stand = _uebernehmen(db, person, aktuell)
            neu += stand == "neu"
            ergaenzt += stand == "ergaenzt"
            aktuell = {}
            continue
        if ":" not in zeile:
            continue
        kopf, roh_wert = zeile.split(":", 1)
        # Parameter abtrennen: EMAIL;TYPE=INTERNET -> EMAIL
        feld = kopf.split(";")[0].strip().upper()
        roh_wert = roh_wert.strip()
        if feld == "EMAIL" and "adresse" not in aktuell:
            aktuell["adresse"] = _entmaskieren(roh_wert)
        elif feld == "FN":
            aktuell["name"] = _entmaskieren(roh_wert)
        elif feld == "N" and "name" not in aktuell:
            # N ist Nachname;Vorname;… - hier zusammengesetzt als „Vorname
            # Nachname", weil FN gefehlt hat.
            teile = [t for t in _felder_trennen(roh_wert) if t]
            aktuell["name"] = " ".join(reversed(teile[:2])).strip()
        elif feld == "ORG":
            # ORG ist Firma;Abteilung - nur die Firma wird gebraucht.
            aktuell["firma"] = _felder_trennen(roh_wert)[0]
        elif feld == "TEL" and "telefon" not in aktuell:
            aktuell["telefon"] = _entmaskieren(roh_wert)
        elif feld == "NOTE":
            aktuell["notiz"] = _entmaskieren(roh_wert)

    db.commit()
    logger.info("vCard import: %s new, %s updated.", neu, ergaenzt)
    return {"neu": neu, "ergaenzt": ergaenzt}


def _uebernehmen(db: Session, person: Benutzer, felder: dict[str, str]) -> str:
    adresse = felder.get("adresse", "").strip().lower()
    if not _ADRESSE.match(adresse):
        return "uebersprungen"

    vorhanden = db.execute(
        select(Kontakt).where(Kontakt.benutzer_id == person.id, Kontakt.adresse == adresse)
    ).scalar_one_or_none()
    if vorhanden is not None:
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
            name=felder.get("name", ""),
            firma=felder.get("firma", ""),
            telefon=felder.get("telefon", ""),
            notiz=felder.get("notiz", ""),
            quelle="hand",
        )
    )
    return "neu"


__all__ = [
    "KontaktFehler",
    "aendern",
    "adresse_pruefen",
    "als_vcard",
    "anlegen",
    "aus_vcard",
    "einsammeln",
    "entfernen",
    "gesammelte_entfernen",
    "gruppe_anlegen",
    "gruppe_entfernen",
    "gruppe_umbenennen",
    "gruppen",
    "meine",
    "mitglieder_setzen",
    "vorschlagen",
]
