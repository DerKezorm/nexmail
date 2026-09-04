"""Was mit einer geprueften OIDC-Identitaet geschieht.

Der Weg zur Identitaet liegt in ``services/oidc``; hier steht nur noch die
Frage „wer ist das, und bekommt diese Person ein nexmail-Konto?".

⚠️ **Die Adress-Bruecke zaehlt nur bei bestaetigter Adresse.** Ein
OIDC-Anbieter sagt ausdrueckisch dazu, ob er fuer die Adresse buergt
(``email_verified``) — und bei „nein" waere die Bruecke eine offene Tuer: Wer
sich bei irgendeinem Anbieter ein Konto mit fremder Adresse anlegt, uebernaehme
darueber das fremde nexmail-Konto samt allen Postfaechern.
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
    """Wer ist das? — zwei Wege, mehr nicht.

    1. **Eine bestehende Verknuepfung.** Der Normalfall ab der zweiten
       Anmeldung; sie entsteht, wenn jemand sich angemeldet verknuepft.
    2. **Eine offene Einladung an genau diese Adresse.** Daraus entsteht das
       Konto, und die Einladung gilt als angenommen.

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

    einladung = _offene_einladung(db, ident)
    if einladung is None:
        raise OidcFehler(
            "oidc_kein_konto",
            "No nexmail account matches this sign-in. Sign in with a password and "
            "link the provider in the settings, or ask the operator for an "
            "invitation.",
        )

    from datetime import datetime, timezone

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


def _offene_einladung(db: Session, ident: Identitaet):
    """Eine offene Einladung an genau diese Adresse — oder ``None``.

    ⚠️ **Die Adresse muss bestaetigt sein.** Sonst genuegte ein Anbieter, bei
    dem man sich eine beliebige Adresse eintragen darf, um eine fremde
    Einladung einzuloesen. Die Einladung nennt eine Adresse; der Anbieter muss
    dafuer buergen.
    """
    if not ident.adresse or not ident.adresse_bestaetigt:
        return None
    from .einladung import abgelaufen, offene

    for e in offene(db):
        if e.adresse.strip().lower() == ident.adresse and not abgelaufen(e):
            return e
    return None
