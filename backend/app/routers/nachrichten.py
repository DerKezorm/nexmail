"""Nachrichten lesen.

⚠️ **Jede Abfrage geht durch ``benutzer_id``.** Nicht durch verstreute
``where``-Bedingungen — siehe FALLSTRICKE.md §5. Ein vergessenes Filter wäre
hier kein Anzeigefehler, sondern fremde Post.
"""

from __future__ import annotations

import base64
import json
import re
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select

from ..config import get_settings
from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Anhang, Konto, Nachricht, Ordner
from ..services import (
    abgleich,
    bereinigen,
    handeln,
    imap as imapdienst,
    konten as kontendienst,
)

logger = logging.getLogger("nexmail.nachrichten")

router = APIRouter(prefix="/api/nachrichten", tags=["nachrichten"])


class Person(BaseModel):
    name: str = ""
    adresse: str = ""


class Zeile(BaseModel):
    id: int
    konto_id: str
    ordner_id: int
    von: Person
    betreff: str
    anreisser: str
    datum: datetime
    gelesen: bool
    markiert: bool
    beantwortet: bool
    hat_anhang: bool
    groesse: int
    #: Wie viele Nachrichten der Strang hat — ueber alle Ordner. 1 heisst:
    #: kein Strang. Nur bei ``gruppiert=true`` groesser als 1.
    strang_anzahl: int = 1
    strang_ungelesen: int = 0
    #: Der Schluessel, mit dem sich der Strang aufklappen laesst.
    thread_key: str = ""


class AnhangZeile(BaseModel):
    id: int
    dateiname: str
    mime: str
    groesse: int
    inline: bool


class Voll(Zeile):
    an: list[Person]
    kopie: list[Person]
    #: Bereinigt und mit ausgeklinkten Bildern.
    html: str
    text: str
    geblockte_bilder: int
    anhaenge: list[AnhangZeile]


def _personen(roh: str) -> list[Person]:
    try:
        return [Person(name=e.get("n", ""), adresse=e.get("a", "")) for e in json.loads(roh or "[]")]
    except (ValueError, AttributeError):
        return []


def _zeile(n: Nachricht) -> Zeile:
    return Zeile(
        id=n.id,
        konto_id=n.konto_id,
        ordner_id=n.ordner_id,
        von=Person(name=n.von_name, adresse=n.von_adresse),
        betreff=n.betreff,
        anreisser=n.anreisser,
        datum=n.datum,
        gelesen=n.gelesen,
        markiert=n.markiert,
        beantwortet=n.beantwortet,
        hat_anhang=n.hat_anhang,
        groesse=n.groesse,
        thread_key=n.thread_key,
    )


