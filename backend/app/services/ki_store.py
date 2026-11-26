"""Die Anbindung des Moduls ki 0.1.2 (``app.vendor.nexki``) an nexmails Tabellen: ``AppConfig`` mit nexmails
Auftraegen und der Store ueber die Felder von vorher (Bauplan „Entwurf KI-Anbieter“, „Alte Einstellungen gelten
weiter“).

⚠️ **Kein Feld wandert.** Der Hauptschalter bleibt ``einstellung.ki_erlaubt`` („1“/„0“, ab Werk aus), der eigene Zugang
bleibt ``Benutzer.ki_url``/``ki_modell``/``ki_schluessel`` (versiegelt, Kontext ``benutzer:<id>:ki``), „KI für mich“
bleibt ``ki_aktiv``, „KI erlaubt“ des Kontos ``ki_erlaubt``. Neu sind nur ``Benutzer.ki_api`` (ab Werk ``openai``, wie
jeder Zugang bisher), die Einstellungen des Betreibers als ``einstellung`` ``ki_<name>`` (JSON) und zwei Spalten in
``ki_vorgang`` (``form``, ``an``). Eine aeltere Fassung liest, was sie kannte, wie vorher.

⚠️ **nexmail war „Jedes Konto selbst“** (K2): ``uebernehmen`` ruft beim Start ``settings.adopt`` mit
``older_mode="own"``, sobald die Datenbank schon Konten hat (eine Fassung von vorher), auch wenn noch niemand einen
Zugang eingetragen hat (ki 0.1.2, K-9); Rechner eigener Zugaenge im eigenen Netz kommen einmal auf die Liste des
Betreibers (K4). Eine frische Installation (beim ersten Start noch ohne Konto) beginnt mit „Einer für alle“.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import crypto
from ..db import einstellung_lesen, einstellung_schreiben
from ..models import Benutzer, KiVorgang
from ..vendor import nexki
from ..vendor.nexki.model import Event, OwnAccess

logger = logging.getLogger("nexmail.ki")

#: Der Hauptschalter, wo er immer lag; ab Werk aus (nexmail 0.10).
SCHALTER = "ki_erlaubt"

#: ``ki_vorgang.form`` einer Zeile des Moduls.
FORM_MODUL = "modul"

#: nexmails Auftraege. Temperaturen und Grenzen wie vorher (``kidienst.TEMPERATUREN``, ``MAX_TOKEN…``); alle per
#: Knopf, also wörtlich in „Was ging hinaus“ (K5). Frist 120 s wie vorher, jetzt fuer die ganze Anfrage.
CONFIG = nexki.AppConfig(
    app_name="nexmail",
    tasks=(
        nexki.Task("rechtschreibung", temperature=0.2, max_out=8_000, seconds=120.0),
        nexki.Task("uebersetzen", temperature=0.2, max_out=8_000, seconds=120.0),
        nexki.Task("umformulieren", temperature=0.7, max_out=8_000, seconds=120.0),
        nexki.Task("zusammenfassen", temperature=0.2, max_out=1_000, seconds=120.0),
        nexki.Task("frage", temperature=0.2, max_out=1_000, seconds=120.0),
        nexki.Task("antworten", temperature=0.5, max_out=1_500, seconds=120.0),
    ),
    modes=("shared", "own"),
    account_key_context=lambda account_id: f"benutzer:{account_id}:ki",
    per_minute=20,
)


def _alter_kontext(benutzer_id: str) -> str:
    """Der Kontext der Zeilen von vorher (``kidienst._vorgang_kontext``)."""
    return f"benutzer:{benutzer_id}:ki-vorgang"


def _neuer_kontext(benutzer_id: str) -> str:
    """Der Kontext, mit dem das Modul den Text einer Zeile versiegelt (``client._keep``)."""
    return f"{CONFIG.account_key_context(benutzer_id)}:events"


class KiStore:
    """``nexki.Store`` ueber nexmails Tabellen, innerhalb einer Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Einstellungen des Betreibers ---------------------------------------------------------------------------

    def setting(self, name: str) -> Any:
        if name == "enabled":
            # Mit seiner alten Vorgabe „aus“ gilt er als gespeichert (nie ``None``), adopt laesst ihn stehen.
            return einstellung_lesen(self.db, SCHALTER, "0") == "1"
        wert = einstellung_lesen(self.db, f"ki_{name}")
        return json.loads(wert) if wert else None

    def set_setting(self, name: str, value: Any) -> None:
        if name == "enabled":
            einstellung_schreiben(self.db, SCHALTER, "1" if value else "0")
            return
        einstellung_schreiben(self.db, f"ki_{name}", json.dumps(value))

    # --- Konten ---------------------------------------------------------------------------------------------------

    def _person(self, account_id: Any) -> Benutzer | None:
        return self.db.get(Benutzer, str(account_id))

    def account_allowed(self, account_id: Any) -> bool:
        person = self._person(account_id)
        return person is not None and bool(person.ki_erlaubt)

    def account_out(self, account_id: Any) -> bool:
        person = self._person(account_id)
        return person is None or person.gesperrt_seit is not None or person.geloescht_am is not None

    def person_on(self, account_id: Any) -> bool:
        person = self._person(account_id)
        return person is not None and bool(person.ki_aktiv)

    def set_person_on(self, account_id: Any, on: bool) -> None:
        person = self._person(account_id)
        if person is not None:
            person.ki_aktiv = bool(on)
            self.db.flush()

    def own_access(self, account_id: Any) -> OwnAccess | None:
        person = self._person(account_id)
        if person is None or not (person.ki_url or person.ki_modell):
            return None
        return OwnAccess(person.ki_api or "openai", person.ki_url, person.ki_modell, person.ki_schluessel or "")

    def set_own_access(self, account_id: Any, access: OwnAccess | None) -> None:
        person = self._person(account_id)
        if person is None:
            return
        if access is None:
            person.ki_url, person.ki_modell, person.ki_schluessel, person.ki_api = "", "", "", "openai"
        else:
            person.ki_api, person.ki_url, person.ki_modell = access.api, access.url, access.model
            person.ki_schluessel = access.key
        # nexmails Regel von vorher: ein Zugang, der unvollstaendig wird, schaltet sich ab, und die Erlaubnis fuer
        # eingegangene Post faellt mit (sie galt diesem Dienst).
        if not (person.ki_url and person.ki_modell):
            person.ki_aktiv = False
            person.ki_fremde_post = False
        self.db.flush()

    def own_access_urls(self) -> list[str]:
        return [url for url in self.db.scalars(select(Benutzer.ki_url).where(Benutzer.ki_url != "")) if url]

    # --- Versiegeln -----------------------------------------------------------------------------------------------

    def seal(self, text: str, context: str) -> str:
        return crypto.verschluesseln(text, context) if text else ""

    def unseal(self, sealed: str, context: str) -> str:
        if not sealed:
            return ""
        try:
            return crypto.entschluesseln(sealed, context)
        except Exception:  # noqa: BLE001 - ein anderes Geheimnis des Servers: dann eben leer
            return ""

    # --- Was ging hinaus ----------------------------------------------------------------------------------------------

    def add_event(self, event: Event) -> None:
        self.db.add(
            KiVorgang(
                benutzer_id=str(event.account_id),
                zeitpunkt=event.at.astimezone(UTC).replace(tzinfo=None),
                modell=event.model[:200],
                auftrag=event.task[:40],
                rumpf=event.sent,
                rein=event.chars,
                fehler="" if event.outcome == "ok" else event.outcome[:60],
                form=FORM_MODUL,
                an=event.to[:255],
            )
        )
        self.db.flush()

    def _event(self, zeile: KiVorgang) -> Event:
        gesendet = zeile.rumpf
        if zeile.form != FORM_MODUL and zeile.rumpf:
            # Eine Zeile von vorher: der Rumpf der Anfrage, in die Form des Moduls (System und Text) gebracht und mit
            # dessen Kontext versiegelt, damit „Was ging hinaus“ sie wie eine neue zeigt.
            try:
                rumpf = json.loads(crypto.entschluesseln(zeile.rumpf, _alter_kontext(zeile.benutzer_id)))
                teile = {m.get("role"): m.get("content", "") for m in rumpf.get("messages", [])}
                text = json.dumps({"system": teile.get("system", ""), "user": teile.get("user", "")}, ensure_ascii=False)
                gesendet = self.seal(text, _neuer_kontext(zeile.benutzer_id))
            except Exception:  # noqa: BLE001 - unlesbar: die Zeile bleibt, ohne Text
                gesendet = ""
        return Event(
            account_id=zeile.benutzer_id,
            at=zeile.zeitpunkt.replace(tzinfo=UTC),
            task=zeile.auftrag,
            to=zeile.an or "",
            model=zeile.modell,
            manual=True,
            chars=zeile.rein or 0,
            outcome=zeile.fehler or "ok",
            sent=gesendet,
            id=zeile.id,
        )

    def events(self, account_id: Any) -> list[Event]:
        zeilen = self.db.scalars(
            select(KiVorgang)
            .where(KiVorgang.benutzer_id == str(account_id))
            .order_by(KiVorgang.zeitpunkt.desc(), KiVorgang.id.desc())
        )
        return [self._event(z) for z in zeilen]

    def clear_events(self, account_id: Any) -> int:
        weg = self.db.execute(delete(KiVorgang).where(KiVorgang.benutzer_id == str(account_id))).rowcount
        self.db.flush()
        return int(weg or 0)

    def drop_events(self, before: datetime, *, keep: int) -> int:
        grenze = before.astimezone(UTC).replace(tzinfo=None)
        weg = self.db.execute(delete(KiVorgang).where(KiVorgang.zeitpunkt < grenze)).rowcount or 0
        for benutzer_id in set(self.db.scalars(select(KiVorgang.benutzer_id))):
            behalten = select(KiVorgang.id).where(KiVorgang.benutzer_id == benutzer_id)
            behalten = behalten.order_by(KiVorgang.zeitpunkt.desc(), KiVorgang.id.desc()).limit(keep)
            weg += (
                self.db.execute(
                    delete(KiVorgang).where(
                        KiVorgang.benutzer_id == benutzer_id, KiVorgang.id.not_in(behalten.scalar_subquery())
                    )
                ).rowcount
                or 0
            )
        self.db.flush()
        return int(weg)

    def commit(self) -> None:
        self.db.commit()


