"""Der Abgleich mit dem Postfach.

⚠️ **Eine Verbindung je Konto, geteilt zwischen Abgleich und Oberfläche.**
Apple begrenzt gleichzeitige IMAP-Verbindungen und wirft darüber hinaus
einfach heraus. Deshalb der ``Verbindungshalter``: Wer etwas vom Server will,
leiht sich die eine Verbindung und gibt sie zurück.

⚠️ **``UIDVALIDITY`` ist der Fall, den fast jeder Eigenbau übersieht.** Ändert
der Server sie, sind sämtliche gespeicherten Nummern wertlos — sie zeigen dann
auf andere Nachrichten als gedacht. Wer das nicht prüft, zeigt irgendwann eine
Mail an, die es so nie gab. Hier wird der Ordner in diesem Fall lokal geleert
und neu geholt.

⚠️ **Kopfdaten in Blöcken, Texte auf Abruf.** Vierzigtausend Mails vollständig
zu holen dauert Stunden und sprengt die Datenbank. Geholt werden ``ENVELOPE``,
``FLAGS``, ``RFC822.SIZE``, ``BODYSTRUCTURE`` und ein kurzer Anriss — der Rest
erst beim Öffnen.
"""

from __future__ import annotations

import base64
import json
import logging
import quopri
import threading
from dataclasses import dataclass, field

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Anhang, Konto, Nachricht, Ordner, utcnow
from . import (
    abwesenheit as abwesenheitsdienst,
    bereinigen,
    imap as imapdienst,
    konten as kontendienst,
    mime,
    schlagworte as schlagwortdienst,
    straenge,
)

logger = logging.getLogger("nexmail.abgleich")

#: Wie viele UIDs je Runde geholt werden. 200 ist ein Kompromiss: Größer
#: heißt weniger Runden, aber auch eine längere Transaktion, während der
#: die Oberfläche wartet.
BLOCK = 200

#: Wie weit zurück Flags nachgezogen werden. Wer eine drei Jahre alte Mail auf
#: dem Telefon als gelesen markiert, sieht das hier nicht — dafür kostet der
#: Abgleich nicht bei jeder Runde das ganze Postfach.
FLAGS_FENSTER = 2000


class Verbindungshalter:
    """Die eine Verbindung je Konto, mit Schloss.

    Bewusst kein Vorrat mehrerer Verbindungen: Apple lässt genau eine zu, und
    ein Vorrat, der bei einem Anbieter funktioniert und beim nächsten zum
    Hinauswurf führt, ist schlimmer als keiner.
    """

    def __init__(self) -> None:
        self._schloesser: dict[str, threading.Lock] = {}
        self._verwaltung = threading.Lock()

    def schloss(self, konto_id: str) -> threading.Lock:
        with self._verwaltung:
            return self._schloesser.setdefault(konto_id, threading.Lock())


HALTER = Verbindungshalter()


@dataclass
class Runde:
    """Was eine Abgleichrunde bewegt hat — für Protokoll und Oberfläche."""

    neu: int = 0
    entfernt: int = 0
    geaendert: int = 0
    neu_aufgebaut: bool = False
    #: Die Kennungen der neu hinzugekommenen Nachrichten. ⚠️ Die Regeln
    #: brauchen sie: Sie sollen auf **Neues** laufen, nicht bei jedem Abgleich
    #: über den ganzen Ordner - sonst schiebt eine Regel Post zurück, die
    #: jemand von Hand woandershin geräumt hat.
    neue_ids: list[int] = field(default_factory=list)


def _personen_json(leute) -> str:
    return json.dumps([{"n": p.name, "a": p.adresse} for p in leute], ensure_ascii=False)


