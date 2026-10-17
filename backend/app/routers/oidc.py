"""Anmelden ueber OpenID Connect, das eigene Konto verknuepfen, die Anbieter verwalten, der authentik-Knopf.

Der Ablauf selbst steht im gemeinsamen Modul ``app.vendor.nexoidc``, hier
nur, was nexmail dazugibt: Sitzung, zweiter Faktor, Bremse, Passwort, Betreiber und die Antworten. Pfade:

| Methode | Pfad | Wer |
|---|---|---|
| GET | ``/api/oidc/providers`` | alle: Kurzname und Name der aktiven Anbieter (Anmelde- und Einladungsseite) |
| GET, POST | ``/api/oidc/admin/providers`` | Betreiber: die Liste, einen anlegen |
| PUT | ``/api/oidc/admin/providers/order`` | Betreiber: Reihenfolge |
| PUT, DELETE | ``/api/oidc/admin/providers/{id}`` | Betreiber: speichern, entfernen |
| GET | ``/api/oidc/admin/providers/{id}/impact?issuer=`` | Betreiber: Zahlen fuer die beiden Rueckfragen |
| GET, PUT | ``/api/oidc/admin/anmeldung`` | Betreiber: Karte 1, „Anmeldung mit Passwort" |
| GET | ``/api/oidc/{slug}/start[?invite=]`` | alle: zum Anbieter |
| GET | ``/api/oidc/{slug}/callback``, ``/api/oidc/callback`` | alle: zurueck vom Anbieter |
| GET | ``/api/oidc/{slug}/zurueck`` | alle: dasselbe fuer die Anbieter aus 0.21 (``redirect_path``) |
| GET | ``/api/oidc/me`` | angemeldet: die aktiven Anbieter mit ``linked`` |
| POST, DELETE | ``/api/oidc/{slug}/link`` | angemeldet: verknuepfen (mit Passwort), loesen |
| DELETE | ``/api/oidc/admin/accounts/{konto}/links/{anbieter}`` | Betreiber, mit eigenem Passwort |
| POST | ``/api/oidc/authentik/setup`` | Betreiber: der Knopf, immer 200 |
| GET, POST | ``/api/oidc/authentik/address`` | Betreiber: was die authentik-Karte zur Adresse zeigt; „Nur uebernehmen" |
| GET | ``/api/oidc/authentik/blueprint`` | Betreiber: ``nexmail-authentik.yaml`` |

⚠️ **Der Rueckweg ist eine Browser-Weiterleitung, keine API-Antwort.** Jeder Ausgang, auch jeder Fehler, endet auf
der eigenen Oberflaeche: ``/anmelden?error=<code>``, beim Verknuepfen ``/konto/sicherheit?error=<code>``.

⚠️ **Fehler der Anmeldung gehen als Kennung des Moduls hinaus** (``abgelehnt``), uebersetzt aus dessen Wortlauten
(``oidc.error.*``, ``oidc.formError.*``), nicht aus ``serverfehler``. ``test_oidc_app`` haelt fest, dass jede dieser
Kennungen dort steht.
"""

from __future__ import annotations

import html
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import einstellung_lesen, einstellung_schreiben
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..meldung import MeldungHttp
from ..models import Benutzer, OidcAnbieter, OidcVerknuepfung
from ..services import anmeldebremse
from ..services import benutzer as benutzerdienst
from ..services import sitzung as sitzungsdienst
from ..services.oidc_store import SqlStore
from ..vendor.nexoidc import (
    OidcError,
    ProviderInvalid,
    accounts,
    authentik,
    flow,
    providers,
)
from ..vendor.nexoidc.attempt import LINK
from ..vendor.nexoidc.attempt import read as anlauf_lesen
from ..vendor.nexoidc.config import current

router = APIRouter(tags=["oidc"])
logger = logging.getLogger("nexmail.oidc")

API = "/api"

#: Die Einstellung hinter „Anmeldung mit Passwort" (Karte 1). ``aus``: nur die Anbieter lassen herein, der Betreiber
#: kommt immer mit Passwort hinein. Wirkt nur, solange ein Anbieter an ist.
SCHLUESSEL_PASSWORT = "anmeldung_passwort"


