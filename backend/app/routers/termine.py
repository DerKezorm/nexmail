"""Termin-Einladungen: anzeigen und beantworten.

⚠️ **nexmail hat keinen Kalender.** Eine Zusage sagt dem Einladenden Bescheid,
sie legt den Termin nirgends ab. Gemerkt wird nur, **wie** geantwortet wurde —
damit die Einladung beim zweiten Öffnen nicht aussieht wie beim ersten.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..db import einstellung_lesen
from ..deps import AngemeldeterBenutzer, DbSession
from ..meldung import Meldung
from ..models import Anhang, Konto, MailTermin, Nachricht, Terminantwort
from ..services import (
    kalender,
    konten as kontendienst,
    nextime,
    nextimeverbindung,
    senden as sendedienst,
    termineinladung,
    verfassen,
)
from ..services.aliase import lesen as aliase_lesen
from .einstellungen import SCHLUESSEL_ZEITZONE
from ..meldung import MeldungHttp

logger = logging.getLogger("nexmail.termine")

router = APIRouter(prefix="/api/termine", tags=["termine"])

#: Wie lange die Karte auf nextime wartet. ⚠️ **Kurz** (Prüfbericht, Befund 6):
#: Die Mail steht schon da; ein langsames nextime soll sie nicht aufhalten.
KARTE_FRIST = 5.0

_SCHLOESSER: dict[str, threading.Lock] = {}
_SCHLOESSER_SCHLOSS = threading.Lock()


@contextmanager
def _nacheinander(schluessel: str):
    """Ein Schloss je Benutzer und Einladung bzw. Mail.

    ⚠️ **Gegen den Doppelklick im Server** (Prüfbericht, Befunde 4 und 12):
    Zwei gleichzeitige Zusagen fänden beide nichts in nextime, beide trügen
    ein, und es gingen zwei Antworten an den Organisator. Nacheinander sieht
    die zweite, was die erste getan hat.
    """
    with _SCHLOESSER_SCHLOSS:
        schloss = _SCHLOESSER.setdefault(schluessel, threading.Lock())
    with schloss:
        yield


#: Woran man eine Einladung im Anhang erkennt.
KALENDER_TYPEN = ("text/calendar", "application/ics")


class PersonZeile(BaseModel):
    name: str = ""
    adresse: str = ""


class Einladung(BaseModel):
    uid: str
    methode: str
    titel: str
    beschreibung: str
    ort: str
    beginn: str
    ende: str
    ganztaegig: bool
    #: Gesetzt, wenn die Zeitzone der Einladung unbekannt war. Die Zeit steht
    #: dann so da, wie sie kam — die Oberfläche nennt den Namen dazu.
    fremde_zeitzone: str
    wiederholt_sich: bool
    abgesagt: bool
    organisator: PersonZeile
    teilnehmer: list[PersonZeile]
    #: Was zuletzt geantwortet wurde: ``zusage`` | ``vorbehalt`` | ``absage``.
    antwort: str = ""
    antwort_am: datetime | None = None
    #: Gesetzt, wenn dieser Termin schon in einem Kalender liegt — dann
    #: bietet die Karte das Uebernehmen nicht noch einmal an.
    im_kalender: bool = False
    #: Der Stand in nextime, wenn nextime verbunden ist (MAIL-1).
    nextime: "NextimeLage | None" = None


class Treffer(BaseModel):
    """Ein Termin zur selben Zeit (MAIL-1 AC-12)."""

    titel: str
    beginn: datetime
    ende: datetime
    ganztaegig: bool
    kalender: str


class NextimeLage(BaseModel):
    """Was nextime über diese Einladung weiß.

    ⚠️ **``fehler`` statt einer Absage**: Ist nextime gerade nicht zu
    sprechen, soll die Karte trotzdem erscheinen, nur ohne diesen Teil.
    """

    fehler: str = ""
    #: Steht die UID schon in nextime? Dann hier der Termin.
    termin_id: int | None = None
    kalender_id: str = ""
    kalender_name: str = ""
    link: str = ""
    #: ``zusage`` | ``vorbehalt`` | ``absage`` | leer (offen).
    antwort: str = ""
    #: Aus einer Mail eingetragen (``origin`` = ``imip``); nur dann darf nexmail
    #: ihn bei einer Absage entfernen oder aktualisieren.
    aus_mail: bool = False
    #: Was die Mail anders sagt als der Termin in nextime: ``titel``,
    #: ``zeit``, ``ort`` (AC-11).
    abweichungen: list[str] = []
    ueberschneidungen: list[Treffer] = []
    #: Der Kalender, der für dieses Postfach zuletzt gewählt wurde (AC-5).
    vorwahl: str = ""


class AntwortEingabe(BaseModel):
    antwort: str
    #: Mit nextime: in welchen Kalender die Zusage den Termin legt
    #: (``nt:<id>`` oder ein eigener). Leer heißt: nur antworten.
    kalender_id: str = ""


def _kalenderteil(db, nachricht: Nachricht) -> bytes | None:
    """Die ``.ics`` aus den Anhängen — oder ``None``."""
    ordner = get_settings().blob_dir
    for anhang in nachricht.anhaenge:
        typ = (anhang.mime or "").split(";")[0].strip().lower()
        endung = (anhang.dateiname or "").lower().endswith(".ics")
        if typ not in KALENDER_TYPEN and not endung:
            continue
        if not anhang.blob_hash:
            continue
        datei = ordner / anhang.blob_hash
        if datei.is_file():
            return datei.read_bytes()
    return None


def _meine(db, person, nachricht_id: int) -> Nachricht:
    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return nachricht


def _einladung(db, person, nachricht: Nachricht) -> tuple[kalender.Termin, Einladung] | None:
    roh = _kalenderteil(db, nachricht)
    if roh is None:
        return None
    zeitzone = einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone
    termin = kalender.lesen(roh, zeitzone)
    if termin is None:
        return None

    gemerkt = db.scalars(
        select(Terminantwort).where(
            Terminantwort.benutzer_id == person.id, Terminantwort.uid == termin.uid
        )
    ).first()

    return termin, Einladung(
        uid=termin.uid,
        methode=termin.methode,
        titel=termin.titel,
        beschreibung=termin.beschreibung,
        ort=termin.ort,
        beginn=termin.beginn,
        ende=termin.ende,
        ganztaegig=termin.ganztaegig,
        fremde_zeitzone=termin.fremde_zeitzone,
        wiederholt_sich=termin.wiederholt_sich,
        abgesagt=termin.abgesagt,
        organisator=PersonZeile(
            name=termin.organisator.name, adresse=termin.organisator.adresse
        ),
        teilnehmer=[PersonZeile(name=t.name, adresse=t.adresse) for t in termin.teilnehmer],
        antwort=gemerkt.antwort if gemerkt else "",
        antwort_am=gemerkt.gesendet if gemerkt else None,
        im_kalender=_liegt_im_kalender(db, person, termin.uid),
    )


def _liegt_im_kalender(db, person, uid: str) -> bool:
    from ..models import Kalender, Termin as Kalendertermin

    if not uid:
        return False
    return db.scalar(
        select(Kalendertermin.id)
        .join(Kalender)
        .where(Kalender.benutzer_id == person.id, Kalendertermin.uid == uid)
        .limit(1)
    ) is not None


class Uebernahme(BaseModel):
    kalender_id: str = ""


def _lokal_uebernehmen(db, person, termin: kalender.Termin, kalender_id: str) -> None:
    """Den Termin einer Einladung in einen eigenen Kalender legen.

    ⚠️ **Der Termin behält die ``UID`` der Einladung.** Daran erkennt jeder
    andere Client denselben Termin wieder — und daran sieht die Karte beim
    zweiten Öffnen, dass er schon drin ist.
    """
    from ..services import termine as kalenderdienst

    if not kalender_id:
        # Der erste beschreibbare Kalender. ⚠️ Ein Abo kann nichts aufnehmen.
        offene = [k for k in kalenderdienst.liste(db, person) if not k.nur_lesen]
        if not offene:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="kalender_fehlt"
            )
        kalender_id = offene[0].id
    try:
        neu = kalenderdienst.anlegen(
            db, person, kalender_id,
            titel=termin.titel or "",
            beginn=_als_zeit(termin.beginn, termin.ganztaegig),
            ende=_als_zeit(termin.ende, termin.ganztaegig) if termin.ende else None,
            ganztaegig=termin.ganztaegig,
            ort=termin.ort or "",
            beschreibung=termin.beschreibung or "",
            aus_einladung=True,
            # ⚠️ **Was die Einladung ausmacht, geht mit.** Ohne den
            # Organisator und die Teilnehmer waere der uebernommene Termin ein
            # Titel mit Uhrzeit — und im Kalender saehe niemand mehr, mit wem.
            organisator=(
                json.dumps({
                    "name": termin.organisator.name,
                    "adresse": termin.organisator.adresse,
                    "antwort": "", "rolle": "",
                })
                if termin.organisator
                else ""
            ),
            teilnehmer=(
                json.dumps([
                    {"name": t.name, "adresse": t.adresse, "antwort": "", "rolle": ""}
                    for t in termin.teilnehmer
                ])
                if termin.teilnehmer
                else ""
            ),
        )
        # ⚠️ Die UID der Einladung uebernehmen, nicht eine neue erfinden.
        neu.uid = termin.uid or neu.uid
        db.commit()
    except kalenderdienst.TerminFehler as f:
        raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f


@router.post("/{nachricht_id}/uebernehmen", response_model=Einladung)
def uebernehmen(
    nachricht_id: int, eingabe: Uebernahme, person: AngemeldeterBenutzer, db: DbSession
) -> Einladung:
    """Den Termin aus der Einladung in einen Kalender übernehmen.

    ⚠️ **Auf Klick, nicht automatisch beim Zusagen.** Wer zusagt, ohne den
    Termin wirklich zu wollen, soll ihn nicht im Kalender wiederfinden. (Mit
    nextime gilt Zusagen samt Kalenderwahl in einem Schritt, MAIL-1 AC-10;
    dieser Weg bleibt für alle ohne nextime.)
    """
    nachricht = _meine(db, person, nachricht_id)
    gefunden = _einladung(db, person, nachricht)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="termin_unbekannt")
    termin, sicht = gefunden
    if eingabe.kalender_id.startswith(nextimeverbindung.VORSILBE):
        # Über nextime eintragen heißt antworten — dafür ist ``antwort`` da.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kalender_unbekannt")
    _lokal_uebernehmen(db, person, termin, eingabe.kalender_id)
    sicht.im_kalender = True
    return sicht


def _als_zeit(wert: str, ganztaegig: bool) -> datetime:
    """Die ISO-Zeichenkette der Einladung als Zeitpunkt."""
    if ganztaegig and len(wert) == 10:
        return datetime.fromisoformat(f"{wert}T00:00:00+00:00")
    wann = datetime.fromisoformat(wert)
    return wann if wann.tzinfo else wann.replace(tzinfo=timezone.utc)


# --- nextime (MAIL-1) ---------------------------------------------------------- #


def _zeitraum(termin: kalender.Termin) -> tuple[datetime, datetime] | None:
    """Beginn und Ende der Einladung als Zeitpunkte; ganztägig bis zum Folgetag."""
    if not termin.beginn:
        return None
    try:
        beginn = _als_zeit(termin.beginn, termin.ganztaegig)
        ende = _als_zeit(termin.ende, termin.ganztaegig) if termin.ende else None
    except ValueError:
        return None
    if ende is None or ende <= beginn:
        ende = beginn + (timedelta(days=1) if termin.ganztaegig else timedelta(hours=1))
    return beginn, ende


def _gefunden(z: nextime.Zugang, uid: str, frist: float | None = None) -> dict | None:
    """Der Termin dieser UID in nextime. ⚠️ **Der aus der Quelle geht vor** dem
    aus einer Mail: nextime räumt die Mail-Kopie ohnehin weg, sobald die
    Quelle ihn bringt (EC-14)."""
    treffer = [e for e in nextime.nach_uid(z, uid, frist=frist) if isinstance(e.get("id"), int)]
    if not treffer:
        return None
    treffer.sort(key=lambda e: 1 if e.get("origin") == "imip" else 0)
    return treffer[0]


def _abweichungen(termin: kalender.Termin, e: dict) -> list[str]:
    """Was die Mail anders sagt als nextime (AC-11). Nur bei Mail-Kopien gefragt."""
    raus = []
    if (termin.titel or "").strip() != str(e.get("title") or "").strip():
        raus.append("titel")
    zeit = _zeitraum(termin)
    ganz = bool(e.get("all_day"))
    beginn = nextimeverbindung.von_nextime(e.get("start"), ganz)
    ende = nextimeverbindung.von_nextime(e.get("end") or e.get("start"), ganz, ende=True)
    if zeit is not None and (beginn != zeit[0] or ende != zeit[1] or ganz != termin.ganztaegig):
        raus.append("zeit")
    if (termin.ort or "").strip() != str(e.get("location") or "").strip():
        raus.append("ort")
    return raus


def _ueberschneidungen(db, person, z, termin: kalender.Termin, namen: dict[str, str]) -> list[Treffer]:
    """Termine aus nextime und nexmail zur selben Zeit (AC-12), ohne die
    Einladung selbst. ⚠️ **Nur Termine, die belegen**: Feiertage und andere
    Hintergrundkalender sind keine Überschneidung."""
    zeit = _zeitraum(termin)
    if zeit is None:
        return []
    from ..services import termine as kalenderdienst

    raus: list[Treffer] = []
    nummern = [int(k[len(nextimeverbindung.VORSILBE):]) for k in namen]
    for e in nextime.termine(z, nextimeverbindung._iso(zeit[0]), nextimeverbindung._iso(zeit[1]), nummern,
                             frist=KARTE_FRIST):
        if (termin.uid and e.get("uid") == termin.uid) or e.get("background") or e.get("busy") is False:
            continue
        ganz = bool(e.get("all_day"))
        b = nextimeverbindung.von_nextime(e.get("start"), ganz)
        n = nextimeverbindung.von_nextime(e.get("end") or e.get("start"), ganz, ende=True)
        if b is None or n is None or not (b < zeit[1] and n > zeit[0]):
            continue
        raus.append(Treffer(
            titel="" if e.get("busy_only") else str(e.get("title") or ""),
            beginn=b, ende=n, ganztaegig=ganz,
            kalender=namen.get(f"{nextimeverbindung.VORSILBE}{e.get('calendar_id')}", ""),
        ))
    for s in kalenderdienst.fenster(db, person, zeit[0], zeit[1], None):
        if (termin.uid and s.termin.uid == termin.uid) or not (s.beginn < zeit[1] and s.ende > zeit[0]):
            continue
        raus.append(Treffer(titel=s.termin.titel, beginn=s.beginn, ende=s.ende,
                            ganztaegig=s.termin.ganztaegig, kalender=s.termin.kalender.name))
    raus.sort(key=lambda t: t.beginn)
    return raus[:10]


def _nextime_lage(db, person, nachricht: Nachricht, termin: kalender.Termin) -> NextimeLage | None:
    """Der Teil der Karte, den nextime beisteuert — ``None`` ohne Verbindung.

    ⚠️ **Scheitert nextime, scheitert nicht die Karte**: Sie zeigt dann die
    Einladung wie ohne nextime und sagt, warum der Teil fehlt (EC-1).
    """
    v = nextimeverbindung.verbindung(db, person)
    if v is None:
        return None
    lage = NextimeLage(vorwahl=nextimeverbindung.vorwahl_lesen(person).get(nachricht.konto_id or "", ""))
    try:
        z = nextimeverbindung.zugang(v)
        liste = nextimeverbindung.kalender_liste(v, nextime.kalender(z, frist=KARTE_FRIST))
        namen = {k.id: k.name for k in liste}
        e = _gefunden(z, termin.uid, frist=KARTE_FRIST) if termin.uid else None
        if e is not None:
            lage.termin_id = e["id"]
            lage.kalender_id = f"{nextimeverbindung.VORSILBE}{e.get('calendar_id')}"
            lage.kalender_name = namen.get(lage.kalender_id, "")
            lage.link = nextime.link(e.get("web_url"))
            lage.antwort = nextimeverbindung.ANTWORT_VON_NEXTIME.get(str(e.get("invitation") or ""), "")
            lage.aus_mail = e.get("origin") == "imip"
            if lage.aus_mail and not termin.abgesagt:
                lage.abweichungen = _abweichungen(termin, e)
        if not termin.abgesagt:
            # ⚠️ Nur aus sichtbaren Kalendern (Befund 11): Was man in nexmail
            # ausgeblendet hat, soll nicht als „zur selben Zeit" auftauchen.
            sichtbare = {k.id: k.name for k in liste if k.sichtbar}
            lage.ueberschneidungen = _ueberschneidungen(db, person, z, termin, sichtbare)
    except Meldung as f:
        nextimeverbindung.fehler_merken(db, v, f)
        lage.fehler = f.kennung
    return lage


def _mit_lage(db, person, nachricht: Nachricht) -> Einladung | None:
    gefunden = _einladung(db, person, nachricht)
    if gefunden is None:
        return None
    termin, sicht = gefunden
    sicht.nextime = _nextime_lage(db, person, nachricht, termin)
    return sicht


@router.get("/{nachricht_id}", response_model=Einladung | None)
def einladung(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Einladung | None:
    """Die Einladung in dieser Nachricht — oder ``null``."""
    nachricht = _meine(db, person, nachricht_id)
    return _mit_lage(db, person, nachricht)


def _antwort_merken(db, person, uid: str, antwort: str) -> None:
    gemerkt = db.scalars(
        select(Terminantwort).where(
            Terminantwort.benutzer_id == person.id, Terminantwort.uid == uid
        )
    ).first()
    if gemerkt is None:
        gemerkt = Terminantwort(benutzer_id=person.id, uid=uid, antwort=antwort)
        db.add(gemerkt)
    else:
        # ⚠️ Umentscheiden ist erlaubt — und dann gilt die neue Antwort samt
        # neuem Zeitpunkt, sonst steht dort für immer die erste.
        gemerkt.antwort = antwort
        gemerkt.gesendet = datetime.now(timezone.utc)
    db.commit()


def _antwort_mailen(db, person, nachricht: Nachricht, termin: kalender.Termin, antwort: str) -> None:
    """Die Antwort an den Einladenden, als Mail aus dem Postfach der Einladung.

    ⚠️ **Die Antwort geht an den Einladenden, nicht an alle Teilnehmer.** Wer
    allen antwortet, macht aus einer Zusage eine Rundmail.
    """
    konto = db.get(Konto, nachricht.konto_id)
    ich = kalender.Person(name=kontendienst.absendername(konto), adresse=konto.adresse)
    ics = kalender.antwort_bauen(termin, ich, antwort, datetime.now(timezone.utc))
    vorsatz = {"zusage": "Zugesagt", "vorbehalt": "Mit Vorbehalt", "absage": "Abgesagt"}[antwort]
    zeile = sendedienst.einreihen(
        db,
        konto,
        verfassen.Entwurf(
            von_name=ich.name,
            von_adresse=ich.adresse,
            an=[termin.organisator.adresse],
            betreff=f"{vorsatz}: {termin.titel}".strip(),
            # ⚠️ **Auch ein Satz im Text.** Ein Empfänger ohne
            # Kalenderunterstützung sähe sonst eine leere Mail.
            text=f"{vorsatz}: {termin.titel}".strip(),
            html="",
            kalender=ics,
            kalender_methode="REPLY",
        ),
    )
    _antwort_merken(db, person, termin.uid, antwort)
    # ⚠️ Erst gemerkt, dann gesendet: Scheitert der Versand, bleibt die Antwort
    # im Ausgang und die Karte sagt trotzdem, was entschieden wurde.
    termineinladung.hinausschicken(db, zeile)


def _eigene_adresse(db, nachricht: Nachricht, termin: kalender.Termin) -> str:
    """Unter welcher Adresse man eingeladen ist: das Postfach oder einer seiner
    Aliasse, sofern er unter den Teilnehmern steht. Sonst leer (nextime nimmt
    dann die Adressen des Kontos)."""
    konto = db.get(Konto, nachricht.konto_id)
    if konto is None:
        return ""
    eigene = {konto.adresse.lower()} | {a.adresse.lower() for a in aliase_lesen(konto)}
    for t in termin.teilnehmer:
        if t.adresse.lower() in eigene:
            return t.adresse.lower()
    return ""


def _ical_text(db, nachricht: Nachricht) -> str:
    roh = _kalenderteil(db, nachricht) or b""
    return roh.decode("utf-8", errors="replace")


@router.post("/{nachricht_id}/antwort", response_model=Einladung)
def antworten(
    nachricht_id: int, eingabe: AntwortEingabe, person: AngemeldeterBenutzer, db: DbSession
) -> Einladung:
    """Zusagen, mit Vorbehalt zusagen oder absagen.

    Mit nextime (MAIL-1 AC-9, AC-10, EC-15, EC-16):

    * **Steht die Einladung schon in nextime**, antwortet nexmail über nextime.
      Sagt nextime ``reply_by: source``, schickt iCloud bzw. Google die Antwort,
      und nexmail schickt ⚠️ **keine** eigene, sonst käme sie doppelt an.
    * **Sonst** trägt eine Zusage den Termin in den gewählten Kalender ein, in
      einem Schritt, und nexmail schickt die Antwort per Mail. nextime schickt
      dabei nichts.
    * **Absagen** trägt nichts ein.
    """
    if eingabe.antwort not in kalender.ANTWORTEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="termin_antwort_unbekannt"
        )

    nachricht = _meine(db, person, nachricht_id)
    gefunden = _einladung(db, person, nachricht)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="termin_fehlt")
    termin, _ = gefunden
    if not termin.organisator.adresse:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="termin_ohne_einladenden"
        )

    v = nextimeverbindung.verbindung(db, person)
    ziel = eingabe.kalender_id
    eintragen = bool(ziel) and eingabe.antwort != "absage"
    if v is None or not termin.uid:
        if eintragen and not ziel.startswith(nextimeverbindung.VORSILBE):
            _lokal_uebernehmen(db, person, termin, ziel)
        _antwort_mailen(db, person, nachricht, termin, eingabe.antwort)
        logger.info("An invitation was answered (%s).", eingabe.antwort)
        return _mit_lage(db, person, nachricht)

    from .nextime import http as nextime_http

    with _nacheinander(f"antwort:{person.id}:{termin.uid}"):
        return _antworten_mit_nextime(db, person, nachricht, termin, v, eingabe, nextime_http)


def _antworten_mit_nextime(db, person, nachricht, termin, v, eingabe, nextime_http) -> Einladung:
    """Der Teil von ``antworten``, der nextime fragt — unter dem Schloss."""
    ziel = eingabe.kalender_id
    eintragen = bool(ziel) and eingabe.antwort != "absage"
    antwort_nt = nextimeverbindung.ANTWORT_NACH_NEXTIME[eingabe.antwort]
    mailen = True
    try:
        z = nextimeverbindung.zugang(v)
        vorhanden = _gefunden(z, termin.uid)
        if vorhanden is not None:
            ergebnis = nextime.antworten(z, vorhanden["id"], antwort_nt)
            mailen = ergebnis.get("reply_by") != "source"
            if mailen and ergebnis.get("changed") is False:
                # ⚠️ **Dieselbe Antwort noch einmal schickt nichts Zweites**
                # (EC-15): nextime hat nichts geändert, also war sie schon da.
                gemerkt = db.scalars(select(Terminantwort).where(
                    Terminantwort.benutzer_id == person.id, Terminantwort.uid == termin.uid)).first()
                mailen = gemerkt is None or gemerkt.antwort != eingabe.antwort
        elif eintragen and ziel.startswith(nextimeverbindung.VORSILBE):
            ergebnis = nextime.ical_eintragen(
                z, _ical_text(db, nachricht),
                kalender_id=nextimeverbindung.kalender_id(ziel), antwort=antwort_nt,
                teilnehmer=_eigene_adresse(db, nachricht, termin),
            )
            if ergebnis.get("reply_by") == "source":
                # Die Quelle kannte ihn schon (``existing``): dort antworten.
                event = ergebnis.get("event") or {}
                if isinstance(event.get("id"), int):
                    nextime.antworten(z, event["id"], antwort_nt)
                mailen = False
            nextimeverbindung.vorwahl_merken(db, person, nachricht.konto_id or "", ziel)
        elif eintragen:
            _lokal_uebernehmen(db, person, termin, ziel)
            nextimeverbindung.vorwahl_merken(db, person, nachricht.konto_id or "", ziel)
    except Meldung as f:
        nextimeverbindung.fehler_merken(db, v, f)
        raise nextime_http(f) from f

    if mailen:
        _antwort_mailen(db, person, nachricht, termin, eingabe.antwort)
    else:
        _antwort_merken(db, person, termin.uid, eingabe.antwort)
    logger.info(
        "An invitation was answered (%s, reply by %s).", eingabe.antwort, "mail" if mailen else "source"
    )
    return _mit_lage(db, person, nachricht)


def _mail_kopie(db, person, nachricht: Nachricht) -> tuple[kalender.Termin, nextime.Zugang, dict]:
    """Einladung und ihre Kopie aus einer Mail in nextime — oder eine Absage.

    ⚠️ **Nur eine Kopie aus einer Mail fasst nexmail an.** Einen Termin aus
    iCloud oder Google ändert und streicht die Quelle selbst.
    """
    gefunden = _einladung(db, person, nachricht)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="termin_fehlt")
    termin, _ = gefunden
    _v, z = nextimeverbindung.gebraucht(db, person)
    vorhanden = _gefunden(z, termin.uid) if termin.uid else None
    if vorhanden is None or vorhanden.get("origin") != "imip":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="nextime_nicht_aus_mail")
    return termin, z, vorhanden


@router.post("/{nachricht_id}/nextime-entfernen", response_model=Einladung)
def nextime_entfernen(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Einladung:
    """Eine abgesagte Einladung aus nextime nehmen — erst auf Klick (AC-18)."""
    from .nextime import http as nextime_http

    nachricht = _meine(db, person, nachricht_id)
    try:
        termin, z, _vorhanden = _mail_kopie(db, person, nachricht)
        if not termin.abgesagt:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="termin_nicht_abgesagt")
        nextime.ical_eintragen(z, _ical_text(db, nachricht), kalender_id=None, antwort=None)
    except Meldung as f:
        raise nextime_http(f) from f
    logger.info("A cancelled invitation was removed from nextime.")
    return _mit_lage(db, person, nachricht)


@router.post("/{nachricht_id}/nextime-aktualisieren", response_model=Einladung)
def nextime_aktualisieren(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Einladung:
    """Eine geänderte Einladung in die Mail-Kopie in nextime übernehmen (AC-11).

    ⚠️ **Die eigene Antwort bleibt**, wie sie in nextime steht; eine
    Aktualisierung ist keine neue Zusage, und es geht keine Mail hinaus.
    """
    from .nextime import http as nextime_http

    nachricht = _meine(db, person, nachricht_id)
    try:
        termin, z, vorhanden = _mail_kopie(db, person, nachricht)
        antwort = str(vorhanden.get("invitation") or "")
        if antwort not in nextimeverbindung.ANTWORT_VON_NEXTIME:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="nextime_erst_antworten")
        nextime.ical_eintragen(
            z, _ical_text(db, nachricht), kalender_id=vorhanden.get("calendar_id"), antwort=antwort,
            teilnehmer=_eigene_adresse(db, nachricht, termin),
        )
    except Meldung as f:
        raise nextime_http(f) from f
    logger.info("An updated invitation was taken into nextime.")
    return _mit_lage(db, person, nachricht)


# --- Termin aus einer Mail (MAIL-1 AC-17) ----------------------------------------- #

#: Wie viel vom Text der Mail in die Notiz geht.
NOTIZ_HOECHSTENS = 20_000


class AusMailWunsch(BaseModel):
    kalender_id: str = Field(max_length=64)
    titel: str = Field(max_length=2000)
    beginn: datetime
    ende: datetime | None = None
    ganztaegig: bool = False
    ort: str = Field(default="", max_length=2000)
    #: Eigener Schlüssel dieses Fensters: Ein Doppelklick legt nichts Zweites
    #: an (EC-15), in nextime über ``client_ref``.
    anfrage: str = Field(default="", max_length=40)


class MailTerminZeile(BaseModel):
    id: int
    kalender: str
    titel: str
    beginn: datetime
    ganztaegig: bool
    link: str


class AusMail(BaseModel):
    #: Der für dieses Postfach zuletzt gewählte Kalender (AC-5), leer ohne.
    vorwahl: str
    termine: list[MailTerminZeile]


def _notiz(db, nachricht: Nachricht) -> str:
    """Absender, Datum und Text der Mail als Notiz (AC-17, EC-21).

    ⚠️ **Gekürzt, und Anhänge gehen nicht mit.** Ein Newsletter mit 300 KB
    Text wäre in nextime keine Notiz mehr, sondern ein Klotz.
    """
    zeitzone = einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone
    datum = nachricht.datum
    if datum is not None:
        try:
            datum = datum.astimezone(ZoneInfo(zeitzone))
        except (ValueError, KeyError):
            pass
    von = nachricht.von_adresse or ""
    if nachricht.von_name:
        von = f"{nachricht.von_name} <{von}>"
    kopf = [f"From: {von}"] if von else []
    if datum is not None:
        kopf.append(f"Date: {datum.strftime('%Y-%m-%d %H:%M')}")
    if nachricht.betreff:
        kopf.append(f"Subject: {nachricht.betreff}")
    text = (nachricht.koerper_text or nachricht.anreisser or "").strip()
    if len(text) > NOTIZ_HOECHSTENS:
        text = text[:NOTIZ_HOECHSTENS].rstrip() + " …"
    return "\n".join(kopf) + ("\n\n" + text if text else "")


def _aus_mail(db, person, nachricht: Nachricht) -> AusMail:
    zeilen = []
    if nachricht.message_id:
        zeilen = list(db.scalars(
            select(MailTermin)
            .where(MailTermin.benutzer_id == person.id, MailTermin.message_id == nachricht.message_id)
            .order_by(MailTermin.angelegt, MailTermin.id)
        ))
    return AusMail(
        vorwahl=nextimeverbindung.vorwahl_lesen(person).get(nachricht.konto_id or "", ""),
        termine=[MailTerminZeile(id=z.id, kalender=z.kalender, titel=z.titel, beginn=z.beginn,
                                 ganztaegig=z.ganztaegig, link=z.link) for z in zeilen],
    )


@router.get("/{nachricht_id}/aus-mail", response_model=AusMail)
def aus_mail(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> AusMail:
    """Welche Termine aus dieser Mail entstanden sind, und welcher Kalender vorgewählt ist."""
    return _aus_mail(db, person, _meine(db, person, nachricht_id))


@router.post("/{nachricht_id}/aus-mail", response_model=AusMail, status_code=status.HTTP_201_CREATED)
def termin_aus_mail(
    nachricht_id: int, wunsch: AusMailWunsch, person: AngemeldeterBenutzer, db: DbSession
) -> AusMail:
    """Aus einer Mail einen Termin machen, in nextime oder einem eigenen Kalender.

    ⚠️ **Mehrere Termine aus einer Mail sind gewollt**, nur ein Doppelklick
    zählt einmal: über ``anfrage``, und in nextime zusätzlich über
    ``client_ref``.
    """
    nachricht = _meine(db, person, nachricht_id)
    titel = wunsch.titel.strip() or (nachricht.betreff or "").strip()
    if not titel:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="termin_ohne_titel")
    with _nacheinander(f"aus-mail:{person.id}:{wunsch.anfrage or nachricht.id}"):
        return _termin_aus_mail(db, person, nachricht, wunsch, titel)


def _termin_aus_mail(db, person, nachricht: Nachricht, wunsch: AusMailWunsch, titel: str) -> AusMail:
    """Der Teil von ``termin_aus_mail`` unter dem Schloss."""
    from ..services import termine as kalenderdienst
    from .nextime import http as nextime_http

    if wunsch.anfrage and nachricht.message_id:
        schon = db.scalars(select(MailTermin).where(
            MailTermin.benutzer_id == person.id, MailTermin.message_id == nachricht.message_id,
            MailTermin.anfrage == wunsch.anfrage)).first()
        if schon is not None:
            return _aus_mail(db, person, nachricht)

    notiz = _notiz(db, nachricht)
    link = ""
    if wunsch.kalender_id.startswith(nextimeverbindung.VORSILBE):
        try:
            s = nextimeverbindung.anlegen(
                db, person, wunsch.kalender_id,
                nextimeverbindung.Eingabe(titel=titel, beginn=wunsch.beginn, ende=wunsch.ende,
                                          ganztaegig=wunsch.ganztaegig, ort=wunsch.ort, beschreibung=notiz),
                client_ref=f"nexmail:{wunsch.anfrage}" if wunsch.anfrage else "",
            )
        except Meldung as f:
            raise nextime_http(f) from f
        link = s.fern.link
        beginn = s.beginn
    else:
        try:
            neu = kalenderdienst.anlegen(
                db, person, wunsch.kalender_id, titel=titel, beginn=wunsch.beginn, ende=wunsch.ende,
                ganztaegig=wunsch.ganztaegig, ort=wunsch.ort, beschreibung=notiz,
            )
        except kalenderdienst.TerminFehler as f:
            raise MeldungHttp.aus(f, status.HTTP_400_BAD_REQUEST) from f
        beginn = neu.beginn

    if nachricht.message_id:
        db.add(MailTermin(benutzer_id=person.id, message_id=nachricht.message_id,
                          kalender=wunsch.kalender_id, titel=titel, beginn=beginn,
                          ganztaegig=wunsch.ganztaegig, link=link, anfrage=wunsch.anfrage))
        db.commit()
    nextimeverbindung.vorwahl_merken(db, person, nachricht.konto_id or "", wunsch.kalender_id)
    logger.info("An event was made from a mail (%s).", "nextime" if link else "nexmail")
    return _aus_mail(db, person, nachricht)
