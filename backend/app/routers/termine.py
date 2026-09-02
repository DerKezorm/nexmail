"""Termin-Einladungen: anzeigen und beantworten.

⚠️ **nexmail hat keinen Kalender.** Eine Zusage sagt dem Einladenden Bescheid,
sie legt den Termin nirgends ab. Gemerkt wird nur, **wie** geantwortet wurde —
damit die Einladung beim zweiten Öffnen nicht aussieht wie beim ersten.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from ..config import get_settings
from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Anhang, Konto, Nachricht, Terminantwort
from ..services import kalender, konten as kontendienst, senden as sendedienst, verfassen
from .einstellungen import SCHLUESSEL_ZEITZONE

logger = logging.getLogger("nexmail.termine")

router = APIRouter(prefix="/api/termine", tags=["termine"])

#: Woran man eine Einladung im Anhang erkennt.
KALENDER_TYPEN = ("text/calendar", "application/ics")


class PersonZeile(BaseModel):
    name: str = ""
    adresse: str = ""


class Einladung(BaseModel):
    uid: str
    methode: str
    titel: str
    beschreibung: str
    ort: str
    beginn: str
    ende: str
    ganztaegig: bool
    #: Gesetzt, wenn die Zeitzone der Einladung unbekannt war. Die Zeit steht
    #: dann so da, wie sie kam — die Oberfläche nennt den Namen dazu.
    fremde_zeitzone: str
    wiederholt_sich: bool
    abgesagt: bool
    organisator: PersonZeile
    teilnehmer: list[PersonZeile]
    #: Was zuletzt geantwortet wurde: ``zusage`` | ``vorbehalt`` | ``absage``.
    antwort: str = ""
    antwort_am: datetime | None = None


class AntwortEingabe(BaseModel):
    antwort: str


def _kalenderteil(db, nachricht: Nachricht) -> bytes | None:
    """Die ``.ics`` aus den Anhängen — oder ``None``."""
    ordner = get_settings().blob_dir
    for anhang in nachricht.anhaenge:
        typ = (anhang.mime or "").split(";")[0].strip().lower()
        endung = (anhang.dateiname or "").lower().endswith(".ics")
        if typ not in KALENDER_TYPEN and not endung:
            continue
        if not anhang.blob_hash:
            continue
        datei = ordner / anhang.blob_hash
        if datei.is_file():
            return datei.read_bytes()
    return None


def _meine(db, person, nachricht_id: int) -> Nachricht:
    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return nachricht


def _einladung(db, person, nachricht: Nachricht) -> tuple[kalender.Termin, Einladung] | None:
    roh = _kalenderteil(db, nachricht)
    if roh is None:
        return None
    zeitzone = einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone
    termin = kalender.lesen(roh, zeitzone)
    if termin is None:
        return None

    gemerkt = db.scalars(
        select(Terminantwort).where(
            Terminantwort.benutzer_id == person.id, Terminantwort.uid == termin.uid
        )
    ).first()

    return termin, Einladung(
        uid=termin.uid,
        methode=termin.methode,
        titel=termin.titel,
        beschreibung=termin.beschreibung,
        ort=termin.ort,
        beginn=termin.beginn,
        ende=termin.ende,
        ganztaegig=termin.ganztaegig,
        fremde_zeitzone=termin.fremde_zeitzone,
        wiederholt_sich=termin.wiederholt_sich,
        abgesagt=termin.abgesagt,
        organisator=PersonZeile(
            name=termin.organisator.name, adresse=termin.organisator.adresse
        ),
        teilnehmer=[PersonZeile(name=t.name, adresse=t.adresse) for t in termin.teilnehmer],
        antwort=gemerkt.antwort if gemerkt else "",
        antwort_am=gemerkt.gesendet if gemerkt else None,
    )


@router.get("/{nachricht_id}", response_model=Einladung | None)
def einladung(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Einladung | None:
    """Die Einladung in dieser Nachricht — oder ``null``."""
    nachricht = _meine(db, person, nachricht_id)
    gefunden = _einladung(db, person, nachricht)
    return gefunden[1] if gefunden else None


@router.post("/{nachricht_id}/antwort", response_model=Einladung)
def antworten(
    nachricht_id: int, eingabe: AntwortEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> Einladung:
    """Zusagen, mit Vorbehalt zusagen oder absagen.

    ⚠️ **Die Antwort geht an den Einladenden, nicht an alle Teilnehmer.** Wer
    allen antwortet, macht aus einer Zusage eine Rundmail.
    """
    if eingabe.antwort not in kalender.ANTWORTEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="termin_antwort_unbekannt"
        )

    nachricht = _meine(db, person, nachricht_id)
    gefunden = _einladung(db, person, nachricht)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="termin_fehlt")
    termin, _ = gefunden

    if not termin.organisator.adresse:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="termin_ohne_einladenden"
        )

    konto = db.get(Konto, nachricht.konto_id)
    ich = kalender.Person(name=kontendienst.absendername(konto), adresse=konto.adresse)
    ics = kalender.antwort_bauen(termin, ich, eingabe.antwort, datetime.now(timezone.utc))

    vorsatz = {"zusage": "Zugesagt", "vorbehalt": "Mit Vorbehalt", "absage": "Abgesagt"}[
        eingabe.antwort
    ]
    sendedienst.einreihen(
        db,
        konto,
        verfassen.Entwurf(
            von_name=ich.name,
            von_adresse=ich.adresse,
            an=[termin.organisator.adresse],
            betreff=f"{vorsatz}: {termin.titel}".strip(),
            # ⚠️ **Auch ein Satz im Text.** Ein Empfänger ohne
            # Kalenderunterstützung sähe sonst eine leere Mail.
            text=f"{vorsatz}: {termin.titel}".strip(),
            html="",
            kalender=ics,
            kalender_methode="REPLY",
        ),
    )

    gemerkt = db.scalars(
        select(Terminantwort).where(
            Terminantwort.benutzer_id == person.id, Terminantwort.uid == termin.uid
        )
    ).first()
    if gemerkt is None:
        gemerkt = Terminantwort(benutzer_id=person.id, uid=termin.uid, antwort=eingabe.antwort)
        db.add(gemerkt)
    else:
        # ⚠️ Umentscheiden ist erlaubt — und dann gilt die neue Antwort samt
        # neuem Zeitpunkt, sonst steht dort für immer die erste.
        gemerkt.antwort = eingabe.antwort
        gemerkt.gesendet = datetime.now(timezone.utc)
    db.commit()

    logger.info("An invitation was answered (%s).", eingabe.antwort)
    gefunden = _einladung(db, person, nachricht)
    assert gefunden is not None
    return gefunden[1]
