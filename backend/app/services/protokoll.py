"""Protokollierung — nach der Vorlage aus Nexview, mit einer Ergänzung.

nexmail schreibt sein Protokoll in eine Datei unter ``data/logs/``. Sie rollt
bei der Größengrenze um, höchstens drei alte Stände bleiben liegen, und alles
älter als 14 Tage wird weggeräumt. So läuft nichts voll.

Die Meldungen sind **englisch**. Log-Zeilen landen in Fehlerberichten und
Suchmaschinen; dort hilft Englisch weiter. ``test_protokoll.py`` hält die
Regel fest.

Vier Stufen, im Betrieb umschaltbar
-----------------------------------

``leise``
    Nur Warnungen und Fehler.
``normal``
    Standard: Zustandsänderungen, Warnungen, Fehler.
``ausfuehrlich``
    Zusätzlich der *Weg* dorthin — jeder IMAP-Befehl, jede Regelentscheidung.
``alles``
    Zusätzlich die Rohdaten der Fremdbibliotheken. Nur auf Anweisung.

``ausfuehrlich`` und ``alles`` **schalten sich selbst wieder ab.** Die Datei
ist ein Ringpuffer: Eine vergessene tiefe Stufe überschreibt binnen eines Tages
genau die Zeilen, die man behalten wollte — und niemand denkt daran, sie
zurückzustellen.

⚠️ **Was hier NIE hineingehört — und das ist bei einem Mail-Client mehr als
bei Nexview**
------------------------------------------------------------------------

Ein Protokoll wird weitergegeben: an einen Fehlerbericht, in ein Forum, an
jemanden, der beim Suchen hilft. In nexmail liegen aber Postfach-Passwörter,
fremde Adressen und **der Inhalt fremder Post**. Deshalb:

* **Keine Passwörter**, auch nicht verkürzt. ``_ZENSUR`` fängt die üblichen
  Formen ab, falls doch eines durchrutscht.
* **Keine Nachrichteninhalte** — kein Betreff, kein Anreißer, kein Text.
  Nummern und Ordnerpfade genügen für jede Fehlersuche.
* **Keine vollständigen Adressen fremder Leute.** Wer eine Adresse braucht,
  bekommt sie verkürzt: ``a***@example.org``.

Diese drei Regeln stehen nicht nur hier — ``test_protokoll.py`` prüft sie.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..config import get_settings

#: Wie viele alte Stände liegen bleiben.
ALTE_STAENDE = 3
#: Alles Ältere wird weggeräumt.
AUFBEWAHRUNG_TAGE = 14

# In der Fehlersuche ist die Datei schnell voll. Deshalb in den tiefen Stufen
# mehr Platz - sonst ist genau der interessante Anfang schon weggerollt.
MAX_BYTES_NORMAL = 5 * 1024 * 1024
MAX_BYTES_TIEF = 25 * 1024 * 1024

FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(ctx)s] | %(message)s"
DATUM = "%Y-%m-%d %H:%M:%S"

# ⚠️ **Die Datei wird in UTC geschrieben, und zwar immer.** Ein Container
# laeuft fast nie in der Zeitzone des Betreibers; stuende dort Ortszeit, waere
# unklar, welche. Die Oberflaeche rechnet beim Anzeigen in die eingestellte
# Zone um - dafuer braucht sie einen eindeutigen Zeitpunkt.
import time as _zeit

_UTC_WANDLER = _zeit.gmtime

#: Fremdbibliotheken, die sonst jeden einzelnen Aufruf protokollieren.
LAUTE = (
    "httpx",
    "httpcore",
    "urllib3",
    "watchfiles",
    "multipart",
    "sqlalchemy.engine",
    "uvicorn.access",
    # ⚠️ IMAPClient protokolliert auf DEBUG den **gesamten** Verkehr - also
    # auch den Anmeldebefehl mit dem Passwort und ganze Nachrichten. Nur in
    # der Stufe „alles", und die schaltet sich selbst ab.
    "imapclient",
    "imaplib",
)

STUFEN: dict[str, dict[str, int]] = {
    #                eigene Meldungen        alles Übrige            Fremde
    "leise": {"app": logging.WARNING, "root": logging.WARNING, "fremd": logging.WARNING},
    "normal": {"app": logging.INFO, "root": logging.INFO, "fremd": logging.WARNING},
    "ausfuehrlich": {"app": logging.DEBUG, "root": logging.INFO, "fremd": logging.INFO},
    "alles": {"app": logging.DEBUG, "root": logging.DEBUG, "fremd": logging.DEBUG},
}

#: Stufen, die sich selbst wieder abschalten.
TIEFE_STUFEN = ("ausfuehrlich", "alles")
VORGABE = "normal"

#: Erlaubte Dauern in Minuten. ``0`` heißt „bis zum Neustart".
ERLAUBTE_MINUTEN = (30, 120, 480, 0)

SCHLUESSEL_STUFE = "protokoll_stufe"
SCHLUESSEL_BIS = "protokoll_stufe_bis"

REIHENFOLGE = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Der Klammerteil ist absichtlich optional: Nach einem Update stehen in
# derselben Datei noch Zeilen im alten Format.
ZEILE = re.compile(
    r"^(?P<zeit>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<stufe>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<modul>\S+)\s"
    r"(?:\[(?P<ctx>[^\]]*)\]\s)?"
    r"\|\s(?P<meldung>.*)$"
)


# --- Was nie in der Datei stehen darf ------------------------------------- #

#: ⚠️ **Der letzte Fangzaun, nicht die erste Verteidigung.** Richtig ist, ein
#: Passwort gar nicht erst in eine Meldung zu schreiben. Aber eine Bibliothek,
#: die ihren ganzen Verkehr ausgibt, hält sich nicht an unsere Vorsätze — und
#: bei ``LOGIN`` steht das Passwort im Klartext in der Zeile.
_ZENSUR = (
    # IMAP: A001 LOGIN benutzer "geheim"
    (re.compile(r"(\bLOGIN\s+\S+\s+)(\S+)", re.IGNORECASE), r"\1***"),
    # SMTP: AUTH PLAIN <base64>
    (re.compile(r"(\bAUTH\s+\w+\s+)(\S+)", re.IGNORECASE), r"\1***"),
    # Alles, was sich selbst Passwort nennt.
    (
        re.compile(r"((?:passwor[dt]|kennwort|secret|token)\W{0,3})([^\s,;)\"']+)", re.IGNORECASE),
        r"\1***",
    ),
)


def zensieren(text: str) -> str:
    """Passwörter aus einer Zeile entfernen, bevor sie geschrieben wird."""
    for muster, ersatz in _ZENSUR:
        text = muster.sub(ersatz, text)
    return text


def adresse_kuerzen(adresse: str) -> str:
    """``anna.beispiel@example.org`` → ``a***@example.org``.

    ⚠️ **Für jede fremde Adresse, die ins Protokoll soll.** Ein Protokoll wird
    weitergegeben; die Adressen der Leute, mit denen der Betreiber schreibt,
    gehen niemanden etwas an. Die Domäne bleibt stehen — an ihr hängt fast
    jede Fehlersuche (falscher Anbieter, falscher Server).
    """
    if "@" not in adresse:
        return "***"
    name, _, domaene = adresse.partition("@")
    return f"{name[:1]}***@{domaene}" if name else f"***@{domaene}"


class _Zensor(logging.Filter):
    """Zensur auf jede Zeile, egal woher sie kommt."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            fertig = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        sauber = zensieren(fertig)
        if sauber != fertig:
            # ⚠️ Args leeren, sonst formatiert der Handler erneut aus dem
            # Original und die Zensur ist wirkungslos.
            record.msg = sauber
            record.args = ()
        return True


