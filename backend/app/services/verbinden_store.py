"""Die Anbindung des Moduls verbinden 0.1.8 (``app.vendor.nexverbinden``) an nexmail: ``AppConfig``, der Store über
die Tabellen des Moduls (``models.Vb…``, Vorlage ``verbinden_partner.SCHEMA``) und ``anfragen``, mit dem nexmails
Gast-Code (nextasks, nextime) über eine per Klick gemachte Verbindung fragt.

⚠️ **Alte Verbindungen merken nichts**, bis das Konto per Klick verbindet, trennt oder ablehnt (verbinden 0.2.0, B9):
``aufgabenverbindung`` (nextasks) und ``nextime_verbindung`` bleiben bis dahin, wie sie sind; das Modul zeigt sie
(``legacy``), danach endet die von Hand eingetragene (``forget_legacy``). Eine Klick-Verbindung legt dieselbe Zeile an wie das Verbinden von Hand,
nur steht im Zugang statt eines Schlüssels ``ueber`` (das Konto der Verbindung): Listen- und Kalenderwahl, Abgleich,
Abhaken und Fehlerzustände laufen damit unverändert (V18), nur die einzelne Anfrage geht über ``nexverbinden.call``.

⚠️ **nexmail ist fast nur Gast.** Es gewährt genau einen Zweck (seit verbinden 0.1.13): ``mails.about`` an nexfolk,
wie viele Mails es mit einer Person gibt und wann die letzte kam (``post_mit_person``, Bereiche = Postfächer); sonst
hält ein Partner ein Token, das nur ``hello`` und ``revoke`` öffnet. V20: Karten nur für Partner, die nexmail wirklich nutzt
(``AppConfig.in_use`` = ``GENUTZT``); die übrigen Partner des Katalogs zeigt nexmail erst, wenn ihre Nutzung gebaut ist.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__, crypto
from ..config import get_settings
from ..db import einstellung_lesen, einstellung_schreiben
from ..models import Aufgabenverbindung, Benutzer, NextimeVerbindung
from ..vendor import nexverbinden

logger = logging.getLogger("nexmail.verbinden")

#: V20: die Partner, die nexmail über die Klick-Verbindung wirklich nutzt.
GENUTZT = ("nextasks", "nextime", "nexfolk", "nexpaper")

CONFIG = nexverbinden.AppConfig(
    app_name="nexmail",
    version=__version__,
    access_prefix="nxv_",
    refresh_prefix="nxvr_",
    code_prefix="nxvc_",
    in_use=GENUTZT,
)

_KONTEXT = "verbinden"


def _iso(wert: datetime | None) -> str | None:
    return wert.isoformat() if wert else None


def _zeit(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _liste(text: str | None) -> Any:
    return json.loads(text) if text else None


class VerbindenStore:
    """``nexverbinden.Store`` über die Tabellen des Moduls in nexmails Datenbank, innerhalb einer Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _sql(self, sql: str, werte: tuple = ()) -> Any:
        return self.db.connection().exec_driver_sql(sql, werte)

    # --- Verbindungen ------------------------------------------------------------------------------------------------

    def _connection(self, z: Any) -> Any:
        if z is None:
            return None
        return nexverbinden.Connection(
            id=z["id"], account_id=z["account_id"], partner=z["partner"], partner_base=z["partner_base"],
            partner_account=z["partner_account"], uses=tuple(json.loads(z["uses"])),
            grants=tuple(json.loads(z["grants"])), areas_granted=_liste(z["areas_granted"]),
            areas_used=_liste(z["areas_used"]), held=z["held"], issued_access_hash=z["issued_access_hash"],
            issued_refresh_hash=z["issued_refresh_hash"], issued_access_expires=_zeit(z["issued_access_expires"]),
            created_at=_zeit(z["created_at"]), used_at=_zeit(z["used_at"]), ok_at=_zeit(z["ok_at"]),
            state=z["state"], stale_since=_zeit(z["stale_since"]), problem=z["problem"],
            partner_version=z["partner_version"],
        )  # fmt: skip

    def _eine(self, sql: str, werte: tuple) -> Any:
        return self._connection(self._sql(sql, werte).mappings().first())

    def connections(self, account_id: Any) -> list[Any]:
        zeilen = self._sql("SELECT * FROM vb_connections WHERE account_id = ? ORDER BY partner", (str(account_id),))
        return [self._connection(z) for z in zeilen.mappings().all()]

    def connection(self, account_id: Any, partner: str) -> Any:
        return self._eine(
            "SELECT * FROM vb_connections WHERE account_id = ? AND partner = ?", (str(account_id), partner)
        )

    def by_issued_access(self, token_hash: str) -> Any:
        return self._eine("SELECT * FROM vb_connections WHERE issued_access_hash = ?", (token_hash,))

    def by_issued_refresh(self, token_hash: str) -> Any:
        return self._eine("SELECT * FROM vb_connections WHERE issued_refresh_hash = ?", (token_hash,))

    def save(self, c: Any) -> None:
        self._sql(
            "INSERT OR REPLACE INTO vb_connections (id, account_id, partner, partner_base, partner_account, uses,"
            " grants, areas_granted, areas_used, held, issued_access_hash, issued_refresh_hash,"
            " issued_access_expires, created_at, used_at, ok_at, state, stale_since, problem, partner_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                c.id, str(c.account_id), c.partner, c.partner_base, c.partner_account, json.dumps(list(c.uses)),
                json.dumps(list(c.grants)), json.dumps(c.areas_granted) if c.areas_granted is not None else None,
                json.dumps(c.areas_used) if c.areas_used is not None else None, c.held, c.issued_access_hash,
                c.issued_refresh_hash, _iso(c.issued_access_expires), _iso(c.created_at), _iso(c.used_at),
                _iso(c.ok_at), c.state, _iso(c.stale_since), c.problem, c.partner_version or "",
            ),
        )  # fmt: skip

    def remove(self, connection_id: str) -> None:
        self._sql("DELETE FROM vb_connections WHERE id = ?", (connection_id,))
        self._sql("DELETE FROM vb_spent WHERE connection_id = ?", (connection_id,))

    # --- Anläufe und Codes ---------------------------------------------------------------------------------------------

    def add_pending(self, p: Any) -> None:
        self._sql(
            "INSERT INTO vb_pending VALUES (?,?,?,?,?,?,?)",
            (p.state_hash, str(p.account_id), p.partner, p.partner_base, p.verifier,
             json.dumps(p.areas_granted) if p.areas_granted is not None else None, _iso(p.created_at)),
        )  # fmt: skip

    def take_pending(self, state_hash: str) -> Any:
        z = self._sql("SELECT * FROM vb_pending WHERE state_hash = ?", (state_hash,)).mappings().first()
        if z is None:
            return None
        self._sql("DELETE FROM vb_pending WHERE state_hash = ?", (state_hash,))
        return nexverbinden.Pending(
            state_hash=z["state_hash"], account_id=z["account_id"], partner=z["partner"],
            partner_base=z["partner_base"], verifier=z["verifier"], areas_granted=_liste(z["areas_granted"]),
            created_at=_zeit(z["created_at"]),
        )  # fmt: skip

    def add_code(self, c: Any) -> None:
        self._sql(
            "INSERT INTO vb_codes VALUES (?,?,?,?,?,?,?,?)",
            (c.code_hash, str(c.account_id), c.partner, c.partner_base, c.redirect_uri, c.challenge,
             json.dumps(c.areas_granted) if c.areas_granted is not None else None, _iso(c.expires_at)),
        )  # fmt: skip

    def take_code(self, code_hash: str) -> Any:
        z = self._sql("SELECT * FROM vb_codes WHERE code_hash = ?", (code_hash,)).mappings().first()
        if z is None:
            return None
        self._sql("DELETE FROM vb_codes WHERE code_hash = ?", (code_hash,))
        return nexverbinden.Code(
            code_hash=z["code_hash"], account_id=z["account_id"], partner=z["partner"],
            partner_base=z["partner_base"], redirect_uri=z["redirect_uri"], challenge=z["challenge"],
            areas_granted=_liste(z["areas_granted"]), expires_at=_zeit(z["expires_at"]),
        )  # fmt: skip

    # --- Verbrauchtes, Wartendes ------------------------------------------------------------------------------------

    def spend(self, connection_id: str, token_hash: str, keep: int) -> None:
        nr = self._sql("SELECT COALESCE(MAX(at), 0) + 1 FROM vb_spent").scalar()
        self._sql("INSERT OR REPLACE INTO vb_spent VALUES (?,?,?)", (token_hash, connection_id, nr))
        self._sql(
            "DELETE FROM vb_spent WHERE connection_id = ? AND at NOT IN "
            "(SELECT at FROM vb_spent WHERE connection_id = ? ORDER BY at DESC LIMIT ?)",
            (connection_id, connection_id, keep),
        )

    def spent_by(self, token_hash: str) -> str | None:
        return self._sql("SELECT connection_id FROM vb_spent WHERE token_hash = ?", (token_hash,)).scalar()

    def revoke_later(self, account_id: Any, partner_base: str, sealed_token: str, now: datetime) -> None:
        self._sql(
            "INSERT INTO vb_waiting (account_id, partner_base, token, since) VALUES (?,?,?,?)",
            (str(account_id), partner_base, sealed_token, _iso(now)),
        )

    def waiting(self) -> list[Any]:
        zeilen = self._sql("SELECT * FROM vb_waiting ORDER BY id").mappings().all()
        return [nexverbinden.Waiting(z["id"], z["partner_base"], z["token"], _zeit(z["since"])) for z in zeilen]

    def done_waiting(self, waiting_id: Any) -> None:
        self._sql("DELETE FROM vb_waiting WHERE id = ?", (waiting_id,))

    # --- Konto und App ----------------------------------------------------------------------------------------------

    def account_may(self, account_id: Any) -> bool:
        person = self.db.get(Benutzer, str(account_id))
        return person is not None and person.gesperrt_seit is None and person.geloescht_am is None

    def account_name(self, account_id: Any) -> str:
        person = self.db.get(Benutzer, str(account_id))
        return person.benutzername if person else "?"

    def account_card(self, account_id: Any) -> dict[str, Any]:
        """verbinden 0.1.8 (B1): wer auf der Zustimmungsseite angemeldet ist, so wie die Profilzeile es zeigt.

        Anzeigename, Benutzername und die Adresse des eigenen Profilbilds genau wie ``profilbildAdresse`` in
        ``components/Profilbild.tsx`` (Vorbau, ``/api/auth/profilbild/<id>?v=<Stand>``); ohne Bild ``None``, dann
        zeigt das Modul den Buchstaben nach derselben Regel wie nexmail. nexmail hat keine Farbe der Person
        (der Platzhalter rechnet seinen Ton aus dem Namen), also ``None``."""
        person = self.db.get(Benutzer, str(account_id))
        if person is None:
            return {"name": "", "username": "?", "picture": None, "color": None}
        bild = None
        if person.profilbild_am is not None:
            stand = quote(person.profilbild_am.isoformat(), safe="")
            bild = f"{get_settings().url_base}/api/auth/profilbild/{quote(person.id, safe='')}?v={stand}"
        return {"name": person.anzeigename, "username": person.benutzername, "picture": bild, "color": None}

    def areas(self, account_id: Any) -> list[dict[str, Any]]:
        """Die Postfächer des Kontos (verbinden 0.1.13): Für ``mails.about`` wählt die Zustimmung, in welchen nexfolk
        Mails mit einer Person zählen darf (``post_mit_person``)."""
        from ..models import Konto

        frage = select(Konto).where(Konto.benutzer_id == str(account_id)).order_by(Konto.reihenfolge, Konto.angelegt)
        return [{"id": k.id, "name": k.anzeigename or k.adresse} for k in self.db.scalars(frage)]

    def legacy(self, account_id: Any) -> list[Any]:
        """Die von Hand eingetragenen Verbindungen (Adresse plus API-Schlüssel), wie sie sind."""
        from . import aufgabenziele, nextimeverbindung

        alte = []
        for v in self.db.scalars(
            select(Aufgabenverbindung).where(
                Aufgabenverbindung.benutzer_id == str(account_id), Aufgabenverbindung.art == "nextasks"
            )
        ):
            try:
                zugang = aufgabenziele._nextasks_zugang(v)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                continue
            if zugang.ueber:
                continue
            alte.append(nexverbinden.Legacy("nextasks", zugang.url, zugang.token[:8], problem=_problem(v.letzter_fehler)))
        nt = self.db.scalar(select(NextimeVerbindung).where(NextimeVerbindung.benutzer_id == str(account_id)))
        if nt is not None:
            try:
                zugang = nextimeverbindung.zugang(nt)
            except Exception:  # noqa: BLE001
                zugang = None
            if zugang is not None and zugang.token and not zugang.ueber:
                alte.append(nexverbinden.Legacy("nextime", zugang.url, zugang.token[:8], problem=_problem(nt.letzter_fehler)))
        return [a for a in alte if a.partner in GENUTZT]

    def forget_legacy(self, account_id: Any, partner: str) -> None:
        """verbinden 0.2.0 (B9, V56): die von Hand eingetragene Verbindung mit ``partner`` endet (nach einer
        Klick-Verbindung, nach „Trennen“, nach „Ablehnen“), so dass ``legacy`` sie nicht mehr nennt.

        Steht eine Klick-Verbindung, über die nexmail den Partner nutzt, geht die Zeile auf sie über (``ueber`` statt
        Schlüssel, wie ``ueber_klick``): Listen, Kalenderwahl und Aufgaben mit Abzug bleiben. Sonst löst nexmail sie
        wie beim Trennen von Hand. Zeilen, die schon über die Klick-Verbindung laufen, bleiben. Nie committen (das
        Modul committet), nie die eigenen API-Schlüssel anfassen (``retire_key``)."""
        from ..models import Aufgabe
        from . import aufgabenziele, nextasks, nextime, nextimeverbindung

        person = self.db.get(Benutzer, str(account_id))
        if person is None or partner not in ("nextasks", "nextime"):
            return
        klick = self.connection(account_id, partner)
        uebernehmen = klick is not None and bool(klick.uses)
        if partner == "nextasks":
            for v in self.db.scalars(
                select(Aufgabenverbindung).where(
                    Aufgabenverbindung.benutzer_id == person.id, Aufgabenverbindung.art == "nextasks"
                )
            ).all():
                try:
                    alt = aufgabenziele._nextasks_zugang(v)  # noqa: SLF001
                except Exception:  # noqa: BLE001 - unlesbar zählt wie von Hand
                    alt = None
                if alt is not None and alt.ueber:
                    continue
                if uebernehmen:
                    zugang = nextasks.Zugang(url=klick.partner_base.rstrip("/"), token="", ueber=person.id)
                    v.zugang = crypto.verschluesseln(
                        nextasks.zugang_schreiben(zugang), aufgabenziele._kontext(v.id)  # noqa: SLF001
                    )
                    v.letzter_fehler = ""
                    continue
                for aufgabe in self.db.scalars(select(Aufgabe).where(Aufgabe.verbindung_id == v.id)):
                    aufgabe.verbindung_id = None
                if person.aufgaben_standard.split(":", 1)[0] == v.id:
                    person.aufgaben_standard = ""
                self.db.delete(v)
                self.db.flush()
                if not aufgabenziele.verbindungen(self.db, person):
                    person.aufgaben_eigene = True  # wie ``aufgabenziele.trennen`` (MAIL-2 EC-18)
        else:
            nt = nextimeverbindung.verbindung(self.db, person)
            if nt is None:
                return
            try:
                alt = nextimeverbindung.zugang(nt)
            except Exception:  # noqa: BLE001 - unlesbar zählt wie von Hand
                alt = None
            if alt is not None and alt.ueber:
                return
            if uebernehmen:
                url = klick.partner_base.rstrip("/")
                if alt is None or alt.url != url:
                    nt.sichtbar = "{}"
                zugang = nextime.Zugang(url=url, token="", ueber=person.id)
                nt.zugang = crypto.verschluesseln(
                    nextime.zugang_schreiben(zugang), nextimeverbindung._kontext(nt.id)  # noqa: SLF001
                )
                nt.letzter_fehler = ""
            else:
                self.db.delete(nt)
        self.db.flush()
        logger.info("The older connection with %s typed in by hand ended.", partner)

    def retire_key(self, token: str) -> bool:
        """Ein alter API-Schlüssel nexmails (``nxm_``), den eine andere App von Hand eingetragen hatte, endet von
        selbst, sobald diese App neu verbunden hat (V15). Nur genau dieser Schlüssel."""
        import hashlib

        from ..models import ApiSchluessel

        zeile = self.db.scalar(
            select(ApiSchluessel).where(ApiSchluessel.schluessel_hash == hashlib.sha256(token.encode()).hexdigest())
        )
        if zeile is None:
            return False
        self.db.delete(zeile)
        self.db.flush()
        logger.info("An older API key ended itself after a new connection.")
        return True

    def setting(self, name: str) -> Any:
        wert = einstellung_lesen(self.db, f"vb_{name}")
        return json.loads(wert) if wert else None

    def set_setting(self, name: str, value: Any) -> None:
        einstellung_schreiben(self.db, f"vb_{name}", json.dumps(value))

    def local_allowed(self) -> bool:
        return bool(self.setting("connections_local_network"))

    def set_local_allowed(self, on: bool) -> None:
        """verbinden 0.1.4 (V-12): der Haken „Verbindungen ins eigene Netz“ der Betreiberkarte, dieselbe Einstellung,
        die ``local_allowed`` liest. nexmail hat dafür keinen eigenen Schalter."""
        self.set_setting("connections_local_network", bool(on))

    def seal(self, text: str) -> str:
        return crypto.verschluesseln(text, _KONTEXT)

    def unseal(self, sealed: str) -> str:
        return crypto.entschluesseln(sealed, _KONTEXT)

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def _problem(fehler: str) -> str | None:
    if not fehler:
        return None
    return "unreachable" if "erreichbar" in fehler or "zeit" in fehler else "refused"


