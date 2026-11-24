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
from ..models import Benutzer
from ..services import anmeldebremse
from ..services import konten_store as kontenstore
from ..services import kontenpost
from ..services import sitzung as sitzungsdienst
from ..vendor import nexkonten
from .oidc import passwort_anmeldung_an

logger = logging.getLogger("nexmail.einladung")

router = APIRouter(prefix="/api/einladung", tags=["einladung"])


class Vorschau(BaseModel):
    #: ⚠️ **Der Benutzername ist jetzt ein Vorschlag**: der Name einer Einladung von vorher (sie behaelt ihn), sonst
    #: einer aus dem Anzeigenamen. Feldname wie bisher.
    benutzername: str
    anzeigename: str
    #: Die Adresse der Einladung, vorbelegt; aendert der Eingeladene sie, gilt die neue erst nach ihrem Link.
    kontaktadresse: str = ""
    #: Ob ein Passwort hier hereinfuehrt. Aus („Anmeldung mit Passwort“ in der
    #: Verwaltung): nur „Weiter mit …“ ueber einen Anbieter.
    passwort: bool = True
    min_passwort: int = nexkonten.names.PASSWORD_MIN


class Annahme(BaseModel):
    passwort: str = Field(min_length=1, max_length=300)
    #: ⚠️ **Fehlen alle drei, kommt die Anfrage von einer Oberflaeche von vorher** (nur das Passwort): Dann gilt der
    #: Benutzername der Einladung, ihr Anzeigename und ihre Adresse (``older_request`` im Modul).
    anzeigename: str | None = Field(default=None, max_length=200)
    benutzername: str | None = Field(default=None, max_length=200)
    kontaktadresse: str | None = Field(default=None, max_length=320)


def _gemailt(db, schluessel: str) -> bool:
    from ..services import einladung as einladungsdienst

    zeile = einladungsdienst.finden(db, schluessel)
    return bool(zeile is not None and zeile.gemailt and zeile.adresse)


@router.get("/{schluessel}", response_model=Vorschau)
def ansehen(schluessel: str, request: Request, db: DbSession) -> Vorschau:
    """Was die Seite vorbelegt. ⚠️ Hier kommt **kein** Konto zustande und kein Cookie."""
    wache = anmeldebremse.torwaechter(request, "einladung", schluessel[:12])
    try:
        form = nexkonten.invites.invite_form(kontenstore.store_fuer(db), schluessel)
    except nexkonten.AccountError as fehler:
        wache.fehlgeschlagen()
        raise kontenstore.http(fehler, status.HTTP_404_NOT_FOUND) from fehler
    wache.geschafft()
    return Vorschau(
        benutzername=form.username,
        anzeigename=form.display_name,
        kontaktadresse=form.email,
        passwort=passwort_anmeldung_an(db),
    )


@router.post("/{schluessel}", status_code=status.HTTP_201_CREATED)
def annehmen(
    schluessel: str,
    eingabe: Annahme,
    request: Request,
    response: Response,
    db: DbSession,
) -> dict[str, str]:
    """Konto anlegen — und damit ist man drin.

    ⚠️ **Ohne zweiten Faktor**, und das ist Absicht: Er ist eine Wahl, die jeder fuer sich unter Einstellungen →
    Sicherheit trifft.
    """
    wache = anmeldebremse.torwaechter(request, "einladung", schluessel[:12])
    if not passwort_anmeldung_an(db):
        # Ein Passwort, mit dem man sich danach nicht anmelden kann, waere eine Falle.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="passwort_anmeldung_aus")
    store = kontenstore.store_fuer(db)
    alt = eingabe.anzeigename is None and eingabe.benutzername is None and eingabe.kontaktadresse is None
    try:
        form = nexkonten.invites.invite_form(store, schluessel)
        adresse = eingabe.kontaktadresse if eingabe.kontaktadresse is not None else form.email
        gemailt = _gemailt(db, schluessel)
        ergebnis = nexkonten.invites.accept_invite(
            store,
            schluessel,
            display_name=eingabe.anzeigename if eingabe.anzeigename is not None else form.display_name,
            username=eingabe.benutzername if eingabe.benutzername is not None else form.username,
            email=adresse,
            password=eingabe.passwort,
            language=request.headers.get("accept-language", "").split(",")[0].split(";")[0],
            mail=kontenpost.mail_moeglich(db),
            older_request=alt,
            # Der Link ging per Mail an genau diese Adresse: Wer ihn oeffnet, hat sie bewiesen.
            proven=gemailt and nexkonten.names.same_address(adresse, form.email),
        )
    except nexkonten.AccountError as fehler:
        if fehler.code in ("invite_invalid", "invite_expired"):
            wache.fehlgeschlagen()
            # 400 wie vor dem Kontenmodul; die Seite davor (GET) antwortet 404.
            raise kontenstore.http(fehler, status.HTTP_400_BAD_REQUEST) from fehler
        raise kontenstore.http(fehler) from fehler
    wache.geschafft()

    if ergebnis.mail is not None:
        try:
            kontenpost.senden(db, ergebnis.mail)
        except Exception as fehler:  # noqa: BLE001 - das Konto steht; die Adresse wartet, der Link geht nochmal
            logger.warning("The confirmation mail of a new account could not be sent: %r", fehler)

    neuer = db.get(Benutzer, str(ergebnis.account.id))
    sitzungsdienst.anlegen(db, neuer, request, response, bestaetigt=True)
    logger.info("An invitation was redeemed.")
    return {"benutzername": neuer.benutzername}
