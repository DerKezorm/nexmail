"""Die Abwesenheitsnotiz — lesen, einstellen, nachsehen wer sie bekam.

Die Regeln, nach denen sie verschickt wird, stehen in
``services/abwesenheit.py``. Hier steht nur, wie man sie einstellt.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Abwesenheitsantwort, Konto
from ..services import abwesenheit as dienst
from .einstellungen import SCHLUESSEL_ZEITZONE

logger = logging.getLogger("nexmail.abwesenheit")

router = APIRouter(prefix="/api/abwesenheit", tags=["abwesenheit"])


class Stand(BaseModel):
    konto_id: str
    adresse: str
    farbe: int
    aktiv: bool = False
    von: str = ""
    bis: str = ""
    betreff: str = ""
    text: str = ""
    #: Ob die Notiz **jetzt** greift. `aktiv` allein sagt das nicht — der
    #: Zeitraum kann noch nicht begonnen oder schon geendet haben, und die
    #: Oberfläche soll den Unterschied zeigen können.
    laeuft: bool = False


class Eingabe(BaseModel):
    aktiv: bool = False
    #: Leer oder ``JJJJ-MM-TT``.
    von: str = Field(default="", max_length=10)
    bis: str = Field(default="", max_length=10)
    betreff: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=5000)


class Antwortzeile(BaseModel):
    konto_id: str
    adresse: str
    gesendet: datetime


def _zeitzone(db) -> str:
    return einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone


def _stand(konto: Konto, zeitzone: str) -> Stand:
    return Stand(
        konto_id=konto.id,
        adresse=konto.adresse,
        farbe=konto.farbe,
        aktiv=konto.abwesenheit_aktiv,
        von=konto.abwesenheit_von,
        bis=konto.abwesenheit_bis,
        betreff=konto.abwesenheit_betreff,
        text=konto.abwesenheit_text,
        laeuft=dienst.laeuft(konto, zeitzone),
    )


def _meins(db, person, konto_id: str) -> Konto:
    konto = db.get(Konto, konto_id)
    if konto is None or konto.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return konto


@router.get("", response_model=list[Stand])
def alle(person: AngemeldeterBenutzer, db: DbSession) -> list[Stand]:
    zeitzone = _zeitzone(db)
    konten = db.scalars(
        select(Konto).where(Konto.benutzer_id == person.id).order_by(Konto.angelegt)
    )
    return [_stand(k, zeitzone) for k in konten]


@router.put("/{konto_id}", response_model=Stand)
def stellen(konto_id: str, eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    """Einstellen — und beim Einschalten die Merkliste leeren.

    ⚠️ **Ohne Text keine Notiz.** Eine eingeschaltete Abwesenheit, die eine
    leere Mail verschickt, ist schlimmer als keine: Der Empfänger denkt, er
    habe etwas kaputtgemacht.
    """
    konto = _meins(db, person, konto_id)

    for wert in (eingabe.von, eingabe.bis):
        if wert:
            try:
                date.fromisoformat(wert)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="abwesenheit_datum_ungueltig"
                ) from None
    if eingabe.von and eingabe.bis and eingabe.bis < eingabe.von:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="abwesenheit_zeitraum_verdreht"
        )
    if eingabe.aktiv and not eingabe.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="abwesenheit_ohne_text"
        )

    # ⚠️ **Nur beim Umlegen von aus auf an leeren.** Wer nur den Text
    # nachbessert, während die Notiz läuft, soll nicht plötzlich allen ein
    # zweites Mal antworten.
    if eingabe.aktiv and not konto.abwesenheit_aktiv:
        dienst.zuruecksetzen(db, konto)

    konto.abwesenheit_aktiv = eingabe.aktiv
    konto.abwesenheit_von = eingabe.von
    konto.abwesenheit_bis = eingabe.bis
    konto.abwesenheit_betreff = eingabe.betreff.strip()
    konto.abwesenheit_text = eingabe.text
    db.commit()
    logger.info("The out-of-office setting was changed (active=%s).", eingabe.aktiv)
    return _stand(konto, _zeitzone(db))


@router.get("/antworten", response_model=list[Antwortzeile])
def antworten(person: AngemeldeterBenutzer, db: DbSession) -> list[Antwortzeile]:
    """Wem die Notiz schon geschickt wurde — über alle eigenen Postfächer.

    ⚠️ **Diese Liste ist der Schleifenschutz, sichtbar gemacht.** „Je Absender
    einmal" muss ohnehin irgendwo stehen; wer sie sieht, erkennt eine Schleife,
    bevor sie peinlich wird.
    """
    zeilen = db.execute(
        select(Abwesenheitsantwort)
        .join(Konto, Konto.id == Abwesenheitsantwort.konto_id)
        .where(Konto.benutzer_id == person.id)
        .order_by(Abwesenheitsantwort.gesendet.desc())
        .limit(200)
    ).scalars()
    return [
        Antwortzeile(konto_id=z.konto_id, adresse=z.adresse, gesendet=z.gesendet) for z in zeilen
    ]