@router.get("", response_model=list[Zeile])
def liste(
    person: AngemeldeterBenutzer,
    db: DbSession,
    ordner_id: int | None = None,
    #: Ohne Ordner: alle Posteingänge. Das ist die zusammengeführte Ansicht.
    nur_posteingaenge: bool = False,
    suche: str = "",
    #: ``alle`` | ``ungelesen`` | ``markiert``
    #:
    #: ⚠️ **Im Server gefiltert, nicht im Browser.** Die Oberfläche hält nur
    #: die neuesten Zeilen eines Ordners — ein Filter darin fände die
    #: markierte Mail von vor drei Monaten nie und meldete „keine".
    filter: str = "alle",
    #: Kommagetrennte Postfach-Kennungen. Leer heißt: alle Postfächer.
    #:
    #: ⚠️ **Die Einschränkung gehört in den Server, nicht in den Browser.**
    #: Die Oberfläche hält nur die neuesten 200 Zeilen. Wer sie erst holt und
    #: dann nach Postfach aussiebt, zeigt bei einem vollen Posteingang womöglich
    #: drei Mails und behauptet damit, mehr gebe es nicht.
    konto_ids: str = "",
    grenze: int = Query(default=100, le=500),
    versatz: int = 0,
    #: Weiterlesen **hinter** dieser Zeile: ``<ISO-Datum>,<id>``.
    #:
    #: ⚠️ **Nicht über ``versatz`` blättern.** Die Liste steht nach Datum,
    #: und oben kommt ständig Neues dazu. Trifft zwischen zwei Seiten eine
    #: Mail ein, rutscht alles um eins nach unten: Seite 2 beginnt mit der
    #: letzten Zeile von Seite 1. Der Betreiber sieht Nachrichten doppelt und
    #: eine andere gar nicht — und hält es für einen Abgleichfehler.
    #:
    #: Deshalb der Merkpunkt: „gib mir, was älter ist als das hier". Die
    #: Kennung muss mit, weil zwei Mails dieselbe Sekunde tragen können.
    nach: str = "",
    #: Einen Strang zu einer Zeile zusammenfassen.
    #:
    #: ⚠️ **Gezeigt wird die neueste Nachricht im gerade sichtbaren Bereich**,
    #: gezaehlt wird ueber **alle** Ordner. Das klingt widerspruechlich und ist
    #: es nicht: Im Posteingang will man sehen, was dort zuletzt ankam — aber
    #: wissen, dass man schon geantwortet hat.
    gruppiert: bool = False,
) -> list[Zeile]:
    abfrage = select(Nachricht).where(Nachricht.benutzer_id == person.id)

    gewuenscht = [k for k in konto_ids.split(",") if k]
    if gewuenscht:
        # ⚠️ Über die Ordner des Postfachs, und die Postfächer selbst noch
        # einmal am Benutzer geprüft: Eine fremde Kennung darf hier nichts
        # herausholen, auch wenn sie echt ist.
        erlaubte = (
            select(Ordner.id)
            .join(Konto, Konto.id == Ordner.konto_id)
            .where(Konto.benutzer_id == person.id, Konto.id.in_(gewuenscht))
        )
        abfrage = abfrage.where(Nachricht.ordner_id.in_(erlaubte))

    if ordner_id is not None:
        abfrage = abfrage.where(Nachricht.ordner_id == ordner_id)
    elif nur_posteingaenge:
        eingaenge = (
            select(Ordner.id)
            .join(Konto, Konto.id == Ordner.konto_id)
            .where(Konto.benutzer_id == person.id, Ordner.rolle == "posteingang")
        )
        abfrage = abfrage.where(Nachricht.ordner_id.in_(eingaenge))

    if filter == "ungelesen":
        abfrage = abfrage.where(Nachricht.gelesen.is_(False))
    elif filter == "markiert":
        abfrage = abfrage.where(Nachricht.markiert.is_(True))

    if suche.strip():
        muster = f"%{suche.strip()}%"
        abfrage = abfrage.where(
            Nachricht.betreff.ilike(muster)
            | Nachricht.von_name.ilike(muster)
            | Nachricht.von_adresse.ilike(muster)
            | Nachricht.anreisser.ilike(muster)
        )

    if nach:
        merk_datum, _, merk_id = nach.rpartition(",")
        try:
            grenz_datum = datetime.fromisoformat(merk_datum)
            grenz_id = int(merk_id)
        except ValueError:
            # ⚠️ Ein kaputter Merkpunkt darf nicht in „dann eben von vorn"
            # umschlagen — sonst hängt das Nachladen in einer Schleife und
            # zeigt immer wieder dieselben Zeilen.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Der Merkpunkt zum Weiterlesen ist unbrauchbar.",
            ) from None
        if grenz_datum.tzinfo is None:
            grenz_datum = grenz_datum.replace(tzinfo=timezone.utc)
        abfrage = abfrage.where(
            (Nachricht.datum < grenz_datum)
            | ((Nachricht.datum == grenz_datum) & (Nachricht.id < grenz_id))
        )

    # ⚠️ Die Kennung als zweites Ordnungsmerkmal — ohne sie ist die Reihenfolge
    # bei gleicher Sekunde nicht festgelegt, und der Merkpunkt trifft mal die
    # eine, mal die andere Zeile.
    abfrage = abfrage.order_by(Nachricht.datum.desc(), Nachricht.id.desc())
    if gruppiert:
        return _gruppiert(db, person, abfrage, grenze, versatz)

    abfrage = abfrage.limit(grenze).offset(versatz)
    return [_zeile(n) for n in db.execute(abfrage).scalars().all()]