def _kodierung_aus_struktur(struktur) -> tuple[str, str | None]:
    """Wie das erste Textstück kodiert ist — aus ``BODYSTRUCTURE`` abgelesen.

    ⚠️ **Ohne das steht rohes Quoted-Printable in der Vorschau.** Ein Teilabruf
    (``BODY[1]<0.512>``) liefert die Bytes **so, wie sie in der Mail stehen** —
    der Server dekodiert nichts. In der Liste stand deshalb „f=C3=BCr deinen
    Apple=C2=A0Account" statt „für deinen Apple Account". Am 01.09.2026 an
    einem echten Postfach gesehen.

    Zurück kommt die Übertragungskodierung (``quoted-printable``, ``base64``,
    …) und der Zeichensatz, falls die Struktur ihn nennt.
    """
    if struktur is None:
        return "", None
    # Die Struktur ist verschachtelt und je Server anders geformt. Statt sie
    # zu zergliedern, wird flach gesucht - für zwei Angaben genügt das, und es
    # überlebt jede Sonderform.
    flach: list[object] = []

    def sammeln(wert) -> None:
        if isinstance(wert, (list, tuple)):
            for teil in wert:
                sammeln(teil)
        else:
            flach.append(wert)

    sammeln(struktur)
    stuecke = [w.decode("ascii", "replace").lower() if isinstance(w, bytes) else str(w).lower()
               for w in flach if w is not None]

    kodierung = next(
        (w for w in stuecke if w in ("quoted-printable", "base64", "7bit", "8bit", "binary")),
        "",
    )
    zeichensatz = next(
        (w for w in stuecke if w.startswith(("utf-", "iso-", "windows-", "us-ascii", "koi8"))),
        None,
    )
    return kodierung, zeichensatz


def _anriss_aus_teil(roh: bytes | None, struktur=None) -> str:
    """Aus dem ersten Textstück einen Anreißer machen.

    Geholt wird ``BODY.PEEK[1]<0.512>`` — der erste Teil, bei den allermeisten
    Mails der Text. Ist es HTML, werden die Marken entfernt. Das ist eine
    Näherung und darf eine sein: Es geht um drei Zeilen Vorschau, nicht um den
    Inhalt.

    ⚠️ **Erst dekodieren, dann kürzen.** Siehe ``_kodierung_aus_struktur``.
    """
    if not roh:
        return ""

    kodierung, zeichensatz = _kodierung_aus_struktur(struktur)
    if kodierung == "quoted-printable":
        roh = quopri.decodestring(roh)
    elif kodierung == "base64":
        # ⚠️ Ein Teilabruf schneidet mitten in einer Base64-Gruppe ab. Die
        # angebrochene Gruppe wegwerfen, sonst wirft der Dekoder alles weg.
        sauber = b"".join(roh.split())
        sauber = sauber[: len(sauber) - len(sauber) % 4]
        try:
            roh = base64.b64decode(sauber, validate=False)
        except Exception:  # noqa: BLE001
            return ""

    text = mime.text_entziffern(roh, zeichensatz)
    if "<" in text and ">" in text:
        return bereinigen.text_aus_html(text)
    return bereinigen.anreisser(text)


def _wichtigkeit_deuten(roh: bytes | None) -> str:
    """Aus ``Importance`` und ``X-Priority`` eine von drei Stufen machen.

    Zwei Kopfzeilen fuer dieselbe Sache, weil Clients verschieden lesen und
    schreiben: Outlook setzt ``Importance: high``, Thunderbird ``X-Priority: 1``
    — oft steht auch beides da. ``Importance`` gewinnt, wenn beide da sind und
    sich widersprechen: Es sagt woertlich, was gemeint ist, waehrend die Zahl
    eine Deutung braucht.

    ⚠️ **Die Zahl kommt selten allein.** ``X-Priority: 1 (Highest)`` ist der
    Normalfall — deshalb zaehlt nur die erste Ziffer. 1–2 heisst hoch, 4–5
    niedrig, alles andere (auch Unlesbares) normal: Eine kaputte Kopfzeile
    darf keine Mail rot anmalen.
    """
    if not roh:
        return "normal"

    importance = ""
    prioritaet = ""
    for zeile in roh.decode(errors="replace").splitlines():
        name, getrennt, wert = zeile.partition(":")
        if not getrennt:
            continue
        name = name.strip().lower()
        if name == "importance":
            importance = wert.strip().lower()
        elif name == "x-priority":
            prioritaet = wert.strip()

    if importance.startswith("high"):
        return "hoch"
    if importance.startswith("low"):
        return "niedrig"
    if prioritaet[:1] in ("1", "2"):
        return "hoch"
    if prioritaet[:1] in ("4", "5"):
        return "niedrig"
    return "normal"


