"""Die Mails rund ums Konto: Einladung, Link fuer ein neues Passwort, Adresse bestaetigen, neuer Benutzername,
Bescheid an die alte Adresse.

Das Kontenmodul verschickt nie selbst; es sagt, was hinaus soll (``nexkonten.Mail``), und hier wird daraus eine Mail
ueber den Systempostausgang (``services/systempost``), mit Link aus der oeffentlichen Adresse.

⚠️ **Text und HTML, nicht entweder-oder** (wie bisher): Der Textteil traegt denselben Link wie der Knopf. Wer einen
Nur-Text-Client benutzt oder vorlesen laesst, haette sonst einen Weg ohne Weg.

⚠️ **In der Sprache des Kontos**, Deutsch oder Englisch; ohne gewaehlte Sprache Deutsch wie bisher.
"""

from __future__ import annotations

from html import escape

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import einstellung_lesen
from ..models import Benutzer, Einladung
from ..vendor.nexkonten import (
    MAIL_CONFIRM_EMAIL,
    MAIL_EMAIL_CHANGED,
    MAIL_RESET,
    MAIL_USERNAME_CHANGED,
    Mail,
)
from . import mailvorlage, systempost
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


def _englisch(db: Session, benutzer_id: object) -> bool:
    person = db.get(Benutzer, str(benutzer_id)) if benutzer_id else None
    return bool(person and (person.sprache or "").lower().startswith("en"))


def _stunden(stunden: int, en: bool) -> str:
    if stunden % 24 == 0 and stunden >= 24:
        tage = stunden // 24
        return (f"{tage} day" + ("s" if tage != 1 else "")) if en else (f"{tage} Tag" + ("e" if tage != 1 else ""))
    return (f"{stunden} hour" + ("s" if stunden != 1 else "")) if en else (f"{stunden} Stunde" + ("n" if stunden != 1 else ""))


def _senden(db: Session, an: str, betreff: str, hallo: str, absaetze: list[str], knopf: tuple[str, str] | None,
            fuss: str) -> None:
    """Eine Mail aus Absaetzen (Klartext); der HTML-Teil bekommt dieselben, maskiert."""
    teile = [f"{hallo},", *absaetze]
    if knopf:
        teile.append(knopf[1])
    teile.append(fuss)
    text = "\n\n".join(teile) + "\n"
    html = mailvorlage.rahmen(
        ueberschrift=escape(hallo),
        absaetze=[escape(a) for a in absaetze],
        knopf=knopf,
        fusszeile=escape(fuss),
    )
    systempost.senden(db, an, betreff, text, html)


def senden(db: Session, mail: Mail) -> None:
    """Eine Mail des Kontenmoduls verschicken. Wirft ``systempost.PostFehler``."""
    en = _englisch(db, mail.account_id)
    name = mail.display_name or mail.username
    hallo = f"Hello {name}" if en else f"Hallo {name}"
    if mail.kind == MAIL_RESET:
        dauer = _stunden(mail.hours, en)
        ziel = link(db, f"/kennwort/{mail.token}")
        if en:
            _senden(db, mail.to, "New password for nexmail", hallo,
                    ["Somebody asked for a new password for your nexmail account.",
                     f"Your username: {mail.username}", "Set a new password with this link:"],
                    ("Set a new password", ziel),
                    f"The link holds {dauer} and works once. If this was not you, nothing has happened: your "
                    "password stays as it is while nobody opens the link.")
        else:
            _senden(db, mail.to, "Neues Passwort für nexmail", hallo,
                    ["für dein nexmail-Konto wurde ein neues Passwort angefordert.",
                     f"Dein Benutzername: {mail.username}", "Über diesen Link setzt du ein neues Passwort:"],
                    ("Neues Passwort setzen", ziel),
                    f"Der Link gilt {dauer} und nur einmal. Warst du das nicht, ist nichts passiert: Solange "
                    "niemand den Link öffnet, bleibt dein Passwort, wie es war.")
    elif mail.kind == MAIL_CONFIRM_EMAIL:
        dauer = _stunden(mail.hours, en)
        ziel = link(db, f"/adresse/{mail.token}")
        if en:
            _senden(db, mail.to, "Confirm your address for nexmail", hallo,
                    [f"Confirm that this address belongs to your nexmail account {mail.username}:"],
                    ("Confirm address", ziel),
                    f"The link holds {dauer}. Until then your old address stays in effect. If this was not you, "
                    "ignore this mail.")
        else:
            _senden(db, mail.to, "Adresse für nexmail bestätigen", hallo,
                    [f"bestätige, dass diese Adresse zu deinem nexmail-Konto {mail.username} gehört:"],
                    ("Adresse bestätigen", ziel),
                    f"Der Link gilt {dauer}. Bis dahin gilt deine bisherige Adresse. Warst du das nicht, "
                    "ignoriere diese Mail.")
    elif mail.kind == MAIL_USERNAME_CHANGED:
        if en:
            _senden(db, mail.to, "Your nexmail username has changed", hallo,
                    [f"Your username is now {mail.username}. You sign in with it from now on."], None,
                    "If this was not you, tell the operator of your nexmail.")
        else:
            _senden(db, mail.to, "Dein nexmail-Benutzername ist neu", hallo,
                    [f"Dein Benutzername ist jetzt {mail.username}. Damit meldest du dich ab jetzt an."], None,
                    "Warst du das nicht, sag dem Betreiber deines nexmail Bescheid.")
    elif mail.kind == MAIL_EMAIL_CHANGED:
        if en:
            satz = (f"The address of your nexmail account {mail.username} is now {mail.new_hint}."
                    if mail.new_hint else f"Your nexmail account {mail.username} has no address any more.")
            _senden(db, mail.to, "Your nexmail address has changed", hallo, [satz], None,
                    "If this was not you, tell the operator of your nexmail.")
        else:
            satz = (f"die Adresse deines nexmail-Kontos {mail.username} ist jetzt {mail.new_hint}."
                    if mail.new_hint else f"dein nexmail-Konto {mail.username} hat keine Adresse mehr.")
            _senden(db, mail.to, "Deine nexmail-Adresse hat sich geändert", hallo, [satz], None,
                    "Warst du das nicht, sag dem Betreiber deines nexmail Bescheid.")
    else:  # pragma: no cover - das Modul kennt nur diese vier
        raise ValueError(f"unknown mail kind {mail.kind!r}")


def einladung_senden(db: Session, einladung: Einladung, schluessel: str, tage: int) -> None:
    """Die Einladungsmail. Wirft ``systempost.PostFehler``. Ohne Benutzernamen: Den waehlt der Eingeladene selbst."""
    ziel = link(db, f"/einladung/{schluessel}")
    name = einladung.anzeigename.strip()
    dauer = _stunden(tage * 24, False)
    _senden(
        db,
        einladung.adresse,
        "Deine Einladung zu nexmail",
        f"Hallo {name}" if name else "Hallo",
        ["du wurdest zu nexmail eingeladen, einem selbstgehosteten E-Mail-Client.",
         "Über diesen Link legst du dein Konto an:"],
        ("Konto anlegen", ziel),
        f"Der Link gilt {dauer}. Wenn du damit nichts anfangen kannst, ignoriere diese Mail; es passiert dann nichts.",
    )