# --- Zusammenhang einer Anfrage -------------------------------------------- #

# ⚠️ Im ``ContextVar`` steht ein **veränderliches** Wörterbuch, kein Text.
# FastAPI führt synchrone Endpunkte in einem Threadpool aus, und der bekommt
# eine *Kopie* des Kontexts: Ein dort gesetzter Wert wäre nach der Rückkehr
# wieder weg. Das Wörterbuch dagegen ist in allen Kopien dasselbe Objekt.
_kontext: ContextVar[dict[str, str | None] | None] = ContextVar(
    "nexmail_protokoll", default=None
)


def vorgang_beginnen(nummer: str) -> object:
    return _kontext.set({"nr": nummer, "wer": None})


def vorgang_beenden(marke: object) -> None:
    _kontext.reset(marke)  # type: ignore[arg-type]


def wer_setzen(name: str | None) -> None:
    daten = _kontext.get()
    if daten is not None:
        daten["wer"] = name


def vorgangsnummer() -> str | None:
    daten = _kontext.get()
    return daten.get("nr") if daten else None


class _KontextFilter(logging.Filter):
    """Vorgangsnummer und Benutzer an jede Zeile hängen.

    ⚠️ **Das ist der Unterschied zwischen „irgendwann heute" und „bei diesem
    Klick".** Wer einen Fehler meldet, kennt selten die genaue Uhrzeit — aber
    die Vorgangsnummer steht in der Fehlermeldung, die er gesehen hat.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        daten = _kontext.get() or {}
        teile = [w for w in (daten.get("nr"),) if w]
        wer = daten.get("wer")
        if wer:
            teile.append(f"u:{wer}")
        record.ctx = " ".join(teile) if teile else "-"
        return True


class _KeinDoppelterStacktrace(logging.Filter):
    """uvicorns zweiten Stacktrace unterdrücken — unsere Zeile sagt mehr.

    ⚠️ **Verglichen wird gestrippt, und das ist der ganze Punkt.** uvicorn
    schreibt ``"Exception in ASGI application