def ordner_abgleichen(klient, db: Session, konto: Konto, ordner: Ordner) -> Runde:
    """Einen Ordner auf Stand bringen."""
    runde = Runde()

    zustand = klient.select_folder(ordner.pfad, readonly=True)
    gueltigkeit = int(zustand.get(b"UIDVALIDITY", 0))

    # ⚠️ Der Fall, der alles entwertet.
    if ordner.uidvalidity and gueltigkeit != ordner.uidvalidity:
        logger.warning(
            "UIDVALIDITY of %s changed (%s -> %s). The folder is rebuilt from scratch.",
            ordner.pfad,
            ordner.uidvalidity,
            gueltigkeit,
        )
        db.execute(delete(Nachricht).where(Nachricht.ordner_id == ordner.id))
        ordner.hoechste_uid = 0
        runde.neu_aufgebaut = True
    ordner.uidvalidity = gueltigkeit

    alle_uids = set(klient.search(["ALL"]))

    # --- Verschwundene entfernen ---------------------------------------- #
    bekannt = set(
        db.execute(select(Nachricht.uid).where(Nachricht.ordner_id == ordner.id)).scalars().all()
    )
    verschwunden = bekannt - alle_uids
    if verschwunden:
        db.execute(
            delete(Nachricht).where(
                Nachricht.ordner_id == ordner.id, Nachricht.uid.in_(verschwunden)
            )
        )
        runde.entfernt = len(verschwunden)

    # --- Neue holen ------------------------------------------------------ #
    neue = sorted(u for u in alle_uids if u > ordner.hoechste_uid)
    for start in range(0, len(neue), BLOCK):
        haufen = neue[start : start + BLOCK]
        antwort = klient.fetch(
            haufen,
            [
                "ENVELOPE",
                "FLAGS",
                "RFC822.SIZE",
                "BODYSTRUCTURE",
                b"BODY.PEEK[1]<0.512>",
                # ⚠️ ``References`` steht **nicht** im ENVELOPE — es ist eine
                # gewoehnliche Kopfzeile. Ohne sie zerfaellt ein Strang,
                # sobald die Nachricht dazwischen fehlt.
                b"BODY.PEEK[HEADER.FIELDS (REFERENCES)]",
                # Die Wichtigkeit steht ebenfalls nur in Kopfzeilen — und je
                # nach Absender in einer von zweien. Beide holen, sonst gilt
                # eine Outlook-Mail als normal und eine Thunderbird-Mail nicht.
                b"BODY.PEEK[HEADER.FIELDS (IMPORTANCE X-PRIORITY)]",
            ],
        )
        frische = []
        atome: set[str] = set()
        for uid, felder in antwort.items():
            zeile = _aus_fetch(db, konto, ordner, uid, felder)
            db.add(zeile)
            frische.append(zeile)
            atome.update(schlagwortdienst.atome_lesen(zeile))
            runde.neu += 1
        # ⚠️ **Fremde Atome legen ihre Definition selbst an.** Was Thunderbird
        # oder das Telefon als Keyword vergeben hat, soll hier als Schlagwort
        # erscheinen — nicht unsichtbar an der Mail kleben.
        schlagwortdienst.definitionen_sicherstellen(db, konto.benutzer_id, atome)
        db.commit()
        runde.neue_ids.extend(z.id for z in frische)

        # ⚠️ **Die Abwesenheitsnotiz haengt hier, nicht am Takt.** Sie soll
        # genau die Post beantworten, die GERADE hereinkam — und nur die.
        # Ein eigener Durchlauf ueber den Bestand koennte nach einem Neustart
        # drei Wochen Post rueckwirkend beantworten.
        #
        # ⚠️ **Und sie darf den Abgleich nicht mitreissen.** Post holen ist
        # wichtiger als Post beantworten.
        if konto.abwesenheit_aktiv:
            try:
                abwesenheitsdienst.erledigen(klient, db, konto, ordner, frische)
            except Exception:  # noqa: BLE001
                logger.exception("The out-of-office check failed for one batch.")

    if neue:
        ordner.hoechste_uid = max(neue)

    # --- Flags der jüngsten Nachrichten nachziehen ----------------------- #
    juengste = sorted(alle_uids)[-FLAGS_FENSTER:]
    if juengste:
        if not ordner.wichtigkeit_nachgezogen:
            # ⚠️ **Einmaliger Nachzug des Bestands.** Die Spalte
            # ``wichtigkeit`` kam nach den ersten Abgleichen dazu; alle
            # Zeilen davor standen auf „normal", während identische neue
            # Mails ihr „!" bekamen. Nachgeholt wird im selben Fenster wie
            # die Flags — dieselbe bewusste Grenze: Was älter ist, heilt
            # erst das Öffnen (``koerper_holen``).
            flags = klient.fetch(
                juengste,
                ["FLAGS", b"BODY.PEEK[HEADER.FIELDS (IMPORTANCE X-PRIORITY)]"],
            )
            runde.geaendert = _flags_uebernehmen(db, ordner, flags, mit_wichtigkeit=True)
            ordner.wichtigkeit_nachgezogen = True
        else:
            flags = klient.fetch(juengste, ["FLAGS"])
            runde.geaendert = _flags_uebernehmen(db, ordner, flags)

    # Die Zähler kommen aus den Nachrichten, nicht aus dem, was der Server
    # gemeldet hat: Sonst stimmen sie nach einem lokalen Verschieben nicht mehr.
    ordner.anzahl = db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id).count()
    ordner.ungelesen = (
        db.query(Nachricht)
        .filter(Nachricht.ordner_id == ordner.id, Nachricht.gelesen.is_(False))
        .count()
    )
    db.commit()
    return runde


