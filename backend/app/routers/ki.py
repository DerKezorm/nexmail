"""Der KI-Dienst — Einstellungen des BENUTZERS, nicht der Verwaltung.

⚠️ **Hier steht kein Anbieter im Code.** Der Server kennt Adresse, Schlüssel
und Modell; welche Kacheln die Oberfläche zum Vorausfüllen anbietet, ist ihre
Sache. Wer die Liste in den Server schriebe, sperrte jeden Dienst aus, der
morgen dazukommt — dieselbe Entscheidung wie bei ``lib/anbieter.ts`` für die
Postfächer, wo „von Hand eintragen" der Hauptweg ist.
"""

from __future__ import annotations

import logging

from datetime import datetime

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..meldung import MeldungHttp
from ..services import anmeldebremse
from ..services import kidienst

logger = logging.getLogger("nexmail.ki")

router = APIRouter(prefix="/api/ki", tags=["ki"])


class Stand(BaseModel):
    aktiv: bool
    url: str
    modell: str
    #: ⚠️ **Ob der Betreiber es ueberhaupt erlaubt.** Steht das auf false,
    #: zeigt der Reiter den Grund statt eines Formulars — ein Zugang, den
    #: man einrichten kann und der beim ersten Handgriff abgewiesen wird,
    #: waere die schlechtere Auskunft.
    erlaubt: bool
    #: ⚠️ **Nicht der Schlüssel selbst**, nur ob einer da ist. Er geht nie
    #: zurück, auch nicht an seinen Eigentümer — dieselbe Regel wie beim
    #: Postfach-Passwort.
    schluessel_da: bool


class Aenderung(BaseModel):
    #: ⚠️ ``None`` heisst **unverändert** — dieselbe Regel wie beim Passwort.
    #: Eine leere Zeichenkette heisst „weg".
    aktiv: bool | None = None
    url: str | None = Field(default=None, max_length=500)
    modell: str | None = Field(default=None, max_length=200)
    schluessel: str | None = Field(default=None, max_length=500)


class Abfrage(BaseModel):
    """Womit die Modelle geholt werden sollen.

    ⚠️ **Aus der Anfrage, nicht aus der Datenbank.** Man holt die Liste, um zu
    sehen, ob ein *noch nicht gespeicherter* Zugang taugt. Wer dafür erst
    speichern müsste, hätte einen kaputten Zugang gespeichert.
    """

    url: str = Field(max_length=500)
    #: Leer heisst: den gespeicherten nehmen. So lässt sich das Modell
    #: wechseln, ohne den Schlüssel noch einmal einzutippen.
    schluessel: str = Field(default="", max_length=500)


class Modell(BaseModel):
    id: str
    #: Lesbarer Name, wo der Dienst einen liefert. Anthropic tut es, OpenAI
    #: und Ollama nicht — dann bleibt das Feld leer.
    name: str = ""


