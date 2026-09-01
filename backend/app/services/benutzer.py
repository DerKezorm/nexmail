"""Benutzer anlegen und Passwoerter pruefen.

⚠️ **Argon2id, nicht bcrypt.** Nexview nimmt bcrypt, und fuer Nexview ist das
in Ordnung. Eine Anwendung, die *alle Postfaecher* ihres Betreibers haelt,
ist ein anderes Ziel: Argon2id ist speicherhart, also auch mit Grafikkarten
teuer zu durchsuchen. Der Unterschied kostet hier nichts - es wird einmal je
Anmeldung gerechnet.

⚠️ **Ein Benutzer darf kein Passwort haben.** Siehe FALLSTRICKE.md §4:
Passwort ist *ein* Anmeldeweg, nicht *der*. Waere es Pflicht, waere reines
OIDC spaeter ein Umbau am Kern.
"""

from __future__ import annotations

import logging
import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Benutzer

logger = logging.getLogger("nexmail.benutzer")

#: Parameter nach den OWASP-Empfehlungen (Stand 2026): 19 MiB Speicher, zwei
#: Durchgaenge, ein Faden. Der Speicher ist der wirksame Teil - er macht die
#: Rechnung auf Grafikkarten unattraktiv. Wer sie aendert: Bestehende Hashes
#: tragen ihre Parameter in sich und bleiben gueltig; ``needs_rehash`` faengt
#: das beim naechsten Anmelden auf.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID)

#: Mindestlaenge. Bewusst keine Regeln ueber Sonderzeichen: Sie erzeugen
#: nachweislich schlechtere Passwoerter ("Passwort1!"), nicht bessere.
MIN_LAENGE = 10

BENUTZERNAME_MUSTER = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


class BenutzerFehler(ValueError):
    pass


def passwort_pruefen_regeln(passwort: str) -> None:
    if len(passwort) < MIN_LAENGE:
        raise BenutzerFehler(f"Das Passwort muss mindestens {MIN_LAENGE} Zeichen haben.")


def benutzername_pruefen(name: str) -> None:
    if not BENUTZERNAME_MUSTER.fullmatch(name):
        raise BenutzerFehler(
            "Der Benutzername darf 3 bis 64 Zeichen haben: Buchstaben, Ziffern, Punkt, "
            "Unterstrich und Bindestrich."
        )


def hashen(passwort: str) -> str:
    return _hasher.hash(passwort)


def passwort_stimmt(benutzer: Benutzer, passwort: str) -> bool:
    """Passwort pruefen.

    ⚠️ Ein Benutzer ohne Passwort meldet sich anders an - fuer diesen Weg ist
    er es nie. Nicht "leeres Passwort passt zu leerem Hash".
    """
    if not benutzer.passwort_hash:
        return False
    try:
        return _hasher.verify(benutzer.passwort_hash, passwort)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_auffrischen(db: Session, benutzer: Benutzer, passwort: str) -> None:
    """Nach einer erfolgreichen Anmeldung: Hash auf aktuelle Parameter heben."""
    try:
        if _hasher.check_needs_rehash(benutzer.passwort_hash):
            benutzer.passwort_hash = _hasher.hash(passwort)
            db.commit()
            logger.info("A password hash was upgraded to the current parameters.")
    except InvalidHashError:  # pragma: no cover - kaputter Bestand
        pass


def passwort_aendern(
    db: Session, benutzer: Benutzer, altes: str, neues: str
) -> None:
    """Das eigene Kennwort ändern.

    ⚠️ **Das alte wird verlangt, obwohl der Benutzer angemeldet ist.** Sonst
    genügt eine geklaute Sitzung — ein offener Rechner, ein mitgelesenes
    Cookie — um den Zugang zu übernehmen und den Eigentümer auszusperren. Das
    alte Kennwort ist der Beweis, dass da der Richtige sitzt.

    ⚠️ **Der Aufrufer beendet danach die übrigen Sitzungen.** Wer sein
    Kennwort ändert, tut das meist, weil er jemand anderen im Verdacht hat —
    ein Wechsel, nach dem der andere angemeldet bleibt, hilft nicht.
    """
    if not passwort_stimmt(benutzer, altes):
        raise BenutzerFehler("Das bisherige Kennwort stimmt nicht.")
    if neues == altes:
        raise BenutzerFehler("Das neue Kennwort ist dasselbe wie das bisherige.")
    passwort_pruefen_regeln(neues)

    benutzer.passwort_hash = hashen(neues)
    db.commit()
    logger.info("A user changed their password.")


