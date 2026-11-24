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
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .. import __version__
from ..config import get_settings
from ..deps import AktiveSitzung, AngemeldeterBenutzer, DbSession, HalbeSitzung
from .oidc import passwort_anmeldung_an
from ..services import anmeldebremse
from ..services import benutzer as benutzerdienst
from ..services import kidienst
from ..services import profilbild as profilbilddienst
from ..services import konten_store as kontenstore
from ..services import kontenpost
from ..services import sitzung as sitzungsdienst
from ..services import zwei_faktor
from ..meldung import MeldungHttp
from ..models import Benutzer, utcnow
from ..vendor import nexkonten

logger = logging.getLogger("nexmail.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Anmeldung(BaseModel):
    #: „Benutzername oder E-Mail“. ⚠️ **Der Feldname bleibt** (Passwortmanager, Skripte); 254 Zeichen, weil eine
    #: lange Adresse sonst 422 statt „stimmt nicht“ bekaeme.
    benutzername: str = Field(min_length=1, max_length=nexkonten.names.EMAIL_MAX)
    passwort: str = Field(min_length=1, max_length=300)


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
    #: Wohin ein Ruecksetz-Link ginge. Leer heisst: **kein Weg zurueck**, und
    #: die Sicherheitsseite sagt das auch so.
    kontaktadresse: str = ""
    #: ⚠️ **Hier und nicht ueber einen eigenen Abruf.** Der KI-Knopf im Editor
    #: darf nur dastehen, wenn der Dienst wirklich eingeschaltet ist; ein Knopf,
    #: der beim Druecken „ist gar nicht an" sagt, ist ein Fehler. Am `ich` zu
    #: haengen erspart eine Anfrage je Verfassen-Fenster und laesst den Knopf
    #: ueber `ichNeuLaden` sofort erscheinen, wenn jemand den Schalter umlegt.
    #: ⚠️ **Beides zusammen entscheidet ueber den Knopf im Editor.** Der
    #: eigene Schalter allein genuegt nicht: Der Betreiber kann KI-Dienste
    #: fuer die ganze Installation sperren, und dann darf der Knopf nicht
    #: dastehen.
    ki_aktiv: bool = False
    #: Ob es ein Kennwort gibt. Ein Konto aus OIDC hat keins; dort steht der
    #: Knopf „Kennwort ändern" nicht, weil er nach dem bisherigen fragt.
    hat_kennwort: bool = True
    #: Ob die Liste Logos der Absenderdomains holt. Reist am ``ich`` mit wie
    #: ``ki_aktiv``: Die Bildadresse traegt den Stand, und wer umschaltet,
    #: sieht es ohne F5.
    absenderlogos: bool = False
    #: Ob dieses Konto KI-Dienste ueberhaupt benutzen darf (Installation
    #: UND Konto). Daran haengt der Punkt in der Leiste.
    ki_erlaubt: bool = False
    #: Ob eine eingegangene Mail zusammengefasst werden darf: alle Riegel und
    #: beide Schalter. Daran haengt der Knopf im Lesebereich.
    ki_fremde_post: bool = False
    #: Die laufende Version und bis wohin dieses Konto „Was ist neu“ gesehen
    #: hat. Weichen sie ab und gibt es zur laufenden einen Eintrag, steht der
    #: Banner da. ⚠️ **Verglichen wird auf Gleichheit, nicht auf „neuer“**:
    #: Nach einem Rückweg auf eine ältere Version erscheint deren Text, falls
    #: es einen gibt, und das ist richtig, denn genau die läuft dann.
    version: str = ""
    wasneu_gesehen: str = ""
    #: Wann das Profilbild gesetzt wurde (ISO), der Stand in seiner Adresse;
    #: ``None`` ohne Bild. Das Bild selbst holt ``GET /api/auth/profilbild/{id}``.
    profilbild: str | None = None
    #: Die eigene Reihenfolge der Postfachgruppen-Reiter (siehe ``models``).
    gruppen_reihenfolge: list[str] = []
    #: Seit dem Kontenmodul: ob die Adresse zaehlt, welche auf ihren Link wartet, die Sprache des Kontos (``""``:
    #: die des Browsers), und nach einem neuen Passwort ueber einen Link, wer ihn machte (``self``, ``operator``,
    #: ``server``; ``""``: nichts zu zeigen).
    kontaktadresse_zaehlt: bool = True
    kontaktadresse_wartet: str = ""
    sprache: str = ""
    neues_passwort: str = ""


def bremsschluessel(store, eingetippt: str, request: Request) -> str:
    """Woran die Bremse zaehlt (Kontenmodul, zwei Toepfe): am Konto, egal ob Name oder Adresse getippt wurde (ein
    Konto, ein Zaehler), sonst an der Eingabe (``typed:<hash>``), **und** am Absender. Den zweiten Topf fuehrt
    ``anmeldebremse.torwaechter`` selbst (``...:adresse:<ip>``), und zwar nur mit ``NEXMAIL_CLIENT_IP``: Ohne kennt
    nexmail keinen Absender, und ein gemeinsamer Topf fuer alle liesse jeden alle aussperren."""
    _, konto_oder_eingabe = nexkonten.login.attempt_key(store, eingetippt, anmeldebremse.adresse_von(request))
    return konto_oder_eingabe


def _konto_schluessel(person: Benutzer) -> str:
    """Der Bremsschluessel eines angemeldeten Kontos, derselbe wie beim Anmelden."""
    return f"account:{person.id}"


@router.post("/anmelden", response_model=Schritt)
def anmelden(
    eingabe: Anmeldung, request: Request, response: Response, db: DbSession
) -> Schritt:
    """Schritt eins: „Benutzername oder E-Mail“ und das Passwort (Kontenmodul).

    Bei Erfolg entsteht eine **halbe** Sitzung, wenn das Konto einen zweiten Faktor hat. Sie laeuft nach wenigen
    Minuten ab und darf nur den zweiten Schritt aufrufen.

    ⚠️ **Jede Ablehnung ist dieselbe** (``anmeldung_falsch``, gleich lang gerechnet): kein Konto, falsches
    Passwort, eine Adresse, die zwei Konten haben, ein Konto nur ueber Anbieter.
    """
    store = kontenstore.store_fuer(db)
    wache = anmeldebremse.torwaechter(request, "anmelden", bremsschluessel(store, eingabe.benutzername, request))

    # ⚠️ **„Anmeldung mit Passwort" aus** (Verwaltung → Anmeldung): Nur die Anbieter lassen herein. Der Betreiber
    # kommt immer mit seinem Passwort hinein, sonst stuende er vor der Tuer, sobald der Anbieter ausfaellt. Die
    # Antwort ist dieselbe wie bei einem falschen Passwort und dauert genauso lange.
    gemeint = nexkonten.login.resolve_login(store, eingabe.benutzername)
    if gemeint is not None and not gemeint.operator and not passwort_anmeldung_an(db):
        store.check_password(None, eingabe.passwort)
        wache.fehlgeschlagen()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="anmeldung_falsch")
    try:
        konto = nexkonten.login.authenticate(store, eingabe.benutzername, eingabe.passwort)
    except nexkonten.AccountError as fehler:
        wache.fehlgeschlagen()
        raise kontenstore.http(fehler, status.HTTP_401_UNAUTHORIZED) from fehler

    person = db.get(Benutzer, str(konto.id))
    wache.geschafft()
    benutzerdienst.hash_auffrischen(db, person, eingabe.passwort)

    # ⚠️ Der Nothammer. Er ueberspringt den zweiten Faktor vollstaendig -
    # gedacht fuer den Fall, dass Telefon und Wiederherstellungscodes weg sind.
    if get_settings().zwei_faktor_aus:
        sitzungsdienst.anlegen(db, person, request, response, bestaetigt=True)
        nexkonten.login.succeeded(store, person.id)
        logger.warning("Signed in with the second factor disabled (NEXMAIL_ZWEI_FAKTOR_AUS).")
        return Schritt(schritt="fertig")

    # ⚠️ **Der zweite Faktor ist eine Wahl, keine Pflicht:** Wer nexmail rein
    # lokal betreibt, braucht ihn nicht. Eingeschaltet wird er unter
    # Einstellungen → Sicherheit, nicht mitten in der Anmeldung: Ein
    # Assistent, den man nicht abbrechen kann, ist keine Wahl.
    if not person.totp_bestaetigt:
        sitzungsdienst.anlegen(db, person, request, response, bestaetigt=True)
        nexkonten.login.succeeded(store, person.id)
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
    wache = anmeldebremse.torwaechter(request, "code", _konto_schluessel(person))

    if not zwei_faktor.code_pruefen(db, person, eingabe.code.strip()):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="code_falsch"
        )

    if not person.totp_bestaetigt:
        person.totp_bestaetigt = True
        db.commit()

    wache.geschafft()
    sitzungsdienst.bestaetigen(db, sitzung, request, response)
    nexkonten.login.succeeded(kontenstore.store_fuer(db), person.id)
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
    wache = anmeldebremse.torwaechter(request, "wiederherstellung", _konto_schluessel(person))

    if not zwei_faktor.code_einloesen(db, person, eingabe.code.strip()):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="code_ungueltig"
        )

    wache.geschafft()
    sitzungsdienst.bestaetigen(db, sitzung, request, response)
    nexkonten.login.succeeded(kontenstore.store_fuer(db), person.id)
    logger.warning("A user signed in with a recovery code.")
    return Schritt(schritt="fertig")


