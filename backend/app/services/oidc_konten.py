"""Was mit einer geprueften OIDC-Identitaet geschieht.

Der Weg zur Identitaet liegt in ``services/oidc``; hier steht nur noch die
Frage „wer ist das, und bekommt diese Person ein nexmail-Konto?".

⚠️ **Eine Adresse oeffnet hier nichts mehr, auch keine Einladung.** Bis zum
09.10.2026 fand eine Anmeldung ueber den Anbieter eine offene Einladung an
ihre bestaetigte Adresse (``email_verified``). Das trug zweimal nicht: Entra ID
schickt gar kein ``email_verified``, also ging es dort nie, und in authentik
kann jeder seine Adresse selbst aendern, also auch auf die einer fremden
offenen Einladung. Jetzt ist der Schluessel aus der Einladungsmail der
Nachweis, wie beim Annehmen mit Kennwort; die Einladungsseite nimmt ihn mit
zum Anbieter (``routers/oidc.einladung_starten``).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, OidcVerknuepfung
from . import benutzer as benutzerdienst
from .oidc import Identitaet, OidcFehler

logger = logging.getLogger("nexmail.oidc")


def verknuepfung_suchen(db: Session, ident: Identitaet) -> OidcVerknuepfung | None:
    """⚠️ Ueber ``(issuer, subject)``, nie ueber die Adresse.

    Adressen wechseln den Besitzer, ``subject`` nicht. Wer ueber die Adresse
    verknuepft, baut eine Kontouebernahme ein.
    """
    return db.execute(
        select(OidcVerknuepfung).where(
            OidcVerknuepfung.issuer == ident.issuer,
            OidcVerknuepfung.subject == ident.subject,
        )
    ).scalar_one_or_none()


def verknuepfen(db: Session, person: Benutzer, ident: Identitaet) -> OidcVerknuepfung:
    """Eine Identitaet an ein bestehendes Konto haengen."""
    vorhanden = verknuepfung_suchen(db, ident)
    if vorhanden is not None:
        if vorhanden.benutzer_id != person.id:
            raise OidcFehler(
                "oidc_fremd_verknuepft",
                "This identity already belongs to a different nexmail account.",
            )
        return vorhanden

    verknuepfung = OidcVerknuepfung(
        benutzer_id=person.id,
        issuer=ident.issuer,
        subject=ident.subject,
        adresse_bestaetigt=ident.adresse_bestaetigt,
    )
    db.add(verknuepfung)
    db.commit()
    logger.info("An OIDC identity was linked to an account.")
    return verknuepfung


def aufloesen(db: Session, ident: Identitaet) -> Benutzer:
    """Wer ist das? — ueber die Anmeldeseite nur noch eine Antwort.

    **Eine bestehende Verknuepfung.** Sie entsteht, wenn jemand sich angemeldet
    verknuepft oder eine Einladung ueber den Anbieter annimmt
    (``einladung_einloesen``). Der zweite Weg herein ist die Einladungsseite,
    nicht diese hier.

    ⚠️ **Kein Abgleich mit bestehenden Konten** (so entschieden am 01.09.2026).
    Vorher galt: „bestaetigte Adresse trifft vorhandenes Konto" — das war die
    Stelle, an der ein Anbieter mit einer erschwindelten Adresse ein fremdes
    Konto haette oeffnen koennen, und die ganze ``email_verified``-Pruefung
    existierte nur, um sie abzusichern.

    Der Betreiber: „Ist die Frage ob man einen Verknuepfen button einfach ins profil
    macht und generell nur bereits eingeladene Konten reinlaesst?" — Genau so.
    Eine Einladung **ist** die Erlaubnis, und sie wurde bewusst ausgesprochen.
    Damit faellt auch der Schalter „Neue Konten anlegen" ersatzlos weg.
    """
    verknuepfung = verknuepfung_suchen(db, ident)
    if verknuepfung is not None:
        person = db.get(Benutzer, verknuepfung.benutzer_id)
        if person is None:
            # Die Verknuepfung zeigt ins Leere — das Konto wurde entfernt.
            db.delete(verknuepfung)
            db.commit()
        else:
            return person

    raise OidcFehler(
        "oidc_kein_konto",
        # ⚠️ Nicht „with a password and …" schreiben: Die Zensur im Protokoll
        # schwaerzt das Wort nach „password", und heraus kam „password *****".
        "No nexmail account matches this sign-in. Link the provider under "
        "Security once signed in, or open the invitation link from the "
        "operator's mail.",
    )


def einladung_einloesen(db: Session, ident: Identitaet, einladung_id: str) -> Benutzer:
    """Aus der Einladung, deren Kennung im signierten Anlauf steht, ein Konto machen.

    ⚠️ **Die Einladung wird hier noch einmal geprueft.** Zwischen Hin- und
    Rueckweg liegen Minuten beim Anbieter; in der Zeit kann sie jemand mit
    Kennwort angenommen oder der Betreiber sie zurueckgezogen haben.

    ⚠️ **Eine schon verknuepfte Identitaet loest keine zweite Einladung
    ein.** Sonst haette ein Mensch zwei Konten, und die Anmeldung fuehrte nur
    noch in eins davon.
    """
    from datetime import datetime, timezone

    from ..models import Einladung
    from .einladung import abgelaufen

    einladung = db.get(Einladung, einladung_id) if einladung_id else None
    if einladung is None or einladung.eingeloest is not None or abgelaufen(einladung):
        raise OidcFehler(
            "oidc_einladung_ungueltig",
            "The invitation was redeemed, withdrawn or has expired in the meantime.",
        )
    if verknuepfung_suchen(db, ident) is not None:
        raise OidcFehler(
            "oidc_fremd_verknuepft",
            "This identity already belongs to a different nexmail account.",
        )
    # ⚠️ Dieselbe Pruefung wie beim Annehmen mit Kennwort: Der Name kann in
    # der Zwischenzeit vergeben worden sein.
    if benutzerdienst.finden(db, einladung.benutzername) is not None:
        raise OidcFehler(
            "oidc_benutzername_vergeben",
            "The user name of this invitation was taken in the meantime.",
        )

    neuer = benutzerdienst.anlegen(
        db,
        einladung.benutzername,
        # ⚠️ **Kein Passwort.** Ab Stufe 0 darf ein Benutzer keins haben —
        # dieser Mensch meldet sich anders an. Ein zufaelliges zu setzen waere
        # ein Zugang, den niemand kennt und niemand widerrufen kann.
        passwort="",
        anzeigename=ident.anzeigename or einladung.anzeigename,
        ohne_passwort=True,
    )
    # ⚠️ **Dieselbe Einladung, dasselbe Ergebnis.** Der Weg ueber ein Kennwort
    # traegt die Adresse der Einladung als Kontaktadresse ein; ohne diese Zeile
    # haette ein ueber OIDC eingeloester Mensch keine — und damit keinen Weg
    # zurueck, wenn seine Verknuepfung einmal wegfaellt.
    neuer.kontaktadresse = einladung.adresse
    einladung.eingeloest = datetime.now(timezone.utc)
    db.commit()
    verknuepfen(db, neuer, ident)
    logger.info("An invitation was redeemed through an OIDC provider.")
    return neuer
