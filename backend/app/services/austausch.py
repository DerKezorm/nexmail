"""Post hinein und hinaus — mbox und einzelne ``.eml``.

Der Umzug von Thunderbird, und der Weg zurück. Beides fasst denselben Bestand
an, aber die Gefahren liegen an verschiedenen Enden:

* **Beim Import** ist es die Wiederholung. Ein Import bricht ab — Netz weg,
  Server müde, Browser geschlossen — und wer ihn dann noch einmal startet, hat
  ohne Vorkehrung alles doppelt. Deshalb wird übersprungen, was im Zielordner
  schon liegt, erkannt an der ``Message-ID``. **Ein abgebrochener Import ist
  damit einfach zu wiederholen**, und genau darauf ist die Mengengrenze
  ausgelegt: Sie zählt, was wirklich angehängt wurde.
* **Beim Export** ist es die Größe. Ein Thunderbird-Postfach hat Gigabyte, und
  wer es am Stück in den Speicher legt, bringt den Container um. Es wird
  deshalb gestroemt, Nachricht für Nachricht.

⚠️ **Die vorhandenen Kennungen werden EINMAL geholt, nicht je Mail gesucht.**
Ein ``SEARCH`` je Nachricht wäre bei zwanzigtausend Mails zwanzigtausend
Runden über das Netz — bei 50 ms Laufzeit ein Vormittag, in dem nichts
passiert. Ein Blockabruf über die Kopfzeile kostet eine Runde je 2000 Mails
und ein paar Megabyte Speicher.

⚠️ **mbox ist ein Format ohne Norm.** Es gibt vier Varianten, und sie
unterscheiden sich genau dort, wo es weh tut: wie eine Zeile maskiert wird, die
im Text mit ``From `` beginnt. Was hier gelesen und geschrieben wird, ist
**mboxrd** — die einzige Variante, die verlustfrei ist. Die Einzelheiten stehen
bei ``_entmaskieren``.
"""

from __future__ import annotations

import io
import logging
import re
import secrets
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Konto, Ordner
from . import abgleich, imap as imapdienst, konten as kontendienst

logger = logging.getLogger("nexmail.austausch")

#: Eine maskierte ``From``-Zeile in mboxrd: beliebig viele ``>``, dann ``From ``.
_MASKIERT = re.compile(rb"^(>+)From ", re.MULTILINE)

#: Wie viele Nachrichten hoechstens in einem Zug **angehaengt** werden.
#: ⚠️ **Gezaehlt wird das Anhaengen, nicht das Lesen.** Das Lesen der Datei
#: kostet nichts; jedes ``APPEND`` ist eine Runde ueber das Netz. Wer stattdessen
#: das Gelesene zaehlte, koennte einen abgebrochenen Import nie fortsetzen: Der
#: zweite Anlauf verbrauchte seine Grenze mit dem Ueberspringen dessen, was
#: schon da ist, und kaeme nie zum Rest.
MAX_NACHRICHTEN = 20_000

#: Wie viele Kopfzeilen auf einmal geholt werden. Eine Speichergrenze, kein
#: Geschwindigkeitsregler.
BLOCK_KOEPFE = 2_000

#: Wie viele **ganze** Nachrichten auf einmal geholt werden. Absichtlich klein:
#: Ein Block liegt vollstaendig im Speicher, und 2000 Mails koennen ein
#: Gigabyte sein.
BLOCK_MAILS = 50

#: Nach so vielen Fehlschlaegen hintereinander wird abgebrochen. ⚠️ Ohne das
#: laeuft eine gekappte Verbindung durch zwanzigtausend Nachrichten und meldet
#: am Ende zwanzigtausend Fehler statt „die Verbindung ist weg".
FEHLER_HINTEREINANDER = 10

#: So viele Fehlermeldungen stehen im Bericht. Der Rest wird gezaehlt.
MAX_FEHLER_IM_BERICHT = 20


