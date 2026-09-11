"""Adressbuch: auflisten, pflegen, einsammeln, vCard ein und aus."""

from __future__ import annotations

import logging

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import adressbuecher, kontaktvorgang
from ..services import kontakte as kontaktdienst
from ..services import vcard
from ..meldung import MeldungHttp

logger = logging.getLogger("nexmail.kontakte")

router = APIRouter(prefix="/api/kontakte", tags=["kontakte"])

#: Eine vCard-Datei ist Text. Wer hier ein Abbild hochlädt, soll das früh und
#: klar gesagt bekommen, statt dass der Server es zu lesen versucht.
MAX_VCARD = 5 * 1024 * 1024


class Nummer(BaseModel):
    """Eine Nummer der Liste. ``art`` ist eine der bekannten Sorten (cell,
    home, work, main, fax, pager, other), ``beschriftung`` eine eigene
    („Zweitbüro"), ``bevorzugt`` der Stern: die Nummer, die die Liste zeigt."""

    nummer: str = Field(max_length=120)
    art: str = Field(default="", max_length=16)
    beschriftung: str = Field(default="", max_length=80)
    bevorzugt: bool = False


class Adresse(BaseModel):
    adresse: str = Field(max_length=320)
    art: str = Field(default="", max_length=16)
    beschriftung: str = Field(default="", max_length=80)
    bevorzugt: bool = False


class Anschrift(BaseModel):
    """Die sieben Teile einer vCard-Anschrift. Die Maske zeigt Strasse, PLZ,
    Ort und Land; Region, Postfach und Zusatz reisen mit, damit eine Karte
    beim Speichern nichts davon verliert."""

    strasse: str = Field(default="", max_length=200)
    plz: str = Field(default="", max_length=40)
    ort: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)
    land: str = Field(default="", max_length=120)
    postfach: str = Field(default="", max_length=120)
    zusatz: str = Field(default="", max_length=200)
    art: str = Field(default="", max_length=16)
    beschriftung: str = Field(default="", max_length=80)
    bevorzugt: bool = False


class Weiteres(BaseModel):
    """Was die Karte ausserdem traegt und nexmail zeigt, aber nicht aendert:
    Social-Profile, Messenger, weitere Daten, verwandte Namen. Nur Apple
    kennt diese Zeilen; sie bleiben beim Speichern stehen."""

    art: str
    beschriftung: str = ""
    text: str = ""


class Zeile(BaseModel):
    id: int
    #: Der Anzeigename, abgeleitet: „Vorname Nachname", sonst die Firma.
    name: str
    vorname: str = ""
    nachname: str = ""
    spitzname: str = ""
    #: Die bevorzugte Adresse und Nummer, abgeleitet aus den Listen.
    adresse: str
    telefon: str
    firma: str
    abteilung: str = ""
    titel: str = ""
    geburtstag: str = ""
    webseite: str = ""
    notiz: str
    quelle: str
    verwendet: int
    #: In welchem Buch der Eintrag liegt.
    adressbuch_id: str | None = None
    #: Die Listen, bei jedem Kontakt: Seit dem Felder-Schritt (11.09.2026)
    #: pflegt nexmail sie selbst, und der Zeilen-Editor bringt sie in die
    #: Karte. Vorher standen hier nur die gelesenen Nummern verbundener
    #: Kontakte.
    nummern: list[Nummer] = Field(default_factory=list)
    adressen: list[Adresse] = Field(default_factory=list)
    anschriften: list[Anschrift] = Field(default_factory=list)
    #: Nur bei Kontakten aus verbundenen Büchern, aus der Rohkarte gelesen.
    weiteres: list[Weiteres] = Field(default_factory=list)
    #: Die Karte traegt ein eingebettetes Foto; die Oberflaeche holt es ueber
    #: ``GET …/{id}/foto``. Nicht in der Zeile selbst: 185 Karten mit je
    #: 100 kB Base64 waeren eine Listenantwort von 18 MB.
    hat_foto: bool = False


def _verbundene(db, person) -> set[str]:
    from ..services import adressbuecher

    return {b.id for b in adressbuecher.meine(db, person) if b.art}