def store_fuer(db: Session) -> VerbindenStore:
    return VerbindenStore(db)


def anfragen(partner: str, konto_id: str, methode: str, pfad: str, *, params: Any = None, rumpf: Any = None) -> httpx.Response:
    """Eine Anfrage an den Partner über die Klick-Verbindung des Kontos (``nexverbinden.call``), als ``httpx.Response``,
    damit nexmails Gast-Code (Absagen, JSON) unverändert weiterläuft. ``None`` als Antwort gibt es nicht: nicht
    erreichbar wirft ``Unerreichbar``; getrennt, ruhend oder abgeschaltet kommen als 401 mit der Kennung des Moduls."""
    from ..db import SessionLocal

    if isinstance(params, list):
        params = dict(params)
    with SessionLocal() as db:
        store = store_fuer(db)
        try:
            antwort = nexverbinden.call(
                store, CONFIG, konto_id, partner, methode, pfad, datetime.now(UTC), body=rumpf, params=params
            )
        except nexverbinden.Refused as abgelehnt:
            store.commit()
            if abgelehnt.code == "unreachable":
                raise Unerreichbar(partner) from abgelehnt
            return httpx.Response(401, json={"detail": {"code": abgelehnt.code}})
        store.commit()
    inhalt = json.dumps(antwort.data).encode() if antwort.data is not None else b""
    return httpx.Response(antwort.status, content=inhalt, headers={"content-type": "application/json"})