@dataclass
class Bericht:
    """Was ein Import getan hat — und was nicht.

    ⚠️ **Die Zahlen wachsen waehrend des Laufs.** Der Fortschrittsbalken liest
    dieselbe Instanz aus einem anderen Faden; deshalb stehen hier nur einfache
    Werte, die man ohne Schloss lesen kann.
    """

    gelesen: int = 0
    importiert: int = 0
    #: Schon im Zielordner, an der ``Message-ID`` erkannt.
    uebersprungen: int = 0
    #: Nachrichten ohne ``Message-ID``. Bei ihnen kann nexmail nicht sagen, ob
    #: sie schon da sind — sie werden angehaengt, und das steht im Bericht.
    ohne_kennung: int = 0
    fehler: list[str] = field(default_factory=list)
    #: Wie viele Nachrichten wirklich scheiterten — ``fehler`` ist gedeckelt.
    fehler_gesamt: int = 0
    #: Wahr, wenn ``MAX_NACHRICHTEN`` gegriffen hat. Ein zweiter Lauf mit
    #: derselben Datei macht dort weiter.
    abgeschnitten: bool = False
    #: Wahr, wenn jemand abgebrochen hat. Was bis dahin drin ist, bleibt drin.
    abgebrochen: bool = False


class AustauschFehler(RuntimeError):
    pass


def _entmaskieren(roh: bytes) -> bytes:
    """Die ``>From``-Maskierung von mboxrd aufheben.

    ⚠️ **Das ist die Stelle, an der die vier mbox-Varianten auseinandergehen.**
    Eine Zeile im Nachrichtentext, die mit ``From `` beginnt, muesste sonst als
    Trennzeile gelesen werden. mboxrd setzt ein ``>`` davor — und weil der Text
    selbst schon ``>From `` enthalten kann, wird auch das maskiert. Beim Lesen
    faellt genau ein ``>`` weg, nie mehr; wer alle entfernt, macht aus einem
    zitierten ``>From `` ein ``From `` und verfaelscht die Mail.
    """
    return _MASKIERT.sub(lambda t: b">" * (len(t.group(1)) - 1) + b"From ", roh)


def _maskieren(roh: bytes) -> bytes:
    """Die Umkehrung — beim Schreiben einer mbox."""
    return re.sub(rb"^(>*)From ", lambda t: b">" + t.group(1) + b"From ", roh, flags=re.MULTILINE)


def mbox_lesen(strom: io.BufferedReader) -> Iterator[bytes]:
    """Eine mbox in einzelne Nachrichten zerlegen — stroemend.

    ⚠️ **Nicht ``mailbox.mbox`` aus der Standardbibliothek.** Die will einen
    Dateinamen, legt einen Index an und haelt die Datei fuer sich; hier kommt
    der Inhalt aber als Upload. Und sie kennt nur mboxo, verliert also genau
    die Maskierung, um die es oben geht.
    """
    puffer = bytearray()
    aktuell: bytearray | None = None

    def fertig(teil: bytearray) -> bytes | None:
        roh = bytes(teil).rstrip(b"\r\n")
        return _entmaskieren(roh) if roh.strip() else None

    while True:
        block = strom.read(1 << 20)
        if not block:
            break
        puffer += block
        # Bis zur letzten VOLLSTAENDIGEN Zeile arbeiten: Ein Block endet
        # mitten in einer Zeile, und die darf nicht als Trenner gelten.
        letzter = puffer.rfind(b"\n")
        if letzter < 0:
            continue
        arbeit, puffer = puffer[: letzter + 1], puffer[letzter + 1 :]
        for zeile in arbeit.splitlines(keepends=True):
            if zeile.startswith(b"From "):
                if aktuell is not None:
                    roh = fertig(aktuell)
                    if roh:
                        yield roh
                aktuell = bytearray()
                continue
            if aktuell is not None:
                aktuell += zeile

    if puffer and aktuell is not None:
        aktuell += puffer
    if aktuell is not None:
        roh = fertig(aktuell)
        if roh:
            yield roh


