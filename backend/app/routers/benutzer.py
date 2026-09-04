"""Benutzerverwaltung — was der Anwendung gehoert, nicht dem Einzelnen.

⚠️ **Nur der Betreiber.** ``ist_betreiber`` ist dabei ein Haken, kein Rang: Er
sagt nicht, was dieser Mensch darf, sondern was andere mit ihm nicht duerfen.

⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
einzeln. nexmail ist der Mail-Client eines Haushalts, keine Plattform.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import einstellung_lesen
from ..deps import Betreiber, DbSession
from ..meldung import Meldung, MeldungHttp
from ..models import Benutzer, Einladung
from ..routers.einstellungen import SCHLUESSEL_OEFFENTLICHE_ADRESSE
from ..services import anmeldebremse
from ..services import benutzer as benutzerdienst
from ..services import kidienst
from ..services import einladung as einladungsdienst
from ..services import systempost

logger = logging.getLogger("nexmail.benutzer")

router = APIRouter(prefix="/api/benutzer", tags=["benutzer"])


class BenutzerZeile(BaseModel):
    id: str
    benutzername: str
    anzeigename: str
    ist_betreiber: bool
    zwei_faktor_aktiv: bool
    angelegt: datetime
    #: Wie viele Postfaecher an ihm haengen — die Liste soll etwas aussagen.
    postfaecher: int
    #: ⚠️ **Der Riegel des Betreibers je Konto**, nicht die Wahl des Benutzers.
    #: Ab Werk erlaubt: Die Spalte ist die Ausnahmeliste, nicht die
    #: Einladungsliste — der bewusste Akt ist der Riegel der Installation.
    ki_erlaubt: bool


class EinladungsZeile(BaseModel):
    id: str
    benutzername: str
    anzeigename: str
    adresse: str
    angelegt: datetime
    laeuft_ab: datetime
    abgelaufen: bool


class Bestand(BaseModel):
    benutzer: list[BenutzerZeile]
    einladungen: list[EinladungsZeile]
    #: Ohne Postausgang laesst sich niemand einladen — das sagt die Oberflaeche
    #: **vorher**, statt den Betreiber gegen einen Fehler laufen zu lassen.
    postausgang_da: bool
    #: Ohne oeffentliche Adresse waere der Link in der Mail unbrauchbar.
    adresse_da: bool


class Einladen(BaseModel):
    benutzername: str = Field(min_length=1, max_length=64)
    adresse: str = Field(min_length=3, max_length=320)
    anzeigename: str = Field(default="", max_length=120)


class Umfang(BaseModel):
    postfaecher: int
    nachrichten: int
    kontakte: int
    regeln: int
    signaturen: int


def _zeile(db, person: Benutzer) -> BenutzerZeile:
    from ..models import Konto

    anzahl = len(db.execute(select(Konto.id).where(Konto.benutzer_id == person.id)).all())
    return BenutzerZeile(
        id=person.id,
        benutzername=person.benutzername,
        anzeigename=person.anzeigename,
        ist_betreiber=person.ist_betreiber,
        zwei_faktor_aktiv=person.totp_bestaetigt,
        angelegt=person.angelegt,
        postfaecher=anzahl,
        ki_erlaubt=person.ki_erlaubt,
    )


def _einladungszeile(e: Einladung) -> EinladungsZeile:
    return EinladungsZeile(
        id=e.id,
        benutzername=e.benutzername,
        anzeigename=e.anzeigename,
        adresse=e.adresse,
        angelegt=e.angelegt,
        laeuft_ab=e.laeuft_ab,
        abgelaufen=einladungsdienst.abgelaufen(e),
    )


@router.get("", response_model=Bestand)
def liste(_: Betreiber, db: DbSession) -> Bestand:
    leute = db.execute(select(Benutzer).order_by(Benutzer.angelegt)).scalars().all()
    return Bestand(
        benutzer=[_zeile(db, p) for p in leute],
        einladungen=[_einladungszeile(e) for e in einladungsdienst.offene(db)],
        postausgang_da=systempost.lesen(db).eingerichtet,
        adresse_da=bool(einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE)),
    )


@router.post("/einladungen", response_model=EinladungsZeile, status_code=status.HTTP_201_CREATED)
def einladen(eingabe: Einladen, _: Betreiber, db: DbSession) -> EinladungsZeile:
    """Einladen — anlegen **und** verschicken.

    ⚠️ **Beides oder nichts.** Eine Einladung, die in der Liste steht, deren
    Mail aber nie hinausging, ist die schlimmste Sorte: Der Betreiber wartet,
    der Eingeladene weiss von nichts, und in der Oberflaeche sieht alles
    richtig aus. Geht der Versand schief, wird die Zeile wieder entfernt und
    der Grund gemeldet.
    """
    adresse_der_app = einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE)
    if not adresse_der_app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oeffentliche_adresse_fehlt",
        )

    try:
        einladung, schluessel = einladungsdienst.aussprechen(
            db,
            benutzername=eingabe.benutzername,
            adresse=eingabe.adresse,
            anzeigename=eingabe.anzeigename,
        )
    except einladungsdienst.EinladungsFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler

    try:
        einladungsdienst.verschicken(db, einladung, schluessel, adresse_der_app)
    except systempost.PostFehler as fehler:
        db.delete(einladung)
        db.commit()
        raise MeldungHttp.aus(fehler, status.HTTP_502_BAD_GATEWAY) from fehler

    return _einladungszeile(einladung)


@router.delete("/einladungen/{einladung_id}", status_code=status.HTTP_204_NO_CONTENT)
def einladung_zuruecknehmen(einladung_id: str, _: Betreiber, db: DbSession) -> None:
    einladung = db.get(Einladung, einladung_id)
    if einladung is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    db.delete(einladung)
    db.commit()
    logger.info("An invitation was withdrawn.")


@router.get("/{benutzer_id}/umfang", response_model=Umfang)
def umfang(benutzer_id: str, _: Betreiber, db: DbSession) -> Umfang:
    """Was am Benutzer haengt — fuer die Rueckfrage vor dem Entfernen."""
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Umfang(**benutzerdienst.umfang(db, person))


class Uebergabe(BaseModel):
    #: ⚠️ Das eigene Kennwort. Siehe die Begruendung an der Adresse.
    passwort: str = Field(min_length=1, max_length=200)


@router.post("/{benutzer_id}/betreiber", status_code=status.HTTP_204_NO_CONTENT)
def betreiber_uebergeben(
    benutzer_id: str, eingabe: Uebergabe, ich: Betreiber, request: Request, db: DbSession
) -> None:
    """Den Betreiber-Haken an jemand anderen geben.

    ⚠️ **Genau ein Betreiber, immer.** Der Haken wandert, er wird nicht
    vergeben: Wer ihn abgibt, hat ihn danach nicht mehr. Zwei Betreiber waeren
    nicht schlimm, aber null waeren das Ende — aus der Anwendung heraus fuehrt
    dann kein Weg zurueck.

    ⚠️ **Das eigene Kennwort steht davor.** Das ist der teuerste Knopf in der
    ganzen Verwaltung: Wer ihn drueckt, gibt die Verwaltung ab und kann sie
    sich nicht zurueckholen. Eine geklaute Sitzung genuegt dafuer nicht —
    dieselbe Ueberlegung wie beim Abschalten des zweiten Faktors.

    ⚠️ **Danach laesst sich der alte Betreiber entfernen.** Genau dafuer gibt
    es diesen Weg: Wer die Wohnung wechselt, hinterlaesst sonst eine
    Installation, an die niemand mehr herankommt.
    """
    wache = anmeldebremse.torwaechter(request, "betreiber-uebergeben", ich.benutzername)
    if not benutzerdienst.passwort_stimmt(ich, eingabe.passwort):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="kennwort_falsch"
        )
    wache.geschafft()

    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if person.id == ich.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="betreiber_an_sich_selbst"
        )

    person.ist_betreiber = True
    ich.ist_betreiber = False
    db.commit()
    logger.warning("The operator flag was handed over to another user.")


@router.delete("/{benutzer_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(benutzer_id: str, ich: Betreiber, db: DbSession) -> None:
    """Einen Benutzer mit allem entfernen, was ihm gehoert.

    ⚠️ **Der Betreiber selbst geht nicht.** Danach haette nexmail niemanden,
    der die Verwaltung oeffnen kann — und aus der Anwendung heraus fuehrt kein
    Weg zurueck. Wer den Betreiber wechseln will, uebergibt den Haken; das ist
    ein anderer Vorgang und keine Loeschung.
    """
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if person.id == ich.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sich_selbst_entfernen",
        )
    if person.ist_betreiber:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="betreiber_entfernen",
        )
    benutzerdienst.entfernen(db, person)


class KiErlaubnis(BaseModel):
    erlaubt: bool


@router.put("/{benutzer_id}/ki", response_model=BenutzerZeile)
def ki_erlaubnis(
    benutzer_id: str, eingabe: KiErlaubnis, ich: Betreiber, db: DbSession
) -> BenutzerZeile:
    """Einem einzelnen Konto KI-Dienste erlauben oder verbieten.

    ⚠️ **Kein Kennwort davor, anders als beim Uebergeben des Betreibers.** Das
    hier ist umkehrbar mit demselben Klick und kostet niemandem seinen Zugang —
    die Schluessel bleiben stehen. Eine Bremse fuer jede Verwaltungsaenderung
    macht die Verwaltung unbenutzbar, und dann wird sie umgangen.
    """
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise MeldungHttp.aus(Meldung("benutzer_nicht_gefunden"), status.HTTP_404_NOT_FOUND)
    kidienst.erlauben_fuer(db, person, eingabe.erlaubt)
    return _zeile(db, person)