def _gruppiert(db, person, abfrage, grenze: int, versatz: int) -> list[Zeile]:
    """Je Strang eine Zeile.

    ⚠️ **Ein Fensterausdruck statt einer Schleife.** Die Alternative waere,
    alles zu holen und in Python zu gruppieren — das bricht genau dann, wenn es
    darauf ankommt: bei einem vollen Posteingang. Fensterausdruecke kann SQLite
    seit 3.25.
    """
    rang = (
        func.row_number()
        .over(
            partition_by=Nachricht.thread_key,
            order_by=(Nachricht.datum.desc(), Nachricht.id.desc()),
        )
        .label("rang")
    )
    innen = abfrage.add_columns(rang).subquery()

    aussen = (
        select(Nachricht)
        .join(innen, Nachricht.id == innen.c.id)
        .where(innen.c.rang == 1)
        .order_by(Nachricht.datum.desc(), Nachricht.id.desc())
        .limit(grenze)
        .offset(versatz)
    )
    kopfzeilen = list(db.execute(aussen).scalars().all())
    if not kopfzeilen:
        return []

    # ⚠️ **Gezaehlt wird ueber alle Ordner** — sonst fehlt im Strang die
    # eigene Antwort, und das ist der Nutzen der Ansicht.
    schluessel = [n.thread_key for n in kopfzeilen if n.thread_key]
    zaehler: dict[str, tuple[int, int]] = {}
    if schluessel:
        for key, anzahl, ungelesen in db.execute(
            select(
                Nachricht.thread_key,
                func.count(Nachricht.id),
                func.sum(case((Nachricht.gelesen.is_(False), 1), else_=0)),
            )
            .where(
                Nachricht.benutzer_id == person.id,
                Nachricht.thread_key.in_(schluessel),
            )
            .group_by(Nachricht.thread_key)
        ).all():
            zaehler[key] = (int(anzahl or 0), int(ungelesen or 0))

    heraus = []
    for n in kopfzeilen:
        anzahl, ungelesen = zaehler.get(n.thread_key, (1, 0 if n.gelesen else 1))
        zeile = _zeile(n)
        zeile.strang_anzahl = anzahl
        zeile.strang_ungelesen = ungelesen
        heraus.append(zeile)
    return heraus


@router.get("/strang/{schluessel:path}", response_model=list[Zeile])
def strang(schluessel: str, person: AngemeldeterBenutzer, db: DbSession) -> list[Zeile]:
    """Alle Nachrichten eines Strangs — ueber alle Ordner, aelteste zuerst.

    ⚠️ **Aelteste zuerst**, anders als die Liste. Ein Gespraech liest man von
    vorn; die Liste dagegen zeigt, was zuletzt passiert ist.
    """
    zeilen = db.execute(
        select(Nachricht)
        .where(Nachricht.benutzer_id == person.id, Nachricht.thread_key == schluessel)
        .order_by(Nachricht.datum, Nachricht.id)
        .limit(200)
    ).scalars().all()
    return [_zeile(n) for n in zeilen]


def _meine(db, person, nachricht_id: int) -> Nachricht:
    nachricht = db.get(Nachricht, nachricht_id)
    # Erst holen, dann Besitzer prüfen - und bei fremdem Besitz dasselbe
    # melden wie bei „gibt es nicht".
    if nachricht is None or nachricht.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return nachricht


