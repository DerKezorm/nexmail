"""Sicherung und Wiederherstellung.

⚠️ **Eine Kopie neben der Datenbank ist noch keine Sicherung.** Beide lägen im
selben Verzeichnis, also auf demselben Volume — stirbt das, sind sie zusammen
weg. Deshalb erzeugt ``archiv()`` etwas zum **Herunterladen**, und erst das ist
eine.

Was hineingehört — und warum das mehr ist als die Datenbank
-----------------------------------------------------------
Die Postfach-Passwörter liegen verschlüsselt in der Datenbank. Der Schlüssel
dazu steht **nicht** darin, sondern daneben in ``secret.key``. Wer nur die
Datenbank sichert, merkt das erst im Ernstfall: Beim Einspielen auf einer
frischen Installation entstünde ein neuer Schlüssel, und danach wäre kein
einziger Zugang mehr lesbar — bei nexmail heißt das: **alle Postfächer neu
einrichten.**

⚠️ **AES-ZIP und kein eigenes Format.** Ein selbstgebautes Format könnte nur
nexmail wieder öffnen — und ausgerechnet dann, wenn man die Sicherung braucht,
läuft nexmail vielleicht nicht. Ein ZIP bekommt man mit 7-Zip, WinRAR oder dem
Explorer auf. Die Daten bleiben ihrem Besitzer zugänglich, auch ohne uns.

⚠️ **Beim Wiederherstellen wird zuerst geprüft, dann ersetzt.** Erst wenn der
Schlüssel im Archiv den Daten-Schlüssel der mitgelieferten Datenbank
tatsächlich aufschließt, wird etwas angefasst. Sonst hätte man eine laufende
Installation gegen eine unlesbare getauscht — und der erste Reflex wäre, die
Zugänge neu einzutragen und damit die alten zu überschreiben.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pyzipper

from .. import __version__, crypto
from ..config import get_settings
from ..db import datenbank_ersetzen, engine

logger = logging.getLogger("nexmail.sicherung")

DATENBANK_IM_ARCHIV = "nexmail.db"
SCHLUESSEL_IM_ARCHIV = "secret.key"
MANIFEST_IM_ARCHIV = "manifest.json"

#: Was statt des Schlüssels ins Archiv wandert, wenn keiner danebenliegt.
#: Er steht dann in NEXMAIL_SECRET_KEY, also in der Docker-Datei — und der
#: Hinweis darauf gehört ins Archiv, nicht in ein Protokoll, das niemand liest.
OHNE_SCHLUESSEL = (
    "Dieser Installation liegt kein secret.key bei - der Schluessel kommt aus\n"
    "NEXMAIL_SECRET_KEY, also aus der Umgebung (docker-compose.yml oder .env).\n"
    "\n"
    "⚠️ Ohne diesen Wert ist die Datenbank in diesem Archiv nutzlos: Alle\n"
    "Postfach-Passwoerter sind damit verschluesselt. Sichere ihn getrennt.\n"
)

#: ⚠️ **Diese Liste ist der Wächter, nicht die Ausrede.** Der naheliegende Test
#: prüft benannte Bestandteile: „ist die Datenbank drin, ist der Schlüssel
#: drin". Genau deshalb konnte in Nexview ein ganzer Ordner unbemerkt fehlen —
#: er stand auf keiner Liste, also fragte niemand danach. Der Test hier dreht
#: es um: **Alles** im Datenverzeichnis muss entweder ins Archiv gehen oder
#: hier stehen, samt Begründung.
#:
#: ⚠️ **Beim Fehlschlag wird hier nicht routinemäßig ein Eintrag ergänzt.** Ein
#: neuer Name heißt: Jemand hat etwas angelegt, ohne zu entscheiden, ob es in
#: eine Sicherung gehört. Diese Entscheidung ist der Zweck des roten Laufs. Wer
#: hier einträgt, schreibt den Grund dazu — und wenn ihm keiner einfällt,
#: gehört der Eintrag ins Archiv statt in diese Liste.
NICHT_INS_ARCHIV: dict[str, str] = {
    "blobs": (
        "Die Anhänge. Am 31.08.2026 bewusst ausgenommen: Sie sind der weitaus "
        "größte Posten und liegen ohnehin noch im Postfach auf dem Server. Eine "
        "Sicherung, die zu groß zum Herunterladen ist, lädt niemand herunter. "
        "Für wen das nicht reicht, gibt es einen eigenen Knopf für ein "
        "Anhang-Archiv."
    ),
    "sicherungen": (
        "Die Kopien, die vor einer Schemaänderung entstehen. Eine Sicherung in "
        "der Sicherung verdoppelt die Größe und rettet nichts, was das Archiv "
        "nicht ohnehin trägt."
    ),
    "logs": (
        "Das Protokoll beschreibt den Betrieb, nicht den Stand. Vier Wochen "
        "alte Zeilen in einer frisch eingespielten Installation wären "
        "irreführend."
    ),
    "nexmail.db-wal": (
        "Begleitdatei von SQLite. Ihr Inhalt steckt bereits in der "
        "konsistenten Kopie der Datenbank; einzeln mitgenommen wäre sie ein "
        "Zwischenstand ohne die Datei, zu der er gehört."
    ),
    "nexmail.db-shm": (
        "Begleitdatei von SQLite, wie -wal. Sie beschreibt den gemeinsamen "
        "Speicher laufender Verbindungen und ist ausserhalb dieses Prozesses "
        "bedeutungslos."
    ),
}


class SicherungFehler(RuntimeError):
    """Etwas am Archiv stimmt nicht — mit einem Satz, der sagt was."""


# --- Erzeugen ------------------------------------------------------------ #


def _konsistente_kopie(ziel: Path) -> None:
    """Die Datenbank kopieren, während sie benutzt wird.

    ⚠️ Über SQLites eigene Sicherungs-Schnittstelle und **nicht** mit
    ``shutil.copy``: Eine Dateikopie mitten in einer Schreiboperation ist ein
    halber Zustand, und man merkt es erst beim Einspielen.
    """
    quelle = sqlite3.connect(str(get_settings().db_path))
    try:
        kopie = sqlite3.connect(str(ziel))
        try:
            quelle.backup(kopie)
        finally:
            kopie.close()
    finally:
        quelle.close()


def archiv(passwort: str) -> bytes:
    """Ein verschlüsseltes ZIP mit allem, was den Stand ausmacht."""
    if not passwort:
        raise SicherungFehler("Ein Archiv ohne Passwort wäre keine Sicherung.")

    einstellungen = get_settings()
    puffer = io.BytesIO()

    with tempfile.TemporaryDirectory() as ordner:
        db_kopie = Path(ordner) / DATENBANK_IM_ARCHIV
        _konsistente_kopie(db_kopie)

        with pyzipper.AESZipFile(
            puffer, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
        ) as zip_datei:
            zip_datei.setpassword(passwort.encode("utf-8"))

            zip_datei.write(db_kopie, DATENBANK_IM_ARCHIV)

            # ⚠️ **Der Ausgang gehoert hinein.** Was dort liegt, ist noch
            # nicht verschickt - es ist Zustand, kein Zwischenspeicher. Wer
            # ihn weglaesst, verliert bei einer Wiederherstellung genau die
            # Mails, die noch niemand bekommen hat.
            ausgang = einstellungen.data_dir / "ausgang"
            if ausgang.is_dir():
                for eintrag in sorted(ausgang.glob("*.eml")):
                    zip_datei.write(eintrag, f"ausgang/{eintrag.name}")

            if einstellungen.key_path.exists():
                zip_datei.write(einstellungen.key_path, SCHLUESSEL_IM_ARCHIV)
                schluessel_dabei = True
            else:
                zip_datei.writestr("SCHLUESSEL-FEHLT.txt", OHNE_SCHLUESSEL)
                schluessel_dabei = False

            zip_datei.writestr(
                MANIFEST_IM_ARCHIV,
                json.dumps(
                    {
                        "anwendung": "nexmail",
                        "version": __version__,
                        "erstellt": datetime.now(timezone.utc).isoformat(),
                        "schluessel_dabei": schluessel_dabei,
                        "nicht_enthalten": sorted(NICHT_INS_ARCHIV),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

    logger.info("A backup archive was created (key included: %s).", schluessel_dabei)
    return puffer.getvalue()


def archiv_name() -> str:
    stempel = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"nexmail-sicherung-{stempel}.zip"


# --- Einspielen ---------------------------------------------------------- #


def _dek_pruefen(db_datei: Path, schluessel: str | None) -> None:
    """Lässt sich der Daten-Schlüssel dieser Datenbank überhaupt aufschließen?

    ⚠️ Das ist die Prüfung, die vor dem Ersetzen läuft. Fällt sie durch, wird
    **nichts** angefasst — und die Meldung sagt, was fehlt, statt hinterher
    lauter leere Zugangsdaten zu zeigen.
    """
    verbindung = sqlite3.connect(str(db_datei))
    try:
        try:
            zeile = verbindung.execute(
                "select wert from geheimnis where schluessel = 'dek'"
            ).fetchone()
        except sqlite3.DatabaseError as fehler:
            raise SicherungFehler(
                "Die Datei im Archiv ist keine nexmail-Datenbank."
            ) from fehler
    finally:
        verbindung.close()

    if zeile is None:
        # Eine Datenbank ohne Daten-Schlüssel ist entweder sehr alt oder leer.
        # Beides ist kein Grund abzulehnen - es gibt dann nichts zu entschlüsseln.
        return

    einstellungen = get_settings()
    alter_wert = einstellungen.secret_key
    try:
        if schluessel is not None:
            einstellungen.secret_key = schluessel
        crypto.dek_auspacken(zeile[0])
    except crypto.SchluesselFehler as fehler:
        raise SicherungFehler(
            "Der Schlüssel passt nicht zu dieser Datenbank. Ohne ihn wären "
            "alle Postfach-Passwörter unlesbar, deshalb wurde nichts ersetzt. "
            "Fehlt im Archiv die Datei secret.key, muss NEXMAIL_SECRET_KEY auf "
            "den Wert der alten Installation gesetzt werden."
        ) from fehler
    finally:
        einstellungen.secret_key = alter_wert


def wiederherstellen(daten: bytes, passwort: str) -> dict:
    """Ein Archiv einspielen. Erst prüfen, dann ersetzen."""
    einstellungen = get_settings()

    with tempfile.TemporaryDirectory() as ordner:
        ziel = Path(ordner)
        try:
            with pyzipper.AESZipFile(io.BytesIO(daten)) as zip_datei:
                zip_datei.setpassword(passwort.encode("utf-8"))
                namen = set(zip_datei.namelist())
                if DATENBANK_IM_ARCHIV not in namen:
                    raise SicherungFehler("Im Archiv fehlt die Datenbank.")
                zip_datei.extract(DATENBANK_IM_ARCHIV, ziel)
                if SCHLUESSEL_IM_ARCHIV in namen:
                    zip_datei.extract(SCHLUESSEL_IM_ARCHIV, ziel)
        except RuntimeError as fehler:
            # pyzipper meldet ein falsches Passwort als RuntimeError.
            raise SicherungFehler("Das Passwort passt nicht zu diesem Archiv.") from fehler
        except SicherungFehler:
            raise
        except Exception as fehler:
            raise SicherungFehler("Die Datei ist kein lesbares nexmail-Archiv.") from fehler

        db_datei = ziel / DATENBANK_IM_ARCHIV
        schluessel_datei = ziel / SCHLUESSEL_IM_ARCHIV
        aus_archiv = (
            schluessel_datei.read_text(encoding="utf-8").strip()
            if schluessel_datei.exists()
            else None
        )

        # ⚠️ Hier wird geprüft. Bis hierher ist nichts ersetzt worden.
        _dek_pruefen(db_datei, aus_archiv)

        # Ab hier wird angefasst - und zwar der Schlüssel zuerst: Eine
        # Datenbank ohne passenden Schlüssel wäre der schlimmere Zwischenstand.
        if aus_archiv is not None:
            einstellungen.key_path.write_text(aus_archiv + "\n", encoding="utf-8")
            try:
                einstellungen.key_path.chmod(0o600)
            except OSError:  # pragma: no cover
                pass

        datenbank_ersetzen(db_datei)

    # Den Daten-Schlüssel neu laden - der alte gehört zu einer Datenbank, die
    # es nicht mehr gibt.
    crypto.dek_setzen(None)
    from ..db import SessionLocal, _dek_laden

    with SessionLocal() as db:
        _dek_laden(db)

    logger.warning("A backup was restored. All sessions from the previous state are gone.")
    return {"schluessel_ersetzt": aus_archiv is not None}


def datenverzeichnis_eintraege() -> list[str]:
    """Was gerade im Datenverzeichnis liegt - für den Wächter-Test."""
    return sorted(p.name for p in get_settings().data_dir.iterdir())


def engine_schliessen() -> None:
    """Nur für Tests: Verbindungen loslassen, damit Dateien ersetzbar sind."""
    engine.dispose()
