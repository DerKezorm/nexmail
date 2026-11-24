"""Die Anbindung des gemeinsamen Kontenmoduls (``app.vendor.nexkonten``) an nexmails Tabellen.

Das Modul regelt Einrichtung, Einladung, Anmelden mit Passwort, Profil und Passwort vergessen gleich in jeder
nex-App; es fragt ueber einen ``Store``, und der steht hier, ueber ``benutzer``, ``einladung``, ``ruecksetzung``,
``adresswechsel``, ``frueherer_name``, ``sitzung`` und ``api_schluessel``. Eine Instanz gilt fuer eine
Datenbanksitzung, also eine Anfrage.

⚠️ **Die Spalten behalten ihre Namen.** ``benutzername`` ist ``username``, ``anzeigename`` ``display_name``,
``kontaktadresse`` ``email``. Was das Modul darueber hinaus braucht, kam ergaenzend dazu (``models.Benutzer``,
``services/konten_wanderung``).

⚠️ **nexmail sperrt keine Konten.** ``blocked`` ist immer falsch, ``is_locked`` auch: Die Bremse gegen Raten steht
im Arbeitsspeicher (``services/anmeldebremse``) und zaehlt seit dem Modul am Konto (``login.attempt_key``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..meldung import MeldungHttp
from ..models import (
    Adresswechsel,
    ApiSchluessel,
    AppKopplung,
    Benutzer,
    Einladung,
    Einrichtung,
    FruehererName,
    Kennwortruecksetzung,
    Passkey,
    Sitzung,
    Wiederherstellungscode,
    utcnow,
)
from ..vendor import nexkonten
from ..vendor.nexkonten import (
    Access,
    Account,
    AccountError,
    AccountId,
    EmailChange,
    Event,
    Invite,
    NewAccount,
    Picture,
    Reset,
    Taken,
    names,
)
from ..vendor.nexkonten.model2 import (
    KIND_BROWSER,
    KIND_DEVICE,
    KIND_WAITING,
    STAGE_FULL,
)
from ..vendor.nexkonten.model2 import Passkey as PasskeyDaten
from ..vendor.nexkonten.model2 import Session as SitzungDaten
from . import benutzer as benutzerdienst

#: Die Schalter des Betreibers (Teil 2): „Zweiten Faktor fuer alle verlangen“ (ab Werk aus) und „Passkeys erlaubt“
#: (ab Werk an). nexmail hatte keinen Pflichtschalter; der zweite Faktor war schon vorher eine Wahl.
SCHALTER_FAKTOR_FUER_ALLE = "zwei_faktor_fuer_alle"
SCHALTER_PASSKEYS = "passkeys_erlaubt"

logger = logging.getLogger("nexmail.konten")

PROVIDER = "provider"

#: Die Kennungen, die nexmails Oberflaeche, Skripte und die iPhone-App von vor dem Modul kennen. Nach aussen bleiben
#: sie (Entwurf, Entscheidung „Fehlerkennungen nach aussen“); die Oberflaeche bildet sie zurueck
#: (``frontend/src/lib/servermeldung.ts``).
ALTE_KENNUNGEN = {
    "wrong_credentials": "anmeldung_falsch",
    "username_taken": "benutzername_vergeben",
    "username_invalid": "benutzername_ungueltig",
    "password_too_short": "passwort_zu_kurz",
    "email_invalid": "adresse_ungueltig",
    "wrong_password": "kennwort_falsch",
    "invite_invalid": "einladung_abgelaufen",
    "invite_expired": "einladung_abgelaufen",
    "reset_invalid": "ruecksetzung_ungueltig",
    "reset_expired": "ruecksetzung_ungueltig",
    "not_found": "benutzer_nicht_gefunden",
}


def einrichten() -> None:
    """Das Modul kennt danach nexmails Namen, Protokoll und Kennungen. Beim Import und von Tests."""
    nexkonten.configure(
        nexkonten.AppConfig(
            app_name="nexmail",
            setup_token=lambda: get_settings().setup_token,
            logger_name="nexmail.konten",
            error_codes=ALTE_KENNUNGEN,
        )
    )


einrichten()


def http(fehler: AccountError, status_code: int | None = None) -> MeldungHttp:
    """Eine Ablehnung des Moduls in nexmails Form: ``detail`` die Kennung (die alte, wo es eine gibt), Werte daneben."""
    werte = dict(fehler.extra)
    if "minimum" in werte:
        # ``passwort_zu_kurz`` nannte die Zahl ``min``; beide stehen da, damit alte und neue Saetze passen.
        werte.setdefault("min", werte["minimum"])
    # 422 heisst bei nexmail „Pydantic hat abgelehnt“; eine Regel des Moduls war bisher 400 (``benutzername_ungueltig``).
    if fehler.code == "too_many_attempts":
        # konten 0.3.1: Auch Sicherheitsseiten bremsen (falsches Passwort beim Bestaetigen). Dieselbe Antwort wie
        # nexmails eigene Bremse: 429 ``zu_viele_versuche`` mit ``Retry-After``; die Oberflaeche kennt sie.
        warten = int(werte.get("retry_after") or 1)
        return MeldungHttp(429, "zu_viele_versuche", werte, headers={"Retry-After": str(warten)})
    status = status_code or (400 if fehler.status == 422 else fehler.status)
    return MeldungHttp(status, fehler.public_code, werte)


#: Was ``check_password`` prueft, wenn es kein Konto oder kein Passwort gibt: Die Antwort dauert so lange wie bei
#: einem falschen Passwort und verraet keine Namen oder Adressen.
_SCHEIN: str | None = None
_SCHEIN_SCHLOSS = threading.Lock()


def _schein() -> str:
    global _SCHEIN
    with _SCHEIN_SCHLOSS:
        if _SCHEIN is None:
            import secrets

            _SCHEIN = benutzerdienst.hashen(secrets.token_urlsafe(16))
    return _SCHEIN


def _bewusst(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


#: Die Kontosperre (Teil 2, Entwurf: „10 Fehlversuche, 15 Minuten, ueberall“).
SPERRE_NACH = 10
SPERRE_MINUTEN = 15

#: Ob das Bild vom Anbieter in einem eigenen Faden geholt wird. Tests schalten das ab und warten nicht.
BILD_IM_FADEN = True


class KontenStore:
    """``nexkonten.Store`` ueber nexmails Tabellen, innerhalb einer Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Konten --------------------------------------------------------------------------------------------------
    def _konto(self, zeile: Benutzer) -> Account:
        wartet = self.db.scalar(select(Adresswechsel.adresse).where(Adresswechsel.benutzer_id == zeile.id))
        if zeile.profilbild_am is None:
            bild = nexkonten.PICTURE_NONE
        else:
            bild = nexkonten.PICTURE_PROVIDER if zeile.profilbild_herkunft == PROVIDER else nexkonten.PICTURE_OWN
        return Account(
            id=zeile.id,
            username=zeile.benutzername,
            display_name=zeile.anzeigename or "",
            email=zeile.kontaktadresse or "",
            email_confirmed=bool(zeile.kontaktadresse_zaehlt) if zeile.kontaktadresse else True,
            email_proven=bool(zeile.kontaktadresse_bewiesen),
            email_source=zeile.kontaktadresse_herkunft or "",
            pending_email=wartet or "",
            has_password=bool(zeile.passwort_hash),
            blocked=False,
            operator=bool(zeile.ist_betreiber),
            picture=bild,
            language=zeile.sprache or "",
        )

    def count_accounts(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(Benutzer)) or 0)

    def get_account(self, account_id: AccountId) -> Account | None:
        zeile = self.db.get(Benutzer, str(account_id))
        return self._konto(zeile) if zeile is not None else None

    def find_by_username(self, username: str) -> list[Account]:
        zeilen = self.db.scalars(
            select(Benutzer).where(func.lower(Benutzer.benutzername) == username.strip().lower())
        )
        return [self._konto(z) for z in zeilen]

    def find_by_email(self, address: str) -> list[Account]:
        gesucht = address.strip().lower()
        if not gesucht:
            return []
        zeilen = self.db.scalars(select(Benutzer).where(func.lower(Benutzer.kontaktadresse) == gesucht))
        return [self._konto(z) for z in zeilen]

    def name_reserved(self, username: str, except_id: AccountId | None) -> bool:
        abfrage = select(FruehererName.id).where(func.lower(FruehererName.benutzername) == username.strip().lower())
        if except_id is not None:
            abfrage = abfrage.where(FruehererName.konto != str(except_id))
        return self.db.scalar(abfrage.limit(1)) is not None

    def find_by_former_name(self, username: str) -> list[Account]:
        kennungen = self.db.scalars(
            select(FruehererName.konto).where(
                func.lower(FruehererName.benutzername) == username.strip().lower(), FruehererName.konto != ""
            )
        )
        return [k for k in (self.get_account(kennung) for kennung in set(kennungen)) if k is not None]

    def display_name_taken(self, display_name: str, except_id: AccountId | None) -> bool:
        gesucht = names.display_key(display_name)
        if not gesucht:
            return False
        zeilen = self.db.execute(select(Benutzer.id, Benutzer.anzeigename).where(Benutzer.anzeigename != ""))
        return any(z.id != str(except_id) and names.display_key(z.anzeigename) == gesucht for z in zeilen)

    def _schreiben(self, anweisung=None) -> None:
        """Eine Anweisung (oder das Nachziehen der Sitzung); ein eindeutiger Index, der ablehnt, wird ``Taken``."""
        try:
            if anweisung is not None:
                self.db.execute(anweisung)
            self.db.flush()
        except IntegrityError as fehler:
            self.db.rollback()
            text = str(fehler.orig)
            raise Taken("email" if "kontaktadresse" in text else "username") from fehler

    def add_account(self, new: NewAccount) -> AccountId:
        if new.display_name and self.display_name_taken(new.display_name, None):
            raise Taken("display_name")
        zeile = Benutzer(
            benutzername=new.username,
            anzeigename=new.display_name,
            passwort_hash=benutzerdienst.hashen(new.password) if new.password else "",
            ist_betreiber=new.operator,
            kontaktadresse=new.email,
            kontaktadresse_zaehlt=new.email_confirmed,
            kontaktadresse_bewiesen=new.email_proven,
            kontaktadresse_herkunft="",
            sprache=new.language,
            # Neue Konten starten auf der laufenden Version (siehe ``models.Benutzer.wasneu_gesehen``).
            wasneu_gesehen=__version__,
        )
        self.db.add(zeile)
        self._schreiben()
        return zeile.id

    def set_username(self, account_id: AccountId, username: str) -> None:
        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is None:
            return
        alt = zeile.benutzername
        self._schreiben(update(Benutzer).where(Benutzer.id == str(account_id)).values(benutzername=username))
        self.db.add(FruehererName(konto=str(account_id), benutzername=alt))
        self.db.flush()
        self.db.expire(zeile)

    def set_display_name(self, account_id: AccountId, display_name: str) -> None:
        if display_name and self.display_name_taken(display_name, account_id):
            raise Taken("display_name")
        self.db.execute(update(Benutzer).where(Benutzer.id == str(account_id)).values(anzeigename=display_name))
        self._auffrischen(account_id)

    def set_email(self, account_id: AccountId, address: str, *, confirmed: bool, proven: bool, source: str) -> None:
        werte = {
            "kontaktadresse": address,
            "kontaktadresse_zaehlt": confirmed if address else True,
            "kontaktadresse_bewiesen": proven if address else False,
            "kontaktadresse_herkunft": source,
        }
        self._schreiben(update(Benutzer).where(Benutzer.id == str(account_id)).values(**werte))
        self._auffrischen(account_id)

    def set_language(self, account_id: AccountId, language: str) -> None:
        self.db.execute(update(Benutzer).where(Benutzer.id == str(account_id)).values(sprache=language))
        self._auffrischen(account_id)

    def _auffrischen(self, account_id: AccountId) -> None:
        """Eine Zeile, die die Sitzung schon geladen hat, nach einem ``update()`` neu lesen lassen."""
        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is not None:
            self.db.expire(zeile)

    # --- Passwoerter, Fehlversuche, Sitzungen --------------------------------------------------------------------
    def check_password(self, account_id: AccountId | None, password: str) -> bool:
        zeile = self.db.get(Benutzer, str(account_id)) if account_id is not None else None
        if zeile is None or not zeile.passwort_hash:
            benutzerdienst.passwort_prueft_schein(_schein(), password)
            return False
        return benutzerdienst.passwort_stimmt(zeile, password)

    def set_password(self, account_id: AccountId, password: str) -> None:
        self.db.execute(
            update(Benutzer)
            .where(Benutzer.id == str(account_id))
            .values(passwort_hash=benutzerdienst.hashen(password), fehlversuche=0, gesperrt_bis=None)
        )
        self._auffrischen(account_id)

    def is_locked(self, account_id: AccountId) -> bool:
        """Gesperrt nach 10 Fehlversuchen fuer 15 Minuten (Teil 2; nexmail hatte vorher nur die Bremse)."""
        zeile = self.db.get(Benutzer, str(account_id))
        return bool(zeile and zeile.gesperrt_bis and _bewusst(zeile.gesperrt_bis) > utcnow())

    def note_failure(self, account_id: AccountId | None) -> None:
        """Ein Fehlversuch am Konto; nach ``SPERRE_NACH`` gesperrt fuer ``SPERRE_MINUTEN``. Ohne Konto (``None``)
        dieselbe Arbeit an einer Zeile, die es nicht gibt: gleich teuer, die Zeit verraet nichts."""
        from datetime import timedelta

        self.db.execute(
            update(Benutzer)
            .where(Benutzer.id == (str(account_id) if account_id is not None else ""))
            .values(fehlversuche=Benutzer.fehlversuche + 1)
        )
        if account_id is None:
            return
        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is not None:
            self.db.refresh(zeile)
            if zeile.fehlversuche >= SPERRE_NACH:
                zeile.gesperrt_bis = utcnow() + timedelta(minutes=SPERRE_MINUTEN)
                zeile.fehlversuche = 0
            self.db.flush()

    def note_success(self, account_id: AccountId) -> None:
        self.db.execute(
            update(Benutzer).where(Benutzer.id == str(account_id)).values(fehlversuche=0, gesperrt_bis=None)
        )
        self._auffrischen(account_id)

    def end_sessions(self, account_id: AccountId) -> None:
        """Browser-Sitzungen und Anmeldungen, die auf den zweiten Faktor warten (beides ``art = browser``). Die
        iPhone-App (``art = geraet``) und API-Schluessel bleiben (Entwurf, Entscheidung „Neues Passwort“)."""
        self.db.execute(delete(Sitzung).where(Sitzung.benutzer_id == str(account_id), Sitzung.art == "browser"))
        # Kennungen bekannter Browser werden mit einem neuen Passwort wertlos (Teil 2).
        self.renew_device_key(account_id)

    def list_access(self, account_id: AccountId) -> list[Access]:
        geraete = self.db.scalars(
            select(Sitzung).where(
                Sitzung.benutzer_id == str(account_id), Sitzung.art == "geraet", Sitzung.gueltig_bis > utcnow()
            )
        )
        schluessel = self.db.scalars(select(ApiSchluessel).where(ApiSchluessel.benutzer_id == str(account_id)))
        return [Access(g.id, "device", g.geraet or "", g.zuletzt_gesehen) for g in geraete] + [
            Access(s.id, "api_key", s.name, s.zuletzt_benutzt) for s in schluessel
        ]

    def revoke_access(self, account_id: AccountId) -> int:
        weg = self.db.execute(
            delete(Sitzung).where(Sitzung.benutzer_id == str(account_id), Sitzung.art == "geraet")
        ).rowcount or 0
        weg += self.db.execute(delete(ApiSchluessel).where(ApiSchluessel.benutzer_id == str(account_id))).rowcount or 0
        # Ein QR-Code, den noch niemand gescannt hat, wuerde sonst gleich wieder ein Geraet anlegen.
        self.db.execute(delete(AppKopplung).where(AppKopplung.benutzer_id == str(account_id)))
        return int(weg)

    def second_factor(self, account_id: AccountId) -> str:
        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is not None and (zeile.totp_bestaetigt or self.passkeys_of(account_id)):
            return nexkonten.SECOND_FACTOR_ACTIVE
        if zeile is not None and self.factor_required():
            return nexkonten.SECOND_FACTOR_REQUIRED
        return nexkonten.SECOND_FACTOR_NONE

    # --- Bilder --------------------------------------------------------------------------------------------------
    def set_provider_picture(self, account_id: AccountId, picture: Picture) -> bool:
        """Durch nexmails eigene Bildbearbeitung wie ein hochgeladenes, und nur, solange das Konto keins hat (eine
        Anweisung mit dieser Bedingung)."""
        from . import profilbild as profilbilddienst

        try:
            webp = profilbilddienst.zeichnen(picture.data)
        except profilbilddienst.ProfilbildFehler:
            return False
        ergebnis = self.db.execute(
            update(Benutzer)
            .where(Benutzer.id == str(account_id), Benutzer.profilbild_am.is_(None))
            .values(profilbild=webp, profilbild_am=utcnow(), profilbild_herkunft=PROVIDER)
        )
        self._auffrischen(account_id)
        return int(ergebnis.rowcount or 0) == 1

    # --- Einladungen ---------------------------------------------------------------------------------------------
    def find_invite(self, key: str) -> Invite | None:
        if not key:
            return None
        zeile = self.db.scalar(select(Einladung).where(Einladung.schluessel_hash == _hash(key)))
        if zeile is None or zeile.eingeloest is not None:
            return None
        return Invite(
            key=key,
            id=zeile.id,
            email=zeile.adresse or "",
            display_name=zeile.anzeigename or "",
            username=zeile.benutzername or "",
            expires_at=_bewusst(zeile.laeuft_ab),
        )

    def consume_invite(self, invite: Invite) -> bool:
        ergebnis = self.db.execute(
            update(Einladung)
            .where(Einladung.id == str(invite.id), Einladung.eingeloest.is_(None))
            .values(eingeloest=utcnow())
        )
        return int(ergebnis.rowcount or 0) == 1

    def accept_invite(self, account_id: AccountId, invite: Invite) -> None:
        """nexmails Einladungen tragen keine Rechte: Jeder ist Mitglied."""

    # --- Adresswechsel -------------------------------------------------------------------------------------------
    def start_email_change(self, account_id: AccountId, address: str, token: str, expires_at: datetime) -> None:
        self.db.execute(delete(Adresswechsel).where(Adresswechsel.benutzer_id == str(account_id)))
        self.db.add(
            Adresswechsel(
                benutzer_id=str(account_id), adresse=address, schluessel_hash=_hash(token), laeuft_ab=expires_at
            )
        )
        self.db.flush()

    def find_email_change(self, token: str) -> EmailChange | None:
        if not token:
            return None
        zeile = self.db.scalar(select(Adresswechsel).where(Adresswechsel.schluessel_hash == _hash(token)))
        if zeile is None:
            return None
        return EmailChange(
            id=zeile.id, account_id=zeile.benutzer_id, address=zeile.adresse, expires_at=_bewusst(zeile.laeuft_ab)
        )

    def consume_email_change(self, change: EmailChange) -> bool:
        ergebnis = self.db.execute(delete(Adresswechsel).where(Adresswechsel.id == str(change.id)))
        return int(ergebnis.rowcount or 0) == 1

    def drop_email_change(self, account_id: AccountId) -> None:
        self.db.execute(delete(Adresswechsel).where(Adresswechsel.benutzer_id == str(account_id)))

    # --- Links fuer ein neues Passwort ---------------------------------------------------------------------------
    def start_reset(
        self,
        account_id: AccountId,
        token: str,
        expires_at: datetime,
        *,
        created_by: AccountId | None,
        origin: str,
    ) -> None:
        self.drop_resets(account_id)
        self.db.add(
            Kennwortruecksetzung(
                schluessel_hash=_hash(token),
                benutzer_id=str(account_id),
                laeuft_ab=expires_at,
                herkunft=origin,
                angelegt_von=str(created_by) if created_by is not None else None,
            )
        )
        self.db.flush()

    def find_reset(self, token: str) -> Reset | None:
        if not token:
            return None
        zeile = self.db.scalar(
            select(Kennwortruecksetzung).where(
                Kennwortruecksetzung.schluessel_hash == _hash(token), Kennwortruecksetzung.eingeloest.is_(None)
            )
        )
        if zeile is None:
            return None
        return Reset(
            id=zeile.id,
            account_id=zeile.benutzer_id,
            expires_at=_bewusst(zeile.laeuft_ab),
            created_by=zeile.angelegt_von or None,
            origin=zeile.herkunft or nexkonten.RESET_SELF,
        )

    def consume_reset(self, reset: Reset) -> bool:
        ergebnis = self.db.execute(
            update(Kennwortruecksetzung)
            .where(Kennwortruecksetzung.id == str(reset.id), Kennwortruecksetzung.eingeloest.is_(None))
            .values(eingeloest=utcnow())
        )
        return int(ergebnis.rowcount or 0) == 1

    def drop_resets(self, account_id: AccountId, *, origin: str | None = None) -> None:
        bedingung = [Kennwortruecksetzung.benutzer_id == str(account_id), Kennwortruecksetzung.eingeloest.is_(None)]
        if origin is not None:
            bedingung.append(Kennwortruecksetzung.herkunft == origin)
        self.db.execute(delete(Kennwortruecksetzung).where(*bedingung))

    def claim_setup(self) -> bool:
        """Die Ersteinrichtung einmal je Datenbank: eine Zeile mit fester Kennung; die zweite scheitert am
        Primaerschluessel, auch aus einem zweiten Prozess."""
        try:
            self.db.add(Einrichtung(id=1))
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return False
        return True

    # --- Nach dem Festschreiben ----------------------------------------------------------------------------------
    def notify(self, event: Event) -> None:
        """Was nach dem Festschreiben folgt. Bei nexmail haengt nichts am Namen (Sitzungen, Geraete, Schluessel,
        Verschluesselung tragen die Kennung); nur ein neues Passwort ueber einen Link hinterlaesst einen Hinweis fuer
        die naechste Anmeldung: „Diese Geraete haben noch Zugriff“."""
        if event.kind == nexkonten.EVENT_PASSWORD_SET:
            herkunft = str(event.details.get("origin") or nexkonten.RESET_SELF)
            self.db.execute(
                update(Benutzer).where(Benutzer.id == str(event.account_id)).values(neues_passwort=herkunft)
            )
            self.db.commit()
            self._auffrischen(event.account_id)
        elif event.kind == nexkonten.EVENT_RENAMED:
            logger.info("Account %s renamed.", event.account_id)


    # === Teil 2: zweiter Faktor, Passkeys, Sitzungen, Bilder (``nexkonten.model2``) ================================

    # --- Zweiter Faktor -------------------------------------------------------------------------------------------
    def totp_seed(self, account_id: AccountId) -> str | None:
        """Das Geheimnis eines **bestaetigten** Faktors, geoeffnet; versiegelt bleibt es wie bisher (Kontext
        ``benutzer:<id>:totp``), damit eingerichtete Authenticator-Apps weiter gelten."""
        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is None or not zeile.totp_bestaetigt or not zeile.totp_geheimnis:
            return None
        from . import zwei_faktor

        return zwei_faktor.geheimnis_lesen(zeile) or None

    def set_totp(self, account_id: AccountId, seed: str | None) -> None:
        from . import zwei_faktor

        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is None:
            return
        if seed:
            zwei_faktor.geheimnis_speichern(zeile, seed)
            zeile.totp_bestaetigt = True
        else:
            zeile.totp_geheimnis = ""
            zeile.totp_bestaetigt = False
            zeile.totp_letzter_schritt = 0
        self.db.flush()

    def claim_step(self, account_id: AccountId, step: int) -> bool:
        ergebnis = self.db.execute(
            update(Benutzer)
            .where(Benutzer.id == str(account_id), Benutzer.totp_letzter_schritt < step)
            .values(totp_letzter_schritt=step)
        )
        self._auffrischen(account_id)
        return int(ergebnis.rowcount or 0) == 1

    def recovery_hashes(self, account_id: AccountId) -> list[str]:
        return list(
            self.db.scalars(
                select(Wiederherstellungscode.code_hash).where(
                    Wiederherstellungscode.benutzer_id == str(account_id), Wiederherstellungscode.verbraucht.is_(None)
                )
            )
        )

    def set_recovery(self, account_id: AccountId, hashes: list[str]) -> None:
        self.db.execute(delete(Wiederherstellungscode).where(Wiederherstellungscode.benutzer_id == str(account_id)))
        for wert in hashes:
            self.db.add(Wiederherstellungscode(benutzer_id=str(account_id), code_hash=wert))
        self.db.flush()

    def claim_recovery(self, account_id: AccountId, stored: str) -> bool:
        ergebnis = self.db.execute(
            update(Wiederherstellungscode)
            .where(
                Wiederherstellungscode.benutzer_id == str(account_id),
                Wiederherstellungscode.code_hash == stored,
                Wiederherstellungscode.verbraucht.is_(None),
            )
            .values(verbraucht=utcnow())
        )
        return int(ergebnis.rowcount or 0) == 1

    def recovery_key(self) -> bytes:
        import hashlib

        return hashlib.sha256(b"nexmail-recovery:" + get_settings().resolved_secret_key().encode("utf-8")).digest()

    def factor_required(self) -> bool:
        from ..db import einstellung_lesen

        return einstellung_lesen(self.db, SCHALTER_FAKTOR_FUER_ALLE) == "1"

    # --- Passkeys -------------------------------------------------------------------------------------------------
    def passkeys_allowed(self) -> bool:
        from ..db import einstellung_lesen

        return einstellung_lesen(self.db, SCHALTER_PASSKEYS) != "0"

    def _passkey(self, z: Passkey) -> "PasskeyDaten":
        return PasskeyDaten(
            uid=z.id,
            account_id=z.benutzer_id,
            credential_id=bytes(z.credential_id),
            public_key=bytes(z.public_key),
            sign_count=z.sign_count,
            name=z.name,
            created_at=_bewusst(z.angelegt),
            last_used_at=_bewusst(z.zuletzt) if z.zuletzt else None,
        )

    def passkeys_of(self, account_id: AccountId) -> list["PasskeyDaten"]:
        zeilen = self.db.scalars(select(Passkey).where(Passkey.benutzer_id == str(account_id)).order_by(Passkey.angelegt))
        return [self._passkey(z) for z in zeilen]

    def find_passkey(self, credential_id: bytes) -> "PasskeyDaten | None":
        zeile = self.db.scalar(select(Passkey).where(Passkey.credential_id == credential_id))
        return self._passkey(zeile) if zeile is not None else None

    def add_passkey(self, passkey: "PasskeyDaten") -> None:
        self.db.add(
            Passkey(
                id=passkey.uid,
                benutzer_id=str(passkey.account_id),
                credential_id=passkey.credential_id,
                public_key=passkey.public_key,
                sign_count=passkey.sign_count,
                name=passkey.name,
                angelegt=passkey.created_at,
            )
        )
        self.db.flush()

    def claim_counter(self, uid: str, old: int, new: int) -> bool:
        ergebnis = self.db.execute(
            update(Passkey)
            .where(Passkey.id == uid, Passkey.sign_count == old)
            .values(sign_count=new, zuletzt=utcnow())
        )
        return int(ergebnis.rowcount or 0) == 1

    def remove_passkey(self, account_id: AccountId, uid: str) -> bool:
        ergebnis = self.db.execute(delete(Passkey).where(Passkey.benutzer_id == str(account_id), Passkey.id == uid))
        return int(ergebnis.rowcount or 0) == 1

    def remove_passkeys(self, account_id: AccountId) -> int:
        return int(self.db.execute(delete(Passkey).where(Passkey.benutzer_id == str(account_id))).rowcount or 0)

    def user_handle(self, account_id: AccountId) -> bytes:
        import secrets

        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is None:
            raise LookupError(account_id)
        if not zeile.passkey_handle:
            zeile.passkey_handle = secrets.token_urlsafe(32)
            self.db.flush()
        return zeile.passkey_handle.encode("ascii")

    # --- Sitzungen ------------------------------------------------------------------------------------------------
    def _sitzung(self, z: Sitzung) -> "SitzungDaten":
        if z.art == "geraet":
            art = KIND_DEVICE
        elif not z.bestaetigt:
            art = KIND_WAITING
        else:
            art = KIND_BROWSER
        return SitzungDaten(
            uid=z.id,
            account_id=z.benutzer_id,
            kind=art,
            created_at=_bewusst(z.angelegt),
            expires_at=_bewusst(z.gueltig_bis),
            last_seen_at=_bewusst(z.zuletzt_gesehen) if z.zuletzt_gesehen else None,
            remember=bool(z.merken),
            stage=z.stufe or STAGE_FULL,
            provider_checked=bool(z.anbieter_geprueft),
            label=z.geraet or "",
            address=z.adresse or "",
        )

    def add_session(self, session: "SitzungDaten", token_hash: str) -> None:
        self.db.add(
            Sitzung(
                id=session.uid,
                benutzer_id=str(session.account_id),
                token_hash=token_hash,
                bestaetigt=session.kind != KIND_WAITING,
                art="geraet" if session.kind == KIND_DEVICE else "browser",
                geraet=session.label[:200],
                adresse=session.address[:64],
                angelegt=session.created_at,
                zuletzt_gesehen=session.last_seen_at or session.created_at,
                gueltig_bis=session.expires_at,
                merken=session.remember,
                stufe=session.stage,
                anbieter_geprueft=session.provider_checked,
            )
        )
        self.db.flush()

    def session_by_hash(self, token_hash: str) -> "SitzungDaten | None":
        zeile = self.db.scalar(select(Sitzung).where(Sitzung.token_hash == token_hash))
        return self._sitzung(zeile) if zeile is not None else None

    def touch_session(self, uid: str, last_seen_at: datetime, expires_at: datetime) -> None:
        self.db.execute(
            update(Sitzung).where(Sitzung.id == uid).values(zuletzt_gesehen=last_seen_at, gueltig_bis=expires_at)
        )

    def set_stage(self, uid: str, stage: str) -> None:
        self.db.execute(update(Sitzung).where(Sitzung.id == uid).values(stufe=stage))

    def sessions_of(self, account_id: AccountId) -> list["SitzungDaten"]:
        zeilen = self.db.scalars(
            select(Sitzung)
            # Angefangene Anmeldungen (auf den zweiten Faktor wartend) stehen nicht in der Liste.
            .where(Sitzung.benutzer_id == str(account_id), Sitzung.gueltig_bis > utcnow(), Sitzung.bestaetigt.is_(True))
            .order_by(Sitzung.zuletzt_gesehen.desc())
        )
        return [self._sitzung(z) for z in zeilen]

    def end_session(self, account_id: AccountId, uid: str) -> bool:
        ergebnis = self.db.execute(delete(Sitzung).where(Sitzung.benutzer_id == str(account_id), Sitzung.id == uid))
        return int(ergebnis.rowcount or 0) == 1

    def end_everywhere(self, account_id: AccountId, keep_uid: str | None) -> int:
        """Browser, wartende Anmeldungen und gekoppelte iPhones; API-Schluessel und Passkeys bleiben."""
        bedingung = [Sitzung.benutzer_id == str(account_id)]
        if keep_uid:
            bedingung.append(Sitzung.id != keep_uid)
        return int(self.db.execute(delete(Sitzung).where(*bedingung)).rowcount or 0)

    def device_key(self, account_id: AccountId) -> str:
        import secrets

        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is None:
            raise LookupError(account_id)
        if not zeile.geraete_schluessel:
            zeile.geraete_schluessel = secrets.token_urlsafe(32)
            self.db.flush()
        return zeile.geraete_schluessel

    def renew_device_key(self, account_id: AccountId) -> None:
        import secrets

        self.db.execute(
            update(Benutzer).where(Benutzer.id == str(account_id)).values(geraete_schluessel=secrets.token_urlsafe(32))
        )
        self._auffrischen(account_id)

    # --- Bilder ---------------------------------------------------------------------------------------------------
    def picture_of(self, account_id: AccountId) -> tuple[bytes, datetime] | None:
        zeile = self.db.get(Benutzer, str(account_id))
        if zeile is None or zeile.profilbild_am is None or not zeile.profilbild:
            return None
        return bytes(zeile.profilbild), _bewusst(zeile.profilbild_am)

    def set_picture(self, account_id: AccountId, data: bytes, at: datetime, source: str) -> None:
        self.db.execute(
            update(Benutzer)
            .where(Benutzer.id == str(account_id))
            .values(profilbild=data, profilbild_am=at, profilbild_herkunft=PROVIDER if source == PROVIDER else "")
        )
        self._auffrischen(account_id)

    def remove_picture(self, account_id: AccountId) -> None:
        self.db.execute(
            update(Benutzer)
            .where(Benutzer.id == str(account_id))
            .values(profilbild=None, profilbild_am=None, profilbild_herkunft="")
        )
        self._auffrischen(account_id)

    # --- Transaktion ---------------------------------------------------------------------------------------------
    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def store_fuer(db: Session) -> KontenStore:
    return KontenStore(db)


@contextmanager
def eigener_store() -> Iterator[KontenStore]:
    """Ein Store mit eigener Sitzung, fuer Arbeit nach der Antwort (Passwort vergessen, Bild vom Anbieter)."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        yield KontenStore(db)


def bild_vom_anbieter(benutzer_id: str, adresse: str, aussteller: str) -> None:
    """Das Bild des Anbieters fuer ein Konto ohne Bild, in einem eigenen Faden (holen dauert bis zu fuenf Sekunden).
    Scheitert es, bleibt das Konto ohne Bild; die Anmeldung ist laengst durch."""

    def arbeit() -> None:
        with eigener_store() as store:
            nexkonten.pictures.take_provider_picture(store, benutzer_id, adresse, aussteller)

    if BILD_IM_FADEN:
        threading.Thread(target=arbeit, name="nexmail-anbieterbild", daemon=True).start()
    else:
        arbeit()
