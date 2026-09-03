"""Post hinein und hinaus — mbox und ``.eml``.

⚠️ **Der Import ist ein Vorgang, kein Knopfdruck.** Ein Thunderbird-Ordner mit
zehntausend Mails braucht über IMAP seine Zeit; eine Anfrage, die so lange
offen steht, läuft in jeden Proxy-Zeitablauf und lässt den Betreiber im
Ungewissen, ob noch etwas passiert. Deshalb: hochladen, Vorgang anwerfen,
Fortschritt abfragen.

⚠️ **Der Export ist dagegen ein Strom.** Er hält nie mehr als einen Block
Nachrichten im Speicher — außer beim ZIP, und das ist der Grund für seine
Mengengrenze.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from ..config import get_settings
from ..deps import AngemeldeterBenutzer, DbSession
from ..models import Konto, Nachricht, Ordner
from ..services import austausch as dienst

logger = logging.getLogger("nexmail.austausch")

router = APIRouter(prefix="/api/austausch", tags=["austausch"])

#: Wie groß eine hochgeladene mbox höchstens sein darf. Ein Postfach von
#: zwanzig Jahren passt hinein; alles darüber ist eher ein Versehen als ein
#: Umzug. ⚠️ Die Datei geht **auf die Platte**, nicht in den Speicher — die
#: eigentliche Grenze ist der freie Platz im Datenverzeichnis, und die Meldung
#: sagt es.
MAX_BYTES = 4 * 1024 * 1024 * 1024

#: Blockgröße beim Entgegennehmen des Uploads.
UPLOAD_BLOCK = 1 << 20

#: Wie viele Nachrichten ein ZIP höchstens fasst. ⚠️ **Ein ZIP entsteht
#: vollständig im Speicher** — sein Verzeichnis steht am Ende, es lässt sich
#: also nicht sinnvoll strömen. Wer mehr exportieren will, nimmt mbox, und die
#: Oberfläche sagt das an der Stelle, an der man wählt.
MAX_ZIP = 2_000


class Vorgangsstand(BaseModel):
    id: str
    dateiname: str
    laeuft: bool
    #: Leer heißt: lief durch. Sonst der Satz, an dem er gescheitert ist.
    fehler: str
    gelesen: int
    importiert: int
    uebersprungen: int
    ohne_kennung: int
    fehler_je_mail: list[str]
    fehler_gesamt: int
    abgeschnitten: bool
    abgebrochen: bool


def _stand(vorgang: dienst.Vorgang) -> Vorgangsstand:
    b = vorgang.bericht
    return Vorgangsstand(
        id=vorgang.id,
        dateiname=vorgang.dateiname,
        laeuft=vorgang.laeuft,
        fehler=vorgang.fehler,
        gelesen=b.gelesen,
        importiert=b.importiert,
        uebersprungen=b.uebersprungen,
        ohne_kennung=b.ohne_kennung,
        fehler_je_mail=list(b.fehler),
        fehler_gesamt=b.fehler_gesamt,
        abgeschnitten=b.abgeschnitten,
        abgebrochen=b.abgebrochen,
    )


def _mein_ordner(db, person, ordner_id: int) -> tuple[Ordner, Konto]:
    """Der Ordner und sein Postfach — oder 404, auch bei fremdem Besitz."""
    ordner = db.get(Ordner, ordner_id)
    konto = db.get(Konto, ordner.konto_id) if ordner else None
    if ordner is None or konto is None or konto.benutzer_id != person.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not ordner.waehlbar:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dieser Ordner kann keine Nachrichten aufnehmen.",
        )
    return ordner, konto


# --------------------------------------------------------------------------- #
# Hinein
# --------------------------------------------------------------------------- #


@router.post("/import", response_model=Vorgangsstand)
async def einspielen(
    person: AngemeldeterBenutzer,
    db: DbSession,
    datei: UploadFile = File(...),
    ordner_id: int = Form(...),
) -> Vorgangsstand:
    """Eine mbox-Datei in einen Ordner einspielen.

    ⚠️ **Erst auf die Platte, dann anfangen.** Ein ``UploadFile`` ist mit dem
    Ende der Anfrage geschlossen; der Faden, der danach eine Stunde lang
    anhängt, läse ins Leere. Der Vorgang übernimmt die Datei und räumt sie weg.
    """
    ordner, konto = _mein_ordner(db, person, ordner_id)

    laeuft = dienst.laeuft_schon(person.id)
    if laeuft is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Es läuft schon ein Import ({laeuft.dateiname}). Bitte abwarten.",
        )

    ziel = get_settings().data_dir / "einfuhr"
    ziel.mkdir(parents=True, exist_ok=True)
    pfad = ziel / f"{secrets.token_urlsafe(12)}.mbox"

    groesse = 0
    try:
        with pfad.open("wb") as raus:
            while block := await datei.read(UPLOAD_BLOCK):
                groesse += len(block)
                if groesse > MAX_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            "Die Datei ist größer als 4 GB. Thunderbird legt je Ordner "
                            "eine eigene mbox an — bitte einzeln einspielen."
                        ),
                    )
                raus.write(block)
    except BaseException:
        pfad.unlink(missing_ok=True)
        raise

    if groesse == 0:
        pfad.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Die Datei ist leer."
        )

    vorgang = dienst.vorgang_starten(
        person.id, konto.id, ordner.id, datei.filename or "mbox", pfad
    )
    logger.info("Import %s started into %s (%s bytes).", vorgang.id, ordner.pfad, groesse)
    return _stand(vorgang)


@router.get("/vorgang", response_model=Vorgangsstand | None)
def laufender(person: AngemeldeterBenutzer) -> Vorgangsstand | None:
    """Der gerade laufende Import, falls es einen gibt.

    ⚠️ **Damit ein Neuladen der Seite den Vorgang nicht verliert.** Ohne das
    steht der Betreiber nach einem F5 vor einem Postfach, in dem sich etwas
    tut, und hat keine Anzeige mehr dazu.
    """
    gefunden = dienst.laeuft_schon(person.id)
    return _stand(gefunden) if gefunden else None


@router.get("/vorgang/{kennung}", response_model=Vorgangsstand)
def vorgang(kennung: str, person: AngemeldeterBenutzer) -> Vorgangsstand:
    gefunden = dienst.stand(kennung, person.id)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _stand(gefunden)


@router.post("/vorgang/{kennung}/abbrechen", response_model=Vorgangsstand)
def abbrechen(kennung: str, person: AngemeldeterBenutzer) -> Vorgangsstand:
    """Anhalten. ⚠️ Was schon angehängt wurde, bleibt — rückgängig gibt es nicht.

    Ein zweiter Anlauf mit derselben Datei überspringt es und macht weiter.
    """
    gefunden = dienst.stand(kennung, person.id)
    if gefunden is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    dienst.abbrechen(kennung, person.id)
    return _stand(gefunden)


# --------------------------------------------------------------------------- #
# Hinaus
# --------------------------------------------------------------------------- #


def _zeilen(db, ordner: Ordner) -> list[tuple[int, str]]:
    return list(
        db.execute(
            select(Nachricht.uid, Nachricht.betreff)
            .where(Nachricht.ordner_id == ordner.id)
            .order_by(Nachricht.datum)
        ).all()
    )


def _dateiname(ordner: Ordner, endung: str) -> str:
    return f"{dienst.sicherer_stamm(ordner.name, 'Ordner')}.{endung}"


class Vorschau(BaseModel):
    #: Wie viele Nachrichten nexmail von diesem Ordner kennt.
    bekannt: int
    #: Wie viele beim Anbieter liegen. Weicht ab, solange nicht abgeglichen ist.
    gesamt: int
    zip_grenze: int


@router.get("/vorschau/{ordner_id}", response_model=Vorschau)
def vorschau(ordner_id: int, person: AngemeldeterBenutzer, db: DbSession) -> Vorschau:
    """Was ein Export dieses Ordners umfassen würde.

    ⚠️ **Der Unterschied zwischen ``bekannt`` und ``gesamt`` ist der Punkt.**
    Exportiert wird, was nexmail kennt; ein nie abgeglichener Ordner gäbe eine
    fast leere Datei, und das sähe aus wie Datenverlust. Die Oberfläche nennt
    beide Zahlen, **bevor** heruntergeladen wird.
    """
    ordner, _ = _mein_ordner(db, person, ordner_id)
    bekannt = db.scalar(
        select(func.count()).select_from(Nachricht).where(Nachricht.ordner_id == ordner.id)
    )
    return Vorschau(bekannt=bekannt or 0, gesamt=ordner.anzahl, zip_grenze=MAX_ZIP)


@router.get("/export/{ordner_id}")
def ausgeben(
    ordner_id: int, person: AngemeldeterBenutzer, db: DbSession, form: str = "mbox"
):
    """Einen Ordner herunterladen — als mbox oder als ZIP einzelner ``.eml``.

    ⚠️ **Exportiert wird, was nexmail kennt.** Ein Ordner, der nie abgeglichen
    wurde, ist hier leer, auch wenn beim Anbieter Post liegt. Die Oberfläche
    nennt die Zahl vorher, damit das nicht als Datenverlust erscheint.
    """
    if form not in ("mbox", "zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekanntes Format."
        )

    ordner, konto = _mein_ordner(db, person, ordner_id)
    zeilen = _zeilen(db, ordner)
    if not zeilen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="In diesem Ordner ist nichts, was sich ausgeben ließe.",
        )

    uids = [uid for uid, _ in zeilen]
    betreffe = dict(zeilen)

    if form == "zip":
        if len(uids) > MAX_ZIP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Der Ordner hat {len(uids)} Nachrichten; als ZIP gehen höchstens "
                    f"{MAX_ZIP}. Bitte mbox nehmen — das strömt und hat keine Grenze."
                ),
            )
        # ⚠️ Ohne ``status_einsetzen``: Eine ``.eml`` ist die Mail, wie sie
        # ankam. Eine Kopfzeile, die nexmails Ansicht beschreibt, gehoert
        # nicht hinein — anders als in die mbox, die ein Postfach ist.
        daten = dienst.als_zip(
            (betreffe.get(uid, ""), roh)
            for uid, roh, _ in dienst.roh_stroemen(db, konto, ordner.pfad, uids)
        )
        return StreamingResponse(
            iter([daten]),
            media_type="application/zip",
            headers={
                "content-disposition": f'attachment; filename="{_dateiname(ordner, "zip")}"'
            },
        )

    def strom() -> Iterator[bytes]:
        # ⚠️ **Gelesen und markiert muessen mit in die Datei.** Am 02.09.2026
        # gegen ein echtes Postfach gemessen: hinaus und wieder herein, und
        # alles war ungelesen. Die Leseseite konnte die Kopfzeile laengst —
        # nur schrieb sie niemand.
        yield from dienst.als_mbox(
            dienst.status_einsetzen(roh, flags)
            for _, roh, flags in dienst.roh_stroemen(db, konto, ordner.pfad, uids)
        )

    return StreamingResponse(
        strom(),
        media_type="application/mbox",
        headers={
            "content-disposition": f'attachment; filename="{_dateiname(ordner, "mbox")}"'
        },
    )