def _kopf(roh: bytes) -> bytes:
    """Nur der Kopfteil einer Nachricht.

    ⚠️ **Eine Kopfzeile im Rumpf zaehlt nicht.** Zitierte Mails tragen ihren
    alten Kopf im Text; wer die ganze Nachricht durchsucht, liest die
    ``Message-ID`` oder das Datum einer fremden Mail und haelt es fuer das
    eigene.
    """
    return roh.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]


def kennung_lesen(roh: bytes) -> str:
    """Die ``Message-ID`` aus dem Kopfteil — ohne die ganze Mail zu zerlegen."""
    kopf = _kopf(roh)
    treffer = re.search(rb"^Message-ID:\s*(.+)$", kopf, re.IGNORECASE | re.MULTILINE)
    return treffer.group(1).decode("utf-8", "replace").strip() if treffer else ""


def datum_lesen(roh: bytes) -> datetime | None:
    """Das Absendedatum aus der ``Date``-Kopfzeile.

    ⚠️ **Ohne das ist nach dem Import jede Mail von heute.** ``APPEND`` ohne
    Datum lässt den Server die aktuelle Zeit eintragen; ein Postfach, in dem
    zehn Jahre Post denselben Zeitstempel tragen, ist nicht mehr sortierbar.
    Dieselbe Falle wie beim Verschieben über Kontogrenzen — dort steht die
    ``INTERNALDATE`` zur Verfügung, hier muss sie aus der Mail kommen.

    ⚠️ **Nicht aus der ``From``-Trennzeile.** Die trägt zwar ein Datum, aber
    in einem Format, das jedes Programm anders schreibt — und sie ist ein
    Artefakt der Datei, kein Teil der Mail.
    """
    kopf = _kopf(roh)
    treffer = re.search(rb"^Date:\s*(.+)$", kopf, re.IGNORECASE | re.MULTILINE)
    if not treffer:
        return None
    try:
        wert = parsedate_to_datetime(treffer.group(1).decode("utf-8", "replace").strip())
    except (TypeError, ValueError):
        return None
    # Ein Datum ohne Zone kommt vor. Es als UTC zu lesen verschiebt es
    # höchstens um Stunden; es wegzuwerfen verschiebt es um Jahre.
    return wert.replace(tzinfo=timezone.utc) if wert.tzinfo is None else wert


def flags_lesen(roh: bytes) -> list[bytes]:
    """Gelesen und markiert aus den Kopfzeilen, die Thunderbird hinterlaesst.

    ⚠️ **Ohne das ist nach dem Umzug alles ungelesen.** Bei zehntausend Mails
    ist das Postfach damit unbrauchbar, und niemand liest sie einzeln nach.
    Thunderbird schreibt ``X-Mozilla-Status`` (Bit 1 = gelesen, Bit 4 =
    markiert); andere schreiben ``Status: RO``.
    """
    kopf = _kopf(roh)
    flags: list[bytes] = []

    moz = re.search(rb"^X-Mozilla-Status:\s*([0-9A-Fa-f]+)", kopf, re.MULTILINE)
    if moz:
        try:
            wert = int(moz.group(1), 16)
        except ValueError:
            wert = 0
        if wert & 0x0001:
            flags.append(rb"\Seen")
        if wert & 0x0004:
            flags.append(rb"\Flagged")
        if wert & 0x0002:
            flags.append(rb"\Answered")
        return flags

    stand = re.search(rb"^Status:\s*(\S+)", kopf, re.IGNORECASE | re.MULTILINE)
    if stand and b"R" in stand.group(1):
        flags.append(rb"\Seen")
    return flags


_STATUS_WEG = re.compile(rb"^X-Mozilla-Status2?:.*(?:\r?\n)", re.IGNORECASE | re.MULTILINE)


