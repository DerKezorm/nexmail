"""Sitzungen - der Zustand liegt im Server, nicht im Token.

⚠️ **Kein JWT.** Ein signiertes Token gilt bis zum Ablauf, egal was passiert:
Wer es abgreift, ist drin, bis die Uhr abgelaufen ist. Hier kostet jede
Anfrage eine Datenbankabfrage und bringt dafuer, was bei einem Mail-Client
zaehlt - **"auf allen Geraeten abmelden" wirkt sofort**, und in den
Einstellungen steht, welche Geraete das sind.

⚠️ **Im Cookie steht der Zufallswert, in der Datenbank sein Hash.** Wer die
Datei liest, hat keine gueltige Sitzung in der Hand.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Benutzer, Sitzung, utcnow
from . import anmeldebremse

logger = logging.getLogger("nexmail.sitzung")

COOKIE_NAME = "nexmail_sitzung"


def cookie_pfad() -> str:
    """Der Pfad, unter dem das Cookie mitfaehrt.

    ⚠️ **Mit Unterpfad traegt er den Vorbau.** Cookie-Pfade prueft der
    *Browser*, und aus dessen Sicht liegt nexmail unter ``/nexmail/api`` - egal
    ob der Proxy den Vorbau durchreicht oder abschneidet; abgeschnitten wird
    erst dahinter. Ohne das faehrt das Cookie nie mit, und niemand kommt
    hinein.

    ``/api`` und nicht ``/``: Das Cookie hat auf dem Weg zu einer statischen
    Datei nichts zu suchen.
    """
    return f"{get_settings().url_base}/api"


def _secure(request: Request) -> bool:
    """Traegt das Cookie ``Secure``?

    ``auto`` schaut auf das Schema **dieser** Anfrage. Das ist bewusst
    zurueckhaltend: Ein Secure-Cookie, das der Browser wegwirft, sperrt jeden
    aus, der nexmail ohne HTTPS betreibt - und das sind bei einer
    selbstgehosteten Anwendung viele. Lieber ein Cookie ohne Secure als eine
    Anmeldung, die nicht mehr geht.

    Hinter einem HTTPS-Proxy, der intern http weiterreicht, sieht nexmail
    ``http``. Dafuer gibt es ``NEXMAIL_COOKIE_SECURE=on``. Geraten wird nicht.
    """
    einstellung = get_settings().cookie_secure
    if einstellung == "on":
        return True
    if einstellung == "off":
        return False
    return request.url.scheme == "https"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _geraet(request: Request) -> str:
    """Was in der Geraeteliste stehen soll. Roh, aber gekuerzt."""
    return (request.headers.get("user-agent") or "")[:200]


def anlegen(
    db: Session,
    benutzer: Benutzer,
    request: Request,
    response: Response,
    *,
    bestaetigt: bool,
) -> Sitzung:
    """Eine Sitzung anlegen und das Cookie setzen.

    ``bestaetigt=False`` heisst: Das Passwort stimmte, der zweite Faktor fehlt
    noch. Eine solche Sitzung darf ausschliesslich den zweiten Schritt
    aufrufen - siehe ``deps.angemeldet``.
    """
    einstellungen = get_settings()
    token = secrets.token_urlsafe(48)
    dauer = (
        timedelta(days=einstellungen.sitzung_tage)
        if bestaetigt
        else timedelta(minutes=einstellungen.zwei_faktor_minuten)
    )

    sitzung = Sitzung(
        benutzer_id=benutzer.id,
        token_hash=_hash(token),
        bestaetigt=bestaetigt,
        geraet=_geraet(request),
        adresse=anmeldebremse.adresse_von(request),
        gueltig_bis=utcnow() + dauer,
    )
    db.add(sitzung)
    db.commit()

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(dauer.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=_secure(request),
        path=cookie_pfad(),
    )
    return sitzung


def bestaetigen(db: Session, sitzung: Sitzung, request: Request, response: Response) -> None:
    """Aus dem Zwischenschritt eine vollwertige Sitzung machen."""
    dauer = timedelta(days=get_settings().sitzung_tage)
    sitzung.bestaetigt = True
    sitzung.gueltig_bis = utcnow() + dauer
    db.commit()

    # Der Browser bekommt dasselbe Token mit neuer Laufzeit. Ein Tausch waere
    # sauberer - und wuerde beim ersten Netzwackler zwischen "gesetzt" und
    # "angekommen" die Anmeldung verlieren.
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=int(dauer.total_seconds()),
            httponly=True,
            samesite="strict",
            secure=_secure(request),
            path=cookie_pfad(),
        )


def holen(db: Session, request: Request) -> Sitzung | None:
    """Die Sitzung zum Cookie - oder nichts."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    sitzung = db.execute(
        select(Sitzung).where(Sitzung.token_hash == _hash(token))
    ).scalar_one_or_none()
    if sitzung is None:
        return None

    if sitzung.gueltig_bis <= utcnow():
        db.delete(sitzung)
        db.commit()
        return None

    # Gleitende Verlaengerung, aber nur einmal je Stunde: Sonst schriebe jede
    # einzelne Anfrage in die Datenbank, und bei einem Mail-Client sind das
    # viele.
    if sitzung.bestaetigt and (utcnow() - sitzung.zuletzt_gesehen) > timedelta(hours=1):
        sitzung.zuletzt_gesehen = utcnow()
        sitzung.gueltig_bis = utcnow() + timedelta(days=get_settings().sitzung_tage)
        db.commit()

    return sitzung


def beenden(db: Session, sitzung: Sitzung, response: Response) -> None:
    db.delete(sitzung)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path=cookie_pfad())


def alle_beenden(db: Session, benutzer: Benutzer, ausser: str | None = None) -> int:
    """Auf allen Geraeten abmelden. Wirkt sofort - das ist der ganze Punkt."""
    anzahl = 0
    for sitzung in list(benutzer.sitzungen):
        if ausser is not None and sitzung.id == ausser:
            continue
        db.delete(sitzung)
        anzahl += 1
    db.commit()
    logger.info("%s session(s) were revoked.", anzahl)
    return anzahl


def aufraeumen(db: Session) -> int:
    """Abgelaufene Sitzungen wegwerfen. Beim Start aufgerufen."""
    abgelaufen = db.execute(select(Sitzung).where(Sitzung.gueltig_bis <= utcnow())).scalars().all()
    for sitzung in abgelaufen:
        db.delete(sitzung)
    if abgelaufen:
        db.commit()
    return len(abgelaufen)
