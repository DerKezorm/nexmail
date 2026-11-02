"""Die Fläche der eigenen iPhone-App: ``/api/app/1``.

⚠️ **Ein Versprechen, aber nur an die eigene App.** Die App im App Store und die
selbst betriebenen Server werden nie gleichzeitig aktualisiert. Deshalb spricht
sie nicht mit dem Innenteil unter ``/api/…``, und ``/api/v1`` liest nur Kopfdaten.
Solange ``app/1`` in der Adresse steht, bricht hier nichts; muss etwas brechen,
entsteht ``/api/app/2`` daneben. Die Wächter stehen in
``tests/test_app_zusage.py`` und ``tests/app1_abdruck.json``, der Vertrag in
``nexmail-ios/docs/vertrag-block1.md``.

⚠️ **Die Handler sind dieselben wie im Browser**, ein zweites Mal registriert
(``_zweitschrift``). Rechte, Besitzprüfung, Riegel und Fehler gelten dadurch
genau wie dort. Antwortform und Statuscode werden aus der Originalroute
übernommen, nicht abgeschrieben. Die Feldnamen sind deshalb die der Oberfläche.

⚠️ **Wer fragt, entscheidet ``deps._sitzung`` am Pfad:** Hier zählt nur die
Kopfzeile, außerhalb nur das Cookie. Die Handler merken davon nichts.

⚠️ **Hier hängt nichts ewig.** Die ``AppFristMiddleware`` setzt Fristen für das
Schloss eines Postfachs und den ersten Abruf einer Mail; danach kommt 503 samt
``Retry-After`` (``abgleich.WartenFehler``), und die App versucht es wieder.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, status
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import __version__
from ..deps import AktiveSitzung, AngemeldeterBenutzer, DbSession
from ..meldung import MeldungHttp
from ..models import Nachricht
from ..services import abgleich, aenderungen, aliase as aliasdienst
from ..services import kidienst
from ..services import konten as kontendienst
from ..services import push as pushdienst
from . import (
    absenderbild,
    aufgaben,
    ki,
    kontakte,
    konten,
    nachrichten,
    schlagworte,
    suche,
    termine,
    verfassen,
)

router = APIRouter(prefix="/api/app/1", tags=["app"])


def _zweitschrift(
    pfad: str, quelle: APIRouter, endpoint: Any, methode: str, summary: str
) -> None:
    """Denselben Handler noch einmal eintragen, mit Form und Wachen des Originals."""
    for route in quelle.routes:
        if isinstance(route, APIRoute) and route.endpoint is endpoint and methode in route.methods:
            router.add_api_route(
                pfad,
                endpoint,
                methods=[methode],
                response_model=route.response_model,
                status_code=route.status_code,
                responses=route.responses,
                dependencies=list(route.dependencies),
                summary=summary,
                description=f"Same as `{methode} {route.path}` in the web interface.",
            )
            return
    raise LookupError(f"{endpoint.__name__} ({methode}) is not registered on {quelle.prefix}")


# --- Wer bin ich ----------------------------------------------------------- #


class AppKonto(BaseModel):
    id: str
    name: str
    benutzername: str
    betreiber: bool


class AppAlias(BaseModel):
    adresse: str
    name: str = ""


class AppPostfach(BaseModel):
    id: str
    anzeigename: str
    adresse: str
    farbe: int
    #: ``anmeldung``, wenn der Mailserver die Zugangsdaten ablehnt.
    stoerung: str = ""
    tags: list[str] = []
    aliase: list[AppAlias] = []


class AppGeraet(BaseModel):
    id: str
    name: str


class AppSelbstauskunft(BaseModel):
    version: str
    konto: AppKonto
    postfaecher: list[AppPostfach]
    geraet: AppGeraet
    #: Was dieser Server dieser Person gerade anbietet. Fehlt ein Wort, zeigt
    #: die App den Knopf nicht. Ein älterer Server kennt es nicht und nennt es
    #: nicht; das bricht nichts.
    faehigkeiten: list[str]


def _faehigkeiten(db: DbSession, person) -> list[str]:
    raus = ["abbestellen", "aenderungen", "endgueltig_loeschen", "wiedervorlage"]
    if kidienst.erlaubt_fuer(db, person) and person.ki_aktiv:
        raus.append("umformulieren")
    if kidienst.fremde_post_fuer(db, person):
        raus.append("kurzfassung")
    if pushdienst.relay_adresse():
        raus.append("push")
    return raus


@router.get("/me", response_model=AppSelbstauskunft, summary="Who am I, and what can this server do")
def selbstauskunft(
    person: AngemeldeterBenutzer, sitzung: AktiveSitzung, db: DbSession
) -> AppSelbstauskunft:
    """Der erste Aufruf der App. Ein nexmail ohne diese Fläche antwortet 404."""
    return AppSelbstauskunft(
        version=__version__,
        konto=AppKonto(
            id=person.id,
            name=person.anzeigename or person.benutzername,
            benutzername=person.benutzername,
            betreiber=person.ist_betreiber,
        ),
        postfaecher=[
            AppPostfach(
                id=k.id,
                anzeigename=k.anzeigename,
                adresse=k.adresse,
                farbe=k.farbe,
                stoerung=k.stoerung or "",
                tags=kontendienst.tags_lesen(k),
                aliase=[AppAlias(adresse=a.adresse, name=a.name) for a in aliasdienst.lesen(k)],
            )
            for k in kontendienst.meine(db, person)
        ],
        geraet=AppGeraet(id=sitzung.id, name=sitzung.geraet),
        faehigkeiten=_faehigkeiten(db, person),
    )


@router.delete(
    "/device", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect this device"
)
def selbst_trennen(sitzung: AktiveSitzung, db: DbSession) -> None:
    """Die App trennt sich selbst; ihr Schlüssel gilt ab sofort nicht mehr."""
    db.delete(sitzung)
    db.commit()


# --- Lesen ----------------------------------------------------------------- #

_zweitschrift("/accounts", konten.router, konten.liste, "GET", "The mailboxes")
_zweitschrift(
    "/accounts/{konto_id}/folders", konten.router, konten.ordner, "GET", "Folder tree with counts"
)
_zweitschrift("/messages", nachrichten.router, nachrichten.liste, "GET", "The message list")
_zweitschrift(
    "/messages/thread/{schluessel:path}",
    nachrichten.router,
    nachrichten.strang,
    "GET",
    "All messages of a conversation",
)
_zweitschrift("/events", nachrichten.router, nachrichten.ereignisse, "GET", "Wait for a change")
_zweitschrift("/labels", schlagworte.router, schlagworte.liste, "GET", "The tags")
_zweitschrift("/search", suche.router, suche.suchen, "POST", "Search through the server")
_zweitschrift(
    "/sender-image", absenderbild.router, absenderbild.bild, "GET", "A sender's picture"
)

# --- Handeln, die festen Wege vor ``/messages/{nachricht_id}`` --------------- #

_zweitschrift(
    "/messages/move", nachrichten.router, nachrichten.verschieben, "POST", "Move messages"
)
_zweitschrift(
    "/messages/delete", nachrichten.router, nachrichten.loeschen, "POST", "Move to the trash"
)
_zweitschrift(
    "/messages/archive", nachrichten.router, nachrichten.archivieren, "POST", "Archive messages"
)
_zweitschrift("/messages/junk", nachrichten.router, nachrichten.junk, "POST", "Move to junk")
_zweitschrift(
    "/messages/delete-forever",
    nachrichten.router,
    nachrichten.endgueltig,
    "POST",
    "Delete messages for good, only from trash or junk",
)
_zweitschrift("/messages/undo", nachrichten.router, nachrichten.zurueck, "POST", "Undo a move")
_zweitschrift(
    "/messages/labels/{atom}",
    nachrichten.router,
    nachrichten.schlagwort_geben,
    "POST",
    "Add a tag to messages",
)
_zweitschrift(
    "/messages/labels/{atom}",
    nachrichten.router,
    nachrichten.schlagwort_nehmen,
    "DELETE",
    "Remove a tag from messages",
)
_zweitschrift(
    "/snoozes", nachrichten.router, nachrichten.wiedervorlage_liste, "GET", "Snoozed messages"
)
_zweitschrift(
    "/snoozes", nachrichten.router, nachrichten.wiedervorlage_anlegen, "POST", "Snooze a message"
)
_zweitschrift(
    "/snoozes/{eintrag_id}",
    nachrichten.router,
    nachrichten.wiedervorlage_entfernen,
    "DELETE",
    "Wake a message early",
)
_zweitschrift(
    "/folders/{ordner_id}/read",
    nachrichten.router,
    nachrichten.ordner_gelesen,
    "POST",
    "Mark a folder as read",
)
_zweitschrift(
    "/folders/{ordner_id}/empty",
    nachrichten.router,
    nachrichten.leeren,
    "POST",
    "Empty the trash or junk for good",
)
_zweitschrift("/tasks", aufgaben.router, aufgaben.anlegen, "POST", "Make a task from a message")

# --- Eine Mail ------------------------------------------------------------- #

_zweitschrift(
    "/messages/{nachricht_id}", nachrichten.router, nachrichten.eine, "GET", "One message"
)
_zweitschrift(
    "/messages/{nachricht_id}/attachments/{anhang_id}",
    nachrichten.router,
    nachrichten.anhang,
    "GET",
    "An attachment",
)
_zweitschrift(
    "/messages/{nachricht_id}/images",
    nachrichten.router,
    nachrichten.bilder_anzeigen,
    "POST",
    "Load the blocked images",
)
_zweitschrift(
    "/messages/{nachricht_id}/flags", nachrichten.router, nachrichten.flags_setzen, "POST", "Set flags"
)
_zweitschrift(
    "/messages/{nachricht_id}/unsubscribe",
    nachrichten.router,
    nachrichten.abbestellen,
    "POST",
    "Unsubscribe with one click",
)
_zweitschrift(
    "/messages/{nachricht_id}/summary",
    nachrichten.router,
    nachrichten.zusammenfassung,
    "POST",
    "Summarise a received message",
)
_zweitschrift(
    "/messages/{nachricht_id}/invitation",
    termine.router,
    termine.einladung,
    "GET",
    "The invitation in a message",
)
_zweitschrift(
    "/messages/{nachricht_id}/invitation/answer",
    termine.router,
    termine.antworten,
    "POST",
    "Answer an invitation",
)

# --- Schreiben ------------------------------------------------------------- #

_zweitschrift(
    "/compose/template/{nachricht_id}",
    verfassen.router,
    verfassen.vorlage,
    "GET",
    "Template for a reply or a forward",
)
_zweitschrift(
    "/compose/signature/{konto_id}",
    verfassen.router,
    verfassen.signatur_fuer,
    "GET",
    "The signature of a mailbox",
)
_zweitschrift("/compose/send", verfassen.router, verfassen.senden_, "POST", "Send, now or later")
_zweitschrift("/drafts", verfassen.router, verfassen.entwurf_ablegen, "POST", "Save a draft")
_zweitschrift(
    "/drafts/{uid}", verfassen.router, verfassen.entwurf_wegwerfen, "DELETE", "Discard a draft"
)
_zweitschrift("/outbox", verfassen.router, verfassen.ausgang, "GET", "The outbox")
_zweitschrift(
    "/outbox/{ausgang_id}/cancel",
    verfassen.router,
    verfassen.ausgang_abbrechen,
    "POST",
    "Cancel a message in the outbox",
)
_zweitschrift(
    "/contacts/suggest", kontakte.router, kontakte.vorschlag, "GET", "Recipient suggestions"
)
_zweitschrift("/ai/text", ki.router, ki.text, "POST", "Rephrase, correct or translate a draft")


# --- Nur für die App ------------------------------------------------------- #


class Abgleichwunsch(BaseModel):
    #: Leer heißt: alle Postfächer.
    konto_id: str = ""


class Abgleichstand(BaseModel):
    #: So viele Abgleiche wurden angestoßen.
    gestartet: int
    #: So viele liefen schon.
    laufen_schon: int


@router.post(
    "/sync",
    response_model=Abgleichstand,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Look for new mail",
)
def abgleichen(
    person: AngemeldeterBenutzer, db: DbSession, wunsch: Abgleichwunsch | None = None
) -> Abgleichstand:
    """Anstoßen, nicht abwarten: Der Posteingang jedes Postfachs im Hintergrund.

    ⚠️ **Anders als im Browser.** Dort läuft der Abgleich in der Anfrage und über
    alle Ordner; ein erster Abgleich dauert Stunden, und ein Telefon wartet
    nicht so lange. Das Ergebnis steht danach unter ``/changes``.
    """
    ziel = wunsch.konto_id if wunsch else ""
    konten_ = [k for k in kontendienst.meine(db, person) if k.aktiv and (not ziel or k.id == ziel)]
    if ziel and not konten_:
        raise MeldungHttp(status.HTTP_404_NOT_FOUND, "postfach_unbekannt")
    gestartet = sum(abgleich.im_hintergrund(k.id) for k in konten_)
    return Abgleichstand(gestartet=gestartet, laufen_schon=len(konten_) - gestartet)


class Aenderungszeile(BaseModel):
    seq: int
    art: Literal["nachricht", "ordner", "postfach"]
    #: Die Kennung der Mail, des Ordners oder des Postfachs.
    kennung: str
    konto_id: str = ""
    #: Das Ding gibt es nicht mehr: aus dem Speicher nehmen.
    weg: bool = False
    #: Die Listenzeile, wenn ``art`` ``nachricht`` ist und ``weg`` falsch. Bei
    #: ``ordner`` und ``postfach`` holt die App den Baum neu.
    nachricht: nachrichten.Zeile | None = None


class Aenderungsseite(BaseModel):
    eintraege: list[Aenderungszeile]
    #: Damit als nächstes fragen.
    weiter: int
    mehr: bool
    #: Die neueste Nummer überhaupt.
    stand: int


@router.get(
    "/changes",
    response_model=Aenderungsseite,
    summary="What changed after a number",
    responses={410: {"description": "`app_von_vorn`: read the lists again, then start from `stand`"}},
)
def aenderungen_lesen(
    person: AngemeldeterBenutzer,
    db: DbSession,
    since: int = Query(default=0, ge=0, le=2**62),
    limit: int = Query(default=200, ge=1, le=500),
) -> Aenderungsseite:
    """Neues, Geändertes und Entferntes, älteste Änderung zuerst.

    Der Ablauf: ``since=0`` gibt die aktuelle Nummer und nichts sonst. Mit ihr
    liest die App die Listen, danach fragt sie mit ``weiter``, bis ``mehr``
    falsch ist. Kommt 410 ``app_von_vorn``, passt ihr Speicher nicht mehr.

    ⚠️ **Eine Mail steht hier mit ihrem heutigen Stand**, nicht mit dem zur
    Nummer. Ist sie inzwischen fort, fehlt die Zeile, und weiter hinten steht
    ihr ``weg``. Doppelte Arbeit, aber nie ein falscher Stand.
    """
    try:
        seite = aenderungen.seite(db, person.id, since, limit)
    except aenderungen.AenderungFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_410_GONE) from fehler

    ids = [int(z.kennung) for z in seite.eintraege if z.art == "nachricht" and not z.weg]
    gefunden = {
        n.id: n
        for n in db.scalars(
            select(Nachricht).where(Nachricht.id.in_(ids), Nachricht.benutzer_id == person.id)
        )
    }
    vertraut = nachrichten._vertraut(db, gefunden.values())
    zeilen: list[Aenderungszeile] = []
    for z in seite.eintraege:
        mail = None
        if z.art == "nachricht" and not z.weg:
            n = gefunden.get(int(z.kennung))
            if n is None:
                continue
            mail = nachrichten._zeile(n, vertraut)
        zeilen.append(
            Aenderungszeile(
                seq=z.seq,
                art=z.art,
                kennung=z.kennung,
                konto_id=z.konto_id,
                weg=z.weg,
                nachricht=mail,
            )
        )
    return Aenderungsseite(eintraege=zeilen, weiter=seite.weiter, mehr=seite.mehr, stand=seite.stand)


class Pushziel(BaseModel):
    #: Das Ticket vom Relay.
    ticket: str = Field(min_length=1, max_length=1024)
    #: Der öffentliche X25519-Schlüssel des Geräts, base64 von 32 Byte. Bewusst
    #: ohne Längengrenze hier: Ein falscher Schlüssel soll ``kein_gueltiger_schluessel``
    #: geben, kein 422.
    schluessel: str


class Pushstand(BaseModel):
    status: str = "ok"


@router.put("/push", response_model=Pushstand, summary="Where notifications for this device go")
def push_merken(ziel: Pushziel, sitzung: AktiveSitzung, db: DbSession) -> Pushstand:
    """Ticket und Geräteschlüssel merken. Die App ruft das bei jedem Start."""
    if not pushdienst.schluessel_gueltig(ziel.schluessel):
        raise MeldungHttp(status.HTTP_400_BAD_REQUEST, "kein_gueltiger_schluessel")
    pushdienst.geraet_merken(db, sitzung, ziel.ticket, ziel.schluessel)
    return Pushstand()


@router.delete("/push", response_model=Pushstand, summary="Stop notifications for this device")
def push_vergessen(sitzung: AktiveSitzung, db: DbSession) -> Pushstand:
    """Ticket und Geräteschlüssel vergessen; das Gerät bleibt gekoppelt."""
    pushdienst.geraet_vergessen(db, sitzung)
    return Pushstand()


#: ⚠️ **Die Liste ist das Versprechen.** ``test_app_zusage.py`` hält sie gegen
#: die Routentabelle. Eine Adresse kommt nur durch einen Eintrag hier dazu, und
#: eine, die wegfällt, braucht ``/api/app/2``.
ZUGESAGT = (
    "/api/app/1/accounts",
    "/api/app/1/accounts/{konto_id}/folders",
    "/api/app/1/ai/text",
    "/api/app/1/changes",
    "/api/app/1/compose/send",
    "/api/app/1/compose/signature/{konto_id}",
    "/api/app/1/compose/template/{nachricht_id}",
    "/api/app/1/contacts/suggest",
    "/api/app/1/device",
    "/api/app/1/drafts",
    "/api/app/1/drafts/{uid}",
    "/api/app/1/events",
    "/api/app/1/folders/{ordner_id}/empty",
    "/api/app/1/folders/{ordner_id}/read",
    "/api/app/1/labels",
    "/api/app/1/me",
    "/api/app/1/messages",
    "/api/app/1/messages/archive",
    "/api/app/1/messages/delete",
    "/api/app/1/messages/delete-forever",
    "/api/app/1/messages/junk",
    "/api/app/1/messages/labels/{atom}",
    "/api/app/1/messages/move",
    "/api/app/1/messages/thread/{schluessel:path}",
    "/api/app/1/messages/undo",
    "/api/app/1/messages/{nachricht_id}",
    "/api/app/1/messages/{nachricht_id}/attachments/{anhang_id}",
    "/api/app/1/messages/{nachricht_id}/flags",
    "/api/app/1/messages/{nachricht_id}/images",
    "/api/app/1/messages/{nachricht_id}/invitation",
    "/api/app/1/messages/{nachricht_id}/invitation/answer",
    "/api/app/1/messages/{nachricht_id}/summary",
    "/api/app/1/messages/{nachricht_id}/unsubscribe",
    "/api/app/1/outbox",
    "/api/app/1/outbox/{ausgang_id}/cancel",
    "/api/app/1/pairing/code",
    "/api/app/1/pairing/{pairing_id}/key",
    "/api/app/1/push",
    "/api/app/1/search",
    "/api/app/1/sender-image",
    "/api/app/1/snoozes",
    "/api/app/1/snoozes/{eintrag_id}",
    "/api/app/1/sync",
    "/api/app/1/tasks",
)