class Vergessen(BaseModel):
    #: „Benutzername oder E-Mail“; der Feldname bleibt.
    benutzername: str = Field(min_length=1, max_length=nexkonten.names.EMAIL_MAX)


class NeuesKennwort(BaseModel):
    schluessel: str = Field(min_length=1, max_length=200)
    passwort: str = Field(min_length=1, max_length=300)


class VergessenStand(BaseModel):
    #: Ob ein Link per Mail hinaus kann. Ohne: „Der Betreiber kann dir unter Konten einen Link erstellen …“.
    per_mail: bool


def _per_mail(db) -> bool:
    return kontenpost.mail_moeglich(db) and passwort_anmeldung_an(db)


@router.get("/kennwort-vergessen", response_model=VergessenStand)
def kennwort_vergessen_stand(db: DbSession) -> VergessenStand:
    """Ob die Seite das Formular zeigt oder den Satz ueber den Betreiber. Sagt nichts ueber ein Konto."""
    return VergessenStand(per_mail=_per_mail(db))


@router.post("/kennwort-vergessen", status_code=status.HTTP_202_ACCEPTED)
def kennwort_vergessen(
    eingabe: Vergessen, request: Request, background: BackgroundTasks, db: DbSession
) -> Response:
    """Einen Link fuer ein neues Passwort anfordern, mit Benutzername oder E-Mail (Kontenmodul).

    ⚠️ **Immer 202, immer derselbe Rumpf, immer gleich schnell.** Gesucht, angelegt und verschickt wird erst nach
    der Antwort (``forgot_in_background``). Eine Adresse, die zwei Konten haben, findet keines; mit dem Benutzernamen
    geht der Link trotzdem an die eigene Adresse.

    ⚠️ **Die Bremse zaehlt trotzdem**, am Konto oder an der Eingabe. Ohne sie schickt eine Maschine tausend Mails
    los, und der Postausgang landet auf einer Sperrliste.
    """
    store = kontenstore.store_fuer(db)
    wache = anmeldebremse.torwaechter(request, "vergessen", bremsschluessel(store, eingabe.benutzername, request))
    wache.fehlgeschlagen()

    if not _per_mail(db):
        logger.info("A password link was asked for, but there is no system mail, public address or password sign-in.")
        return Response(status_code=status.HTTP_202_ACCEPTED)

    def senden(mail: nexkonten.Mail) -> None:
        from ..db import SessionLocal

        with SessionLocal() as eigene:
            kontenpost.senden(eigene, mail)

    nexkonten.resets.forgot_in_background(
        eingabe.benutzername,
        open_store=kontenstore.eigener_store,
        send=senden,
        later=background.add_task,
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


class LinkStand(BaseModel):
    benutzername: str
    min_passwort: int = nexkonten.names.PASSWORD_MIN


@router.get("/kennwort-neu/{schluessel}", response_model=LinkStand)
def kennwort_neu_stand(schluessel: str, request: Request, db: DbSession) -> LinkStand:
    """Fuer wen der Link gilt; verbraucht nichts. ``ruecksetzung_ungueltig`` fuer alles, was nicht gilt."""
    wache = anmeldebremse.torwaechter(request, "kennwort-neu", "-")
    try:
        konto = nexkonten.resets.reset_state(
            kontenstore.store_fuer(db), schluessel, password_login=passwort_anmeldung_an(db)
        )
    except nexkonten.AccountError as fehler:
        wache.fehlgeschlagen()
        raise kontenstore.http(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return LinkStand(benutzername=konto.username)


@router.post("/kennwort-neu", status_code=status.HTTP_204_NO_CONTENT)
def kennwort_neu(eingabe: NeuesKennwort, request: Request, db: DbSession) -> Response:
    """Das neue Passwort setzen (Kontenmodul).

    ⚠️ **Browser-Anmeldungen und angefangene Anmeldungen enden; die iPhone-App und API-Schluessel bleiben**
    (Entwurf, Entscheidung „Neues Passwort“). Was noch Zugriff hat, zeigt die Oberflaeche nach der naechsten
    Anmeldung mit „Alle trennen“ (``/api/auth/zugaenge``).

    ⚠️ **204 wie bisher**, ohne Rumpf: Wer diese Adresse heute aufruft, rechnet damit.
    """
    wache = anmeldebremse.torwaechter(request, "kennwort-neu", "-")
    try:
        nexkonten.resets.use_reset(
            kontenstore.store_fuer(db), eingabe.schluessel, eingabe.passwort, password_login=passwort_anmeldung_an(db)
        )
    except nexkonten.AccountError as fehler:
        if fehler.code in ("reset_invalid", "reset_expired"):
            wache.fehlgeschlagen()
        # Ein zu kurzes Passwort ist kein Fehlversuch an der Tuer, und es verbraucht den Link nicht.
        raise kontenstore.http(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    wache.geschafft()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class Zugang(BaseModel):
    id: str
    #: ``device`` (die iPhone-App) oder ``api_key``.
    art: str
    name: str
    zuletzt: datetime | None = None


class Zugaenge(BaseModel):
    #: Wer den Link machte (``self``, ``operator``, ``server``), ``""`` ohne neues Passwort.
    herkunft: str
    zugaenge: list[Zugang]


@router.get("/zugaenge", response_model=Zugaenge)
def zugaenge(person: AngemeldeterBenutzer, db: DbSession) -> Zugaenge:
    """„Diese Geraete haben noch Zugriff“: was ein neues Passwort nicht beendet hat."""
    liste = kontenstore.store_fuer(db).list_access(person.id)
    return Zugaenge(
        herkunft=person.neues_passwort or "",
        zugaenge=[Zugang(id=str(z.id), art=z.kind, name=z.label, zuletzt=z.last_used_at) for z in liste],
    )


class Getrennt(BaseModel):
    getrennt: int


@router.post("/zugaenge/trennen", response_model=Getrennt)
def zugaenge_trennen(person: AngemeldeterBenutzer, db: DbSession) -> Getrennt:
    """„Alle trennen“: jedes Geraet und jeder API-Schluessel des eigenen Kontos. Der Hinweis ist danach erledigt."""
    anzahl = nexkonten.resets.disconnect_all(kontenstore.store_fuer(db), person.id)
    person.neues_passwort = ""
    db.commit()
    return Getrennt(getrennt=anzahl)


@router.post("/zugaenge/gesehen", status_code=status.HTTP_204_NO_CONTENT)
def zugaenge_gesehen(person: AngemeldeterBenutzer, db: DbSession) -> None:
    """Der Hinweis nach einem neuen Passwort ist gelesen; die Zugaenge bleiben."""
    person.neues_passwort = ""
    db.commit()


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
    wache = anmeldebremse.torwaechter(request, "passwort", _konto_schluessel(person))
    try:
        benutzerdienst.passwort_aendern(db, person, wunsch.altes, wunsch.neues)
    except benutzerdienst.BenutzerFehler as fehler:
        wache.fehlgeschlagen()
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
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
            detail="zwei_faktor_schon_an",
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
            detail="zwei_faktor_schon_an",
        )
    if not zwei_faktor.geheimnis_lesen(person):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="qr_code_fehlt",
        )

    wache = anmeldebremse.torwaechter(request, "code", _konto_schluessel(person))
    if not zwei_faktor.code_pruefen(db, person, eingabe.code.strip()):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="code_falsch"
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
    wache = anmeldebremse.torwaechter(request, "zwei-faktor-aus", _konto_schluessel(person))
    if not benutzerdienst.passwort_stimmt(person, eingabe.passwort):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="kennwort_falsch"
        )
    wache.geschafft()

    # ⚠️ Auch das Geheimnis und die Wiederherstellungscodes muessen weg. Blieben
    # sie liegen, waere der alte QR-Code nach dem Wiedereinschalten guelltig -
    # samt allem, was ihn inzwischen abfotografiert hat.
    zwei_faktor.abschalten(db, person)
    logger.warning("The second factor was switched off for a user.")