def abgelehnt(status_code: int, code: str, **werte: Any) -> MeldungHttp:
    """Eine Ablehnung mit einer Kennung des Moduls (``nexoidc.errors``) oder seiner Rueckfragen."""
    return MeldungHttp(status_code, code, werte or None)


def _form_error(error: ProviderInvalid) -> MeldungHttp:
    return abgelehnt(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, field=error.field)


def basis(request: Request) -> str:
    """Die Adresse dieser Anfrage samt Vorbau (``NEXMAIL_URL_BASE``), so wie der Browser nexmail erreicht.

    ⚠️ ``request.base_url`` kennt den Vorbau nicht: ``BasisPfadMiddleware`` streift ihn vorher ab.
    """
    return str(request.base_url).rstrip("/") + get_settings().url_base


# -- Karte 1: Anmeldung mit Passwort ---------------------------------------------


def aktiver_anbieter(db: Session) -> bool:
    return any(entry.enabled for entry in SqlStore(db).list_providers())


def passwort_anmeldung_an(db: Session) -> bool:
    """Ob Konten ohne Betreiber-Haken sich mit Passwort anmelden duerfen. Ohne aktiven Anbieter immer: sonst kaeme
    niemand mehr herein."""
    return einstellung_lesen(db, SCHLUESSEL_PASSWORT) != "aus" or not aktiver_anbieter(db)


class AnmeldungIn(BaseModel):
    passwort: bool


@router.get(f"{API}/oidc/admin/anmeldung", summary="Card 1: whether people sign in with a password")
def anmeldung_lesen(_: Betreiber, db: DbSession) -> dict[str, Any]:
    return {"passwort": passwort_anmeldung_an(db), "anbieter_aktiv": aktiver_anbieter(db)}


@router.put(f"{API}/oidc/admin/anmeldung", summary="Card 1: switch password sign-in on or off")
def anmeldung_setzen(eingabe: AnmeldungIn, betreiber: Betreiber, db: DbSession) -> dict[str, Any]:
    if not eingabe.passwort and not aktiver_anbieter(db):
        raise MeldungHttp(status.HTTP_409_CONFLICT, "passwort_ohne_anbieter")
    einstellung_schreiben(db, SCHLUESSEL_PASSWORT, "an" if eingabe.passwort else "aus")
    logger.info("Password sign-in switched %s by=%s", "on" if eingabe.passwort else "off", betreiber.benutzername)
    return anmeldung_lesen(betreiber, db)


# -- Bremse, Sitzung, Antworten -----------------------------------------------------


def _sitzungskonto(request: Request, db: Session) -> Benutzer | None:
    """Das Konto einer bestaetigten Sitzung dieses Browsers, sonst None."""
    sitzung = sitzungsdienst.holen(db, request)
    return sitzung.benutzer if sitzung is not None and sitzung.bestaetigt else None


def _cookie(response: Response, cookie: flow.Cookie) -> None:
    if cookie.max_age == 0:
        response.delete_cookie(cookie.name, path=cookie.path, secure=cookie.secure, httponly=True, samesite="lax")
    else:
        response.set_cookie(
            cookie.name,
            cookie.value,
            max_age=cookie.max_age,
            path=cookie.path,
            httponly=cookie.http_only,
            samesite="lax",
            secure=cookie.secure,
        )


def _weiter(redirect: flow.Redirect) -> RedirectResponse:
    response = RedirectResponse(redirect.location, status_code=status.HTTP_303_SEE_OTHER)
    _cookie(response, redirect.cookie)
    return response


def _knoepfe(db: Session) -> list[dict[str, str]]:
    return providers.public_list(SqlStore(db))


# -- Oeffentlich: Anbieter, Start, Rueckkehr -------------------------------------------


@router.get(f"{API}/oidc/providers", summary="The active sign-in providers, for the sign-in and invitation pages")
def oeffentliche_anbieter(db: DbSession) -> list[dict[str, str]]:
    """Kurzname und Name der aktiven Eintraege, in der Reihenfolge der Liste. Nur, was ohnehin auf einem Knopf steht."""
    return _knoepfe(db)


@router.get(f"{API}/oidc/anmeldeseite", summary="What the sign-in page shows: the buttons and the password form")
def anmeldeseite(db: DbSession) -> dict[str, Any]:
    """Die Knoepfe und ob das Passwortformular dasteht (sonst nur klein „Als Betreiber mit Passwort anmelden")."""
    return {"providers": _knoepfe(db), "password": passwort_anmeldung_an(db)}


