"""Die Mails rund ums Konto: Einladung, Link fuer ein neues Passwort, Adresse bestaetigen, neuer Benutzername,
Bescheid an die alte Adresse.

Das Kontenmodul verschickt nie selbst; es sagt, was hinaus soll (``nexkonten.Mail``), und hier wird daraus eine Mail
ueber den Systempostausgang (``services/systempost``), mit Link aus der oeffentlichen Adresse.

Seit Teil 2 baut das gemeinsame Mailmodul (``vendor/nexpost``) die Briefe: Text und HTML mit Logo, einzeilige
Kopfzeilen, die Sprache des Kontos (DE, EN, FR), sonst die des Betreibers, sonst Englisch. Verschickt wird ueber die
Outbox mit Wiederholung (``services/post_store``).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import einstellung_lesen
from ..models import Benutzer, Einladung
from ..vendor.nexkonten import MAIL_CONFIRM_EMAIL, MAIL_RESET, Mail
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


def senden(db: Session, mail: Mail, *, where: str = "") -> None:
    """Eine Mail des Kontenmoduls: als Brief des Mailmoduls (Logo, Text und HTML, Sprache des Kontos) in die Outbox.
    Der erste Versuch laeuft gleich, weitere holt der Takt nach (``services/post_store``)."""
    pfad = _PFADE.get(mail.kind)
    brief = nexpost.letters.from_account_mail(
        mail,
        language=_sprache(db, mail.account_id),
        link=link(db, f"{pfad}{mail.token}") if pfad and mail.token else "",
        where=where,
    )
    post_store.einreihen(db, brief)


def einladung_senden(db: Session, einladung: Einladung, schluessel: str, tage: int) -> None:
    """Die Einladungsmail, in der Sprache des Betreibers. Ohne Benutzernamen: den waehlt der Eingeladene selbst.

    ⚠️ **Sofort, nicht ueber die Outbox:** Anlegen und Verschicken sind eins (``routers/benutzer.einladen``). Geht
    sie nicht hinaus, wird die Einladung wieder entfernt und der Grund gesagt; eine Einladung, deren Mail erst Stunden
    spaeter scheitert, saehe in der Liste richtig aus. Wirft ``systempost.PostFehler``."""
    sprache = _sprache(db)
    brief = nexpost.letters.compose(
        "invite",
        einladung.adresse,
        language=sprache,
        values={
            "name": einladung.anzeigename.strip(),
            "valid": nexpost.letters.validity(sprache, days=tage),
        },
        link=link(db, f"/einladung/{schluessel}"),
    )
    try:
        nexpost.send.deliver(post_store.PostStore(db).mail_settings(), brief)
    except nexpost.MailError as fehler:
        raise _postfehler(fehler, brief.to) from fehler


#: Die Kennungen des Mailmoduls in nexmails alten (``serverfehler.*``), samt den Werten, die die Saetze brauchen.
_ALTE_POSTKENNUNGEN = {
    "mail_recipient_refused": "empfaenger_abgelehnt",
    "mail_sender_refused": "absender_abgelehnt",
    "mail_unreachable": "postausgang_nicht_erreichbar",
    "mail_off": "postausgang_fehlt",
}


def _postfehler(fehler: Exception, an: str) -> systempost.PostFehler:
    code = getattr(fehler, "code", "")
    grund = getattr(fehler, "detail", "") or str(fehler)
    return systempost.PostFehler(_ALTE_POSTKENNUNGEN.get(code, "postausgang_abgelehnt"), an=an, grund=grund, code="")
