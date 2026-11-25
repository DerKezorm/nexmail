"""Benutzerverwaltung — was der Anwendung gehoert, nicht dem Einzelnen.

⚠️ **Nur der Betreiber.** ``ist_betreiber`` ist dabei ein Haken, kein Rang: Er
sagt nicht, was dieser Mensch darf, sondern was andere mit ihm nicht duerfen.

⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
einzeln. nexmail ist der Mail-Client eines Haushalts, keine Plattform.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AktiveSitzung, Betreiber, DbSession
from ..meldung import Meldung, MeldungHttp
from ..models import Benutzer, Einladung
from ..services import anmeldebremse
from ..services import benutzer as benutzerdienst
from ..services import kidienst
from ..services import einladung as einladungsdienst
from ..services import konten_store as kontenstore
from ..services import kontenpost
from ..services import systempost
from ..vendor import nexkonten

logger = logging.getLogger("nexmail.benutzer")

router = APIRouter(prefix="/api/benutzer", tags=["benutzer"])


class BenutzerZeile(BaseModel):
    id: str
    benutzername: str
    anzeigename: str
    ist_betreiber: bool
    zwei_faktor_aktiv: bool
    angelegt: datetime
    #: Wie viele Postfaecher an ihm haengen — die Liste soll etwas aussagen.
    postfaecher: int
    #: ⚠️ **Der Riegel des Betreibers je Konto**, nicht die Wahl des Benutzers.
    #: Ab Werk erlaubt: Die Spalte ist die Ausnahmeliste, nicht die
    #: Einladungsliste — der bewusste Akt ist der Riegel der Installation.
    ki_erlaubt: bool
    #: Die Kennung im Anmeldemodul (ganze Zahl), fuer „Verknuepfung loesen".
    nummer: int = 0
    #: Die Anmeldeanbieter, mit denen das Konto verknuepft ist (Marken in der Liste).
    anbieter: list[dict] = []
    #: Seit dem Kontenmodul: die Adresse (klein in der Liste), ob ein anderes Konto sie auch hat (Hinweis), ob es
    #: ein Passwort gibt (ein Konto nur ueber Anbieter bekommt per Link ein erstes).
    kontaktadresse: str = ""
    adresse_doppelt: bool = False
    hat_kennwort: bool = True


class EinladungsZeile(BaseModel):
    id: str
    #: Nur bei Einladungen von vorher; neue tragen keinen Namen (der Eingeladene waehlt ihn).
    benutzername: str
    anzeigename: str
    adresse: str
    angelegt: datetime
    laeuft_ab: datetime
    abgelaufen: bool
    #: Der Link, einmal, wenn er nicht per Mail hinausging (keine Adresse oder kein Postausgang).
    link: str = ""


class Bestand(BaseModel):
    benutzer: list[BenutzerZeile]
    einladungen: list[EinladungsZeile]
    #: Ohne Postausgang laesst sich niemand einladen — das sagt die Oberflaeche
    #: **vorher**, statt den Betreiber gegen einen Fehler laufen zu lassen.
    postausgang_da: bool
    #: Ohne oeffentliche Adresse waere der Link in der Mail unbrauchbar.
    adresse_da: bool


class Einladen(BaseModel):
    #: ⚠️ **Wird nicht mehr verwendet** (Entwurf: Der Betreiber gibt keinen Benutzernamen mehr vor). Das Feld bleibt
    #: erlaubt, damit Skripte von vorher nicht mit 422 scheitern.
    benutzername: str = Field(default="", max_length=64)
    #: Freiwillig. Mit Postausgang geht der Link dorthin, sonst kopiert ihn der Betreiber.
    adresse: str = Field(default="", max_length=320)
    anzeigename: str = Field(default="", max_length=200)
    #: Wie lange der Link gilt: 1, 7 oder 30 Tage.
    tage: int = nexkonten.invites.INVITE_DAYS_DEFAULT


class Umfang(BaseModel):
    postfaecher: int
    nachrichten: int
    kontakte: int
    regeln: int
    signaturen: int


def _zeile(db, person: Benutzer, verknuepft: dict | None = None) -> BenutzerZeile:
    from ..models import Konto
    from ..routers.oidc import verknuepfungen_je_konto

    if verknuepft is None:
        verknuepft = verknuepfungen_je_konto(db)

    anzahl = len(db.execute(select(Konto.id).where(Konto.benutzer_id == person.id)).all())
    store = kontenstore.store_fuer(db)
    konto = store.get_account(person.id)
    return BenutzerZeile(
        id=person.id,
        benutzername=person.benutzername,
        anzeigename=person.anzeigename,
        ist_betreiber=person.ist_betreiber,
        zwei_faktor_aktiv=person.totp_bestaetigt,
        angelegt=person.angelegt,
        postfaecher=anzahl,
        ki_erlaubt=person.ki_erlaubt,
        nummer=person.nummer or 0,
        anbieter=verknuepft.get(person.id, []),
        kontaktadresse=person.kontaktadresse or "",
        adresse_doppelt=nexkonten.login.duplicate_email(store, konto) if konto is not None else False,
        hat_kennwort=bool(person.passwort_hash),
    )


def _einladungszeile(e: Einladung, link: str = "") -> EinladungsZeile:
    return EinladungsZeile(
        link=link,
        id=e.id,
        benutzername=e.benutzername,
        anzeigename=e.anzeigename,
        adresse=e.adresse,
        angelegt=e.angelegt,
        laeuft_ab=e.laeuft_ab,
        abgelaufen=einladungsdienst.abgelaufen(e),
    )


@router.get("", response_model=Bestand)
def liste(_: Betreiber, db: DbSession) -> Bestand:
    from ..routers.oidc import verknuepfungen_je_konto

    leute = db.execute(select(Benutzer).order_by(Benutzer.angelegt)).scalars().all()
    verknuepft = verknuepfungen_je_konto(db)
    return Bestand(
        benutzer=[_zeile(db, p, verknuepft) for p in leute],
        einladungen=[_einladungszeile(e) for e in einladungsdienst.offene(db)],
        postausgang_da=systempost.lesen(db).eingerichtet,
        adresse_da=bool(kontenpost.oeffentliche_adresse(db)),
    )


@router.post("/einladungen", response_model=EinladungsZeile, status_code=status.HTTP_201_CREATED)
def einladen(eingabe: Einladen, _: Betreiber, db: DbSession) -> EinladungsZeile:
    """Einladen: Adresse und Anzeigename freiwillig, **kein Benutzername** (Kontenmodul), Gueltigkeit 1, 7 oder 30
    Tage.

    ⚠️ **Mit Adresse und Postausgang: anlegen und verschicken sind eins.** Eine Einladung, die in der Liste steht,
    deren Mail aber nie hinausging, ist die schlimmste Sorte. Geht der Versand schief, wird die Zeile wieder
    entfernt und der Grund gemeldet. **Ohne Adresse oder ohne Postausgang** zeigt die Antwort den Link einmal
    (``link``); der Betreiber gibt ihn selbst weiter.
    """
    if not kontenpost.oeffentliche_adresse(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oeffentliche_adresse_fehlt",
        )
    store = kontenstore.store_fuer(db)
    try:
        adresse, anzeigename = nexkonten.invites.invite_values(
            store,
            email=eingabe.adresse,
            display_name=eingabe.anzeigename,
            public_url=kontenpost.oeffentliche_adresse(db),
        )
        laeuft_ab = nexkonten.invites.invite_expires_at(eingabe.tage)
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler

    einladung, schluessel = einladungsdienst.aussprechen(
        db, adresse=adresse, anzeigename=anzeigename, laeuft_ab=laeuft_ab
    )
    einladung.gemailt = False
    db.commit()
    if adresse and systempost.lesen(db).eingerichtet:
        try:
            kontenpost.einladung_senden(db, einladung, schluessel, eingabe.tage)
        except systempost.PostFehler as fehler:
            db.delete(einladung)
            db.commit()
            raise MeldungHttp.aus(fehler, status.HTTP_502_BAD_GATEWAY) from fehler
        einladung.gemailt = True
        db.commit()
        return _einladungszeile(einladung)
    return _einladungszeile(einladung, kontenpost.link(db, f"/einladung/{schluessel}"))


@router.delete("/einladungen/{einladung_id}", status_code=status.HTTP_204_NO_CONTENT)
def einladung_zuruecknehmen(einladung_id: str, _: Betreiber, db: DbSession) -> None:
    einladung = db.get(Einladung, einladung_id)
    if einladung is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    db.delete(einladung)
    db.commit()
    logger.info("An invitation was withdrawn.")


@router.get("/{benutzer_id}/umfang", response_model=Umfang)
def umfang(benutzer_id: str, _: Betreiber, db: DbSession) -> Umfang:
    """Was am Benutzer haengt — fuer die Rueckfrage vor dem Entfernen."""
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Umfang(**benutzerdienst.umfang(db, person))


class Uebergabe(BaseModel):
    #: ⚠️ Das eigene Passwort. Siehe die Begruendung an der Adresse.
    passwort: str = Field(min_length=1, max_length=200)


@router.post("/{benutzer_id}/betreiber", status_code=status.HTTP_204_NO_CONTENT)
def betreiber_uebergeben(
    benutzer_id: str, eingabe: Uebergabe, ich: Betreiber, request: Request, db: DbSession
) -> None:
    """Den Betreiber-Haken an jemand anderen geben.

    ⚠️ **Genau ein Betreiber, immer.** Der Haken wandert, er wird nicht
    vergeben: Wer ihn abgibt, hat ihn danach nicht mehr. Zwei Betreiber waeren
    nicht schlimm, aber null waeren das Ende — aus der Anwendung heraus fuehrt
    dann kein Weg zurueck.

    ⚠️ **Das eigene Passwort steht davor.** Das ist der teuerste Knopf in der
    ganzen Verwaltung: Wer ihn drueckt, gibt die Verwaltung ab und kann sie
    sich nicht zurueckholen. Eine geklaute Sitzung genuegt dafuer nicht —
    dieselbe Ueberlegung wie beim Abschalten des zweiten Faktors.

    ⚠️ **Danach laesst sich der alte Betreiber entfernen.** Genau dafuer gibt
    es diesen Weg: Wer die Wohnung wechselt, hinterlaesst sonst eine
    Installation, an die niemand mehr herankommt.
    """
    wache = anmeldebremse.torwaechter(request, "betreiber-uebergeben", f"account:{ich.id}")
    if not benutzerdienst.passwort_stimmt(ich, eingabe.passwort):
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="kennwort_falsch"
        )
    wache.geschafft()

    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if person.id == ich.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="betreiber_an_sich_selbst"
        )

    person.ist_betreiber = True
    ich.ist_betreiber = False
    db.commit()
    logger.warning("The operator flag was handed over to another user.")


@router.delete("/{benutzer_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(benutzer_id: str, ich: Betreiber, db: DbSession) -> None:
    """Einen Benutzer mit allem entfernen, was ihm gehoert.

    ⚠️ **Der Betreiber selbst geht nicht.** Danach haette nexmail niemanden,
    der die Verwaltung oeffnen kann — und aus der Anwendung heraus fuehrt kein
    Weg zurueck. Wer den Betreiber wechseln will, uebergibt den Haken; das ist
    ein anderer Vorgang und keine Loeschung.
    """
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if person.id == ich.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sich_selbst_entfernen",
        )
    if person.ist_betreiber:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="betreiber_entfernen",
        )
    benutzerdienst.entfernen(db, person)


class KiErlaubnis(BaseModel):
    erlaubt: bool


@router.put("/{benutzer_id}/ki", response_model=BenutzerZeile)
def ki_erlaubnis(
    benutzer_id: str, eingabe: KiErlaubnis, ich: Betreiber, db: DbSession
) -> BenutzerZeile:
    """Einem einzelnen Konto KI-Dienste erlauben oder verbieten.

    ⚠️ **Kein Passwort davor, anders als beim Uebergeben des Betreibers.** Das
    hier ist umkehrbar mit demselben Klick und kostet niemandem seinen Zugang —
    die Schluessel bleiben stehen. Eine Bremse fuer jede Verwaltungsaenderung
    macht die Verwaltung unbenutzbar, und dann wird sie umgangen.
    """
    person = db.get(Benutzer, benutzer_id)
    if person is None:
        raise MeldungHttp.aus(Meldung("benutzer_nicht_gefunden"), status.HTTP_404_NOT_FOUND)
    kidienst.erlauben_fuer(db, person, eingabe.erlaubt)
    return _zeile(db, person)


# --- Kontenmodul: was der Betreiber an fremden Konten aendert ------------------------------------------------------- #
#
# ⚠️ **Immer mit dem eigenen Passwort** (ein Betreiber ohne Passwort: frisch beim Anbieter angemeldet). Der Betreiber
# setzt nie ein Passwort und nie eine Adresse, er nimmt eine nur weg: Sonst ginge ein Passwort-Link an eine Adresse
# seiner Wahl.


class MitPasswort(BaseModel):
    passwort: str = Field(default="", max_length=300)


class NeuerBenutzername(MitPasswort):
    benutzername: str = Field(min_length=1, max_length=200)


class NeuerAnzeigename(MitPasswort):
    anzeigename: str = Field(default="", max_length=200)


class LinkWunsch(MitPasswort):
    #: 1, 7 oder 30 Tage; ab Werk einer.
    tage: int = nexkonten.resets.OPERATOR_DAYS_DEFAULT


class Passwortlink(BaseModel):
    #: Der Link zum Weitergeben, einmal; leer, wenn er per Mail ging.
    link: str = ""
    #: Wohin die Mail ging; leer, wenn der Link hier steht.
    an: str = ""
    laeuft_ab: datetime


def _bestaetigt(ich: Benutzer, sitzung) -> bool:
    from .auth import _bestaetigt as bestaetigt

    return bestaetigt(ich, sitzung)


def _handeln(request: Request, ich: Benutzer, tuer: str):
    return anmeldebremse.torwaechter(request, tuer, f"account:{ich.id}")


def _abgelehnt(fehler: nexkonten.AccountError, wache) -> MeldungHttp:
    if fehler.code == "wrong_password":
        wache.fehlgeschlagen()
    return kontenstore.http(fehler)


@router.put("/{benutzer_id}/benutzername", response_model=BenutzerZeile)
def benutzername_aendern(
    benutzer_id: str,
    eingabe: NeuerBenutzername,
    ich: Betreiber,
    sitzung: AktiveSitzung,
    request: Request,
    db: DbSession,
) -> BenutzerZeile:
    """Den Benutzernamen eines Kontos aendern. Gilt sofort; Sitzungen und Geraete bleiben."""
    wache = _handeln(request, ich, "betreiber-handelt")
    try:
        mail = nexkonten.profiles.change_username(
            kontenstore.store_fuer(db),
            benutzer_id,
            eingabe.benutzername,
            actor_id=ich.id,
            password=eingabe.passwort,
            actor_confirmed=_bestaetigt(ich, sitzung),
        )
    except nexkonten.AccountError as fehler:
        raise _abgelehnt(fehler, wache) from fehler
    wache.geschafft()
    if mail is not None and kontenpost.mail_moeglich(db):
        try:
            kontenpost.senden(db, mail)
        except systempost.PostFehler:
            logger.warning("The mail about a new username could not be sent.")
    person = db.get(Benutzer, benutzer_id)
    db.refresh(person)
    return _zeile(db, person)


@router.put("/{benutzer_id}/anzeigename", response_model=BenutzerZeile)
def anzeigename_aendern(
    benutzer_id: str,
    eingabe: NeuerAnzeigename,
    ich: Betreiber,
    sitzung: AktiveSitzung,
    request: Request,
    db: DbSession,
) -> BenutzerZeile:
    """Den Anzeigenamen eines Kontos aendern (leer: der Benutzername wird gezeigt)."""
    wache = _handeln(request, ich, "betreiber-handelt")
    try:
        nexkonten.profiles.change_display_name(
            kontenstore.store_fuer(db),
            benutzer_id,
            eingabe.anzeigename,
            actor_id=ich.id,
            password=eingabe.passwort,
            actor_confirmed=_bestaetigt(ich, sitzung),
        )
    except nexkonten.AccountError as fehler:
        raise _abgelehnt(fehler, wache) from fehler
    wache.geschafft()
    person = db.get(Benutzer, benutzer_id)
    db.refresh(person)
    return _zeile(db, person)


@router.post("/{benutzer_id}/kontaktadresse-entfernen", response_model=BenutzerZeile)
def adresse_entfernen(
    benutzer_id: str,
    eingabe: MitPasswort,
    ich: Betreiber,
    sitzung: AktiveSitzung,
    request: Request,
    db: DbSession,
) -> BenutzerZeile:
    """Die Adresse eines Kontos wegnehmen (nie setzen). Die alte Adresse hoert davon, wenn Post hinaus kann."""
    wache = _handeln(request, ich, "betreiber-handelt")
    try:
        ergebnis = nexkonten.profiles.remove_email(
            kontenstore.store_fuer(db),
            benutzer_id,
            actor_id=ich.id,
            password=eingabe.passwort,
            actor_confirmed=_bestaetigt(ich, sitzung),
            mail=kontenpost.mail_moeglich(db),
        )
    except nexkonten.AccountError as fehler:
        raise _abgelehnt(fehler, wache) from fehler
    wache.geschafft()
    if ergebnis.notice is not None:
        try:
            kontenpost.senden(db, ergebnis.notice)
        except systempost.PostFehler:
            logger.warning("The notice about a removed address could not be sent.")
    person = db.get(Benutzer, benutzer_id)
    db.refresh(person)
    return _zeile(db, person)


@router.post("/{benutzer_id}/passwort-link", response_model=Passwortlink)
def passwort_link(
    benutzer_id: str,
    eingabe: LinkWunsch,
    ich: Betreiber,
    sitzung: AktiveSitzung,
    request: Request,
    db: DbSession,
) -> Passwortlink:
    """Ein Link fuer ein neues Passwort, vom Betreiber erstellt (Kontenmodul).

    Mit Postausgang und einer Adresse, die zaehlt, geht er per Mail hin (auch an eine, die ein anderes Konto
    ebenfalls hat: die Adresse ist die eigene); sonst steht er einmal in der Antwort. Fuer sich selbst erstellt der
    Betreiber keinen (``use_account_page``). Ein Konto nur ueber Anbieter bekommt so ein erstes Passwort, solange die
    Anmeldung mit Passwort an ist.
    """
    from .oidc import passwort_anmeldung_an

    wache = _handeln(request, ich, "betreiber-handelt")
    store = kontenstore.store_fuer(db)
    try:
        ergebnis = nexkonten.resets.reset_link(
            store,
            benutzer_id,
            actor_id=ich.id,
            password=eingabe.passwort,
            actor_confirmed=_bestaetigt(ich, sitzung),
            mail=kontenpost.mail_moeglich(db),
            password_login=passwort_anmeldung_an(db),
            days=eingabe.tage,
        )
    except nexkonten.AccountError as fehler:
        raise _abgelehnt(fehler, wache) from fehler
    wache.geschafft()
    if ergebnis.mail is not None:
        try:
            kontenpost.senden(db, ergebnis.mail)
        except systempost.PostFehler as fehler:
            nexkonten.resets.reset_mail_failed(store, benutzer_id)
            raise MeldungHttp.aus(fehler, status.HTTP_502_BAD_GATEWAY) from fehler
        return Passwortlink(an=ergebnis.mail.to, laeuft_ab=ergebnis.expires_at)
    return Passwortlink(link=kontenpost.link(db, f"/kennwort/{ergebnis.token}"), laeuft_ab=ergebnis.expires_at)


class FaktorZuruecksetzen(MitPasswort):
    #: „Gekoppelte Geraete auch trennen“ (konten 0.3.1), ab Werk an: Ein verlorenes Handy ist sonst noch angemeldet.
    geraete_trennen: bool = True
    #: „Passkeys auch entfernen“ (konten 0.3.3), ab Werk an: Ein verlorenes Handy traegt vielleicht einen.
    passkeys_entfernen: bool = True


class FaktorUeberblick(BaseModel):
    """Was ein Zuruecksetzen wegnaehme (``factor.reset_overview``), fuer den Dialog davor."""

    authenticator: bool
    codes: int
    passkeys: list[str]
    geraete: list[str]


@router.get("/{benutzer_id}/zweiter-faktor-ueberblick", response_model=FaktorUeberblick)
def zweiter_faktor_ueberblick(benutzer_id: str, ich: Betreiber, db: DbSession) -> FaktorUeberblick:
    """konten 0.3.3: Authenticator, Codes, Passkeys (mit Namen) und gekoppelte Geraete des Kontos."""
    from ..vendor.nexkonten import factor

    try:
        stand = factor.reset_overview(kontenstore.store_fuer(db), benutzer_id, actor_id=ich.id)
    except nexkonten.AccountError as fehler:
        raise kontenstore.http(fehler) from fehler
    return FaktorUeberblick(
        authenticator=stand.authenticator,
        codes=stand.recovery_codes,
        passkeys=[p.name for p in stand.passkeys],
        geraete=[g.label for g in stand.devices],
    )


@router.post("/{benutzer_id}/zweiter-faktor-zuruecksetzen", response_model=BenutzerZeile)
def zweiten_faktor_zuruecksetzen(
    benutzer_id: str,
    eingabe: FaktorZuruecksetzen,
    ich: Betreiber,
    sitzung: AktiveSitzung,
    request: Request,
    db: DbSession,
) -> BenutzerZeile:
    """„Zweiten Faktor zuruecksetzen“ (Kontenmodul Teil 2): Authenticator-App, Wiederherstellungscodes und (mit
    ``passkeys_entfernen``, ab Werk an) Passkeys des Kontos fallen weg, seine Browser-Anmeldungen enden; mit Adresse
    hoert es davon. Fuer jemanden, dessen Telefon
    weg ist. Mit dem eigenen Passwort des Betreibers; fuer sich selbst nicht (``use_account_page``)."""
    from ..vendor.nexkonten import factor

    wache = _handeln(request, ich, "betreiber-handelt")
    try:
        mail = factor.operator_reset(
            kontenstore.store_fuer(db),
            benutzer_id,
            actor_id=ich.id,
            password=eingabe.passwort,
            actor_confirmed=_bestaetigt(ich, sitzung),
            disconnect_devices=eingabe.geraete_trennen,
            remove_passkeys=eingabe.passkeys_entfernen,
        )
    except nexkonten.AccountError as fehler:
        raise _abgelehnt(fehler, wache) from fehler
    wache.geschafft()
    if mail is not None and kontenpost.mail_moeglich(db):
        kontenpost.senden(db, mail)
    person = db.get(Benutzer, benutzer_id)
    db.refresh(person)
    return _zeile(db, person)
