"""Protokollierung, aus dem gemeinsamen Modul ``log`` (``app/vendor/nexlog``, bauplaene/log 1.0.0).

nexmail schreibt sein Protokoll weiter in ``data/logs/nexmail.log``: dieselbe Datei, dasselbe Zeilenformat, in UTC.
Sie rollt bei der Größengrenze um, höchstens drei alte Stände bleiben liegen, alles älter als 14 Tage wird
weggeräumt. Vier Stufen; die beiden tiefen schalten sich selbst ab (von der Seite nach einer Stunde, über den alten
Weg nach 30, 120 oder 480 Minuten). ``NEXMAIL_LOG_STUFE`` setzt die Stufe fest. Das alles steht jetzt im Modul; diese
Datei sagt ihm nur, was nexmails eigenes ist, und behält die Namen, die die übrigen Teile seit jeher rufen
(``adresse_kuerzen``, ``vorgang_beginnen``, ``ablauf_pruefen`` …).

Die Meldungen sind **englisch**. Log-Zeilen landen in Fehlerberichten und Suchmaschinen; dort hilft Englisch weiter.

⚠️ **Was hier NIE hineingehört — und das ist bei einem Mail-Client mehr als bei anderen Apps**

Ein Protokoll wird weitergegeben: an einen Fehlerbericht, in ein Forum, an jemanden, der beim Suchen hilft. In nexmail
liegen aber Postfach-Passwörter, fremde Adressen und **der Inhalt fremder Post**. Deshalb:

* **Keine Passwörter**, auch nicht verkürzt. Das Modul schwärzt die üblichen Formen, dazu nexmails eigene Regeln
  (``REGELN``: LOGIN, AUTH, Wörter wie Passwort), wörtlich wie vorher.
* **Keine Nachrichteninhalte**: kein Betreff, kein Anreißer, kein Text. Nummern und Ordnerpfade genügen.
* **Keine vollständigen Adressen fremder Leute**: ``adresse_kuerzen`` macht ``a***@example.org`` daraus.

``test_protokoll.py`` prüft diese Regeln, die Vertragstests unter ``tests/nexlog`` das Modul.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import get_settings
from ..vendor import nexlog

#: nexmails eigene Schwärzungen, wörtlich aus der Fassung vor dem Modul (``_ZENSUR``).
REGELN: tuple[tuple[str, str], ...] = (
    # IMAP: A001 LOGIN benutzer "geheim"
    (r"(?i)(\bLOGIN\s+\S+\s+)(\S+)", r"\1***"),
    # SMTP: AUTH PLAIN <base64>
    (r"(?i)(\bAUTH\s+\w+\s+)(\S+)", r"\1***"),
    # Alles, was sich selbst Passwort nennt.
    (r"(?i)((?:passwor[dt]|kennwort|secret|token)\W{0,3})([^\s,;)\"']+)", r"\1***"),
)

#: Die Vorsilben der Schlüssel: API-Schlüssel (``nxm_``) und Gerätetoken der iPhone-App (``nxa_``).
VORSILBEN = ("nxm_", "nxa_")
#: Pfade, hinter denen ein Schlüssel steht (Einladung, neues Passwort, Adresse bestätigen, App koppeln).
SCHLUESSELPFADE = ("einladung", "kennwort", "adresse", "auth/kennwort-neu", "auth/adresse", "app-kopplung")

#: IMAPClient protokolliert auf DEBUG den **gesamten** Verkehr, also auch den Anmeldebefehl und ganze Nachrichten.
#: Nur in der Stufe „alles", und die schaltet sich selbst ab.
LAUTE = ("imapclient", "imaplib", "urllib3")

#: Die alten Namen der Stufen (gespeichert und am alten Weg ``/api/protokoll``) und ihre Namen im Modul.
STUFEN: dict[str, str] = {"leise": "quiet", "normal": "normal", "ausfuehrlich": "detailed", "alles": "trace"}
_DEUTSCH = {englisch: deutsch for deutsch, englisch in STUFEN.items()}
TIEFE_STUFEN = ("ausfuehrlich", "alles")
VORGABE = "normal"

#: Erlaubte Dauern am alten Weg. ``0`` hieß „bis zum Neustart" und ist seit dem Modul 30 Minuten: eine tiefe Stufe
#: endet immer.
ERLAUBTE_MINUTEN = (30, 120, 480, 0)

SCHLUESSEL_STUFE = "protokoll_stufe"
#: Ein anderer Ordner für die Dateien (nur Tests: ein frischer Ordner wie auf einem neuen Server); sonst ``data/logs``.
ORDNER: Path | None = None
SCHLUESSEL_BIS = "protokoll_stufe_bis"


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


def konfiguration() -> nexlog.AppConfig:
    return nexlog.AppConfig(
        app_name="nexmail",
        log_dir=lambda: ORDNER or get_settings().data_dir / "logs",
        env_level=lambda: get_settings().log_stufe or "",
        env_name="NEXMAIL_LOG_STUFE",
        utc=True,
        key_prefixes=VORSILBEN,
        token_paths=SCHLUESSELPFADE,
        redactions=REGELN,
        noisy_loggers=LAUTE,
    )


# Gleich beim Laden: Wer schwärzt oder kürzt, bevor der Start ``einrichten`` ruft, bekommt schon nexmails Regeln.
nexlog.configure(konfiguration())


def einrichten() -> None:
    """Einmal beim Start, vor allem anderen. Die gespeicherte Stufe kommt mit der Datenbank dazu."""
    nexlog.configure(konfiguration())
    nexlog.setup()
    nexlog.attach_store(_lesen_gespeichert, _schreiben_gespeichert)


def _lesen_gespeichert() -> tuple[str, str]:
    from ..db import SessionLocal, einstellung_lesen

    try:
        with SessionLocal() as db:
            return einstellung_lesen(db, SCHLUESSEL_STUFE), einstellung_lesen(db, SCHLUESSEL_BIS)
    except Exception:  # noqa: BLE001 (vor der Schemapflege gibt es die Tabelle noch nicht)
        return "", ""


def _schreiben_gespeichert(stufe: str, bis: datetime | None) -> None:
    from ..db import SessionLocal, einstellung_schreiben

    with SessionLocal() as db:
        einstellung_schreiben(db, SCHLUESSEL_STUFE, stufe)
        einstellung_schreiben(db, SCHLUESSEL_BIS, bis.isoformat() if bis else "")


def gespeicherte_stufe_anwenden(db=None) -> None:  # noqa: ARG001 (der alte Aufruf reichte die Sitzung herein)
    """Beim Start, sobald die Datenbank steht: die gemerkte Stufe holen, falls sie noch gilt."""
    nexlog.attach_store(_lesen_gespeichert, _schreiben_gespeichert)
    nexlog.apply_stored_mode()


def _englisch(stufe: str) -> str:
    gewaehlt = nexlog.normalize_mode(stufe)
    if gewaehlt is None:
        raise ValueError(f"Unknown log level: {stufe}")
    return gewaehlt


def stufe_anwenden(stufe: str) -> None:
    """Stufe wirksam machen, ohne sie zu merken."""
    nexlog.apply_mode(nexlog.normalize_mode(stufe) or nexlog.DEFAULT_MODE)


def aktuelle_stufe() -> str:
    return _DEUTSCH.get(nexlog.current_mode(), nexlog.current_mode())


def stufe_setzen(db, stufe: str, minuten: int = 0) -> Stand:  # noqa: ARG001
    """Stufe umstellen und merken (alter Weg). Eine tiefe Stufe ohne Dauer läuft 30 Minuten wie vorher."""
    englisch = _englisch(stufe)
    if englisch in nexlog.DEEP_MODES and minuten not in nexlog.ALLOWED_MINUTES:
        minuten = ERLAUBTE_MINUTEN[0]
    nexlog.set_mode(englisch, minuten if englisch in nexlog.DEEP_MODES else 0)
    return stand()


def stand(db=None) -> Stand:  # noqa: ARG001
    lage = nexlog.state()
    return Stand(stufe=_DEUTSCH.get(lage.mode, lage.mode), bis=lage.until, durch_umgebung=lage.fixed_by_env)


def stufe_aus_umgebung() -> str | None:
    gewaehlt = nexlog.env_mode()
    return _DEUTSCH.get(gewaehlt, gewaehlt) if gewaehlt else None


def ablauf_pruefen(db=None) -> bool:  # noqa: ARG001
    """Ist die tiefe Stufe abgelaufen? Dann zurück auf ``normal``. Der Takt ruft es; das Modul hat dazu seinen Wächter."""
    return nexlog.enforce_expiry()


def zensieren(text: str) -> str:
    """Passwörter und Schlüssel aus einer Zeile entfernen, bevor sie geschrieben wird."""
    return nexlog.redact(text)


def adresse_kuerzen(adresse: str) -> str:
    """``anna.beispiel@example.org`` → ``a***@example.org``. Für jede fremde Adresse, die ins Protokoll soll; die
    Domäne bleibt, an ihr hängt fast jede Fehlersuche."""
    return nexlog.shorten_address(adresse)


def vorgang_beginnen(nummer: str) -> object:
    return nexlog.bind_request(nummer)


def vorgang_beenden(marke: object) -> None:
    nexlog.unbind_request(marke)  # type: ignore[arg-type]


def wer_setzen(name: str | None) -> None:
    nexlog.set_actor(name)


def vorgangsnummer() -> str | None:
    return nexlog.current_request_id()


def ordner() -> Path:
    return nexlog.log_dir()


def datei() -> Path:
    return nexlog.log_file()


def alte_dateien() -> list[Path]:
    return nexlog.rotated_files()


def aufraeumen() -> None:
    nexlog.purge_old()


def lesen(grenze: int = 200, stufe: str | None = None, suche: str | None = None) -> list[Protokollzeile]:
    """Die neuesten Zeilen, neueste zuerst; ``stufe`` meint „diese und höher"."""
    gewaehlt = (stufe or "").upper()
    return [
        Protokollzeile(
            zeit=zeile.time,
            stufe=zeile.level,
            modul=zeile.logger,
            meldung=zeile.message,
            vorgang=zeile.request_id,
            benutzer=zeile.user,
        )
        for zeile in nexlog.read(
            limit=grenze, level=gewaehlt if gewaehlt in nexlog.LEVEL_ORDER else None, search=suche or None
        )
    ]


def leeren() -> None:
    """Alle Zeilen weg, auch die älteren Dateien; danach eine WARNING-Zeile mit dem Konto (Modul)."""
    nexlog.clear()


__all__ = [
    "ERLAUBTE_MINUTEN",
    "Protokollzeile",
    "SCHLUESSEL_BIS",
    "SCHLUESSEL_STUFE",
    "STUFEN",
    "Stand",
    "TIEFE_STUFEN",
    "VORGABE",
    "ablauf_pruefen",
    "adresse_kuerzen",
    "aktuelle_stufe",
    "alte_dateien",
    "aufraeumen",
    "datei",
    "einrichten",
    "gespeicherte_stufe_anwenden",
    "konfiguration",
    "leeren",
    "lesen",
    "ordner",
    "stand",
    "stufe_anwenden",
    "stufe_aus_umgebung",
    "stufe_setzen",
    "vorgang_beenden",
    "vorgang_beginnen",
    "vorgangsnummer",
    "wer_setzen",
    "zensieren",
]
