"""Regeln, Signaturen und Textvorlagen."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Ordner, Regel, Signatur, Textvorlage
from ..services import (
    regeln as regeldienst,
    signaturen as signaturdienst,
    textvorlagen as vorlagendienst,
)

logger = logging.getLogger("nexmail.regeln")

router = APIRouter(prefix="/api", tags=["regeln"])


# --- Regeln ---------------------------------------------------------------- #


class Bedingung(BaseModel):
    feld: str
    vergleich: str
    wert: str = Field(max_length=500)


class Aktion(BaseModel):
    art: str
    wert: str = Field(default="", max_length=100)


class RegelZeile(BaseModel):
    id: int
    name: str
    aktiv: bool
    reihenfolge: int
    konto_id: str
    verknuepfung: str
    bedingungen: list[Bedingung]
    aktionen: list[Aktion]
    stopp: bool


class RegelEingabe(BaseModel):
    name: str = Field(default="", max_length=200)
    aktiv: bool = True
    konto_id: str = ""
    verknuepfung: str = "und"
    bedingungen: list[Bedingung]
    aktionen: list[Aktion]
    stopp: bool = False
    reihenfolge: int = 0


def _regel(r: Regel) -> RegelZeile:
    return RegelZeile(
        id=r.id,
        name=r.name,
        aktiv=r.aktiv,
        reihenfolge=r.reihenfolge,
        konto_id=r.konto_id,
        verknuepfung=r.verknuepfung,
        bedingungen=[Bedingung(**b) for b in json.loads(r.bedingungen_json or "[]")],
        aktionen=[Aktion(**a) for a in json.loads(r.aktionen_json or "[]")],
        stopp=r.stopp,
    )


@router.get("/regeln", response_model=list[RegelZeile])
def regeln(person: AngemeldeterBenutzer, db: DbSession) -> list[RegelZeile]:
    return [_regel(r) for r in regeldienst.meine(db, person)]


@router.post("/regeln", response_model=RegelZeile, status_code=status.HTTP_201_CREATED)
def regel_anlegen(
    eingabe: RegelEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> RegelZeile:
    bedingungen = [b.model_dump() for b in eingabe.bedingungen]
    aktionen = [a.model_dump() for a in eingabe.aktionen]
    try:
        regeldienst.pruefen(bedingungen, aktionen)
    except regeldienst.RegelFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    vorhandene = regeldienst.meine(db, person)
    zeile = Regel(
        benutzer_id=person.id,
        name=eingabe.name or _name_raten(bedingungen),
        aktiv=eingabe.aktiv,
        konto_id=eingabe.konto_id,
        verknuepfung="oder" if eingabe.verknuepfung == "oder" else "und",
        bedingungen_json=json.dumps(bedingungen, ensure_ascii=False),
        aktionen_json=json.dumps(aktionen, ensure_ascii=False),
        stopp=eingabe.stopp,
        # Neue Regeln hinten anstellen: Wer eine Kette gebaut hat, will sie
        # nicht durch die naechste Regel umgestossen bekommen.
        reihenfolge=max((r.reihenfolge for r in vorhandene), default=0) + 1,
    )
    db.add(zeile)
    db.commit()
    return _regel(zeile)


def _name_raten(bedingungen: list[dict]) -> str:
    """Ein Name, den man wiedererkennt — besser als „Regel 4"."""
    if not bedingungen:
        return "Regel"
    erste = bedingungen[0]
    return f"{erste.get('feld', '')}: {str(erste.get('wert', ''))[:40]}"