def status_einsetzen(roh: bytes, flags) -> bytes:
    """Gelesen und markiert als ``X-Mozilla-Status`` in die Mail schreiben.

    ⚠️ **Ohne das verliert eine exportierte mbox den Gelesen-Zustand** — und
    zwar still. Am 02.09.2026 gegen ein echtes Postfach gemessen: hinaus und
    wieder herein, und alles war ungelesen. ``flags_lesen`` kann die Zeile
    lesen, nur schrieb sie niemand; Thunderbird schreibt sie in seine eigenen
    mbox-Dateien.

    ⚠️ **Nur in die mbox, nicht in eine ``.eml``.** Eine ``.eml`` ist die Mail,
    wie sie ankam — dort hat eine Kopfzeile nichts zu suchen, die nexmails
    Ansicht beschreibt. Eine mbox ist ein *Postfach*, und dazu gehoert der
    Zustand.
    """
    wert = 0
    for f in flags or ():
        klein = f.lower() if isinstance(f, bytes) else str(f).lower().encode()
        if klein == rb"\seen":
            wert |= 0x0001
        elif klein == rb"\answered":
            wert |= 0x0002
        elif klein == rb"\flagged":
            wert |= 0x0004

    # Eine schon vorhandene Zeile wird ersetzt, nicht verdoppelt: Sonst traegt
    # eine aus Thunderbird eingespielte und wieder ausgegebene Mail zwei, und
    # welche gilt, entscheidet der Zufall.
    kopf, trenner, rumpf = roh.partition(b"\r\n\r\n")
    if not trenner:
        kopf, trenner, rumpf = roh.partition(b"\n\n")
    kopf = _STATUS_WEG.sub(b"", kopf)
    zeile = b"X-Mozilla-Status: %04x\r\n" % wert
    return zeile + kopf + trenner + rumpf


def als_mbox(nachrichten: Iterator[bytes]) -> Iterator[bytes]:
    """Nachrichten als mbox ausgeben — stroemend, Stueck fuer Stueck.

    ⚠️ **Die Trennzeile braucht ein Datum, sonst lesen manche Programme die
    Datei gar nicht ein.** Ein echter Absender steht dort nicht: Die Zeile ist
    ein Artefakt des Formats, kein Teil der Mail.
    """
    stempel = format_datetime(datetime.now(timezone.utc))
    for roh in nachrichten:
        yield b"From nexmail " + stempel.encode("ascii", "replace") + b"\r\n"
        yield _maskieren(roh)
        if not roh.endswith(b"\n"):
            yield b"\r\n"
        yield b"\r\n"


def als_zip(nachrichten: Iterator[tuple[str, bytes]]) -> bytes:
    """Nachrichten als ZIP einzelner ``.eml``.

    ⚠️ **Anders als bei mbox liegt hier alles im Speicher.** Ein ZIP laesst
    sich nicht sinnvoll stroemen, ohne das Verzeichnis am Ende zu kennen. Der
    Aufrufer begrenzt deshalb die Menge — und die Oberflaeche sagt, dass mbox
    der Weg fuer grosse Ordner ist.
    """
    behaelter = io.BytesIO()
    with zipfile.ZipFile(behaelter, "w", zipfile.ZIP_DEFLATED) as archiv:
        vergeben: set[str] = set()
        for name, roh in nachrichten:
            sicher = _dateiname(name, vergeben)
            archiv.writestr(sicher, roh)
    return behaelter.getvalue()


_TABU = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sicherer_stamm(text: str, rueckfall: str) -> str:
    """Ein Dateinamens-Stamm, den jedes Betriebssystem vertraegt.

    ⚠️ **Ein Schraegstrich macht im Archiv ein Verzeichnis auf**, ein ``..``
    fuehrt beim Auspacken aus ihm heraus. Beides kommt in echten Betreffs vor
    („Rechnung 1/2026"), und beides ist hier kein Sonderfall, sondern der Grund
    fuer die Liste.
    """
    stamm = _TABU.sub("_", text or rueckfall).strip(" .") or rueckfall
    return stamm[:80]