class Felder(BaseModel):
    """Was ein Mensch an einem Kontakt eingibt. ``name``, ``adresse`` und
    ``telefon`` einzeln sind der alte Weg: Ein Name wird geteilt, eine
    einzelne Nummer oder Adresse wird zum Eintrag mit Stern."""

    vorname: str | None = Field(default=None, max_length=160)
    nachname: str | None = Field(default=None, max_length=160)
    spitzname: str | None = Field(default=None, max_length=160)
    firma: str | None = Field(default=None, max_length=320)
    abteilung: str | None = Field(default=None, max_length=160)
    titel: str | None = Field(default=None, max_length=160)
    geburtstag: str | None = Field(default=None, max_length=32)
    webseite: str | None = Field(default=None, max_length=320)
    notiz: str | None = Field(default=None, max_length=5000)
    nummern: list[Nummer] | None = Field(default=None, max_length=50)
    adressen: list[Adresse] | None = Field(default=None, max_length=50)
    anschriften: list[Anschrift] | None = Field(default=None, max_length=50)
    adresse: str | None = Field(default=None, max_length=320)
    name: str | None = Field(default=None, max_length=320)
    telefon: str | None = Field(default=None, max_length=120)


class Eingabe(Felder):
    #: In welches Buch. Leer heisst: das lokale. Ein verbundenes Buch schickt
    #: die Karte zuerst zum Anbieter.
    adressbuch_id: str | None = Field(default=None, max_length=32)


class Aenderung(Felder):
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


def _zeile_aus_felder(k, felder: dict, weiteres: list[dict]) -> Zeile:
    return Zeile(
        id=k.id,
        name=felder.get("name", ""),
        vorname=felder.get("vorname", ""),
        nachname=felder.get("nachname", ""),
        spitzname=felder.get("spitzname", ""),
        adresse=felder.get("adresse", ""),
        telefon=felder.get("telefon", ""),
        firma=felder.get("firma", ""),
        abteilung=felder.get("abteilung", ""),
        titel=felder.get("titel", ""),
        geburtstag=felder.get("geburtstag", ""),
        webseite=felder.get("webseite", ""),
        notiz=felder.get("notiz", ""),
        quelle=k.quelle,
        verwendet=k.verwendet,
        adressbuch_id=k.adressbuch_id,
        nummern=[Nummer.model_validate(n) for n in felder.get("nummern", [])],
        adressen=[Adresse.model_validate(a) for a in felder.get("adressen", [])],
        anschriften=[Anschrift.model_validate(a) for a in felder.get("anschriften", [])],
        weiteres=[Weiteres.model_validate(w) for w in weiteres],
        hat_foto=vcard.hat_foto(k.roh),
    )


def _zeile(k, verbundene: set[str] | frozenset[str] = frozenset()) -> Zeile:
    felder = kontaktdienst.felder_der_zeile(k)
    felder["name"] = k.name
    weiteres = (
        kontaktdienst.felder_aus_vcard(k.roh)["weiteres"]
        if k.roh and k.adressbuch_id in verbundene
        else []
    )
    return _zeile_aus_felder(k, felder, weiteres)


@router.get("", response_model=list[Zeile])
def liste(person: AngemeldeterBenutzer, db: DbSession, suche: str = "") -> list[Zeile]:
    verbundene = _verbundene(db, person)
    return [_zeile(k, verbundene) for k in kontaktdienst.meine(db, person, suche)]


