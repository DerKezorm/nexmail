"""Die Anbindung des gemeinsamen Gerätemoduls ``geraete`` 0.1.0 (``app.vendor.nexgeraete``) an nexmails Tabellen.

⚠️ **Keine Zeile wandert, kein Schlüssel wird neu gehasht.** Ein gekoppeltes iPhone, iPad oder ein Mac ist wie seit
jeher eine Zeile von ``sitzung`` mit ``art = 'geraet'`` (Vorsilbe ``nxa_``, 48 Zufallsbyte, ``sha256`` als Hex); das
Modul rechnet genau das. Jede Abfrage hier trägt ``art = 'geraet'``: eine Browser-Zeile ist nie ein Gerät. Neu und
ergänzend sind die Spalten ``geraet_art``, ``modell``, ``system``, ``app_version``, ``weg``, ``versteht``,
``mitteilungen``; Zeilen der Vorfassung behalten ``NULL``.

⚠️ **Die Kopplungen bleiben in ``app_kopplung``** (statt einer neuen ``app_pairings``, G34): die Tabelle passt, sie
bekommt nur ``geraet_id`` und ``angelegt`` dazu, und die Wächter der veröffentlichten App
(``tests/test_app_flaeche.py``) lesen sie unverändert. Der Einmalcode der Anmeldung im Browser liegt in der neuen
Tabelle ``app_codes`` (nexnotes' Form).

``gueltig_bis`` bekommen neue Geräte weiter (zehn Jahre, damit eine ältere Fassung sie nach einem Rückweg liest);
das Modul trennt nach 365 Tagen ohne Nutzung (G27, G39). Eine Zeile, deren ``gueltig_bis`` doch einmal vorbei ist,
liest der Store wie die Vorfassung als getrennt.

Uhr und Versand stehen als ``jetzt`` und ``senden`` in diesem Modul, damit der Vertragsadapter sie ersetzen kann
(``tests/nexgeraete_adapter.py``): die Router rufen sie bei jeder Anfrage über eine Lambda.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AppCode, AppKopplung, Benutzer, Sitzung, neue_id, utcnow
from ..vendor import nexgeraete
from ..vendor.nexgeraete.config import LANGUAGES
from ..vendor.nexgeraete.devices import Caller
from ..vendor.nexgeraete.model import (
    ConnectCode,
    Device,
    DeviceChange,
    Holder,
    NewDevice,
    NewPairing,
    Pairing,
    PushState,
)

logger = logging.getLogger("nexmail.geraete")

#: Zehn Jahre wie bisher (``sitzung.GERAET_TAGE``): eine ältere Fassung prüft ``gueltig_bis`` noch.
GERAET_TAGE = 3650

#: So lange darf der Relay antworten (wie ``push.RELAY_SEKUNDEN``).
RELAY_SEKUNDEN = 8.0

#: Die Arten, die nexmail schickt; die veröffentlichte App (nexmail-ios 1.x) kennt beide, also ``legacy_kinds``.
MAIL = nexgeraete.PushKind(
    id="mail",
    title={"de": "Neue Mail", "en": "New mail", "fr": "Nouveau courriel"},
    hint={
        "de": "Wenn neue Post ankommt, so wie unter Benachrichtigungen eingestellt.",
        "en": "When new mail arrives, as set under Notifications.",
        "fr": "Quand un nouveau courriel arrive, selon les réglages des notifications.",
    },
)
TERMIN = nexgeraete.PushKind(
    id="event",
    title={"de": "Terminerinnerungen", "en": "Event reminders", "fr": "Rappels d'événements"},
    hint={
        "de": "Vor einem Termin, wie seine Erinnerung es sagt.",
        "en": "Before an event, as its reminder says.",
        "fr": "Avant un événement, selon son rappel.",
    },
)


#: Die Kennungen, unter denen die App-Wege des Moduls ohne ``X-Nex-App`` antworten (Form ``mail``, wie nexmail bis
#: 0.34): die Oberfläche und die veröffentlichte App übersetzen sie (``serverfehler`` im Katalog).
ALTE_KENNUNGEN = frozenset(
    {
        "app_kopplung_unbekannt",
        "app_abgeschaltet",
        "zu_viele_versuche",
        "app_zu_viele_geraete",
        "app_zu_viele_kopplungen",
        "kein_gueltiger_schluessel",
        "nicht_gefunden",
        "nicht_angemeldet",
    }
)


def _relay() -> str:
    """Leer: der Betreiber will nichts nach außen (``NEXMAIL_PUSH_RELAY``)."""
    return get_settings().push_relay.strip().rstrip("/")


KONFIGURATION = nexgeraete.AppConfig(
    app="nexmail",
    scheme="nexmail",
    token_prefix="nxa_",
    token_bytes=48,
    form=nexgeraete.FORM_MAIL,
    push_info="nexmail-push-v1",
    kinds=(MAIL, TERMIN),
    legacy_kinds=("mail", "event"),
    # nexmail hat nur den Riegel ``app_geraete_erlaubt``: neue Geräte folgen ihm.
    switches=(nexgeraete.SWITCH_APP,),
    account_id=str,
    device_id=str,
    relay_url=_relay,
    # Leer, solange keine Adresse im App Store bekannt ist: das Fenster zeigt dann keinen Link dorthin.
    app_store_url="",
)


def jetzt() -> datetime:
    """Die Uhr des Moduls (der Vertragsadapter stellt sie vor)."""
    return utcnow()


def senden(url: str, rumpf: dict[str, Any]) -> int:
    """Der Versand an den Relay über ``httpx`` wie bisher (``push.an_geraet``): acht Sekunden, kein Wiederholen.

    ⚠️ **Ein Netzfehler wird ``OSError``**, nur den fängt das Modul je Gerät ab; ein stummes Gerät hält das nächste
    nicht auf. Im Fehlertext steht nur die Art des Fehlers, nie das Ticket."""
    try:
        with httpx.Client(timeout=RELAY_SEKUNDEN) as klient:
            return int(klient.post(url, json=rumpf).status_code)
    except httpx.HTTPError as fehler:
        raise OSError(type(fehler).__name__) from None


def _bewusst(wert: datetime | None) -> datetime | None:
    if wert is None:
        return None
    return wert if wert.tzinfo is not None else wert.replace(tzinfo=timezone.utc)


def _json(wert: str | None, vorgabe: Any) -> Any:
    if not wert:
        return vorgabe
    try:
        return json.loads(wert)
    except ValueError:
        return vorgabe


def geraet_aus(z: Sitzung) -> Device:
    """Eine Zeile ``art = geraet`` so, wie das Modul ein Gerät sieht (nie Schlüssel oder Hash)."""
    push = None
    if z.push_ticket and z.push_schluessel:
        versteht = _json(z.versteht, None)
        push = PushState(
            z.push_ticket,
            z.push_schluessel,
            tuple(str(art) for art in versteht) if isinstance(versteht, list) else None,
        )
    arten = _json(z.mitteilungen, {})
    return Device(
        id=z.id,
        account_id=z.benutzer_id,
        name=z.geraet or "iPhone",
        kind=z.geraet_art,
        model=z.modell,
        system=z.system,
        app_version=z.app_version,
        via=z.weg,
        created_at=_bewusst(z.angelegt),
        last_seen_at=_bewusst(z.zuletzt_gesehen),
        push=push,
        kinds={str(k): bool(v) for k, v in arten.items()} if isinstance(arten, dict) else {},
    )


class GeraeteStore:
    """Der ``Store`` des Moduls über eine Sitzung der Datenbank (eine Transaktion je Anfrage)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Geräte -------------------------------------------------------------------------------------------------
    def _zeilen(self, *bedingung: Any) -> list[Sitzung]:
        return list(
            self.db.scalars(
                select(Sitzung)
                .where(Sitzung.art == "geraet", Sitzung.gueltig_bis > utcnow(), *bedingung)
                .order_by(Sitzung.angelegt.desc(), Sitzung.id.desc())
            )
        )

    def _zeile(self, device_id: Any) -> Sitzung | None:
        gefunden = self._zeilen(Sitzung.id == str(device_id))
        return gefunden[0] if gefunden else None

    def devices_of(self, account_id: Any) -> list[Device]:
        return [geraet_aus(z) for z in self._zeilen(Sitzung.benutzer_id == str(account_id))]

    def device(self, device_id: Any) -> Device | None:
        zeile = self._zeile(device_id)
        return geraet_aus(zeile) if zeile is not None else None

    def device_by_hash(self, token_hash: str) -> Device | None:
        gefunden = self._zeilen(Sitzung.token_hash == token_hash)
        return geraet_aus(gefunden[0]) if gefunden else None

    def add_device(self, new: NewDevice) -> Device:
        zeile = Sitzung(
            id=neue_id(),
            benutzer_id=str(new.account_id),
            token_hash=new.token_hash,
            bestaetigt=True,
            art="geraet",
            geraet=new.name[:200],
            adresse="",
            angelegt=new.created_at,
            zuletzt_gesehen=new.created_at,
            gueltig_bis=max(new.created_at, utcnow()) + timedelta(days=GERAET_TAGE),
            geraet_art=new.kind,
            modell=(new.model or None) and new.model[:64],
            system=(new.system or None) and new.system[:64],
            app_version=(new.app_version or None) and new.app_version[:32],
            weg=new.via,
        )
        self.db.add(zeile)
        self.db.flush()
        return geraet_aus(zeile)

    def change_device(self, device_id: Any, change: DeviceChange) -> Device:
        zeile = self.db.get(Sitzung, str(device_id))
        if zeile is None or zeile.art != "geraet":
            raise LookupError(device_id)
        if change.name is not None:
            zeile.geraet = change.name[:200]
        if change.model is not None:
            zeile.modell = change.model[:64]
        if change.system is not None:
            zeile.system = change.system[:64]
        if change.app_version is not None:
            zeile.app_version = change.app_version[:32]
        self.db.flush()
        return geraet_aus(zeile)

    def remove_device(self, device_id: Any) -> None:
        zeile = self.db.get(Sitzung, str(device_id))
        if zeile is not None and zeile.art == "geraet":
            self.db.delete(zeile)
            self.db.flush()

    def _orm(self, device_id: Any) -> Sitzung | None:
        zeile = self.db.get(Sitzung, str(device_id))
        return zeile if zeile is not None and zeile.art == "geraet" else None

    def touch(self, device_id: Any, when: datetime) -> None:
        zeile = self._orm(device_id)
        if zeile is not None:
            zeile.zuletzt_gesehen = when
            self.db.flush()

    def idle_devices(self, before: datetime) -> list[Device]:
        return [
            geraet_aus(z)
            for z in self._zeilen(func.coalesce(Sitzung.zuletzt_gesehen, Sitzung.angelegt) < before)
        ]

    def set_push(self, device_id: Any, state: PushState | None) -> None:
        zeile = self._orm(device_id)
        if zeile is None:
            return
        zeile.push_ticket = state.ticket if state else ""
        zeile.push_schluessel = state.key if state else ""
        zeile.versteht = (
            json.dumps(list(state.understands)) if state is not None and state.understands is not None else None
        )
        self.db.flush()

    def set_kinds(self, device_id: Any, kinds: dict[str, bool]) -> None:
        zeile = self._orm(device_id)
        if zeile is not None:
            zeile.mitteilungen = json.dumps(kinds, sort_keys=True)
            self.db.flush()

    # --- Konten -------------------------------------------------------------------------------------------------
    def holder(self, account_id: Any) -> Holder | None:
        person = self.db.get(Benutzer, str(account_id))
        if person is None:
            return None
        from ..vendor import nexkonten, nexpost
        from . import benutzer as benutzerdienst
        from . import konten_store

        chef = benutzerdienst.betreiber(self.db)
        sprache = nexpost.letters.language_for(person.sprache or "", chef.sprache if chef else "")
        return Holder(
            id=person.id,
            name=person.anzeigename or person.benutzername,
            login=person.benutzername,
            email=person.kontaktadresse if person.kontaktadresse and person.kontaktadresse_zaehlt else "",
            avatar=(_bewusst(person.profilbild_am).isoformat() if person.profilbild_am and person.profilbild else ""),
            operator=bool(person.ist_betreiber),
            out=person.gesperrt_seit is not None or person.geloescht_am is not None,
            language=sprache if sprache in LANGUAGES else "en",
            factor_owed=konten_store.store_fuer(self.db).second_factor(person.id) == nexkonten.SECOND_FACTOR_REQUIRED,
        )

    def operators(self) -> list[Any]:
        return list(
            self.db.scalars(
                select(Benutzer.id).where(
                    Benutzer.ist_betreiber.is_(True), Benutzer.gesperrt_seit.is_(None), Benutzer.geloescht_am.is_(None)
                )
            )
        )

    # --- Kopplungen (``app_kopplung``) --------------------------------------------------------------------------
    def _kopplung(self, z: AppKopplung | None) -> Pairing | None:
        if z is None:
            return None
        ende = _bewusst(z.gilt_bis)
        assert ende is not None
        return Pairing(
            id=z.id,
            account_id=z.benutzer_id,
            secret_hash=z.geheimnis_hash,
            code_hash=z.code_hash,
            created_at=_bewusst(z.angelegt) or ende - timedelta(minutes=KONFIGURATION.pairing_minutes),
            expires_at=ende,
            used_at=_bewusst(z.abgeholt),
            device_id=z.geraet_id,
        )

    def add_pairing(self, new: NewPairing) -> Pairing:
        zeile = AppKopplung(
            id=new.id,
            benutzer_id=str(new.account_id),
            geheimnis_hash=new.secret_hash,
            code_hash=new.code_hash,
            gilt_bis=new.expires_at,
            angelegt=new.created_at,
        )
        self.db.add(zeile)
        self.db.flush()
        gefunden = self._kopplung(zeile)
        assert gefunden is not None
        return gefunden

    def pairing(self, pairing_id: str) -> Pairing | None:
        return self._kopplung(self.db.get(AppKopplung, pairing_id))

    def pairing_by_code(self, code_hash: str) -> Pairing | None:
        return self._kopplung(
            self.db.scalars(
                select(AppKopplung).where(AppKopplung.code_hash == code_hash).order_by(AppKopplung.gilt_bis.desc())
            ).first()
        )

    def open_pairings(self, account_id: Any, now: datetime) -> list[Pairing]:
        zeilen = self.db.scalars(
            select(AppKopplung).where(
                AppKopplung.benutzer_id == str(account_id), AppKopplung.abgeholt.is_(None), AppKopplung.gilt_bis > now
            )
        )
        return [k for k in (self._kopplung(z) for z in zeilen) if k is not None]

    def use_pairing(self, pairing_id: str, device_id: Any, when: datetime) -> bool:
        """⚠️ **Ein bedingtes UPDATE, kein Nachsehen**: von zwei gleichzeitigen Abholungen greift genau eine (SQLite hat
        einen Schreiber). ``geraet`` bekommt den Namen wie bisher, damit „verbunden“ ihn nennt."""
        name = ""
        if device_id is not None:
            zeile = self.db.get(Sitzung, str(device_id))
            name = zeile.geraet if zeile is not None else ""
        getroffen = self.db.execute(
            update(AppKopplung)
            .where(AppKopplung.id == pairing_id, AppKopplung.abgeholt.is_(None), AppKopplung.gilt_bis > when)
            .values(abgeholt=when, geraet_id=None if device_id is None else str(device_id), geraet=name)
            .execution_options(synchronize_session=False)
        ).rowcount
        return getroffen == 1

    def remove_pairing(self, pairing_id: str) -> None:
        zeile = self.db.get(AppKopplung, pairing_id)
        if zeile is not None:
            self.db.delete(zeile)
            self.db.flush()

    # --- Einmalcodes (``app_codes``) ----------------------------------------------------------------------------
    def add_connect_code(self, new: ConnectCode) -> None:
        self.db.add(
            AppCode(
                code_hash=new.code_hash,
                account_id=str(new.account_id),
                state=new.state,
                challenge=new.challenge,
                created_at=new.created_at,
                expires_at=new.expires_at,
            )
        )
        self.db.flush()

    def take_connect_code(self, code_hash: str, when: datetime) -> ConnectCode | None:
        getroffen = self.db.execute(
            update(AppCode)
            .where(AppCode.code_hash == code_hash, AppCode.used_at.is_(None), AppCode.expires_at > when)
            .values(used_at=when)
            .execution_options(synchronize_session=False)
        ).rowcount
        if getroffen != 1:
            return None
        zeile = self.db.scalars(select(AppCode).where(AppCode.code_hash == code_hash)).one()
        self.db.refresh(zeile)
        return ConnectCode(
            code_hash=zeile.code_hash,
            account_id=zeile.account_id,
            state=zeile.state,
            challenge=zeile.challenge,
            created_at=_bewusst(zeile.created_at),  # type: ignore[arg-type]
            expires_at=_bewusst(zeile.expires_at),  # type: ignore[arg-type]
        )

    # --- Schalter, Transaktion ----------------------------------------------------------------------------------
    def switch(self, name: str) -> bool:
        """Nur ``app`` (``app_geraete_erlaubt``, ab Werk an), derselbe Schalter wie in ``schluessel``."""
        from . import app_kopplung

        return app_kopplung.erlaubt(self.db)

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def store_fuer(db: Session) -> GeraeteStore:
    return GeraeteStore(db)


