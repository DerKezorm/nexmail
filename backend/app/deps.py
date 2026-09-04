"""Die Abhaengigkeiten, an denen die Rechte haengen.

⚠️ **Erlaubnisliste, keine Verbotsliste.** Jede Adresse muss ausdruecklich
sagen, wer sie benutzen darf. Umgekehrt gedacht - "ich sperre, was schaden
kann" - waere die erste vergessene Zeile ein Datenleck. Ein Test laeuft ueber
die ganze Routentabelle und schlaegt fehl, sobald ein Pfad weder geschuetzt
ist noch auf der begruendeten Liste der oeffentlichen steht.
Siehe FALLSTRICKE.md §5 und ``tests/test_waechter.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import Benutzer, Sitzung
from .services import sitzung as sitzungsdienst

DbSession = Annotated[Session, Depends(get_db)]


def _sitzung(request: Request, db: Session) -> Sitzung:
    lage = sitzungsdienst.holen(db, request)
    if lage is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="nicht_angemeldet",
        )
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


AngemeldeterBenutzer = Annotated[Benutzer, Depends(angemeldet)]
Betreiber = Annotated[Benutzer, Depends(nur_betreiber)]
AktiveSitzung = Annotated[Sitzung, Depends(angemeldete_sitzung)]
HalbeSitzung = Annotated[Sitzung, Depends(halbe_sitzung)]


def nur_meine(abfrage, benutzer: Benutzer, spalte):
    """Der eine Einschraenker.

    ⚠️ **Jede Abfrage auf persoenliche Daten geht hier durch**, nicht durch
    verstreute ``where``-Bedingungen. Wenn Mehrbenutzer kommt, ist das eine
    Stelle statt einer Jagd - und ein vergessenes ``where`` ist dann kein
    Datenleck, sondern ein Aufruf, der gar nicht erst kompiliert.
    """
    return abfrage.where(spalte == benutzer.id)