def _dateiname(betreff: str, vergeben: set[str]) -> str:
    """Ein Dateiname, den jedes Betriebssystem vertraegt — und der eindeutig ist.

    ⚠️ **Zwei Mails duerfen denselben Betreff haben.** Ohne Nummerierung
    ueberschreibt die zweite die erste, und im Archiv fehlt eine Mail, ohne
    dass irgendwo etwas steht.
    """
    stamm = sicherer_stamm(betreff, "Nachricht")
    name = f"{stamm}.eml"
    zaehler = 2
    while name.lower() in vergeben:
        name = f"{stamm} ({zaehler}).eml"
        zaehler += 1
    vergeben.add(name.lower())
    return name


# --------------------------------------------------------------------------- #
# Die Seite zum Postfach hin
# --------------------------------------------------------------------------- #

#: Nur die Kopfzeile, die uns interessiert. ⚠️ ``PEEK``, sonst setzt der Abruf
#: nebenbei ``\Seen`` — der Import machte damit ein ganzes Postfach gelesen.
KOPF_KENNUNG = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
KOPF_KENNUNG_SCHLUESSEL = b"BODY[HEADER.FIELDS (MESSAGE-ID)]"


def vorhandene_kennungen(klient, pfad: str) -> set[str]:
    """Alle ``Message-ID`` eines Ordners — klein geschrieben, in einem Satz.

    ⚠️ **Das ist der Wiederholungsschutz.** Ohne ihn hat ein zweiter Anlauf
    alles doppelt, und ein doppelter Posteingang ist von Hand nicht mehr
    aufzuräumen.
    """
    klient.select_folder(pfad, readonly=True)
    uids = list(klient.search(["ALL"]))
    raus: set[str] = set()
    for i in range(0, len(uids), BLOCK_KOEPFE):
        antwort = klient.fetch(uids[i : i + BLOCK_KOEPFE], [KOPF_KENNUNG])
        for felder in antwort.values():
            kennung = kennung_lesen(felder.get(KOPF_KENNUNG_SCHLUESSEL) or b"")
            if kennung:
                raus.add(kennung.lower())
    return raus


def _fehler_merken(bericht: Bericht, roh: bytes, fehler: Exception) -> None:
    bericht.fehler_gesamt += 1
    if len(bericht.fehler) >= MAX_FEHLER_IM_BERICHT:
        return
    treffer = re.search(rb"^Subject:\s*(.+)$", _kopf(roh), re.IGNORECASE | re.MULTILINE)
    betreff = treffer.group(1).decode("utf-8", "replace").strip() if treffer else "(ohne Betreff)"
    # ⚠️ Der Satz des Servers wird durchgereicht, nicht ersetzt. „Ging nicht"
    # sieht aus wie ein kaputtes nexmail, obwohl der Server sagt, warum.
    bericht.fehler.append(f"{betreff[:120]}: {fehler}")


