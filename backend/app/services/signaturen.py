"""Signaturen — der Textbaustein unter der eigenen Post.

⚠️ **Je Postfach, nicht je Benutzer.** Wer geschäftlich und privat aus
derselben Anwendung schreibt, will nicht die Firmenanschrift unter der Mail an
die Familie. Eine Signatur ohne Postfach gilt als Rückfallebene für alle
Postfächer, die keine eigene haben.

⚠️ **Dieselbe Bereinigung wie beim Senden.** Eine Signatur ist HTML, das der
Betreiber selbst schreibt — aber sie geht denselben Weg hinaus wie eine Mail,
und wer sie aus einem alten Client hineinkopiert, bringt fremde Auszeichnung
mit.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Signatur
from . import bereinigen

logger = logging.getLogger("nexmail.signaturen")


class SignaturFehler(RuntimeError):
    """Etwas, das der Betreiber lesen soll."""


def meine(db: Session, person: Benutzer) -> list[Signatur]:
    return list(
        db.execute(
            select(Signatur)
            .where(Signatur.benutzer_id == person.id)
            .order_by(Signatur.konto_id, Signatur.name)
        )
        .scalars()
        .all()
    )


def fuer_konto(db: Session, person: Benutzer, konto_id: str) -> Signatur | None:
    """Welche Signatur eine neue Mail aus diesem Postfach bekommt.

    Zuerst die des Postfachs, dann die allgemeine. Innerhalb beider zählt
    ``standard`` — es kann mehrere geben, aber nur eine wird von selbst
    eingesetzt.
    """
    alle = [s for s in meine(db, person) if s.standard]
    eigene = [s for s in alle if s.konto_id == konto_id]
    if eigene:
        return eigene[0]
    allgemein = [s for s in alle if not s.konto_id]
    return allgemein[0] if allgemein else None


def anlegen(
    db: Session,
    person: Benutzer,
    name: str,
    html: str,
    konto_id: str = "",
    standard: bool = False,
) -> Signatur:
    if not name.strip():
        raise SignaturFehler("Die Signatur braucht einen Namen.")

    eintrag = Signatur(
        benutzer_id=person.id,
        konto_id=konto_id,
        name=name.strip(),
        html=bereinigen.fuer_versand(html),
        standard=standard,
    )
    db.add(eintrag)
    db.flush()
    if standard:
        _nur_eine_standard(db, person, eintrag)
    db.commit()
    return eintrag


def aendern(db: Session, person: Benutzer, signatur_id: int, **felder) -> Signatur:
    eintrag = _meine(db, person, signatur_id)
    if "name" in felder and felder["name"] is not None:
        if not str(felder["name"]).strip():
            raise SignaturFehler("Die Signatur braucht einen Namen.")
        eintrag.name = str(felder["name"]).strip()
    if "html" in felder and felder["html"] is not None:
        eintrag.html = bereinigen.fuer_versand(str(felder["html"]))
    if "konto_id" in felder and felder["konto_id"] is not None:
        eintrag.konto_id = str(felder["konto_id"])
    if felder.get("standard") is not None:
        eintrag.standard = bool(felder["standard"])
        if eintrag.standard:
            _nur_eine_standard(db, person, eintrag)
    db.commit()
    return eintrag


def entfernen(db: Session, person: Benutzer, signatur_id: int) -> None:
    db.delete(_meine(db, person, signatur_id))
    db.commit()


def _meine(db: Session, person: Benutzer, signatur_id: int) -> Signatur:
    eintrag = db.get(Signatur, signatur_id)
    if eintrag is None or eintrag.benutzer_id != person.id:
        raise SignaturFehler("Diese Signatur gibt es nicht.")
    return eintrag


def _nur_eine_standard(db: Session, person: Benutzer, gewaehlt: Signatur) -> None:
    """⚠️ Zwei Vorgaben für dasselbe Postfach heißt: Es entscheidet der Zufall.

    Welche gewinnt, hinge an der Reihenfolge der Zeilen — und die ändert sich,
    ohne dass jemand etwas anfasst.
    """
    for andere in meine(db, person):
        if andere.id != gewaehlt.id and andere.konto_id == gewaehlt.konto_id:
            andere.standard = False


__all__ = ["SignaturFehler", "aendern", "anlegen", "entfernen", "fuer_konto", "meine"]