def store_der_anfrage(db: Annotated[Session, Depends(get_db)]) -> GeraeteStore:
    """Die Abhängigkeit der Router des Moduls: dieselbe Sitzung der Datenbank wie die übrigen Abhängigkeiten der
    Anfrage (``deps.DbSession``)."""
    return GeraeteStore(db)


def aufraeumen(db: Session) -> int:
    """Einmalcodes, die seit einem Tag abgelaufen sind (die Kopplungen räumt ``app_kopplung.aufraeumen``)."""
    stichtag = utcnow() - timedelta(days=1)
    alte = list(db.scalars(select(AppCode).where(or_(AppCode.expires_at < stichtag, AppCode.used_at < stichtag))))
    for zeile in alte:
        db.delete(zeile)
    if alte:
        db.commit()
    return len(alte)


def als_http(form: str, abgewiesen: Any) -> HTTPException:
    """Eine Abweisung des Moduls aus einer Abhängigkeit, in der Form der Anfrage. In nexmails alter Form stehen die
    Werte als ``werte`` neben ``detail`` (``main.als_antwort``)."""
    stand, rumpf, kopf = nexgeraete.forms.refusal(form, abgewiesen)
    kennung = rumpf.pop("detail")
    fehler = HTTPException(status_code=stand, detail=kennung, headers=kopf)
    if "werte" in rumpf:
        fehler.werte = rumpf["werte"]  # type: ignore[attr-defined]
    return fehler


