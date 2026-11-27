"""Die iPhone-App koppeln: im Browser der Code, in der App das Abholen, in nexmails alter Form.

Seit 0.35.0 koppelt das Gerätemodul ``geraete`` (``routers/geraete.py``). Zwei Seiten bleiben hier als Hüllen:

* ``router`` (``/api/app-kopplung``) gehört zur Oberfläche von vorher und steht unter keiner Zusage; die neue
  Oberfläche nimmt ``/api/app-pairing`` und ``/api/app-devices`` des Moduls. Die Antworten bleiben, wie sie waren
  (``kennung``, ``stand`` ``wartet``/``verbunden``/``abgelaufen``, deutsche Kennungen).
* ``public_router`` liegt unter ``/api/app/1`` und ist dort der einzige Teil ohne Schlüssel: Wer noch keinen hat, holt
  ihn hier. Die Handler sind die des Moduls, eingetragen mit der Antwortform der veröffentlichten App
  (``AbgeholterSchluessel``); sie stehen unter der Zusage (``app1.ZUGESAGT``).
"""

from __future__ import annotations

import io
from datetime import datetime
from urllib.parse import quote, urlsplit

import segno
from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..meldung import MeldungHttp
from ..models import Sitzung, utcnow
from ..services import adresse as adressdienst
from ..services import app_kopplung
from ..services.app_kopplung import KopplungFehler
from . import geraete as geraetewege

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
        "app_zu_viele_geraete": status.HTTP_429_TOO_MANY_REQUESTS,
    }.get(fehler.kennung, status.HTTP_400_BAD_REQUEST)


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
        v = app_kopplung.vorbereiten(db, person, adresse)
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


class GekoppeltesGeraet(BaseModel):
    id: str
    geraet: str
    zuletzt_gesehen: datetime
    #: Ob das Geraet Mitteilungen bekommt (es hat sich beim Push-Vermittler angemeldet).
    mitteilungen: bool


@router.get("/geraete", response_model=list[GekoppeltesGeraet])
def geraete(person: AngemeldeterBenutzer, db: DbSession) -> list[GekoppeltesGeraet]:
    """Die gekoppelten iPhones und iPads dieses Kontos in der Form von vorher (die neue Karte nimmt
    ``GET /api/app-devices``). Trennen geht ueber ``DELETE /api/sitzungen/{id}`` wie bisher."""
    zeilen = db.scalars(
        select(Sitzung)
        .where(Sitzung.benutzer_id == person.id, Sitzung.art == "geraet", Sitzung.gueltig_bis > utcnow())
        .order_by(Sitzung.zuletzt_gesehen.desc())
    )
    return [
        GekoppeltesGeraet(id=z.id, geraet=z.geraet or "", zuletzt_gesehen=z.zuletzt_gesehen, mitteilungen=bool(z.push_ticket))
        for z in zeilen
    ]


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


class AbgeholtesKonto(BaseModel):
    id: str
    name: str


class AbgeholterSchluessel(BaseModel):
    """Die Antwort jedes neuen Geräteschlüssels in nexmails alter Form: QR-Code, kurzer Code und
    ``POST /api/app/1/devices`` antworten gleich. Mit ``X-Nex-App`` antwortet das Modul in der neuen Form
    (``token``, ``account`` mit Benutzername und Bild, ``device``)."""

    key: str
    account: AbgeholtesKonto


public_router.add_api_route(
    "/pairing/code",
    geraetewege.modulweg("/pairing/code", "POST").endpoint,
    methods=["POST"],
    response_model=AbgeholterSchluessel,
    operation_id="mit_code_api_app_1_pairing_code_post",
    summary="Fetch the key with the short code",
    description="The code to type under the QR code, or the one-time code of the sign-in in the browser. "
    "The brake counts per sender.",
)
public_router.add_api_route(
    "/pairing/{pairing_id}/key",
    geraetewege.modulweg("/pairing/{pairing_id}/key", "POST").endpoint,
    methods=["POST"],
    response_model=AbgeholterSchluessel,
    operation_id="abholen_api_app_1_pairing__pairing_id__key_post",
    summary="Fetch the key from a QR code",
    description="Unknown, wrong, expired and used answer alike (`app_kopplung_unbekannt`).",
)