"`` — **mit** Zeilenumbruch; er
    steht wörtlich in ``uvicorn/protocols/http/h11_impl.py``. Verglichen wurde
    ohne, und damit griff dieser Filter vom ersten Tag an nie. Gezählt am
    03.09.2026 in ``data-dev/logs``: 24 Blöcke, 2.462 Zeilen, 179.873 Byte,
    also 15,1 Prozent der Datei.

    ⚠️ **Es geht nicht um den Platz.** Unsere eigene Zeile aus
    ``middleware.py`` trägt die Vorgangsnummer und die betroffene Adresse; der
    zweite Rückverfolg trägt sie nicht. Wer im Protokoll sucht, findet dasselbe
    Ereignis zweimal — einmal mit Zusammenhang, einmal ohne — und hält es für
    zwei.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().strip() != "Exception in ASGI application"


@dataclass(frozen=True)
class Protokollzeile:
    zeit: str
    stufe: str
    modul: str
    meldung: str
    vorgang: str | None = None
    benutzer: str | None = None


@dataclass(frozen=True)
class Stand:
    stufe: str
    bis: str | None
    durch_umgebung: bool


# --- Dateien ---------------------------------------------------------------- #


def ordner() -> Path:
    ziel = get_settings().data_dir / "logs"
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def datei() -> Path:
    return ordner() / "nexmail.log"


def alte_dateien() -> list[Path]:
    return sorted(p for p in ordner().glob("nexmail.log.*") if p.is_file())


def aufraeumen() -> None:
    grenze = datetime.now(timezone.utc) - timedelta(days=AUFBEWAHRUNG_TAGE)
    for pfad in alte_dateien():
        try:
            if datetime.fromtimestamp(pfad.stat().st_mtime, timezone.utc) < grenze:
                pfad.unlink()
        except OSError:
            # Ein Protokoll, das sich nicht aufräumen lässt, darf den Start
            # nicht aufhalten.
            pass


# --- Einrichten und Umschalten ---------------------------------------------- #

_handler: RotatingFileHandler | None = None
_konsole: logging.StreamHandler | None = None
_stufe = VORGABE


def stufe_aus_umgebung() -> str | None:
    """Stufe aus ``NEXMAIL_LOG_STUFE`` — der Notausgang.

    ⚠️ Gebraucht, wenn die Anwendung gar nicht erst startet: Dann kommt man an
    keine Oberfläche, um die Stufe umzustellen.
    """
    wert = (get_settings().log_stufe or "").strip().lower()
    if wert in STUFEN:
        return wert
    # Wer technisch benennt, soll nicht ins Leere greifen.
    aliase = {
        "warning": "leise",
        "warn": "leise",
        "quiet": "leise",
        "info": "normal",
        "debug": "ausfuehrlich",
        "detailed": "ausfuehrlich",
        "trace": "alles",
    }
    return aliase.get(wert)


def einrichten() -> None:
    """Einmal beim Start. Die gespeicherte Stufe kommt später dazu."""
    global _handler, _konsole

    wurzel = logging.getLogger()
    uvicorn_fehler = logging.getLogger("uvicorn.error")

    # Doppelte Handler vermeiden - etwa beim automatischen Neustart.
    for logger_ in (wurzel, uvicorn_fehler):
        for vorhanden in list(logger_.handlers):
            if getattr(vorhanden, "_nexmail", False):
                logger_.removeHandler(vorhanden)

    former = logging.Formatter(FORMAT, DATUM)
    former.converter = _UTC_WANDLER  # type: ignore[assignment]

    handler = RotatingFileHandler(
        datei(), maxBytes=MAX_BYTES_NORMAL, backupCount=ALTE_STAENDE, encoding="utf-8"
    )
    handler.setFormatter(former)
    handler.addFilter(_KontextFilter())
    handler.addFilter(_Zensor())
    handler._nexmail = True  # type: ignore[attr-defined]
    wurzel.addHandler(handler)
    _handler = handler

    konsole = logging.StreamHandler(sys.stderr)
    konsole.setFormatter(former)
    konsole.addFilter(_KontextFilter())
    konsole.addFilter(_Zensor())
    konsole._nexmail = True  # type: ignore[attr-defined]
    wurzel.addHandler(konsole)
    _konsole = konsole

    # ⚠️ uvicorn hängt seinen Logger auf ``propagate = False``. Ohne die
    # nächste Zeile landet **kein** Startfehler und kein Absturz aus dem Server
    # selbst in der Datei, die der Betreiber herunterladen kann — er stünde nur
    # im Docker-Log. Genau das macht Ferndiagnosen unmöglich: Man bittet um das
    # Protokoll, und der Absturz fehlt darin.
    uvicorn_fehler.addHandler(handler)
    if not any(isinstance(f, _KeinDoppelterStacktrace) for f in uvicorn_fehler.filters):
        uvicorn_fehler.addFilter(_KeinDoppelterStacktrace())

    stufe_anwenden(stufe_aus_umgebung() or VORGABE)
    aufraeumen()