def _datum_aus_umschlag(wert) -> "datetime":
    """Das ENVELOPE-Datum nach UTC — ohne die Zeitzone zu verlieren.

    ⚠️ **Naiv heisst hier UTC, nicht Ortszeit.** Seit ``normalise_times=False``
    (siehe ``imap.verbinden``) liefert der Server das Datum samt Zeitzone, und
    ``astimezone`` rechnet richtig um. Ein naives Datum kommt nur noch von
    einem Server, der gar keine Zeitzone nennt — es als Ortszeit zu deuten
    hiesse, die Zeitzone des **nexmail-Rechners** zu raten, und genau dieses
    Raten hat den Fehler verursacht: Auf einem +02:00-Rechner stand an jeder
    Mail 09:52 statt 07:52, waehrend derselbe Code im UTC-Container zufaellig
    stimmte.
    """
    from datetime import datetime, timezone

    if wert is None:
        return utcnow()
    if wert.tzinfo is None:
        return wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(timezone.utc)


def _aus_fetch(db: Session, konto: Konto, ordner: Ordner, uid: int, felder: dict) -> Nachricht:
    umschlag = felder.get(b"ENVELOPE")
    flags = felder.get(b"FLAGS", ())
    struktur = felder.get(b"BODYSTRUCTURE")

    def person(liste):
        if not liste:
            return []
        raus = []
        for eintrag in liste:
            name = mime.kopf_lesen(
                eintrag.name.decode(errors="replace") if eintrag.name else ""
            )
            adresse = ""
            if eintrag.mailbox and eintrag.host:
                adresse = (
                    eintrag.mailbox.decode(errors="replace")
                    + "@"
                    + eintrag.host.decode(errors="replace")
                ).lower()
            raus.append(mime.Person(name=name, adresse=adresse))
        return raus

    von = person(getattr(umschlag, "from_", None))
    betreff = mime.kopf_lesen(
        umschlag.subject.decode(errors="replace") if umschlag and umschlag.subject else ""
    )

    datum = _datum_aus_umschlag(getattr(umschlag, "date", None))

    message_id = (
        umschlag.message_id.decode(errors="replace") if umschlag and umschlag.message_id else ""
    )

    # ⚠️ **Der Strang wird beim Schreiben bestimmt**, nicht beim Lesen — sonst
    # muesste jede Listenabfrage Ketten aufloesen. Siehe services/straenge.py.
    kern = mime.betreff_kern(betreff).lower()
    in_reply_to = (
        umschlag.in_reply_to.decode(errors="replace")
        if umschlag and getattr(umschlag, "in_reply_to", None)
        else ""
    )
    roh_refs = felder.get(b"BODY[HEADER.FIELDS (REFERENCES)]") or b""
    references = [
        w
        for w in roh_refs.decode(errors="replace").replace("References:", " ").split()
        if w.startswith("<")
    ]

    an = _personen_json(person(getattr(umschlag, "to", None)))
    kopie = _personen_json(person(getattr(umschlag, "cc", None)))
    beteiligte = {von[0].adresse.lower()} if von else set()
    for feld in (an, kopie):
        import json as _json

        for eintrag in _json.loads(feld or "[]"):
            if eintrag.get("adresse"):
                beteiligte.add(eintrag["adresse"].lower())

    thread = straenge.schluessel(
        db,
        konto,
        message_id=message_id,
        references=references,
        in_reply_to=in_reply_to,
        betreff_kern=kern,
        beteiligte=beteiligte,
        datum=datum,
    )

    return Nachricht(
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=uid,
        message_id=message_id,
        thread_key=thread,
        referenzen=" ".join([*references, in_reply_to]).strip(),
        betreff_kern=kern,
        von_name=von[0].name if von else "",
        von_adresse=von[0].adresse if von else "",
        an_json=an,
        kopie_json=kopie,
        betreff=betreff,
        datum=datum,
        groesse=int(felder.get(b"RFC822.SIZE", 0) or 0),
        gelesen=rb"\Seen" in flags,
        markiert=rb"\Flagged" in flags,
        beantwortet=rb"\Answered" in flags,
        # ⚠️ Alle Nicht-Systemflags werden als Schlagwort-Atome uebernommen —
        # das ist der Interop-Gewinn (siehe services/schlagworte.py).
        schlagworte=json.dumps(schlagwortdienst.atome_aus_flags(flags), ensure_ascii=False),
        hat_anhang=_hat_anhang(struktur),
        wichtigkeit=_wichtigkeit_deuten(
            felder.get(b"BODY[HEADER.FIELDS (IMPORTANCE X-PRIORITY)]")
        ),
        anreisser=_anriss_aus_teil(felder.get(b"BODY[1]<0>"), struktur),
    )


