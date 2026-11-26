"""Die Anbindung des Moduls mcp 1.1.0 (``app.vendor.nexmcp``) an nexmails Tabellen: ein Store, der zugleich der Store
von ``schluessel`` ist (``SchluesselStore``) und der von ``nexmcp``.

nexmail hatte vor dem Durchgang „Module“ kein MCP. Alles hier ist neu und liegt in eigenen Tabellen
(``models.McpSchluessel``, ``McpProgramm``, ``McpCode``, ``McpVerbraucht``, ``McpRecht``, ``McpAnfrage``); kein
bestehender Schluessel aendert sich. Die Einstellungen des Moduls (Programme erlauben, Hoechste Stufe, Gesperrte
Werkzeuge) stehen als JSON in ``einstellung`` unter ``mcp_<name>``; der Schalter „MCP-Zugang“ ist ``mcp_zugang``
(``SchluesselStore.switch("mcp")``, ab Werk aus).

⚠️ **Wer ruft, prueft ``schluessel``** (``nexschluessel.authenticate(…, ("mcp",))``): Vorsilbe, Hash, gesperrt,
abgelaufen, Konto gesperrt oder geloescht, zweiter Faktor geschuldet. Ein Konto ohne „KI erlaubt“ kommt als
``ai_allowed=False`` zurueck, das Modul antwortet dann 401 ``ai_rests`` (MCP-Entscheidung 10).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..db import einstellung_lesen, einstellung_schreiben
from ..models import (
    Benutzer,
    McpAnfrage,
    McpCode,
    McpProgramm,
    McpRecht,
    McpSchluessel,
    McpVerbraucht,
)
from ..vendor import nexschluessel
from ..vendor.nexmcp import Caller, Client, Code, Grant, Program
from ..vendor.nexmcp import Request as McpRequest
from .schluessel_store import KONFIGURATION, SchluesselStore

logger = logging.getLogger("nexmail.mcp")


def ki_erlaubt(db: Session, benutzer_id: str) -> bool:
    """„KI erlaubt“ des Kontos (Server › Konten › Verwalten), auch fuer KI-Programme von aussen (MCP-Entscheidung 10),
    so wie das Modul ki es fuer Programme fragt (``nexki.chain.for_programs``, K8: nur „KI erlaubt“ und nicht gesperrt;
    Hauptschalter und Dienst gelten fuer Programme nicht, dafuer gibt es „MCP-Zugang“)."""
    from ..vendor import nexki
    from . import ki_store

    return nexki.chain.for_programs(ki_store.store_fuer(db), benutzer_id)


def zugang_entfernen(db: Session, schluessel_id: str) -> None:
    """Ein MCP-Schluessel oder Programm ist weg, samt verbrauchten Token und Rechten je Werkzeug. Seine Rueckfragen
    bleiben stehen und scheitern beim Erlauben; was es geschrieben hat, bleibt."""
    db.execute(delete(McpVerbraucht).where(McpVerbraucht.schluessel_id == schluessel_id))
    db.execute(delete(McpRecht).where(McpRecht.schluessel_id == schluessel_id))
    db.execute(delete(McpSchluessel).where(McpSchluessel.id == schluessel_id))
    db.flush()


def programme_trennen(db: Session, benutzer_id: str) -> int:
    """E42: wird ein Konto gesperrt oder geloescht, enden seine verbundenen Programme (wie Sitzungen und Geraete); nach
    dem Entsperren verbinden sie sich neu. MCP-Schluessel von Hand ruhen nur (``holder.out``)."""
    ids = list(
        db.scalars(
            select(McpSchluessel.id).where(
                McpSchluessel.benutzer_id == benutzer_id, McpSchluessel.programm_id.is_not(None)
            )
        )
    )
    for schluessel_id in ids:
        zugang_entfernen(db, schluessel_id)
    return len(ids)


def _json(wert: Any) -> str | None:
    return None if wert is None else json.dumps([str(a) for a in wert])


def _liste(text: str | None) -> list[Any] | None:
    return None if text is None else json.loads(text)


class McpStore(SchluesselStore):
    """``nexschluessel.Store`` und ``nexmcp.Store`` ueber nexmails Tabellen, innerhalb einer Sitzung."""

    # --- wer ruft ----------------------------------------------------------------------------------------------

    def _caller(self, key: Any, holder: Any) -> Caller:
        person = self.db.get(Benutzer, str(key.account_id))
        return Caller(
            key_id=key.id,
            key_name=key.name or "",
            account_id=key.account_id,
            account_name=holder.name,
            level=key.right,
            areas=key.areas,
            options={name: on for name, on in key.options.items() if name == "mailtext"},
            rights=self.key_rights(key.id),
            program=key.program,
            admin=bool(person and person.ist_betreiber),
            ai_allowed=self.ai_allowed(key.account_id),
            account=person,
        )

    def caller(self, token: str) -> Caller | None:
        try:
            gefunden = nexschluessel.authenticate(self, KONFIGURATION, token, ("mcp",))
        except nexschluessel.KeyRefused as abgewiesen:
            if abgewiesen.code != "ai_rests":
                return None
            key = self.key_by_hash(nexschluessel.digest(token))
            holder = self.holder(key.account_id) if key else None
            return self._caller(key, holder) if key and holder else None
        return self._caller(gefunden.key, gefunden.holder)

    def caller_of_key(self, key_id: Any) -> Caller | None:
        key = self.key(key_id)
        if key is None or key.kind != "mcp":
            return None
        holder = self.holder(key.account_id)
        if holder is None or holder.out or key.blocked_at is not None or self.keys_wait(key.account_id):
            return None
        return self._caller(key, holder)

    def count_keys(self, account_id: Any) -> int:
        anzahl = self.db.scalar(
            select(func.count()).select_from(McpSchluessel).where(McpSchluessel.benutzer_id == str(account_id))
        )
        return int(anzahl or 0)

    def account_may(self, account_id: Any) -> bool:
        holder = self.holder(account_id)
        return holder is not None and not holder.out and not self.keys_wait(account_id)

    def key_areas(self, account_id: Any) -> list[dict[str, Any]]:
        return [{"id": area.id, "name": area.name} for area in self.areas_of(account_id, "mcp")]

    # --- Einstellungen -----------------------------------------------------------------------------------------

    def mcp_on(self) -> bool:
        return self.switch("mcp")

    def setting(self, name: str) -> Any:
        wert = einstellung_lesen(self.db, f"mcp_{name}")
        return json.loads(wert) if wert else None

    def set_setting(self, name: str, value: Any) -> None:
        einstellung_schreiben(self.db, f"mcp_{name}", json.dumps(value))

    def key_rights(self, key_id: Any) -> dict[str, str]:
        zeilen = self.db.scalars(select(McpRecht).where(McpRecht.schluessel_id == str(key_id)))
        return {z.werkzeug: z.wert for z in zeilen}

    def set_key_rights(self, key_id: Any, rights: dict[str, str]) -> None:
        self.db.execute(delete(McpRecht).where(McpRecht.schluessel_id == str(key_id)))
        for werkzeug, wert in rights.items():
            self.db.add(McpRecht(schluessel_id=str(key_id), werkzeug=werkzeug, wert=wert))
        self.db.flush()

    # --- OAuth: Programme ----------------------------------------------------------------------------------------

    def _client(self, z: McpProgramm) -> Client:
        in_benutzung = (
            self.db.scalar(select(McpSchluessel.id).where(McpSchluessel.programm_id == z.id).limit(1)) is not None
        )
        return Client(
            id=z.id,
            name=z.name,
            redirect_uris=tuple(json.loads(z.adressen_json or "[]")),
            created_at=z.angelegt,
            last_used_at=z.zuletzt_benutzt,
            in_use=in_benutzung,
        )

    def add_client(self, client: Client) -> None:
        self.db.add(
            McpProgramm(
                id=client.id,
                name=client.name[:200],
                adressen_json=json.dumps(list(client.redirect_uris)),
                angelegt=client.created_at,
            )
        )
        self.db.flush()

    def client(self, client_id: str) -> Client | None:
        z = self.db.get(McpProgramm, client_id)
        return self._client(z) if z is not None else None

    def clients(self) -> list[Client]:
        return [self._client(z) for z in self.db.scalars(select(McpProgramm))]

    def remove_client(self, client_id: str) -> None:
        self.db.execute(delete(McpProgramm).where(McpProgramm.id == client_id))

    def touch_client(self, client_id: str, when: datetime) -> None:
        self.db.execute(update(McpProgramm).where(McpProgramm.id == client_id).values(zuletzt_benutzt=when))

    def add_code(self, code: Code) -> None:
        self.db.add(
            McpCode(
                code_hash=code.code_hash,
                programm_id=code.client_id,
                benutzer_id=str(code.account_id),
                adresse=code.redirect_uri,
                challenge=code.challenge,
                stufe=code.level,
                konten_json=_json(code.areas),
                extras_json=json.dumps(code.options),
                laeuft_ab=code.expires_at,
                resource=code.resource,
            )
        )
        self.db.flush()

    def take_code(self, code_hash: str) -> Code | None:
        z = self.db.get(McpCode, code_hash)
        if z is None:
            return None
        weg = self.db.execute(delete(McpCode).where(McpCode.code_hash == code_hash)).rowcount
        if weg != 1:
            return None
        return Code(
            code_hash=z.code_hash,
            client_id=z.programm_id,
            account_id=z.benutzer_id,
            redirect_uri=z.adresse,
            challenge=z.challenge,
            level=z.stufe,
            areas=_liste(z.konten_json),
            options=json.loads(z.extras_json or "{}"),
            expires_at=z.laeuft_ab,
            resource=z.resource or "",
        )

    def has_program(self, account_id: Any, client_id: str) -> bool:
        return (
            self.db.scalar(
                select(McpSchluessel.id).where(
                    McpSchluessel.benutzer_id == str(account_id), McpSchluessel.programm_id == client_id
                )
            )
            is not None
        )

    def program_signed_in(
        self,
        account_id: Any,
        client: Client,
        *,
        level: str,
        areas: list[Any] | None,
        options: dict[str, bool],
        grant: Grant,
        now: datetime,
    ) -> Any:
        z = self.db.scalar(
            select(McpSchluessel).where(
                McpSchluessel.benutzer_id == str(account_id), McpSchluessel.programm_id == client.id
            )
        )
        if z is None:
            z = McpSchluessel(benutzer_id=str(account_id), name=client.name[:200], programm_id=client.id, angelegt=now)
            self.db.add(z)
        z.stufe = level
        z.konten_json = _json(areas)
        z.extras_json = json.dumps({"mailtext": bool(options.get("mailtext"))})
        z.schluessel_hash = grant.access_hash
        z.praefix = grant.access_prefix
        z.laeuft_ab = grant.access_expires
        z.erneuerung_hash = grant.refresh_hash
        z.angemeldet_am = now
        z.erneuert_am = now
        self.db.flush()
        return z.id

    def _program(self, z: McpSchluessel | None) -> Program | None:
        if z is None or z.programm_id is None:
            return None
        angemeldet = z.angemeldet_am or z.angelegt
        return Program(
            key_id=z.id,
            account_id=z.benutzer_id,
            client_id=z.programm_id,
            signed_in_at=angemeldet,
            refreshed_at=z.erneuert_am or angemeldet,
        )

    def program_by_refresh(self, refresh_hash: str) -> Program | None:
        return self._program(
            self.db.scalar(
                select(McpSchluessel).where(
                    McpSchluessel.erneuerung_hash == refresh_hash, McpSchluessel.programm_id.is_not(None)
                )
            )
        )

    def program_of_token(self, token_hash: str) -> Program | None:
        return self._program(
            self.db.scalar(
                select(McpSchluessel).where(
                    McpSchluessel.programm_id.is_not(None),
                    (McpSchluessel.erneuerung_hash == token_hash) | (McpSchluessel.schluessel_hash == token_hash),
                )
            )
        )

    def program_refreshed(self, key_id: Any, grant: Grant, now: datetime) -> None:
        self.db.execute(
            update(McpSchluessel)
            .where(McpSchluessel.id == str(key_id))
            .values(
                schluessel_hash=grant.access_hash,
                praefix=grant.access_prefix,
                laeuft_ab=grant.access_expires,
                erneuerung_hash=grant.refresh_hash,
                erneuert_am=now,
            )
        )

    def spend(self, key_id: Any, token_hash: str, keep: int) -> None:
        if self.db.scalar(select(McpVerbraucht.nr).where(McpVerbraucht.token_hash == token_hash)) is None:
            self.db.add(McpVerbraucht(token_hash=token_hash, schluessel_id=str(key_id)))
            self.db.flush()
        behalten = select(McpVerbraucht.nr).where(McpVerbraucht.schluessel_id == str(key_id))
        behalten = behalten.order_by(McpVerbraucht.nr.desc()).limit(keep)
        self.db.execute(
            delete(McpVerbraucht).where(
                McpVerbraucht.schluessel_id == str(key_id), McpVerbraucht.nr.not_in(behalten.scalar_subquery())
            )
        )

    def spent_by(self, token_hash: str) -> Any:
        return self.db.scalar(select(McpVerbraucht.schluessel_id).where(McpVerbraucht.token_hash == token_hash))

    def end_program(self, key_id: Any) -> None:
        zugang_entfernen(self.db, str(key_id))

    # --- Rueckfragen -----------------------------------------------------------------------------------------------

    @staticmethod
    def _request(z: McpAnfrage | None) -> McpRequest | None:
        if z is None:
            return None
        return McpRequest(
            id=z.id,
            account_id=z.benutzer_id,
            key_id=z.schluessel_id,
            key_name=z.schluessel_name,
            tool=z.werkzeug,
            arguments=z.argumente,
            digest=z.pruefsumme,
            status=z.stand,
            created_at=z.angelegt,
            expires_at=z.laeuft_ab,
            decided_at=z.entschieden_am,
            decided_by=z.entschieden_von or "",
            result=z.ergebnis,
            summary=z.zusammenfassung or "",
            dangerous=bool(z.gefaehrlich),
        )

    def add_request(self, request: McpRequest) -> McpRequest:
        z = McpAnfrage(
            benutzer_id=str(request.account_id),
            schluessel_id=str(request.key_id),
            schluessel_name=request.key_name[:200],
            werkzeug=request.tool,
            argumente=request.arguments,
            pruefsumme=request.digest,
            stand=request.status,
            angelegt=request.created_at,
            laeuft_ab=request.expires_at,
            zusammenfassung=request.summary,
            gefaehrlich=request.dangerous,
        )
        self.db.add(z)
        self.db.flush()
        gefunden = self._request(z)
        assert gefunden is not None
        return gefunden

    def request(self, request_id: Any) -> McpRequest | None:
        try:
            nummer = int(request_id)
        except (TypeError, ValueError):
            return None
        return self._request(self.db.get(McpAnfrage, nummer))

    def requests_of(self, account_id: Any) -> list[McpRequest]:
        zeilen = self.db.scalars(
            select(McpAnfrage).where(McpAnfrage.benutzer_id == str(account_id)).order_by(McpAnfrage.id.desc())
        )
        return [r for z in zeilen if (r := self._request(z)) is not None]

    def count_waiting(self, account_id: Any, key_id: Any = None) -> int:
        frage = select(func.count()).select_from(McpAnfrage).where(
            McpAnfrage.benutzer_id == str(account_id), McpAnfrage.stand == "waiting"
        )
        if key_id is not None:
            frage = frage.where(McpAnfrage.schluessel_id == str(key_id))
        return int(self.db.scalar(frage) or 0)

    def claim(self, request_id: Any, status: str, *, now: datetime, by: str = "") -> bool:
        geaendert = self.db.execute(
            update(McpAnfrage)
            .where(McpAnfrage.id == int(request_id), McpAnfrage.stand == "waiting")
            .values(stand=status, entschieden_am=now, entschieden_von=by)
        )
        return geaendert.rowcount == 1

    def finish(self, request_id: Any, status: str, result: str | None, now: datetime) -> None:
        self.db.execute(
            update(McpAnfrage)
            .where(McpAnfrage.id == int(request_id))
            .values(stand=status, ergebnis=result, entschieden_am=now)
        )

    def expire(self, now: datetime) -> int:
        geaendert = self.db.execute(
            update(McpAnfrage)
            .where(McpAnfrage.stand == "waiting", McpAnfrage.laeuft_ab <= now)
            .values(stand="expired", entschieden_am=now)
        )
        return int(geaendert.rowcount or 0)


def store_fuer(db: Session) -> McpStore:
    return McpStore(db)


__all__ = ["McpStore", "ki_erlaubt", "programme_trennen", "store_fuer", "zugang_entfernen"]