def stufe_anwenden(stufe: str) -> None:
    """Stufe wirksam machen — ohne Neustart.

    Ein Neustart zerstört oft genau den Zustand, den man untersuchen wollte.
    """
    global _stufe
    werte = STUFEN.get(stufe)
    if werte is None:
        stufe, werte = VORGABE, STUFEN[VORGABE]
    _stufe = stufe

    logging.getLogger().setLevel(werte["root"])
    logging.getLogger("nexmail").setLevel(werte["app"])
    for name in LAUTE:
        logging.getLogger(name).setLevel(werte["fremd"])

    if _handler is not None:
        _handler.maxBytes = MAX_BYTES_TIEF if stufe in TIEFE_STUFEN else MAX_BYTES_NORMAL
    if _konsole is not None:
        # Nie feiner als INFO: Die Container-Ausgabe soll auch während einer
        # Diagnose lesbar bleiben; die Einzelheiten stehen in der Datei.
        _konsole.setLevel(max(werte["app"], logging.INFO))


def aktuelle_stufe() -> str:
    return _stufe


# --- Lesen ------------------------------------------------------------------ #


def _zerlegen(roh: str) -> Protokollzeile | None:
    treffer = ZEILE.match(roh.rstrip("\n"))
    if treffer is None:
        return None  # Fortsetzungszeile eines Stacktrace
    daten = treffer.groupdict()
    ctx = (daten.pop("ctx") or "").strip()
    nummer: str | None = None
    benutzer: str | None = None
    for stueck in ctx.split():
        if stueck == "-":
            continue
        if stueck.startswith("u:"):
            benutzer = stueck[2:]
        else:
            nummer = stueck
    return Protokollzeile(**daten, vorgang=nummer, benutzer=benutzer)


def lesen(grenze: int = 200, stufe: str | None = None, suche: str | None = None):
    """Die neuesten Zeilen — neueste zuerst.

    ⚠️ ``stufe`` wirkt als **„diese und höher"**. Ein Gleichheitsvergleich
    wäre die häufigste Falle: Wer „WARNING" wählt, bekäme die ERROR-Zeilen
    nicht zu sehen — also genau die, die er sucht.
    """
    pfad = datei()
    if not pfad.is_file():
        return []

    gewaehlt = (stufe or "").upper()
    schwelle = REIHENFOLGE.index(gewaehlt) if gewaehlt in REIHENFOLGE else 0
    nadel = suche.casefold() if suche else None

    zeilen: list[Protokollzeile] = []
    with pfad.open("r", encoding="utf-8", errors="replace") as griff:
        for roh in griff:
            eintrag = _zerlegen(roh)
            if eintrag is None:
                continue
            if REIHENFOLGE.index(eintrag.stufe) < schwelle:
                continue
            if nadel and not _passt(eintrag, nadel):
                continue
            zeilen.append(eintrag)

    zeilen.reverse()
    return zeilen[:grenze]


def _passt(eintrag: Protokollzeile, nadel: str) -> bool:
    return any(
        nadel in (wert or "").casefold()
        for wert in (eintrag.meldung, eintrag.vorgang, eintrag.benutzer, eintrag.modul)
    )


# --- Selbstabschaltung ------------------------------------------------------ #