class Unerreichbar(Exception):
    """Der Partner antwortet nicht (die Karte sagt „nicht erreichbar seit …“)."""


class Abgelehnt(Exception):
    """Die Klick-Verbindung trägt nicht (Kennung des Moduls: ``not_connected``, ``refused``, ``resting``,
    ``partner_off``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def zugriff(partner: str, konto_id: str, *, neu: bool = False) -> nexverbinden.Access:
    """V18 (verbinden 0.1.2): Adresse und frisches Token der Klick-Verbindung für nexmails eigene Anfragen, wo
    ``call`` nicht passt, weil kein JSON hin- und zurückgeht: CardDAV mit nexfolk, eine Datei an nexpaper. ``neu``
    nach einem 401 des Partners. Danach sagt ``gelaufen`` dem Modul, wie die Anfrage ausging."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        store = store_fuer(db)
        try:
            zugang = nexverbinden.access(store, CONFIG, konto_id, partner, datetime.now(UTC), force=neu)
        except nexverbinden.Refused as abgelehnt:
            store.commit()
            if abgelehnt.code == "unreachable":
                raise Unerreichbar(partner) from abgelehnt
            raise Abgelehnt(abgelehnt.code) from abgelehnt
        store.commit()
    return zugang


def eigenes_netz_erlaubt() -> bool:
    """Der Haken „Verbindungen ins eigene Netz“ der Betreiberkarte (verbinden 0.1.4), für nexmails eigene Anfragen über
    eine Klick-Verbindung (eine Datei an nexpaper): dieselbe Freigabe, mit der die Verbindung selbst ins eigene Netz
    darf, nicht die für Kalender und Webhooks (``netzfreigabe``)."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        return store_fuer(db).local_allowed()


def gelaufen(partner: str, konto_id: str, problem: str | None = None) -> None:
    """Wie nexmails eigene Anfrage über die Klick-Verbindung ausging, für die Karte (``nexverbinden.reached``):
    ``None`` beantwortet, ``unreachable``, oder die Absage des Partners (``token_invalid`` nach dem zweiten 401)."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        store = store_fuer(db)
        nexverbinden.reached(store, konto_id, partner, datetime.now(UTC), problem=problem)
        store.commit()


