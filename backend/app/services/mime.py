"""Eine Mail auseinandernehmen.

Was hier hereinkommt, ist dreißig Jahre gewachsener Wildwuchs: Kopfzeilen in
sechs Kodierungen, Zeichensätze, die gelogen sind, verschachtelte Teile,
Anhänge ohne Namen. Die Regel für alles hier lautet deshalb: **niemals
abstürzen, immer etwas zurückgeben.** Eine Mail, die nexmail nicht anzeigen
kann, ist schlimmer als eine, die schief aussieht.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import logging
import re
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from datetime import datetime, timezone

from charset_normalizer import from_bytes

logger = logging.getLogger("nexmail.mime")

#: Kodierungen, die jede Bytefolge annehmen und deshalb nie einen Fehler
#: werfen - siehe die Begruendung in ``text_entziffern``.
NIE_FEHLSCHLAGEND = {
    "iso-8859-1", "iso8859-1", "latin-1", "latin1", "latin_1", "l1",
    "windows-1252", "cp1252", "iso-8859-15", "iso8859-15",
    "ascii", "us-ascii",
}

#: Wie viel Text je Nachricht für die Suche aufgehoben wird. Eine einzelne
#: Mail mit einem angehängten Roman soll den Index nicht sprengen.
TEXT_GRENZE = 64 * 1024


@dataclass
class Person:
    name: str
    adresse: str


@dataclass
class Anhangteil:
    teil_id: str
    dateiname: str
    mime: str
    groesse: int
    #: Bei Inline-Bildern der Wert aus ``Content-ID``, ohne spitze Klammern.
    cid: str = ""
    inhalt: bytes = b""

    @property
    def inline(self) -> bool:
        return bool(self.cid)

    def hash(self) -> str:
        return hashlib.sha256(self.inhalt).hexdigest()


@dataclass
class Zerlegt:
    betreff: str
    von: Person
    an: list[Person]
    kopie: list[Person]
    datum: datetime
    message_id: str
    in_reply_to: str
    references: list[str]
    text: str
    html: str
    anhaenge: list[Anhangteil] = field(default_factory=list)


def kopf_lesen(wert: str | None) -> str:
    """Eine Kopfzeile lesbar machen — egal in welcher Kodierung sie steckt.

    ⚠️ Fällt das hier um, ist die ganze Mail nicht anzeigbar. Deshalb wird
    jeder Fehler geschluckt und der Rohwert genommen: Ein schief aussehender
    Betreff ist besser als eine Nachricht, die es nicht in die Liste schafft.
    """
    if not wert:
        return ""
    try:
        return str(make_header(decode_header(wert))).strip()
    except Exception:  # noqa: BLE001
        return wert.strip()


def _personen(nachricht: Message, feld: str) -> list[Person]:
    roh = nachricht.get_all(feld, [])
    ergebnis = []
    for name, adresse in getaddresses([str(w) for w in roh]):
        if not adresse:
            continue
        ergebnis.append(Person(name=kopf_lesen(name), adresse=adresse.strip().lower()))
    return ergebnis


def text_entziffern(roh: bytes, angegeben: str | None) -> str:
    """Bytes zu Text — und dem angegebenen Zeichensatz nicht blind glauben.

    ⚠️ **Der angegebene Zeichensatz ist oft falsch.** „iso-8859-1" steht in
    unzähligen Mails, die in Wahrheit UTF-8 sind; das Ergebnis sind dann
    Buchstaben wie „Ã¼". Deshalb: erst der angegebene Wert, und wenn er nicht
    aufgeht, raten lassen - und ganz zum Schluss stur mit Ersatzzeichen.
    """
    if not roh:
        return ""

    if angegeben:
        name = angegeben.strip().lower()

        # ⚠️ **Diese Kodierungen lehnen nichts ab.** latin-1 und Verwandte
        # bilden jedes Byte auf irgendein Zeichen ab - ein Versuch mit
        # ``strict`` gelingt deshalb *immer* und liefert bei einer in
        # Wahrheit UTF-8 kodierten Mail „GrÃ¼ÃŸe" statt „Grüße". Der
        # Fehlerfall, den man abfangen wollte, tritt nie ein.
        #
        # Deshalb bei genau diesen Angaben zuerst UTF-8 versuchen: Geht das
        # auf, war die Angabe gelogen - und das ist sie in unzähligen Mails.
        if name in NIE_FEHLSCHLAGEND:
            try:
                return roh.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                pass

        try:
            return roh.decode(name, errors="strict")
        except (LookupError, UnicodeDecodeError):
            pass

    try:
        geraten = from_bytes(roh).best()
        if geraten is not None:
            return str(geraten)
    except Exception:  # noqa: BLE001
        pass

    return roh.decode("utf-8", errors="replace")


def _datum(nachricht: Message) -> datetime:
    roh = nachricht.get("Date")
    if roh:
        try:
            wert = parsedate_to_datetime(roh)
            if wert.tzinfo is None:
                wert = wert.replace(tzinfo=timezone.utc)
            return wert.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    # Kein oder kaputtes Datum. Nicht abstürzen - die Mail bekommt „jetzt"
    # und rutscht damit an den Anfang der Liste, wo sie auffällt.
    return datetime.now(timezone.utc)


def _dateiname(teil: Message, nummer: str) -> str:
    name = teil.get_filename()
    if name:
        return kopf_lesen(name)
    endung = {"text/plain": ".txt", "text/html": ".html"}.get(teil.get_content_type(), "")
    unterart = teil.get_content_subtype() or "dat"
    return f"Anhang-{nummer}{endung or '.' + unterart}"


def zerlegen(roh: bytes) -> Zerlegt:
    """Eine ganze Mail zerlegen."""
    nachricht = email.message_from_bytes(roh, policy=email.policy.compat32)

    text_teile: list[str] = []
    html_teile: list[str] = []
    anhaenge: list[Anhangteil] = []

    def durchgehen(teil: Message, nummer: str) -> None:
        if teil.is_multipart():
            for i, unter in enumerate(teil.get_payload(), start=1):
                durchgehen(unter, f"{nummer}.{i}" if nummer else str(i))
            return

        typ = (teil.get_content_type() or "").lower()
        verfuegung = (teil.get("Content-Disposition") or "").lower()
        cid = (teil.get("Content-ID") or "").strip().strip("<>")

        try:
            inhalt = teil.get_payload(decode=True) or b""
        except Exception:  # noqa: BLE001 - kaputte Kodierung ist kein Absturzgrund
            inhalt = b""

        ist_anhang = "attachment" in verfuegung or bool(teil.get_filename()) or bool(cid)

        if not ist_anhang and typ == "text/plain":
            text_teile.append(text_entziffern(inhalt, teil.get_content_charset()))
            return
        if not ist_anhang and typ == "text/html":
            html_teile.append(text_entziffern(inhalt, teil.get_content_charset()))
            return

        anhaenge.append(
            Anhangteil(
                teil_id=nummer or "1",
                dateiname=_dateiname(teil, nummer or "1"),
                mime=typ or "application/octet-stream",
                groesse=len(inhalt),
                cid=cid,
                inhalt=inhalt,
            )
        )

    durchgehen(nachricht, "")

    referenzen = re.findall(r"<[^>]+>", nachricht.get("References", "") or "")

    return Zerlegt(
        betreff=kopf_lesen(nachricht.get("Subject")),
        von=(_personen(nachricht, "From") or [Person("", "")])[0],
        an=_personen(nachricht, "To"),
        kopie=_personen(nachricht, "Cc"),
        datum=_datum(nachricht),
        message_id=(nachricht.get("Message-ID") or "").strip(),
        in_reply_to=(nachricht.get("In-Reply-To") or "").strip(),
        references=[r.strip() for r in referenzen],
        text="\n".join(text_teile)[:TEXT_GRENZE],
        html="\n".join(html_teile),
        anhaenge=anhaenge,
    )


# --- Stränge ------------------------------------------------------------- #

#: Was am Anfang eines Betreffs weggeschnitten wird, um zwei Nachrichten
#: demselben Strang zuzuordnen.
#:
#: ⚠️ **Deutsch gehört dazu.** „AW:" und „WG:" sind hierzulande der Normalfall,
#: und wer nur „Re:" und „Fwd:" abschneidet, macht aus einem Hin und Her drei
#: verschiedene Stränge.
_PRAEFIX = re.compile(
    r"^\s*(?:(?:re|aw|antw|fw|fwd|wg|sv|vs|rif|odp|res|enc)\s*(?:\[\d+\])?\s*:\s*)+",
    re.IGNORECASE,
)


def betreff_kern(betreff: str) -> str:
    return _PRAEFIX.sub("", betreff or "").strip()


def strang_kennung(zerlegt: Zerlegt) -> str:
    """Woran zwei Nachrichten als zusammengehörig erkannt werden.

    ⚠️ **Wird ab Stufe 2 mitgeschrieben, obwohl v1 flach anzeigt.** Falsch
    gruppiert *versteckt* eine Nachricht in einem zugeklappten Strang; das will
    an echten Mails erprobt sein, bevor es die Standardansicht wird. Wenn die
    Spalte aber erst später entsteht, entsteht mit ihr eine Wanderung über
    Hunderttausende Zeilen.

    Die Wurzel der ``References``-Kette schlägt den Betreff: Sie ist eindeutig,
    der Betreff nur wahrscheinlich.
    """
    if zerlegt.references:
        return zerlegt.references[0]
    if zerlegt.in_reply_to:
        return zerlegt.in_reply_to
    kern = betreff_kern(zerlegt.betreff)
    if kern:
        return "betreff:" + hashlib.sha256(kern.lower().encode("utf-8")).hexdigest()[:32]
    return zerlegt.message_id or ""