def importieren(
    db: Session,
    konto: Konto,
    ordner: Ordner,
    strom,
    bericht: Bericht | None = None,
    halt: threading.Event | None = None,
) -> Bericht:
    """Eine mbox in einen Ordner einspielen.

    ⚠️ **Unter dem Schloss des Kontos, und zwar die ganze Zeit.** Apple lässt
    genau eine Verbindung je Postfach zu; ein Import über eine Stunde hält den
    Takt dieses Postfachs so lange auf. Das ist der Preis, und er ist der
    richtige: Zwei Verbindungen wären keine, sondern ein Rauswurf.

    ⚠️ **Ein Fehlschlag bei einer Nachricht bricht nicht den ganzen Import
    ab.** Eine kaputte Mail unter zehntausend darf die anderen nicht kosten;
    sie kommt in den Bericht. Erst zehn Fehlschläge hintereinander gelten als
    „die Verbindung ist weg" und beenden den Lauf.
    """
    bericht = bericht if bericht is not None else Bericht()
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
            bekannt = vorhandene_kennungen(klient, ordner.pfad)
            hintereinander = 0

            for roh in mbox_lesen(strom):
                if halt is not None and halt.is_set():
                    bericht.abgebrochen = True
                    break
                if bericht.importiert >= MAX_NACHRICHTEN:
                    bericht.abgeschnitten = True
                    break

                bericht.gelesen += 1
                kennung = kennung_lesen(roh).lower()
                if kennung:
                    if kennung in bekannt:
                        bericht.uebersprungen += 1
                        continue
                else:
                    bericht.ohne_kennung += 1

                try:
                    klient.append(ordner.pfad, roh, flags_lesen(roh), datum_lesen(roh))
                except Exception as fehler:  # noqa: BLE001
                    _fehler_merken(bericht, roh, fehler)
                    hintereinander += 1
                    if hintereinander >= FEHLER_HINTEREINANDER:
                        raise AustauschFehler(
                            "Der Server hat zehnmal hintereinander abgelehnt. Der Import "
                            "wurde abgebrochen; was bis dahin ankam, liegt im Ordner."
                        ) from fehler
                    continue

                hintereinander = 0
                bericht.importiert += 1
                if kennung:
                    bekannt.add(kennung)

            # ⚠️ Ohne das steht die Post auf dem Server und nicht in der Liste —
            # dieselbe Regel wie bei jeder Handlung: Eine Handlung ist erst
            # fertig, wenn nexmails Datenbank es weiss.
            abgleich.ordner_abgleichen(klient, db, konto, ordner)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    logger.info(
        "Import into %s: %s read, %s appended, %s skipped, %s failed.",
        ordner.pfad,
        bericht.gelesen,
        bericht.importiert,
        bericht.uebersprungen,
        bericht.fehler_gesamt,
    )
    return bericht


def roh_stroemen(konto: Konto, pfad: str, uids: list[int]) -> Iterator[tuple[int, bytes, tuple]]:
    """Die Rohfassungen eines Ordners, blockweise beim Anbieter geholt.

    ⚠️ **nexmail hebt keine ganzen Mails auf** — nur Kopfdaten, und Texte erst
    ab dem ersten Öffnen. Ein Export muss die Post also beim Anbieter holen,
    und das dauert. Blockweise, damit nie mehr als ``BLOCK_MAILS`` Mails
    gleichzeitig im Speicher liegen.

    ⚠️ **Eine UID, die der Server nicht mehr kennt, wird übersprungen.** Der
    Export ist eine Momentaufnahme; wer währenddessen vom Telefon aus etwas
    löscht, soll keinen Abbruch bekommen.

    Geliefert werden auch die Flags — ``status_einsetzen`` macht daraus die
    Kopfzeile, ohne die eine exportierte mbox den Gelesen-Zustand verliert.
    """
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
            klient.select_folder(pfad, readonly=True)
            for i in range(0, len(uids), BLOCK_MAILS):
                teil = uids[i : i + BLOCK_MAILS]
                antwort = klient.fetch(teil, [abgleich.GANZE_MAIL, "FLAGS"])
                for uid in teil:
                    felder = antwort.get(uid) or {}
                    roh = felder.get(abgleich.GANZE_MAIL_SCHLUESSEL)
                    if roh:
                        yield uid, roh, tuple(felder.get(b"FLAGS") or ())
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# Vorgaenge: ein Import laeuft laenger als eine Anfrage
# --------------------------------------------------------------------------- #

#: Wie lange ein abgeschlossener Vorgang noch abrufbar bleibt. Danach ist sein
#: Bericht weg — er wurde entweder gelesen oder niemand hat gefragt.
VORGANG_ALTER_SEKUNDEN = 3600


@dataclass
class Vorgang:
    """Ein laufender Import.

    ⚠️ **Er lebt im Speicher, nicht in der Datenbank.** Ein Neustart des
    Containers beendet ihn; was bis dahin angehängt wurde, liegt beim Anbieter
    und wird beim nächsten Anlauf übersprungen. Ihn zu speichern hieße, einen
    halben Vorgang wiederaufnehmen zu müssen — die Wiederaufnahme ist aber
    ohnehin „Datei noch einmal auswählen".
    """

    id: str
    benutzer_id: str
    konto_id: str
    ordner_id: int
    dateiname: str
    bericht: Bericht = field(default_factory=Bericht)
    laeuft: bool = True
    #: Der Satz, an dem der ganze Vorgang gescheitert ist. Leer heisst: lief.
    fehler: str = ""
    beendet: datetime | None = None
    halt: threading.Event = field(default_factory=threading.Event)
    #: Der Faden, in dem er laeuft. Nur zum Abwarten in Tests — im Betrieb
    #: fragt die Oberflaeche den Stand ab, statt zu warten.
    faden: threading.Thread | None = None


