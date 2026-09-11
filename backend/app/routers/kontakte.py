"""Adressbuch: auflisten, pflegen, einsammeln, vCard ein und aus."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import kontakte as kontaktdienst
from ..meldung import MeldungHttp

logger = logging.getLogger("nexmail.kontakte")

router = APIRouter(prefix="/api/kontakte", tags=["kontakte"])

#: Eine vCard-Datei ist Text. Wer hier ein Abbild hochlädt, soll das früh und
#: klar gesagt bekommen, statt dass der Server es zu lesen versucht.
MAX_VCARD = 5 * 1024 * 1024


class Nummer(BaseModel):
    nummer: str
    #: Die Typen der Karte, klein und mit Komma: ``cell,voice,pref``.
    typen: str = ""
    #: Eine eigene Beschriftung („Mutter") oder Apples Wort („Mobile").
    beschriftung: str = ""


class Adresse(BaseModel):
    adresse: str
    typen: str = ""
    beschriftung: str = ""


class Zeile(BaseModel):
    id: int
    name: str
    adresse: str
    firma: str
    telefon: str
    notiz: str
    quelle: str
    verwendet: int
    #: In welchem Buch der Eintrag liegt.
    adressbuch_id: str | None = None
    #: Alle Nummern und Adressen der Karte, **nur bei Kontakten aus
    #: verbundenen Büchern**: Das Modell kennt eine Nummer, die Karte viele.
    #: Ein lokaler Kontakt trägt seine Felder; seine Rohkarte könnte hinter
    #: einer Änderung von Hand zurückliegen. Seit Lieferung 2 pflegt der
    #: Zeilen-Editor die Rohkarte bei jeder Änderung mit, deshalb stimmen
    #: beide auch nach dem Bearbeiten überein.
    nummern: list[Nummer] = Field(default_factory=list)
    adressen: list[Adresse] = Field(default_factory=list)


def _verbundene(db, person) -> set[str]:
    from ..services import adressbuecher

    return {b.id for b in adressbuecher.meine(db, person) if b.art}


class Eingabe(BaseModel):
    #: Leer heisst: kein Postfach. Der Dienst verlangt dann wenigstens Name,
    #: Nummer oder Firma.
    adresse: str = Field(default="", max_length=320)
    name: str = Field(default="", max_length=320)
    firma: str = Field(default="", max_length=320)
    telefon: str = Field(default="", max_length=120)
    notiz: str = Field(default="", max_length=5000)
    #: In welches Buch. Leer heisst: das lokale. Ein verbundenes Buch schickt
    #: die Karte zuerst zum Anbieter.
    adressbuch_id: str | None = Field(default=None, max_length=32)


class Aenderung(BaseModel):
    adresse: str | None = Field(default=None, max_length=320)
    name: str | None = Field(default=None, max_length=320)
    firma: str | None = Field(default=None, max_length=320)
    telefon: str | None = Field(default=None, max_length=120)
    notiz: str | None = Field(default=None, max_length=5000)
    #: ⚠️ **Die Antwort auf eine Rückfrage, kein Schalter.** „Meine Fassung
    #: gewinnt" im Konfliktfenster; ohne die Frage davor wäre es das
    #: stillschweigende Überbügeln, das der Abgleich ausdrücklich nicht tut.
    erzwingen: bool = False


class Umzug(BaseModel):
    adressbuch_id: str = Field(min_length=1, max_length=32)


class Konfliktbild(BaseModel):
    """Was auf der anderen Seite steht, zum Ansehen, nicht zum Übernehmen."""

    #: Falsch heisst: Dort liegt nichts mehr. Jemand hat die Karte gelöscht.
    vorhanden: bool
    fremd: Zeile | None = None


def _zeile(k, verbundene: set[str] | frozenset[str] = frozenset()) -> Zeile:
    verbunden = k.adressbuch_id in verbundene
    daten = (
        kontaktdienst.kontaktdaten_aus_vcard(k.roh)
        if verbunden and k.roh
        else {"nummern": [], "adressen": []}
    )
    return Zeile(
        id=k.id,
        name=k.name,
        adresse=k.adresse,
        firma=k.firma,
        telefon=k.telefon,
        notiz=k.notiz,
        quelle=k.quelle,
        verwendet=k.verwendet,
        adressbuch_id=k.adressbuch_id,
        nummern=[Nummer(**n) for n in daten["nummern"]],
        adressen=[Adresse(**a) for a in daten["adressen"]],
    )


@router.get("", response_model=list[Zeile])
def liste(person: AngemeldeterBenutzer, db: DbSession, suche: str = "") -> list[Zeile]:
    verbundene = _verbundene(db, person)
    return [_zeile(k, verbundene) for k in kontaktdienst.meine(db, person, suche)]


@router.get("/vorschlag", response_model=list[Zeile])
def vorschlag(anfang: str, person: AngemeldeterBenutzer, db: DbSession) -> list[Zeile]:
    """Für die Autovervollständigung im Verfassen-Fenster."""
    verbundene = _verbundene(db, person)
    return [_zeile(k, verbundene) for k in kontaktdienst.vorschlagen(db, person, anfang)]


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
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="gruppe_unbekannt")


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
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return _gruppenzeile(db, person, gruppe.id)


@router.patch("/gruppen/{gruppe_id}", response_model=GruppenZeile)
def gruppe_umbenennen(
    gruppe_id: int, eingabe: GruppenEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> GruppenZeile:
    try:
        kontaktdienst.gruppe_umbenennen(db, person, gruppe_id, eingabe.name)
    except kontaktdienst.KontaktFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return _gruppenzeile(db, person, gruppe_id)


@router.delete("/gruppen/{gruppe_id}", status_code=status.HTTP_204_NO_CONTENT)
def gruppe_entfernen(gruppe_id: int, person: AngemeldeterBenutzer, db: DbSession) -> None:
    try:
        kontaktdienst.gruppe_entfernen(db, person, gruppe_id)
    except kontaktdienst.KontaktFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler


@router.put("/gruppen/{gruppe_id}/mitglieder", response_model=GruppenZeile)
def mitglieder_setzen(
    gruppe_id: int, eingabe: MitgliederEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> GruppenZeile:
    try:
        kontaktdienst.mitglieder_setzen(db, person, gruppe_id, eingabe.kontakt_ids)
    except kontaktdienst.KontaktFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
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
                adressbuch_id=eingabe.adressbuch_id,
            ),
            _verbundene(db, person),
        )
    except kontaktdienst.KontaktFehler as fehler:
        raise MeldungHttp.aus(fehler, _kontaktfehler_code(fehler)) from fehler


@router.patch("/{kontakt_id}", response_model=Zeile)
def aendern(
    kontakt_id: int, wunsch: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> Zeile:
    felder = wunsch.model_dump(exclude_none=True)
    erzwingen = bool(felder.pop("erzwingen", False))
    try:
        return _zeile(
            kontaktdienst.aendern(db, person, kontakt_id, erzwingen=erzwingen, **felder),
            _verbundene(db, person),
        )
    except kontaktdienst.KontaktFehler as fehler:
        raise MeldungHttp.aus(fehler, _kontaktfehler_code(fehler)) from fehler


def _kontaktfehler_code(fehler: kontaktdienst.KontaktFehler) -> int:
    # „Gibt es nicht" ist ein 404; „darf nicht" und „passt nicht" sind 400.
    # Ein Konflikt ist ein 409, wie beim Kalender; was der Anbieter nicht
    # annimmt oder nicht beantwortet, ist ein 502 — die Ursache liegt drüben.
    if fehler.kennung in ("eintrag_unbekannt", "kontakt_nicht_gefunden", "adressbuch_nicht_gefunden"):
        return status.HTTP_404_NOT_FOUND
    if fehler.kennung == "kontakt_konflikt":
        return status.HTTP_409_CONFLICT
    if fehler.kennung.startswith(("carddav_", "caldav_")):
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_400_BAD_REQUEST


# --- Konflikt und Umzug (Lieferung 2) ---------------------------------------- #


def _meiner(db, person, kontakt_id: int):
    from ..models import Kontakt

    eintrag = db.get(Kontakt, kontakt_id)
    if eintrag is None or eintrag.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kontakt_nicht_gefunden")
    return eintrag


@router.get("/{kontakt_id}/konflikt", response_model=Konfliktbild)
def konflikt_ansehen(
    kontakt_id: int, person: AngemeldeterBenutzer, db: DbSession
) -> Konfliktbild:
    """Die Fassung des Anbieters holen, ohne etwas zu ändern.

    ⚠️ **Eine Attrappe, keine Zeile in der Datenbank.** Angesehen wird die
    fremde Fassung; gespeichert ist sie erst, wenn jemand sie wählt.
    """
    from ..services import adressbuchabgleich

    eintrag = _meiner(db, person, kontakt_id)
    try:
        karte = adressbuchabgleich.fremde_fassung(db, eintrag)
    except Exception as fehler:  # noqa: BLE001
        # ⚠️ Ein Netzfehler beim Nachsehen darf nicht wie „dort ist nichts"
        # aussehen — das wäre die Aufforderung zu löschen.
        logger.info("The other version of a contact could not be fetched: %s", type(fehler).__name__)
        raise MeldungHttp(status.HTTP_502_BAD_GATEWAY, "konflikt_nicht_abrufbar", {}) from fehler
    if karte is None:
        return Konfliktbild(vorhanden=False)
    felder = kontaktdienst.felder_aus_vcard(karte.roh)
    daten = kontaktdienst.kontaktdaten_aus_vcard(karte.roh)
    return Konfliktbild(
        vorhanden=True,
        fremd=Zeile(
            id=eintrag.id,
            name=felder.get("name", ""),
            adresse=felder.get("adresse", ""),
            firma=felder.get("firma", ""),
            telefon=felder.get("telefon", ""),
            notiz=felder.get("notiz", ""),
            quelle=eintrag.quelle,
            verwendet=eintrag.verwendet,
            adressbuch_id=eintrag.adressbuch_id,
            nummern=[Nummer(**n) for n in daten["nummern"]],
            adressen=[Adresse(**a) for a in daten["adressen"]],
        ),
    )


@router.post("/{kontakt_id}/konflikt", response_model=Zeile)
def konflikt_aufloesen(kontakt_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Zeile:
    """Die fremde Fassung übernehmen; die eigene Änderung fällt weg.

    ⚠️ **Der andere Ausgang braucht keine eigene Adresse.** „Meine Fassung
    gewinnt" ist dasselbe Ändern wie vorher, nur mit ``erzwingen``.
    """
    from ..services import adressbuchabgleich

    eintrag = _meiner(db, person, kontakt_id)
    try:
        geklappt = adressbuchabgleich.fremde_fassung_uebernehmen(db, eintrag)
    except Exception as fehler:  # noqa: BLE001
        logger.info("The other version of a contact could not be taken: %s", type(fehler).__name__)
        raise MeldungHttp(status.HTTP_502_BAD_GATEWAY, "konflikt_nicht_abrufbar", {}) from fehler
    if not geklappt:
        raise MeldungHttp(status.HTTP_409_CONFLICT, "kontakt_drueben_geloescht", {})
    return _zeile(eintrag, _verbundene(db, person))


@router.post("/{kontakt_id}/verschieben", response_model=Zeile)
def verschieben(
    kontakt_id: int, umzug: Umzug, person: AngemeldeterBenutzer, db: DbSession
) -> Zeile:
    """Einen Kontakt in ein anderes Buch legen — der Weg für Aufgeschnapptes
    und für alles, was drüben stehen soll."""
    try:
        eintrag = kontaktdienst.verschieben(db, person, kontakt_id, umzug.adressbuch_id)
    except kontaktdienst.KontaktFehler as fehler:
        raise MeldungHttp.aus(fehler, _kontaktfehler_code(fehler)) from fehler
    return _zeile(eintrag, _verbundene(db, person))


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
        raise MeldungHttp.aus(fehler, _kontaktfehler_code(fehler)) from fehler


@router.post("/einsammeln")
def einsammeln(person: AngemeldeterBenutzer, db: DbSession) -> dict[str, int]:
    """Empfänger aus „Gesendet" übernehmen."""
    return kontaktdienst.einsammeln(db, person)


@router.get("/vcard")
def ausfuehren(person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """Das ganze Adressbuch als vCard-Datei."""
    inhalt = kontaktdienst.als_vcard(kontaktdienst.meine(db, person), _verbundene(db, person))
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
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="vcard_zu_gross",
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
