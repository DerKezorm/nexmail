"""Die iPhone-App koppeln: im Browser der Code, in der App das Abholen.

Zwei Seiten:

* ``router`` gehört zur Oberfläche und steht unter keiner Zusage.
* ``public_router`` liegt unter ``/api/app/1`` und ist dort der einzige Teil ohne
  Schlüssel: Wer noch keinen hat, holt ihn hier. Er steht unter der Zusage
  (``app1.ZUGESAGT``).

Die Regeln stehen in ``services/app_kopplung.py``.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Annotated
from urllib.parse import quote, urlsplit

import segno
from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..meldung import MeldungHttp
from ..services import adresse as adressdienst
from ..services import anmeldebremse, app_kopplung
from ..services.app_kopplung import KopplungFehler

#: Das Schema, auf das die App hört. Die Kamera des iPhones öffnet den Link
#: aus dem QR-Code direkt in nexmail.
APP_LINK = "nexmail://connect"

router = APIRouter(prefix="/api/app-kopplung", tags=["app"])
public_router = APIRouter(prefix="/api/app/1", tags=["app"])


def _status(fehler: KopplungFehler) -> int:
    return {
        "app_kopplung_unbekannt": status.HTTP_404_NOT_FOUND,
        "app_abgeschaltet": status.HTTP_403_FORBIDDEN,
        "app_zu_viele_kopplungen": status.HTTP_409_CONFLICT,
    }[fehler.kennung]


# --- Oberfläche ------------------------------------------------------------ #


class KopplungAnlegen(BaseModel):
    #: Die Adresse, unter der der Browser nexmail gerade sieht. Gilt nur, wenn
    #: unter Verwaltung keine öffentliche Adresse steht; die geht vor.
    adresse: str = Field(default="", max_length=300)


class KopplungNeu(BaseModel):
    kennung: str
    #: ⚠️ Nur in dieser Antwort im Klartext. Die Seite zeigt den Code und
    #: vergisst ihn wieder.
    code: str
    gilt_bis: datetime
    #: Die Adresse, die die App sich merkt. Beim kurzen Code tippt man sie ein.
    adresse: str
    link: str
    qr_svg: str


class KopplungStand(BaseModel):
    #: ``wartet``, ``verbunden`` oder ``abgelaufen``.
    stand: str
    geraet: str = ""


class Riegel(BaseModel):
    erlaubt: bool


def _qr_svg(link: str) -> str:
    """Dunkel auf Weiß mit Ruhezone: Ein Telefon liest ihn auch auf dunkler Seite.

    ⚠️ ``omitsize``: Mit festen Maßen gibt segno keine ``viewBox`` aus, und ein
    auf 200 px gesetztes Bild schneidet dann rechts und unten ab, statt zu
    skalieren. Der Code sieht fast richtig aus und lässt sich nicht lesen.
    """
    aus = io.BytesIO()
    segno.make(link, error="m").save(
        aus,
        kind="svg",
        scale=4,
        dark="#111827",
        light="#ffffff",
        border=4,
        xmldecl=False,
        svgns=True,
        omitsize=True,
    )
    return aus.getvalue().decode("utf-8")


def _adresse(db: DbSession, vom_browser: str) -> str:
    """⚠️ **Die Einstellung geht vor.** Wer nexmail im Heimnetz über eine
    IP-Adresse aufruft, will der App trotzdem die Adresse mitgeben, unter der es
    auch unterwegs erreichbar ist."""
    gespeichert = einstellung_lesen(db, "oeffentliche_adresse")
    eingestellt = adressdienst.fuer_modul(gespeichert, get_settings().url_base)
    for kandidat in (eingestellt, vom_browser.strip().rstrip("/")):
        teile = urlsplit(kandidat)
        if teile.scheme in ("http", "https") and teile.netloc:
            return kandidat
    raise MeldungHttp(status.HTTP_422_UNPROCESSABLE_CONTENT, "app_adresse_fehlt")


@router.post("", response_model=KopplungNeu, status_code=status.HTTP_201_CREATED)
def anlegen(
    person: AngemeldeterBenutzer, db: DbSession, eingabe: KopplungAnlegen | None = None
) -> KopplungNeu:
    """Einen Code für das eigene Konto."""
    # Erst die Adresse: Ohne sie entstünde ein Code, den keine App benutzen kann.
    adresse = _adresse(db, eingabe.adresse if eingabe else "")
    try:
        v = app_kopplung.vorbereiten(db, person)
    except KopplungFehler as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    link = (
        f"{APP_LINK}?address={quote(adresse, safe='')}&pairing={quote(v.kennung, safe='')}"
        f"&secret={quote(v.geheimnis, safe='')}"
    )
    return KopplungNeu(
        kennung=v.kennung,
        code=v.code,
        gilt_bis=v.gilt_bis,
        adresse=adresse,
        link=link,
        qr_svg=_qr_svg(link),
    )


@router.get("/erlaubt", response_model=Riegel)
def riegel_lesen(person: AngemeldeterBenutzer, db: DbSession) -> Riegel:
    return Riegel(erlaubt=app_kopplung.erlaubt(db))


@router.put("/erlaubt", response_model=Riegel)
def riegel_setzen(eingabe: Riegel, person: Betreiber, db: DbSession) -> Riegel:
    """⚠️ **Nur der Betreiber.** Zu heißt: Keine App kommt mehr herein, sofort."""
    return Riegel(erlaubt=app_kopplung.erlauben(db, eingabe.erlaubt))


@router.get("/{kennung}", response_model=KopplungStand)
def stand(kennung: str, person: AngemeldeterBenutzer, db: DbSession) -> KopplungStand:
    """Ist der Code abgeholt? Die Seite fragt das alle paar Sekunden."""
    try:
        wie, geraet = app_kopplung.stand(db, kennung, person)
    except KopplungFehler as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    return KopplungStand(stand=wie, geraet=geraet)


@router.delete("/{kennung}", status_code=status.HTTP_204_NO_CONTENT)
def zurueckziehen(kennung: str, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        app_kopplung.zurueckziehen(db, kennung, person)
    except KopplungFehler as fehler:
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler


# --- App ------------------------------------------------------------------- #


class SchluesselAbholen(BaseModel):
    device: str = Field(default="", max_length=app_kopplung.GERAET_HOECHSTENS)


class CodeAbholen(SchluesselAbholen):
    code: str = Field(max_length=20)


class AbgeholtesKonto(BaseModel):
    id: str
    name: str


class AbgeholterSchluessel(BaseModel):
    key: str
    account: AbgeholtesKonto


def _antwort(token: str, person) -> JSONResponse:
    inhalt = AbgeholterSchluessel(
        key=token,
        account=AbgeholtesKonto(id=person.id, name=person.anzeigename or person.benutzername),
    )
    # ⚠️ Ein Schlüssel darf in keinem Zwischenspeicher liegen bleiben.
    return JSONResponse(content=inhalt.model_dump(), headers={"Cache-Control": "no-store"})


def _wege_offen(db: DbSession) -> None:
    if not app_kopplung.erlaubt(db):
        raise MeldungHttp(status.HTTP_403_FORBIDDEN, "app_abgeschaltet")


@public_router.post(
    "/pairing/code",
    response_model=AbgeholterSchluessel,
    summary="Fetch the key with the short code",
)
def mit_code(eingabe: CodeAbholen, request: Request, db: DbSession) -> JSONResponse:
    """⚠️ **Die Bremse zählt je Adresse.** Hier gibt es keine Kennung, an der man
    zählen könnte, und 40 Bit tragen nur mit ihr."""
    _wege_offen(db)
    wache = anmeldebremse.torwaechter(request, "app-kopplung", "code")
    try:
        token, person = app_kopplung.mit_code(
            db, eingabe.code, eingabe.device, anmeldebremse.adresse_von(request)
        )
    except KopplungFehler as fehler:
        wache.fehlgeschlagen()
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    wache.geschafft()
    return _antwort(token, person)


@public_router.post(
    "/pairing/{pairing_id}/key",
    response_model=AbgeholterSchluessel,
    summary="Fetch the key from a QR code",
)
def abholen(
    pairing_id: str,
    request: Request,
    db: DbSession,
    eingabe: SchluesselAbholen | None = None,
    secret: Annotated[str | None, Header(alias="X-Pairing-Secret", max_length=100)] = None,
) -> JSONResponse:
    """⚠️ **Unbekannt, falsch, abgelaufen und verbraucht antworten gleich**
    (404 ``app_kopplung_unbekannt``). Ein Unterschied wäre nur für jemanden
    nützlich, der Geheimnisse durchprobiert."""
    _wege_offen(db)
    wache = anmeldebremse.torwaechter(request, "app-kopplung", pairing_id[:32])
    try:
        token, person = app_kopplung.abholen(
            db,
            pairing_id,
            secret,
            eingabe.device if eingabe else "",
            anmeldebremse.adresse_von(request),
        )
    except KopplungFehler as fehler:
        wache.fehlgeschlagen()
        raise MeldungHttp.aus(fehler, _status(fehler)) from fehler
    wache.geschafft()
    return _antwort(token, person)
