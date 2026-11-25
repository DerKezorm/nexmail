"""Die erste Einrichtung.

⚠️ **Diese Endpunkte sind ohne Anmeldung erreichbar** - anders geht es nicht,
es gibt ja noch kein Konto. Der Schutz ist: **Sobald ein Benutzer existiert,
ist der Weg zu** - mit 404, nicht ausgeblendet.

⚠️ **Seit dem Kontenmodul mit Einrichtungscode** (Entwurf, Entscheidung „Einrichtungscode: ueberall gleich“).
Vorher galt: Wer eine frische, aus dem Netz erreichbare Installation vor ihrem Besitzer findet, kann sie uebernehmen.
Der Code steht bei jedem Start im Protokoll, solange es kein Konto gibt, oder kommt aus ``NEXMAIL_SETUP_TOKEN``.
Eine laufende Installation fragt nie danach. Derselbe Code schuetzt das Einspielen einer Sicherung vor der
Einrichtung (``routers/sicherung``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import hat_benutzer
from ..deps import DbSession
from ..models import Benutzer
from ..services import anmeldebremse
from ..services import konten_store as kontenstore
from ..vendor import nexkonten
from ..services import sitzung as sitzungsdienst
from ..vendor import nexkonten

logger = logging.getLogger("nexmail.setup")

router = APIRouter(prefix="/api/setup", tags=["setup"])


class Stand(BaseModel):
    eingerichtet: bool
    zwei_faktor_aus: bool
    #: Ob die Einrichtung einen Code verlangt (ohne Konto immer).
    code_noetig: bool = True
    #: Die Mindestlaenge eines neuen Passworts.
    min_passwort: int = nexkonten.names.PASSWORD_MIN


class KontoEingabe(BaseModel):
    #: ⚠️ **Feldnamen wie vorher**, dazu die neuen. Die Regeln prueft das Modul (Kennungen statt 422 von Pydantic).
    benutzername: str = Field(default="", max_length=200)
    passwort: str = Field(default="", max_length=300)
    anzeigename: str = Field(default="", max_length=200)
    einrichtungscode: str = Field(default="", max_length=200)
    kontaktadresse: str = Field(default="", max_length=320)
    #: Still aus dem Browser (kein Feld auf der Seite); geaendert wird sie im Profil.
    sprache: str = Field(default="", max_length=35)


class KontoAntwort(BaseModel):
    benutzername: str


def _nur_vor_der_einrichtung(db) -> None:
    if hat_benutzer(db):
        # 404 und nicht 403: Es gibt diesen Weg nach der Einrichtung nicht
        # mehr, und das ist eine ehrlichere Auskunft als "verboten".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/status", response_model=Stand)
def status_lesen(db: DbSession) -> Stand:
    """Ob die Oberflaeche den Einrichtungsassistenten zeigen muss."""
    eingerichtet = hat_benutzer(db)
    return Stand(
        eingerichtet=eingerichtet,
        zwei_faktor_aus=nexkonten.factor.switched_off(),
        code_noetig=not eingerichtet,
    )


@router.post("/konto", response_model=KontoAntwort, status_code=status.HTTP_201_CREATED)
def konto_anlegen(
    eingabe: KontoEingabe, request: Request, response: Response, db: DbSession
) -> KontoAntwort:
    """Das erste Konto anlegen - und damit die Tuer schliessen.

    ⚠️ **Der Betreiber-Haken entsteht hier, und das ist der Regelfall.** Das Konto aus dem Assistenten gehoert dem
    Menschen, dem der Server gehoert; seine Adresse zaehlt sofort (es gibt noch keinen Postausgang).

    ⚠️ **Der zweite Faktor wird hier nicht erzwungen** (01.09.2026): Er ist eine Wahl unter Einstellungen →
    Sicherheit. Die Sitzung ist deshalb sofort vollstaendig.

    ⚠️ **Die Bremse zaehlt den Code am Absender** (bzw. an der Tuer, ohne ``NEXMAIL_CLIENT_IP``): Er ist kurz.
    """
    _nur_vor_der_einrichtung(db)
    wache = anmeldebremse.torwaechter(request, "einrichtung", "-")
    store = kontenstore.store_fuer(db)
    try:
        ergebnis = nexkonten.setup.setup(
            store,
            code=eingabe.einrichtungscode,
            display_name=eingabe.anzeigename,
            username=eingabe.benutzername,
            email=eingabe.kontaktadresse,
            password=eingabe.passwort,
            language=eingabe.sprache,
        )
    except nexkonten.AccountError as fehler:
        if fehler.code == "already_set_up":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from fehler
        if fehler.code == "setup_code_wrong":
            wache.fehlgeschlagen()
        raise kontenstore.http(fehler) from fehler
    wache.geschafft()

    neuer = db.get(Benutzer, str(ergebnis.account.id))
    sitzungsdienst.anlegen(db, neuer, request, response, bestaetigt=True)
    sitzungsdienst.angemeldet(db, neuer, request, response, mail=False)
    logger.info("Initial setup completed: the operator account was created.")

    return KontoAntwort(benutzername=neuer.benutzername)