def uebernehmen(db: Session) -> list[str]:
    """Beim Start (``main``): was nie gespeichert war, einmal festschreiben (``settings.adopt``). Eine Datenbank mit
    Konten stammt von einer Fassung von vorher, deren Weg „Jedes Konto selbst“ war (K2)."""
    vorher = db.scalar(select(Benutzer.id).limit(1)) is not None
    return nexki.settings.adopt(store_fuer(db), CONFIG, older_mode="own" if vorher else None)


def store_fuer(db: Session) -> KiStore:
    return KiStore(db)


def entfaltet(db: Session, zeile: KiVorgang) -> dict | None:
    """Der Rumpf einer Zeile fuer den alten Weg ``GET /api/ki/vorgaenge``: eine Zeile von vorher wie gespeichert, eine
    des Moduls als Rumpf in der Form von vorher (Modell und die zwei Nachrichten); ``None``, wenn unlesbar oder leer."""
    if zeile.form != FORM_MODUL:
        try:
            return json.loads(crypto.entschluesseln(zeile.rumpf, _alter_kontext(zeile.benutzer_id)))
        except Exception:  # noqa: BLE001
            return None
    text = KiStore(db).unseal(zeile.rumpf, _neuer_kontext(zeile.benutzer_id))
    if not text:
        return None
    try:
        gesendet = json.loads(text)
    except ValueError:
        return None
    return {
        "model": zeile.modell,
        "messages": [
            {"role": "system", "content": gesendet.get("system", "")},
            {"role": "user", "content": gesendet.get("user", "")},
        ],
    }


__all__ = ["CONFIG", "FORM_MODUL", "KiStore", "SCHALTER", "entfaltet", "store_fuer"]