@router.get("/ich", response_model=Ich)
def ich(person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    return Ich(
        id=person.id,
        benutzername=person.benutzername,
        anzeigename=person.anzeigename,
        ist_betreiber=person.ist_betreiber,
        zwei_faktor_aktiv=person.totp_bestaetigt,
        offene_codes=zwei_faktor.offene_codes(person),
        kontaktadresse=person.kontaktadresse,
        ki_aktiv=person.ki_aktiv and kidienst.erlaubt_fuer(db, person),
        absenderlogos=person.absenderlogos_laden,
        ki_erlaubt=kidienst.erlaubt_fuer(db, person),
        ki_fremde_post=kidienst.fremde_post_fuer(db, person),
        hat_kennwort=bool(person.passwort_hash),
        version=__version__,
        wasneu_gesehen=person.wasneu_gesehen,
        profilbild=person.profilbild_am.isoformat() if person.profilbild_am else None,
        gruppen_reihenfolge=_reihenfolge_lesen(person.gruppen_reihenfolge),
        kontaktadresse_zaehlt=bool(person.kontaktadresse_zaehlt) if person.kontaktadresse else True,
        kontaktadresse_wartet=kontenstore.store_fuer(db).get_account(person.id).pending_email,
        sprache=person.sprache or "",
        neues_passwort=person.neues_passwort or "",
    )


def _reihenfolge_lesen(roh: str) -> list[str]:
    """Was gespeichert ist; Kaputtes zählt als „keine eigene Reihenfolge"."""
    import json

    try:
        wert = json.loads(roh) if roh else []
    except ValueError:
        return []
    return [w for w in wert if isinstance(w, str)] if isinstance(wert, list) else []


@router.post("/ich/wasneu-gesehen", response_model=Ich)
def wasneu_gesehen(person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    """„Was ist neu“ zur laufenden Version ist gesehen oder weggeklickt.

    ⚠️ **Die laufende Version kommt aus dem Server, nicht aus der Anfrage.**
    Ein Browser mit einer alten Oberfläche im Speicher könnte sonst eine
    Version melden, die gar nicht läuft, und der Banner käme nie.
    """
    person.wasneu_gesehen = __version__
    db.commit()
    return ich(person, db)


#: Wie lange eine Anmeldung als „frisch“ gilt: Ein Konto ohne Passwort bestaetigt eine neue Adresse mit einer
#: frischen Anmeldung beim Anbieter statt mit einem Passwort (Entwurf, Entscheidung „Adresse aendern“).
FRISCH_MINUTEN = 5


def _frisch(sitzung) -> bool:
    from datetime import timedelta

    angelegt = sitzung.angelegt if sitzung.angelegt.tzinfo else sitzung.angelegt.replace(tzinfo=utcnow().tzinfo)
    return utcnow() - angelegt <= timedelta(minutes=FRISCH_MINUTEN)


def _bestaetigt(person: Benutzer, sitzung) -> bool:
    """``actor_confirmed`` fuer das Modul: nur ein Konto **ohne** Passwort, frisch angemeldet. Mit Passwort prueft
    das Modul selbst."""
    return not person.passwort_hash and _frisch(sitzung)


def _mail_versuchen(db, mail: nexkonten.Mail | None) -> None:
    """Eine Mail des Moduls, die nicht ueber die Antwort entscheidet (Bescheid an die alte Adresse, neuer Name)."""
    if mail is None:
        return
    try:
        kontenpost.senden(db, mail)
    except Exception as fehler:  # noqa: BLE001 - ein Bescheid darf nichts umwerfen, was schon gilt
        logger.warning("An account mail could not be sent: %r", getattr(fehler, "kennung", fehler))


def _adresse_aendern(db, person: Benutzer, sitzung, adresse: str, passwort: str) -> None:
    """Die eigene Adresse ueber das Modul: nur mit Passwort (ohne Passwort: frisch angemeldet). Mit Postausgang
    wartet die neue auf ihren Link, ohne gilt sie sofort. ``""`` entfernt sie."""
    store = kontenstore.store_fuer(db)
    mit_mail = kontenpost.mail_moeglich(db)
    ergebnis = nexkonten.profiles.change_email(
        store, person.id, adresse, password=passwort, actor_confirmed=_bestaetigt(person, sitzung), mail=mit_mail
    )
    if ergebnis.mail is not None:
        try:
            kontenpost.senden(db, ergebnis.mail)
        except Exception as fehler:  # noqa: BLE001
            # Ohne Mail wartet die Adresse auf einen Link, den niemand hat: zuruecknehmen und sagen, warum.
            nexkonten.profiles.withdraw_email_change(store, person.id)
            raise MeldungHttp(status.HTTP_502_BAD_GATEWAY, getattr(fehler, "kennung", "post_fehler")) from fehler
    _mail_versuchen(db, ergebnis.notice)
    db.expire(person)


class Kontaktadresse(BaseModel):
    #: Leer heisst: entfernen. Das ist erlaubt und wird nicht wegdiskutiert —
    #: aber die Oberflaeche sagt, was es kostet.
    adresse: str = Field(default="", max_length=320)
    #: Seit dem Kontenmodul verlangt: das eigene Passwort (Entwurf, Entscheidung „Adresse aendern“).
    passwort: str = Field(default="", max_length=300)


@router.put("/ich/kontaktadresse", response_model=Ich)
def kontaktadresse_setzen(
    eingabe: Kontaktadresse, request: Request, person: AngemeldeterBenutzer, sitzung: AktiveSitzung, db: DbSession
) -> Ich:
    """Die eigene Adresse setzen oder entfernen.

    ⚠️ **Ohne sie gibt es keinen Weg zurueck**, wenn der Betreiber keinen Link erstellt. Sie ist ausdruecklich
    **nicht** eines der eingerichteten Postfaecher.

    ⚠️ **Nur mit Passwort** (seit dem Kontenmodul; vorher ohne, als Abwaegung). Wer eine fremde Sitzung uebernommen
    hat, koennte sonst die Adresse umbiegen und sich danach das Passwort schicken lassen. Dieselbe Bremse wie am
    Anmelden haengt davor.
    """
    wache = anmeldebremse.torwaechter(request, "adresse", _konto_schluessel(person))
    try:
        _adresse_aendern(db, person, sitzung, eingabe.adresse.strip(), eingabe.passwort)
    except nexkonten.AccountError as fehler:
        if fehler.code == "wrong_password":
            wache.fehlgeschlagen()
        raise kontenstore.http(fehler) from fehler
    wache.geschafft()
    logger.info("A user changed their address (empty=%s).", not eingabe.adresse.strip())
    return ich(person, db)


class Profil(BaseModel):
    #: Leer heisst: es wird der Benutzername gezeigt (seit dem Kontenmodul bleibt das Feld dann leer).
    anzeigename: str = Field(default="", max_length=200)
    #: Die eigene Adresse; ist sie anders als bisher, verlangt das ``passwort``.
    kontaktadresse: str | None = Field(default=None, max_length=320)
    passwort: str = Field(default="", max_length=300)


@router.put("/ich/profil", response_model=Ich)
def profil_setzen(
    eingabe: Profil, request: Request, person: AngemeldeterBenutzer, sitzung: AktiveSitzung, db: DbSession
) -> Ich:
    """Anzeigename und Adresse aus den Einstellungen → Profil, in einem Zug.

    ⚠️ **Erst pruefen, dann schreiben:** Der Anzeigename wird vorher geprueft (eindeutig), die Adresse geaendert
    (mit Passwort), erst dann der Name gesetzt. Sonst bliebe der Name geaendert und die Adresse nicht.
    """
    store = kontenstore.store_fuer(db)
    try:
        nexkonten.names.check_display_name(store, eingabe.anzeigename, person.id, required=False)
        adresse = (eingabe.kontaktadresse if eingabe.kontaktadresse is not None else person.kontaktadresse).strip()
        if not nexkonten.names.same_address(adresse, person.kontaktadresse) and (adresse or person.kontaktadresse):
            wache = anmeldebremse.torwaechter(request, "adresse", _konto_schluessel(person))
            try:
                _adresse_aendern(db, person, sitzung, adresse, eingabe.passwort)
            except nexkonten.AccountError as fehler:
                if fehler.code == "wrong_password":
                    wache.fehlgeschlagen()
                raise
            wache.geschafft()
        nexkonten.profiles.change_display_name(store, person.id, eingabe.anzeigename, actor_id=person.id)
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    db.expire(person)
    logger.info("A user changed their profile.")
    return ich(person, db)


class NeuerName(BaseModel):
    benutzername: str = Field(min_length=1, max_length=200)
    passwort: str = Field(default="", max_length=300)


@router.put("/ich/benutzername", response_model=Ich)
def benutzername_aendern(
    eingabe: NeuerName, request: Request, person: AngemeldeterBenutzer, db: DbSession
) -> Ich:
    """Den eigenen Benutzernamen aendern (Kontenmodul): nach den Regeln, nur wenn ihn kein Konto hat oder hatte, mit
    dem Passwort (ein Konto ohne Passwort ohne). Gilt sofort; Sitzungen, Geraete und Schluessel bleiben, sie haengen
    an der Kennung. Der alte Name bleibt fuer dieses Konto reserviert; anmelden geht nur mit dem neuen."""
    wache = anmeldebremse.torwaechter(request, "benutzername", _konto_schluessel(person))
    try:
        mail = nexkonten.profiles.change_username(
            kontenstore.store_fuer(db), person.id, eingabe.benutzername, actor_id=person.id, password=eingabe.passwort
        )
    except nexkonten.AccountError as fehler:
        if fehler.code == "wrong_password":
            wache.fehlgeschlagen()
        raise kontenstore.http(fehler) from fehler
    wache.geschafft()
    _mail_versuchen(db, mail if kontenpost.mail_moeglich(db) else None)
    db.expire(person)
    return ich(person, db)


class Sprache(BaseModel):
    #: ``de``, ``en``; ``""`` heisst: die des Browsers.
    sprache: str = Field(default="", max_length=35)


@router.put("/ich/sprache", response_model=Ich)
def sprache_setzen(eingabe: Sprache, person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    """Die Sprache des Kontos; sie reist mit auf jedes Geraet."""
    nexkonten.profiles.change_language(kontenstore.store_fuer(db), person.id, eingabe.sprache)
    db.expire(person)
    return ich(person, db)


@router.post("/ich/kontaktadresse/nochmal", response_model=Ich)
def adresslink_nochmal(request: Request, person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    """„Link nochmal schicken“ fuer die Adresse, die auf ihren Link wartet."""
    anmeldebremse.torwaechter(request, "adresslink", _konto_schluessel(person)).fehlgeschlagen()
    try:
        mail = nexkonten.profiles.resend_email_link(kontenstore.store_fuer(db), person.id)
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    try:
        kontenpost.senden(db, mail)
    except Exception as fehler:  # noqa: BLE001
        raise MeldungHttp(status.HTTP_502_BAD_GATEWAY, getattr(fehler, "kennung", "post_fehler")) from fehler
    return ich(person, db)


@router.delete("/ich/kontaktadresse/wartend", response_model=Ich)
def adresswechsel_zuruecknehmen(person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    """Die Adresse, die auf ihren Link wartet, zuruecknehmen; die bisherige gilt weiter."""
    nexkonten.profiles.withdraw_email_change(kontenstore.store_fuer(db), person.id)
    return ich(person, db)


class AdressLink(BaseModel):
    adresse: str


@router.get("/adresse/{schluessel}", response_model=AdressLink)
def adresslink_stand(schluessel: str, request: Request, db: DbSession) -> AdressLink:
    """Welche Adresse der Link bestaetigt; verbraucht nichts. Ohne Anmeldung: Der Link kommt per Mail."""
    wache = anmeldebremse.torwaechter(request, "adresse-link", "-")
    try:
        wechsel = nexkonten.profiles.email_change_state(kontenstore.store_fuer(db), schluessel)
    except nexkonten.AccountError as fehler:
        wache.fehlgeschlagen()
        raise kontenstore.http(fehler) from fehler
    return AdressLink(adresse=wechsel.address)


@router.post("/adresse/{schluessel}", response_model=AdressLink)
def adresslink_einloesen(schluessel: str, request: Request, db: DbSession) -> AdressLink:
    """Die Adresse des Links gilt ab jetzt und ist bewiesen; die alte hoert davon."""
    wache = anmeldebremse.torwaechter(request, "adresse-link", "-")
    store = kontenstore.store_fuer(db)
    try:
        ergebnis = nexkonten.profiles.confirm_email(store, schluessel)
    except nexkonten.AccountError as fehler:
        wache.fehlgeschlagen()
        raise kontenstore.http(fehler) from fehler
    _mail_versuchen(db, ergebnis.notice)
    return AdressLink(adresse=ergebnis.account.email)


@router.put("/ich/profilbild", response_model=Ich)
async def profilbild_setzen(request: Request, person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    """Das eigene Profilbild setzen; das Bild selbst ist der Rumpf.

    ⚠️ **Kein Multipart.** Ein Bild ist eine Datei, und ``python-multipart``
    ist die Stelle mit den Meldungen (siehe ``requirements.txt``).
    """
    daten = await request.body()
    try:
        bild = profilbilddienst.zeichnen(daten)
    except profilbilddienst.ProfilbildFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_422_UNPROCESSABLE_CONTENT) from fehler
    person.profilbild = bild
    person.profilbild_am = utcnow()
    db.commit()
    logger.info("A user set their profile picture.")
    return ich(person, db)


@router.delete("/ich/profilbild", response_model=Ich)
def profilbild_entfernen(person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    person.profilbild = None
    person.profilbild_am = None
    db.commit()
    return ich(person, db)


@router.get("/profilbild/{benutzer_id}")
def profilbild(benutzer_id: str, person: AngemeldeterBenutzer, db: DbSession) -> Response:
    """Ein Profilbild, fuer die, die es sehen duerfen.

    ⚠️ **Allen anderen antwortet es wie ein Bild, das es nicht gibt** (404):
    Sonst liesse sich abfragen, welche Kennungen ein Konto sind.
    """
    zeile = db.get(Benutzer, benutzer_id) if profilbilddienst.darf_sehen(person, benutzer_id) else None
    bild = zeile.profilbild if zeile is not None else None
    if not bild:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profilbild_fehlt")
    # Die Adresse traegt den Stand (?v=), ein neues Bild ist eine neue Adresse.
    return Response(
        bild,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


class GruppenReihenfolge(BaseModel):
    #: Die Schlagworte in der gewünschten Reihenfolge. Mehr als 100 Gruppen
    #: hat niemand; die Grenze hält nur Unsinn aus der Datenbank.
    reihenfolge: list[str] = Field(default_factory=list, max_length=100)


@router.put("/ich/gruppen", response_model=Ich)
def gruppen_ordnen(eingabe: GruppenReihenfolge, person: AngemeldeterBenutzer, db: DbSession) -> Ich:
    """Die Reihenfolge der Postfachgruppen-Reiter merken (Ziehen in der Leiste).

    Doppelte fallen weg (klein geschrieben verglichen), leere auch, jedes Wort
    höchstens 64 Zeichen wie ein Schlagwort am Postfach.
    """
    import json

    gesehen: set[str] = set()
    sauber: list[str] = []
    for wort in eingabe.reihenfolge:
        wort = wort.strip()[:64]
        if wort and wort.lower() not in gesehen:
            gesehen.add(wort.lower())
            sauber.append(wort)
    person.gruppen_reihenfolge = json.dumps(sauber, ensure_ascii=False)
    db.commit()
    return ich(person, db)
