"""Die Abhaengigkeiten, an denen die Rechte haengen.

⚠️ **Erlaubnisliste, keine Verbotsliste.** Jede Adresse muss ausdruecklich
sagen, wer sie benutzen darf. Umgekehrt gedacht - "ich sperre, was schaden
kann" - waere die erste vergessene Zeile ein Datenleck. Ein Test laeuft ueber
die ganze Routentabelle und schlaegt fehl, sobald ein Pfad weder geschuetzt
ist noch auf der begruendeten Liste der oeffentlichen steht.
Siehe ``tests/test_waechter.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiSchluessel, Benutzer, Sitzung
from .services import sitzung as sitzungsdienst
from .vendor import nexlog

DbSession = Annotated[Session, Depends(get_db)]


#: Die Fläche der iPhone-App. Hier zählt nur die Kopfzeile, überall sonst nur
#: das Cookie.
APP_FLAECHE = "/api/app/"


def _sitzung(request: Request, db: Session) -> Sitzung:
    """Wer fragt: die eine Stelle, an der beide Türen getrennt werden.

    ⚠️ **Entschieden wird am Pfad, nicht an dem, was mitgeschickt wurde.**
    Würde hier genommen, was gerade dabei ist, öffnete ein Gerätetoken jede
    Adresse und ein Cookie die Fläche der App. So sieht ``/api/app/1`` kein
    Cookie und der Rest keine Kopfzeile. Die Handler sind dieselben, und keiner
    muss davon wissen. ``scope["path"]`` hat den Unterpfad schon verloren
    (``BasisPfadMiddleware``).
    """
    if request.scope.get("path", "").startswith(APP_FLAECHE):
        return _geraet(request, db)
    lage = sitzungsdienst.holen(db, request)
    if lage is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="nicht_angemeldet",
        )
    return lage


def _geraet(request: Request, db: Session) -> Sitzung:
    """Das Gerät zur Kopfzeile ``Authorization: Bearer nxa_…`` unter ``/api/app/1``: entscheidet das Gerätemodul
    (``nexgeraete.authenticate``, G12, G38). Ruht das Konto (gesperrt oder gelöscht, G26), verlangt der Betreiber einen
    zweiten Faktor, den es nicht hat, oder ist der Riegel zu, bleibt das Gerät gespeichert und wird abgewiesen.

    ⚠️ **Die Antwort in der Form der Anfrage** (G32): ohne ``X-Nex-App`` wie seit jeher (``401 nicht_angemeldet``,
    ``403 app_abgeschaltet``), mit ihr in der neuen Form (``device_disconnected``, ``account_blocked`` …). Der Aufrufer
    steht danach in ``request.state.geraet`` (``me_fields``)."""
    from .services import geraete_store
    from .vendor.nexgeraete import DeviceRefused, authenticate, client_of, forms, tokens

    config = geraete_store.KONFIGURATION
    store = geraete_store.store_fuer(db)
    try:
        aufrufer = authenticate(
            store,
            config,
            tokens.bearer(request.headers.get("authorization")),
            client=client_of(request.headers.get("x-nex-app")),
            now=geraete_store.jetzt(),
        )
    except DeviceRefused as abgewiesen:
        db.rollback()
        raise geraete_store.als_http(forms.form_of(config, request.headers), abgewiesen) from None
    lage = db.get(Sitzung, str(aufrufer.device.id))
    if lage is None:  # zwischen Prüfen und Lesen getrennt
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="nicht_angemeldet")
    request.state.geraet = aufrufer
    return lage


def angemeldete_sitzung(request: Request, db: DbSession) -> Sitzung:
    """Eine **bestaetigte** Sitzung - Passwort und zweiter Faktor.

    ⚠️ Eine halbe Sitzung wird hier abgewiesen, und zwar mit demselben 401 wie
    gar keine. Sonst waere der zweite Faktor eine Zierde: Wer nur das Passwort
    kennt, haette bereits ein Cookie in der Hand.
    """
    lage = _sitzung(request, db)
    if not lage.bestaetigt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="zweiter_faktor_noetig",
        )
    # konten 1.1.0: Sperren und Loeschen beenden alle Browser-Sitzungen (``shut_out``); stuende doch noch eine, gilt sie
    # nicht. Geraete ruhen seit konten 1.1.5 (G26); sie weist schon ``_geraet`` ab.
    if lage.benutzer.gesperrt_seit is not None or lage.benutzer.geloescht_am is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="nicht_angemeldet")
    # Wer handelt, steht ab hier in jeder Zeile dieser Anfrage (Modul log): ``[vorgang u:benutzername]``.
    nexlog.set_actor(lage.benutzer.benutzername)
    return lage


def angemeldet(sitzung: Annotated[Sitzung, Depends(angemeldete_sitzung)]) -> Benutzer:
    """Der angemeldete Mensch. Das ist die Abhaengigkeit fuer fast alles."""
    return sitzung.benutzer


def halbe_sitzung(request: Request, db: DbSession) -> Sitzung:
    """Die Sitzung zwischen Passwort und Code - und **nur** die.

    Eine bereits bestaetigte Sitzung wird hier ebenfalls abgewiesen: Wer schon
    drin ist, hat am zweiten Schritt nichts mehr zu suchen, und ein zweiter
    Durchlauf waere nur eine weitere Tuer zum Codeprobieren.
    """
    lage = _sitzung(request, db)
    if lage.bestaetigt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="schon_angemeldet",
        )
    return lage


def nur_betreiber(person: Annotated[Benutzer, Depends(angemeldet)]) -> Benutzer:
    """Nur der Betreiber. Fuer alles, was der **Anwendung** gehoert.

    ⚠️ **Kein Rollensystem.** ``ist_betreiber`` ist ein Haken, kein Rang: Er
    sagt nicht, was dieser Benutzer darf, sondern was andere mit ihm nicht
    duerfen. Wer daraus Rollen macht, baut eine Rechteverwaltung fuer einen
    Haushalt.

    ⚠️ **403 mit einem Satz, nicht 404.** Ein 404 verbirgt hier nichts: nexmail
    ist offen, jeder kann die Adressliste nachlesen. Es macht nur die Suche
    schwer, wenn ein Betreiber sich wundert, warum eine Seite leer bleibt.
    Dieselbe Antwort wie beim Protokoll — zwei Sorten waeren eine zu viel.
    """
    if not person.ist_betreiber:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="nur_betreiber",
        )
    return person


def nur_geraet(sitzung: Annotated[Sitzung, Depends(angemeldete_sitzung)]) -> Benutzer:
    """Der Schutz von ``/api/app/1``, ausdrücklich und zählbar.

    ``_sitzung`` trennt schon am Pfad. Diese Abhängigkeit hängt zusätzlich an
    der ganzen Fläche, damit ``test_waechter.py`` sie abzählen kann und ein Router,
    der falsch eingehängt wird, nicht still an der Wache vorbeiläuft.
    """
    if sitzung.art != "geraet":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="nicht_angemeldet")
    return sitzung.benutzer


def api_zugriff(request: Request, db: DbSession) -> ApiSchluessel:
    """Ein API-Schluessel statt einer Sitzung. Nur fuer ``/api/v1``.

    ⚠️ **Kein Cookie, nur die Kopfzeile.** Diese Adressen sind fuer andere
    Anwendungen gebaut; eine angemeldete Browsersitzung kommt hier nicht
    hinein. Damit kann keine fremde Seite ueber das Cookie eines Angemeldeten
    etwas abfragen, und umgekehrt oeffnet ein Schluessel keine einzige der
    uebrigen Adressen.

    ⚠️ **Der Riegel wird bei jeder Abfrage gefragt**, nicht beim Anlegen.
    Macht der Betreiber zu, steht jedes Dashboard sofort still.

    Keine Anmeldebremse: 256 Bit Zufall raet niemand, und ein gemeinsamer
    Zaehler waere ein billiger Weg, alle Dashboards lahmzulegen. Dieselbe
    Ueberlegung wie bei den Einladungen.
    """
    kopf = request.headers.get("authorization", "")
    art, _, wert = kopf.partition(" ")
    if art.lower() != "bearer" or not wert.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api_schluessel_fehlt",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # schluessel 1.0.0: das Modul entscheidet (``keys.authenticate``): Schalter aus 403 ``api_schluessel_abgeschaltet``;
    # unbekannt, gesperrt oder Konto gesperrt/geloescht 401 ``api_schluessel_ungueltig``; verlangt der Betreiber einen
    # zweiten Faktor und das Konto hat keinen, ruhen seine Schluessel (401 ``second_factor_required``), Anlegen bleibt.
    from .services import schluessel_store
    from .vendor.nexschluessel import keys
    from .vendor.nexschluessel.errors import KeyRefused

    try:
        gefunden = keys.authenticate(schluessel_store.store_fuer(db), schluessel_store.KONFIGURATION, wert.strip())
    except KeyRefused as fehler:
        raise HTTPException(
            status_code=fehler.status,
            detail=fehler.public_code,
            headers={"WWW-Authenticate": "Bearer"} if fehler.status == status.HTTP_401_UNAUTHORIZED else None,
        ) from fehler
    schluessel = db.get(ApiSchluessel, str(gefunden.key.id))
    if schluessel is None:  # zwischen Pruefen und Lesen widerrufen
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api_schluessel_ungueltig",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return schluessel


AngemeldeterBenutzer = Annotated[Benutzer, Depends(angemeldet)]
Betreiber = Annotated[Benutzer, Depends(nur_betreiber)]
AktiveSitzung = Annotated[Sitzung, Depends(angemeldete_sitzung)]
HalbeSitzung = Annotated[Sitzung, Depends(halbe_sitzung)]
ApiZugriff = Annotated[ApiSchluessel, Depends(api_zugriff)]


def nur_meine(abfrage, benutzer: Benutzer, spalte):
    """Der eine Einschraenker.

    ⚠️ **Jede Abfrage auf persoenliche Daten geht hier durch**, nicht durch
    verstreute ``where``-Bedingungen. Wenn Mehrbenutzer kommt, ist das eine
    Stelle statt einer Jagd - und ein vergessenes ``where`` ist dann kein
    Datenleck, sondern ein Aufruf, der gar nicht erst kompiliert.
    """
    return abfrage.where(spalte == benutzer.id)
