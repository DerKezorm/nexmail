"""Adressbuch: auflisten, pflegen, einsammeln, vCard ein und aus."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import kontakte as kontaktdienst

logger = logging.getLogger("nexmail.kontakte")

router = APIRouter(prefix="/api/kontakte", tags=["kontakte"])

#: Eine vCard-Datei ist Text. Wer hier ein Abbild hochlädt, soll das früh und
#: klar gesagt bekommen, statt dass der Server es zu lesen versucht.
MAX_VCARD = 5 * 1024 * 1024


class Zeile(BaseModel):
    id: int
    name: str
    adresse: str
    firma: str
    telefon: str
    notiz: str
    quelle: str
    verwendet: int


class Eingabe(BaseModel):
    adresse: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=320)
    firma: str = Field(default="", max_length=320)
    telefon: str = Field(default="", max_length=120)
    notiz: str = Field(default="", max_length=5000)


class Aenderung(BaseModel):
    adresse: str | None = Field(default=None, max_length=320)
    name: str | None = Field(default=None, max_length=320)
    firma: str | None = Field(default=None, max_length=320)
    telefon: str | None = Field(default=None, max_length=120)
    notiz: str | None = Field(default=None, max_length=5000)


def _zeile(k) -> Zeile:
    return Zeile(
        id=k.id,
        name=k.name,
        adresse=k.adresse,
        firma=k.firma,
        telefon=k.telefon,
        notiz=k.notiz,
        quelle=k.quelle,
        verwendet=k.verwendet,
    )


@router.get("", response_model=list[Zeile])
def liste(person: AngemeldeterBenutzer, db: DbSession, suche: str = "") -> list[Zeile]:
    return [_zeile(k) for k in kontaktdienst.meine(db, person, suche)]


@router.get("/vorschlag", response_model=list[Zeile])
def vorschlag(anfang: str, person: AngemeldeterBenutzer, db: DbSession) -> list[Zeile]:
    """Für die Autovervollständigung im Verfassen-Fenster."""
    return [_zeile(k) for k in kontaktdienst.vorschlagen(db, person, anfang)]


# --- Gruppen ---------------------------------------------------------------- #
# Ein Verteiler ist ein Eingabehelfer beim Adressieren, kein Mailbegriff:
# In der Mail stehen nur die Einzeladressen der Mitglieder.


class GruppenZeile(BaseModel):
    id: int
    name: str
    #: Die Zahl fuer die Liste und die Rueckfrage vor dem Loeschen.
    mitglieder: int
    #: Fuer die Mehrfachauswahl beim Bearbeiten.
    mitglied_ids: list[int]
    #: Fuer das Adressfeld beim Verfassen - dort gibt es das Adressbuch nicht.
    adressen: list[str]


class GruppenEingabe(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MitgliederEingabe(BaseModel):
    kontakt_ids: list[int] = Field(max_length=10000)


def _gruppenzeile(db, person, gruppe_id: int) -> GruppenZeile:
    for g in kontaktdienst.gruppen(db, person):
        if g["id"] == gruppe_id:
            return GruppenZeile(**g)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diese Gruppe gibt es nicht.")


@router.get("/gruppen", response_model=list[GruppenZeile])
def gruppen(person: AngemeldeterBenutzer, db: DbSession) -> list[GruppenZeile]:
    return [GruppenZeile(**g) for g in kontaktdienst.gruppen(db, person)]


@router.post("/gruppen", response_model=GruppenZeile, status_code=status.HTTP_201_CREATED)
def gruppe_anlegen(
    eingabe: GruppenEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> GruppenZeile:
    try:
        gruppe = kontaktdienst.gruppe_anlegen(db, person, eingabe.name)
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return _gruppenzeile(db, person, gruppe.id)


@router.patch("/gruppen/{gruppe_id}", response_model=GruppenZeile)
def gruppe_umbenennen(
    gruppe_id: int, eingabe: GruppenEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> GruppenZeile:
    try:
        kontaktdienst.gruppe_umbenennen(db, person, gruppe_id, eingabe.name)
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return _gruppenzeile(db, person, gruppe_id)


@router.delete("/gruppen/{gruppe_id}", status_code=status.HTTP_204_NO_CONTENT)
def gruppe_entfernen(gruppe_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        kontaktdienst.gruppe_entfernen(db, person, gruppe_id)
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler


@router.put("/gruppen/{gruppe_id}/mitglieder", response_model=GruppenZeile)
def mitglieder_setzen(
    gruppe_id: int, eingabe: MitgliederEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> GruppenZeile:
    try:
        kontaktdienst.mitglieder_setzen(db, person, gruppe_id, eingabe.kontakt_ids)
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return _gruppenzeile(db, person, gruppe_id)


@router.post("", response_model=Zeile, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession) -> Zeile:
    try:
        return _zeile(
            kontaktdienst.anlegen(
                db,
                person,
                eingabe.adresse,
                eingabe.name,
                eingabe.firma,
                eingabe.telefon,
                eingabe.notiz,
            )
        )
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler


@router.patch("/{kontakt_id}", response_model=Zeile)
def aendern(
    kontakt_id: int, wunsch: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> Zeile:
    try:
        return _zeile(
            kontaktdienst.aendern(db, person, kontakt_id, **wunsch.model_dump(exclude_none=True))
        )
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler


# ⚠️ **Diese Regel muss vor ``/{kontakt_id}`` stehen.** FastAPI probiert die
# Regeln in der Reihenfolge ihrer Erklärung. Steht die Zahlen-Regel zuerst,
# landet „gesammelte" dort, scheitert an der Zahl und gibt 422 zurück - die
# Adresse hier würde nie erreicht. Der Fehler sähe nach kaputter Eingabe aus.
@router.delete("/gesammelte", status_code=status.HTTP_200_OK)
def gesammelte_entfernen(person: AngemeldeterBenutzer, db: DbSession) -> dict[str, int]:
    """Alles Aufgeschnappte in einem Zug loswerden."""
    return {"entfernt": kontaktdienst.gesammelte_entfernen(db, person)}


@router.delete("/{kontakt_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(kontakt_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        kontaktdienst.entfernen(db, person, kontakt_id)
    except kontaktdienst.KontaktFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler


@router.post("/einsammeln")
def einsammeln(person: AngemeldeterBenutzer, db: DbSession) -> dict[str, int]:
    """Empfänger aus „Gesendet" übernehmen."""
    return kontaktdienst.einsammeln(db, person)


