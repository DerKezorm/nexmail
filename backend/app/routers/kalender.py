"""Kalender und Termine.

⚠️ **Die Termin-Adressen stehen VOR ``/{kalender_id}``.** FastAPI nimmt die
erste passende Route; sonst läse es ``termine`` als Kalender-Kennung. Dasselbe
Muster wie bei ``/api/aufgaben/reihenfolge`` und den Schlagworten.

⚠️ **Der Server nennt, die Oberfläche übersetzt.** ``TerminFehler`` trägt eine
KENNUNG (``kalender_nur_lesen``), keinen deutschen Satz — nexmail spricht zwei
Sprachen, und ein hier gebauter Satz wäre in einer davon falsch.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ..models import Termin
from ..deps import AngemeldeterBenutzer, DbSession
from ..services import caldav
from ..services import kalenderabgleich
from ..services import termine as dienst
from ..services import wiederholung
from ..services import konten as kontendienst
from ..services import termineinladung as einladungsdienst
from ..services.aliase import lesen as aliase_lesen
from ..services.kontakte import _ADRESSE
from ..meldung import MeldungHttp

logger = logging.getLogger("nexmail.kalender")

router = APIRouter(prefix="/api/kalender", tags=["kalender"])


def _leute_json(eingaben) -> str:
    """Die Teilnehmerliste als JSON, wie sie in ``Termin`` liegt.

    ⚠️ **Klein gespeichert und ohne Doppel.** Zweimal dieselbe Adresse waeren
    zwei ``ATTENDEE``-Zeilen fuer eine Person, und zwei Einladungen fuer
    dieselbe Mail.

    ⚠️ **Ohne Zusagestand.** Der gehoert der Person; ihn hier zu setzen hiesse,
    fuer andere zuzusagen. Er kommt spaeter ueber die Antwort zurueck.
    """
    raus: list[dict[str, str]] = []
    gesehen: set[str] = set()
    for e in eingaben:
        adresse = e.adresse.strip().lower()
        if not _ADRESSE.match(adresse):
            raise dienst.TerminFehler("teilnehmer_adresse_ungueltig", adresse=adresse)
        if adresse in gesehen:
            continue
        gesehen.add(adresse)
        raus.append({"name": e.name.strip(), "adresse": adresse, "antwort": "NEEDS-ACTION"})
    return json.dumps(raus, ensure_ascii=False) if raus else ""


def _absender_json(db, person, adresse: str) -> str:
    """Der Organisator als JSON — geprueft, nicht uebernommen.

    ⚠️ Leer heisst „kein Organisator", nicht „irgendeiner". Ein Termin ohne
    Teilnehmer braucht keinen.
    """
    if not adresse.strip():
        return ""
    konto = einladungsdienst.postfach_fuer(db, person, adresse)
    name = kontendienst.absendername(konto)
    for alias in aliase_lesen(konto):
        if alias.adresse == adresse.strip().lower():
            name = alias.name or name
    return json.dumps(
        {"name": name, "adresse": adresse.strip().lower(), "antwort": "", "rolle": "CHAIR"},
        ensure_ascii=False,
    )


def _fehler(f: Exception) -> HTTPException:
    kennung = str(f)
    # „Gibt es nicht" ist ein 404, alles andere eine schlechte Anfrage.
    code = (
        status.HTTP_404_NOT_FOUND
        if kennung in ("kalender_unbekannt", "termin_unbekannt")
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=kennung)


# --- Formen --------------------------------------------------------------- #


class KalenderZeile(BaseModel):
    id: str
    name: str
    farbe: int
    sichtbar: bool
    #: "" (nur hier) | "caldav" | "ics"
    art: str
    herkunft: str
    nur_lesen: bool
    letzter_fehler: str


class KalenderWunsch(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    farbe: int = 0


class KalenderAenderung(BaseModel):
    #: Nicht mitgeschickt heisst **unveraendert** — dieselbe Regel wie beim
    #: Passwort und bei den Schlagworten eines Postfachs.
    name: str | None = None
    farbe: int | None = None
    sichtbar: bool | None = None


class Beteiligter(BaseModel):
    name: str = ""
    adresse: str = ""
    #: ``NEEDS-ACTION`` | ``ACCEPTED`` | ``DECLINED`` | ``TENTATIVE`` | …
    #: ⚠️ Die Kennung, nicht der Satz — die Oberflaeche formuliert.
    antwort: str = ""
    rolle: str = ""


class TerminZeile(BaseModel):
    id: int
    kalender_id: str
    titel: str
    #: Der Beginn **dieses Vorkommens**, nicht der der Reihe.
    beginn: datetime
    ende: datetime
    ganztaegig: bool
    ort: str
    beschreibung: str
    #: Wahr, wenn es aus einer Wiederholung stammt — dann wird beim Aendern
    #: gefragt, ob einer, alle oder die folgenden gemeint sind.
    aus_reihe: bool
    #: Die Regel als Kennung fuer die Oberflaeche (``woechentlich``).
    wiederholung: str
    #: Die Wochentage als ``MO``/``TU``/… — die Oberflaeche macht daraus
    #: Namen, die der Browser ohnehin kennt.
    wiederholung_tage: list[str]
    wiederholung_intervall: int
    # --- Dieselbe Regel, zerlegt fuer die MASKE ------------------------- #
    #
    # ⚠️ **Zwei Gruppen, und sie sagen Verschiedenes.** Oben steht, was ein
    # SATZ braucht (``als_satz``); hier, was ein FORMULAR braucht
    # (``regel_lesen``). Bei „jedem ersten Donnerstag" meldet die erste Gruppe
    # ``allgemein`` und **keine** Wochentage — richtig fuer einen Satz, denn
    # „donnerstags" waere gelogen. Ein Formular, das dieselben Felder benutzt,
    # zeigt danach „Keine" und nimmt die Wiederholung beim Speichern mit.
    # Genau so am 03.09.2026 passiert; deshalb der eigene Praefix.
    regel_freq: str = ""
    regel_intervall: int = 1
    regel_tage: list[str] = Field(default_factory=list)
    #: ``tag`` | ``wochentag`` — bei monatlich: am 17. oder am 3. Dienstag.
    regel_monatsart: str = "tag"
    #: Der Wievielte bei ``wochentag``: 1..4 oder **-1 fuer den letzten**.
    regel_ordinal: int = 1
    #: ``nie`` | ``anzahl`` | ``datum``
    regel_ende: str = "nie"
    regel_anzahl: int = 0
    #: ``JJJJ-MM-TT``
    regel_bis: str = ""
    #: ⚠️ Wahr, wenn die Regel etwas enthaelt, das die Maske nicht abbildet.
    #: Dann wird sie **nicht** zerlegt angeboten, sondern bleibt als Ganzes
    #: stehen — sonst zerstoert ein Speichern die Reihe eines fremden Termins.
    regel_fremd: bool = False
    #: ⚠️ **Nur zum Anzeigen.** Beim Zurueckschreiben bleiben sie unangetastet
    #: in ``roh``; wer sie aendern koennte, muesste auch einladen koennen.
    organisator: Beteiligter | None = None
    teilnehmer: list[Beteiligter] = Field(default_factory=list)
    rrule: str
    aus_einladung: bool
    #: ⚠️ **Wahr, sobald eine Einladung hinausgegangen ist.** Nur dann fragt
    #: die Oberflaeche beim Loeschen nach einer Absage — wer nie eingeladen
    #: wurde, soll von dem Termin nicht durch seinen Ausfall erfahren.
    eingeladen: bool = False
    #: Minuten vor dem Beginn, **-1 heisst keine**.
    erinnerung: int = -1


class TeilnehmerEingabe(BaseModel):
    """Eine Person, die eingeladen werden soll.

    ⚠️ **Der Zusagestand kommt NICHT von hier.** Er gehoert der Person, nicht
    dem Einladenden; wer ihn setzen koennte, koennte fuer andere zusagen.
    """

    adresse: str = Field(max_length=320)
    name: str = Field(default="", max_length=200)


class TerminWunsch(BaseModel):
    kalender_id: str
    titel: str = Field(min_length=1)
    beginn: datetime
    ende: datetime | None = None
    ganztaegig: bool = False
    ort: str = ""
    beschreibung: str = ""
    rrule: str = ""
    erinnerung: int = -1
    #: Wer eingeladen werden soll. Leer heisst: niemand.
    teilnehmer: list[TeilnehmerEingabe] = Field(default_factory=list)
    #: Unter welcher Adresse eingeladen wird. ⚠️ Ein Kalender gehoert zu keinem
    #: Postfach; die Adresse wird gegen die Postfaecher geprueft, nicht
    #: uebernommen.
    absender: str = Field(default="", max_length=320)


class TerminAenderung(BaseModel):
    titel: str | None = None
    beginn: datetime | None = None
    ende: datetime | None = None
    ganztaegig: bool | None = None
    ort: str | None = None
    beschreibung: str | None = None
    rrule: str | None = None
    #: ⚠️ ``None`` heisst **unveraendert** — dieselbe Regel wie beim Passwort.
    #: Nur ein wirklich mitgeschickter Wert ersetzt den ``VALARM`` im
    #: Original; sonst bliebe von einem fremden Alarm nichts uebrig.
    erinnerung: int | None = None
    #: ⚠️ ``None`` heisst auch hier **unveraendert**, und das ist mehr als
    #: Bequemlichkeit: Nur ein mitgeschickter Wert laesst nexmail die
    #: ``ATTENDEE``-Zeilen im Original ersetzen. Bei einem Termin, zu dem man
    #: selbst eingeladen wurde, wuerde das sonst die Zusagen der anderen
    #: wegwerfen — siehe ``vevent.aktualisieren``.
    teilnehmer: list[TeilnehmerEingabe] | None = None
    absender: str | None = Field(default=None, max_length=320)
    #: ``dieser`` | ``folgende`` | ``alle``
    umfang: str = "alle"
    #: Der Beginn des angeklickten Vorkommens. Ohne ihn laesst sich „nur
    #: dieser" nicht sagen.
    vorkommen: datetime | None = None


def _kalender(k) -> KalenderZeile:
    return KalenderZeile(
        id=k.id, name=k.name, farbe=k.farbe, sichtbar=k.sichtbar, art=k.art,
        herkunft=k.herkunft, nur_lesen=k.nur_lesen, letzter_fehler=k.letzter_fehler,
    )


def _liste(roh: str) -> list[dict]:
    """Die gespeicherte JSON-Liste — oder nichts. ⚠️ **Ein kaputter Eintrag
    darf den Termin nicht kosten**: Er kommt von einem fremden Server."""
    if not roh:
        return []
    try:
        werte = json.loads(roh)
    except ValueError:
        logger.info("An event carries unreadable participants; ignored.")
        return []
    return werte if isinstance(werte, list) else []


def _beteiligter(roh) -> Beteiligter | None:
    """Ein gespeicherter Eintrag als Zeile — oder ``None``.

    ⚠️ **Nimmt beides**: die JSON-Zeichenkette des Organisators und die schon
    ausgepackten Wörterbücher aus der Teilnehmerliste. Und ⚠️ **ein kaputter
    Eintrag darf den Termin nicht kosten** — er kommt von einem fremden Server.
    """
    if isinstance(roh, str):
        if not roh:
            return None
        try:
            roh = json.loads(roh)
        except ValueError:
            logger.info("An event carries an unreadable organiser; ignored.")
            return None
    if not isinstance(roh, dict) or not (roh.get("adresse") or roh.get("name")):
        return None
    return Beteiligter(
        name=roh.get("name", ""), adresse=roh.get("adresse", ""),
        antwort=roh.get("antwort", ""), rolle=roh.get("rolle", ""),
    )


def _sicht(s: dienst.Sicht) -> TerminZeile:
    t = s.termin
    kennung, tage, intervall = wiederholung.als_satz(t.rrule)
    regel = wiederholung.regel_lesen(t.rrule)
    return TerminZeile(
        id=t.id, kalender_id=t.kalender_id, titel=t.titel,
        beginn=s.beginn, ende=s.ende, ganztaegig=t.ganztaegig,
        ort=t.ort, beschreibung=t.beschreibung, aus_reihe=s.aus_reihe,
        wiederholung=kennung, wiederholung_tage=tage,
        wiederholung_intervall=intervall,
        regel_freq=regel.freq,
        regel_intervall=regel.intervall,
        regel_tage=regel.tage,
        regel_monatsart=regel.monatsart,
        regel_ordinal=regel.ordinal,
        regel_ende=regel.ende_art,
        regel_anzahl=regel.anzahl,
        regel_bis=regel.bis,
        regel_fremd=regel.fremd,
        organisator=_beteiligter(t.organisator),
        teilnehmer=[b for b in map(_beteiligter, _liste(t.teilnehmer)) if b],
        rrule=t.rrule,
        aus_einladung=t.aus_einladung, erinnerung=t.erinnerung,
        eingeladen=t.eingeladen_am is not None,
    )


# --- Termine (VOR /{kalender_id}) ----------------------------------------- #


@router.get("/termine", response_model=list[TerminZeile])
def fenster(
    person: AngemeldeterBenutzer,
    db: DbSession,
    von: datetime,
    bis: datetime,
    kalender: list[str] | None = Query(default=None),
) -> list[TerminZeile]:
    """Alle Vorkommen im Zeitraum.

    ⚠️ **Eingeschraenkt wird hier, nicht im Browser** — dieselbe Regel wie bei
    der Nachrichtenliste.
    """
    try:
        return [_sicht(s) for s in dienst.fenster(db, person, von, bis, kalender)]
    except dienst.TerminFehler as f:
        raise _fehler(f) from f


class Suchergebnis(BaseModel):
    """Was die Suche zurueckgibt.

    ⚠️ **Die Zahl gehoert dazu, nicht nur die Liste.** Sonst ist „nichts
    gefunden" nicht von „abgeschnitten" zu unterscheiden — dieselbe Regel wie
    beim Fuss der Nachrichtenliste.
    """

    treffer: list[TerminZeile]
    abgeschnitten: bool


@router.get("/suche", response_model=Suchergebnis)
def suche(
    person: AngemeldeterBenutzer,
    db: DbSession,
    q: str,
    kalender: list[str] | None = Query(default=None),
) -> Suchergebnis:
    """Termine nach Titel, Ort und Beschreibung suchen.

    ⚠️ **Vor ``/termine/{id}``**, sonst nimmt FastAPI die erste passende Route
    und liest ``suche`` als kaputte Kennung — dasselbe Muster wie bei den
    Schlagworten und bei ``/api/aufgaben/reihenfolge``.
    """
    gefunden, abgeschnitten = dienst.suchen(db, person, q, kalender)
    return Suchergebnis(
        treffer=[_sicht(dienst.Sicht(t.termin, t.beginn, t.ende, t.aus_reihe)) for t in gefunden],
        abgeschnitten=abgeschnitten,
    )


@router.post("/termine", response_model=TerminZeile, status_code=status.HTTP_201_CREATED)
def termin_anlegen(
    wunsch: TerminWunsch, person: AngemeldeterBenutzer, db: DbSession
) -> TerminZeile:
    try:
        termin = dienst.anlegen(
            db, person, wunsch.kalender_id,
            titel=wunsch.titel, beginn=wunsch.beginn, ende=wunsch.ende,
            ganztaegig=wunsch.ganztaegig, ort=wunsch.ort,
            beschreibung=wunsch.beschreibung, rrule=wunsch.rrule,
            erinnerung=wunsch.erinnerung,
            teilnehmer=_leute_json(wunsch.teilnehmer),
            organisator=_absender_json(db, person, wunsch.absender),
        )
    except dienst.TerminFehler as f:
        raise _fehler(f) from f
    return _sicht(dienst.Sicht(termin, termin.beginn, termin.ende, bool(termin.rrule)))


@router.patch("/termine/{termin_id}", response_model=TerminZeile)
def termin_aendern(
    termin_id: int, aenderung: TerminAenderung, person: AngemeldeterBenutzer, db: DbSession
) -> TerminZeile:
    try:
        termin = dienst.aendern(
            db, person, termin_id,
            vorkommen=aenderung.vorkommen, umfang=aenderung.umfang,
            titel=aenderung.titel, beginn=aenderung.beginn, ende=aenderung.ende,
            ganztaegig=aenderung.ganztaegig, ort=aenderung.ort,
            beschreibung=aenderung.beschreibung, rrule=aenderung.rrule,
            erinnerung=aenderung.erinnerung,
            teilnehmer=(
                None if aenderung.teilnehmer is None else _leute_json(aenderung.teilnehmer)
            ),
            organisator=(
                None
                if aenderung.absender is None
                else _absender_json(db, person, aenderung.absender)
            ),
        )
    except dienst.TerminFehler as f:
        raise _fehler(f) from f
    return _sicht(dienst.Sicht(termin, termin.beginn, termin.ende, bool(termin.rrule)))


class Einladungsstand(BaseModel):
    #: An wie viele Personen die Einladung ging.
    empfaenger: int


@router.post("/termine/{termin_id}/einladen", response_model=Einladungsstand)
def einladen(termin_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Einladungsstand:
    """Die Einladung zu diesem Termin verschicken.

    ⚠️ **Ein eigener Aufruf, nicht ein Nebeneffekt des Speicherns.** Das ist
    die zweite Stelle, an der nexmail von sich aus Post an Fremde schickt; sie
    gehoert hinter eine ausdrueckliche Handlung. Die Oberflaeche fragt davor,
    auch beim Aendern — wer einen Tippfehler in der Notiz ausbessert, soll
    nicht allen eine neue Einladung schicken.
    """
    termin = db.get(Termin, termin_id)
    if termin is None or termin.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        anzahl = einladungsdienst.versenden(db, person, termin)
    except einladungsdienst.EinladungFehler as f:
        raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f
    return Einladungsstand(empfaenger=anzahl)


@router.delete("/termine/{termin_id}", status_code=status.HTTP_204_NO_CONTENT)
def termin_entfernen(
    termin_id: int,
    person: AngemeldeterBenutzer,
    db: DbSession,
    umfang: str = "alle",
    vorkommen: datetime | None = None,
    absagen: bool = False,
) -> Response:
    """Einen Termin loeschen — auf Wunsch mit Absage an die Eingeladenen.

    ⚠️ **``absagen`` ist ein Wunsch, keine Voreinstellung.** Ein geloeschter
    Termin steht bei allen anderen weiter im Kalender, aber eine Absage ist
    Post an Fremde; sie geht nur hinaus, wenn die Oberflaeche danach gefragt
    hat.

    ⚠️ **Erst absagen, dann loeschen.** Danach ist der Termin fort, samt
    Teilnehmerliste und Nummer — die Absage waere nicht mehr zu bauen.
    """
    if absagen:
        termin = db.get(Termin, termin_id)
        if termin is not None and termin.benutzer_id == person.id:
            try:
                einladungsdienst.absagen(db, person, termin)
            except einladungsdienst.EinladungFehler as f:
                raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f
    try:
        dienst.entfernen(db, person, termin_id, vorkommen=vorkommen, umfang=umfang)
    except dienst.TerminFehler as f:
        raise _fehler(f) from f
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Verbinden und abonnieren (VOR /{kalender_id}) ------------------------ #


class Zugangswunsch(BaseModel):
    #: ``icloud`` und ``google`` bringen die Adresse selbst mit; sonst wird
    #: ``adresse`` genommen.
    art: str = "andere"
    adresse: str = ""
    benutzer: str = ""
    passwort: str = ""
    #: Statt eines Passworts: eine erteilte Zustimmung. ⚠️ **Google laesst nur
    #: das zu** — Basic Auth an seinem CalDAV-Endpunkt wird abgewiesen.
    oauth_zugang_id: str = ""


def _token(db, person, zugang_id: str) -> tuple[str, str]:
    """Zugriffstoken und Kontoadresse zu einer erteilten Zustimmung."""
    from ..models import OauthZugang
    from ..services import mailoauth

    if not zugang_id:
        return "", ""
    erlaubnis = db.get(OauthZugang, zugang_id)
    if erlaubnis is None or erlaubnis.benutzer_id != person.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="oauth_zugang_unbekannt"
        )
    try:
        return mailoauth.zugriffstoken(db, erlaubnis), erlaubnis.adresse
    except mailoauth.OauthFehler as f:
        raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f


class Gefunden(BaseModel):
    url: str
    name: str
    #: ⚠️ **Was schon dasteht, darf nicht noch einmal angeboten werden.** Ein
    #: Eintrag, dessen Auswahl nur in eine Absage fuehrt, ist eine Sackgasse
    #: mit Beschriftung — dieselbe Regel wie beim gesperrten Google-Eintrag.
    schon_verbunden: bool = False


@router.post("/pruefen", response_model=list[Gefunden])
def pruefen(
    wunsch: Zugangswunsch, person: AngemeldeterBenutzer, db: DbSession
) -> list[Gefunden]:
    """Welche Kalender liegen unter diesem Zugang?

    ⚠️ **Es wird nichts angelegt.** Ein CalDAV-Zugang liefert mehrere Kalender;
    welche davon nexmail holen soll, entscheidet der Betreiber danach.
    """
    token, adresse = _token(db, person, wunsch.oauth_zugang_id)
    try:
        gefunden = kalenderabgleich.finden(
            wunsch.art, wunsch.adresse, wunsch.benutzer or adresse, wunsch.passwort, token
        )
    except (caldav.CaldavFehler, kalenderabgleich.AbgleichFehler) as f:
        raise _fehler(f) from f
    bekannt = {k.url for k in dienst.liste(db, person) if k.url}
    return [
        Gefunden(url=k.url, name=k.name, schon_verbunden=k.url in bekannt) for k in gefunden
    ]


class Verbindungswunsch(Zugangswunsch):
    #: Die Adressen der Kalender, die wirklich geholt werden sollen.
    auswahl: list[Gefunden] = Field(default_factory=list)


@router.post("/verbinden", response_model=list[KalenderZeile])
def verbinden(
    wunsch: Verbindungswunsch, person: AngemeldeterBenutzer, db: DbSession
) -> list[KalenderZeile]:
    if not wunsch.auswahl:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="kalender_keine_auswahl"
        )
    token, adresse = _token(db, person, wunsch.oauth_zugang_id)
    herkunft = {
        "icloud": "iCloud",
        "google": "Google",
    }.get(wunsch.art) or (
        wunsch.adresse.split("/")[2] if "//" in wunsch.adresse else wunsch.adresse
    )
    try:
        neue = kalenderabgleich.verbinden(
            db, person,
            herkunft=herkunft,
            benutzer_name=wunsch.benutzer or adresse,
            passwort=wunsch.passwort,
            auswahl=[(g.url, g.name) for g in wunsch.auswahl],
            oauth_zugang_id=wunsch.oauth_zugang_id,
        )
        for kalender in neue:
            kalenderabgleich.abgleichen(db, kalender)
    except (caldav.CaldavFehler, kalenderabgleich.AbgleichFehler) as f:
        raise _fehler(f) from f
    return [_kalender(k) for k in neue]


class Abowunsch(BaseModel):
    url: str = Field(min_length=1)
    name: str = ""
    farbe: int = 0


@router.post("/abo", response_model=KalenderZeile, status_code=status.HTTP_201_CREATED)
def abonnieren(
    wunsch: Abowunsch, person: AngemeldeterBenutzer, db: DbSession
) -> KalenderZeile:
    """Einen veröffentlichten ICS-Link abonnieren. ⚠️ **Immer nur lesen.**"""
    try:
        kalender = kalenderabgleich.abonnieren(
            db, person, url=wunsch.url, name=wunsch.name, farbe=wunsch.farbe
        )
        kalenderabgleich.abgleichen(db, kalender)
    except (caldav.CaldavFehler, kalenderabgleich.AbgleichFehler) as f:
        raise _fehler(f) from f
    # ⚠️ Ein Abo, das gar nicht ging, wird wieder entfernt — sonst steht ein
    # toter Kalender in der Spalte und niemand weiss, warum er leer ist.
    if kalender.letzter_fehler:
        kennung = kalender.letzter_fehler
        db.delete(kalender)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=kennung)
    return _kalender(kalender)


class Abgleichbericht(BaseModel):
    neu: int = 0
    geaendert: int = 0
    entfernt: int = 0
    hochgeladen: int = 0
    #: Kalender, die dabei einen Fehler hatten — als Kennung je Kalender.
    fehler: dict[str, str] = Field(default_factory=dict)


@router.post("/abgleichen", response_model=Abgleichbericht)
def abgleichen(person: AngemeldeterBenutzer, db: DbSession) -> Abgleichbericht:
    """Jeden verbundenen Kalender einmal.

    ⚠️ **Ein Kalender, der klemmt, hält die anderen nicht auf** — sonst bringt
    eine falsche Adresse alles zum Stillstand.
    """
    bericht = Abgleichbericht()
    for kalender_id, runde in kalenderabgleich.alle_abgleichen(db, person).items():
        bericht.neu += runde.neu
        bericht.geaendert += runde.geaendert
        bericht.entfernt += runde.entfernt
        bericht.hochgeladen += runde.hochgeladen
    for kalender in dienst.liste(db, person):
        if kalender.letzter_fehler:
            bericht.fehler[kalender.id] = kalender.letzter_fehler
    return bericht


# --- Kalender ------------------------------------------------------------- #


@router.get("", response_model=list[KalenderZeile])
def liste(person: AngemeldeterBenutzer, db: DbSession) -> list[KalenderZeile]:
    return [_kalender(k) for k in dienst.liste(db, person)]


@router.post("", response_model=KalenderZeile, status_code=status.HTTP_201_CREATED)
def anlegen(
    wunsch: KalenderWunsch, person: AngemeldeterBenutzer, db: DbSession
) -> KalenderZeile:
    try:
        return _kalender(dienst.kalender_anlegen(db, person, wunsch.name, wunsch.farbe))
    except dienst.TerminFehler as f:
        raise _fehler(f) from f


@router.patch("/{kalender_id}", response_model=KalenderZeile)
def aendern(
    kalender_id: str,
    aenderung: KalenderAenderung,
    person: AngemeldeterBenutzer,
    db: DbSession,
) -> KalenderZeile:
    try:
        return _kalender(
            dienst.kalender_aendern(
                db, person, kalender_id,
                name=aenderung.name, farbe=aenderung.farbe, sichtbar=aenderung.sichtbar,
            )
        )
    except dienst.TerminFehler as f:
        raise _fehler(f) from f


class Weg(BaseModel):
    termine: int


@router.delete("/{kalender_id}", response_model=Weg)
def entfernen(kalender_id: str, person: AngemeldeterBenutzer, db: DbSession) -> Weg:
    """Mit allem, was darin liegt.

    ⚠️ **Bei einer Gegenstelle wird dort nichts geloescht.** Der Kalender
    verschwindet aus nexmail; auf dem Server bleibt er — die vorsichtige
    Richtung, und die Oberflaeche sagt es, bevor sie fragt.
    """
    try:
        return Weg(termine=dienst.kalender_entfernen(db, person, kalender_id))
    except dienst.TerminFehler as f:
        raise _fehler(f) from f