def _hat_anhang(struktur) -> bool:
    """Aus der Struktur ablesen, ob etwas dranhängt — ohne sie zu holen."""
    if struktur is None:
        return False
    text = str(struktur).lower()
    return "attachment" in text or "'name'" in text or "filename" in text


def _flags_uebernehmen(
    db: Session, ordner: Ordner, antwort: dict, mit_wichtigkeit: bool = False
) -> int:
    """Gelesen, markiert, beantwortet und die Schlagworte aus dem Fenster.

    ⚠️ **Geschrieben wird nur, was sich wirklich geaendert hat.** Bis zum
    03.09.2026 lief hier je UID ein ``UPDATE``, ohne den alten Wert
    anzusehen — bei ``FLAGS_FENSTER = 2000`` also zweitausend Schreibvorgaenge
    je Ordner und Taktrunde, auch wenn sich seit zwei Minuten nichts getan hat.
    Gemessen: 740,7 ms je Fenster gegen 16,8 ms, wenn vorher verglichen wird.
    Bei fuenf Postfaechern und einem Takt von 120 Sekunden waren das rund
    111 Sekunden Rechenzeit je Stunde, ohne dass ein Mensch etwas tut.

    ⚠️ **Und die Rueckgabe stimmt jetzt.** Vorher war es die Zahl der
    getroffenen Zeilen, also die Fenstergroesse — die Oberflaeche meldete nach
    jedem Abgleich „2000 geaendert", und das war schlicht falsch.
    """
    geaendert = 0
    gesehene_atome: set[str] = set()

    # ⚠️ **Der Bestand des Fensters in EINER Abfrage.** Je UID einzeln
    # nachzusehen waere derselbe Fehler in gruen: zweitausend Abfragen statt
    # zweitausend Schreibvorgaengen.
    vorher = {
        n.uid: n
        for n in db.execute(
            select(Nachricht).where(
                Nachricht.ordner_id == ordner.id,
                Nachricht.uid.in_(list(antwort)),
            )
        ).scalars()
    }

    for uid, felder in antwort.items():
        flags = felder.get(b"FLAGS", ())
        atome = schlagwortdienst.atome_aus_flags(flags)
        gesehene_atome.update(atome)
        werte: dict = {
            "gelesen": rb"\Seen" in flags,
            "markiert": rb"\Flagged" in flags,
            "beantwortet": rb"\Answered" in flags,
            # ⚠️ Auch das Flags-Fenster zieht Schlagworte nach: Wer am Telefon
            # eine Marke setzt oder nimmt, sieht das hier ohne Neuabgleich.
            "schlagworte": json.dumps(atome, ensure_ascii=False),
        }
        if mit_wichtigkeit:
            # Nur beim einmaligen Nachzug — siehe ``ordner_abgleichen``.
            werte["wichtigkeit"] = _wichtigkeit_deuten(
                felder.get(b"BODY[HEADER.FIELDS (IMPORTANCE X-PRIORITY)]")
            )

        zeile = vorher.get(uid)
        if zeile is None:
            # Die UID kennt nexmail (noch) nicht — dann gibt es auch nichts
            # zu aendern. Das Holen neuer Nachrichten macht ``_aus_fetch``.
            continue
        if all(getattr(zeile, feld) == wert for feld, wert in werte.items()):
            continue
        db.execute(
            update(Nachricht)
            .where(Nachricht.ordner_id == ordner.id, Nachricht.uid == uid)
            .values(**werte)
        )
        geaendert += 1
    # Fremde Atome aus dem Fenster bekommen ebenfalls ihre Definition.
    schlagwortdienst.definitionen_sicherstellen(
        db, ordner.konto.benutzer_id, gesehene_atome
    )
    return geaendert


