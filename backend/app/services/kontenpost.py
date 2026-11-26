"""Die Mails rund ums Konto: Einladung, Link fuer ein neues Passwort, Adresse bestaetigen, neuer Benutzername,
Bescheid an die alte Adresse.

Das Kontenmodul verschickt nie selbst; es sagt, was hinaus soll (``nexkonten.Mail``), und hier wird daraus eine Mail
ueber den Systempostausgang (``services/systempost``), mit Link aus der oeffentlichen Adresse.

Seit Teil 2 baut das gemeinsame Mailmodul (``vendor/nexpost``) die Briefe: Text und HTML mit Logo, einzeilige
Kopfzeilen, die Sprache des Kontos (DE, EN, FR), sonst die des Betreibers, sonst Englisch. Verschickt wird ueber die
Outbox mit Wiederholung (``services/post_store``); nur „Passwort vergessen“ geht sofort (``sofort_senden``).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import einstellung_lesen
from ..models import Benutzer, Einladung
from ..vendor.nexkonten import MAIL_CONFIRM_EMAIL, MAIL_NEW_SIGN_IN, MAIL_RESET, Mail
from ..vendor import nexpost
from . import post_store, systempost
from .adresse import fuer_modul

SCHLUESSEL_OEFFENTLICHE_ADRESSE = "oeffentliche_adresse"


def oeffentliche_adresse(db: Session) -> str:
    """Die Adresse, unter der Menschen nexmail oeffnen, samt Vorbau; ``""`` ohne."""
    return fuer_modul(einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE), get_settings().url_base).rstrip("/")


def mail_moeglich(db: Session) -> bool:
    """Ob ein Link per Mail hinaus kann: Systempostausgang und oeffentliche Adresse sind da."""
    return systempost.lesen(db).eingerichtet and bool(oeffentliche_adresse(db))


def link(db: Session, pfad: str) -> str:
    return f"{oeffentliche_adresse(db)}{pfad}"


def _sprache(db: Session, benutzer_id: object = None) -> str:
    """Die Sprache einer Mail: die des Kontos, sonst die des Betreibers, sonst Englisch (Mailmodul)."""
    from . import benutzer as benutzerdienst

    person = db.get(Benutzer, str(benutzer_id)) if benutzer_id else None
    chef = benutzerdienst.betreiber(db)
    return nexpost.letters.language_for(person.sprache if person else "", chef.sprache if chef else "")


_PFADE = {MAIL_RESET: "/kennwort/", MAIL_CONFIRM_EMAIL: "/adresse/"}

#: Die Seite Sicherheit (``frontend/src/lib/kontorueckweg.ts`` ``KONTOSEITE``): Ziel des Knopfs „Angemeldete Geraete
#: ansehen“ in der Mail „Neue Anmeldung“ (post 1.0.0).
SEITE_SICHERHEIT = "/konto/sicherheit"


def zeitzone(db: Session) -> str:
    """Die Zeitzone der Installation (Verwaltung → Allgemein, sonst ``NEXMAIL_ZEITZONE``); Personen fuehren in nexmail
    keine eigene. ``""``: die des Servers."""
    return einstellung_lesen(db, "zeitzone") or get_settings().zeitzone


def _brief(db: Session, mail: Mail, where: str = ""):
    if mail.kind == MAIL_NEW_SIGN_IN:
        # post 1.0.0: Browser auf System und Uhrzeit in der Zone der Installation, der Knopf zur Seite Sicherheit;
        # nie eine Netzadresse (``where`` ist nur der User-Agent).
        return nexpost.letters.from_account_mail(
            mail,
            language=_sprache(db, mail.account_id),
            link=link(db, SEITE_SICHERHEIT),
            where=where,
            time_zone=zeitzone(db) or None,
        )
    pfad = _PFADE.get(mail.kind)
    return nexpost.letters.from_account_mail(
        mail,
        language=_sprache(db, mail.account_id),
        link=link(db, f"{pfad}{mail.token}") if pfad and mail.token else "",
        where=where,
    )


def senden(db: Session, mail: Mail, *, where: str = "") -> None:
    """Eine Mail des Kontenmoduls: als Brief des Mailmoduls (Logo, Text und HTML, Sprache des Kontos) in die Outbox.
    Der erste Versuch laeuft gleich, weitere holt der Takt nach (``services/post_store``)."""
    post_store.einreihen(db, _brief(db, mail, where))


def sofort_senden(db: Session, mail: Mail) -> None:
    """„Passwort vergessen“ (konten 0.3.10): **sofort, nie ueber die Outbox.** Geht die Mail nicht hinaus, wirft
    das, und das Modul nimmt den Link wieder weg (``resets.forgot_in_background``); ueber die Outbox bliebe ein Link,
    den niemand bekam, und der Mensch wartete auf eine Mail, die erst eine Stunde spaeter oder nie kommt."""
    nexpost.outbox.deliver_now(post_store.PostStore(db), _brief(db, mail))


def einladung_senden(db: Session, einladung: Einladung, einladungslink: str, tage: int) -> None:
    """Die Einladungsmail, in der Sprache des Betreibers. Ohne Benutzernamen: den waehlt der Eingeladene selbst.

    ⚠️ **Sofort, nicht ueber die Outbox:** Anlegen und Verschicken sind eins (``routers/benutzer.einladen``). Geht
    sie nicht hinaus, wird die Einladung wieder entfernt und der Grund gesagt; eine Einladung, deren Mail erst Stunden
    spaeter scheitert, saehe in der Liste richtig aus. Wirft ``systempost.PostFehler``. ``einladungslink`` kommt
    fertig von ``invites.invite_link`` (oeffentliche Adresse, sonst die der Anfrage des Betreibers)."""
    sprache = _sprache(db)
    brief = nexpost.letters.compose(
        "invite",
        einladung.adresse,
        language=sprache,
        values={
            "name": einladung.anzeigename.strip(),
            "valid": nexpost.letters.validity(sprache, days=tage),
        },
        link=einladungslink,
    )
    try:
        nexpost.outbox.deliver_now(post_store.PostStore(db), brief)
    except nexpost.MailError as fehler:
        raise _postfehler(fehler, brief.to) from fehler


#: Die Kennungen des Mailmoduls in nexmails alten (``serverfehler.*``), samt den Werten, die die Saetze brauchen.
_ALTE_POSTKENNUNGEN = {
    "mail_recipient_refused": "empfaenger_abgelehnt",
    "mail_sender_refused": "absender_abgelehnt",
    "mail_unreachable": "postausgang_nicht_erreichbar",
    "mail_off": "postausgang_fehlt",
}


#: Was keiner der alten Kennungen entspricht.
POSTKENNUNG_SONST = "postausgang_abgelehnt"


def _postfehler(fehler: Exception, an: str) -> systempost.PostFehler:
    code = getattr(fehler, "code", "")
    grund = getattr(fehler, "detail", "") or str(fehler)
    return systempost.PostFehler(_ALTE_POSTKENNUNGEN.get(code, POSTKENNUNG_SONST), an=an, grund=grund, code="")