def ueber_klick(partner: str, store: Any, konto_id: Any) -> None:
    """``on_connected``: nach dem Verbinden per Klick legt nexmail die Zeile an, die das Verbinden von Hand anlegt
    (nextasks: ``aufgabenverbindung``, nextime: ``nextime_verbindung``), mit ``ueber`` statt eines Schlüssels. Gibt es
    schon eine von Hand, bleibt sie (alte Verbindungen merken nichts); „Neu verbinden“ ersetzt ihren Zugang."""
    from . import aufgabenziele, nextimeverbindung

    db: Session = store.db
    person = db.get(Benutzer, str(konto_id))
    verbindung = store.connection(konto_id, partner)
    if person is None or verbindung is None:
        return
    store.commit()
    try:
        if partner == "nextasks":
            aufgabenziele.nextasks_ueber_klick(db, person, verbindung.partner_base)
        elif partner == "nextime":
            nextimeverbindung.ueber_klick(db, person, verbindung.partner_base)
        elif partner == "nexfolk":
            from . import adressbuchabgleich

            adressbuchabgleich.nexfolk_ueber_klick(db, person, verbindung.partner_base)
        # nexpaper: keine Zeile, „Als Dokument an nexpaper“ fragt die Verbindung bei jedem Anhang selbst.
    except Exception:  # noqa: BLE001 - die Verbindung steht; die Karte zeigt, wenn die erste Anfrage scheitert
        logger.warning("Setting up the use of a connection failed partner=%s", partner, exc_info=True)