# --- Körper auf Abruf ---------------------------------------------------- #


#: ⚠️ **``BODY.PEEK[]``, nicht ``RFC822``.** Zwei Gründe, beide gemessen:
#:
#: 1. **iCloud liefert auf ``RFC822`` gar nichts** — die Antwort enthält nur
#:    die laufende Nummer, kein Byte Inhalt. Beim All-Inkl-Postfach ging es,
#:    bei iCloud blieb jede geöffnete Mail leer. Am 01.09.2026 nachgemessen:
#:    ``RFC822`` → nur ``SEQ``; ``BODY.PEEK[]`` → 20 240 Bytes.
#: 2. ``RFC822`` setzt nebenbei ``\Seen``. nexmail entscheidet selbst, wann
#:    eine Mail als gelesen gilt (zwei Sekunden im Lesebereich) — der Server
#:    soll ihm da nicht vorgreifen.
#:
#: Der Schlüssel in der Antwort heißt dann ``BODY[]``, nicht ``BODY.PEEK[]``.
GANZE_MAIL = "BODY.PEEK[]"
GANZE_MAIL_SCHLUESSEL = b"BODY[]"


def roh_holen(db: Session, konto: Konto, nachricht: Nachricht) -> bytes | None:
    """Die eine Roh-Mail einer Nachricht beim Anbieter abholen.

    Der gemeinsame Abruf für den ``.eml``-Download, die Antwort-Vorlage und
    das Weiterleiten als Anhang — drei Stellen, ein Weg. Wer hier etwas
    ändert (etwa den Fetch-Schlüssel), ändert es damit für alle drei.

    ⚠️ **Unter dem Schloss des Kontos**, wie jede eigene Verbindung: Apple
    lässt genau eine zu und wirft darüber hinaus einfach heraus.

    ``None`` heißt: Der Server kennt die Nachricht nicht mehr — die Meldung
    dazu formuliert der Aufrufer, denn sie klingt beim Download anders als
    beim Antworten.
    """
    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            klient.select_folder(nachricht.ordner.pfad, readonly=True)
            antwort = klient.fetch([nachricht.uid], [GANZE_MAIL])
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass
    return antwort.get(nachricht.uid, {}).get(GANZE_MAIL_SCHLUESSEL) or None


def koerper_holen(klient, db: Session, nachricht: Nachricht) -> None:
    """Die ganze Mail holen, zerlegen, bereinigen und ablegen.

    ⚠️ Erst hier werden Anhänge auf die Platte geschrieben — beim Abgleich
    wäre das die Gigabyte-Falle.
    """
    ordner = nachricht.ordner
    klient.select_folder(ordner.pfad, readonly=True)
    antwort = klient.fetch([nachricht.uid], [GANZE_MAIL])
    roh = antwort.get(nachricht.uid, {}).get(GANZE_MAIL_SCHLUESSEL)
    if not roh:
        logger.warning("Message %s is gone from %s.", nachricht.uid, ordner.pfad)
        return

    zerlegt = mime.zerlegen(roh)
    html, geblockt = bereinigen.fuer_anzeige(zerlegt.html) if zerlegt.html else ("", 0)

    nachricht.koerper_text = zerlegt.text
    nachricht.koerper_html = html
    nachricht.geblockte_bilder = geblockt
    nachricht.koerper_geholt = utcnow()
    # Die Wichtigkeit noch einmal aus den echten Kopfzeilen — Zeilen von vor
    # der Spalte stehen sonst fuer immer auf „normal". Nur der Kopfteil: Im
    # Rumpf kann ein zitiertes „Importance: high" stehen, das keines ist.
    kopfteil = roh.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    nachricht.wichtigkeit = _wichtigkeit_deuten(kopfteil)
    # ⚠️ **Immer überschreiben, nicht nur wenn leer.** Der Anreißer aus dem
    # Teilabruf ist eine Näherung; hier liegt die ganze, dekodierte Mail vor.
    # Vorher blieb eine einmal falsch gebaute Vorschau für immer stehen — auch
    # nachdem der Fehler behoben war.
    besser = (
        bereinigen.anreisser(zerlegt.text)
        if zerlegt.text
        else bereinigen.text_aus_html(zerlegt.html)
    )
    if besser:
        nachricht.anreisser = besser
    # Jetzt ist die ganze Kette bekannt - der Strang wird genauer.
    nachricht.thread_key = mime.strang_kennung(zerlegt) or nachricht.thread_key

    blobs = get_settings().blob_dir
    blobs.mkdir(parents=True, exist_ok=True)

    nachricht.anhaenge.clear()
    for teil in zerlegt.anhaenge:
        pruefsumme = teil.hash()
        ziel = blobs / pruefsumme
        if not ziel.exists():
            ziel.write_bytes(teil.inhalt)
        nachricht.anhaenge.append(
            Anhang(
                teil_id=teil.teil_id,
                dateiname=teil.dateiname,
                mime=teil.mime,
                groesse=teil.groesse,
                cid=teil.cid,
                blob_hash=pruefsumme,
            )
        )
    nachricht.hat_anhang = any(not a.inline for a in zerlegt.anhaenge)
    db.commit()