def stufe_setzen(db, stufe: str, minuten: int = 0) -> Stand:
    """Stufe umstellen und merken.

    ⚠️ **Eine tiefe Stufe ohne Ablauf gibt es nicht in der Oberfläche.** Die
    Datei ist ein Ringpuffer: Eine vergessene Stufe „alles" überschreibt binnen
    eines Tages genau die Zeilen, die man behalten wollte. Wer wirklich bis zum
    Neustart mitschreiben will, setzt ``NEXMAIL_LOG_STUFE`` — dann ist es eine
    bewusste Entscheidung und steht in der compose-Datei, wo man sie wiederfindet.
    """
    from ..db import einstellung_schreiben

    if stufe not in STUFEN:
        raise ValueError(f"Unbekannte Protokollstufe: {stufe}")
    if stufe in TIEFE_STUFEN and minuten <= 0:
        minuten = ERLAUBTE_MINUTEN[0]

    bis = None
    if stufe in TIEFE_STUFEN and minuten > 0:
        bis = datetime.now(timezone.utc) + timedelta(minutes=minuten)

    einstellung_schreiben(db, SCHLUESSEL_STUFE, stufe)
    einstellung_schreiben(db, SCHLUESSEL_BIS, bis.isoformat() if bis else "")
    stufe_anwenden(stufe)
    logging.getLogger("nexmail.protokoll").info(
        "Log level set to %s%s.", stufe, f" for {minuten} minutes" if bis else ""
    )
    return stand(db)


def stand(db) -> Stand:
    from ..db import einstellung_lesen

    aus_umgebung = stufe_aus_umgebung()
    if aus_umgebung:
        return Stand(stufe=aus_umgebung, bis=None, durch_umgebung=True)
    roh = einstellung_lesen(db, SCHLUESSEL_BIS)
    return Stand(stufe=aktuelle_stufe(), bis=roh or None, durch_umgebung=False)


def gespeicherte_stufe_anwenden(db) -> None:
    """Beim Start: die gemerkte Stufe holen — falls sie noch gilt."""
    from ..db import einstellung_lesen

    if stufe_aus_umgebung():
        return  # Die Umgebung hat Vorrang.

    stufe = einstellung_lesen(db, SCHLUESSEL_STUFE) or VORGABE
    if stufe in TIEFE_STUFEN and _abgelaufen(einstellung_lesen(db, SCHLUESSEL_BIS)):
        # ⚠️ Auch über einen Neustart hinweg: Wer den Container mit „alles"
        # neu startet, soll nicht wochenlang mitschreiben.
        stufe = VORGABE
    stufe_anwenden(stufe)


def ablauf_pruefen(db) -> bool:
    """Ist die tiefe Stufe abgelaufen? Dann zurück auf ``normal``.

    Gibt zurück, ob umgestellt wurde. Wird vom Takt aufgerufen.
    """
    from ..db import einstellung_lesen, einstellung_schreiben

    if stufe_aus_umgebung() or aktuelle_stufe() not in TIEFE_STUFEN:
        return False
    if not _abgelaufen(einstellung_lesen(db, SCHLUESSEL_BIS)):
        return False

    einstellung_schreiben(db, SCHLUESSEL_STUFE, VORGABE)
    einstellung_schreiben(db, SCHLUESSEL_BIS, "")
    stufe_anwenden(VORGABE)
    logging.getLogger("nexmail.protokoll").info("Log level fell back to %s.", VORGABE)
    return True


def _abgelaufen(roh: str) -> bool:
    if not roh:
        # Kein Ablauf gemerkt - dann gilt sie als abgelaufen. Lieber einmal zu
        # oft auf „normal" als eine Stufe, die nie zurückfällt.
        return True
    try:
        bis = datetime.fromisoformat(roh)
    except ValueError:
        return True
    if bis.tzinfo is None:
        bis = bis.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= bis


def leeren() -> None:
    """Die Datei zurücksetzen — ohne den laufenden Handler zu verlieren."""
    try:
        with datei().open("w", encoding="utf-8"):
            pass
    except OSError:
        pass


__all__ = [
    "ERLAUBTE_MINUTEN",
    "Protokollzeile",
    "SCHLUESSEL_BIS",
    "SCHLUESSEL_STUFE",
    "STUFEN",
    "Stand",
    "TIEFE_STUFEN",
    "VORGABE",
    "adresse_kuerzen",
    "ablauf_pruefen",
    "aktuelle_stufe",
    "alte_dateien",
    "aufraeumen",
    "datei",
    "einrichten",
    "gespeicherte_stufe_anwenden",
    "leeren",
    "lesen",
    "ordner",
    "stand",
    "stufe_anwenden",
    "stufe_setzen",
    "stufe_aus_umgebung",
    "vorgang_beenden",
    "vorgang_beginnen",
    "vorgangsnummer",
    "wer_setzen",
    "zensieren",
]
