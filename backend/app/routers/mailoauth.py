"""OAuth für Google und Microsoft — die Adressen.

⚠️ **Zwei Ebenen, zwei Rechte.** Die App-Anmeldung (Client-ID und Geheimnis)
richtet der **Betreiber** einmal ein; die Zustimmung erteilt **jeder Benutzer**
für sein eigenes Konto. Wer das vermischt, gibt entweder jedem das Geheimnis
oder dem Betreiber fremde Postfächer.

⚠️ **Der Rückweg ist eine Weiterleitung, nie JSON.** Ihn sieht ein Mensch —
dieselbe Regel wie bei ``routers/oidc.py``, und dort steht auch, warum.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..models import OauthZugang
from ..services import mailoauth as dienst

logger = logging.getLogger("nexmail.mailoauth")

router = APIRouter(prefix="/api/mailoauth", tags=["mailoauth"])

#: Wie lange ein angefangener Anlauf gilt. ⚠️ Kurz: Er liegt als Cookie beim
#: Browser, und ein alter Anlauf ist nur noch ein offenes Fenster.
ANLAUF_SEKUNDEN = 600
ANLAUF_COOKIE = "nexmail_oauth"


class AnbieterZeile(BaseModel):
    art: str
    name: str
    eingerichtet: bool
    client_id: str = ""
    mandant: str = ""
    #: Die Adresse, die beim Anbieter als Rückkehr eingetragen werden muss —
    #: wörtlich zum Kopieren.
    rueckkehr: str = ""


class AnbieterWunsch(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    #: ⚠️ Leer heißt **unverändert** — dieselbe Regel wie beim Passwort.
    client_secret: str = ""
    mandant: str = "common"


class ZugangZeile(BaseModel):
    id: str
    art: str
    adresse: str
    letzter_fehler: str
    #: Wie viel an dieser Zustimmung haengt. ⚠️ **Die Rueckfrage beim Trennen
    #: muss es nennen koennen** — „2 Postfaecher und 3 Kalender werden
    #: entfernt" ist eine andere Aussage als „Zustimmung entfernen".
    postfaecher: int = 0
    kalender: int = 0


def _rueckkehr(db, art: str) -> str:
    """Die Rückkehr-Adresse dieser Installation.

    ⚠️ **Sie muss beim Anbieter wörtlich hinterlegt sein.** Ein Zeichen
    daneben, und Google antwortet mit ``redirect_uri_mismatch`` — die
    Oberfläche zeigt sie deshalb zum Kopieren an, statt sie beschreiben zu
    lassen.
    """
    from ..config import get_settings
    from .einstellungen import SCHLUESSEL_OEFFENTLICHE_ADRESSE

    basis = (einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE) or "").rstrip("/")
    return f"{basis}{get_settings().url_base}/api/mailoauth/{art}/zurueck"


# --- Die App des Betreibers ----------------------------------------------- #


@router.get("/anbieter", response_model=list[AnbieterZeile])
def anbieter_liste(_: Betreiber, db: DbSession) -> list[AnbieterZeile]:
    raus: list[AnbieterZeile] = []
    for art, beschreibung in dienst.ARTEN.items():
        eintrag = dienst.anbieter(db, art)
        raus.append(
            AnbieterZeile(
                art=art,
                name=beschreibung.name,
                eingerichtet=eintrag is not None,
                client_id=eintrag.client_id if eintrag else "",
                mandant=eintrag.mandant if eintrag else "common",
                rueckkehr=_rueckkehr(db, art),
            )
        )
    return raus


@router.put("/anbieter/{art}", response_model=AnbieterZeile)
def anbieter_setzen(
    art: str, wunsch: AnbieterWunsch, _: Betreiber, db: DbSession
) -> AnbieterZeile:
    try:
        eintrag = dienst.anbieter_setzen(
            db, art, wunsch.client_id, wunsch.client_secret, wunsch.mandant
        )
    except dienst.OauthFehler as f:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(f)) from f
    return AnbieterZeile(
        art=art,
        name=dienst.ARTEN[art].name,
        eingerichtet=True,
        client_id=eintrag.client_id,
        mandant=eintrag.mandant,
        rueckkehr=_rueckkehr(db, art),
    )


@router.delete("/anbieter/{art}", status_code=status.HTTP_204_NO_CONTENT)
def anbieter_entfernen(art: str, _: Betreiber, db: DbSession) -> Response:
    dienst.anbieter_entfernen(db, art)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Die Zustimmung des Benutzers ----------------------------------------- #


class MoeglichZeile(BaseModel):
    art: str
    name: str
    eingerichtet: bool


@router.get("/moeglich", response_model=list[MoeglichZeile])
def moeglich(_: AngemeldeterBenutzer, db: DbSession) -> list[MoeglichZeile]:
    """Welche Anbieter offenstehen — für **jeden** Benutzer, nicht nur den
    Betreiber.

    ⚠️ **Ein Knopf, der nur in eine Fehlermeldung führt, ist eine Sackgasse
    mit Beschriftung.** „Postfach hinzufügen" bietet Google nur an, wenn der
    Betreiber die App eingetragen hat — und das muss auch ein gewöhnlicher
    Benutzer erfahren dürfen.

    ⚠️ **Nur Name und Ja/Nein.** Client-ID, Mandant und Rückkehr-Adresse
    bleiben bei ``/anbieter`` und damit beim Betreiber; sie sagen etwas über
    die Installation, und dafür gibt es hier keinen Anlass.
    """
    return [
        MoeglichZeile(
            art=art,
            name=beschreibung.name,
            eingerichtet=dienst.anbieter(db, art) is not None,
        )
        for art, beschreibung in dienst.ARTEN.items()
    ]


@router.get("/zugaenge", response_model=list[ZugangZeile])
def zugaenge(person: AngemeldeterBenutzer, db: DbSession) -> list[ZugangZeile]:
    raus: list[ZugangZeile] = []
    for z in dienst.zugaenge(db, person):
        postfaecher, kalender = dienst.was_daran_haengt(db, z)
        raus.append(
            ZugangZeile(
                id=z.id,
                art=z.art,
                adresse=z.adresse,
                letzter_fehler=z.letzter_fehler,
                postfaecher=len(postfaecher),
                kalender=len(kalender),
            )
        )
    return raus


@router.delete("/zugaenge/{zugang_id}", status_code=status.HTTP_204_NO_CONTENT)
def zugang_entfernen(
    zugang_id: str, person: AngemeldeterBenutzer, db: DbSession
) -> Response:
    """⚠️ Beim Anbieter bleibt die Erlaubnis bestehen — dort widerruft man sie
    selbst. nexmail vergisst nur seine Token.

    ⚠️ **Die Postfaecher und Kalender daran gehen mit.** Sie haben danach
    keinen Anmeldeweg mehr; stehen liessen wir sonst Zeilen, die bei jedem
    Takt „Anmeldung fehlgeschlagen" melden — und niemand braechte das mit dem
    Trennen in Verbindung. Die Oberflaeche sagt es **vorher**, mit Zahlen.
    """
    try:
        dienst.entfernen(db, person, zugang_id)
    except dienst.OauthFehler as f:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(f)) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class Anlauf(BaseModel):
    ziel: str


class Anlaufwunsch(BaseModel):
    """⚠️ **Wozu die Zustimmung dient, faehrt im Anlauf mit.**

    Der Rueckweg vom Anbieter ist eine ganze Seitennavigation: Was die
    Oberflaeche gerade offen hatte, ist danach weg. Ohne diesen Hinweis
    landete jeder wieder auf der Startseite und muesste den Weg von vorn
    beginnen — mit ihm macht das Fenster dort weiter, wo es war.

    ``postfach`` heisst: Der Weg kam aus „Postfach hinzufuegen". Leer heisst:
    Es ging nur um die Zustimmung selbst (Einstellungen → Sicherheit).
    """

    zweck: str = Field(default="", max_length=20)


#: Was ``zweck`` sein darf. ⚠️ Der Wert landet in einer Weiterleitungsadresse;
#: eine freie Zeichenkette waere eine Einladung, dort etwas anderes
#: unterzubringen.
ZWECKE = ("", "postfach")


@router.post("/{art}/start", response_model=Anlauf)
def start(
    art: str,
    request: Request,
    person: AngemeldeterBenutzer,
    db: DbSession,
    antwort: Response,
    wunsch: Anlaufwunsch | None = None,
) -> Anlauf:
    """Wohin der Browser geschickt wird — plus das Anlauf-Cookie.

    ⚠️ **``SameSite=lax``, nicht ``strict``.** Der Rückweg ist eine Navigation
    von fremder Seite; ein striktes Cookie fährt dabei nicht mit, und die
    Zustimmung scheiterte jedes Mal mit „Anlauf fehlt". Genau daran ist der
    Verknüpfen-Knopf bei OIDC schon einmal gescheitert.
    """
    if art not in dienst.ARTEN:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    zweck = (wunsch.zweck if wunsch else "") or ""
    if zweck not in ZWECKE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="oauth_zweck")
    zustand = secrets.token_urlsafe(24)
    try:
        ziel = dienst.hinweg(db, art, _rueckkehr(db, art), zustand)
    except dienst.OauthFehler as f:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(f)) from f

    from ..services import sitzung as sitzungsdienst

    antwort.set_cookie(
        ANLAUF_COOKIE,
        f"{zustand}:{person.id}:{zweck}",
        max_age=ANLAUF_SEKUNDEN,
        httponly=True,
        samesite="lax",
        secure=sitzungsdienst._secure(request),
        path=f"{_basis()}/api/mailoauth",
    )
    return Anlauf(ziel=ziel)


def _basis() -> str:
    from ..config import get_settings

    return get_settings().url_base


def _oberflaeche(pfad: str) -> str:
    return f"{_basis()}{pfad}"


@router.get("/{art}/zurueck")
def zurueck(art: str, request: Request, db: DbSession) -> RedirectResponse:
    """Der Rückweg vom Anbieter.

    ⚠️ **Der Fehler des Anbieters wird VOR dem Anlauf geprüft.** Sonst wird aus
    „der Benutzer hat abgelehnt" ein irreführendes „Anlauf fehlt" — derselbe
    Fallstrick wie bei OIDC.
    """
    fehler = request.query_params.get("error")
    if fehler:
        logger.info("The %s consent was refused: %s", art, fehler)
        return _zurueck_zur_seite("abgelehnt")

    anlauf = request.cookies.get(ANLAUF_COOKIE) or ""
    zustand = request.query_params.get("state") or ""
    code = request.query_params.get("code") or ""
    if not anlauf or ":" not in anlauf:
        return _zurueck_zur_seite("anlauf_fehlt")
    erwartet, _, rest = anlauf.partition(":")
    benutzer_id, _, zweck = rest.partition(":")
    # ⚠️ Zeitkonstanter Vergleich: Der Zustand ist ein Geheimnis auf Zeit.
    if not secrets.compare_digest(erwartet, zustand) or not code:
        return _zurueck_zur_seite("anlauf_fehlt")

    from ..models import Benutzer

    person = db.get(Benutzer, benutzer_id)
    if person is None:
        return _zurueck_zur_seite("anlauf_fehlt")

    try:
        zugang = dienst.einloesen(db, person, art, code, _rueckkehr(db, art))
    except dienst.OauthFehler as f:
        logger.info("Redeeming the %s code failed: %s", art, f)
        # ⚠️ Auch im Fehlerfall den Zweck mitgeben: Wer aus „Postfach
        # hinzufuegen" kam, soll den Grund dort sehen und nicht auf einer
        # Startseite ohne Zusammenhang.
        return _zurueck_zur_seite(str(f), zweck)

    antwort = _zurueck_zur_seite("", zweck, zugang.id)
    antwort.delete_cookie(ANLAUF_COOKIE, path=f"{_basis()}/api/mailoauth")
    return antwort


def _zurueck_zur_seite(fehler: str, zweck: str = "", zugang_id: str = "") -> RedirectResponse:
    """⚠️ **Immer eine Weiterleitung, nie JSON.** Den Rückweg sieht ein Mensch.

    ``zweck`` und ``zugang`` sagen der Oberfläche, wo sie weitermachen soll —
    die Zustimmung kostet eine volle Seitennavigation, und ohne diese beiden
    Werte wäre danach alles zu, was vorher offen war.
    """
    felder = {"oauth": fehler or "ok"}
    if zweck in ZWECKE and zweck:
        felder["weiter"] = zweck
    if zugang_id:
        felder["zugang"] = zugang_id
    return RedirectResponse(
        _oberflaeche(f"/?{urlencode(felder)}"), status_code=status.HTTP_303_SEE_OTHER
    )