@router.get("", response_model=Stand)
def stand(person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    return Stand(erlaubt=kidienst.erlaubt_fuer(db, person), **kidienst.einstellung_lesen(person))


@router.put("", response_model=Stand)
def aendern(eingabe: Aenderung, person: AngemeldeterBenutzer, db: DbSession) -> Stand:
    try:
        return Stand(
            erlaubt=kidienst.erlaubt_fuer(db, person),
            **kidienst.einstellung_schreiben(
                db,
                person,
                aktiv=eingabe.aktiv,
                url=eingabe.url,
                modell=eingabe.modell,
                schluessel=eingabe.schluessel,
            )
        )
    except kidienst.KiFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler


@router.post("/modelle", response_model=list[Modell])
def modelle(
    eingabe: Abfrage, person: AngemeldeterBenutzer, request: Request, db: DbSession
) -> list[Modell]:
    """Die Modellliste holen — und damit den Zugang prüfen.

    ⚠️ **Die Bremse hängt davor.** Der Server ruft hier eine fremde Adresse
    auf, die aus der Anfrage kommt; ohne Bremse liesse sich nexmail als
    Werkzeug benutzen, um jemand anderen mit Anfragen zu belegen.

    ⚠️ **Und ohne ``geschafft()``, anders als an jeder anderen Tür.** Dort
    zählt die Bremse Fehlversuche beim Raten eines Geheimnisses, und ein
    Treffer setzt sie zurück. Hier ist der **gelungene** Aufruf das, was
    begrenzt werden soll — er ist ja der, der hinausgeht. Der erste Anlauf
    setzte den Zähler nach jedem Erfolg zurück, und die Bremse griff nie.
    """
    if not kidienst.erlaubt_fuer(db, person):
        raise MeldungHttp.aus(
            kidienst.KiFehler("ki_vom_betreiber_gesperrt"), status.HTTP_403_FORBIDDEN
        )
    wache = anmeldebremse.torwaechter(request, "ki-modelle", person.benutzername)
    wache.fehlgeschlagen()

    schluessel = eingabe.schluessel.strip() or kidienst.schluessel_lesen(person)
    try:
        gefunden = kidienst.modelle_holen(eingabe.url, schluessel)
    except kidienst.KiFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return [Modell(**m) for m in gefunden]


class Textauftrag(BaseModel):
    """Was mit dem Text geschehen soll.

    ⚠️ **Der Text kommt aus dem Editor, nicht aus der Datenbank.** Er ist noch
    nirgends gespeichert — genau das ist der Fall: Man lässt einen Entwurf
    umformulieren, bevor man ihn abschickt.
    """

    #: Der markierte Bereich oder der ganze Entwurf, als HTML.
    #: ⚠️ **Ohne Zitat und ohne Signatur** — das schneidet die Oberfläche ab,
    #: bevor sie sendet. Fremde Post gehört nicht zum Anbieter geschickt, und
    #: umgeschrieben werden soll sie erst recht nicht.
    text: str = Field(max_length=kidienst.MAX_ZEICHEN)
    auftrag: str = Field(max_length=40)
    #: Ton beim Umformulieren, Sprache beim Übersetzen, sonst leer.
    ziel: str = Field(default="", max_length=40)


class Textergebnis(BaseModel):
    #: ⚠️ **Nur das Ergebnis, nicht der Ersatz.** Was damit geschieht,
    #: entscheidet ein Mensch im Fenster davor — der Server schreibt nichts in
    #: den Entwurf.
    text: str


@router.post("/text", response_model=Textergebnis)
def text(
    eingabe: Textauftrag,
    person: AngemeldeterBenutzer,
    request: Request,
    db: DbSession,
) -> Textergebnis:
    """Einen Entwurf bearbeiten lassen.

    ⚠️ **Die Bremse hängt davor, und wieder ohne ``geschafft()``.** Der
    gelungene Aufruf ist der, der hinausgeht und kostet — er ist das, was
    begrenzt werden soll. Dieselbe Begründung wie beim Modellabruf.
    """
    wache = anmeldebremse.torwaechter(request, "ki-text", person.benutzername)
    wache.fehlgeschlagen()

    try:
        raus = kidienst.text_bearbeiten(
            person,
            eingabe.text,
            auftrag=eingabe.auftrag,
            ziel=eingabe.ziel,
            # ⚠️ **Ohne `db` wird nichts gemerkt.** Die Liste haengt am Weg
            # ueber die Adresse, nicht am Dienst — so bleibt `text_bearbeiten`
            # in den Tests ohne Datenbank benutzbar, und der einzige Weg, auf
            # dem ein Mensch Text hinausschickt, schreibt immer mit.
            db=db,
        )
    except kidienst.KiFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    return Textergebnis(text=raus)


class Vorgang(BaseModel):
    """Ein Handgriff, wie er hinausging.

    ⚠️ **Der Rumpf geht wortwoertlich zurueck.** Das ist der ganze Zweck: Wer
    nachsehen will, ob Zitat und Signatur wirklich drausen geblieben sind, muss
    sehen, was geschickt wurde — nicht eine Zusammenfassung davon.
    """

    id: int
    zeitpunkt: datetime
    modell: str
    auftrag: str
    ziel: str
    rein: int
    raus: int
    #: Leer heisst: hat geklappt.
    fehler: str
    #: ``None``, wenn die Zeile nicht mehr zu entschluesseln ist.
    rumpf: dict | None


@router.get("/vorgaenge", response_model=list[Vorgang])
def vorgaenge(person: AngemeldeterBenutzer, db: DbSession) -> list[Vorgang]:
    return [Vorgang(**v) for v in kidienst.vorgaenge_lesen(db, person)]


@router.delete("/vorgaenge", status_code=status.HTTP_204_NO_CONTENT)
def vorgaenge_leeren(person: AngemeldeterBenutzer, db: DbSession) -> None:
    """Die Liste sofort leeren.

    ⚠️ **Sofort, nicht in vierzehn Tagen.** Wer sie loescht, will sie loeschen;
    ihn auf eine Frist zu verweisen waere dieselbe Sorte Antwort wie „bitte
    erst abgleichen".
    """
    kidienst.vorgaenge_leeren(db, person)


# --- Der Riegel des Betreibers -------------------------------------------- #


class Riegel(BaseModel):
    erlaubt: bool


@router.get("/erlaubt", response_model=Riegel)
def riegel_lesen(person: AngemeldeterBenutzer, db: DbSession) -> Riegel:
    """Steht der Riegel offen? Darf jeder Angemeldete wissen — sein eigener
    Reiter haengt davon ab."""
    return Riegel(erlaubt=kidienst.erlaubt(db))


@router.put("/erlaubt", response_model=Riegel)
def riegel_setzen(eingabe: Riegel, person: Betreiber, db: DbSession) -> Riegel:
    """⚠️ **Nur der Betreiber.** Er ist der Verantwortliche fuer die
    Installation; die Entscheidung, ob Mailtext das Haus verlassen darf, ist
    seine und nicht die eines einzelnen Benutzers."""
    return Riegel(erlaubt=kidienst.erlauben(db, eingabe.erlaubt))
