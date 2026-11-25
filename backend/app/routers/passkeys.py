"""Passkeys (Kontenmodul Teil 2): anmelden mit Fingerabdruck, Gesicht oder der PIN des Geraets, ohne Passwort.

Die Arbeit macht ``nexkonten.passkeys`` (WebAuthn, Challenge, Zaehler); hier stehen nur nexmails Wege dazu:

- Anmelden: ``POST /api/auth/passkey/start`` gibt die Optionen und legt den Anlauf in ein Cookie,
  ``POST /api/auth/passkey`` nimmt die Antwort des Browsers und meldet an. Ein Passkey ist beide Faktoren zugleich:
  Es folgt kein Code.
- Verwalten (Einstellungen → Sicherheit): Liste, hinzufuegen (mit dem Passwort, bei einem Konto ohne Passwort mit
  einer frischen Anmeldung), entfernen.

⚠️ **Nur mit der oeffentlichen Adresse auf https** (oder ``localhost``): Ein Passkey gehoert zu genau einem Host, und
ohne eingetragene Adresse wuesste nexmail nicht, zu welchem. Dann sagen die Wege ``passkeys_off``.

⚠️ **Der Betreiber kann Passkeys abschalten** (Verwaltung → Anmeldung, ab Werk an). Vorhandene bleiben gespeichert,
melden aber nicht mehr an.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from ..deps import AktiveSitzung, AngemeldeterBenutzer, DbSession
from ..services import anmeldebremse, kontenpost
from ..services import konten_store as kontenstore
from ..services import sitzung as sitzungsdienst
from ..vendor import nexkonten
from ..vendor.nexkonten import factor, passkeys

logger = logging.getLogger("nexmail.konten")

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Die Anlaeufe im Cookie: einer fuers Anmelden, einer fuers Hinzufuegen. Fuenf Minuten, wie die Challenge im Modul.
COOKIE_ANMELDEN = "nexmail_passkey"
COOKIE_NEU = "nexmail_passkey_neu"


def _ort(db, request: Request) -> passkeys.Party:
    """Der Host, zu dem ein Passkey gehoert: die oeffentliche Adresse. ⚠️ **Auf localhost die Seite selbst**
    (``Origin``, sonst die Adresse der Anfrage): Browser erlauben WebAuthn dort ohne https, und die Seite laeuft beim
    Ausprobieren oft unter einem anderen Port als die eingetragene Adresse. Ein Passkey fuer localhost taugt nirgends
    sonst, deshalb gibt es diesen Weg nur dort. Bei einem GET ohne ``Origin`` nimmt das Modul die Adresse der Anfrage
    (``request_url``, konten 0.3.3)."""
    return passkeys.party(
        kontenpost.oeffentliche_adresse(db), origin=request.headers.get("origin", ""), request_url=str(request.url)
    )


def _cookie(request: Request, response: Response, name: str, wert: str) -> None:
    response.set_cookie(
        name,
        wert,
        max_age=passkeys.CHALLENGE_SECONDS,
        httponly=True,
        samesite="strict",
        secure=sitzungsdienst._secure(request),
        path=sitzungsdienst.cookie_pfad(),
    )


def _weg(response: Response, name: str) -> None:
    response.delete_cookie(name, path=sitzungsdienst.cookie_pfad())


# --- Anmelden ------------------------------------------------------------------------------------------------------


class Stand(BaseModel):
    #: Ob die Anmeldeseite „Mit Passkey anmelden“ zeigt: erlaubt und mit einer Adresse, unter der es geht.
    an: bool


@router.get("/passkey", response_model=Stand)
def passkey_stand(request: Request, db: DbSession) -> Stand:
    store = kontenstore.store_fuer(db)
    try:
        _ort(db, request)
    except nexkonten.AccountError:
        return Stand(an=False)
    return Stand(an=store.passkeys_allowed())


@router.post("/passkey/start")
def passkey_anmelden_start(request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    store = kontenstore.store_fuer(db)
    try:
        token, optionen = passkeys.begin_sign_in(store, _ort(db, request), sender=anmeldebremse.adresse_von(request))
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    _cookie(request, response, COOKIE_ANMELDEN, token)
    return passkeys.options_json(optionen)


class PasskeyAntwort(BaseModel):
    #: Die Antwort des Browsers (``PublicKeyCredential`` als JSON).
    credential: dict[str, Any]
    #: „Angemeldet bleiben“ wie beim Passwort.
    angemeldet_bleiben: bool = True


@router.post("/passkey")
def passkey_anmelden(
    eingabe: PasskeyAntwort, request: Request, response: Response, db: DbSession
) -> dict[str, str]:
    store = kontenstore.store_fuer(db)
    token = request.cookies.get(COOKIE_ANMELDEN, "")
    _weg(response, COOKIE_ANMELDEN)
    try:
        konto = passkeys.finish_sign_in(store, token, eingabe.credential, _ort(db, request))
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    from ..models import Benutzer

    person = db.get(Benutzer, str(konto.id))
    # War der Passkey der zweite Schritt nach dem Passwort (``factor.finish_waiting_by_passkey``), weicht die halbe
    # Sitzung der neuen, vollen, mit „Angemeldet bleiben“ von dort.
    merken = eingabe.angemeldet_bleiben
    gewartet = factor.finish_waiting_by_passkey(request.cookies.get(sitzungsdienst.WARTET_COOKIE, ""), konto.id)
    if gewartet is not None:
        merken = gewartet.remember
    _weg(response, sitzungsdienst.WARTET_COOKIE)
    sitzungsdienst.halbe_beenden(db, request)
    sitzungsdienst.anlegen(db, person, request, response, bestaetigt=True, merken=merken)
    nexkonten.login.succeeded(store, person.id)
    sitzungsdienst.angemeldet(db, person, request, response)
    return {"schritt": "fertig"}


# --- Verwalten -----------------------------------------------------------------------------------------------------


class Liste(BaseModel):
    erlaubt: bool
    #: Leer, wenn es geht; sonst die Kennung, warum nicht (``passkeys_off``: keine https-Adresse).
    grund: str = ""
    passkeys: list[dict[str, Any]]


@router.get("/passkeys", response_model=Liste)
def passkeys_liste(person: AngemeldeterBenutzer, request: Request, db: DbSession) -> Liste:
    store = kontenstore.store_fuer(db)
    grund = ""
    try:
        _ort(db, request)
    except nexkonten.AccountError as fehler:
        grund = fehler.code
    return Liste(
        erlaubt=store.passkeys_allowed() and not grund,
        grund=grund,
        passkeys=[passkeys.view(p) for p in store.passkeys_of(person.id)],
    )


class MitPasswort(BaseModel):
    passwort: str = Field(default="", max_length=300)


def _bestaetigt(person, sitzung) -> bool:
    from .auth import _bestaetigt as bestaetigt

    return bestaetigt(person, sitzung)


@router.post("/passkeys/start")
def passkey_neu_start(
    eingabe: MitPasswort,
    person: AngemeldeterBenutzer,
    sitzung: AktiveSitzung,
    request: Request,
    response: Response,
    db: DbSession,
) -> dict[str, Any]:
    """Mit dem Passwort (ein Konto ohne Passwort: frische Anmeldung beim Anbieter), konten 0.3.1."""
    store = kontenstore.store_fuer(db)
    try:
        token, optionen = passkeys.begin_register(
            store,
            person.id,
            _ort(db, request),
            app_name="nexmail",
            password=eingabe.passwort,
            actor_confirmed=_bestaetigt(person, sitzung),
        )
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    _cookie(request, response, COOKIE_NEU, token)
    return passkeys.options_json(optionen)


class NeuerPasskey(BaseModel):
    credential: dict[str, Any]
    name: str = Field(default="", max_length=200)


@router.post("/passkeys", status_code=status.HTTP_201_CREATED)
def passkey_neu(
    eingabe: NeuerPasskey, person: AngemeldeterBenutzer, request: Request, response: Response, db: DbSession
) -> dict[str, Any]:
    store = kontenstore.store_fuer(db)
    token = request.cookies.get(COOKIE_NEU, "")
    _weg(response, COOKIE_NEU)
    try:
        neu = passkeys.finish_register(store, person.id, token, eingabe.credential, _ort(db, request), name=eingabe.name)
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    return passkeys.view(neu)


@router.post("/passkeys/{uid}/entfernen", status_code=status.HTTP_204_NO_CONTENT)
def passkey_entfernen(
    uid: str, eingabe: MitPasswort, person: AngemeldeterBenutzer, sitzung: AktiveSitzung, db: DbSession
) -> Response:
    store = kontenstore.store_fuer(db)
    try:
        weg = passkeys.remove(
            store, person.id, uid, password=eingabe.passwort, actor_confirmed=_bestaetigt(person, sitzung)
        )
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    if not weg:
        raise kontenstore.http(nexkonten.AccountError("not_found", "No such passkey.", 404))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