_VORGAENGE: dict[str, Vorgang] = {}
_SCHLOSS = threading.Lock()


def _aufraeumen() -> None:
    """Alte, beendete Vorgaenge vergessen. Laeuft beim Anlegen des naechsten."""
    grenze = datetime.now(timezone.utc).timestamp() - VORGANG_ALTER_SEKUNDEN
    for kennung, vorgang in list(_VORGAENGE.items()):
        if not vorgang.laeuft and vorgang.beendet and vorgang.beendet.timestamp() < grenze:
            del _VORGAENGE[kennung]


def laeuft_schon(benutzer_id: str) -> Vorgang | None:
    """Der laufende Import dieses Benutzers, falls es einen gibt.

    ⚠️ **Einer auf einmal.** Zwei Importe in denselben Ordner überholen
    einander beim Nachsehen: Beide holen die vorhandenen Kennungen, bevor der
    andere angehängt hat — und legen alles doppelt ab.
    """
    with _SCHLOSS:
        for vorgang in _VORGAENGE.values():
            if vorgang.laeuft and vorgang.benutzer_id == benutzer_id:
                return vorgang
    return None


def stand(kennung: str, benutzer_id: str) -> Vorgang | None:
    with _SCHLOSS:
        vorgang = _VORGAENGE.get(kennung)
    # Fremder Besitz wird behandelt wie „gibt es nicht".
    return vorgang if vorgang and vorgang.benutzer_id == benutzer_id else None


def abbrechen(kennung: str, benutzer_id: str) -> bool:
    vorgang = stand(kennung, benutzer_id)
    if vorgang is None or not vorgang.laeuft:
        return False
    vorgang.halt.set()
    return True


def vorgang_starten(
    benutzer_id: str, konto_id: str, ordner_id: int, dateiname: str, datei: Path
) -> Vorgang:
    """Einen Import in einem eigenen Faden anwerfen.

    ⚠️ **Die hochgeladene Datei gehoert ab hier dem Vorgang** — er loescht sie,
    wie auch immer er endet. Ein liegengebliebenes Gigabyte-Archiv im
    Datenverzeichnis findet niemand wieder.
    """
    vorgang = Vorgang(
        id=secrets.token_urlsafe(12),
        benutzer_id=benutzer_id,
        konto_id=konto_id,
        ordner_id=ordner_id,
        dateiname=dateiname,
    )
    with _SCHLOSS:
        _aufraeumen()
        _VORGAENGE[vorgang.id] = vorgang

    vorgang.faden = threading.Thread(
        target=_lauf, args=(vorgang, datei), name=f"nexmail-import-{vorgang.id}", daemon=True
    )
    vorgang.faden.start()
    return vorgang


def _lauf(vorgang: Vorgang, datei: Path) -> None:
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        konto = db.get(Konto, vorgang.konto_id)
        ordner = db.get(Ordner, vorgang.ordner_id)
        if konto is None or ordner is None:
            vorgang.fehler = "Das Postfach oder der Ordner gibt es nicht mehr."
            return
        with datei.open("rb") as strom:
            importieren(db, konto, ordner, strom, vorgang.bericht, vorgang.halt)
    except Exception as fehler:  # noqa: BLE001
        vorgang.fehler = str(fehler)
        logger.exception("Import %s failed.", vorgang.id)
    finally:
        db.close()
        try:
            datei.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - Windows haelt die Datei manchmal
            logger.warning("The uploaded file %s could not be removed.", datei)
        vorgang.beendet = datetime.now(timezone.utc)
        vorgang.laeuft = False