@router.get("/{nachricht_id}", response_model=Voll)
def eine(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Voll:
    """Eine Nachricht mit Körper — der wird beim ersten Mal geholt."""
    nachricht = _meine(db, person, nachricht_id)

    if nachricht.koerper_geholt is None:
        konto = db.get(Konto, nachricht.konto_id)
        imap_pw, _ = kontendienst.passwoerter_lesen(konto)
        with abgleich.HALTER.schloss(konto.id):
            klient = imapdienst.verbinden(
                konto.imap_server,
                konto.imap_port,
                konto.imap_sicherheit,
                konto.imap_benutzer,
                imap_pw,
            )
            try:
                abgleich.koerper_holen(klient, db, nachricht)
            finally:
                try:
                    klient.logout()
                except Exception:  # noqa: BLE001
                    pass

    grund = _zeile(nachricht).model_dump()
    return Voll(
        **grund,
        an=_personen(nachricht.an_json),
        kopie=_personen(nachricht.kopie_json),
        html=bereinigen.cid_einsetzen(nachricht.koerper_html, _inline_quellen(nachricht)),
        text=nachricht.koerper_text,
        geblockte_bilder=nachricht.geblockte_bilder,
        anhaenge=[
            AnhangZeile(
                id=a.id,
                dateiname=a.dateiname,
                mime=a.mime,
                groesse=a.groesse,
                inline=bool(a.cid),
            )
            for a in nachricht.anhaenge
        ],
    )


class Html(BaseModel):
    html: str


@router.post("/{nachricht_id}/bilder", response_model=Html)
def bilder_anzeigen(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Html:
    """Die Bilder wieder einhängen — auf ausdrücklichen Wunsch.

    ⚠️ **Das ist eine Entscheidung des Menschen, kein Vorgang.** Bis hierher
    hat der Browser die Adressen nie gesehen; danach weiß der Absender, dass
    und wann seine Mail geöffnet wurde.
    """
    nachricht = _meine(db, person, nachricht_id)
    return Html(html=bereinigen.bilder_einhaengen(nachricht.koerper_html))


#: Wie groß ein eingebettetes Bild höchstens sein darf, um im Lesebereich
#: mitgeliefert zu werden. ⚠️ Base64 bläht auf etwa 4/3 auf, und das Ganze
#: landet in einer JSON-Antwort - ohne Grenze macht ein Bildschirmfoto aus
#: einer Mail eine Antwort von zehn Megabyte. Darüber bleibt das Bild als
#: Anhang erreichbar, nur eben nicht im Text.
MAX_INLINE = 2 * 1024 * 1024


def _inline_quellen(nachricht: Nachricht) -> dict[str, str]:
    """Für jedes ``cid:`` eine Adresse, die der Lesebereich anzeigen kann.

    ⚠️ **Beigelegt, nicht verlinkt.** Der Lesebereich läuft in einem
    ``<iframe sandbox>`` ohne ``allow-same-origin``: Der Rahmen hat eine
    fremde Herkunft und bekäme bei einer Adresse wie ``/api/…`` weder
    Sitzungskeks noch Antwort. Ein Verweis dorthin wäre ein kaputtes Bild.
    """
    quellen: dict[str, str] = {}
    ordner = get_settings().blob_dir
    for anhang in nachricht.anhaenge:
        if not anhang.cid or not anhang.blob_hash:
            continue
        if not anhang.mime.startswith("image/"):
            continue
        if anhang.groesse > MAX_INLINE:
            logger.info("An inline image was too large to embed (%s bytes).", anhang.groesse)
            continue
        datei = ordner / anhang.blob_hash
        if not datei.is_file():
            continue
        roh = base64.b64encode(datei.read_bytes()).decode("ascii")
        quellen[anhang.cid] = f"data:{anhang.mime};base64,{roh}"
    return quellen


@router.get("/{nachricht_id}/anhang/{anhang_id}")
def anhang(nachricht_id: int, anhang_id: int, person: AngemeldeterBenutzer, db: DbSession):
    """Einen Anhang ausliefern.

    ⚠️ **Immer als Download, nie zur Anzeige im Browser.** Ein HTML-Anhang,
    den der Browser rendert, läuft unter nexmails eigener Herkunft - und damit
    an der ganzen Bereinigung vorbei. Deshalb ``attachment`` und ein
    unverfänglicher Typ.
    """
    nachricht = _meine(db, person, nachricht_id)
    zeile = db.get(Anhang, anhang_id)
    if zeile is None or zeile.nachricht_id != nachricht.id or not zeile.blob_hash:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    datei = get_settings().blob_dir / zeile.blob_hash
    if not datei.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    name = zeile.dateiname.replace('"', "").replace("\\", "")
    return FileResponse(
        datei,
        media_type="application/octet-stream",
        headers={"content-disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{nachricht_id}/roh")
def roh(nachricht_id: int, person: AngemeldeterBenutzer, db: DbSession):
    """Die Mail als ``.eml`` — zum Herunterladen und Aufbewahren.

    ⚠️ **Ungefiltert, und das ist der Sinn.** Eine ``.eml`` ist die Mail, wie
    sie ankam: mit allen Kopfzeilen, allen Teilen, allen Anhängen. Genau das
    braucht man, um sie in ein anderes Programm zu tragen oder jemandem zu
    zeigen, der sie prüfen soll.

    ⚠️ **Deshalb als Download, nie zur Anzeige.** ``content-disposition:
    attachment`` und ein unverfänglicher Typ: Ein Browser, der das rendert,
    liefe an der ganzen Bereinigung vorbei.
    """
    nachricht = _meine(db, person, nachricht_id)
    konto = db.get(Konto, nachricht.konto_id)
    imap_pw, _ = kontendienst.passwoerter_lesen(konto)

    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.verbinden(
            konto.imap_server,
            konto.imap_port,
            konto.imap_sicherheit,
            konto.imap_benutzer,
            imap_pw,
        )
        try:
            klient.select_folder(nachricht.ordner.pfad, readonly=True)
            antwort = klient.fetch([nachricht.uid], [abgleich.GANZE_MAIL])
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    inhalt = antwort.get(nachricht.uid, {}).get(abgleich.GANZE_MAIL_SCHLUESSEL)
    if not inhalt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Der Server kennt diese Nachricht nicht mehr.",
        )

    # Ein Dateiname, den jedes Betriebssystem annimmt.
    name = re.sub(r'[\/:*?"<>|]', "_", (nachricht.betreff or "nachricht").strip())[:80]
    return Response(
        content=inhalt,
        media_type="application/octet-stream",
        headers={"content-disposition": f'attachment; filename="{name or "nachricht"}.eml"'},
    )


@router.get("/{nachricht_id}/inline/{anhang_id}")
def inline_bild(nachricht_id: int, anhang_id: int, person: AngemeldeterBenutzer, db: DbSession):
    """Ein Inline-Bild (``cid:``) für den Lesebereich.

    Anders als beim Anhang wird hier im Browser angezeigt — aber nur, wenn der
    Teil auch wirklich ein Bild ist. Sonst wäre das der Weg an der
    Bereinigung vorbei, den der Anhang-Endpunkt gerade verschließt.
    """
    nachricht = _meine(db, person, nachricht_id)
    zeile = db.get(Anhang, anhang_id)
    if zeile is None or zeile.nachricht_id != nachricht.id or not zeile.blob_hash:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not zeile.mime.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    datei = get_settings().blob_dir / zeile.blob_hash
    if not datei.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(datei, media_type=zeile.mime)


class Flagwunsch(BaseModel):
    gelesen: bool | None = None
    markiert: bool | None = None


@router.post("/{nachricht_id}/flags", response_model=Zeile)
def flags_setzen(
    nachricht_id: int, wunsch: Flagwunsch, person: AngemeldeterBenutzer, db: DbSession
) -> Zeile:
    """Gelesen und markiert setzen — **auf dem Server**, nicht nur hier.

    ⚠️ Wer das nur lokal merkt, hat eine Anwendung, die ihrem Besitzer etwas
    vormacht: Auf dem Telefon steht die Mail weiter ungelesen da, und beim
    nächsten Abgleich springt sie hier zurück. Deshalb erst STORE, dann
    speichern — und wenn der Server nicht mitspielt, wird auch lokal nichts
    geändert.
    """
    nachricht = _meine(db, person, nachricht_id)
    konto = db.get(Konto, nachricht.konto_id)
    imap_pw, _ = kontendienst.passwoerter_lesen(konto)

    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.verbinden(
            konto.imap_server,
            konto.imap_port,
            konto.imap_sicherheit,
            konto.imap_benutzer,
            imap_pw,
        )
        try:
            klient.select_folder(nachricht.ordner.pfad, readonly=False)
            if wunsch.gelesen is not None:
                if wunsch.gelesen:
                    klient.add_flags([nachricht.uid], [rb"\Seen"])
                else:
                    klient.remove_flags([nachricht.uid], [rb"\Seen"])
                nachricht.gelesen = wunsch.gelesen
            if wunsch.markiert is not None:
                if wunsch.markiert:
                    klient.add_flags([nachricht.uid], [rb"\Flagged"])
                else:
                    klient.remove_flags([nachricht.uid], [rb"\Flagged"])
                nachricht.markiert = wunsch.markiert
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    # Der Ordnerzähler hängt daran.
    nachricht.ordner.ungelesen = (
        db.query(Nachricht)
        .filter(Nachricht.ordner_id == nachricht.ordner_id, Nachricht.gelesen.is_(False))
        .count()
    )
    db.commit()
    return _zeile(nachricht)


# --- Handeln ------------------------------------------------------------- #


class Auswahl(BaseModel):
    ids: list[int]


class Verschiebewunsch(Auswahl):
    ordner_id: int


class Zugergebnis(BaseModel):
    bewegt: int
    #: Was zum Zurücknehmen gebraucht wird. Die Oberfläche schickt es
    #: unverändert an /zurueck.
    rueckweg: dict | None = None


def _auswahl(db, person, ids: list[int]) -> list[Nachricht]:
    if not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nichts ausgewählt.")
    # ⚠️ Jede einzelne durch dieselbe Besitzprüfung. Eine Liste von Kennungen
    # ist der bequemste Weg, fremde Post mitzunehmen.
    return [_meine(db, person, kennung) for kennung in ids]


def _zug(db, tun) -> Zugergebnis:
    try:
        weg = tun()
    except handeln.HandelnFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    except imapdienst.Verbindungsfehler as fehler:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=fehler.text) from fehler
    return Zugergebnis(bewegt=len(weg.message_ids), rueckweg=weg.__dict__)


@router.post("/verschieben", response_model=Zugergebnis)
def verschieben(wunsch: Verschiebewunsch, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    nachrichten = _auswahl(db, person, wunsch.ids)
    ziel = db.get(Ordner, wunsch.ordner_id)
    if ziel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Der Zielordner muss dem Benutzer gehören - sonst wäre das ein Weg,
    # eigene Post in ein fremdes Postfach zu schieben.
    konto = db.get(Konto, ziel.konto_id)
    if konto is None or konto.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _zug(db, lambda: handeln.verschieben(db, nachrichten, ziel))


@router.post("/loeschen", response_model=Zugergebnis)
def loeschen(auswahl: Auswahl, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    """In den Papierkorb — nicht endgültig. Dafür gibt es „Ordner leeren"."""
    nachrichten = _auswahl(db, person, auswahl.ids)
    return _zug(db, lambda: handeln.in_rolle(db, nachrichten, "papierkorb"))


@router.post("/archivieren", response_model=Zugergebnis)
def archivieren(auswahl: Auswahl, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    nachrichten = _auswahl(db, person, auswahl.ids)
    return _zug(db, lambda: handeln.in_rolle(db, nachrichten, "archiv"))


@router.post("/junk", response_model=Zugergebnis)
def junk(auswahl: Auswahl, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    nachrichten = _auswahl(db, person, auswahl.ids)
    return _zug(db, lambda: handeln.in_rolle(db, nachrichten, "junk"))


class Rueckwunsch(BaseModel):
    konto_id: str
    quelle_pfad: str
    ziel_pfad: str
    message_ids: list[str]
    text: str = ""


@router.post("/zurueck", response_model=Zugergebnis)
def zurueck(wunsch: Rueckwunsch, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    """Einen Zug zurücknehmen.

    ⚠️ Das Postfach wird geprüft, nicht geglaubt: Die Oberfläche schickt hier
    zurück, was sie bekommen hat — und das kommt aus dem Browser.
    """
    konto = db.get(Konto, wunsch.konto_id)
    if konto is None or konto.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    weg = handeln.Rueckweg(
        konto_id=wunsch.konto_id,
        quelle_pfad=wunsch.quelle_pfad,
        ziel_pfad=wunsch.ziel_pfad,
        message_ids=wunsch.message_ids,
    )
    try:
        anzahl = handeln.zurueck(db, weg)
    except handeln.HandelnFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler
    return Zugergebnis(bewegt=anzahl)


@router.post("/ordner/{ordner_id}/leeren", response_model=Zugergebnis)
def leeren(ordner_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    """⚠️ Der einzige Vorgang ohne Rückweg. Nur Papierkorb und Junk."""
    ordner = db.get(Ordner, ordner_id)
    if ordner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    konto = db.get(Konto, ordner.konto_id)
    if konto is None or konto.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        return Zugergebnis(bewegt=handeln.ordner_leeren(db, ordner))
    except handeln.HandelnFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler


@router.post("/ordner/{ordner_id}/gelesen", response_model=Zugergebnis)
def ordner_gelesen(ordner_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Zugergebnis:
    """Alles Ungelesene in einem Ordner als gelesen markieren.

    ⚠️ **Ein Befehl für alle.** Bei dreihundert Ungelesenen wären es sonst
    dreihundert Umläufe zum Server.
    """
    ordner = db.get(Ordner, ordner_id)
    if ordner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    konto = db.get(Konto, ordner.konto_id)
    if konto is None or konto.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        return Zugergebnis(bewegt=handeln.ordner_als_gelesen(db, konto, ordner))
    except handeln.HandelnFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler


class Abgleichergebnis(BaseModel):
    neu: int
    entfernt: int
    ordner: int


@router.post("/abgleichen", response_model=Abgleichergebnis)
def abgleichen(
    person: AngemeldeterBenutzer, db: DbSession, konto_id: str | None = None
) -> Abgleichergebnis:
    """Von Hand anstoßen. Der Takt im Hintergrund kommt später."""
    konten = kontendienst.meine(db, person)
    if konto_id:
        konten = [k for k in konten if k.id == konto_id]
        if not konten:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    neu = entfernt = ordner = 0
    for konto in konten:
        if not konto.aktiv:
            continue
        try:
            runden = abgleich.konto_abgleichen(db, konto)
        except imapdienst.Verbindungsfehler as fehler:
            konto.letzter_fehler = fehler.text
            db.commit()
            continue
        for runde in runden.values():
            neu += runde.neu
            entfernt += runde.entfernt
            ordner += 1

    return Abgleichergebnis(neu=neu, entfernt=entfernt, ordner=ordner)
