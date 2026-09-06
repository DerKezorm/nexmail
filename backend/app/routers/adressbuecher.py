"""Die Adressen der Adressbücher: verbinden, abgleichen, trennen. **Beta.**

⚠️ **Lieferung 1 liest nur.** Keine dieser Adressen schreibt oder löscht beim
Anbieter. ``DELETE`` trennt das Buch hier und lässt es drüben stehen; wer ein
verbundenes Buch entfernt, verliert nichts als nexmails Kopie. Die
Oberfläche sagt das vor der Frage, und ein Test hält fest, dass der
Doppelgänger nie einen anderen Befehl als ``PROPFIND`` und ``REPORT`` sieht.

⚠️ **``/pruefen``, ``/verbinden`` und ``/abgleichen`` stehen vor
``/{buch_id}``.** FastAPI nimmt die erste passende Regel; dahinter läse es
„pruefen" als Kennung eines Buches.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import MeldungHttp
from ..models import Kontakt
from ..services import adressbuchabgleich, adressbuecher, caldav, carddav
from .kalender import _token  # noqa: PLC2701  (dieselbe Zustimmung, dasselbe Token)

logger = logging.getLogger("nexmail.adressbuecher")

router = APIRouter(prefix="/api/adressbuecher", tags=["adressbuecher"])

_VERBINDUNGSFEHLER = (
    carddav.CarddavFehler,
    caldav.CaldavFehler,
    adressbuchabgleich.AbgleichFehler,
)


# --- Formen --------------------------------------------------------------- #


class BuchZeile(BaseModel):
    id: str
    name: str
    farbe: int
    sichtbar: bool
    ist_lokal: bool
    #: "" (lebt nur hier) | "carddav"
    art: str
    herkunft: str
    letzter_fehler: str
    #: Wie viele Kontakte darin liegen, für die Rückfrage vor dem Trennen.
    kontakte: int


def _zaehler(db, person) -> dict[str | None, int]:
    return dict(
        db.execute(
            select(Kontakt.adressbuch_id, func.count())
            .where(Kontakt.benutzer_id == person.id)
            .group_by(Kontakt.adressbuch_id)
        ).all()
    )


def _zeile(b, anzahl: int) -> BuchZeile:
    return BuchZeile(
        id=b.id, name=b.name, farbe=b.farbe, sichtbar=b.sichtbar, ist_lokal=b.ist_lokal,
        art=b.art, herkunft=b.herkunft, letzter_fehler=b.letzter_fehler, kontakte=anzahl,
    )


def _buchfehler(f: adressbuecher.BuchFehler) -> MeldungHttp:
    code = (
        status.HTTP_404_NOT_FOUND
        if f.kennung in ("adressbuch_nicht_gefunden", "kontakt_nicht_gefunden")
        else status.HTTP_400_BAD_REQUEST
    )
    return MeldungHttp.aus(f, code)


# --- Verbinden (VOR /{buch_id}) ------------------------------------------ #


class Zugangswunsch(BaseModel):
    #: ``icloud`` und ``google`` bringen die Adresse selbst mit; sonst wird
    #: ``adresse`` genommen.
    art: str = "andere"
    adresse: str = ""
    benutzer: str = ""
    passwort: str = ""
    #: Statt eines Passworts: eine erteilte Zustimmung. ⚠️ Google lässt an
    #: seinem CardDAV-Endpunkt nur das zu, wie beim Kalender.
    oauth_zugang_id: str = ""


class Gefunden(BaseModel):
    url: str
    name: str
    #: Was schon dasteht, ist im Fenster gesperrt und sagt warum.
    schon_verbunden: bool = False


def _herkunft(wunsch: Zugangswunsch) -> str:
    """Was in der Spalte als Herkunft steht: „iCloud", „Google", sonst der Host."""
    return {"icloud": "iCloud", "google": "Google"}.get(wunsch.art) or (
        wunsch.adresse.split("/")[2] if "//" in wunsch.adresse else wunsch.adresse
    )


@router.post("/pruefen", response_model=list[Gefunden])
def pruefen(
    wunsch: Zugangswunsch, person: AngemeldeterBenutzer, db: DbSession
) -> list[Gefunden]:
    """Welche Adressbücher liegen unter diesem Zugang? Es wird nichts angelegt."""
    token, adresse = _token(db, person, wunsch.oauth_zugang_id)
    try:
        gefunden = adressbuchabgleich.finden(
            wunsch.art, wunsch.adresse, wunsch.benutzer or adresse, wunsch.passwort, token
        )
    except _VERBINDUNGSFEHLER as f:
        raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f
    bekannt = {b.url for b in adressbuecher.meine(db, person) if b.url}
    # ⚠️ **Ein Buch ohne Anzeigenamen heisst nach seinem Anbieter.** iCloud
    # nennt seines nicht; im Pfad heisst es ``card``, und so stand es am
    # 05.09.2026 in der Spalte. Umbenennen geht ohnehin.
    herkunft = _herkunft(wunsch)
    return [
        Gefunden(
            url=b.url,
            name=b.name if b.benannt else herkunft,
            schon_verbunden=b.url in bekannt,
        )
        for b in gefunden
    ]


class Verbindungswunsch(Zugangswunsch):
    #: Die Adressen der Bücher, die wirklich geholt werden sollen.
    auswahl: list[Gefunden] = Field(default_factory=list)


@router.post("/verbinden", response_model=list[BuchZeile])
def verbinden(
    wunsch: Verbindungswunsch, person: AngemeldeterBenutzer, db: DbSession
) -> list[BuchZeile]:
    """Die gewählten Bücher anlegen und gleich einmal holen."""
    if not wunsch.auswahl:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="adressbuch_keine_auswahl"
        )
    token, adresse = _token(db, person, wunsch.oauth_zugang_id)
    herkunft = _herkunft(wunsch)
    try:
        neue = adressbuchabgleich.verbinden(
            db, person,
            herkunft=herkunft,
            benutzer_name=wunsch.benutzer or adresse,
            passwort=wunsch.passwort,
            auswahl=[(g.url, g.name) for g in wunsch.auswahl],
            oauth_zugang_id=wunsch.oauth_zugang_id,
        )
        for buch in neue:
            adressbuchabgleich.abgleichen(db, buch)
    except _VERBINDUNGSFEHLER as f:
        raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f
    zaehler = _zaehler(db, person)
    return [_zeile(b, zaehler.get(b.id, 0)) for b in neue]


class Abgleichbericht(BaseModel):
    neu: int = 0
    geaendert: int = 0
    entfernt: int = 0
    #: Karten, die übergangen wurden, weil ihre Adresse hier schon einem
    #: anderen Eintrag gehört. Die Oberfläche sagt es, sonst fehlen drüben
    #: Kontakte und niemand weiss warum.
    belegt: int = 0
    #: Bücher, die dabei einen Fehler hatten, als Kennung je Buch.
    fehler: dict[str, str] = Field(default_factory=dict)


@router.post("/abgleichen", response_model=Abgleichbericht)
def abgleichen(person: AngemeldeterBenutzer, db: DbSession) -> Abgleichbericht:
    """Jedes verbundene Buch einmal, **mit** ``erzwingen``.

    ⚠️ Der Knopf ist der Weg, übergangene Karten nachzuholen: Wer den lokalen
    Doppelgänger gerade gelöscht hat, will die Karte jetzt sehen, und das
    ``ctag`` drüben hat sich dabei nicht geändert.
    """
    bericht = Abgleichbericht()
    for runde in adressbuchabgleich.alle_abgleichen(db, person, erzwingen=True).values():
        bericht.neu += runde.neu
        bericht.geaendert += runde.geaendert
        bericht.entfernt += runde.entfernt
        bericht.belegt += runde.belegt
    for buch in adressbuecher.meine(db, person):
        if buch.letzter_fehler:
            bericht.fehler[buch.id] = buch.letzter_fehler
    return bericht


# --- Bücher --------------------------------------------------------------- #


@router.get("", response_model=list[BuchZeile])
def liste(person: AngemeldeterBenutzer, db: DbSession) -> list[BuchZeile]:
    zaehler = _zaehler(db, person)
    return [_zeile(b, zaehler.get(b.id, 0)) for b in adressbuecher.meine(db, person)]


class BuchAenderung(BaseModel):
    #: Nicht mitgeschickt heisst unverändert, dieselbe Regel wie überall.
    name: str | None = None
    farbe: int | None = None
    sichtbar: bool | None = None


@router.patch("/{buch_id}", response_model=BuchZeile)
def aendern(
    buch_id: str, aenderung: BuchAenderung, person: AngemeldeterBenutzer, db: DbSession
) -> BuchZeile:
    try:
        buch = adressbuecher.aendern(
            db, person, buch_id, **aenderung.model_dump(exclude_none=True)
        )
    except adressbuecher.BuchFehler as f:
        raise _buchfehler(f) from f
    return _zeile(buch, _zaehler(db, person).get(buch.id, 0))


class Weg(BaseModel):
    kontakte: int


@router.delete("/{buch_id}", response_model=Weg)
def trennen(buch_id: str, person: AngemeldeterBenutzer, db: DbSession) -> Weg:
    """Das Buch samt seiner Kopie der Kontakte aus nexmail nehmen.

    ⚠️ **Beim Anbieter bleibt alles stehen.** Das ist der ganze Sinn der Beta:
    Nichts, was hier passiert, erreicht iCloud oder Google. Das lokale Buch
    geht nicht; es hält, was nur hier lebt.
    """
    try:
        return Weg(kontakte=adressbuecher.entfernen(db, person, buch_id))
    except adressbuecher.BuchFehler as f:
        raise _buchfehler(f) from f
