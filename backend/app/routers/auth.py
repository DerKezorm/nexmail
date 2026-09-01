"""Anmelden, zweiter Faktor, abmelden.

Der Ablauf hat zwei Schritte, und das ist Absicht:

    Passwort  ->  halbe Sitzung  ->  Code  ->  volle Sitzung

⚠️ **Der zweite Schritt verraet nie, ob das Passwort richtig war.** Er
antwortet auf einen falschen Code immer gleich, egal ob dahinter ein Konto
steht. Und der erste Schritt setzt zwar ein Cookie, aber eines, mit dem man
ausser dem zweiten Schritt nichts aufrufen kann.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import AktiveSitzung, AngemeldeterBenutzer, DbSession, HalbeSitzung
from ..services import anmeldebremse
from ..services import benutzer as benutzerdienst
from ..services import sitzung as sitzungsdienst
from ..services import zwei_faktor

logger = logging.getLogger("nexmail.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Anmeldung(BaseModel):
    benutzername: str = Field(min_length=1, max_length=64)
    passwort: str = Field(min_length=1, max_length=200)


class Codeeingabe(BaseModel):
    code: str = Field(min_length=4, max_length=20)


class Schritt(BaseModel):
    #: "fertig" | "code" | "einrichten"
    schritt: str


class Einrichtung(BaseModel):
    geheimnis: str
    otpauth: str
    qr_svg: str


class Ich(BaseModel):
    id: str
    benutzername: str
    anzeigename: str
    ist_betreiber: bool
    zwei_faktor_aktiv: bool
    offene_codes: int


@router.post("/anmelden", response_model=Schritt)
def anmelden(
    eingabe: Anmeldung, request: Request, response: Response, db: DbSession
) -> Schritt:
    """Schritt eins: das Passwort.

    Bei Erfolg entsteht eine **halbe** Sitzung. Sie laeuft nach wenigen
    Minuten ab und darf nur den zweiten Schritt aufrufen.
    """
    wache = anmeldebremse.torwaechter(request, "anmelden", eingabe.benutzername)

    person = benutzerdienst.finden(db, eingabe.benutzername)
    if person is None or not benutzerdienst.passwort_stimmt(person, eingabe.passwort):
        wache.fehlgeschlagen()
        # Dieselbe Antwort fuer "kein solches Konto" und "falsches Passwort".
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzername oder Passwort stimmt nicht.",
        )

    wache.geschafft()
    benutzerdienst.hash_auffrischen(db, person, eingabe.passwort)

    # ⚠️ Der Nothammer. Er ueberspringt den zweiten Faktor vollstaendig -
    # gedacht fuer den Fall, dass Telefon und Wiederherstellungscodes weg sind.
    if get_settings().zwei_faktor_aus:
        sitzungsdienst.anlegen(db, person, request, response, bestaetigt=True)
        logger.warning("Signed in with the second factor disabled (NEXMAIL_2FA_AUS).")
        return Schritt(schritt="fertig")

    # ⚠️ **Der zweite Faktor ist eine Wahl, keine Pflicht** — so entschieden am
    # 01.09.2026: „das sollten die User selber entscheiden duerfen … wenn
    # jemand das rein lokal im netz betreibt waere das ja unoetig."
    #
    # Wer ihn nicht eingeschaltet hat, kommt hier durch. Eingeschaltet wird er
    # unter Einstellungen → Sicherheit, nicht mitten in der Anmeldung: Ein
    # Assistent, den man nicht abbrechen kann, ist keine Wahl.
    #
    # ⚠️ Was das kostet, steht in der Oberflaeche: Solange er aus ist, haengen
    # alle Postfaecher dieses Benutzers an einem Passwort. Wer nexmail ins
    # Internet stellt, sollte ihn einschalten.
    if not person.totp_bestaetigt:
        sitzungsdienst.anlegen(db, person, request, response, bestaetigt=True)
        return Schritt(schritt="fertig")

    sitzungsdienst.anlegen(db, person, request, response, bestaetigt=False)
    return Schritt(schritt="code")


@router.get("/einrichtung", response_model=Einrichtung)
def einrichtung_holen(sitzung: HalbeSitzung) -> Einrichtung:
    """Den QR-Code noch einmal zeigen - solange der Faktor unbestaetigt ist.

    ⚠️ **Das ist die Rettung vor dem haeufigsten Selbstausschluss:** Konto
    angelegt, Browser geschlossen, QR nie eingescannt. Ohne diesen Weg waere
    das Konto tot, obwohl niemand etwas falsch gemacht hat.

    Sobald der Faktor bestaetigt ist, gibt es hier nichts mehr - das Geheimnis
    verlaesst den Server danach nie wieder.
    """
    person = sitzung.benutzer
    if person.totp_bestaetigt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    geheimnis = zwei_faktor.geheimnis_lesen(person)
    adresse = zwei_faktor.otpauth_adresse(person, geheimnis)
    return Einrichtung(geheimnis=geheimnis, otpauth=adresse, qr_svg=zwei_faktor.qr_svg(adresse))


@router.post("/code", response_model=Schritt)
def code_pruefen(
    eingabe: Codeeingabe, sitzung: HalbeSitzung, request: Request, response: Response, db: DbSession
) -> Schritt:
    """Schritt zwei: der sechsstellige Code.

    ⚠️ **Hier haengt dieselbe Bremse wie am Passwort.** Sechs Stellen sind
    eine Million Moeglichkeiten - ohne Bremse in Minuten durchprobiert, und
    das Cookie fuer diesen Schritt hat jeder, der das Passwort kennt.
    """
    person = sitzung.benutzer
    wache = anmeldebremse.torwaechter(request, "code", person.benutzername)

    if not zwei_faktor.code_pruefen(db, person, eingabe.code.strip()):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Der Code stimmt nicht."
        )

    if not person.totp_bestaetigt:
        person.totp_bestaetigt = True
        db.commit()

    wache.geschafft()
    sitzungsdienst.bestaetigen(db, sitzung, request, response)
    return Schritt(schritt="fertig")


@router.post("/wiederherstellung", response_model=Schritt)
def wiederherstellung(
    eingabe: Codeeingabe, sitzung: HalbeSitzung, request: Request, response: Response, db: DbSession
) -> Schritt:
    """Der Weg zurueck, wenn das Telefon weg ist.

    ⚠️ Ein verbrauchter Code ist verbraucht. Und die Bremse zaehlt hier
    genauso - sonst waere dies die bequemere Tuer zum Durchprobieren.
    """
    person = sitzung.benutzer
    wache = anmeldebremse.torwaechter(request, "wiederherstellung", person.benutzername)

    if not zwei_faktor.code_einloesen(db, person, eingabe.code.strip()):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Dieser Code gilt nicht."
        )

    wache.geschafft()
    sitzungsdienst.bestaetigen(db, sitzung, request, response)
    logger.warning("A user signed in with a recovery code.")
    return Schritt(schritt="fertig")


@router.post("/abmelden", status_code=status.HTTP_204_NO_CONTENT)
def abmelden(sitzung: AktiveSitzung, response: Response, db: DbSession) -> None:
    sitzungsdienst.beenden(db, sitzung, response)


class Kennwortwechsel(BaseModel):
    altes: str = Field(min_length=1, max_length=200)
    neues: str = Field(min_length=1, max_length=200)


class Wechselergebnis(BaseModel):
    #: Wie viele andere Geräte dabei abgemeldet wurden.
    abgemeldet: int


@router.put("/passwort", response_model=Wechselergebnis)
def passwort_aendern(
    wunsch: Kennwortwechsel,
    request: Request,
    person: AngemeldeterBenutzer,
    aktuelle: AktiveSitzung,
    db: DbSession,
) -> Wechselergebnis:
    """Das eigene Kennwort ändern.

    ⚠️ **Mit Bremse.** Ohne sie wäre das die bequemste Stelle, ein Kennwort zu
    erraten: Man ist schon angemeldet, und jeder Versuch verrät, ob er stimmte.

    ⚠️ **Danach fliegen die anderen Geräte hinaus.** Wer sein Kennwort ändert,
    tut das meist, weil er jemanden im Verdacht hat. Ein Wechsel, nach dem der
    andere angemeldet bleibt, hilft nicht. Das eigene Gerät bleibt drin —
    sonst wirft sich der Betreiber gerade selbst hinaus.
    """
    # ``torwaechter`` sperrt selbst mit 429, wenn zu oft angeklopft wurde.
    wache = anmeldebremse.torwaechter(request, "passwort", person.benutzername)
    try:
        benutzerdienst.passwort_aendern(db, person, wunsch.altes, wunsch.neues)
    except benutzerdienst.BenutzerFehler as fehler:
        wache.fehlgeschlagen()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    wache.geschafft()

    weg = sitzungsdienst.alle_beenden(db, person, ausser=aktuelle.id)
    logger.warning("Password changed; %s other session(s) were ended.", weg)
    return Wechselergebnis(abgemeldet=weg)


class Anschalten(BaseModel):
    geheimnis: str
    otpauth: str
    qr_svg: str


class Bestaetigung(BaseModel):
    #: ⚠️ Die Wiederherstellungscodes gibt es genau hier und nie wieder.
    codes: list[str]


class MitKennwort(BaseModel):
    passwort: str = Field(min_length=1, max_length=200)


@router.post("/zwei-faktor/starten", response_model=Anschalten)
def zwei_faktor_starten(person: AngemeldeterBenutzer, db: DbSession) -> Anschalten:
    """Den zweiten Faktor einschalten - Schritt eins: der QR-Code.

    ⚠️ **Bestaetigt wird er erst im zweiten Schritt.** Wer hier abbricht, weil
    die Kamera nicht will oder das Telefon nicht da ist, aendert nichts an
    seinem Zugang. Genau daran scheitern Assistenten, die den Faktor mitten in
    der Anmeldung erzwingen: Man kommt weder vor noch zurueck.
    """
    if person.totp_bestaetigt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Der zweite Faktor ist schon eingeschaltet.",
        )

    geheimnis = zwei_faktor.geheimnis_erzeugen()
    zwei_faktor.geheimnis_speichern(person, geheimnis)
    db.commit()

    adresse = zwei_faktor.otpauth_adresse(person, geheimnis)
    return Anschalten(geheimnis=geheimnis, otpauth=adresse, qr_svg=zwei_faktor.qr_svg(adresse))


@router.post("/zwei-faktor/bestaetigen", response_model=Bestaetigung)
def zwei_faktor_bestaetigen(
    eingabe: Codeeingabe, person: AngemeldeterBenutzer, request: Request, db: DbSession
) -> Bestaetigung:
    """Schritt zwei: einmal den Code tippen, dann gilt er.

    ⚠️ **Ohne diesen Schritt wird nichts eingeschaltet.** Ein Faktor, der ohne
    Probe gilt, sperrt jeden aus, bei dem die Uhr des Telefons falsch geht oder
    der QR-Code nicht ankam - und zwar beim naechsten Anmelden, wenn niemand
    mehr weiss, woran es lag.
    """
    if person.totp_bestaetigt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Der zweite Faktor ist schon eingeschaltet.",
        )
    if not zwei_faktor.geheimnis_lesen(person):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zuerst den QR-Code holen.",
        )

    wache = anmeldebremse.torwaechter(request, "code", person.benutzername)
    if not zwei_faktor.code_pruefen(db, person, eingabe.code.strip()):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Der Code stimmt nicht."
        )
    wache.geschafft()

    person.totp_bestaetigt = True
    db.commit()
    codes = zwei_faktor.codes_neu(db, person)
    logger.info("The second factor was switched on for a user.")
    return Bestaetigung(codes=codes)


@router.post("/zwei-faktor/aus", status_code=status.HTTP_204_NO_CONTENT)
def zwei_faktor_aus(
    eingabe: MitKennwort, person: AngemeldeterBenutzer, request: Request, db: DbSession
) -> None:
    """Den zweiten Faktor abschalten - nur mit dem Kennwort.

    ⚠️ **Das Kennwort noch einmal, obwohl man angemeldet ist.** Sonst genuegt
    ein unbeaufsichtigter Bildschirm, um den zweiten Faktor zu entfernen - und
    danach ist er weg, ohne dass jemand etwas merkt. Dieselbe Bremse wie an der
    Anmeldung haengt daran.
    """
    wache = anmeldebremse.torwaechter(request, "zwei-faktor-aus", person.benutzername)
    if not benutzerdienst.passwort_stimmt(person, eingabe.passwort):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Das Kennwort stimmt nicht."
        )
    wache.geschafft()

    # ⚠️ Auch das Geheimnis und die Wiederherstellungscodes muessen weg. Blieben
    # sie liegen, waere der alte QR-Code nach dem Wiedereinschalten guelltig -
    # samt allem, was ihn inzwischen abfotografiert hat.
    zwei_faktor.abschalten(db, person)
    logger.warning("The second factor was switched off for a user.")


@router.get("/ich", response_model=Ich)
def ich(person: AngemeldeterBenutzer) -> Ich:
    return Ich(
        id=person.id,
        benutzername=person.benutzername,
        anzeigename=person.anzeigename,
        ist_betreiber=person.ist_betreiber,
        zwei_faktor_aktiv=person.totp_bestaetigt,
        offene_codes=zwei_faktor.offene_codes(person),
    )
