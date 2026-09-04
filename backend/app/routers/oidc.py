"""Anmelden über einen fremden Anbieter — und die Verwaltung dazu.

Zwei Wege, ein Ablauf:

* **Anmelden** (ohne Sitzung) — endet in einer gewöhnlichen nexmail-Sitzung.
* **Verknüpfen** (mit Sitzung) — hängt die Identität an das eigene Konto.

⚠️ **Der Rückweg ist eine Browser-Weiterleitung, keine API-Antwort.** Der
Anbieter schickt den Browser per GET zurück; was hier herauskommt, sieht ein
Mensch. Deshalb endet **jeder** Ausgang — auch jeder Fehler — in einer
Weiterleitung auf die eigene Oberfläche mit einer Kennung in der Adresse, nie
in nacktem JSON.

⚠️ **Deaktivierte oder unbekannte Anbieter: 404 auf beiden Adressen.**
Abschalten blendet nicht nur den Knopf aus — der Weg selbst ist zu.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import crypto
from ..config import get_settings
from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..models import Benutzer, OidcAnbieter, OidcVerknuepfung
from ..routers.einstellungen import SCHLUESSEL_OEFFENTLICHE_ADRESSE
from ..services import anmeldebremse, oidc
from ..services import oidc_konten as kontendienst
from ..services import sitzung as sitzungsdienst

logger = logging.getLogger("nexmail.oidc")

router = APIRouter(prefix="/api/oidc", tags=["oidc"])


def _kontext(anbieter_id: str) -> str:
    return f"oidc:{anbieter_id}:geheimnis"


def _anbieter(db, kuerzel: str) -> OidcAnbieter:
    zeile = db.execute(
        select(OidcAnbieter).where(OidcAnbieter.kuerzel == kuerzel)
    ).scalar_one_or_none()
    # ⚠️ 404 auch bei abgeschaltet: Der Weg ist zu, nicht nur der Knopf weg.
    if zeile is None or not zeile.aktiv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return zeile


def _rueckkehr(db, kuerzel: str) -> str:
    """Die Adresse, die beim Anbieter hinterlegt sein muss.

    ⚠️ **Ohne öffentliche Adresse geht es nicht los.** Aus ihr entsteht die
    Rückkehr-Adresse; ohne sie schickt der Anbieter den Browser ins Leere und
    meldet nur ein nichtssagendes ``invalid_grant``.
    """
    basis = einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE).rstrip("/")
    if not basis:
        raise oidc.OidcFehler(
            "oidc_keine_adresse",
            "Without a public address there is no redirect URI. It lives in the "
            "administration under 'Server'.",
        )
    return f"{basis}{get_settings().url_base}/api/oidc/{kuerzel}/zurueck"


def _oberflaeche(pfad: str = "/") -> str:
    return f"{get_settings().url_base}{pfad}"


# --- Der Hinweg ----------------------------------------------------------- #


@router.get("/{kuerzel}/start")
async def starten(kuerzel: str, request: Request, db: DbSession) -> Response:
    """Zum Anbieter weiterleiten und den Anlauf im Cookie merken."""
    anbieter = _anbieter(db, kuerzel)
    # Mit Sitzung heißt: verknüpfen. Ohne: anmelden.
    sitzung = sitzungsdienst.holen(db, request)
    absicht = "verknuepfen" if sitzung else "anmelden"

    try:
        rueckkehr = _rueckkehr(db, kuerzel)
        beschreibung = await oidc.beschreibung_holen(anbieter.issuer)
        anlauf = oidc.anlauf_erzeugen(kuerzel, absicht, sitzung.benutzer_id if sitzung else "")
        ziel = oidc.weiterleitung_bauen(
            beschreibung,
            client_id=anbieter.client_id,
            scopes=anbieter.scopes,
            rueckkehr=rueckkehr,
            anlauf=anlauf,
        )
    except oidc.OidcFehler as fehler:
        logger.warning("OIDC: start via %r failed: %s", kuerzel, fehler.text)
        return RedirectResponse(
            _oberflaeche(f"/?{urlencode({'oidc_fehler': fehler.code})}"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    antwort = RedirectResponse(ziel, status_code=status.HTTP_303_SEE_OTHER)
    antwort.set_cookie(
        oidc.COOKIE_NAME,
        oidc.zustand_schreiben(anlauf),
        max_age=oidc.ANLAUF_MINUTEN * 60,
        path=oidc.cookie_pfad(),
        httponly=True,
        # ``lax`` lässt das Cookie bei der Rückkehr mitfahren — das ist eine
        # Navigation von oberster Ebene. ``strict`` sähe sicherer aus und
        # bräche genau diesen Schritt.
        samesite="lax",
        # ⚠️ **Dasselbe ``secure`` wie beim Sitzungs-Cookie.** In nexview fehlte
        # es: Auf einer HTTPS-Installation durfte ein Angreifer im Netz über
        # eine Klartext-Anfrage ein eigenes, gültig signiertes Anlauf-Cookie
        # setzen — und wer dem Browser eines anderen seinen Lauf unterschiebt,
        # meldet ihn in **seinem** Konto an.
        secure=sitzungsdienst._secure(request),
    )
    return antwort


# --- Der Rückweg ---------------------------------------------------------- #


@router.get("/{kuerzel}/zurueck")
async def zurueck(
    kuerzel: str,
    request: Request,
    db: DbSession,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> Response:
    """Der Anbieter schickt den Browser zurück.

    ⚠️ **Jeder Ausgang ist eine Weiterleitung.** Auch jeder Fehler.
    """
    anbieter = _anbieter(db, kuerzel)
    zustand = oidc.zustand_lesen(request.cookies.get(oidc.COOKIE_NAME))

    def scheitern(kennung: str, grund: str) -> Response:
        logger.warning("OIDC: callback for %r failed (%s): %s", kuerzel, kennung, grund)
        antwort = RedirectResponse(
            _oberflaeche(f"/?{urlencode({'oidc_fehler': kennung})}"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
        antwort.delete_cookie(oidc.COOKIE_NAME, path=oidc.cookie_pfad(), httponly=True)
        return antwort

    # ⚠️ **Diese Prüfung steht VOR der des ``state``.** Ein Rückweg mit
    # ``error`` trägt keinen ``code`` und nicht zwingend einen brauchbaren
    # ``state``. Weiter unten würde daraus „state passt nicht" — ein Nebenbefund,
    # der den Anmeldenden zum vergeblichen Wiederholen schickt, statt ihm zu
    # sagen, dass der Anbieter abgelehnt hat.
    if error:
        return scheitern("oidc_abgelehnt", f"provider returned error={error[:200]!r} {error_description[:200]!r}")

    if zustand is None:
        return scheitern(
            "oidc_anlauf_fehlt",
            f"callback cookie missing or expired (other browser, cookie blocked, "
            f"or more than {oidc.ANLAUF_MINUTEN} minutes at the provider)",
        )
    if not code or not state:
        return scheitern("oidc_anlauf_fehlt", "callback without code or state")
    if zustand.get("kuerzel") != kuerzel or zustand.get("state") != state:
        return scheitern("oidc_anlauf_fehlt", "the running attempt belongs to something else")

    # ⚠️ **Die Bremse zählt erst NACH der state-Prüfung** — was daran schon
    # scheitert, hat den Anbieter nie gesehen und ist beliebig billig zu
    # erzeugen.
    #
    # ⚠️ **Und sie zählt NIE am Anbieter-Kürzel.** In nexview stand dort das
    # Kürzel, und das machte aus der Bremse eine Waffe: Ein Fremder holte sich
    # ein eigenes Anlauf-Cookie, kehrte zehnmal mit erfundenem Code zurück —
    # und danach kam **niemand** mehr über diesen Anbieter herein. Dasselbe
    # passierte ohne Angreifer nach einem falsch abgetippten Geheimnis.
    wache = anmeldebremse.torwaechter(request, "oidc", zustand.get("state", "")[:16])

    try:
        beschreibung = await oidc.beschreibung_holen(anbieter.issuer)
        geheimnis = (
            crypto.entschluesseln(anbieter.client_secret, _kontext(anbieter.id))
            if anbieter.client_secret
            else ""
        )
        id_token, zugang = await oidc.code_tauschen(
            beschreibung,
            client_id=anbieter.client_id,
            client_secret=geheimnis,
            code=code,
            verifier=zustand["verifier"],
            rueckkehr=_rueckkehr(db, kuerzel),
        )
        ausweis = await oidc.ausweis_pruefen(
            beschreibung, id_token, client_id=anbieter.client_id, nonce=zustand["nonce"]
        )
        auskunft = await oidc.nachfragen(beschreibung, zugang, str(ausweis.get("sub"))) if zugang else {}
        ident = oidc.identitaet_bauen(ausweis, auskunft, str(beschreibung.get("issuer") or anbieter.issuer))
    except oidc.OidcFehler as fehler:
        wache.fehlgeschlagen()
        return scheitern(fehler.code, fehler.text)

    wache.geschafft()

    if zustand.get("absicht") == "verknuepfen":
        # ⚠️ **Aus dem signierten Anlauf, nicht aus der Sitzung.** Das
        # Sitzungs-Cookie ist ``SameSite=strict`` und faehrt beim Rueckweg
        # vom Anbieter nicht mit — er ist eine Navigation von fremder
        # Seite. Wer es hier liest, bekommt **immer** ``None``.
        #
        # Bis zum 01.09.2026 stand genau das hier: Der Verknuepfen-Knopf im
        # Profil sah aus, als taete er etwas, und tat nie etwas. Aufgefallen
        # erst, als der Pruefstand ihn zum ersten Mal an einem echten
        # Keycloak durchspielte. Siehe ``oidc.anlauf_erzeugen``.
        person = db.get(Benutzer, zustand.get("benutzer_id") or "")
        if person is None:
            return scheitern("oidc_abgemeldet", "the session is gone; nothing was linked")
        try:
            kontendienst.verknuepfen(db, person, ident)
        except oidc.OidcFehler as fehler:
            return scheitern(fehler.code, fehler.text)
        antwort = RedirectResponse(
            _oberflaeche("/?oidc=verknuepft"), status_code=status.HTTP_303_SEE_OTHER
        )
        antwort.delete_cookie(oidc.COOKIE_NAME, path=oidc.cookie_pfad(), httponly=True)
        return antwort

    try:
        person = kontendienst.aufloesen(db, ident)
    except oidc.OidcFehler as fehler:
        return scheitern(fehler.code, fehler.text)

    antwort = RedirectResponse(_oberflaeche("/"), status_code=status.HTTP_303_SEE_OTHER)
    # ⚠️ **Ohne zweiten Faktor.** Wer sich über einen fremden Anbieter anmeldet,
    # hat dort schon bewiesen, wer er ist — und dessen zweiter Faktor gilt.
    # nexmail nochmals nachzufragen wäre Doppelarbeit ohne Gewinn.
    sitzungsdienst.anlegen(db, person, request, antwort, bestaetigt=True)
    antwort.delete_cookie(oidc.COOKIE_NAME, path=oidc.cookie_pfad(), httponly=True)
    logger.info("A user signed in through an OIDC provider.")
    return antwort


# --- Was die Anmeldeseite braucht ----------------------------------------- #


class KnopfZeile(BaseModel):
    kuerzel: str
    anzeigename: str


@router.get("/knoepfe", response_model=list[KnopfZeile])
def knoepfe(db: DbSession) -> list[KnopfZeile]:
    """Die Anbieter für die Anmeldeseite.

    ⚠️ **Ohne Anmeldung erreichbar** — die Anmeldeseite sieht ja noch niemand.
    Herausgegeben wird nur, was ohnehin auf einem Knopf steht.
    """
    zeilen = db.execute(
        select(OidcAnbieter).where(OidcAnbieter.aktiv.is_(True)).order_by(OidcAnbieter.anzeigename)
    ).scalars().all()
    return [KnopfZeile(kuerzel=a.kuerzel, anzeigename=a.anzeigename) for a in zeilen]


# --- Verwaltung ----------------------------------------------------------- #


class AnbieterZeile(BaseModel):
    id: str
    kuerzel: str
    anzeigename: str
    issuer: str
    client_id: str
    scopes: str
    aktiv: bool
    geheimnis_liegt_vor: bool
    #: Was beim Anbieter hinterlegt werden muss.
    rueckkehr_adresse: str


class AnbieterEingabe(BaseModel):
    kuerzel: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    anzeigename: str = Field(min_length=1, max_length=120)
    issuer: str = Field(min_length=8, max_length=300)
    client_id: str = Field(min_length=1, max_length=300)
    #: ⚠️ ``None`` heißt **unverändert** — dieselbe Regel wie beim Postfach.
    client_secret: str | None = Field(default=None, max_length=500)
    scopes: str = Field(default="openid email profile", max_length=300)
    aktiv: bool = True


def _zeile(db, a: OidcAnbieter) -> AnbieterZeile:
    basis = einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE).rstrip("/")
    return AnbieterZeile(
        id=a.id,
        kuerzel=a.kuerzel,
        anzeigename=a.anzeigename,
        issuer=a.issuer,
        client_id=a.client_id,
        scopes=a.scopes,
        aktiv=a.aktiv,
        geheimnis_liegt_vor=bool(a.client_secret),
        rueckkehr_adresse=(
            f"{basis}{get_settings().url_base}/api/oidc/{a.kuerzel}/zurueck" if basis else ""
        ),
    )


@router.get("/anbieter", response_model=list[AnbieterZeile])
def anbieter_liste(_: Betreiber, db: DbSession) -> list[AnbieterZeile]:
    zeilen = db.execute(select(OidcAnbieter).order_by(OidcAnbieter.angelegt)).scalars().all()
    return [_zeile(db, a) for a in zeilen]


@router.post("/anbieter", response_model=AnbieterZeile, status_code=status.HTTP_201_CREATED)
def anbieter_anlegen(eingabe: AnbieterEingabe, betreiber: Betreiber, db: DbSession) -> AnbieterZeile:
    if not eingabe.issuer.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="anbieter_adresse_ohne_schema",
        )
    if db.execute(
        select(OidcAnbieter).where(OidcAnbieter.kuerzel == eingabe.kuerzel)
    ).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kuerzel_vergeben")

    from ..models import neue_id

    anbieter = OidcAnbieter(
        id=neue_id(),
        kuerzel=eingabe.kuerzel,
        anzeigename=eingabe.anzeigename,
        issuer=eingabe.issuer.rstrip("/"),
        client_id=eingabe.client_id,
        scopes=eingabe.scopes,
        aktiv=eingabe.aktiv,
    )
    # ⚠️ Erst die Kennung, dann verschlüsseln — sie fährt als Zusatzdaten mit.
    anbieter.client_secret = (
        crypto.verschluesseln(eingabe.client_secret, _kontext(anbieter.id))
        if eingabe.client_secret
        else ""
    )
    db.add(anbieter)
    db.commit()
    logger.info("An OIDC provider was added.")
    return _zeile(db, anbieter)


@router.put("/anbieter/{anbieter_id}", response_model=AnbieterZeile)
def anbieter_aendern(
    anbieter_id: str, eingabe: AnbieterEingabe, _: Betreiber, db: DbSession
) -> AnbieterZeile:
    anbieter = db.get(OidcAnbieter, anbieter_id)
    if anbieter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    anbieter.kuerzel = eingabe.kuerzel
    anbieter.anzeigename = eingabe.anzeigename
    anbieter.issuer = eingabe.issuer.rstrip("/")
    anbieter.client_id = eingabe.client_id
    anbieter.scopes = eingabe.scopes
    anbieter.aktiv = eingabe.aktiv
    # ⚠️ Leer heißt „unverändert", nicht „kein Geheimnis".
    if eingabe.client_secret:
        anbieter.client_secret = crypto.verschluesseln(eingabe.client_secret, _kontext(anbieter.id))
    db.commit()
    return _zeile(db, anbieter)


@router.delete("/anbieter/{anbieter_id}", status_code=status.HTTP_204_NO_CONTENT)
def anbieter_entfernen(anbieter_id: str, _: Betreiber, db: DbSession) -> None:
    anbieter = db.get(OidcAnbieter, anbieter_id)
    if anbieter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    db.delete(anbieter)
    db.commit()
    logger.warning("An OIDC provider was removed.")


# --- Die eigenen Verknüpfungen -------------------------------------------- #


class VerknuepfungZeile(BaseModel):
    id: int
    issuer: str
    anzeigename: str
    #: Das Kuerzel des Anbieters, zu dem die Verknuepfung gehoert — leer, wenn
    #: es ihn nicht mehr gibt.
    #:
    #: ⚠️ **Die Oberflaeche ordnet danach zu, nicht ueber den Anzeigenamen.**
    #: Der ist frei waehlbar und kann zweimal vorkommen; das Kuerzel nicht.
    kuerzel: str = ""


@router.get("/meine", response_model=list[VerknuepfungZeile])
def meine(person: AngemeldeterBenutzer, db: DbSession) -> list[VerknuepfungZeile]:
    zeilen = db.execute(
        select(OidcVerknuepfung).where(OidcVerknuepfung.benutzer_id == person.id)
    ).scalars().all()
    # ⚠️ **Ohne abschliessenden Schraegstrich vergleichen.** Der Anbieter
    # steht so in der Datenbank, wie der Betreiber ihn eingetippt hat; die
    # Verknuepfung traegt den Aussteller so, wie der Anbieter sich selbst
    # nennt. authentik haengt dort ein ``/`` an, der Betreiber meist nicht.
    #
    # Am 01.09.2026 genau daran haengengeblieben: Das Verknuepfen hatte
    # funktioniert („An OIDC identity was linked to an account"), aber im
    # Profil stand weiter „Verknuepfen" — die Zuordnung fand ihren Anbieter
    # nicht und fiel auf die rohe Adresse zurueck. Der Fehler sah damit aus
    # wie ein misslungenes Verknuepfen, obwohl nur die Anzeige irrte.
    def gleich(adresse: str) -> str:
        return adresse.rstrip("/")

    anbieter = {
        gleich(a.issuer): a for a in db.execute(select(OidcAnbieter)).scalars().all()
    }
    return [
        VerknuepfungZeile(
            id=v.id,
            issuer=v.issuer,
            anzeigename=(
                anbieter[gleich(v.issuer)].anzeigename
                if gleich(v.issuer) in anbieter
                else v.issuer
            ),
            kuerzel=(
                anbieter[gleich(v.issuer)].kuerzel if gleich(v.issuer) in anbieter else ""
            ),
        )
        for v in zeilen
    ]


@router.delete("/meine/{verknuepfung_id}", status_code=status.HTTP_204_NO_CONTENT)
def loesen(verknuepfung_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    """Eine Verknüpfung lösen.

    ⚠️ **Nicht, wenn danach kein Weg mehr hineinführt.** Wer kein Kennwort hat
    und seine letzte Verknüpfung löst, sperrt sich selbst aus — und aus der
    Anwendung heraus führt kein Weg zurück.
    """
    verknuepfung = db.get(OidcVerknuepfung, verknuepfung_id)
    if verknuepfung is None or verknuepfung.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    uebrig = db.execute(
        select(OidcVerknuepfung).where(
            OidcVerknuepfung.benutzer_id == person.id, OidcVerknuepfung.id != verknuepfung_id
        )
    ).scalars().all()
    if not uebrig and not person.passwort_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "letzter_anmeldeweg"
            ),
        )

    db.delete(verknuepfung)
    db.commit()
