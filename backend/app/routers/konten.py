"""Postfächer: vorschlagen, prüfen, anlegen, auflisten, entfernen.

Der Weg in der Oberfläche ist absichtlich in dieser Reihenfolge gebaut:

    Adresse eintippen  →  /vorschlag  →  Felder gefüllt (oder von Hand)
                       →  /pruefen    →  beide Wege gemeldet
                       →  /           →  angelegt, Ordner übernommen

⚠️ **Geprüft wird vor dem Anlegen, nicht danach.** Ein Postfach, das in der
Liste steht und nicht funktioniert, sieht aus wie ein Fehler von nexmail.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Nachricht
from ..services import (
    imap as imapdienst,
    konten as kontendienst,
    ordner as ordnerdienst,
)
from ..services.konten import Zugangsdaten

logger = logging.getLogger("nexmail.konten")

router = APIRouter(prefix="/api/konten", tags=["konten"])


# --- Formen -------------------------------------------------------------- #


class Serverteil(BaseModel):
    server: str = ""
    port: int = 0
    sicherheit: str = "ssl"
    benutzer: str = ""


class VorschlagAntwort(BaseModel):
    gefunden: bool
    quelle: str = ""
    anbietername: str = ""
    app_passwort_noetig: bool = False
    app_passwort_wo: str = ""
    imap: Serverteil = Serverteil()
    smtp: Serverteil = Serverteil()


class Eingabe(BaseModel):
    anzeigename: str = Field(default="", max_length=120)
    absendername: str = Field(default="", max_length=120)
    adresse: str = Field(min_length=3, max_length=320)
    imap_server: str = Field(min_length=1, max_length=255)
    imap_port: int = 993
    imap_sicherheit: str = "ssl"
    imap_benutzer: str = Field(min_length=1, max_length=320)
    #: ⚠️ **Leer ist erlaubt, wenn eine Zustimmung mitkommt.** Google und
    #: Microsoft nehmen ueber IMAP kein Passwort mehr an; ein Pflichtfeld hier
    #: hiesse, dort ein erfundenes einzutippen.
    imap_passwort: str = Field(default="", max_length=500)
    smtp_server: str = Field(min_length=1, max_length=255)
    smtp_port: int = 587
    smtp_sicherheit: str = "starttls"
    smtp_benutzer: str = Field(min_length=1, max_length=320)
    smtp_passwort: str = Field(default="", max_length=500)
    #: Freie Schlagworte zum Gruppieren der Postfächer in der Ordnerspalte.
    tags: list[str] | None = None
    #: Statt der Passwoerter: eine erteilte Zustimmung (OAuth).
    oauth_zugang_id: str = Field(default="", max_length=32)

    def als_zugangsdaten(self) -> Zugangsdaten:
        return Zugangsdaten(**self.model_dump())


class Aenderung(Eingabe):
    """Wie ``Eingabe``, aber die Passwörter dürfen leer bleiben.

    ⚠️ **Leer heißt „unverändert", nicht „leer".** Die Oberfläche kann ein
    gespeichertes Passwort nicht anzeigen — sie schickt deshalb nichts, wenn
    niemand das Feld angefasst hat. Mit dem geerbten ``min_length=1`` scheiterte
    das an einer rohen Pydantic-Meldung („String should have at least 1
    character"), die weder sagt, welches Feld gemeint ist, noch auf Deutsch
    steht. Genau so gemeldet am 01.09.2026.
    """

    imap_passwort: str = Field(default="", max_length=500)
    smtp_passwort: str = Field(default="", max_length=500)


class TeilAntwort(BaseModel):
    ok: bool
    art: str = ""
    text: str = ""


class OrdnerAntwort(BaseModel):
    # ⚠️ **Die Zähler kommen vom Server, nicht aus der geladenen Liste.**
    # Die Oberfläche hält nur die Nachrichten des offenen Ordners; wer daraus
    # zählt, zeigt bei allen anderen Ordnern null. Genau so gemeldet am
    # 01.09.2026: „ich sehe die ungelesenen Einträge nur, wenn ich das
    # entsprechende Postfach ausgewählt habe."
    #: 0 beim Verbindungstest - da existiert der Ordner noch nicht in der
    #: Datenbank. Nach dem Anlegen traegt er seine echte Kennung.
    id: int = 0
    pfad: str
    name: str
    rolle: str
    waehlbar: bool
    #: Wie viele Nachrichten nexmail von diesem Ordner kennt.
    anzahl: int = 0
    #: Wie viele davon ungelesen sind.
    ungelesen: int = 0
    abonniert: bool


class BefundAntwort(BaseModel):
    ok: bool
    imap: TeilAntwort
    smtp: TeilAntwort
    ordner: list[OrdnerAntwort]
    #: Kann der Server MOVE? Sonst wird verschoben mit COPY + \Deleted.
    kann_move: bool = False


class KontoAntwort(BaseModel):
    id: str
    #: 'anmeldung', wenn der Mailserver die Zugangsdaten ablehnt - die
    #: Oberflaeche macht daraus den roten Banner. Leer = alles in Ordnung.
    stoerung: str = ""
    #: Wie das Postfach in der Ordnerspalte heißt.
    anzeigename: str
    #: Wie der Empfänger den Absender sieht. Leer = wie ``anzeigename``.
    absendername: str
    adresse: str
    farbe: int
    aktiv: bool
    imap_server: str
    smtp_server: str
    # ⚠️ **Alles außer den Passwörtern.** Die Oberfläche braucht die
    # Servereinstellungen, um sie zum Bearbeiten vorzulegen — die Passwörter
    # verlassen den Server nie, auch nicht verschlüsselt.
    imap_port: int
    imap_sicherheit: str
    imap_benutzer: str
    smtp_port: int
    smtp_sicherheit: str
    smtp_benutzer: str
    zuletzt_geprueft: datetime | None
    letzter_fehler: str
    #: Die Kennung dazu (Fehlerart.*) - daraus macht die Oberflaeche den Satz
    #: in der eingestellten Sprache. Leer bei Altbestand: dann bleibt der
    #: gespeicherte Satz die Rueckfallebene.
    letzter_fehler_art: str = ""
    anzahl_ordner: int
    tags: list[str]
    #: 'google', 'microsoft' — oder leer bei einem gewoehnlichen
    #: IMAP-Postfach. Die Kachel zeigt daran, woher das Postfach kommt; ohne
    #: das saehe ein Google-Postfach aus wie jedes andere und niemand wuesste,
    #: warum dort keine Passwortfelder stehen.
    oauth_art: str = ""
    #: Wie viele Kalender an derselben Zustimmung haengen. ⚠️ **Die Zahl
    #: gehoert in die Rueckfrage**, sonst hakt man „Kalender mit entfernen" an,
    #: ohne zu wissen, wie viele das sind.
    oauth_kalender: int = 0


def _antwort(konto) -> KontoAntwort:
    return KontoAntwort(
        id=konto.id,
        anzeigename=konto.anzeigename,
        stoerung=konto.stoerung or "",
        absendername=konto.absendername,
        adresse=konto.adresse,
        farbe=konto.farbe,
        aktiv=konto.aktiv,
        imap_server=konto.imap_server,
        smtp_server=konto.smtp_server,
        imap_port=konto.imap_port,
        imap_sicherheit=konto.imap_sicherheit,
        imap_benutzer=konto.imap_benutzer,
        smtp_port=konto.smtp_port,
        smtp_sicherheit=konto.smtp_sicherheit,
        smtp_benutzer=konto.smtp_benutzer,
        zuletzt_geprueft=konto.zuletzt_geprueft,
        letzter_fehler=konto.letzter_fehler,
        letzter_fehler_art=konto.letzter_fehler_art or "",
        anzahl_ordner=len(konto.ordner),
        tags=kontendienst.tags_lesen(konto),
        oauth_art=konto.oauth_zugang.art if konto.oauth_zugang else "",
        oauth_kalender=len(konto.oauth_zugang.kalender) if konto.oauth_zugang else 0,
    )


def _befund_antwort(befund) -> BefundAntwort:
    return BefundAntwort(
        ok=befund.ok,
        imap=TeilAntwort(ok=befund.imap.ok, art=befund.imap.art, text=befund.imap.text),
        smtp=TeilAntwort(ok=befund.smtp.ok, art=befund.smtp.art, text=befund.smtp.text),
        ordner=[
            OrdnerAntwort(
                pfad=o.pfad,
                name=o.name,
                rolle=o.rolle,
                waehlbar=o.waehlbar,
                abonniert="abonniert" in o.kennzeichen,
            )
            for o in befund.ordner
        ],
        kann_move=any(k.upper() == "MOVE" for k in befund.faehigkeiten),
    )


# --- Adressen ------------------------------------------------------------ #


class NurAdresse(BaseModel):
    adresse: str = Field(min_length=3, max_length=320)


@router.post("/vorschlag", response_model=VorschlagAntwort)
def vorschlag(eingabe: NurAdresse, _: AngemeldeterBenutzer) -> VorschlagAntwort:
    """Serverdaten zur Adresse suchen — Autoconfig zuerst, Tabelle danach.

    Findet nichts etwas, ist das **kein Fehler**: Dann trägt man sie von Hand
    ein, und das ist der Hauptweg. Jedes IMAP-Postfach muss ohne Vorwissen von
    nexmail funktionieren.
    """
    gefunden = kontendienst.vorschlag_fuer(eingabe.adresse.strip())
    if gefunden is None:
        return VorschlagAntwort(gefunden=False)

    from ..services.anbieter import benutzer_bilden

    adresse = eingabe.adresse.strip()
    return VorschlagAntwort(
        gefunden=True,
        quelle=gefunden.quelle,
        anbietername=gefunden.anbietername,
        app_passwort_noetig=gefunden.app_passwort_noetig,
        app_passwort_wo=gefunden.app_passwort_wo,
        imap=Serverteil(
            server=gefunden.imap.server,
            port=gefunden.imap.port,
            sicherheit=gefunden.imap.sicherheit,
            benutzer=benutzer_bilden(adresse, gefunden.imap.benutzerform),
        ),
        smtp=Serverteil(
            server=gefunden.smtp.server,
            port=gefunden.smtp.port,
            sicherheit=gefunden.smtp.sicherheit,
            benutzer=benutzer_bilden(adresse, gefunden.smtp.benutzerform),
        ),
    )


@router.post("/pruefen", response_model=BefundAntwort)
def pruefen(
    eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession
) -> BefundAntwort:
    """Beide Wege prüfen, ohne etwas zu speichern.

    ⚠️ **Mit einer Zustimmung wird der Token geprueft, nicht ein Passwort.**
    Ohne das scheitert der Test bei Google und Microsoft zwangslaeufig — und
    weil er beim Anlegen Pflicht ist, liesse sich dort gar kein Postfach
    einrichten.
    """
    wo, token = _wie_anmelden(db, person, eingabe)
    return _befund_antwort(kontendienst.pruefen(eingabe.als_zugangsdaten(), wo, token))


def _wie_anmelden(db, person, eingabe: Eingabe) -> tuple[str, str]:
    """Wo das App-Passwort steht — und, bei OAuth, das Zugriffstoken.

    ⚠️ **Eine Stelle, nicht zwei.** Der Verbindungstest laeuft an zwei Orten:
    beim Pruefen **und** beim Anlegen (das der Oberflaeche bewusst nicht
    glaubt). Am 03.09.2026 hatte nur der erste den Token bekommen — der Test
    wurde gruen, das Anlegen scheiterte danach mit „app-spezifisches Passwort
    noetig". Dieselbe Lehre wie bei den sechsundzwanzig IMAP-Verbindungen: Wer
    denselben Griff zweimal schreibt, vergisst ihn einmal.
    """
    from ..models import OauthZugang
    from ..services import mailoauth

    vorschlag_ = kontendienst.vorschlag_fuer(eingabe.adresse)
    wo = vorschlag_.app_passwort_wo if vorschlag_ else ""
    if not eingabe.oauth_zugang_id:
        return wo, ""

    zugang = db.get(OauthZugang, eingabe.oauth_zugang_id)
    if zugang is None or zugang.benutzer_id != person.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="oauth_zugang_unbekannt"
        )
    try:
        token = mailoauth.zugriffstoken(db, zugang)
    except mailoauth.OauthFehler as f:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(f)) from f
    # ⚠️ Mit Zustimmung ist der App-Passwort-Hinweis falsch: Er schickt den
    # Betreiber ein Passwort erzeugen, das hier gar nicht gebraucht wird.
    return "", token


@router.get("", response_model=list[KontoAntwort])
def liste(person: AngemeldeterBenutzer, db: DbSession) -> list[KontoAntwort]:
    return [_antwort(k) for k in kontendienst.meine(db, person)]


@router.post("", response_model=KontoAntwort, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession) -> KontoAntwort:
    """Anlegen — nach erfolgreicher Prüfung, und mit den Ordnern.

    ⚠️ Die Prüfung läuft hier **noch einmal**, auch wenn die Oberfläche sie
    schon gemacht hat. Ein Aufruf, der der Oberfläche glaubt, legt bei jedem
    zweiten Werkzeug ein kaputtes Postfach an.
    """
    wo, token = _wie_anmelden(db, person, eingabe)
    befund = kontendienst.pruefen(eingabe.als_zugangsdaten(), wo, token)

    if not befund.ok:
        schlimm = befund.imap if not befund.imap.ok else befund.smtp
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=schlimm.text)

    try:
        konto = kontendienst.anlegen(db, person, eingabe.als_zugangsdaten())
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    kontendienst.ordner_uebernehmen(db, konto, befund.ordner)
    db.refresh(konto)
    return _antwort(konto)


@router.put("/{konto_id}", response_model=KontoAntwort)
def aendern(
    konto_id: str, eingabe: Aenderung, person: AngemeldeterBenutzer, db: DbSession
) -> KontoAntwort:
    """Ein bestehendes Postfach ändern.

    ⚠️ **Ein leeres Passwortfeld heißt „unverändert".** Die Oberfläche kann ein
    gespeichertes Passwort nicht anzeigen; würde sie das leere Feld
    übernehmen, verlöre jeder seinen Zugang, der nur den Anzeigenamen ändert.
    """
    try:
        konto = kontendienst.aendern(db, person, konto_id, eingabe.als_zugangsdaten())
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler

    # ⚠️ **Neue Zugangsdaten heissen: die Stoerung ist erst mal erledigt.**
    # Sonst stuende der rote Banner nach dem Korrigieren noch bis zu zwei
    # Minuten da (naechster Takt) und saehe aus, als haette das Speichern
    # nichts genuetzt. Stimmt es wieder nicht, setzt der naechste Abgleich
    # die Marke erneut - nichts geht verloren.
    if konto.stoerung:
        konto.stoerung = ""
        db.commit()
    return _antwort(konto)


@router.get("/{konto_id}/ordner", response_model=list[OrdnerAntwort])
def ordner(konto_id: str, person: AngemeldeterBenutzer, db: DbSession) -> list[OrdnerAntwort]:
    try:
        konto = kontendienst.eines(db, person, konto_id)
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler

    rang = {
        "posteingang": 0,
        "gesendet": 1,
        "entwuerfe": 2,
        "archiv": 3,
        "junk": 4,
        "papierkorb": 5,
        "eigen": 6,
    }
    # ⚠️ **Gezaehlt wird jetzt, nicht abgelesen.** Bis zum 02.09.2026 kamen die
    # beiden Zahlen aus der Spalte am Ordner, und die Oberflaeche zaehlte fuer
    # den GEOEFFNETEN Ordner daneben noch einmal selbst — ueber die geladene
    # Liste, die gefiltert und auf eine Seite begrenzt ist. Zwei Quellen fuer
    # dieselbe Zahl: Der Baum zeigte 16, ein Klick in den Ordner machte 11
    # daraus, ein Klick daneben wieder 16. Am 02.09.2026 gemeldet.
    #
    # ⚠️ **Der Preis ist gemessen und klein.** Eine Gruppenabfrage ueber alle
    # Ordner eines Postfachs kostet 5,6 ms (CLAUDE.md, „Gemessen, nicht
    # geschaetzt") — der Teilindex ``… where gelesen = 0`` traegt das.
    stand = {
        o_id: (gesamt, ungelesen)
        for o_id, gesamt, ungelesen in db.execute(
            select(
                Nachricht.ordner_id,
                func.count(Nachricht.id),
                func.count(case((Nachricht.gelesen.is_(False), 1))),
            )
            .where(Nachricht.konto_id == konto.id)
            .group_by(Nachricht.ordner_id)
        ).all()
    }

    return [
        OrdnerAntwort(
            id=o.id,
            pfad=o.pfad,
            name=o.name,
            rolle=o.rolle,
            waehlbar=o.waehlbar,
            abonniert=o.abonniert,
            anzahl=stand.get(o.id, (0, 0))[0],
            ungelesen=stand.get(o.id, (0, 0))[1],
        )
        for o in sorted(konto.ordner, key=lambda o: (rang.get(o.rolle, 9), o.name.lower()))
    ]


class NeuerOrdner(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    #: Unter welchem Ordner er entstehen soll. Leer heißt: oberste Ebene.
    eltern_id: int | None = None


@router.post("/{konto_id}/ordner", response_model=OrdnerAntwort, status_code=status.HTTP_201_CREATED)
def ordner_anlegen(
    konto_id: str, wunsch: NeuerOrdner, person: AngemeldeterBenutzer, db: DbSession
) -> OrdnerAntwort:
    """Einen Ordner beim Anbieter anlegen.

    ⚠️ **Nicht nur in nexmail.** Ein Ordner, den nur diese Anwendung kennt,
    wäre auf dem Telefon nicht da und beim nächsten Abgleich wieder weg — die
    Ordnerliste des Servers ist die Wahrheit.
    """
    try:
        konto = kontendienst.eines(db, person, konto_id)
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler

    eltern = None
    if wunsch.eltern_id is not None:
        eltern = next((o for o in konto.ordner if o.id == wunsch.eltern_id), None)
        if eltern is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Den übergeordneten Ordner gibt es in diesem Postfach nicht.",
            )

    try:
        neu = ordnerdienst.anlegen(db, konto, wunsch.name, eltern)
    except ordnerdienst.OrdnerFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    except imapdienst.Verbindungsfehler as fehler:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=fehler.text) from fehler

    return OrdnerAntwort(
        id=neu.id,
        pfad=neu.pfad,
        name=neu.name,
        rolle=neu.rolle,
        waehlbar=neu.waehlbar,
        abonniert=neu.abonniert,
    )


class OrdnerName(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.put("/{konto_id}/ordner/{ordner_id}", response_model=OrdnerAntwort)
def ordner_umbenennen(
    konto_id: str,
    ordner_id: int,
    wunsch: OrdnerName,
    person: AngemeldeterBenutzer,
    db: DbSession,
) -> OrdnerAntwort:
    """Einen Ordner beim Anbieter umbenennen — Unterordner kommen mit."""
    try:
        konto = kontendienst.eines(db, person, konto_id)
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler

    ziel = next((o for o in konto.ordner if o.id == ordner_id), None)
    if ziel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        neu = ordnerdienst.umbenennen(db, konto, ziel, wunsch.name)
    except ordnerdienst.OrdnerFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    except imapdienst.Verbindungsfehler as fehler:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=fehler.text) from fehler

    return OrdnerAntwort(
        id=neu.id,
        pfad=neu.pfad,
        name=neu.name,
        rolle=neu.rolle,
        waehlbar=neu.waehlbar,
        abonniert=neu.abonniert,
    )


@router.delete("/{konto_id}/ordner/{ordner_id}")
def ordner_entfernen(
    konto_id: str, ordner_id: int, person: AngemeldeterBenutzer, db: DbSession
) -> dict[str, int]:
    """Einen Ordner beim Anbieter löschen — samt Inhalt.

    ⚠️ **Ohne Rückweg.** Die Oberfläche fragt vorher und nennt die Zahl der
    Nachrichten; hier wird nur noch ausgeführt.
    """
    try:
        konto = kontendienst.eines(db, person, konto_id)
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler

    ziel = next((o for o in konto.ordner if o.id == ordner_id), None)
    if ziel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        return {"nachrichten": ordnerdienst.entfernen(db, konto, ziel)}
    except ordnerdienst.OrdnerFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    except imapdienst.Verbindungsfehler as fehler:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=fehler.text) from fehler


@router.delete("/{konto_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(
    konto_id: str,
    person: AngemeldeterBenutzer,
    db: DbSession,
    kalender_mit: bool = False,
) -> None:
    """⚠️ **Die Kalender gehen nur mit, wenn es jemand ausdrücklich will.**

    Sie hängen an der **Zustimmung**, nicht am Postfach — ein Postfach zu
    entfernen könnte sie also stehen lassen, und das wäre auch verteidigbar.
    Nur weiß das niemand, der beides in einem Zug angelegt hat: Für ihn ist der
    Kalender danach ein Waisenkind. Deshalb fragt die Oberfläche mit einem
    Haken, vorbelegt mit **aus** — nichts wird still gelöscht.
    """
    try:
        kontendienst.entfernen(db, person, konto_id, kalender_mit=kalender_mit)
    except kontendienst.KontoFehler as fehler:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fehler)) from fehler