@router.get(f"{API}/oidc/{{slug}}/start", summary="Start a sign-in at an identity provider")
async def start(slug: str, request: Request, db: DbSession, invite: str | None = None) -> RedirectResponse:
    store = SqlStore(db)
    try:
        if anmeldebremse.oidc_wartet(request):
            raise OidcError("too_many_attempts", "sender is braked")
        redirect = await flow.begin(store, slug, request_base=basis(request), invite=invite)
    except OidcError as error:
        return _weiter(flow.refused(error, None))
    return _weiter(redirect)


def _durchreichen(request: Request) -> HTMLResponse:
    """Eine Seite, die dieselbe Rueckkehr noch einmal aufruft, diesmal von nexmails eigener Seite aus.

    ⚠️ **Das Sitzungs-Cookie steht auf ``SameSite=strict``** und faehrt bei der Weiterleitung vom Anbieter nicht mit
    (eine Navigation von fremder Seite). Beim Verknuepfen muss die Rueckkehr aber die Sitzung sehen. Ein
    zweiter Aufruf, den nexmails eigene Seite ausloest, ist eine Navigation derselben Seite: Dann faehrt es mit.
    Nichts ist bis hierher verbraucht (``state`` und Code gelten noch), und ohne Skript (``script-src 'self'``)."""
    ziel = html.escape(str(request.url.path) + ("?" + request.url.query if request.url.query else ""), quote=True)
    ziel = html.escape(get_settings().url_base, quote=True) + ziel
    seite = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<meta http-equiv=\"refresh\" content=\"0;url={ziel}\"><title>nexmail</title></head>"
        f"<body><a href=\"{ziel}\">nexmail</a></body></html>"
    )
    return HTMLResponse(seite, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


class EinladungIn(BaseModel):
    schluessel: str = Field(min_length=1, max_length=200)


@router.post(f"{API}/oidc/{{slug}}/einladung", summary="Take an invitation to a provider (the key in the body)")
async def einladung_starten(slug: str, eingabe: EinladungIn, request: Request, db: DbSession) -> JSONResponse:
    """Derselbe Start wie ``GET …/start?invite=<schluessel>``, fuer die Einladungsseite.

    ⚠️ **POST, nicht GET mit dem Schluessel in der Adresse.** Eine Adresse landet im Protokoll des Servers und jedes
    Proxys davor; der Schluessel oeffnet ein Konto. Zurueck kommt nur, wohin der Browser jetzt soll, und das
    Anlauf-Cookie, in dem die Einladung signiert mitreist. Dieselbe Bremse wie beim Annehmen mit Kennwort.
    """
    wache = anmeldebremse.torwaechter(request, "einladung", eingabe.schluessel[:12])
    try:
        if anmeldebremse.oidc_wartet(request):
            raise OidcError("too_many_attempts", "sender is braked")
        redirect = await flow.begin(SqlStore(db), slug, request_base=basis(request), invite=eingabe.schluessel)
    except OidcError as error:
        if error.code == "invite_invalid":
            wache.fehlgeschlagen()
        redirect = flow.refused(error, None)
    else:
        wache.geschafft()
    antwort = JSONResponse({"ziel": redirect.location})
    _cookie(antwort, redirect.cookie)
    return antwort


async def _zurueck(slug: str, request: Request, db: Session) -> Response:
    cookie = request.cookies.get(current().cookie_name)
    gestartet = anlauf_lesen(cookie)
    if (
        gestartet is not None
        and gestartet.purpose == LINK
        and request.headers.get("sec-fetch-site", "").lower() == "cross-site"
        and _sitzungskonto(request, db) is None
    ):
        return _durchreichen(request)
    store = SqlStore(db)
    try:
        if anmeldebremse.oidc_wartet(request):
            raise OidcError("too_many_attempts", "sender is braked")
        arrival = await flow.finish(store, slug, cookie=cookie, params=dict(request.query_params))
        if arrival.started.purpose == LINK:
            konto = _sitzungskonto(request, db)
            accounts.link(store, arrival, store.konto_nummer(konto) if konto is not None else None)
            return _weiter(flow.arrived(arrival, flow.linked_page(slug)))
        angemeldet = accounts.sign_in(store, arrival)
    except OidcError as error:
        # ⚠️ Nur eine Rueckkehr mit gueltigem Anlauf-Cookie zaehlt fuer die Bremse. Sonst sperrte jeder mit
        # ``?error=``, einem erfundenen Kurznamen oder Muell alle anderen hinter demselben Proxy aus.
        if error.code not in ("oidc_state_mismatch", "too_many_attempts") and gestartet is not None:
            anmeldebremse.oidc_fehlschlag(request)
        return _weiter(flow.refused(error, cookie))
    person = store.konto(angemeldet.account_id)
    if person is None:
        return _weiter(flow.refused(OidcError("account_blocked", "the account is gone"), cookie))
    if angemeldet.second_factor_due:
        # Dieselbe Codeabfrage wie nach dem Passwort: eine halbe Sitzung, die nur den zweiten Schritt darf.
        antwort = _weiter(flow.arrived(arrival, f"{current().login_page}?schritt=code"))
        sitzungsdienst.anlegen(db, person, request, antwort, bestaetigt=False)
        return antwort
    antwort = _weiter(flow.arrived(arrival))
    sitzungsdienst.anlegen(db, person, request, antwort, bestaetigt=True)
    return antwort


@router.get(f"{API}/oidc/callback", summary="Return from the provider of the entry oidc")
async def zurueck_oidc(request: Request, db: DbSession) -> Response:
    return await _zurueck("oidc", request, db)


@router.get(f"{API}/oidc/{{slug}}/zurueck", summary="Return from a provider set up in nexmail 0.21")
async def zurueck_alt(slug: str, request: Request, db: DbSession) -> Response:
    """Die Adresse, die die Anbieter aus nexmail 0.21 kennen (``redirect_path`` ihres Eintrags)."""
    return await _zurueck(slug, request, db)


@router.get(f"{API}/oidc/{{slug}}/callback", summary="Return from the identity provider")
async def zurueck(slug: str, request: Request, db: DbSession) -> Response:
    return await _zurueck(slug, request, db)


# -- Mein Konto ----------------------------------------------------------------------


@router.get(f"{API}/oidc/me", summary="The active providers and whether this account is linked to each")
def meine(person: AngemeldeterBenutzer, db: DbSession) -> list[dict[str, Any]]:
    store = SqlStore(db)
    nummer = store.konto_nummer(person)
    verknuepft = {link.provider_id for link in store.links_of_account(nummer)}
    nur_ueber = set(accounts.signs_in_only_through(store, nummer))
    return [
        {
            "slug": entry.slug,
            "label": entry.label,
            "linked": entry.id in verknuepft,
            "only": entry.id in nur_ueber and len(nur_ueber) == 1,
        }
        for entry in store.list_providers()
        if entry.enabled
    ]


class PasswortIn(BaseModel):
    password: str = Field(default="", max_length=200)


def _passwort_pruefen(request: Request, person: Benutzer, passwort: str) -> None:
    """Das eigene Passwort noch einmal, mit derselben Bremse wie an der Anmeldung."""
    wache = anmeldebremse.torwaechter(request, "passwort-bestaetigen", person.benutzername)
    if not person.passwort_hash or not benutzerdienst.passwort_stimmt(person, passwort):
        wache.fehlgeschlagen()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kennwort_falsch")
    wache.geschafft()


@router.post(f"{API}/oidc/{{slug}}/link", summary="Start linking this account; the password confirms it")
async def verknuepfen(
    slug: str, eingabe: PasswortIn, request: Request, person: AngemeldeterBenutzer, db: DbSession
) -> JSONResponse:
    """Antwortet mit der Adresse, zu der es geht, und setzt dabei das Anlauf-Cookie.

    Ein POST mit Sitzung und Passwort, kein Link: So stoesst keine fremde Seite eine Verknuepfung an.
    """
    if anmeldebremse.oidc_wartet(request):
        raise abgelehnt(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts")
    _passwort_pruefen(request, person, eingabe.password)
    store = SqlStore(db)
    nummer = store.konto_nummer(person)
    db.commit()
    try:
        redirect = await flow.begin(store, slug, request_base=basis(request), link_account_id=nummer)
    except OidcError as error:
        raise abgelehnt(status.HTTP_409_CONFLICT, error.code) from error
    antwort = JSONResponse({"url": redirect.location})
    _cookie(antwort, redirect.cookie)
    return antwort


@router.delete(
    f"{API}/oidc/{{slug}}/link", status_code=status.HTTP_204_NO_CONTENT, summary="Undo the link to a provider"
)
def loesen(slug: str, person: AngemeldeterBenutzer, db: DbSession) -> None:
    store = SqlStore(db)
    entry = store.provider_by_slug(slug)
    if entry is None:
        raise abgelehnt(status.HTTP_404_NOT_FOUND, "oidc_not_configured")
    try:
        accounts.unlink(store, store.konto_nummer(person), entry.id)
    except OidcError as error:
        raise abgelehnt(status.HTTP_409_CONFLICT, error.code) from error


@router.delete(
    f"{API}/oidc/admin/accounts/{{account_id}}/links/{{provider_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an account's link, with the operator's own password",
)
def betreiber_loest(
    account_id: int, provider_id: int, eingabe: PasswortIn, request: Request, betreiber: Betreiber, db: DbSession
) -> None:
    _passwort_pruefen(request, betreiber, eingabe.password)
    store = SqlStore(db)
    konto = store.konto(account_id)
    try:
        accounts.unlink(store, account_id, provider_id)
    except OidcError as error:
        raise abgelehnt(status.HTTP_409_CONFLICT, error.code) from error
    logger.info(
        "OIDC link to provider %s removed name=%s by=%s",
        provider_id,
        konto.benutzername if konto is not None else account_id,
        betreiber.benutzername,
    )


# -- Anbieterliste ---------------------------------------------------------------------


class ProviderIn(BaseModel):
    label: str = Field(max_length=200)
    slug: str = Field(default="", max_length=100)
    issuer: str = Field(max_length=600)
    client_id: str = Field(max_length=300)
    client_secret: str = Field(default="", max_length=2000)
    scopes: str = Field(default="openid profile email", max_length=500)
    enabled: bool = True
    auto_create: bool = False
    trusts_second_factor: bool = True


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=200)


def _admin_view(store: SqlStore, entry: Any, request: Request) -> dict[str, Any]:
    return providers.admin_view(entry, basis(request), len(store.links_of_provider(entry.id)))


@router.get(f"{API}/oidc/admin/providers", summary="The sign-in providers, never a secret")
def liste(request: Request, _: Betreiber, db: DbSession) -> list[dict[str, Any]]:
    store = SqlStore(db)
    return [_admin_view(store, entry, request) for entry in store.list_providers()]


@router.post(
    f"{API}/oidc/admin/providers", status_code=status.HTTP_201_CREATED, summary="Add a sign-in provider"
)
async def anlegen(eingabe: ProviderIn, request: Request, _: Betreiber, db: DbSession) -> dict[str, Any]:
    store = SqlStore(db)
    try:
        neu = await providers.create(store, providers.Form(**eingabe.model_dump()))
    except ProviderInvalid as error:
        raise _form_error(error) from error
    return providers.admin_view(neu, basis(request), 0)


@router.put(f"{API}/oidc/admin/providers/order", summary="Put the sign-in buttons in order")
def ordnen(eingabe: OrderIn, _: Betreiber, db: DbSession) -> list[dict[str, str]]:
    store = SqlStore(db)
    providers.reorder(store, eingabe.ids)
    return providers.public_list(store)


@router.put(f"{API}/oidc/admin/providers/{{provider_id}}", summary="Save a sign-in provider")
async def speichern(
    provider_id: int, eingabe: ProviderIn, request: Request, _: Betreiber, db: DbSession
) -> dict[str, Any]:
    store = SqlStore(db)
    try:
        gespeichert, verworfen = await providers.update(store, provider_id, providers.Form(**eingabe.model_dump()))
    except ProviderInvalid as error:
        raise _form_error(error) from error
    return {**_admin_view(store, gespeichert, request), "dropped": verworfen}


@router.get(f"{API}/oidc/admin/providers/{{provider_id}}/impact", summary="Numbers for the two confirmations")
def folgen(provider_id: int, _: Betreiber, db: DbSession, issuer: str = "") -> dict[str, Any]:
    store = SqlStore(db)
    if store.get_provider(provider_id) is None:
        raise abgelehnt(status.HTTP_404_NOT_FOUND, "provider_unknown")
    entfernen = providers.removal_impact(store, provider_id)
    wechsel = providers.issuer_change_impact(store, provider_id, issuer) if issuer else 0
    return {"issuer_change": wechsel, **asdict(entfernen)}


@router.delete(f"{API}/oidc/admin/providers/{{provider_id}}", summary="Remove a sign-in provider and its links")
def entfernen(provider_id: int, _: Betreiber, db: DbSession) -> dict[str, Any]:
    try:
        return asdict(providers.remove(SqlStore(db), provider_id))
    except ProviderInvalid as error:
        raise _form_error(error) from error


# -- authentik -------------------------------------------------------------------------


class SetupIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=2000)
    confirm_issuer_change: bool = False
    #: Die Adresse, die der Betreiber in der Karte bestaetigt hat (die des Browsers), solange nexmail keine hat.
    public_url: str = Field(default="", max_length=600)


