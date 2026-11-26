"""Die Anbindung des gemeinsamen Moduls ``schluessel`` (``app.vendor.nexschluessel``, bauplaene/schluessel 1.0.0) an
nexmails Tabelle ``api_schluessel``.

⚠️ **Keine Zeile wandert, kein Schluessel wird neu gehasht.** nexmail speichert seit jeher ``sha256(schluessel)`` als
Hex samt Vorsilbe ``nxm_``; genau das rechnet das Modul. Die Spalten behalten ihre Namen: ``stufe`` (``anzahl``,
``betreff``) ist das Recht (``count``, ``headers``), ``konten_json`` die Postfaecher (Pflicht, nie „alle"),
``aufgaben``/``schlagworte`` die Extras ``tasks``/``tags``. Neu ist nur die Spalte ``gesperrt`` (der Betreiber sperrt
einen Schluessel, seit 1.0.0 in allen Apps); eine aeltere Fassung liest sie nicht, dort wirkte ein gesperrter
Schluessel wieder (Rueckweg im README des Moduls).

Die Schalter des Betreibers bleiben unter ihren Namen und Vorgaben: ``api`` = ``api_schluessel_erlaubt`` (ab Werk
aus), ``app`` = ``app_geraete_erlaubt`` (ab Werk an). Gekoppelte iPhones (``nxa_``) sind keine Schluessel des Moduls.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..models import ApiSchluessel, Benutzer
from ..vendor.nexschluessel import AppConfig, KeyKind
from ..vendor.nexschluessel.model import ALL_AREAS, Area, Holder, Key, KeyChange, NewKey
from . import apischluessel as apidienst
from . import app_kopplung

logger = logging.getLogger("nexmail.api")

#: nexmails Rechte heissen in der Tabelle ``anzahl`` und ``betreff``, im Modul ``count`` und ``headers``.
ZU_MODUL = {"anzahl": "count", "betreff": "headers"}
ZU_NEXMAIL = {recht: stufe for stufe, recht in ZU_MODUL.items()}

KONFIGURATION = AppConfig(
    app_name="nexmail",
    kinds=(
        KeyKind(
            id="api",
            prefix=apidienst.VORSILBE,
            rights=("count", "headers"),
            default_right="count",
            options=("tasks", "tags"),
            areas=True,
            areas_required=True,
            expiry_days=None,
            max_keys=apidienst.MAX_JE_BENUTZER,
            name_max=apidienst.MAX_NAME,
            shown_extra=6,
        ),
    ),
    switches=("api", "app"),
    key_id=str,
    error_codes={
        "api_off": "api_schluessel_abgeschaltet",
        "token_invalid": "api_schluessel_ungueltig",
        "not_found": "api_schluessel_unbekannt",
    },
)

#: Die Schalter des Moduls und nexmails Einstellung samt Vorgabe.
SCHALTER = {"api": (apidienst.SCHALTER, "0"), "app": (app_kopplung.SCHALTER, "1")}


def _schluessel(z: ApiSchluessel) -> Key:
    return Key(
        id=z.id,
        account_id=z.benutzer_id,
        kind="api",
        name=z.name,
        right=ZU_MODUL.get(z.stufe, "count"),
        prefix=z.praefix,
        created_at=z.angelegt,
        last_used_at=z.zuletzt_benutzt,
        expires_at=None,
        blocked_at=z.gesperrt,
        areas=apidienst.konten_lesen(z),
        options={"tasks": bool(z.aufgaben), "tags": bool(z.schlagworte)},
    )


class SchluesselStore:
    """``nexschluessel.Store`` ueber nexmails Tabellen, innerhalb einer Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def keys_of(self, account_id) -> list[Key]:
        zeilen = self.db.scalars(
            select(ApiSchluessel)
            .where(ApiSchluessel.benutzer_id == str(account_id))
            .order_by(ApiSchluessel.angelegt.desc())
        )
        return [_schluessel(z) for z in zeilen]

    def all_keys(self) -> list[Key]:
        return [_schluessel(z) for z in self.db.scalars(select(ApiSchluessel).order_by(ApiSchluessel.angelegt.desc()))]

    def key(self, key_id) -> Key | None:
        z = self.db.get(ApiSchluessel, str(key_id))
        return _schluessel(z) if z is not None else None

    def key_by_hash(self, token_hash: str) -> Key | None:
        z = self.db.scalar(select(ApiSchluessel).where(ApiSchluessel.schluessel_hash == token_hash))
        return _schluessel(z) if z is not None else None

    def add_key(self, new: NewKey) -> Key:
        zeile = ApiSchluessel(
            benutzer_id=str(new.account_id),
            name=new.name,
            schluessel_hash=new.token_hash,
            praefix=new.prefix,
            stufe=ZU_NEXMAIL.get(new.right, "anzahl"),
            konten_json=json.dumps([str(a) for a in (new.areas or [])]),
            aufgaben=bool(new.options.get("tasks")),
            schlagworte=bool(new.options.get("tags")),
            angelegt=new.created_at,
        )
        self.db.add(zeile)
        self.db.flush()
        return _schluessel(zeile)

    def change_key(self, key_id, change: KeyChange) -> Key:
        zeile = self.db.get(ApiSchluessel, str(key_id))
        if change.name is not None:
            zeile.name = change.name
        if change.right is not None:
            zeile.stufe = ZU_NEXMAIL.get(change.right, zeile.stufe)
        if change.areas is not None and change.areas != ALL_AREAS:
            zeile.konten_json = json.dumps([str(a) for a in change.areas])
        if change.options is not None:
            if "tasks" in change.options:
                zeile.aufgaben = bool(change.options["tasks"])
            if "tags" in change.options:
                zeile.schlagworte = bool(change.options["tags"])
        self.db.flush()
        return _schluessel(zeile)

    def remove_key(self, key_id) -> None:
        zeile = self.db.get(ApiSchluessel, str(key_id))
        if zeile is not None:
            self.db.delete(zeile)
            self.db.flush()

    def set_blocked(self, key_id, when: datetime | None) -> None:
        self.db.execute(update(ApiSchluessel).where(ApiSchluessel.id == str(key_id)).values(gesperrt=when))

    def touch(self, key_id, when: datetime) -> None:
        """⚠️ **Der Vermerk darf die Abfrage nicht kosten** (Issue #9). Haelt ein Abgleich die Datenbank laenger als
        ``busy_timeout``, scheiterte sonst ein Dashboard mit 500, nur weil sich nicht notieren liess, wann es zuletzt
        gefragt hat. Deshalb schreibt der Vermerk selbst und gibt bei einer Sperre auf; das ``commit`` des Moduls
        danach hat nichts mehr zu tun. Dann eben beim naechsten Mal."""
        self.db.execute(update(ApiSchluessel).where(ApiSchluessel.id == str(key_id)).values(zuletzt_benutzt=when))
        try:
            self.db.commit()
        except OperationalError as fehler:
            self.db.rollback()
            logger.info("The last use of an API key could not be recorded (%s); the request goes on.", fehler.orig)

    def holder(self, account_id) -> Holder | None:
        person = self.db.get(Benutzer, str(account_id))
        if person is None:
            return None
        return Holder(
            id=person.id,
            name=person.benutzername,
            display_name=person.anzeigename or "",
            out=person.gesperrt_seit is not None or person.geloescht_am is not None,
        )

    def areas_of(self, account_id, kind: str) -> list[Area]:  # noqa: ARG002
        return [Area(k.id, k.anzeigename or k.adresse) for k in apidienst.eigene_konten(self.db, str(account_id))]

    def keys_wait(self, account_id) -> bool:
        """Die Regel von nexmail: verlangt der Betreiber einen zweiten Faktor, und das Konto meldet sich mit Passwort an
        und hat keinen, ruhen seine Schluessel (``factor.state`` = ``required``)."""
        from ..vendor import nexkonten
        from . import konten_store

        return konten_store.store_fuer(self.db).second_factor(account_id) == nexkonten.SECOND_FACTOR_REQUIRED

    def switch(self, name: str) -> bool:
        schluessel, vorgabe = SCHALTER[name]
        return einstellung_lesen(self.db, schluessel, vorgabe) == "1"

    def set_switch(self, name: str, on: bool) -> None:
        schluessel, _vorgabe = SCHALTER[name]
        einstellung_schreiben(self.db, schluessel, "1" if on else "0")

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def store_fuer(db: Session) -> SchluesselStore:
    return SchluesselStore(db)


__all__ = ["KONFIGURATION", "SchluesselStore", "store_fuer"]
