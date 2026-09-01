"""Eine Einladung annehmen — die einzige Tuer, die ohne Anmeldung aufgeht.

⚠️ **Was hier wirklich schuetzt, ist die Laenge des Schluessels, nicht die
Bremse.** ``secrets.token_urlsafe(32)`` sind 256 Bit — das laesst sich nicht
raten, auch nicht mit beliebig viel Zeit.

Die Bremse haengt trotzdem dran, aber sie zaehlt **je Schluessel**. Das stoppt
jemanden, der denselben falschen Link hundertmal aufruft, und nicht jemanden,
der jedesmal einen anderen probiert. Das ist Absicht: Ein gemeinsamer Zaehler
fuer alle Einladungen waere ein billiger Weg, das Einladen fuer eine
Viertelstunde lahmzulegen — und gewonnen waere nichts, weil gegen 256 Bit
ohnehin niemand anrennt.

⚠️ **Ohne ``NEXMAIL_CLIENT_IP`` zaehlt die Bremse ausserdem gar nicht nach
Adresse** (siehe ``anmeldebremse.adresse_von``). Wer hier eine Sperre nach
Herkunft erwartet, irrt sich — hinter einem Proxy waere sie ohnehin wertlos.

⚠️ **Und deshalb antworten beide gleich, egal was schiefging.** Ob es den
Schluessel nie gab, ob er abgelaufen ist oder schon benutzt wurde, geht
niemanden etwas an, der ihn nicht hat.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..deps import DbSession
from ..services import anmeldebremse
from ..services import einladung as einladungsdienst
from ..services import sitzung as sitzungsdienst

logger = logging.getLogger("nexmail.einladung")

router = APIRouter(prefix="/api/einladung", tags=["einladung"])


class Vorschau(BaseModel):
    benutzername: str
    anzeigename: str


class Annahme(BaseModel):
    passwort: str = Field(min_length=1, max_length=200)


@router.get("/{schluessel}", response_model=Vorschau)
def ansehen(schluessel: str, request: Request, db: DbSession) -> Vorschau:
    """Wen die Einladung meint — damit auf der Seite ein Name steht.

    ⚠️ Hier kommt **kein** Konto zustande und kein Cookie. Die Seite braucht
    nur den Benutzernamen, damit der Eingeladene weiss, wofuer er ein Kennwort
    vergibt.
    """
    wache = anmeldebremse.torwaechter(request, "einladung", schluessel[:12])

    einladung = einladungsdienst.finden(db, schluessel)
    if einladung is None:
        wache.fehlgeschlagen()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diese Einladung gilt nicht mehr. Bitte um eine neue.",
        )
    wache.geschafft()
    return Vorschau(benutzername=einladung.benutzername, anzeigename=einladung.anzeigename)


@router.post("/{schluessel}", status_code=status.HTTP_201_CREATED)
def annehmen(
    schluessel: str,
    eingabe: Annahme,
    request: Request,
    response: Response,
    db: DbSession,
) -> dict[str, str]:
    """Kennwort vergeben — und damit ist man drin.

    ⚠️ **Ohne zweiten Faktor**, und das ist Absicht: Er ist eine Wahl, die
    jeder fuer sich unter Einstellungen → Sicherheit trifft. Ein Assistent, aus
    dem man ohne Telefon nicht herauskommt, waere die schlechteste erste
    Minute, die nexmail einem neuen Benutzer machen kann.
    """
    wache = anmeldebremse.torwaechter(request, "einladung", schluessel[:12])
    try:
        neuer = einladungsdienst.einloesen(db, schluessel, eingabe.passwort)
    except einladungsdienst.EinladungsFehler as fehler:
        wache.fehlgeschlagen()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    except Exception as fehler:  # Passwortregeln
        wache.fehlgeschlagen()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    wache.geschafft()

    sitzungsdienst.anlegen(db, neuer, request, response, bestaetigt=True)
    return {"benutzername": neuer.benutzername}
