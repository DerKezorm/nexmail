"""Wer darf ohne Nachfrage Bilder schicken.

Zwei Wege, und beide gehoeren dem Benutzer, nicht dem Geraet:

* **Je Absender** — „Von diesem Absender immer laden", wie in Thunderbird.
* **Ueberall** — der Schalter „Bilder immer anzeigen" unter Darstellung.

⚠️ **Verglichen wird klein.** Mailadressen sind im lokalen Teil zwar
theoretisch schreibungsabhaengig, in der Praxis nirgends — und wer „Post@…"
freigibt und bei „post@…" wieder gefragt wird, haelt die Einstellung fuer
kaputt.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Bildfreigabe


def normalisieren(adresse: str) -> str:
    return adresse.strip().lower()


def darf_laden(db: Session, benutzer: Benutzer, absender: str) -> bool:
    """Sollen die Bilder dieser Mail ohne Klick erscheinen?"""
    if benutzer.bilder_immer_laden:
        return True
    gesucht = normalisieren(absender)
    if not gesucht:
        return False
    return (
        db.execute(
            select(Bildfreigabe.id).where(
                Bildfreigabe.benutzer_id == benutzer.id,
                Bildfreigabe.adresse == gesucht,
            )
        ).first()
        is not None
    )


def liste(db: Session, benutzer: Benutzer) -> list[Bildfreigabe]:
    return list(
        db.scalars(
            select(Bildfreigabe)
            .where(Bildfreigabe.benutzer_id == benutzer.id)
            .order_by(Bildfreigabe.adresse)
        )
    )


def merken(db: Session, benutzer: Benutzer, absender: str) -> None:
    """Einen Absender freigeben.

    ⚠️ **Zweimal freigeben ist kein Fehler.** Es ist ein Verklicken, und eine
    Fehlermeldung dafuer waere Schikane — dieselbe Haltung wie bei „zu Aufgabe
    machen".
    """
    gesucht = normalisieren(absender)
    if not gesucht:
        return
    schon = db.scalars(
        select(Bildfreigabe).where(
            Bildfreigabe.benutzer_id == benutzer.id, Bildfreigabe.adresse == gesucht
        )
    ).first()
    if schon is not None:
        return
    db.add(Bildfreigabe(benutzer_id=benutzer.id, adresse=gesucht))
    db.commit()


def vergessen(db: Session, benutzer: Benutzer, absender: str) -> None:
    gesucht = normalisieren(absender)
    eintrag = db.scalars(
        select(Bildfreigabe).where(
            Bildfreigabe.benutzer_id == benutzer.id, Bildfreigabe.adresse == gesucht
        )
    ).first()
    if eintrag is None:
        return
    db.delete(eintrag)
    db.commit()
