"""Benachrichtigungen — die Adressen.

⚠️ **Zwei Sorten Einstellung, und sie liegen absichtlich getrennt.** Ob dieser
Browser Meldungen bekommt, entscheidet er selbst und steht als Zeile in
``push_anmeldung``. **Wobei** gemeldet wird, gehoert dem Benutzer und steht an
seiner Zeile. Wer beides zusammenlegte, hiesse entweder „am Telefon melde ich
anderes als am Rechner" (dann versteht niemand mehr, warum es einmal klingelt)
oder „ein Geraet abmelden schaltet alle ab".

⚠️ **Der oeffentliche Schluessel ist kein Geheimnis, die Adresse trotzdem
geschuetzt.** Er ist dafuer gemacht, im Browser zu stehen. Aber eine offene
Adresse waere eine weitere Zeile in ``OEFFENTLICHE_PFADE``, und die will
begruendet sein: Es gibt keinen Grund, denn wer sich anmelden will, ist
angemeldet.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AngemeldeterBenutzer, DbSession
from ..models import PushAnmeldung
from ..services import push as dienst

router = APIRouter(prefix="/api/push", tags=["push"])


class Schluessel(BaseModel):
    oeffentlicher_schluessel: str


class Anmeldewunsch(BaseModel):
    endpunkt: str = Field(min_length=1, max_length=2000)
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=64)


class GeraetZeile(BaseModel):
    id: int
    geraet: str
    angelegt: datetime
    zuletzt_erreicht: datetime | None
    #: Ob das die Anmeldung genau dieses Browsers ist.
    dieses: bool


class Einstellungen(BaseModel):
    push_termine: bool
    push_mail: bool
    push_mail_alle_ordner: bool
    push_mail_nur_ungelesen: bool
    push_mail_buendeln: bool
    push_ruhezeit: bool
    push_ruhezeit_von: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    push_ruhezeit_bis: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def _geraetename(user_agent: str) -> str:
    """„Firefox, Windows" aus dem User-Agent.

    ⚠️ **Grob und mit Absicht.** Der Name steht nur in der Liste, damit man
    seine Geraete auseinanderhaelt; unterschieden werden sie am Endpunkt. Eine
    vollstaendige Auswertung waere eine Bibliothek fuer eine Beschriftung, und
    der ganze User-Agent gehoerte damit in die Datenbank — mehr ueber den
    Benutzer, als hier gebraucht wird.
    """
    if not user_agent:
        return ""
    # Reihenfolge zaehlt: Edge nennt sich auch Chrome, Chrome auch Safari.
    browser = ""
    for kennung, name in (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
    ):
        if kennung in user_agent:
            browser = name
            break
    system = ""
    for kennung, name in (
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Android", "Android"),
        ("Windows", "Windows"),
        ("Mac OS X", "macOS"),
        ("Linux", "Linux"),
    ):
        if kennung in user_agent:
            system = name
            break
    return ", ".join(t for t in (browser, system) if t)[:120]


@router.get("/schluessel", response_model=Schluessel)
def schluessel(person: AngemeldeterBenutzer, db: DbSession) -> Schluessel:
    """Was der Browser als ``applicationServerKey`` braucht."""
    return Schluessel(oeffentlicher_schluessel=dienst.oeffentlicher_schluessel(db))


@router.post("/anmelden", response_model=GeraetZeile)
def anmelden(
    wunsch: Anmeldewunsch,
    person: AngemeldeterBenutzer,
    db: DbSession,
    request: Request,
) -> GeraetZeile:
    """Dieses Geraet nimmt ab jetzt Meldungen an.

    ⚠️ **Derselbe Endpunkt gibt keine zweite Zeile.** Der Browser meldet sich
    bei jedem Start des Service Workers erneut an und bekommt dabei in aller
    Regel dieselbe Adresse zurueck. Ohne diese Stelle waechst die Tabelle mit
    jedem Seitenaufruf, und jede Meldung ginge vielfach hinaus.

    ⚠️ **Und sie kann den Besitzer wechseln.** Meldet sich an einem geteilten
    Rechner ein zweiter Benutzer an, gehoert das Abonnement ab dann ihm — der
    Browser hat nur eines. Andernfalls bekaeme der Vorgaenger weiter die
    Meldungen, und niemand fuende heraus, warum.
    """
    zeile = db.scalar(
        select(PushAnmeldung).where(PushAnmeldung.endpunkt == wunsch.endpunkt)
    )
    if zeile is None:
        zeile = PushAnmeldung(endpunkt=wunsch.endpunkt)
        db.add(zeile)
    zeile.benutzer_id = person.id
    zeile.p256dh = wunsch.p256dh
    zeile.auth = wunsch.auth
    zeile.geraet = _geraetename(request.headers.get("user-agent", ""))
    db.commit()
    db.refresh(zeile)
    return GeraetZeile(
        id=zeile.id,
        geraet=zeile.geraet,
        angelegt=zeile.angelegt,
        zuletzt_erreicht=zeile.zuletzt_erreicht,
        dieses=True,
    )


@router.get("/geraete", response_model=list[GeraetZeile])
def geraete(
    person: AngemeldeterBenutzer, db: DbSession, endpunkt: str = ""
) -> list[GeraetZeile]:
    """Die angemeldeten Geraete dieses Benutzers.

    ``endpunkt`` ist der eigene, damit die Liste „dieses" markieren kann. Er
    ist freiwillig: Ein Browser ohne Erlaubnis hat keinen.
    """
    return [
        GeraetZeile(
            id=a.id,
            geraet=a.geraet,
            angelegt=a.angelegt,
            zuletzt_erreicht=a.zuletzt_erreicht,
            dieses=bool(endpunkt) and a.endpunkt == endpunkt,
        )
        for a in sorted(person.push_anmeldungen, key=lambda a: a.angelegt, reverse=True)
    ]


@router.delete("/geraete/{anmeldung_id}", status_code=status.HTTP_204_NO_CONTENT)
def abmelden(anmeldung_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Response:
    zeile = db.get(PushAnmeldung, anmeldung_id)
    # ⚠️ **Der Besitzer wird geprueft, nicht nur die Kennung.** Die Kennungen
    # sind fortlaufende Zahlen; ohne die Pruefung meldete jeder Benutzer die
    # Geraete jedes anderen ab.
    if zeile is None or zeile.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="geraet_unbekannt")
    db.delete(zeile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/einstellungen", response_model=Einstellungen)
def einstellungen_lesen(person: AngemeldeterBenutzer) -> Einstellungen:
    return Einstellungen.model_validate(person, from_attributes=True)


@router.put("/einstellungen", response_model=Einstellungen)
def einstellungen_setzen(
    wunsch: Einstellungen, person: AngemeldeterBenutzer, db: DbSession
) -> Einstellungen:
    for feld, wert in wunsch.model_dump().items():
        setattr(person, feld, wert)
    db.commit()
    return Einstellungen.model_validate(person, from_attributes=True)


@router.post("/probe", status_code=status.HTTP_204_NO_CONTENT)
def probe(person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """Eine Probemeldung an alle angemeldeten Geraete.

    ⚠️ **Sie ist kein Beiwerk.** Zwischen „der Browser hat die Erlaubnis
    erteilt" und „es kommt wirklich etwas an" liegen ein Service Worker, ein
    Push-Dienst und eine Systemeinstellung, die jeder fuer sich stumm schalten
    kann. Ohne diesen Knopf faellt das erst an dem Tag auf, an dem eine echte
    Meldung ausbleibt — und dann sucht man den Fehler beim Termin.

    ⚠️ **Sie geht durch die Ruhezeit hindurch.** Wer sie drueckt, will jetzt
    wissen, ob es geht.
    """
    if not person.push_anmeldungen:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="kein_geraet_angemeldet"
        )
    dienst.an_benutzer(
        db,
        person,
        dienst.Meldung(
            titel="nexmail",
            text="Benachrichtigungen kommen an.",
            ziel="/",
            marke="probe",
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
