"""API-Schluessel: anlegen, pruefen, und der Riegel des Betreibers davor.

⚠️ **Ab Werk zu, wie der KI-Riegel.** Ein Schluessel ist ein Weg nach
draussen: Betreff und Absender verlassen nexmail und stehen danach auf einem
Dashboard, das der Betreiber nicht kennt. Ob es diesen Weg in seiner
Installation gibt, entscheidet er, nicht jeder Benutzer fuer sich.

⚠️ **Zusperren loescht keinen Schluessel.** Sie bleiben stehen und werden nur
abgewiesen, solange der Riegel zu ist. Sonst kostete ein versehentlicher
Klick jedes eingerichtete Dashboard im Haus.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..meldung import Meldung
from ..models import ApiSchluessel, Benutzer, Konto, utcnow

logger = logging.getLogger("nexmail.api")

#: Der Schluessel des Betreiber-Riegels in der ``einstellung``-Tabelle.
SCHALTER = "api_schluessel_erlaubt"

#: Woran man einen nexmail-Schluessel erkennt, in einer Konfigurationsdatei
#: oder in einem Geheimnis-Scanner.
VORSILBE = "nxm_"

STUFEN = ("anzahl", "betreff")

#: Genug fuer jedes Dashboard im Haus, und eine Grenze gegen eine Liste,
#: die niemand mehr ueberblickt.
MAX_JE_BENUTZER = 20

MAX_NAME = 80

#: Wie alt ``zuletzt_benutzt`` sein darf, bevor es neu geschrieben wird.
MERKEN_ALLE = timedelta(minutes=1)


def erlaubt(db: Session) -> bool:
    """Darf es in dieser Installation ueberhaupt API-Schluessel geben?"""
    return einstellung_lesen(db, SCHALTER, "0") == "1"


def erlauben(db: Session, ja: bool) -> bool:
    einstellung_schreiben(db, SCHALTER, "1" if ja else "0")
    logger.info("The operator %s API keys for this installation.", "allowed" if ja else "blocked")
    return ja


def _hash(klartext: str) -> str:
    return hashlib.sha256(klartext.encode("utf-8")).hexdigest()


def neuer_klartext() -> str:
    return VORSILBE + secrets.token_urlsafe(32)


def konten_lesen(schluessel: ApiSchluessel) -> list[str]:
    try:
        roh = json.loads(schluessel.konten_json or "[]")
    except ValueError:
        return []
    return [str(k) for k in roh if isinstance(k, str)]


def eigene_konten(db: Session, person_id: str) -> list[Konto]:
    return list(
        db.scalars(
            select(Konto).where(Konto.benutzer_id == person_id).order_by(Konto.anzeigename)
        )
    )


def freigegebene_konten(db: Session, schluessel: ApiSchluessel) -> list[Konto]:
    """Die Postfaecher, die dieser Schluessel sehen darf.

    ⚠️ **Der Schnitt, nicht die Liste.** Nur Postfaecher, die heute noch dem
    Besitzer gehoeren UND am Schluessel stehen. Die Reihenfolge ist die der
    Postfachnamen, nicht die der Auswahl.
    """
    gewaehlt = set(konten_lesen(schluessel))
    return [k for k in eigene_konten(db, schluessel.benutzer_id) if k.id in gewaehlt]


class SchluesselFehler(Meldung):
    """Eine Eingabe, die nicht passt. ``str()`` ist die Kennung."""


def _pruefen(db: Session, person: Benutzer, name: str, stufe: str, konten: list[str]) -> tuple[str, list[str]]:
    name = name.strip()
    if not name:
        raise SchluesselFehler("api_schluessel_name_fehlt")
    if len(name) > MAX_NAME:
        raise SchluesselFehler("api_schluessel_name_zu_lang", max=MAX_NAME)
    if stufe not in STUFEN:
        raise SchluesselFehler("api_schluessel_stufe_unbekannt")
    eigene = {k.id for k in eigene_konten(db, person.id)}
    gewaehlt = list(dict.fromkeys(konten))
    if not gewaehlt:
        raise SchluesselFehler("api_schluessel_ohne_postfach")
    if any(k not in eigene for k in gewaehlt):
        # ⚠️ Eine fremde Kennung sieht aus wie eine unbekannte: Wer fremde
        # Postfaecher durchprobiert, erfaehrt nicht, dass es sie gibt.
        raise SchluesselFehler("postfach_unbekannt")
    return name, gewaehlt


def anlegen(
    db: Session, person: Benutzer, name: str, stufe: str, konten: list[str]
) -> tuple[ApiSchluessel, str]:
    """Legt einen Schluessel an und gibt den Klartext **ein einziges Mal** heraus."""
    name, gewaehlt = _pruefen(db, person, name, stufe, konten)
    vorhanden = db.scalars(
        select(ApiSchluessel.id).where(ApiSchluessel.benutzer_id == person.id)
    ).all()
    if len(vorhanden) >= MAX_JE_BENUTZER:
        raise SchluesselFehler("api_schluessel_zu_viele", max=MAX_JE_BENUTZER)

    klartext = neuer_klartext()
    zeile = ApiSchluessel(
        benutzer_id=person.id,
        name=name,
        schluessel_hash=_hash(klartext),
        praefix=klartext[: len(VORSILBE) + 6],
        stufe=stufe,
        konten_json=json.dumps(gewaehlt),
    )
    db.add(zeile)
    db.commit()
    db.refresh(zeile)
    logger.info("An API key was created (scope %s, %d mailboxes).", stufe, len(gewaehlt))
    return zeile, klartext


def aendern(
    db: Session, person: Benutzer, schluessel_id: str, name: str, stufe: str, konten: list[str]
) -> ApiSchluessel | None:
    zeile = eigener(db, person, schluessel_id)
    if zeile is None:
        return None
    name, gewaehlt = _pruefen(db, person, name, stufe, konten)
    zeile.name = name
    zeile.stufe = stufe
    zeile.konten_json = json.dumps(gewaehlt)
    db.commit()
    logger.info("An API key was changed (scope %s, %d mailboxes).", stufe, len(gewaehlt))
    return zeile


def eigener(db: Session, person: Benutzer, schluessel_id: str) -> ApiSchluessel | None:
    return db.scalars(
        select(ApiSchluessel).where(
            ApiSchluessel.id == schluessel_id, ApiSchluessel.benutzer_id == person.id
        )
    ).first()


def liste(db: Session, person: Benutzer) -> list[ApiSchluessel]:
    return list(
        db.scalars(
            select(ApiSchluessel)
            .where(ApiSchluessel.benutzer_id == person.id)
            .order_by(ApiSchluessel.angelegt)
        )
    )


def entfernen(db: Session, person: Benutzer, schluessel_id: str) -> bool:
    zeile = eigener(db, person, schluessel_id)
    if zeile is None:
        return False
    db.delete(zeile)
    db.commit()
    logger.info("An API key was revoked.")
    return True


def finden(db: Session, klartext: str) -> ApiSchluessel | None:
    """Der Schluessel zu diesem Klartext, oder nichts."""
    if not klartext.startswith(VORSILBE):
        return None
    zeile = db.scalars(
        select(ApiSchluessel).where(ApiSchluessel.schluessel_hash == _hash(klartext))
    ).first()
    if zeile is None:
        return None
    jetzt = utcnow()
    zuletzt: datetime | None = zeile.zuletzt_benutzt
    if zuletzt is None or jetzt - zuletzt >= MERKEN_ALLE:
        zeile.zuletzt_benutzt = jetzt
        db.commit()
    return zeile
