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
from ..vendor.nexkonten import sessions as kontensitzungen
from . import anmeldebremse

logger = logging.getLogger("nexmail.sitzung")

COOKIE_NAME = "nexmail_sitzung"

#: Das Cookie „bekannter Browser“ (Kontenmodul Teil 2): bis zu fuenf Marken, je Konto eine, signiert ueber den
#: Geraeteschluessel des Kontos. Ein neues Passwort macht alle Marken des Kontos wertlos.
BEKANNT_COOKIE = "nexmail_bekannt"

#: „Angemeldet bleiben“ aus: Die Sitzung endet mit dem Browser, spaetestens nach 12 Stunden (Entwurf, Teil 2).
BROWSER_STUNDEN = kontensitzungen.BROWSER_HOURS


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


def _volle_dauer(merken: bool) -> timedelta:
    """Wie lange eine volle Sitzung gilt: gemerkt ``sitzung_tage`` (30, gleitend), sonst 12 Stunden fest."""
    return timedelta(days=get_settings().sitzung_tage) if merken else timedelta(hours=BROWSER_STUNDEN)


def _cookie_setzen(request: Request, response: Response, token: str, max_age: int | None) -> None:
    """``max_age=None``: ein Cookie, das mit dem Browser endet („Angemeldet bleiben“ aus)."""
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=_secure(request),
        path=cookie_pfad(),
    )


def _volles_cookie(merken: bool) -> int | None:
    """Gemerkt lebt das Cookie 400 Tage (wie im Kontenmodul): Die Sitzung gleitet im Server, und ein Cookie, das
    nach 30 Tagen ab der Anmeldung verfaellt, schnitte das Gleiten ab. Ohne Merken endet es mit dem Browser."""
    return kontensitzungen.REMEMBER_COOKIE_DAYS * 86400 if merken else None


def anlegen(
    db: Session,
    benutzer: Benutzer,
    request: Request,
    response: Response,
    *,
    bestaetigt: bool,
    merken: bool = True,
) -> Sitzung:
    """Eine Sitzung anlegen und das Cookie setzen.

    ``bestaetigt=False`` heisst: Das Passwort stimmte, der zweite Faktor fehlt
    noch. Eine solche Sitzung darf ausschliesslich den zweiten Schritt
    aufrufen - siehe ``deps.angemeldet``. ``merken`` ist „Angemeldet bleiben“
    (Kontenmodul Teil 2, ab Werk an); eine halbe Sitzung traegt es bis zum
    zweiten Schritt.
    """
    einstellungen = get_settings()
    token = secrets.token_urlsafe(48)
    dauer = _volle_dauer(merken) if bestaetigt else timedelta(minutes=einstellungen.zwei_faktor_minuten)

    sitzung = Sitzung(
        benutzer_id=benutzer.id,
        token_hash=_hash(token),
        bestaetigt=bestaetigt,
        geraet=_geraet(request),
        adresse=anmeldebremse.adresse_von(request),
        gueltig_bis=utcnow() + dauer,
        merken=merken,
    )
    db.add(sitzung)
    db.commit()

    _cookie_setzen(
        request, response, token, _volles_cookie(merken) if bestaetigt else int(dauer.total_seconds())
    )
    return sitzung


def bestaetigen(db: Session, sitzung: Sitzung, request: Request, response: Response) -> None:
    """Aus dem Zwischenschritt eine vollwertige Sitzung machen."""
    merken = bool(sitzung.merken)
    sitzung.bestaetigt = True
    sitzung.gueltig_bis = utcnow() + _volle_dauer(merken)
    db.commit()

    # Der Browser bekommt dasselbe Token mit neuer Laufzeit. Ein Tausch waere
    # sauberer - und wuerde beim ersten Netzwackler zwischen "gesetzt" und
    # "angekommen" die Anmeldung verlieren.
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        _cookie_setzen(request, response, token, _volles_cookie(merken))