def blobs_aufraeumen(db: Session) -> int:
    """Anhangsdateien wegwerfen, auf die keine Zeile mehr zeigt. Einmal beim Start.

    ⚠️ **Bis zum 03.09.2026 loeschte sie niemand.** Geschrieben werden sie
    hier, ein paar Zeilen weiter oben; einen Loeschweg gab es im ganzen Backend
    nicht. Verwaist eine Datei auf zwei Wegen: Beim Neuholen einer Nachricht
    raeumt ``nachricht.anhaenge.clear()`` die Zeilen weg, und beim Loeschen
    einer Nachricht nimmt die Kaskade sie mit — beides in der Datenbank, ohne
    dass eine Datei angefasst wird.

    Gemessen an ``data-dev`` am 03.09.2026: 6 von 13 Dateien ohne Zeile,
    1.741.577 von 1.903.636 Byte, also 91,5 Prozent. Hochgerechnet auf ein
    Postfach mit 20.000 Nachrichten waeren das Hunderte Megabyte, die nie
    wieder weggehen.

    ⚠️ **Die Pruefsumme ist der Dateiname, und sie ist geteilt.** Dieselbe
    Anlage in zwei Mails liegt einmal da. Deshalb wird gegen **alle**
    ``anhang``-Zeilen geprueft und nicht gegen die eines Benutzers; wer je nach
    Benutzer aufraeumte, loeschte dem anderen seinen Anhang weg.

    ⚠️ **Nur beim Start.** Waehrend des Betriebs liegt zwischen dem Schreiben
    der Datei und dem ``commit`` ihrer Zeile ein Moment, in dem sie verwaist
    aussieht. Beim Hochfahren nimmt niemand Anfragen entgegen, und der Fall
    kann nicht eintreten.
    """
    blobs = get_settings().blob_dir
    if not blobs.is_dir():
        return 0

    bekannt = {
        h for h in db.execute(select(Anhang.blob_hash)).scalars() if h
    }
    weg = 0
    frei = 0
    for datei in blobs.iterdir():
        if not datei.is_file() or datei.name in bekannt:
            continue
        try:
            groesse = datei.stat().st_size
            datei.unlink()
        except OSError:  # pragma: no cover - Windows haelt die Datei manchmal
            logger.warning("The orphaned attachment %s could not be removed.", datei.name)
            continue
        weg += 1
        frei += groesse
    if weg:
        logger.info("Removed %s orphaned attachment file(s), %s bytes.", weg, frei)
    return weg


# --- Ein ganzes Konto ---------------------------------------------------- #