def antwort(teile: tuple[int, Any, dict[str, str] | None]) -> Response:
    """Eine Antwort des Moduls (``forms``) als Response."""
    stand, rumpf, kopf = teile
    if rumpf is None:
        return Response(status_code=stand, headers=kopf)
    return JSONResponse(status_code=stand, content=rumpf, headers=kopf)


def aufrufer(request: Request) -> Caller:
    """Das Gerät der Anfrage samt Konto, wie ``deps._geraet`` es geprüft hat (nur unter ``/api/app/1``, nach
    ``nur_geraet``)."""
    gefunden = getattr(request.state, "geraet", None)
    if gefunden is None:
        raise HTTPException(status_code=401, detail="nicht_angemeldet")
    return gefunden


def alte_form_aussen(request: Request) -> None:
    """Vor den Browser-Wegen des Moduls (``/api/app-pairing``, ``/api/app-devices`` …): ein Geräteschlüssel ohne
    ``X-Nex-App`` hört dort wie seit jeher ``401 nicht_angemeldet``, wie an jeder anderen Adresse außerhalb der Fläche
    (``test_app_flaeche``: ein Gerätetoken öffnet nichts und verrät nichts). Mit ``X-Nex-App`` antwortet das Modul
    ``403 browser_only``."""
    if request.headers.get("authorization") and not request.headers.get(nexgeraete.CLIENT_HEADER):
        raise HTTPException(status_code=401, detail="nicht_angemeldet")