def holen(db: Session, request: Request) -> Sitzung | None:
    """Die Sitzung zum Cookie - oder nichts."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    # ⚠️ **Nur Browser-Sitzungen.** Ein Gerätetoken im Cookie öffnet nichts,
    # auch wenn sein Hash in derselben Tabelle steht.
    sitzung = db.execute(
        select(Sitzung).where(Sitzung.token_hash == _hash(token), Sitzung.art == "browser")
    ).scalar_one_or_none()
    if sitzung is None:
        return None

    if sitzung.gueltig_bis <= utcnow():
        db.delete(sitzung)
        db.commit()
        return None

    # Gleitende Verlaengerung, aber nur einmal je Stunde: Sonst schriebe jede
    # einzelne Anfrage in die Datenbank, und bei einem Mail-Client sind das
    # viele. ⚠️ **Nur gemerkte Sitzungen gleiten**; ohne „Angemeldet bleiben“
    # ist nach 12 Stunden Schluss, egal wie viel gearbeitet wurde.
    if sitzung.bestaetigt and sitzung.merken and (utcnow() - sitzung.zuletzt_gesehen) > timedelta(hours=1):
        sitzung.zuletzt_gesehen = utcnow()
        sitzung.gueltig_bis = utcnow() + timedelta(days=get_settings().sitzung_tage)
        db.commit()

    return sitzung


#: Die Vorsilbe eines Gerätetokens. ``nxm_`` trägt der API-Schlüssel.
GERAET_VORSILBE = "nxa_"

#: ⚠️ **Zehn Jahre, also praktisch ohne Ablauf.** Eine App, die drei Wochen
#: im Urlaub nicht geöffnet wurde, soll nicht neu gekoppelt werden müssen.
#: Getrennt wird ein Gerät ausdrücklich, nicht durch eine Uhr.
GERAET_TAGE = 3650


def geraet_anlegen(db: Session, benutzer: Benutzer, name: str, adresse: str) -> str:
    """Ein Gerät so anlegen, wie nexmail bis 0.34 koppelte (ohne die Spalten des Gerätemoduls). Gekoppelt wird seit
    0.35.0 über das Modul (``routers/geraete.py``); das hier schreibt noch die Tests und der Vertragsadapter
    (``tests/nexgeraete_adapter.make_legacy``), damit der Bestand geprüft bleibt. Der Rückgabewert steht nur hier im
    Klartext. Geprüft wird ein Gerät vom Modul (``deps._geraet``)."""
    token = GERAET_VORSILBE + secrets.token_urlsafe(48)
    db.add(
        Sitzung(
            benutzer_id=benutzer.id,
            token_hash=_hash(token),
            bestaetigt=True,
            art="geraet",
            geraet=name,
            adresse=adresse,
            gueltig_bis=utcnow() + timedelta(days=GERAET_TAGE),
        )
    )
    db.commit()
    return token


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


# --- Bekannter Browser (Kontenmodul Teil 2) ------------------------------------------------------------------------


def _markengeheimnis() -> bytes:
    """Abgeleitet vom Serverschluessel, mit eigenem Zweck: dieselbe Marke taugt nirgends sonst."""
    return hashlib.sha256(b"nexmail-known-browser:" + get_settings().resolved_secret_key().encode("utf-8")).digest()


def bekannt(request: Request, store, konto_id: str) -> bool:
    """Ob dieser Browser eine gueltige Marke fuer das Konto traegt. Er ist dann von der Kontosperre ausgenommen, und
    die Mail „Neue Anmeldung“ bleibt aus."""
    return bool(bekannte_marke(request, store, konto_id))


def bekannte_marke(request: Request, store, konto_id: str) -> str:
    """Die gueltige Marke dieses Browsers fuer das Konto, ``""`` ohne (``sessions.known_mark``): der eigene Topf an
    der Bremse."""
    zeile = store.db.get(Benutzer, str(konto_id))
    if zeile is None or not zeile.geraete_schluessel:
        return ""
    return kontensitzungen.known_mark(
        request.cookies.get(BEKANNT_COOKIE, ""), _markengeheimnis(), zeile.geraete_schluessel
    )


def bekannt_merken(request: Request, response: Response, store, konto_id: str) -> None:
    """Dem Browser eine Marke fuer das Konto geben (die neueste zuerst, hoechstens fuenf). Der Aufrufer committet."""
    marke = kontensitzungen.mark(_markengeheimnis(), store.device_key(konto_id))
    response.set_cookie(
        BEKANNT_COOKIE,
        kontensitzungen.add_mark(request.cookies.get(BEKANNT_COOKIE, ""), marke),
        max_age=kontensitzungen.MARK_COOKIE_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=_secure(request),
        path=cookie_pfad(),
    )


def angemeldet(db: Session, benutzer: Benutzer, request: Request, response: Response, *, mail: bool = True) -> None:
    """Nach jeder **vollen** Anmeldung im Browser (Passwort, Code, Anbieter): kennt nexmail den Browser fuer dieses
    Konto noch nicht, geht die Mail „Neue Anmeldung“ an die bestaetigte Adresse (abschaltbar im Profil); danach traegt
    der Browser die Marke. ``mail=False`` beim Anlegen eines Kontos: Dort ist jeder Browser neu."""
    from . import konten_store, kontenpost

    store = konten_store.store_fuer(db)
    war_bekannt = bekannt(request, store, benutzer.id)
    bescheid = None
    if mail and not war_bekannt:
        bescheid = kontensitzungen.new_sign_in(
            store.get_account(benutzer.id), known=False, wanted=bool(benutzer.mail_neue_anmeldung)
        )
    bekannt_merken(request, response, store, benutzer.id)
    db.commit()
    if bescheid is None or not kontenpost.mail_moeglich(db):
        return
    # post 0.1.1: der rohe User-Agent; das Mailmodul macht daraus „Firefox auf Linux“ und laesst kein Wort der
    # Kopfzeile selbst in die Mail (eine Kopfzeile ist fremder Text).
    try:
        kontenpost.senden(db, bescheid, where=_geraet(request))
    except Exception as fehler:  # noqa: BLE001 - die Anmeldung gilt, auch wenn der Bescheid nicht hinausgeht
        logger.warning("The new sign-in mail could not be queued: %r", getattr(fehler, "kennung", fehler))


def naechster_schritt(db: Session, benutzer: Benutzer) -> str:
    """Was nach Passwort oder Anbieter kommt: entscheidet das Modul (``common.next_step``, konten 0.3.2) aus
    ``factor.state``: ``second_factor`` (Code), ``passkey`` (bei „fuer alle verlangen“ ein Passkey statt einer App),
    ``second_factor_setup`` (verlangt, keiner da), ``session``. Der Nothammer (``NEXMAIL_ZWEI_FAKTOR_AUS`` oder
    ``NEXMAIL_SECOND_FACTOR_OFF``) schlaegt alles, im Modul selbst (konten 0.3.3)."""
    from ..vendor.nexkonten import common
    from . import konten_store

    store = konten_store.store_fuer(db)
    return common.next_step(store, store.get_account(benutzer.id))


def faktor_einrichten(db: Session, benutzer: Benutzer) -> bool:
    """Ob diese Anmeldung erst einen zweiten Faktor einrichten muss (``second_factor_setup``). Dann liegt ein
    frisches, unbestaetigtes Geheimnis bereit (ein schon bereitliegendes bleibt, damit ein halb eingescannter QR-Code
    weiter passt), die Anmeldung wird eine halbe Sitzung, und ``/api/auth/code`` bestaetigt beides zugleich.

    Seit konten 0.3.4 richtet das Modul ein (``factor.begin_totp``, ``pending_setup``): versiegelt in der Datenbank,
    ueberlebt einen Neustart und wartet zehn Minuten; eine Einrichtung der Vorfassung (unbestaetigtes
    ``totp_geheimnis``) wartet weiter ohne Ende, damit ein schon eingescannter QR-Code passt."""
    from ..vendor.nexkonten import NEXT_SECOND_FACTOR_SETUP, factor
    from .konten_store import store_fuer

    if naechster_schritt(db, benutzer) != NEXT_SECOND_FACTOR_SETUP:
        return False
    store = store_fuer(db)
    if factor.pending_setup(store, benutzer.id, issuer="nexmail") is None:
        factor.begin_totp(store, benutzer.id, issuer="nexmail")
    return True


def passkey_als_zweiter_schritt(db: Session, benutzer: Benutzer) -> bool:
    """``passkey``: Der Betreiber verlangt einen zweiten Faktor, das Konto hat statt einer App einen Passkey. Ohne
    den Schalter ist ein Konto nur mit Passkey ``none``, das Passwort allein genuegt."""
    from ..vendor.nexkonten import NEXT_PASSKEY

    return naechster_schritt(db, benutzer) == NEXT_PASSKEY


#: Das Cookie der wartenden Anmeldung im Modul (``factor.start_waiting``), wenn ein Passkey der zweite Schritt ist.
WARTET_COOKIE = "nexmail_wartet"


def passkey_warten(request: Request, response: Response, benutzer: Benutzer, *, merken: bool) -> None:
    """Die wartende Anmeldung im Modul, die ``factor.finish_waiting_by_passkey`` mit dem Passkey desselben Kontos
    abschliesst; daneben steht nexmails halbe Sitzung (``bestaetigt=False``), die nie als volle gilt."""
    from ..vendor.nexkonten import factor

    token = factor.start_waiting(benutzer.id, remember=merken)
    response.set_cookie(
        WARTET_COOKIE,
        token,
        max_age=get_settings().zwei_faktor_minuten * 60,
        httponly=True,
        samesite="strict",
        secure=_secure(request),
        path=cookie_pfad(),
    )


def halbe_beenden(db: Session, request: Request) -> None:
    """Die halbe Sitzung dieses Browsers wegwerfen, wenn ein Passkey sie abloest (dort entsteht eine neue, volle)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return
    zeile = db.execute(
        select(Sitzung).where(Sitzung.token_hash == _hash(token), Sitzung.bestaetigt.is_(False))
    ).scalar_one_or_none()
    if zeile is not None:
        db.delete(zeile)
        db.commit()