@router.get("/vorschlag", response_model=list[Zeile])
def vorschlag(anfang: str, person: AngemeldeterBenutzer, db: DbSession) -> list[Zeile]:
    """Für die Autovervollständigung im Verfassen-Fenster — je Adresse eine
    Zeile, denn ein Kontakt hat seit dem Felder-Schritt mehrere."""
    verbundene = _verbundene(db, person)
    return [
        _zeile(k, verbundene).model_copy(update={"adresse": adresse})
        for k, adresse in kontaktdienst.vorschlagen(db, person, anfang)
    ]


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
    felder = eingabe.model_dump(exclude_none=True, exclude={"adressbuch_id"})
    try:
        return _zeile(
            kontaktdienst.anlegen(db, person, adressbuch_id=eingabe.adressbuch_id, **felder),
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
    gelesen = kontaktdienst.felder_aus_vcard(karte.roh)
    felder = kontaktdienst.felder_pruefen_lose(gelesen)
    return Konfliktbild(vorhanden=True, fremd=_zeile_aus_felder(eintrag, felder, gelesen["weiteres"]))


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


# --- vCard in ein verbundenes Buch: ein Vorgang mit Fortschritt --------------- #
# ⚠️ Diese Regeln stehen VOR ``/{kontakt_id}/…``: FastAPI nimmt die erste
# passende, und ``/vcard/vorgang`` saehe sonst aus wie eine kaputte Zahl.


class Vorgangsstand(BaseModel):
    id: str
    dateiname: str
    laeuft: bool
    #: Leer heisst: lief (oder laeuft noch). Sonst die Kennung, an der der
    #: ganze Vorgang scheiterte.
    fehler_satz: str
    gesamt: int
    gelesen: int
    neu: int
    uebersprungen: int
    fehler_gesamt: int
    fehler: list[str]
    abgebrochen: bool


class Einleseantwort(BaseModel):
    """Was ``POST /vcard`` zurueckgibt: ins lokale Buch die Zahlen sofort, in ein
    verbundenes den Vorgang, dessen Stand die Oberflaeche abfragt."""

    neu: int = 0
    ergaenzt: int = 0
    vorgang: Vorgangsstand | None = None


def _vorgangsstand(v: kontaktvorgang.Vorgang) -> Vorgangsstand:
    return Vorgangsstand(
        id=v.id, dateiname=v.dateiname, laeuft=v.laeuft, fehler_satz=v.fehler_satz,
        gesamt=v.gesamt, gelesen=v.gelesen, neu=v.neu, uebersprungen=v.uebersprungen,
        fehler_gesamt=v.fehler_gesamt, fehler=list(v.fehler), abgebrochen=v.abgebrochen,
    )


@router.get("/vcard/vorgang", response_model=Vorgangsstand | None)
def einlesen_laufend(person: AngemeldeterBenutzer) -> Vorgangsstand | None:
    """Der gerade laufende Import, falls es einen gibt — damit ein Neuladen der
    Seite den Vorgang nicht verliert."""
    gefunden = kontaktvorgang.laeuft_schon(person.id)
    return _vorgangsstand(gefunden) if gefunden else None


@router.get("/vcard/vorgang/{kennung}", response_model=Vorgangsstand)
def einlesen_stand(kennung: str, person: AngemeldeterBenutzer) -> Vorgangsstand:
    gefunden = kontaktvorgang.stand(kennung, person.id)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vorgang_unbekannt")
    return _vorgangsstand(gefunden)


@router.post("/vcard/vorgang/{kennung}/abbrechen", response_model=Vorgangsstand)
def einlesen_abbrechen(kennung: str, person: AngemeldeterBenutzer) -> Vorgangsstand:
    """Anhalten. ⚠️ Was schon angelegt wurde, bleibt — beim Anbieter und hier."""
    gefunden = kontaktvorgang.stand(kennung, person.id)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vorgang_unbekannt")
    kontaktvorgang.abbrechen(kennung, person.id)
    return _vorgangsstand(gefunden)


@router.get("/{kontakt_id}/foto")
def foto(kontakt_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """Das eingebettete Foto der Karte, als Bild. Nur zeigen: Beim Schreiben
    bleibt die ``PHOTO``-Zeile ohnehin stehen, wie jede Zeile, die nexmail nicht
    pflegt."""
    eintrag = _meiner(db, person, kontakt_id)
    bild = vcard.foto_lesen(eintrag.roh)
    if bild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="kontakt_kein_foto")
    daten, typ = bild
    # ⚠️ Privat und kurz: Das Bild gehoert zur Sitzung, nicht in einen
    # geteilten Zwischenspeicher; und es aendert sich mit der Karte.
    return Response(content=daten, media_type=typ, headers={"cache-control": "private, max-age=300"})


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


@router.post("/vcard", response_model=Einleseantwort)
async def einlesen(
    datei: UploadFile,
    person: AngemeldeterBenutzer,
    db: DbSession,
    adressbuch_id: Annotated[str | None, Form()] = None,
) -> Einleseantwort:
    """Eine vCard-Datei einlesen: ins lokale Buch sofort, in ein verbundenes als
    Vorgang mit Fortschritt (jede Karte geht einzeln zum Anbieter)."""
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
    if adressbuch_id:
        try:
            buch = adressbuecher.meines(db, person, adressbuch_id)
        except adressbuecher.BuchFehler as fehler:
            raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler
        if buch.art:
            if kontaktvorgang.laeuft_schon(person.id) is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="einlesen_laeuft_schon")
            vorgang = kontaktvorgang.vorgang_starten(
                person.id, buch.id, datei.filename or "kontakte.vcf", inhalt
            )
            return Einleseantwort(vorgang=_vorgangsstand(vorgang))
    zahlen = kontaktdienst.aus_vcard(db, person, inhalt)
    return Einleseantwort(neu=zahlen["neu"], ergaenzt=zahlen["ergaenzt"])