def nach_kopplung(inhaber: Holder, geraet: Device) -> None:
    """Nach jedem neuen Gerät (G29): die Mail „Neue Anmeldung“ wie bei einem neuen Browser, wenn das Konto sie will
    (Profil, „Mail bei neuer Anmeldung“) und die Installation Mail verschicken kann. Läuft nach dem Commit; ein Fehler
    ändert an der Kopplung nichts."""
    from ..db import SessionLocal
    from ..vendor.nexkonten import sessions as kontensitzungen
    from . import konten_store, kontenpost

    with SessionLocal() as db:
        person = db.get(Benutzer, str(inhaber.id))
        if person is None:
            return
        store = konten_store.store_fuer(db)
        bescheid = kontensitzungen.new_sign_in(
            store.get_account(person.id), known=False, wanted=bool(person.mail_neue_anmeldung)
        )
        if bescheid is None or not kontenpost.mail_moeglich(db):
            return
        kontenpost.senden(db, bescheid, where=nexgeraete.describe(geraet))
        db.commit()


def neue_version(fassung: str) -> None:
    """``updates.on_newer`` (G18): „Neue Version“ an die Geräte der Betreiber, die es an haben und verstehen (die
    veröffentlichte App nicht). Ein Fehler hält nichts auf."""
    from .. import __version__
    from ..db import SessionLocal

    with SessionLocal() as db:
        try:
            nexgeraete.notices.newer(
                store_fuer(db), KONFIGURATION, fassung, __version__, f"https://github.com/DerKezorm/nexmail/releases/tag/v{fassung}",
                send=lambda url, rumpf: senden(url, rumpf),
            )
        except Exception as fehler:  # noqa: BLE001 - ein Hinweis ist Beiwerk
            db.rollback()
            logger.warning("The notice of a new version failed: %s", type(fehler).__name__)


def taeglich() -> int:
    """Der tägliche Lauf (G27): Geräte, die 365 Tage nicht genutzt wurden, trennen."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        return nexgeraete.devices.sweep(store_fuer(db), KONFIGURATION, jetzt())


def beschreiben(zeile: Sitzung) -> str:
    """Ein Gerät in einer Zeile für „Angemeldete Geräte“ (konten ``device_label``): Name, dazu das Modell, wo es mehr
    sagt."""
    return nexgeraete.describe(geraet_aus(zeile))


__all__ = [
    "GERAET_TAGE",
    "KONFIGURATION",
    "GeraeteStore",
    "als_http",
    "alte_form_aussen",
    "antwort",
    "aufraeumen",
    "aufrufer",
    "beschreiben",
    "geraet_aus",
    "jetzt",
    "nach_kopplung",
    "neue_version",
    "senden",
    "store_der_anfrage",
    "store_fuer",
    "taeglich",
]
