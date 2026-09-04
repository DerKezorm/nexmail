"""Schreiben: Vorlage holen, Entwurf ablegen, senden, Ausgang ansehen."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Ausgang, Konto, Nachricht
from ..services import (
    abgleich,
    aliase as aliasdienst,
    entwuerfe as entwurfsdienst,
    konten as kontendienst,
    mime,
    senden,
    verfassen,
)
from ..meldung import MeldungHttp

logger = logging.getLogger("nexmail.verfassen")

router = APIRouter(prefix="/api/verfassen", tags=["verfassen"])

#: Grenze für einen einzelnen Anhang. Ohne sie legt ein Versehen den
#: Arbeitsspeicher des Containers lahm — und die meisten Anbieter nehmen
#: ohnehin nicht mehr als 25 MB je Mail.
MAX_ANHANG = 25 * 1024 * 1024


class VorlagenAnlage(BaseModel):
    """Ein Anhang, den die Vorlage schon mitbringt — die Roh-``.eml`` beim
    Weiterleiten als Anhang oder die Anhänge eines wieder geöffneten
    Entwurfs. Dieselbe Form wie ``Anlage`` im Sendewunsch, damit die
    Oberfläche ihn unverändert dorthin durchreichen kann."""

    dateiname: str
    mime_typ: str
    inhalt_b64: str
    #: Bei Bildern im Text des Entwurfs: die ``Content-ID`` — die Oberfläche
    #: setzt daraus wieder eine anzeigbare Adresse in den Editor.
    cid: str = ""


class Vorlage(BaseModel):
    konto_id: str
    an: list[str]
    kopie: list[str]
    #: Nur beim Weiterschreiben eines Entwurfs gefüllt — in gewöhnlicher Post
    #: gibt es keine ``Bcc``-Kopfzeile, die man lesen könnte.
    blindkopie: list[str] = []
    betreff: str
    #: Bereits bereinigtes Zitat bzw. der Weiterleitungsblock.
    html: str
    in_reply_to: str
    references: list[str]
    #: Nur beim Weiterschreiben gesetzt: die UID der Fassung, die dabei
    #: ersetzt wird. 0 heißt „das ist kein Entwurf".
    entwurf_uid: int = 0
    #: Die Signatur für dieses Postfach, schon bereinigt. Leer heißt: keine.
    signatur: str = ""
    #: Beim Weiterleiten als Anhang die Roh-.eml, beim Weiterschreiben eines
    #: Entwurfs dessen Anhänge.
    anlagen: list[VorlagenAnlage] = []
    #: Unter welcher Adresse geantwortet werden soll. Leer heißt: die
    #: Hauptadresse des Postfachs.
    von_adresse: str = ""


@router.get("/vorlage/{nachricht_id}", response_model=Vorlage)
def vorlage(
    nachricht_id: int, art: str, person: AngemeldeterBenutzer, db: DbSession
) -> Vorlage:
    """Was im Verfassen-Fenster stehen soll — Antwort, Allen, Weiterleitung,
    Weiterleiten als Anhang.

    ⚠️ **Gebaut wird das im Server, nicht im Browser.** Empfänger, Betreff und
    Kette folgen Regeln, die man in der Oberfläche zweimal pflegen müsste — und
    das Zitat ist fremdes HTML und gehört durch dieselbe Bereinigung wie beim
    Anzeigen.
    """
    if art not in ("antwort", "allen", "weiter", "anhang", "entwurf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="art_unbekannt")

    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    konto = db.get(Konto, nachricht.konto_id)

    if art == "anhang":
        # Weiterleiten als Anhang: Die Mail fährt **unverändert** als
        # Roh-.eml mit — nichts wird zitiert, nichts bereinigt, nichts
        # umkodiert. Genau dafür ist der Modus da: Der Empfänger soll die
        # Mail prüfen können, wie sie ankam, samt aller Kopfzeilen.
        from ..services import signaturen as signaturdienst

        unterschrift = signaturdienst.fuer_konto(db, person, konto.id)
        roh = _roh(db, konto, nachricht)
        return Vorlage(
            signatur=unterschrift.html if unterschrift else "",
            konto_id=konto.id,
            von_adresse=_antwortabsender(konto, nachricht),
            an=[],
            kopie=[],
            betreff=verfassen.weiterleitung_anhang_betreff(nachricht.betreff),
            html="",
            in_reply_to="",
            references=[],
            anlagen=[
                VorlagenAnlage(
                    # Derselbe Name wie beim .eml-Download — der Empfänger
                    # sieht dieselbe Datei, die man selbst herunterlädt.
                    dateiname=mime.eml_dateiname(nachricht.betreff),
                    mime_typ="message/rfc822",
                    inhalt_b64=base64.b64encode(roh).decode("ascii"),
                )
            ],
        )

    zerlegt = mime.zerlegen(_roh(db, konto, nachricht))

    eigene = {k.adresse.lower() for k in kontendienst.meine(db, person)}

    if art == "entwurf":
        # ⚠️ **Weiterschreiben, nicht antworten.** Empfänger, Betreff und Text
        # sind die des Entwurfs selbst - hier wird nichts zitiert und nichts
        # umgeschrieben. Die UID kommt mit, damit das nächste Speichern diese
        # Fassung ersetzt statt eine zweite anzulegen.
        #
        # ⚠️ **Blindkopie und Anhänge müssen mit.** Die Bcc-Zeile schreibt
        # ``senden._mit_blindkopie`` beim Abbruch eigens in den Entwurf —
        # bliebe sie hier liegen, verlöre das Wieder-Öffnen stillschweigend
        # Empfänger. Und da die UID mitkommt, würde das Senden der
        # verstümmelten Fassung die vollständige auch noch wegräumen.
        return Vorlage(
            konto_id=konto.id,
            von_adresse=_antwortabsender(konto, nachricht),
            an=[p.adresse for p in zerlegt.an if p.adresse],
            kopie=[p.adresse for p in zerlegt.kopie if p.adresse],
            blindkopie=[p.adresse for p in zerlegt.blindkopie if p.adresse],
            betreff=zerlegt.betreff,
            html=zerlegt.html or _text_als_html(zerlegt.text),
            in_reply_to=zerlegt.in_reply_to,
            references=zerlegt.references,
            entwurf_uid=nachricht.uid,
            anlagen=[
                VorlagenAnlage(
                    dateiname=a.dateiname,
                    mime_typ=a.mime or "application/octet-stream",
                    inhalt_b64=base64.b64encode(a.inhalt).decode("ascii"),
                    cid=a.cid,
                )
                for a in zerlegt.anhaenge
            ],
        )

    if art == "weiter":
        from ..services import signaturen as signaturdienst

        unterschrift = signaturdienst.fuer_konto(db, person, konto.id)
        return Vorlage(
            signatur=unterschrift.html if unterschrift else "",
            konto_id=konto.id,
            von_adresse=_antwortabsender(konto, nachricht),
            an=[],
            kopie=[],
            betreff=verfassen.weiterleitung_betreff(zerlegt.betreff),
            html=verfassen.weiterleitung_html(zerlegt),
            in_reply_to="",
            references=[],
        )

    from ..services import signaturen as signaturdienst

    unterschrift = signaturdienst.fuer_konto(db, person, konto.id)
    an, kopie = verfassen.antwort_empfaenger(zerlegt, eigene, allen=(art == "allen"))
    return Vorlage(
        signatur=unterschrift.html if unterschrift else "",
        konto_id=konto.id,
        von_adresse=_antwortabsender(konto, nachricht),
        an=an,
        kopie=kopie,
        betreff=verfassen.antwort_betreff(zerlegt.betreff),
        html=verfassen.zitat_html(zerlegt),
        in_reply_to=zerlegt.message_id,
        references=verfassen.references_fuer_antwort(zerlegt),
    )


def _antwortabsender(konto: Konto, nachricht: Nachricht) -> str:
    """Die Adresse, unter der auf diese Nachricht geantwortet wird.

    ⚠️ **Das ist der ganze Zweck der Aliasse.** Wer auf eine Mail an ``x@``
    antwortet, will als ``x@`` antworten; sonst erfährt der andere die
    Hauptadresse, und die Trennung, für die man sich die Zweitadresse geholt
    hat, ist dahin.

    ⚠️ **Gelesen wird aus der gespeicherten Zeile, nicht aus der Roh-Mail.**
    Empfänger und Kopie stehen längst in ``an_json``; die Mail dafür noch
    einmal zu zerlegen wäre Arbeit für nichts — und beim Weiterleiten als
    Anhang wird sie ausdrücklich **nicht** zerlegt.
    """

    def adressen(roh: str) -> list[str]:
        try:
            eintraege = json.loads(roh or "[]")
        except (ValueError, TypeError):
            return []
        return [str(e.get("a", "")) for e in eintraege if isinstance(e, dict)]

    treffer = aliasdienst.passend(
        konto, adressen(nachricht.an_json) + adressen(nachricht.kopie_json)
    )
    return treffer.adresse if treffer else ""


def _text_als_html(text: str) -> str:
    """Ein Entwurf ohne HTML-Teil - dann steht der reine Text im Editor.

    Die Maskierung ist Pflicht: Ein ``<`` im Text wuerde sonst als Auszeichnung
    gelesen und der Rest der Zeile verschwaende.
    """
    if not text.strip():
        return ""
    zeilen = (verfassen._maskieren(z) for z in text.splitlines())
    return "".join(f"<p>{z or '<br>'}</p>" for z in zeilen)


def _roh(db, konto: Konto, nachricht: Nachricht) -> bytes:
    """Die ganze Mail holen — für Zitat, Kette und den Anhang-Modus.

    Der zwischengespeicherte Körper genügt hier nicht: Für ``References``
    braucht es die Kopfzeilen, und die stehen nicht in der Datenbank. Der
    Abruf selbst ist derselbe wie beim ``.eml``-Download
    (``abgleich.roh_holen``) — eine Stelle, nicht zwei.
    """
    roh = abgleich.roh_holen(db, konto, nachricht)
    if not roh:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="nachricht_weg",
        )
    return roh


class Anlage(BaseModel):
    dateiname: str = Field(max_length=400)
    mime_typ: str = Field(default="application/octet-stream", max_length=120)
    #: Base64. Bilder im Text tragen zusätzlich eine ``cid``.
    inhalt_b64: str
    cid: str = Field(default="", max_length=120)


class Sendewunsch(BaseModel):
    konto_id: str
    an: list[str]
    kopie: list[str] = []
    blindkopie: list[str] = []
    betreff: str = Field(default="", max_length=1000)
    html: str = ""
    text: str = ""
    anlagen: list[Anlage] = []
    in_reply_to: str = ""
    references: list[str] = []
    #: Die UID der Entwurfsfassung, die diese hier ersetzt bzw. die nach dem
    #: Senden weggeräumt werden soll. 0 heißt: Es gibt noch keine.
    entwurf_uid: int = 0
    #: Frühestens ab wann gesendet wird, als ISO-Zeitpunkt in UTC vom Client.
    #: Leer heißt: sofort — dann verhält sich alles exakt wie bisher.
    senden_ab: datetime | None = None
    #: „Senden rückholen": Aufschub als **Dauer**, nicht als Zeitpunkt.
    #: ⚠️ Ein Zeitpunkt vom Client hinge an dessen Uhr — ging sie nach, war
    #: er beim Eintreffen schon vorbei, der Server sendete sofort, und das
    #: Rückholen war bei jedem Senden still wirkungslos. Die Dauer rechnet
    #: der Server auf seine eigene Uhr um. 0 heißt: kein Aufschub.
    rueckhol_sekunden: int = Field(default=0, ge=0, le=600)
    #: Vorgabe ``normal`` heißt: keine Wichtigkeits-Kopfzeilen. Nur ``hoch``
    #: und ``niedrig`` erzeugen ``Importance`` **und** ``X-Priority``.
    wichtigkeit: Literal["hoch", "normal", "niedrig"] = "normal"
    #: Unter welcher Adresse gesendet wird. Leer heißt: die Hauptadresse des
    #: Postfachs. ⚠️ **Der Wert wird geprüft, nicht übernommen** — siehe
    #: ``aliase.absender_pruefen``.
    von_adresse: str = Field(default="", max_length=320)


class Sendeergebnis(BaseModel):
    id: str
    stand: str
    fehler: str = ""
    #: Gesetzt, wenn die Nachricht geplant wurde statt sofort zu gehen.
    senden_ab: datetime | None = None


def _entwurf_bauen(konto: Konto, wunsch: Sendewunsch) -> verfassen.Entwurf:
    """Aus dem Wunsch der Oberfläche einen Entwurf machen.

    Gemeinsam für Senden und Aufbewahren: Beide bauen dieselbe Mail, nur das
    Ziel unterscheidet sich. Zwei Fassungen davon wären zwei Stellen, an denen
    eine Kopfzeile fehlen kann.
    """
    anlagen = []
    for eintrag in wunsch.anlagen:
        try:
            inhalt = base64.b64decode(eintrag.inhalt_b64, validate=True)
        except Exception as fehler:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="anhang_unlesbar"
            ) from fehler
        if len(inhalt) > MAX_ANHANG:
            raise MeldungHttp(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "anhang_zu_gross",
                {"name": eintrag.dateiname, "max_mb": MAX_ANHANG // (1024 * 1024)},
            )
        anlagen.append(
            verfassen.Anlage(
                dateiname=eintrag.dateiname,
                mime_typ=eintrag.mime_typ,
                inhalt=inhalt,
                cid=eintrag.cid,
            )
        )

    # ⚠️ **Die Absenderadresse wird geprüft, nicht übernommen.** Sie kommt aus
    # dem Browser; ohne diese Zeile könnte jeder Benutzer unter **jeder**
    # Adresse senden, denn der Mailserver sieht nur unsere Anmeldung. Ein Alias
    # ohne eigenen Namen behält den Absendernamen des Kontos.
    absender = aliasdienst.absender_pruefen(konto, wunsch.von_adresse)
    return verfassen.Entwurf(
        # ⚠️ Der Absendername, nicht der Name aus der Ordnerspalte.
        von_name=absender.name or kontendienst.absendername(konto),
        von_adresse=absender.adresse,
        an=wunsch.an,
        kopie=wunsch.kopie,
        blindkopie=wunsch.blindkopie,
        betreff=wunsch.betreff,
        html=wunsch.html,
        text=wunsch.text,
        anlagen=anlagen,
        in_reply_to=wunsch.in_reply_to,
        references=wunsch.references,
        wichtigkeit=wunsch.wichtigkeit,
    )


class SignaturAntwort(BaseModel):
    html: str


@router.get("/signatur/{konto_id}", response_model=SignaturAntwort)
def signatur_fuer(konto_id: str, person: AngemeldeterBenutzer, db: DbSession) -> SignaturAntwort:
    """Die Signatur, die eine neue Nachricht aus diesem Postfach bekommt.

    ⚠️ **Eigene Adresse, nicht Teil von ``/vorlage``.** Eine neue Nachricht hat
    keine Bezugsnachricht — sie käme dort nie an.
    """
    from ..services import signaturen as signaturdienst

    _mein_konto(db, person, konto_id)
    gefunden = signaturdienst.fuer_konto(db, person, konto_id)
    return SignaturAntwort(html=gefunden.html if gefunden else "")


@router.post("/senden", response_model=Sendeergebnis)
def senden_(wunsch: Sendewunsch, person: AngemeldeterBenutzer, db: DbSession) -> Sendeergebnis:
    """Eine Nachricht hinausschicken.

    ⚠️ **Erst in die Warteschlange, dann senden.** Scheitert der Versand, ist
    die Mail nicht weg — sie liegt im Ausgang und wird noch einmal versucht.
    """
    konto = _mein_konto(db, person, wunsch.konto_id)

    if not [a for a in wunsch.an + wunsch.kopie + wunsch.blindkopie if a.strip()]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="empfaenger_fehlt"
        )

    # ⚠️ **Die Absenderprüfung steckt in ``_entwurf_bauen``** und wirft eine
    # Kennung. Ungefangen wäre sie ein 500 mit Rückverfolg — dabei ist sie
    # eine gewöhnliche Absage an eine Anfrage, und die Oberfläche kann sie
    # übersetzen.
    try:
        entwurf = _entwurf_bauen(konto, wunsch)
    except aliasdienst.AliasFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler

    # ⚠️ Naiv hieße hier UTC: Der Client schickt ISO mit Zone; wer keine
    # mitschickt, hat sie beim Umrechnen schon angewandt.
    geplant_ab = wunsch.senden_ab
    if geplant_ab is not None:
        geplant_ab = (
            geplant_ab.replace(tzinfo=timezone.utc)
            if geplant_ab.tzinfo is None
            else geplant_ab.astimezone(timezone.utc)
        )

    # „Senden rückholen": Die Dauer wird an der **Server**-Uhr in einen
    # Zeitpunkt übersetzt — so liegt er immer in der Zukunft, egal wie die
    # Client-Uhr geht. Ein zusätzlich mitgeschickter ``senden_ab`` („Später
    # senden") behält Vorrang; beide zugleich schickt die Oberfläche nicht.
    if wunsch.rueckhol_sekunden > 0 and geplant_ab is None:
        geplant_ab = datetime.now(timezone.utc) + timedelta(
            seconds=wunsch.rueckhol_sekunden
        )

    if geplant_ab is not None and geplant_ab > datetime.now(timezone.utc):
        # Geplant: nur einreihen. Hinaus geht die Nachricht, wenn der
        # Versandplan sie für fällig befindet.
        zeile = senden.einreihen(db, konto, entwurf, senden_ab=geplant_ab)
        # ⚠️ Der Entwurf wird schon jetzt weggeräumt, nicht erst beim Versand:
        # Der Inhalt liegt vollständig im Ausgang, und ein Abbruch legt ihn
        # von dort wieder als Entwurf ab. Bliebe die alte Fassung liegen,
        # stünde die Nachricht doppelt da — einmal geplant, einmal als
        # Entwurf, den niemand mehr pflegt.
        if wunsch.entwurf_uid:
            try:
                entwurfsdienst.wegwerfen(db, konto, wunsch.entwurf_uid)
            except Exception as fehler:  # noqa: BLE001
                logger.warning("The draft could not be removed after scheduling: %s", fehler)
        return Sendeergebnis(id=zeile.id, stand=zeile.stand, senden_ab=zeile.senden_ab)

    zeile = senden.einreihen(db, konto, entwurf)
    try:
        senden.versenden(db, zeile)
    except senden.SendeFehler as fehler:
        # Kein 500: Die Mail ist nicht verloren, sie liegt im Ausgang.
        return Sendeergebnis(id=zeile.id, stand=zeile.stand, fehler=str(fehler))

    # ⚠️ Der Entwurf muss weg, **nachdem** die Mail draußen ist. Sonst steht
    # sie zweimal im Postfach - einmal gesendet, einmal als Entwurf, den
    # niemand mehr braucht. Ein Fehler dabei darf den Versand nicht umwerfen:
    # Die Mail ist unterwegs, daran ändert eine gebliebene Fassung nichts.
    if wunsch.entwurf_uid:
        try:
            entwurfsdienst.wegwerfen(db, konto, wunsch.entwurf_uid)
        except Exception as fehler:  # noqa: BLE001
            logger.warning("The draft could not be removed after sending: %s", fehler)

    return Sendeergebnis(id=zeile.id, stand=zeile.stand)


class Entwurfsergebnis(BaseModel):
    #: Die UID der abgelegten Fassung. Beim nächsten Speichern wieder mitgeben,
    #: sonst sammeln sich Fassungen im Entwurfsordner.
    uid: int


@router.post("/entwurf", response_model=Entwurfsergebnis)
def entwurf_ablegen(
    wunsch: Sendewunsch, person: AngemeldeterBenutzer, db: DbSession
) -> Entwurfsergebnis:
    """Eine angefangene Nachricht im Postfach aufbewahren.

    ⚠️ **Nicht im Browser, sondern beim Anbieter.** Ein Entwurf, der nur lokal
    liegt, ist auf dem Telefon nicht zu sehen und nach einem geschlossenen
    Fenster weg. Deshalb geht er denselben Weg wie eine gesendete Mail.

    Ein Entwurf hat **keine Empfängerpflicht** — genau das unterscheidet ihn
    von einer Mail: Man fängt oft mit dem Text an und weiß den Empfänger noch
    nicht.
    """
    konto = _mein_konto(db, person, wunsch.konto_id)
    # ⚠️ Auch hier — ein Entwurf mit fremder Absenderadresse wäre eine Mail
    # mit fremder Absenderadresse, sobald ihn jemand abschickt.
    try:
        entwurf = _entwurf_bauen(konto, wunsch)
    except aliasdienst.AliasFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_400_BAD_REQUEST) from fehler
    try:
        uid = entwurfsdienst.ablegen(db, konto, entwurf, wunsch.entwurf_uid or None)
    except entwurfsdienst.EntwurfFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_409_CONFLICT) from fehler
    return Entwurfsergebnis(uid=uid)


@router.delete("/entwurf/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def entwurf_wegwerfen(
    uid: int, konto_id: str, person: AngemeldeterBenutzer, db: DbSession
) -> None:
    """Einen Entwurf endgültig wegwerfen.

    ⚠️ **Das ist der Unterschied zwischen Kreuz und „Verwerfen".** Das Kreuz
    schließt das Fenster und bewahrt den Text auf; „Verwerfen" wirft ihn weg.
    Zwei Ausgänge, die Verschiedenes tun - keine zwei Wege nach draußen.
    """
    konto = _mein_konto(db, person, konto_id)
    try:
        entwurfsdienst.wegwerfen(db, konto, uid)
    except entwurfsdienst.EntwurfFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_409_CONFLICT) from fehler


def _mein_konto(db, person, konto_id: str) -> Konto:
    try:
        return kontendienst.eines(db, person, konto_id)
    except kontendienst.KontoFehler as fehler:
        raise MeldungHttp.aus(fehler, status.HTTP_404_NOT_FOUND) from fehler


class Ausgangszeile(BaseModel):
    id: str
    stand: str
    betreff: str
    versuche: int
    letzter_fehler: str
    angelegt: datetime
    #: Gesetzt bei geplantem Versand — die Oberfläche zeigt den Zeitpunkt.
    senden_ab: datetime | None = None


@router.get("/ausgang", response_model=list[Ausgangszeile])
def ausgang(person: AngemeldeterBenutzer, db: DbSession) -> list[Ausgangszeile]:
    """Was noch nicht draußen ist — geplant oder liegen geblieben, und warum."""
    zeilen = (
        db.execute(
            select(Ausgang)
            .where(Ausgang.benutzer_id == person.id, Ausgang.stand != "gesendet")
            .order_by(Ausgang.angelegt.desc())
        )
        .scalars()
        .all()
    )
    return [
        Ausgangszeile(
            id=z.id,
            stand=z.stand,
            betreff=z.betreff,
            versuche=z.versuche,
            letzter_fehler=z.letzter_fehler,
            angelegt=z.angelegt,
            senden_ab=z.senden_ab,
        )
        for z in zeilen
    ]


class Abbruchergebnis(BaseModel):
    #: Die UID des Entwurfs, den der Abbruch als Sicherheitsnetz abgelegt hat.
    #: Die Oberfläche hängt das wieder geöffnete Fenster daran — sonst bliebe
    #: nach jedem „Rückgängig" eine Fassung liegen, die niemand mehr wegräumt.
    entwurf_uid: int
    #: Das Postfach dazu — die UID allein reicht zum Aufräumen nicht.
    konto_id: str


@router.post("/ausgang/{ausgang_id}/abbrechen", response_model=Abbruchergebnis)
def ausgang_abbrechen(
    ausgang_id: str, person: AngemeldeterBenutzer, db: DbSession
) -> Abbruchergebnis:
    """Einen geplanten oder liegen gebliebenen Versand zurücknehmen.

    Der Inhalt geht als Entwurf in den Entwurfsordner des Postfachs — nichts
    geht verloren. Was schon unterwegs oder draußen ist, lässt sich nicht
    mehr zurückholen; das sagt die Antwort statt so zu tun.
    """
    zeile = db.get(Ausgang, ausgang_id)
    if zeile is None or zeile.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if zeile.stand not in ("wartet", "gescheitert"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="schon_unterwegs",
        )
    # ⚠️ Vor dem Abbruch merken: Danach ist die Zeile gelöscht, und ein
    # Zugriff auf das verwaiste ORM-Objekt würfe erst hier den Fehler.
    konto_id = zeile.konto_id
    try:
        uid = senden.abbrechen(db, zeile)
    except senden.AbbruchKollision as fehler:
        # ⚠️ Der Stand hier oben ist nur eine Momentaufnahme: Der Versandfaden
        # läuft mit eigener Session und kann die Zeile zwischen Lesen und
        # Abbruch beanspruchen. Das bedingte UPDATE in ``abbrechen``
        # entscheidet — und dessen „nein" heißt: Die Mail geht hinaus, und
        # genau das muss die Antwort sagen statt „zurückgeholt".
        raise MeldungHttp.aus(fehler, status.HTTP_409_CONFLICT) from fehler
    except entwurfsdienst.EntwurfFehler as fehler:
        # ⚠️ Ohne Entwurfsordner bleibt der Eintrag liegen. Ihn trotzdem zu
        # entfernen hieße, die Nachricht stillschweigend wegzuwerfen.
        raise MeldungHttp.aus(fehler, status.HTTP_409_CONFLICT) from fehler
    return Abbruchergebnis(entwurf_uid=uid, konto_id=konto_id)


class Nachlauf(BaseModel):
    versucht: int
    gesendet: int
    liegen: int


@router.post("/ausgang/nachschieben", response_model=Nachlauf)
def nachschieben(person: AngemeldeterBenutzer, db: DbSession) -> Nachlauf:
    """Die Warteschlange noch einmal durchgehen."""
    # Nur die eigenen: Die Funktion im Dienst geht über alle, deshalb hier
    # zuerst einschränken.
    eigene = (
        db.execute(
            select(Ausgang).where(
                Ausgang.benutzer_id == person.id,
                Ausgang.stand.in_(["wartet", "unterwegs"]),
                # ⚠️ Auch hier: Geplantes ist nicht „liegen geblieben".
                senden.faellig_bedingung(),
            )
        )
        .scalars()
        .all()
    )
    ergebnis = {"versucht": 0, "gesendet": 0, "liegen": 0}
    for zeile in eigene:
        ergebnis["versucht"] += 1
        try:
            senden.versenden(db, zeile)
            ergebnis["gesendet"] += 1
        except senden.SendeFehler:
            ergebnis["liegen"] += 1
    return Nachlauf(**ergebnis)
