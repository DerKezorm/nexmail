"""nextasks in der Aufgabenansicht (MAIL-2): Bereiche, Listen, Aufgaben, live.

⚠️ **Jede Absage von nextasks ist 409, nie 401**, wie bei nextime
(``routers/nextime.py``): Bei 401 meldet die Oberflaeche den Menschen aus
nexmail ab; ein abgelaufener Token in nextasks ist aber kein abgelaufenes
nexmail. Ausnahmen: 429 bleibt 429 (mit ``Retry-After``), „nicht da" ist 404,
„nicht erreichbar" 502, eine kaputte Eingabe 400.

⚠️ **Feldnamen deutsch** wie im Rest von nexmail; die Umrechnung aus
nextasks' englischen Namen steht in ``services/nextasksansicht.py``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import Meldung, MeldungHttp
from ..services import nextasks
from ..services import nextasksansicht as dienst

router = APIRouter(prefix="/api/nextasks", tags=["nextasks"])

#: Was als 404 hinausgeht.
NICHT_DA = ("nextasks_nicht_gefunden", "nextasks_liste_unbekannt")
#: Was als 502 hinausgeht: nextasks war nicht zu sprechen.
NETZ = (
    "nextasks_nicht_erreichbar",
    "nextasks_zeitueberschreitung",
    "nextasks_fehler",
    "nextasks_antwort_unlesbar",
    "nextasks_weiterleitung",
)
#: Was eine schlechte Eingabe von hier ist, keine Absage von nextasks.
EINGABE = (
    "nextasks_eingabe_ungueltig",
    "nextasks_sammlung_unbekannt",
    "nextasks_adresse_ungueltig",
    "nextasks_adresse_localhost",
    "nextasks_adresse_im_eigenen_netz",
)

_UHRZEIT = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


def http(f: Meldung) -> MeldungHttp:
    """Eine Meldung aus ``nextasks``/``nextasksansicht`` als Antwort."""
    if f.kennung == "nextasks_zu_viele_anfragen":
        return MeldungHttp(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f.kennung,
            f.werte,
            headers={"Retry-After": str(f.werte.get("sekunden", nextasks.PAUSE_OHNE_ANGABE))},
        )
    if f.kennung in NICHT_DA:
        return MeldungHttp(status.HTTP_404_NOT_FOUND, f.kennung, f.werte)
    if f.kennung in NETZ:
        return MeldungHttp(status.HTTP_502_BAD_GATEWAY, f.kennung, f.werte)
    if f.kennung in EINGABE:
        return MeldungHttp(status.HTTP_400_BAD_REQUEST, f.kennung, f.werte)
    return MeldungHttp(status.HTTP_409_CONFLICT, f.kennung, f.werte)


def _scheitern(db, person, f: Meldung) -> MeldungHttp:
    dienst.fehler_merken(db, person, f)
    return http(f)


# --- Formen --------------------------------------------------------------------- #


class Weitere(BaseModel):
    id: str
    name: str
    adresse: str


class Lage(BaseModel):
    verbunden: bool
    verbindung_id: str = ""
    name: str = ""
    #: nextasks nennt ``members`` in ``features``: Zustaendige waehlbar.
    mitglieder: bool = False
    #: Eine Kennung, wenn nextasks gerade nicht antwortet oder ablehnt.
    fehler: str = ""
    zeitzone: str = ""
    #: Weitere nextasks-Verbindungen aus der Zeit vor MAIL-2 (AC-18).
    weitere: list[Weitere] = Field(default_factory=list)


class Abschnitt(BaseModel):
    id: str
    name: str


class Liste(BaseModel):
    id: str
    name: str
    farbe: str
    symbol: str
    beschreibbar: bool
    offen: int
    gewaehlt: bool
    abschnitte: list[Abschnitt]


class Bereich(BaseModel):
    id: str
    name: str
    symbol: str
    ausgeblendet: bool
    beschreibbar: bool
    geteilt: bool
    listen: list[Liste]


class Listen(BaseModel):
    bereiche: list[Bereich]


class Auswahl(BaseModel):
    gewaehlt: bool


class Person(BaseModel):
    id: int
    #: ``display_name``, sonst ``name``; leer heisst: ehemaliges Mitglied.
    name: str


class Mail(BaseModel):
    aufgabe_id: int
    nachricht_id: int | None
    konto_id: str
    betreff: str
    von_name: str
    von_adresse: str
    verwaist: bool


class Teilaufgaben(BaseModel):
    offen: int
    gesamt: int


class Fernaufgabe(BaseModel):
    id: str
    liste_id: str
    liste_name: str
    bereich_id: str
    bereich_name: str
    abschnitt_id: str | None
    abschnitt_name: str
    eltern_id: str | None
    titel: str
    #: Markdown wie in nextasks. ⚠️ Als Text oder sicher gerendert zeigen (EC-8).
    notiz: str
    notiz_text: str
    url: str | None
    faellig_tag: str | None
    faellig_zeit: str | None
    #: Nur zum Anzeigen; setzen geht nur in nextasks.
    wiederholung: str | None
    markiert: bool
    prioritaet: int
    schlagworte: list[str]
    zustaendige: list[Person]
    erledigt: bool
    erledigt_am: str | None
    papierkorb: bool
    teilaufgaben: Teilaufgaben
    #: In nextasks oeffnen; leer ohne oeffentliche Adresse dort.
    link: str
    #: Die Liste ist in nextasks beschreibbar.
    beschreibbar: bool
    mail: Mail | None


class FernaufgabeVoll(Fernaufgabe):
    teilaufgaben_liste: list[Fernaufgabe]


class Seite(BaseModel):
    aufgaben: list[Fernaufgabe]
    weiter: str | None


class Neu(BaseModel):
    liste_id: str = Field(max_length=64)
    abschnitt_id: str | None = Field(default=None, max_length=64)
    eltern_id: str | None = Field(default=None, max_length=64)
    titel: str = Field(max_length=500)
    notiz: str | None = Field(default=None, max_length=nextasks.MAX_NOTIZ)
    faellig_tag: date | None = None
    faellig_zeit: str | None = Field(default=None, pattern=_UHRZEIT)
    prioritaet: int | None = Field(default=None, ge=0, le=3)
    markiert: bool | None = None
    zustaendige: list[int] | None = Field(default=None, max_length=50)
    #: Eigener Schluessel je Wunsch: derselbe zweimal (Doppelklick, EC-10) gibt
    #: die Aufgabe vom ersten Mal. Zusatz zum Vertrag, wahlweise.
    anfrage: str = Field(default="", max_length=64, pattern=r"^[0-9A-Za-z_-]*$")


class Aenderung(BaseModel):
    """⚠️ **Nur was gesetzt ist, geht hinaus** (``model_fields_set``, AC-4);
    ``null`` leert. Was nicht im Rumpf steht, bleibt in nextasks unberuehrt."""

    titel: str | None = Field(default=None, max_length=500)
    notiz: str | None = Field(default=None, max_length=nextasks.MAX_NOTIZ)
    faellig_tag: date | None = None
    faellig_zeit: str | None = Field(default=None, pattern=_UHRZEIT)
    prioritaet: int | None = Field(default=None, ge=0, le=3)
    markiert: bool | None = None
    schlagworte: list[str] | None = Field(default=None, max_length=100)
    zustaendige: list[int] | None = Field(default=None, max_length=50)
    liste_id: str | None = Field(default=None, max_length=64)
    abschnitt_id: str | None = Field(default=None, max_length=64)
    erledigt: bool | None = None
    #: Nur ``false``: aus dem Papierkorb zurueckholen. Hinein geht es ueber DELETE.
    papierkorb: bool | None = None


def _fern(a: dienst.Fernaufgabe) -> Fernaufgabe:
    return Fernaufgabe(
        **{k: v for k, v in a.__dict__.items() if k not in ("zustaendige", "mail", "teilaufgaben", "teilaufgaben_liste")},
        zustaendige=[Person(id=p.id, name=p.name) for p in a.zustaendige],
        teilaufgaben=Teilaufgaben(**a.teilaufgaben),
        mail=Mail(**a.mail.__dict__) if a.mail else None,
    )


def _voll(a: dienst.Fernaufgabe) -> FernaufgabeVoll:
    return FernaufgabeVoll(
        **_fern(a).model_dump(),
        teilaufgaben_liste=[_fern(t) for t in a.teilaufgaben_liste or []],
    )


# --- Lage und Listen ------------------------------------------------------------ #


@router.get("/lage", response_model=Lage)
def lage(person: AngemeldeterBenutzer, db: DbSession) -> Lage:
    """⚠️ **Immer 200**, auch ohne Verbindung oder wenn nextasks klemmt (EC-1)."""
    l = dienst.lage(db, person)
    return Lage(
        verbunden=l.verbunden,
        verbindung_id=l.verbindung_id,
        name=l.name,
        mitglieder=l.mitglieder,
        fehler=l.fehler,
        zeitzone=l.zeitzone,
        weitere=[Weitere(id=w.id, name=w.name, adresse=w.adresse) for w in l.weitere],
    )


@router.get("/listen", response_model=Listen)
def listen(person: AngemeldeterBenutzer, db: DbSession, alle: bool = False) -> Listen:
    """Die gewaehlten Listen in ihren Bereichen, mit ``alle`` auch die
    abgewaehlten (fuer die Auswahl in der Karte, AC-9)."""
    try:
        bereiche = dienst.listen(db, person, alle=alle)
    except Meldung as f:
        raise _scheitern(db, person, f) from f
    return Listen(
        bereiche=[
            Bereich(
                id=b.id,
                name=b.name,
                symbol=b.symbol,
                ausgeblendet=b.ausgeblendet,
                beschreibbar=b.beschreibbar,
                geteilt=b.geteilt,
                listen=[
                    Liste(
                        id=l.id,
                        name=l.name,
                        farbe=l.farbe,
                        symbol=l.symbol,
                        beschreibbar=l.beschreibbar,
                        offen=l.offen,
                        gewaehlt=l.gewaehlt,
                        abschnitte=[Abschnitt(id=s.id, name=s.name) for s in l.abschnitte],
                    )
                    for l in b.listen
                ],
            )
            for b in bereiche
        ]
    )


@router.patch("/listen/{liste_id}", status_code=status.HTTP_204_NO_CONTENT)
def auswahl(liste_id: str, eingabe: Auswahl, person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """⚠️ **Nur in nexmail** (AC-9): In nextasks bleibt die Liste, wie sie ist."""
    try:
        dienst.auswahl_setzen(db, person, liste_id, eingabe.gewaehlt)
    except Meldung as f:
        raise http(f) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Aufgaben (feste Woerter vor ``/{aufgabe_id}``) ----------------------------- #


@router.get("/aufgaben", response_model=Seite)
def aufgaben(
    person: AngemeldeterBenutzer,
    db: DbSession,
    liste: str | None = Query(default=None, max_length=64),
    sammlung: str | None = Query(default=None, max_length=20),
    suche: str = Query(default="", max_length=200),
    cursor: str = Query(default="", max_length=500),
) -> Seite:
    try:
        seite = dienst.aufgaben_lesen(
            db, person, liste=liste, sammlung=sammlung, suche=suche, cursor=cursor
        )
    except Meldung as f:
        raise _scheitern(db, person, f) from f
    return Seite(aufgaben=[_fern(a) for a in seite.aufgaben], weiter=seite.weiter)


@router.post("/aufgaben", response_model=Fernaufgabe, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Neu, person: AngemeldeterBenutzer, db: DbSession) -> Fernaufgabe:
    """Eine Aufgabe ohne Mail (AC-6), mit ``eltern_id`` eine Teilaufgabe (AC-4)."""
    try:
        a = dienst.anlegen(
            db,
            person,
            liste_id=eingabe.liste_id,
            titel=eingabe.titel,
            abschnitt_id=eingabe.abschnitt_id,
            eltern_id=eingabe.eltern_id,
            notiz=eingabe.notiz,
            faellig_tag=eingabe.faellig_tag,
            faellig_zeit=eingabe.faellig_zeit,
            prioritaet=eingabe.prioritaet,
            markiert=eingabe.markiert,
            zustaendige=eingabe.zustaendige,
            anfrage=eingabe.anfrage,
        )
    except Meldung as f:
        raise _scheitern(db, person, f) from f
    return _fern(a)


@router.get("/aufgaben/{aufgabe_id}", response_model=FernaufgabeVoll)
def eine(aufgabe_id: str, person: AngemeldeterBenutzer, db: DbSession) -> FernaufgabeVoll:
    try:
        return _voll(dienst.aufgabe_lesen(db, person, aufgabe_id))
    except Meldung as f:
        raise _scheitern(db, person, f) from f


@router.patch("/aufgaben/{aufgabe_id}", response_model=Fernaufgabe)
def aendern(
    aufgabe_id: str, eingabe: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> Fernaufgabe:
    """⚠️ **Nur die gesetzten Felder** (``model_fields_set``) gehen hinaus."""
    felder = {name: getattr(eingabe, name) for name in eingabe.model_fields_set}
    try:
        return _fern(dienst.aendern(db, person, aufgabe_id, felder))
    except Meldung as f:
        raise _scheitern(db, person, f) from f


@router.delete("/aufgaben/{aufgabe_id}", status_code=status.HTTP_204_NO_CONTENT)
def loeschen(aufgabe_id: str, person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """In nextasks' Papierkorb (AC-5), 30 Tage zurueckholbar dort."""
    try:
        dienst.loeschen(db, person, aufgabe_id)
    except Meldung as f:
        raise _scheitern(db, person, f) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/bereiche/{bereich_id}/mitglieder", response_model=list[Person])
def mitglieder(bereich_id: str, person: AngemeldeterBenutzer, db: DbSession) -> list[Person]:
    try:
        return [Person(id=p.id, name=p.name) for p in dienst.mitglieder(db, person, bereich_id)]
    except Meldung as f:
        raise _scheitern(db, person, f) from f