def finden(db: Session, benutzername: str) -> Benutzer | None:
    """Benutzer suchen - ohne Ruecksicht auf Gross- und Kleinschreibung.

    Wer sich als "Anna" anmeldet, meint sein Konto "anna". Die Sperre
    gegen zwei Konten, die sich nur darin unterscheiden, sitzt beim Anlegen.
    """
    return db.execute(
        select(Benutzer).where(func.lower(Benutzer.benutzername) == benutzername.strip().lower())
    ).scalar_one_or_none()


def anlegen(
    db: Session,
    benutzername: str,
    passwort: str,
    *,
    anzeigename: str = "",
    ist_betreiber: bool = False,
    ohne_passwort: bool = False,
) -> Benutzer:
    """Ein Konto anlegen.

    ⚠️ **``ohne_passwort`` ist fuer OIDC**, und dort ist es richtig: Ab Stufe 0
    gilt „Passwort ist *ein* Anmeldeweg, nicht *der*". Ein zufaellig gesetztes
    Passwort waere ein Zugang, den niemand kennt und niemand widerrufen kann —
    und beim naechsten Ratelauf zaehlt er trotzdem mit.
    """
    benutzername = benutzername.strip()
    benutzername_pruefen(benutzername)
    if not ohne_passwort:
        passwort_pruefen_regeln(passwort)

    if finden(db, benutzername) is not None:
        raise BenutzerFehler("Diesen Benutzernamen gibt es schon.")

    benutzer = Benutzer(
        benutzername=benutzername,
        anzeigename=anzeigename.strip() or benutzername,
        passwort_hash="" if ohne_passwort else hashen(passwort),
        ist_betreiber=ist_betreiber,
    )
    db.add(benutzer)
    db.commit()
    logger.info("A user account was created (operator=%s).", ist_betreiber)
    return benutzer


def betreiber(db: Session) -> Benutzer | None:
    return db.execute(select(Benutzer).where(Benutzer.ist_betreiber.is_(True))).scalars().first()


def umfang(db: Session, person: Benutzer) -> dict[str, int]:
    """Was an diesem Benutzer haengt — fuer die Rueckfrage vor dem Entfernen.

    ⚠️ **Zahlen statt „alle Daten".** „Wirklich entfernen?" beantwortet man mit
    Ja, ohne nachzudenken. „3 Postfaecher und 12.418 Nachrichten" liest man.
    """
    from ..models import Konto, Kontakt, Nachricht, Regel, Signatur

    def zaehlen(modell) -> int:
        return (
            db.execute(
                select(func.count()).select_from(modell).where(modell.benutzer_id == person.id)
            ).scalar()
            or 0
        )

    return {
        "postfaecher": zaehlen(Konto),
        "nachrichten": zaehlen(Nachricht),
        "kontakte": zaehlen(Kontakt),
        "regeln": zaehlen(Regel),
        "signaturen": zaehlen(Signatur),
    }


def entfernen(db: Session, person: Benutzer) -> None:
    """Einen Benutzer mit allem entfernen, was ihm gehoert.

    ⚠️ **Jede Tabelle mit ``benutzer_id`` wird geleert, und zwar ueber die
    Modelle statt von Hand.** Eine handgeschriebene Liste altert: Wer spaeter
    eine Tabelle dazunimmt, denkt an diese Stelle nicht — und dann bleiben die
    Kontakte eines geloeschten Benutzers liegen, sichtbar fuer niemanden und
    doch da. ``test_benutzer_entfernen`` haelt mit einem Waechter dagegen.

    ⚠️ **Auf dem Mailserver bleibt alles unberuehrt.** nexmail vergisst; es
    loescht keine fremde Post. Das steht auch in der Rueckfrage.
    """
    from ..models import Base

    ich = person.id

    # ⚠️ **Erst die Tabellen, dann der Mensch.** Andersherum stellt SQLAlchemy
    # seine Kaskade auf Sitzungen und Codes zusammen, findet die Zeilen beim
    # Ausfuehren aber nicht mehr — und warnt: „expected to delete 1 row(s); 0
    # were matched". Die Warnung ist harmlos und genau deshalb schaedlich: Sie
    # steht ab dann in jedem Protokoll und niemand liest sie mehr.
    for tabelle in reversed(Base.metadata.sorted_tables):
        if "benutzer_id" not in tabelle.columns:
            continue
        db.execute(tabelle.delete().where(tabelle.c.benutzer_id == ich))

    # Die Beziehungen sind jetzt veraltet; ohne das laeuft die Kaskade erneut.
    db.expire(person)
    db.delete(person)
    db.commit()
    logger.warning("A user account and all of its data were removed.")
