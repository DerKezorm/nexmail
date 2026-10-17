"""Die Anbindung des gemeinsamen Anmeldemoduls (``app.vendor.nexoidc``) an nexmails Tabellen.

Das Modul fragt ueber einen ``Store``; hier steht er, ueber ``oidc_anbieter``, ``oidc_verknuepfung``, ``benutzer``
und ``einladung``. Eine Instanz gilt fuer eine Datenbanksitzung, also eine Anfrage.

⚠️ **Das Modul rechnet mit ganzen Zahlen, nexmail mit Zeichenketten.** Anbieter und Konten tragen deshalb eine
``nummer`` (``models.OidcAnbieter.nummer``, ``models.Benutzer.nummer``); nach aussen gibt der Store nur sie heraus.

⚠️ **Zugeordnet wird nur ueber ``(anbieter_id, subject)``.** Die Adresse vom Anbieter steht hoechstens zur Anzeige an
der Verknuepfung; sie findet nie ein Konto.

⚠️ **0.21 liest dieselben Tabellen.** Deshalb steht das Geheimnis zweimal da (mit dem Kontext des Moduls und so,
wie 0.21 es liest), ``aktiv`` ist, was 0.21 als eingeschaltet sieht, und der Aussteller eines Eintrags behaelt seine
Schreibweise, solange er derselbe bleibt. Einzelheiten in ``models.OidcAnbieter``.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import __version__, crypto
from ..models import Benutzer, Einladung, OidcAnbieter, OidcVerknuepfung, utcnow
from ..vendor.nexoidc import protocol
from ..vendor.nexoidc.errors import OidcError
from ..vendor.nexoidc.model import (
    AccountState,
    Invite,
    Link,
    Provider,
    ProviderValues,
    secret_context,
)
from . import einladung as einladungsdienst

#: Zeichen wie ``benutzer.BENUTZERNAME_MUSTER``. Kuerzer als drei darf ein Name vom Anbieter sein ("jo"): Die
#: Untergrenze gilt fuer selbst gewaehlte Namen, sonst hiesse jede kurze Identitaet "user-2", "user-3".
NAME_MIN, NAME_MAX = 1, 64
_NICHT_IM_NAMEN = re.compile(r"[^A-Za-z0-9._-]+")


def alter_kontext(anbieter_id: str) -> str:
    """Der Kontext, unter dem 0.21 das Geheimnis eines Anbieters verschluesselt."""
    return f"oidc:{anbieter_id}:geheimnis"


def eingeschaltet(row: OidcAnbieter) -> bool:
    """Ob der Eintrag an ist. Von 0.21 angelegt (``eingeschaltet`` NULL): was 0.21 eintrug."""
    return bool(row.aktiv) if row.eingeschaltet is None else bool(row.eingeschaltet)


def fuer_alte_fassung_aktiv(enabled: bool, trusts_second_factor: bool) -> bool:
    """Was in ``aktiv`` steht: 0.21 fragt nach dem Anbieter keinen Code, also laesst sie nur herein, wo der Eintrag
    an ist UND der Anbieter den zweiten Faktor selbst prueft."""
    return bool(enabled and trusts_second_factor)


def nummer_vergeben(db: Session, tabelle: type[Benutzer | OidcAnbieter], zeile_id: str) -> int:
    """Eine Zeile ohne Nummer bekommt die naechste freie; festgeschrieben in derselben Transaktion."""
    hoechste = db.scalar(select(func.coalesce(func.max(tabelle.nummer), 0))) or 0
    db.execute(
        update(tabelle).where(tabelle.id == zeile_id, tabelle.nummer.is_(None)).values(nummer=hoechste + 1)
    )
    db.flush()
    return int(db.scalar(select(tabelle.nummer).where(tabelle.id == zeile_id)))


class SqlStore:
    """``nexoidc.model.Store`` ueber nexmails Tabellen, in einer SQLAlchemy-Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Nummern ---------------------------------------------------------------------------------------------------
    def _anbieter_nummer(self, row: OidcAnbieter) -> int:
        if row.nummer is None:
            # Nur, wenn 0.21 seit dem letzten Start einen Eintrag angelegt hat und der Start noch nicht lief.
            return nummer_vergeben(self.db, OidcAnbieter, row.id)
        return int(row.nummer)

    def konto_nummer(self, person: Benutzer) -> int:
        if person.nummer is None:
            nummer = nummer_vergeben(self.db, Benutzer, person.id)
            self.db.refresh(person)
            return nummer
        return int(person.nummer)

    def _anbieter(self, provider_id: int) -> OidcAnbieter | None:
        return self.db.scalar(select(OidcAnbieter).where(OidcAnbieter.nummer == provider_id))

    def konto(self, account_id: int) -> Benutzer | None:
        return self.db.scalar(select(Benutzer).where(Benutzer.nummer == account_id))

    # --- Anbieter --------------------------------------------------------------------------------------------------
    def _provider(self, row: OidcAnbieter | None) -> Provider | None:
        if row is None:
            return None
        nummer = self._anbieter_nummer(row)
        return Provider(
            id=nummer,
            slug=row.kuerzel,
            label=row.anzeigename,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=crypto.entschluesseln(row.client_secret_enc or "", secret_context(nummer)),
            scopes=row.scopes,
            enabled=eingeschaltet(row),
            auto_create=bool(row.auto_create),
            trusts_second_factor=bool(row.trusts_second_factor),
            managed=row.managed or "",
            position=row.position or 0,
            redirect_path=row.redirect_path or "",
            created_at=row.angelegt,
            registered_redirect=row.registered_redirect or "",
        )

    def list_providers(self) -> list[Provider]:
        rows = self.db.scalars(select(OidcAnbieter).order_by(OidcAnbieter.position, OidcAnbieter.nummer))
        return [provider for row in list(rows) if (provider := self._provider(row)) is not None]

    def get_provider(self, provider_id: int) -> Provider | None:
        return self._provider(self._anbieter(provider_id))

    def provider_by_slug(self, slug: str) -> Provider | None:
        return self._provider(self.db.scalar(select(OidcAnbieter).where(OidcAnbieter.kuerzel == slug)))

    def _apply(self, row: OidcAnbieter, values: ProviderValues) -> None:
        row.kuerzel, row.anzeigename, row.client_id = values.slug, values.label, values.client_id
        # ⚠️ Derselbe Aussteller behaelt seine Schreibweise (mit oder ohne Schraegstrich): so, wie die alte Fassung
        # oder der Betreiber ihn schrieb.
        if not (row.issuer and protocol.same_issuer(row.issuer, values.issuer)):
            row.issuer = values.issuer
        row.scopes = values.scopes
        row.eingeschaltet = values.enabled
        row.auto_create = values.auto_create
        row.trusts_second_factor = values.trusts_second_factor
        row.aktiv = fuer_alte_fassung_aktiv(values.enabled, values.trusts_second_factor)
        row.managed, row.position, row.redirect_path = values.managed, values.position, values.redirect_path
        if values.registered_redirect is not None:
            row.registered_redirect = values.registered_redirect

    def _secret(self, row: OidcAnbieter, secret: str) -> None:
        nummer = self._anbieter_nummer(row)
        row.client_secret_enc = crypto.verschluesseln(secret, secret_context(nummer)) if secret else ""
        # Fuer 0.21, bis die alte Fassung keinen Rueckweg mehr braucht.
        row.client_secret = crypto.verschluesseln(secret, alter_kontext(row.id)) if secret else ""

    def insert_provider(self, values: ProviderValues) -> Provider:
        row = OidcAnbieter(angelegt=utcnow())
        self._apply(row, values)
        if values.registered_redirect is None:
            row.registered_redirect = ""
        self.db.add(row)
        self.db.flush()
        self._secret(row, values.client_secret or "")
        self.db.flush()
        return self._provider(row)  # type: ignore[return-value]

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        row = self._anbieter(provider_id)
        if row is None:
            raise LookupError(f"no provider {provider_id}")
        self._apply(row, values)
        if values.client_secret is not None:
            self._secret(row, values.client_secret)
        self.db.flush()
        return self._provider(row)  # type: ignore[return-value]

    def delete_provider(self, provider_id: int) -> None:
        row = self._anbieter(provider_id)
        if row is None:
            return
        # ON DELETE CASCADE gibt es nur in frisch angelegten Tabellen (eine nachgezogene Spalte traegt keinen
        # Fremdschluessel); deshalb ausdruecklich.
        self.db.execute(OidcVerknuepfung.__table__.delete().where(OidcVerknuepfung.anbieter_id == row.id))
        self.db.delete(row)
        self.db.flush()

    # --- Verknuepfungen --------------------------------------------------------------------------------------------
    def _link(self, row: OidcVerknuepfung, anbieter_nummer: int | None = None) -> Link:
        if anbieter_nummer is None:
            anbieter = self.db.get(OidcAnbieter, row.anbieter_id)
            anbieter_nummer = self._anbieter_nummer(anbieter) if anbieter is not None else 0
        person = self.db.get(Benutzer, row.benutzer_id)
        return Link(
            provider_id=anbieter_nummer,
            subject=row.subject,
            account_id=self.konto_nummer(person) if person is not None else 0,
            issuer=row.issuer or "",
            email=row.email or None,
            created_at=row.angelegt,
            last_used_at=row.zuletzt_benutzt,
        )

    def find_link(self, provider_id: int, subject: str) -> Link | None:
        anbieter = self._anbieter(provider_id)
        if anbieter is None:
            return None
        row = self.db.scalar(
            select(OidcVerknuepfung).where(
                OidcVerknuepfung.anbieter_id == anbieter.id, OidcVerknuepfung.subject == subject
            )
        )
        return self._link(row, provider_id) if row is not None else None

    def links_of_provider(self, provider_id: int) -> list[Link]:
        anbieter = self._anbieter(provider_id)
        if anbieter is None:
            return []
        rows = self.db.scalars(
            select(OidcVerknuepfung).where(OidcVerknuepfung.anbieter_id == anbieter.id).order_by(OidcVerknuepfung.id)
        )
        return [self._link(row, provider_id) for row in list(rows)]

    def links_of_account(self, account_id: int) -> list[Link]:
        person = self.konto(account_id)
        if person is None:
            return []
        rows = self.db.scalars(
            select(OidcVerknuepfung)
            .where(OidcVerknuepfung.benutzer_id == person.id, OidcVerknuepfung.anbieter_id.is_not(None))
            .order_by(OidcVerknuepfung.id)
        )
        return [self._link(row) for row in list(rows)]

    def add_link(self, link: Link) -> None:
        anbieter, person = self._anbieter(link.provider_id), self.konto(link.account_id)
        if anbieter is None or person is None:
            raise LookupError("a link needs its provider and its account")
        # ⚠️ 0.21 haelt (issuer, subject) eindeutig, auch ueber Eintraege hinweg. Haengt die Identitaet schon an einem
        # anderen Eintrag desselben Ausstellers (Entra ``common`` und ein Mandant, authentik zweimal), gehoert sie
        # dort einem Konto: abgewiesen wie jede vergebene Identitaet, nicht als Datenbankfehler (500).
        vergeben = self.db.scalar(
            select(OidcVerknuepfung.id)
            .where(
                OidcVerknuepfung.issuer == link.issuer,
                OidcVerknuepfung.subject == link.subject,
                OidcVerknuepfung.anbieter_id.is_not(None),
            )
            .limit(1)
        )
        if vergeben is not None:
            self.db.rollback()
            raise OidcError(
                "oidc_subject_taken", f"this identity at {anbieter.kuerzel} belongs to an account at another entry"
            )
        # Steht dieselbe Identitaet noch ohne Anbieter da (von 0.21, keinem Eintrag zugeordnet), weicht diese Zeile
        # der neuen.
        self.db.execute(
            OidcVerknuepfung.__table__.delete().where(
                OidcVerknuepfung.issuer == link.issuer,
                OidcVerknuepfung.subject == link.subject,
                OidcVerknuepfung.anbieter_id.is_(None),
            )
        )
        self.db.add(
            OidcVerknuepfung(
                benutzer_id=person.id,
                anbieter_id=anbieter.id,
                issuer=link.issuer,
                subject=link.subject,
                email=(link.email or "")[:300],
                angelegt=utcnow(),
                zuletzt_benutzt=utcnow(),
            )
        )
        self.db.flush()

    def remove_link(self, provider_id: int, account_id: int) -> bool:
        anbieter, person = self._anbieter(provider_id), self.konto(account_id)
        if anbieter is None or person is None:
            return False
        weg = self.db.execute(
            OidcVerknuepfung.__table__.delete().where(
                OidcVerknuepfung.anbieter_id == anbieter.id, OidcVerknuepfung.benutzer_id == person.id
            )
        ).rowcount
        self.db.flush()
        return bool(weg)

    def drop_links(self, provider_id: int) -> int:
        anbieter = self._anbieter(provider_id)
        if anbieter is None:
            return 0
        weg = self.db.execute(
            OidcVerknuepfung.__table__.delete().where(OidcVerknuepfung.anbieter_id == anbieter.id)
        ).rowcount
        self.db.flush()
        return int(weg or 0)

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        anbieter = self._anbieter(provider_id)
        if anbieter is None:
            return
        self.db.execute(
            update(OidcVerknuepfung)
            .where(OidcVerknuepfung.anbieter_id == anbieter.id, OidcVerknuepfung.subject == subject)
            .values(zuletzt_benutzt=utcnow(), email=(email or "")[:300])
        )

    # --- Konten ----------------------------------------------------------------------------------------------------
    def account_state(self, account_id: int) -> AccountState | None:
        person = self.konto(account_id)
        if person is None:
            return None
        return AccountState(
            id=account_id,
            name=person.benutzername,
            # nexmail sperrt keine Konten; entfernt ist entfernt.
            blocked=False,
            has_password=bool(person.passwort_hash),
            has_second_factor=bool(person.totp_bestaetigt),
        )

    def clean_name(self, raw: str) -> str:
        """nexmails Namensregeln (Buchstaben, Ziffern, ``.``, ``_``, ``-``); "" wenn nichts Brauchbares bleibt."""
        cleaned = _NICHT_IM_NAMEN.sub("-", raw.strip())
        cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")[:NAME_MAX].rstrip("-._")
        return cleaned if len(cleaned) >= NAME_MIN else ""

    def name_taken(self, name: str) -> bool:
        return (
            self.db.scalar(select(Benutzer.id).where(func.lower(Benutzer.benutzername) == name.strip().lower()))
            is not None
        )

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        """Ein Konto ohne Passwort. Aus einer Einladung uebernimmt es Anzeigenamen und Adresse, die der Betreiber
        eingetragen hat (wie beim Annehmen mit Kennwort); die Adresse vom Anbieter fasst es nicht an."""
        einladung = self.db.get(Einladung, invite.id) if invite is not None else None
        person = Benutzer(
            benutzername=name,
            anzeigename=(einladung.anzeigename if einladung is not None else "") or name,
            passwort_hash="",
            kontaktadresse=einladung.adresse if einladung is not None else "",
            wasneu_gesehen=__version__,
        )
        self.db.add(person)
        self.db.flush()
        return self.konto_nummer(person)

    # --- Einladungen -----------------------------------------------------------------------------------------------
    def find_invite(self, key: str) -> Invite | None:
        if not key:
            return None
        einladung = einladungsdienst.finden(self.db, key)
        return Invite(key=key, id=einladung.id) if einladung is not None else None

    def consume_invite(self, invite: Invite) -> bool:
        """Eine Anweisung, die genau eine Zeile treffen muss: zwei gleichzeitige Rueckkehrer, nur einer kommt durch."""
        jetzt = utcnow()
        ergebnis = self.db.execute(
            update(Einladung)
            .where(Einladung.id == invite.id, Einladung.eingeloest.is_(None), Einladung.laeuft_ab > jetzt)
            .values(eingeloest=jetzt)
        )
        return int(getattr(ergebnis, "rowcount", 0) or 0) == 1

    def accept_invite(self, account_id: int, invite: Invite) -> None:
        """nexmails Einladungen tragen keine Rechte (jeder ist Mitglied); es gibt nichts dazuzugeben."""

    # --- Transaktion -----------------------------------------------------------------------------------------------
    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
