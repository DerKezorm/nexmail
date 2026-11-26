"""Die eigenen API-Schluessel verwalten, und der Riegel des Betreibers: nexmails alter Weg ``/api/apischluessel``.

Gelesen wird mit einem Schluessel ueber ``/api/v1`` (``routers/api_v1.py``).
Hier stehen die Adressen fuer die Oberflaeche, also mit Sitzung.

⚠️ **Seit schluessel 1.0.0 entscheidet das Modul** (``keys.make``, ``keys.change``, ``keys.revoke``; die Seite nutzt
``/api/connections``). Dieser Weg bleibt fuer alles, was ihn noch ruft, und antwortet in seiner alten Form: dieselben
Felder, dieselben Kennungen, Fehler der Eingabe mit 400 und ``werte``.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..meldung import MeldungHttp
from ..models import ApiSchluessel
from ..services import apischluessel as dienst
from ..services import schluessel_store
from ..vendor.nexschluessel import keys, switches
from ..vendor.nexschluessel.errors import KeyRefused

router = APIRouter(prefix="/api/apischluessel", tags=["apischluessel"])


class Eintrag(BaseModel):
    id: str
    name: str
    praefix: str
    stufe: str
    konten: list[str]
    #: Darf Aufgaben abhaken und wieder oeffnen (``/api/v1/tasks``).
    aufgaben: bool
    #: Darf Schlagworte an der Mail einer Aufgabe setzen (``/api/v1/tags``).
    schlagworte: bool
    angelegt: datetime
    zuletzt_benutzt: datetime | None


class Stand(BaseModel):
    erlaubt: bool
    schluessel: list[Eintrag]


class Eingabe(BaseModel):
    name: str = Field(default="", max_length=200)
    stufe: str = "anzahl"
    konten: list[str] = Field(default_factory=list, max_length=200)
    aufgaben: bool = False
    schlagworte: bool = False


class Neu(Eintrag):
    #: ⚠️ **Nur in dieser einen Antwort.** Danach kennt nexmail nur noch den Hash.
    schluessel: str


class Riegel(BaseModel):
    erlaubt: bool


def _eintrag(zeile: ApiSchluessel, eigene: set[str]) -> Eintrag:
    return Eintrag(
        id=zeile.id,
        name=zeile.name,
        praefix=zeile.praefix,
        stufe=zeile.stufe,
        # Entfernte Postfaecher fallen hier heraus, wie beim Lesen.
        konten=[k for k in dienst.konten_lesen(zeile) if k in eigene],
        aufgaben=zeile.aufgaben,
        schlagworte=zeile.schlagworte,
        angelegt=zeile.angelegt,
        zuletzt_benutzt=zeile.zuletzt_benutzt,
    )


#: Die Kennungen des Moduls in nexmails alter Form (Eingabefehler), mit 400 wie vorher.
ALTE_KENNUNGEN = {
    "name_missing": "api_schluessel_name_fehlt",
    "name_too_long": "api_schluessel_name_zu_lang",
    "right_invalid": "api_schluessel_stufe_unbekannt",
    "choose_areas": "api_schluessel_ohne_postfach",
    # Eine fremde Kennung sieht aus wie eine unbekannte: wer fremde Postfaecher durchprobiert, erfaehrt nichts.
    "areas_invalid": "postfach_unbekannt",
    "too_many_keys": "api_schluessel_zu_viele",
}


def _abgewiesen(fehler: KeyRefused) -> HTTPException:
    """Eine Ablehnung des Moduls, wie dieser Weg sie immer gab."""
    if fehler.code in ALTE_KENNUNGEN:
        werte: dict = {}
        if fehler.code == "name_too_long":
            werte["max"] = dienst.MAX_NAME
        elif fehler.code == "too_many_keys":
            werte["max"] = fehler.details.get("max", dienst.MAX_JE_BENUTZER)
        return MeldungHttp(status.HTTP_400_BAD_REQUEST, ALTE_KENNUNGEN[fehler.code], werte)
    # api_off (403 api_schluessel_abgeschaltet), not_found (404 api_schluessel_unbekannt): wie vorher.
    return HTTPException(status_code=fehler.status, detail=fehler.public_code)


def _optionen(eingabe: "Eingabe") -> dict[str, bool]:
    return {"tasks": eingabe.aufgaben, "tags": eingabe.schlagworte}


def _recht(stufe: str) -> str:
    # Eine unbekannte Stufe geht unveraendert hinein; das Modul lehnt sie ab (right_invalid).
    return schluessel_store.ZU_MODUL.get(stufe, stufe)


@router.get("", response_model=Stand)
def lesen(person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    eigene = {k.id for k in dienst.eigene_konten(db, person.id)}
    return Stand(
        erlaubt=dienst.erlaubt(db),
        schluessel=[_eintrag(z, eigene) for z in dienst.liste(db, person)],
    )


# ⚠️ **Vor den Adressen mit Kennung.** Sonst faengt ``PUT /{schluessel_id}``
# das Wort „erlaubt“ als Kennung ab, und der Riegel antwortet mit 404.
@router.get("/erlaubt", response_model=Riegel)
def riegel_lesen(_: AngemeldeterBenutzer, db: DbSession) -> Riegel:
    return Riegel(erlaubt=dienst.erlaubt(db))


@router.put("/erlaubt", response_model=Riegel)
def riegel_setzen(eingabe: Riegel, _: Betreiber, db: DbSession) -> Riegel:
    """⚠️ **Nur der Betreiber.** Ob Betreff und Absender das Haus verlassen
    duerfen, entscheidet der, der fuer die Installation verantwortlich ist."""
    stand = switches.change(schluessel_store.store_fuer(db), schluessel_store.KONFIGURATION, {"api": eingabe.erlaubt})
    dienst.logger.info("The operator %s API keys for this installation.", "allowed" if stand["api"] else "blocked")
    return Riegel(erlaubt=stand["api"])


@router.post("", response_model=Neu, status_code=status.HTTP_201_CREATED)
def anlegen(eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession) -> Neu:
    # ⚠️ **Auch hier der Riegel, nicht nur beim Lesen** (``keys.make`` fragt ihn). Sonst entstuenden Schluessel, die in
    # dem Moment funktionieren, in dem der Betreiber aufmacht, ohne dass er weiss, dass es sie gibt.
    store = schluessel_store.store_fuer(db)
    try:
        gemacht = keys.make(
            store,
            schluessel_store.KONFIGURATION,
            person.id,
            name=eingabe.name,
            right=_recht(eingabe.stufe),
            areas=list(dict.fromkeys(eingabe.konten)),
            options=_optionen(eingabe),
        )
    except KeyRefused as fehler:
        store.rollback()
        raise _abgewiesen(fehler) from fehler
    zeile = db.get(ApiSchluessel, str(gemacht.key.id))
    dienst.logger.info(
        "An API key was created (scope %s, %d mailboxes%s%s).",
        zeile.stufe,
        len(dienst.konten_lesen(zeile)),
        ", may tick tasks" if zeile.aufgaben else "",
        ", may tag messages" if zeile.schlagworte else "",
    )
    eigene = {k.id for k in dienst.eigene_konten(db, person.id)}
    return Neu(**_eintrag(zeile, eigene).model_dump(), schluessel=gemacht.secret)


@router.put("/{schluessel_id}", response_model=Eintrag)
def aendern(
    schluessel_id: str, eingabe: Eingabe, person: AngemeldeterBenutzer, db: DbSession
) -> Eintrag:
    store = schluessel_store.store_fuer(db)
    try:
        keys.change(
            store,
            schluessel_store.KONFIGURATION,
            person.id,
            schluessel_id,
            name=eingabe.name,
            right=_recht(eingabe.stufe),
            areas=list(dict.fromkeys(eingabe.konten)),
            areas_given=True,
            options=_optionen(eingabe),
        )
    except KeyRefused as fehler:
        store.rollback()
        raise _abgewiesen(fehler) from fehler
    zeile = db.get(ApiSchluessel, schluessel_id)
    dienst.logger.info("An API key was changed (scope %s, %d mailboxes).", zeile.stufe, len(dienst.konten_lesen(zeile)))
    eigene = {k.id for k in dienst.eigene_konten(db, person.id)}
    return _eintrag(zeile, eigene)


@router.delete("/{schluessel_id}", status_code=status.HTTP_204_NO_CONTENT)
def entfernen(schluessel_id: str, person: AngemeldeterBenutzer, db: DbSession) -> None:
    """Widerrufen wirkt sofort: Die naechste Abfrage mit diesem Schluessel
    bekommt 401."""
    try:
        keys.revoke(schluessel_store.store_fuer(db), schluessel_store.KONFIGURATION, person.id, schluessel_id)
    except KeyRefused as fehler:
        raise _abgewiesen(fehler) from fehler
    dienst.logger.info("An API key was revoked.")