@router.get("/vcard")
def ausfuehren(person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """Das ganze Adressbuch als vCard-Datei."""
    inhalt = kontaktdienst.als_vcard(kontaktdienst.meine(db, person))
    return Response(
        content=inhalt.encode("utf-8"),
        media_type="text/vcard; charset=utf-8",
        headers={"content-disposition": 'attachment; filename="nexmail-kontakte.vcf"'},
    )


@router.post("/vcard")
async def einlesen(
    datei: UploadFile, person: AngemeldeterBenutzer, db: DbSession
) -> dict[str, int]:
    roh = await datei.read(MAX_VCARD + 1)
    if len(roh) > MAX_VCARD:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Die Datei ist größer als 5 MB — das ist keine vCard.",
        )
    # ⚠️ **Nicht streng dekodieren.** vCards aus Outlook kommen oft in
    # Windows-1252 statt UTF-8, und ein Umlaut darf nicht den ganzen Import
    # verhindern. Lieber ein schiefes Zeichen als 400 verlorene Kontakte.
    try:
        inhalt = roh.decode("utf-8")
    except UnicodeDecodeError:
        inhalt = roh.decode("cp1252", errors="replace")
        logger.info("A vCard was not UTF-8; read as Windows-1252 instead.")
    return kontaktdienst.aus_vcard(db, person, inhalt)