def _stoerung_merken(db: Session, konto: Konto, art: str) -> None:
    """Abgewiesene Zugangsdaten am Konto festhalten - oder wieder austragen.

    ⚠️ **Nur die Anmeldung zaehlt als Stoerung.** Ein Server, der gerade nicht
    erreichbar ist, heilt von selbst; ein geaendertes Passwort heilt nie von
    selbst. Wer beides in denselben Banner steckt, bringt den Betreiber dazu,
    ihn wegzuklicken - und dann uebersieht er den Fall, der sein Zutun braucht.
    """
    if art == imapdienst.Fehlerart.ANMELDUNG:
        neu = "anmeldung"
    elif art == "":
        neu = ""
    else:
        # Unerreichbar, Zeitgrenze, TLS: voruebergehend. Eine bestehende
        # Anmelde-Stoerung bleibt stehen, bis eine Anmeldung GELINGT -
        # sonst loescht ein kurzer Netzausfall die Meldung, die den
        # Betreiber zum neuen Passwort fuehren soll.
        return
    if konto.stoerung != neu:
        konto.stoerung = neu
        db.commit()
        if neu:
            logger.warning("Sign-in to the mailbox was rejected; the account is flagged.")
        else:
            logger.info("Sign-in to the mailbox works again; the flag was cleared.")


def konto_abgleichen(db: Session, konto: Konto, nur_posteingang: bool = False) -> dict[str, Runde]:
    """Alle (oder nur den wichtigsten) Ordner eines Kontos abgleichen."""
    imap_pw, _ = kontendienst.passwoerter_lesen(konto)

    ergebnis: dict[str, Runde] = {}
    with HALTER.schloss(konto.id):
        try:
            klient = imapdienst.fuer_konto(db, konto)
        except imapdienst.Verbindungsfehler as fehler:
            _stoerung_merken(db, konto, fehler.art)
            raise
        _stoerung_merken(db, konto, "")
        try:
            ordner = [o for o in konto.ordner if o.waehlbar and o.abonniert]
            if nur_posteingang:
                ordner = [o for o in ordner if o.rolle == "posteingang"]
            for eintrag in ordner:
                try:
                    ergebnis[eintrag.pfad] = ordner_abgleichen(klient, db, konto, eintrag)
                except Exception as fehler:  # noqa: BLE001
                    # ⚠️ Ein Ordner, der klemmt, darf nicht den ganzen Abgleich
                    # abbrechen. Sonst hält ein einziger kaputter Ordner das
                    # Postfach dauerhaft leer.
                    logger.warning("Folder %s could not be synced: %s", eintrag.pfad, fehler)
            konto.zuletzt_geprueft = utcnow()
            konto.letzter_fehler = ""
            konto.letzter_fehler_art = ""
            db.commit()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass

    # ⚠️ **Regeln laufen hier, nach dem Abgleich — und nur auf Neues.**
    # Innerhalb des Schlosses ginge es nicht: Eine Regel, die verschiebt,
    # braucht selbst eine IMAP-Verbindung, und die bekäme sie nicht (eine je
    # Postfach). Und nur auf Neues, weil eine Regel sonst bei jedem Abgleich
    # Post zurückschöbe, die jemand von Hand woandershin geräumt hat.
    #
    # ⚠️ **Und nie auf den Wiedervorlage-Ordner.** Was dort liegt, hat ein
    # Mensch bewusst weggelegt — auch von einem anderen Gerät aus, das legt
    # die Mail dort hinein, ohne dass nexmail sie vorher kannte. Für den
    # Abgleich ist sie dann „neu", und eine Regel schöbe die bewusste Ablage
    # beim nächsten Takt wieder heraus.
    from .wiedervorlage import ORDNER_NAME as wiedervorlage_ordner  # kreisfrei erst hier

    neue = [
        kennung
        for pfad, runde in ergebnis.items()
        if pfad != wiedervorlage_ordner
        for kennung in runde.neue_ids
    ]
    if neue:
        _regeln_laufen_lassen(db, konto, neue)

    return ergebnis


def _regeln_laufen_lassen(db: Session, konto: Konto, kennungen: list[int]) -> None:
    from ..models import Benutzer
    from . import regeln as regeldienst

    person = db.get(Benutzer, konto.benutzer_id)
    if person is None:
        return
    nachrichten = [n for n in (db.get(Nachricht, k) for k in kennungen) if n is not None]
    try:
        regeldienst.anwenden(db, person, nachrichten)
    except Exception as fehler:  # noqa: BLE001
        # ⚠️ Eine krumme Regel darf keine Post aufhalten. Der Abgleich ist an
        # dieser Stelle schon durch; was die Regel nicht schafft, bleibt eben
        # im Posteingang liegen.
        logger.warning("Rules could not be applied after sync: %s", fehler)