class AddressIn(BaseModel):
    public_url: str = Field(max_length=600)
    confirm: bool = False


@router.post(f"{API}/oidc/authentik/setup", summary="Set up provider and application in authentik with a token")
async def authentik_einrichten(
    eingabe: SetupIn, request: Request, betreiber: Betreiber, db: DbSession
) -> dict[str, Any]:
    """⚠️ Das Token gilt nur fuer diesen Lauf: nicht gespeichert, nicht protokolliert, nicht zurueckgegeben."""
    logger.info("authentik setup started by=%s", betreiber.benutzername)
    ergebnis = await authentik.setup(
        SqlStore(db),
        eingabe.url,
        eingabe.token,
        basis(request),
        confirm_issuer_change=eingabe.confirm_issuer_change,
        public_url=eingabe.public_url,
        headers=request.headers,
    )
    return ergebnis.as_dict()


@router.get(f"{API}/oidc/authentik/address", summary="What the authentik card shows about the public address")
def authentik_adresse(request: Request, _: Betreiber, db: DbSession) -> dict[str, Any]:
    return authentik.address_view(SqlStore(db), basis(request), request.headers)


@router.post(f"{API}/oidc/authentik/address", summary="Save the public address the authentik card suggests")
def authentik_adresse_speichern(
    eingabe: AddressIn, request: Request, _: Betreiber, db: DbSession
) -> dict[str, Any]:
    try:
        return authentik.save_public_url(SqlStore(db), eingabe.public_url, basis(request), confirm=eingabe.confirm)
    except ValueError as error:
        raise abgelehnt(status.HTTP_422_UNPROCESSABLE_CONTENT, "public_url_invalid") from error
    except authentik.PublicUrlChange as frage:
        raise abgelehnt(status.HTTP_409_CONFLICT, "public_url_change", **frage.question) from frage
    except authentik.PublicUrlNotKept as error:
        raise abgelehnt(status.HTTP_409_CONFLICT, "public_url_needed") from error