def ueber_getrennt(partner: str, store: Any, konto_id: Any) -> None:
    """``on_disconnected`` (verbinden 0.1.4, V-13, Frage 11): eine Klick-Verbindung endete, hier mit „Trennen“ oder beim
    Partner. nexmail löst dann seine Zeilen dieser Verbindung wie beim Trennen von Hand: die nextasks-Verbindung (Abzüge
    der Aufgaben bleiben, die eigene Liste geht wieder an), die nextime-Verbindung, die Adressbücher von nexfolk.
    Verbindungen von Hand (ohne ``ueber``) bleiben, wie sie sind."""
    from ..models import Adressbuch
    from . import adressbuecher, aufgabenziele, nextimeverbindung

    db: Session = store.db
    person = db.get(Benutzer, str(konto_id))
    if person is None:
        return
    store.commit()
    try:
        if partner == "nextasks":
            for v in db.scalars(
                select(Aufgabenverbindung).where(
                    Aufgabenverbindung.benutzer_id == person.id, Aufgabenverbindung.art == "nextasks"
                )
            ).all():
                if aufgabenziele._nextasks_zugang(v).ueber:  # noqa: SLF001
                    aufgabenziele.trennen(db, person, v.id)
        elif partner == "nextime":
            nt = db.scalar(select(NextimeVerbindung).where(NextimeVerbindung.benutzer_id == person.id))
            if nt is not None and nextimeverbindung.zugang(nt).ueber:
                nextimeverbindung.trennen(db, person)
        elif partner == "nexfolk":
            for buch in db.scalars(
                select(Adressbuch).where(Adressbuch.benutzer_id == person.id, Adressbuch.ueber != "")
            ).all():
                adressbuecher.entfernen(db, person, buch.id)
        # nexpaper: keine Zeile; „Als Dokument an nexpaper“ verschwindet mit der Karte.
    except Exception:  # noqa: BLE001 - die Verbindung ist beendet; was hängen bleibt, zeigt die eigene Karte als Fehler
        logger.warning("Dropping the rows of an ended connection failed partner=%s", partner, exc_info=True)


__all__ = ["CONFIG", "GENUTZT", "Abgelehnt", "Unerreichbar", "gelaufen", "zugriff", "VerbindenStore", "anfragen", "store_fuer", "ueber_getrennt", "ueber_klick"]