@router.put("/regeln/{regel_id}", response_model=RegelZeile)
def regel_aendern(
    regel_id: int, eingabe: RegelEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> RegelZeile:
    zeile = db.get(Regel, regel_id)
    if zeile is None or zeile.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    bedingungen = [b.model_dump() for b in eingabe.bedingungen]
    aktionen = [a.model_dump() for a in eingabe.aktionen]
    try:
        regeldienst.pruefen(bedingungen, aktionen)
    except regeldienst.RegelFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    zeile.name = eingabe.name or _name_raten(bedingungen)
    zeile.aktiv = eingabe.aktiv
    zeile.konto_id = eingabe.konto_id
    zeile.verknuepfung = "oder" if eingabe.verknuepfung == "oder" else "und"
    zeile.bedingungen_json = json.dumps(bedingungen, ensure_ascii=False)
    zeile.aktionen_json = json.dumps(aktionen, ensure_ascii=False)
    zeile.stopp = eingabe.stopp
    zeile.reihenfolge = eingabe.reihenfolge
    db.commit()
    return _regel(zeile)


@router.delete("/regeln/{regel_id}", status_code=status.HTTP_204_NO_CONTENT)
def regel_entfernen(regel_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    zeile = db.get(Regel, regel_id)
    if zeile is None or zeile.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    db.delete(zeile)
    db.commit()


class Nachlauf(BaseModel):
    ordner_id: int


@router.post("/regeln/anwenden")
def rueckwirkend(
    wunsch: Nachlauf, person: AngemeldeterBenutzer, db: DbSession
) -> dict[str, int]:
    """Die Regeln auf einen bestehenden Ordner anwenden.

    ⚠️ **Das ist der Grund, warum Regeln überhaupt benutzt werden.** Wer sie
    anlegt, hat schon dreitausend Mails liegen — eine Regel, die erst ab
    morgen gilt, räumt nichts auf.
    """
    ordner = db.get(Ordner, wunsch.ordner_id)
    if ordner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    from ..services import konten as kontendienst

    try:
        kontendienst.eines(db, person, ordner.konto_id)
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from fehler

    return regeldienst.rueckwirkend(db, person, ordner)


# --- Signaturen ------------------------------------------------------------- #


class SignaturZeile(BaseModel):
    id: int
    name: str
    konto_id: str
    html: str
    standard: bool


class SignaturEingabe(BaseModel):
    name: str = Field(max_length=200)
    html: str = ""
    konto_id: str = ""
    standard: bool = False


def _signatur(s: Signatur) -> SignaturZeile:
    return SignaturZeile(
        id=s.id, name=s.name, konto_id=s.konto_id, html=s.html, standard=s.standard
    )


@router.get("/signaturen", response_model=list[SignaturZeile])
def signaturen(person: AngemeldeterBenutzer, db: DbSession) -> list[SignaturZeile]:
    return [_signatur(s) for s in signaturdienst.meine(db, person)]


@router.post("/signaturen", response_model=SignaturZeile, status_code=status.HTTP_201_CREATED)
def signatur_anlegen(
    eingabe: SignaturEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> SignaturZeile:
    try:
        return _signatur(
            signaturdienst.anlegen(
                db, person, eingabe.name, eingabe.html, eingabe.konto_id, eingabe.standard
            )
        )
    except signaturdienst.SignaturFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler


@router.put("/signaturen/{signatur_id}", response_model=SignaturZeile)
def signatur_aendern(
    signatur_id: int, eingabe: SignaturEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> SignaturZeile:
    try:
        return _signatur(
            signaturdienst.aendern(db, person, signatur_id, **eingabe.model_dump())
        )
    except signaturdienst.SignaturFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler


@router.delete("/signaturen/{signatur_id}", status_code=status.HTTP_204_NO_CONTENT)
def signatur_entfernen(signatur_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        signaturdienst.entfernen(db, person, signatur_id)
    except signaturdienst.SignaturFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler


# --- Textvorlagen ----------------------------------------------------------- #
#
# ⚠️ **Fehler gehen als KENNUNG hinaus, nicht als Satz** — dasselbe Muster wie
# bei den Schlagworten. Die Oberflaeche uebersetzt ``textvorlage_name_vergeben``
# in beide Sprachen; ein deutscher Satz als ``detail`` bliebe auf Englisch
# deutsch.


class TextvorlagenZeile(BaseModel):
    id: int
    name: str
    inhalt_html: str
    reihenfolge: int


class TextvorlagenEingabe(BaseModel):
    name: str = Field(max_length=200)
    inhalt_html: str = ""


class TextvorlagenSortierung(BaseModel):
    ids: list[int]


def _vorlage(v: Textvorlage) -> TextvorlagenZeile:
    return TextvorlagenZeile(
        id=v.id, name=v.name, inhalt_html=v.inhalt_html, reihenfolge=v.reihenfolge
    )


def _vorlagen_fehler(fehler: vorlagendienst.TextvorlagenFehler) -> HTTPException:
    kennung = str(fehler)
    if kennung == "textvorlage_unbekannt":
        # Fremder Besitz und „gibt es nicht" antworten gleich.
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if kennung == "textvorlage_name_vergeben":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=kennung)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=kennung)


@router.get("/textvorlagen", response_model=list[TextvorlagenZeile])
def textvorlagen(person: AngemeldeterBenutzer, db: DbSession) -> list[TextvorlagenZeile]:
    return [_vorlage(v) for v in vorlagendienst.meine(db, person)]


@router.post(
    "/textvorlagen", response_model=TextvorlagenZeile, status_code=status.HTTP_201_CREATED
)
def textvorlage_anlegen(
    eingabe: TextvorlagenEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> TextvorlagenZeile:
    try:
        return _vorlage(vorlagendienst.anlegen(db, person, eingabe.name, eingabe.inhalt_html))
    except vorlagendienst.TextvorlagenFehler as fehler:
        raise _vorlagen_fehler(fehler) from fehler


@router.put("/textvorlagen/reihenfolge", status_code=status.HTTP_204_NO_CONTENT)
def textvorlagen_ordnen(
    wunsch: TextvorlagenSortierung, person: AngemeldeterBenutzer, db: DbSession
) -> None:
    """⚠️ **Vor ``/{vorlage_id}``**, sonst schluckt die Kennung dieses Wort.

    FastAPI nimmt die erste passende Route. Stuende sie darunter, landete
    „reihenfolge" als Kennung in ``vorlage_id`` und gaebe eine
    Pydantic-Meldung ueber eine kaputte Zahl — dasselbe Muster wie bei
    ``/api/aufgaben/reihenfolge``.
    """
    vorlagendienst.ordnen(db, person, wunsch.ids)


@router.put("/textvorlagen/{vorlage_id}", response_model=TextvorlagenZeile)
def textvorlage_aendern(
    vorlage_id: int, eingabe: TextvorlagenEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> TextvorlagenZeile:
    try:
        return _vorlage(
            vorlagendienst.aendern(db, person, vorlage_id, eingabe.name, eingabe.inhalt_html)
        )
    except vorlagendienst.TextvorlagenFehler as fehler:
        raise _vorlagen_fehler(fehler) from fehler


@router.delete("/textvorlagen/{vorlage_id}", status_code=status.HTTP_204_NO_CONTENT)
def textvorlage_entfernen(
    vorlage_id: int, person: AngemeldeterBenutzer, db: DbSession
) -> None:
    try:
        vorlagendienst.entfernen(db, person, vorlage_id)
    except vorlagendienst.TextvorlagenFehler as fehler:
        raise _vorlagen_fehler(fehler) from fehler