@router.get(f"{API}/oidc/authentik/blueprint", summary="A blueprint that creates the same objects in authentik")
def authentik_blueprint(request: Request, _: Betreiber, db: DbSession) -> Response:
    try:
        ruecksprung = authentik.blueprint_redirect(SqlStore(db), basis(request))
    except authentik.PublicUrlNeeded as error:
        raise abgelehnt(status.HTTP_409_CONFLICT, "public_url_needed") from error
    name = authentik.blueprint_filename()
    return Response(
        authentik.blueprint(ruecksprung),
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# -- Fuer andere Router ------------------------------------------------------------------


def verknuepfungen_je_konto(db: Session) -> dict[str, list[dict[str, Any]]]:
    """Je Konto (Kennung) die Anbieter, mit denen es verknuepft ist: Marken in der Kontenliste."""
    eintraege = {row.id: row for row in db.scalars(select(OidcAnbieter))}
    ergebnis: dict[str, list[dict[str, Any]]] = {}
    for link in db.scalars(
        select(OidcVerknuepfung).where(OidcVerknuepfung.anbieter_id.is_not(None)).order_by(OidcVerknuepfung.id)
    ):
        eintrag = eintraege.get(link.anbieter_id or "")
        if eintrag is None or eintrag.nummer is None:
            continue
        ergebnis.setdefault(link.benutzer_id, []).append(
            {"id": eintrag.nummer, "slug": eintrag.kuerzel, "label": eintrag.anzeigename}
        )
    return ergebnis
