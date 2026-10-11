"""Beim Start: die Anbieterliste von 0.21 auf den Bauplan nachziehen, und was 0.21 nach einem Rueckweg geaendert hat.

nexmail hatte schon eine Liste (``oidc_anbieter``, ``oidc_verknuepfung``). Die neuen Spalten legt die Schemapflege an
(``db._fehlende_spalten``), alle mit Vorgabe oder NULL; die Namen der alten bleiben, denn 0.21 liest dieselben
Tabellen. Hier passiert der Rest, bei jedem Start, in einer Transaktion:

1. **Nummern** fuer Konten und Eintraege ohne (das Modul rechnet mit ganzen Zahlen).
2. **Eintraege, die 0.21 angelegt hat** (``redirect_path`` NULL, beim ersten Start also alle): Ihr Anbieter kennt die
   Rueckleitadresse ``/api/oidc/<kuerzel>/zurueck``; sie wird ihr ``redirect_path`` und bleibt gueltig (Bauplan 01,
   letzter Absatz; 06 "Pfad der Schnittstelle"). Der Eintrag mit dem Kurznamen ``authentik``, dessen Aussteller auf
   ``/application/o/<slug>/`` endet, kam vom authentik-Knopf von 0.21: ``managed = "authentik"``. Eingeschaltet ist,
   was 0.21 eingeschaltet hatte; den zweiten Faktor fragte 0.21 nach dem Anbieter nie (``trusts_second_factor`` an).
3. **Was 0.21 an einem Eintrag geaendert hat:** ``aktiv`` ist der Spiegel fuer 0.21 (an nur, wenn der Eintrag an ist
   und dem Anbieter den zweiten Faktor glaubt). Weicht er ab, hat 0.21 umgeschaltet: an heisst Eintrag an und
   „Anbieter prueft den zweiten Faktor selbst" an (so verhielt sich 0.21), aus heisst Eintrag aus.
4. **Geheimnis:** Was in der Spalte von 0.21 steht, gilt; weicht die Spalte mit dem Kontext des Bauplans davon ab
   (0.21 hat es geaendert), wird sie neu geschrieben.
5. **Verknuepfungen:** Jede gehoert dem Eintrag, zu dessen Aussteller ihr ``issuer`` passt (bei Entra mit ``common``
   der echte Mandant an der Stelle des Platzhalters). Eine Zeile von 0.21 (ohne Eintrag) wird zugeordnet; eine Zeile,
   deren Eintrag in 0.21 einen anderen Aussteller bekommen hat, verliert ihn (sie meldet dort nicht mehr an, wie in
   0.21). Ein Konto hat je Eintrag hoechstens eine Identitaet: die aelteste Zeile gewinnt.

Vor einer Aenderung an einer bestehenden Liste wird die Datenbank gesichert (``db._sichern``, ein Ruecksetzpunkt
unter ``sicherungen/``). Aussteller, Kurznamen und Verknuepfungen behalten ihre Schreibweise.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..models import Benutzer, OidcAnbieter, OidcVerknuepfung
from ..vendor.nexoidc import migrate, protocol, secret_context
from .oidc_store import alter_kontext, eingeschaltet, fuer_alte_fassung_aktiv

logger = logging.getLogger("nexmail.oidc")

#: Die Rueckleitadresse von 0.21. Der Anbieter jedes Eintrags von damals kennt nur sie.
ALTE_RUECKKEHR = "/api/oidc/{slug}/zurueck"
#: Kurzname, an dem der authentik-Knopf von 0.21 seinen Eintrag erkannte.
ALTER_KNOPF = "authentik"
_AUTHENTIK_AUSSTELLER = re.compile(r"/application/o/[-A-Za-z0-9_]+/?$")
#: Was bei Entra an Stelle einer Mandanten-Kennung im eingetragenen Aussteller stehen darf.
_SAMMELMANDANTEN = ("common", "organizations", "consumers")
_MANDANT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def gehoert_zum_anbieter(anbieter_issuer: str, verknuepft_issuer: str) -> bool:
    """Ob eine Verknuepfung (``iss`` ihres Tokens) zum Aussteller eines Eintrags gehoert.

    Derselbe Aussteller (``same_issuer``), oder Entra: Der Eintrag steht mit ``common`` (``organizations``,
    ``consumers``) da, die Verknuepfung traegt an genau dieser Stelle einen Mandanten.
    """
    if not anbieter_issuer or not verknuepft_issuer:
        return False
    if protocol.same_issuer(anbieter_issuer, verknuepft_issuer):
        return True
    teile_a = protocol.normalize_issuer(anbieter_issuer).split("/")
    teile_v = protocol.normalize_issuer(verknuepft_issuer).split("/")
    if len(teile_a) != len(teile_v):
        return False
    anders = [i for i, (a, v) in enumerate(zip(teile_a, teile_v)) if a != v]
    return (
        len(anders) == 1
        and anders[0] > 2
        and teile_a[anders[0]] in _SAMMELMANDANTEN
        and bool(_MANDANT.fullmatch(teile_v[anders[0]]))
    )


def laufen(engine: Engine) -> None:
    """Der ganze Abgleich beim Start. Laeuft nach der Schemapflege und nach dem Laden des Datenschluessels.

    Erst zur Probe: Aendert sich an einer bestehenden Liste etwas, wird zurueckgerollt, gesichert und noch einmal
    gelaufen. Ein Start ohne Aenderung schreibt nichts, sichert nichts und meldet nichts.
    """
    with Session(engine) as db:
        vorhanden = bool(
            db.scalar(select(func.count()).select_from(OidcAnbieter.__table__))
            or db.scalar(select(func.count()).select_from(OidcVerknuepfung.__table__))
        )
        meldungen: list[tuple[int, str]] = []
        if _schritte(db, meldungen) == 0:
            db.commit()
            return
        db.rollback()
    if vorhanden:
        from ..db import _sichern

        _sichern()
    with Session(engine) as db:
        meldungen = []
        _schritte(db, meldungen)
        db.commit()
    for stufe, text in meldungen:
        logger.log(stufe, text)


def _schritte(db: Session, meldungen: list[tuple[int, str]]) -> int:
    """Alle Schritte in einer Transaktion; die Zahl der geaenderten Dinge (Nummern zaehlen nicht als Aenderung an
    einer Liste, sie werden auch ohne Sicherung festgeschrieben)."""
    _nummern(db)
    return (
        _alte_eintraege(db, meldungen)
        + _umgeschaltet(db, meldungen)
        + _geheimnisse(db, meldungen)
        + _verknuepfungen(db, meldungen)
    )


def _nummern(db: Session) -> None:
    for tabelle in (Benutzer, OidcAnbieter):
        hoechste = db.scalar(select(func.coalesce(func.max(tabelle.nummer), 0))) or 0
        for row in db.scalars(select(tabelle).where(tabelle.nummer.is_(None)).order_by(tabelle.id)):
            hoechste += 1
            row.nummer = hoechste
        db.flush()


def _alte_eintraege(db: Session, meldungen: list[tuple[int, str]]) -> int:
    rows = list(
        db.scalars(select(OidcAnbieter).where(OidcAnbieter.redirect_path.is_(None)).order_by(OidcAnbieter.angelegt))
    )
    for row in rows:
        row.redirect_path = migrate.old_callback(ALTE_RUECKKEHR, row.kuerzel)
        if row.kuerzel == ALTER_KNOPF and _AUTHENTIK_AUSSTELLER.search(row.issuer or "") and not row.managed:
            row.managed = "authentik"
        if row.eingeschaltet is None:
            row.eingeschaltet = bool(row.aktiv)
            row.trusts_second_factor = True
    if rows:
        meldungen.append(
            (logging.INFO, f"{len(rows)} sign-in provider(s) from nexmail 0.21 keep their redirect address {ALTE_RUECKKEHR}.")
        )
    db.flush()
    return len(rows)


def _umgeschaltet(db: Session, meldungen: list[tuple[int, str]]) -> int:
    geaendert = 0
    for row in db.scalars(select(OidcAnbieter)):
        soll = fuer_alte_fassung_aktiv(eingeschaltet(row), bool(row.trusts_second_factor))
        if bool(row.aktiv) == soll:
            continue
        geaendert += 1
        if row.aktiv:
            # 0.21 hat den Eintrag eingeschaltet. Dort fragte nach dem Anbieter niemand den Code.
            row.eingeschaltet, row.trusts_second_factor = True, True
            meldungen.append(
                (logging.INFO, f"Sign-in provider {row.kuerzel} was switched on in nexmail 0.21; it is on here too.")
            )
        else:
            row.eingeschaltet = False
            meldungen.append(
                (logging.INFO, f"Sign-in provider {row.kuerzel} was switched off in nexmail 0.21; it is off here too.")
            )
    db.flush()
    return geaendert


def _geheimnisse(db: Session, meldungen: list[tuple[int, str]]) -> int:
    geaendert = 0
    for row in db.scalars(select(OidcAnbieter)):
        try:
            alt = crypto.entschluesseln(row.client_secret or "", alter_kontext(row.id))
            neu = crypto.entschluesseln(row.client_secret_enc or "", secret_context(row.nummer))
        except crypto.SchluesselFehler:
            meldungen.append((logging.WARNING, f"The client secret of sign-in provider {row.kuerzel} cannot be read."))
            continue
        if alt != neu:
            row.client_secret_enc = crypto.verschluesseln(alt, secret_context(row.nummer)) if alt else ""
            geaendert += 1
    if geaendert:
        meldungen.append(
            (logging.INFO, f"Took over the credentials of {geaendert} sign-in provider(s) as nexmail 0.21 stored them.")
        )
    db.flush()
    return geaendert


def _verknuepfungen(db: Session, meldungen: list[tuple[int, str]]) -> int:
    eintraege = list(db.scalars(select(OidcAnbieter).order_by(OidcAnbieter.position, OidcAnbieter.nummer)))
    nach_id = {row.id: row for row in eintraege}
    konten: set[tuple[str, str]] = set()
    kennungen: set[tuple[str, str]] = set()
    ziele: dict[int, str | None] = {}
    links = list(db.scalars(select(OidcVerknuepfung).order_by(OidcVerknuepfung.id)))
    # Wer schon richtig sitzt, behaelt seinen Platz; erst danach werden die anderen verteilt.
    links.sort(key=lambda link: 0 if link.anbieter_id in nach_id else 1)
    for link in links:
        jetzt = nach_id.get(link.anbieter_id or "")
        if jetzt is not None and gehoert_zum_anbieter(jetzt.issuer, link.issuer):
            ziel = jetzt
        else:
            # Genau so geschrieben zuerst, dann Entra (``common`` gegen den echten Mandanten).
            genau = [row for row in eintraege if protocol.same_issuer(row.issuer, link.issuer)]
            passend = genau or [row for row in eintraege if gehoert_zum_anbieter(row.issuer, link.issuer)]
            ziel = next(iter(passend), None)
        if ziel is not None and ((ziel.id, link.benutzer_id) in konten or (ziel.id, link.subject) in kennungen):
            ziel = None
        if ziel is not None:
            konten.add((ziel.id, link.benutzer_id))
            kennungen.add((ziel.id, link.subject))
        ziele[link.id] = ziel.id if ziel is not None else None
    wechsel = [link for link in links if ziele[link.id] != link.anbieter_id]
    # Zwei Schritte, sonst stiessen zwei Zeilen, die die Plaetze tauschen, an den eindeutigen Indizes an.
    for link in wechsel:
        link.anbieter_id = None
    db.flush()
    zugeordnet = geloest = 0
    for link in wechsel:
        link.anbieter_id = ziele[link.id]
        if link.anbieter_id is None:
            geloest += 1
        else:
            zugeordnet += 1
    db.flush()
    if zugeordnet:
        meldungen.append((logging.INFO, f"{zugeordnet} link(s) from nexmail 0.21 belong to their sign-in provider now."))
    if geloest:
        meldungen.append(
            (
                logging.WARNING,
                (
                    f"{geloest} link(s) no longer match the issuer of their sign-in provider (changed in nexmail "
                    "0.21) or would be a second identity of an account there; they sign in nowhere."
                ),
            )
        )
    return len(wechsel)
