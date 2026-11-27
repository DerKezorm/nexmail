"""Die iPhone-App koppeln: QR-Code oder kurzer Code im Browser, Abholen in der App.

Seit 0.35.0 macht das das gemeinsame Gerätemodul ``geraete`` (``vendor/nexgeraete``, Anbindung in
``services/geraete_store.py``): QR-Code, Code zum Abtippen, Anmeldung im Browser, weiteres Gerät über iCloud, für die
App unter ``/api/app/1`` und im Browser unter ``/api/app-pairing`` und ``/api/app-devices``. Was hier bleibt, sind
nexmails alte Namen in deutscher Form, als dünne Hüllen über das Modul: der Riegel des Betreibers, die Wege unter
``/api/app-kopplung`` (``routers/app_kopplung.py``) und die Fehler ``KopplungFehler``/``GrenzeFehler``.

⚠️ **Ein Gerät hat dieselben Rechte wie eine Browsersitzung.** Deshalb gilt eine Kopplung zehn Minuten und für
genau ein Gerät, und deshalb zählt die Anmeldebremse jeden Fehlversuch (``konten`` ``BRAKE``, Topf
``app-pairing:<Absender>``).

⚠️ **Der Riegel des Betreibers ist ab Werk offen**, anders als bei den API-Schlüsseln: Die App kann nichts, was der
Browser nicht schon kann. Er steht unter Server › Verbindungen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..meldung import Meldung
from ..models import AppKopplung, Benutzer, utcnow

logger = logging.getLogger("nexmail.app")

GILT_MINUTEN = 10
OFFEN_HOECHSTENS = 5
GERAET_HOECHSTENS = 80

#: Ohne 0, O, 1, I, die man abgetippt verwechselt (dasselbe Alphabet hat das Modul).
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LAENGE = 8

SCHALTER = "app_geraete_erlaubt"

#: So viele Geräte darf ein Konto je Stunde über ein schon gekoppeltes Gerät hereinholen (``weiteres_geraet``).
WEITERE_JE_STUNDE = 5
STUNDE = 3600.0


class KopplungFehler(Meldung):
    """Etwas, das dem Menschen oder der App gezeigt wird."""


class GrenzeFehler(KopplungFehler):
    """Zu viele in zu kurzer Zeit; ``nochmal_in`` Sekunden geht es wieder.

    ⚠️ **Die Wartezeit steht nicht in ``werte``**, sie gehört in ``Retry-After``. Jeder Wert in ``werte`` braucht
    seinen Platzhalter im Satz (``test_meldungen``); deshalb wird sie ohne Namen übergeben.
    """

    def __init__(self, kennung: str, nochmal_in: int, /, **werte) -> None:
        super().__init__(kennung, **werte)
        self.nochmal_in = nochmal_in


#: Die Kennungen des Moduls in nexmails alter Form (``forms._MAIL``).
_KENNUNG = {
    "pairing_gone": "app_kopplung_unbekannt",
    "not_found": "app_kopplung_unbekannt",
    "app_disabled": "app_abgeschaltet",
    "app_pairing_disabled": "app_abgeschaltet",
    "too_many_pairings": "app_zu_viele_kopplungen",
    "too_many_devices": "app_zu_viele_geraete",
    "too_many_new_devices": "app_zu_viele_geraete",
}


def _fehler(abgewiesen) -> KopplungFehler:
    """``DeviceRefused`` des Moduls als ``KopplungFehler`` mit nexmails Kennung und Werten."""
    kennung = _KENNUNG.get(abgewiesen.code, abgewiesen.code)
    werte = {k: v for k, v in abgewiesen.values.items() if k != "fields"}
    if abgewiesen.code == "too_many_new_devices":
        return GrenzeFehler(kennung, int(abgewiesen.retry_after or 1), **werte)
    return KopplungFehler(kennung, **werte)


def erlaubt(db: Session) -> bool:
    return einstellung_lesen(db, SCHALTER, "1") == "1"


def erlauben(db: Session, ja: bool) -> bool:
    """Den Riegel umlegen.

    ⚠️ **Zusperren trennt kein Gerät.** Die Tür zu ``/api/app/1`` ist sofort zu (``403 app_abgeschaltet``), die
    Geräte stehen weiter in der Liste; ein versehentliches Zumachen kostet niemanden seine Kopplung.
    """
    einstellung_schreiben(db, SCHALTER, "1" if ja else "0")
    logger.info("The operator %s the iPhone app.", "allowed" if ja else "blocked")
    return ja


def code_zeigen(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


@dataclass
class Vorbereitet:
    kennung: str
    geheimnis: str
    code: str
    gilt_bis: datetime


def vorbereiten(db: Session, person: Benutzer, adresse: str = "") -> Vorbereitet:
    """Eine Kopplung anlegen (``pairing.start``). Geheimnis und Code stehen nur hier im Klartext."""
    from ..vendor.nexgeraete import DeviceRefused, pairing
    from . import geraete_store

    try:
        begonnen = pairing.start(
            geraete_store.store_fuer(db), geraete_store.KONFIGURATION, person.id, address=adresse,
            now=geraete_store.jetzt(),
        )
    except DeviceRefused as abgewiesen:
        db.rollback()
        raise _fehler(abgewiesen) from None
    return Vorbereitet(begonnen.pairing.id, begonnen.secret, begonnen.code, begonnen.pairing.expires_at)


def stand(db: Session, kennung: str, person: Benutzer) -> tuple[str, str]:
    """``wartet``, ``verbunden`` oder ``abgelaufen``, dazu der Gerätename (``pairing.state``)."""
    from ..vendor.nexgeraete import DeviceRefused, pairing
    from . import geraete_store

    try:
        wie, geraet = pairing.state(
            geraete_store.store_fuer(db), geraete_store.KONFIGURATION, person.id, kennung, geraete_store.jetzt()
        )
    except DeviceRefused as abgewiesen:
        raise _fehler(abgewiesen) from None
    if wie == "used":
        if geraet is not None:
            return "verbunden", geraet.name
        zeile = db.get(AppKopplung, kennung)
        return "verbunden", zeile.geraet if zeile is not None else ""
    return ("abgelaufen" if wie == "expired" else "wartet"), ""


def zurueckziehen(db: Session, kennung: str, person: Benutzer) -> None:
    from ..vendor.nexgeraete import DeviceRefused, pairing
    from . import geraete_store

    try:
        pairing.withdraw(geraete_store.store_fuer(db), geraete_store.KONFIGURATION, person.id, kennung)
    except DeviceRefused as abgewiesen:
        raise _fehler(abgewiesen) from None


def _einloesen(db: Session, zeile: AppKopplung, geraet: str, adresse: str) -> tuple[str, Benutzer]:
    """Eine schon gefundene Kopplung für ein Gerät einlösen, wie das Modul es beim Abholen tut (``pairing.redeem``,
    dort samt Geheimnis, Bremse und Hinweisen).

    ⚠️ **Ein bedingtes UPDATE, kein Nachsehen.** Zwei gleichzeitige Abholungen desselben Codes kämen sonst beide
    durch, und aus einem Gerät würden zwei. SQLite hat einen Schreiber; von zwei UPDATEs greift genau eines. Erst
    danach entsteht das Gerät."""
    from ..vendor.nexgeraete import VIA_QR, DeviceRefused, devices
    from . import geraete_store

    store = geraete_store.store_fuer(db)
    jetzt = geraete_store.jetzt()
    if not store.use_pairing(zeile.id, None, jetzt):
        db.rollback()
        raise KopplungFehler("app_kopplung_unbekannt")
    inhaber = store.holder(zeile.benutzer_id)
    if inhaber is None or inhaber.out or inhaber.factor_owed:
        db.commit()
        raise KopplungFehler("app_kopplung_unbekannt")
    try:
        neu, token = devices.add(
            store, geraete_store.KONFIGURATION, inhaber, name=geraet, kind="ios", via=VIA_QR, now=jetzt
        )
    except DeviceRefused as abgewiesen:
        db.rollback()
        raise _fehler(abgewiesen) from None
    db.execute(
        update(AppKopplung)
        .where(AppKopplung.id == zeile.id)
        .values(geraet_id=str(neu.id), geraet=neu.name)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    logger.info("A device was paired with an account.")
    return token, db.get(Benutzer, zeile.benutzer_id)


def weiteres_geraet(
    db: Session, person: Benutzer, geraet: str, adresse: str, jetzt: float | None = None
) -> str:
    """Ein eigener Schlüssel für ein weiteres Gerät desselben Kontos (``pairing.sibling``), etwa das iPad, das die
    Verbindung des iPhones im iCloud-Schlüsselbund findet. Die App ruft dafür ``POST /api/app/1/devices``.

    ⚠️ **Höchstens ``WEITERE_JE_STUNDE`` je Konto, in der Datenbank gezählt** (G9, G33): die lebenden Geräte des
    Kontos, die in der letzten Stunde über iCloud kamen. Ein Neustart vergisst nichts mehr; ein abgewiesener Versuch
    zählt nicht. ``jetzt`` (Sekunden seit 1970) setzt nur ein Test.

    ⚠️ **Der Riegel des Betreibers gilt auch hier**, doppelt: ``deps._sitzung`` sperrt die ganze Fläche, und das Modul
    fragt selbst noch einmal (``pairing.ready``).
    """
    from ..vendor.nexgeraete import Caller, Device, DeviceRefused, pairing
    from . import geraete_store

    store = geraete_store.store_fuer(db)
    inhaber = store.holder(person.id)
    if inhaber is None:
        raise KopplungFehler("nicht_angemeldet")
    zeitpunkt = (
        datetime.fromtimestamp(jetzt, tz=timezone.utc) if jetzt is not None else geraete_store.jetzt()
    )
    # Das bittende Gerät kennt dieser Weg nicht (nexmail führt kein ``via_token_id``).
    bittend = Device(id="", account_id=person.id, name="")
    try:
        neu = pairing.sibling(
            store, geraete_store.KONFIGURATION, Caller(device=bittend, holder=inhaber), name=geraet, now=zeitpunkt
        )
    except DeviceRefused as abgewiesen:
        db.rollback()
        raise _fehler(abgewiesen) from None
    logger.info("A paired device brought in another device of its account.")
    return neu.token


def weitere_vergessen() -> None:
    """Früher die Zählung im Arbeitsspeicher; seit geraete 0.1.0 zählt die Datenbank. Bleibt für die Tests."""


def aufraeumen(db: Session) -> int:
    """Abgelaufenes fällt nach einem Tag, damit die Seite „abgelaufen" sagen kann; dazu die Einmalcodes der
    Anmeldung im Browser."""
    from . import geraete_store

    stichtag = utcnow() - timedelta(days=1)
    alte = list(db.scalars(select(AppKopplung).where(AppKopplung.gilt_bis < stichtag)))
    for zeile in alte:
        db.delete(zeile)
    if alte:
        db.commit()
    return len(alte) + geraete_store.aufraeumen(db)


__all__ = [
    "CODE_LAENGE",
    "GERAET_HOECHSTENS",
    "GILT_MINUTEN",
    "GrenzeFehler",
    "KopplungFehler",
    "OFFEN_HOECHSTENS",
    "Vorbereitet",
    "aufraeumen",
    "erlaubt",
    "erlauben",
    "stand",
    "vorbereiten",
    "weiteres_geraet",
    "WEITERE_JE_STUNDE",
    "zurueckziehen",
]
