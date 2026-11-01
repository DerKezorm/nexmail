"""Die iPhone-App koppeln: QR-Code oder kurzer Code im Browser, Abholen in der App.

⚠️ **Ein Gerät hat dieselben Rechte wie eine Browsersitzung.** Anders als ein
API-Schlüssel, der nur liest. Deshalb gilt eine Kopplung zehn Minuten und für
genau ein Gerät, und deshalb zählt die Anmeldebremse jeden Fehlversuch.

⚠️ **Zwei Wege, derselbe Ausgang.** Der QR-Code trägt Kennung und Geheimnis, 256
Bit, die niemand rät. Der kurze Code ist zum Abtippen und hat 40 Bit; das trägt
nur zusammen mit der Bremse und der kurzen Frist. Unbekannt, falsch, abgelaufen
und verbraucht antworten überall gleich.

⚠️ **Der Riegel des Betreibers ist ab Werk offen**, anders als bei den
API-Schlüsseln: Die App kann nichts, was der Browser nicht schon kann.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..meldung import Meldung
from ..models import AppKopplung, Benutzer, utcnow
from . import sitzung as sitzungsdienst

logger = logging.getLogger("nexmail.app")

GILT_MINUTEN = 10
OFFEN_HOECHSTENS = 5
GERAET_HOECHSTENS = 80

#: Ohne 0, O, 1, I, die man abgetippt verwechselt.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LAENGE = 8

SCHALTER = "app_geraete_erlaubt"


class KopplungFehler(Meldung):
    """Etwas, das dem Menschen oder der App gezeigt wird."""


def erlaubt(db: Session) -> bool:
    return einstellung_lesen(db, SCHALTER, "1") == "1"


def erlauben(db: Session, ja: bool) -> bool:
    """Den Riegel umlegen.

    ⚠️ **Zusperren trennt kein Gerät.** Die Tür zu ``/api/app/1`` ist sofort
    zu, die Geräte stehen weiter in der Liste; dieselbe Regel wie bei den
    API-Schlüsseln, und ein versehentliches Zumachen kostet niemanden seine
    Kopplung.
    """
    einstellung_schreiben(db, SCHALTER, "1" if ja else "0")
    logger.info("The operator %s the iPhone app.", "allowed" if ja else "blocked")
    return ja


def _hash(wert: str) -> str:
    return hashlib.sha256(wert.encode("utf-8")).hexdigest()


def _code_sauber(code: str) -> str:
    """Bindestrich, Leerzeichen und Kleinschreibung sind beim Abtippen normal."""
    return "".join(z for z in code.upper() if z.isalnum())


def code_zeigen(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


@dataclass
class Vorbereitet:
    kennung: str
    geheimnis: str
    code: str
    gilt_bis: datetime


def vorbereiten(db: Session, person: Benutzer) -> Vorbereitet:
    """Eine Kopplung anlegen. Geheimnis und Code stehen nur hier im Klartext."""
    if not erlaubt(db):
        raise KopplungFehler("app_abgeschaltet")
    jetzt = utcnow()
    offen = db.scalar(
        select(func.count())
        .select_from(AppKopplung)
        .where(
            AppKopplung.benutzer_id == person.id,
            AppKopplung.abgeholt.is_(None),
            AppKopplung.gilt_bis > jetzt,
        )
    )
    if offen >= OFFEN_HOECHSTENS:
        raise KopplungFehler("app_zu_viele_kopplungen", max=OFFEN_HOECHSTENS)

    geheimnis = secrets.token_urlsafe(32)
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LAENGE))
    zeile = AppKopplung(
        benutzer_id=person.id,
        geheimnis_hash=_hash(geheimnis),
        code_hash=_hash(code),
        gilt_bis=jetzt + timedelta(minutes=GILT_MINUTEN),
    )
    db.add(zeile)
    db.commit()
    return Vorbereitet(zeile.id, geheimnis, code_zeigen(code), zeile.gilt_bis)


def _eigene(db: Session, kennung: str, person: Benutzer) -> AppKopplung:
    zeile = db.get(AppKopplung, kennung)
    if zeile is None or zeile.benutzer_id != person.id:
        raise KopplungFehler("app_kopplung_unbekannt")
    return zeile


def stand(db: Session, kennung: str, person: Benutzer) -> tuple[str, str]:
    """``wartet``, ``verbunden`` oder ``abgelaufen``, dazu der Gerätename."""
    zeile = _eigene(db, kennung, person)
    if zeile.abgeholt is not None:
        return "verbunden", zeile.geraet
    return ("abgelaufen" if zeile.gilt_bis <= utcnow() else "wartet"), ""


def zurueckziehen(db: Session, kennung: str, person: Benutzer) -> None:
    zeile = _eigene(db, kennung, person)
    if zeile.abgeholt is None:
        db.delete(zeile)
        db.commit()


def _einloesen(db: Session, zeile: AppKopplung, geraet: str, adresse: str) -> tuple[str, Benutzer]:
    """⚠️ **Ein bedingtes UPDATE, kein Nachsehen.** Zwei gleichzeitige Abholungen
    desselben Codes kämen sonst beide durch, und aus einem Gerät würden zwei.
    SQLite hat einen Schreiber; von zwei UPDATEs greift genau eines."""
    name = "".join(z for z in geraet if z.isprintable()).strip()[:GERAET_HOECHSTENS] or "iPhone"
    jetzt = utcnow()
    getroffen = db.execute(
        update(AppKopplung)
        .where(
            AppKopplung.id == zeile.id,
            AppKopplung.abgeholt.is_(None),
            AppKopplung.gilt_bis > jetzt,
        )
        .values(abgeholt=jetzt, geraet=name)
    ).rowcount
    db.commit()
    if not getroffen:
        raise KopplungFehler("app_kopplung_unbekannt")
    person = db.get(Benutzer, zeile.benutzer_id)
    logger.info("A device was paired with an account.")
    return sitzungsdienst.geraet_anlegen(db, person, name, adresse), person


def abholen(
    db: Session, kennung: str, geheimnis: str | None, geraet: str, adresse: str
) -> tuple[str, Benutzer]:
    """Den Schlüssel gegen Kennung und Geheimnis aus dem QR-Code.

    ⚠️ **Auch ohne Zeile wird verglichen**, damit eine unbekannte Kennung nicht
    schneller antwortet als ein falsches Geheimnis.
    """
    zeile = db.get(AppKopplung, kennung)
    erwartet = zeile.geheimnis_hash if zeile is not None else _hash("")
    stimmt = hmac.compare_digest(erwartet, _hash(geheimnis or ""))
    if zeile is None or not stimmt or not geheimnis:
        raise KopplungFehler("app_kopplung_unbekannt")
    return _einloesen(db, zeile, geraet, adresse)


def mit_code(db: Session, code: str, geraet: str, adresse: str) -> tuple[str, Benutzer]:
    """Der Weg zum Abtippen: Die Zeile wird über den Code gefunden."""
    sauber = _code_sauber(code)
    zeile = db.scalars(
        select(AppKopplung).where(
            AppKopplung.code_hash == _hash(sauber),
            AppKopplung.abgeholt.is_(None),
            AppKopplung.gilt_bis > utcnow(),
        )
    ).first()
    if zeile is None or len(sauber) != CODE_LAENGE:
        raise KopplungFehler("app_kopplung_unbekannt")
    return _einloesen(db, zeile, geraet, adresse)


def aufraeumen(db: Session) -> int:
    """Abgelaufenes fällt nach einem Tag, damit die Seite „abgelaufen" sagen kann."""
    stichtag = utcnow() - timedelta(days=1)
    alte = list(db.scalars(select(AppKopplung).where(AppKopplung.gilt_bis < stichtag)))
    for zeile in alte:
        db.delete(zeile)
    if alte:
        db.commit()
    return len(alte)


__all__ = [
    "CODE_LAENGE",
    "GERAET_HOECHSTENS",
    "GILT_MINUTEN",
    "KopplungFehler",
    "OFFEN_HOECHSTENS",
    "Vorbereitet",
    "abholen",
    "aufraeumen",
    "erlaubt",
    "erlauben",
    "mit_code",
    "stand",
    "vorbereiten",
    "zurueckziehen",
]
