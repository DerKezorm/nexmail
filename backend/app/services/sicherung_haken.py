"""nexmails Haken für das gemeinsame Modul ``sicherung`` (``app/vendor/nexsicherung``, bauplaene/sicherung 1.0.1).

Das Modul macht alles um eine Sicherung herum (Namen, Liste, Zeitplan, Behalten, Hoch- und Herunterladen, Prüfen,
Sicherung vor dem Wiederherstellen, die Seite); was hineinkommt und wie sie zurückkommt, sagt nexmail hier.

Drei Formen liegen in ``data/sicherungen`` und alle drei bleiben les- und wiederherstellbar:

``nexmail-YYYYMMDD-HHMMSS.db`` (+ ``.json``)
    Ein Rücksetzpunkt von vorher (oder aus ``db._sichern`` vor einer Schemaänderung): die volle Datenbank, daneben
    der Beipackzettel mit Art, Kommentar und Fassung. Ohne Zettel gilt er als „vor einem Update".
``nexmail-YYYY-MM-DD-HHMMSS.zip``
    Eine Sicherung des Moduls: **dasselbe wie ein Rücksetzpunkt** (die volle Datenbank über SQLites Backup-API und
    der Zettel), nur als ZIP unter dem Namen des Moduls (Entscheidung beim Bauen, sicherung README Nr. 3).
``…-upload.zip``, verschlüsselt (AES)
    Hochgeladen: nexmails schlankes Archiv zum Weitergeben (``sicherung.archiv``), gesperrt mit dem Passwort, das
    beim Herunterladen gewählt wurde. Prüfen und Wiederherstellen fragen danach (``locked``).

Herunterladen gibt **nie** die volle Datei hinaus, sondern das schlanke, verschlüsselte Archiv mit einem eigenen
Passwort (``download``, E22): ohne Nachrichten, die das Postfach ohnehin wieder hergibt.

Wiederherstellen geschieht sofort (``restore = "now"``): die Datenbank wird im laufenden Betrieb getauscht, danach
läuft die Schemapflege, und jede Sitzung ist weg. Die öffentliche Adresse bleibt die jetzige; wer die des Archivs
übernehmen will, nimmt nexmails alten Weg (``/api/sicherung/einspielen``).
"""

from __future__ import annotations

import io
import json
import logging
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pyzipper

from .. import __version__, crypto
from ..config import get_settings
from ..vendor import nexsicherung
from ..vendor.nexsicherung import AppHooks, BackupError, Checked, Described, Schedule, tools
from . import sicherung, sicherungsliste

logger = logging.getLogger("nexmail.sicherung")

#: Die Datenbank und der Zettel in einer Sicherung des Moduls (wie ein Rücksetzpunkt: ``.db`` und ``.json``).
DB_IM_ZIP = "nexmail.db"
ZETTEL_IM_ZIP = "nexmail.json"

#: Die Namen der Rücksetzpunkte von vorher (``db._sichern`` legt sie weiter so an).
ALTE_NAMEN = (re.compile(r"^nexmail-\d{8}-\d{6}\.db$"),)

ART_ZU_KIND = {"manuell": "manual", "zeitplan": "scheduled", "update": "update"}
KIND_ZU_ART = {kind: art for art, kind in ART_ZU_KIND.items()}

#: Der Takt von vorher und seine Namen im Modul.
TAKT_ZU_EVERY = {"aus": "off", "taeglich": "daily", "woechentlich": "weekly", "monatlich": "monthly"}
EVERY_ZU_TAKT = {every: takt for takt, every in TAKT_ZU_EVERY.items()}
SCHLUESSEL_UHRZEIT = "sicherung_uhrzeit"
UHRZEIT_VORGABE = "03:00"

#: Wie groß eine Datenbank beim Auspacken höchstens werden darf (Schutz vor einem Archiv, das sich aufbläht).
GRENZE = 64 * 1024**3


def _verschluesselt(pfad: Path) -> bool:
    with zipfile.ZipFile(pfad) as archiv:
        return any(info.flag_bits & 0x1 for info in archiv.infolist())


def _ganz(db_datei: Path) -> bool:
    try:
        return tools.database_whole(db_datei)
    except (sqlite3.DatabaseError, OSError):
        return False


def _schluessel_passt(db_datei: Path, schluessel: str | None) -> bool:
    try:
        sicherung._dek_pruefen(db_datei, schluessel)
    except sicherung.SicherungFehler:
        return False
    return True


def _aus_zip(pfad: Path, ziel: Path) -> None:
    """Die Datenbank einer Sicherung des Moduls nach ``ziel``."""
    with zipfile.ZipFile(pfad) as archiv:
        if DB_IM_ZIP not in archiv.namelist():
            raise BackupError("backup_invalid", "no database in the archive")
        tools.extract(archiv, DB_IM_ZIP, ziel, limit=GRENZE)


def rueckleitpfad(anbieter: dict) -> str:
    """Der Rueckleitpfad, den der Anbieter eines Eintrags kennt.

    ``redirect_path`` fehlt (Archiv von 0.21) oder ist NULL: ein Eintrag von 0.21, sein Anbieter kennt
    ``/api/oidc/<kuerzel>/zurueck``. Leer: der Standard des Moduls. Sonst der eigene Pfad des Eintrags.
    """
    kuerzel = anbieter.get("kuerzel", "")
    pfad = anbieter.get("redirect_path")
    if pfad is None:
        return f"/api/oidc/{kuerzel}/zurueck"
    if pfad:
        return pfad
    return "/api/oidc/callback" if kuerzel == "oidc" else f"/api/oidc/{kuerzel}/callback"


def _mit_rueckkehr(befund: dict) -> dict:
    """Der Befund eines gesperrten Archivs fuers Fenster „Wiederherstellen“ (E38): je Anmeldeanbieter die Adresse, die
    bei ihm stehen muss, mit der jetzigen Adresse und mit der aus dem Archiv (wie die alte Seite sie nannte)."""
    from .adresse import mit_vorbau

    basis = get_settings().url_base

    def voll(adresse: str, a: dict) -> str:
        return f"{mit_vorbau(adresse, basis)}{rueckleitpfad(a)}" if adresse else ""

    anbieter = [
        {
            **a,
            "rueckkehr_adresse": voll(befund.get("adresse_jetzt", ""), a),
            "rueckkehr_adresse_archiv": voll(befund.get("adresse_im_archiv", ""), a),
        }
        for a in befund.get("oidc_anbieter", [])
    ]
    return {**befund, "oidc_anbieter": anbieter}


def _jetzige_adresse() -> str:
    from ..db import SessionLocal, einstellung_lesen

    with SessionLocal() as db:
        return einstellung_lesen(db, "oeffentliche_adresse")


class Haken(AppHooks):
    """Was in eine Sicherung von nexmail kommt und wie sie zurückkommt."""

    # --- Was hineinkommt --------------------------------------------------------------------------------------------

    def pack(self, target: Path, *, kind: str, note: str, created: str) -> None:
        with tempfile.TemporaryDirectory() as ordner:
            kopie = Path(ordner) / DB_IM_ZIP
            tools.copy_database(get_settings().db_path, kopie)
            zettel = {
                "art": KIND_ZU_ART.get(kind, "manuell"),
                "kommentar": note.strip()[:200],
                "version": __version__,
                "erstellt": created,
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archiv:
                archiv.write(kopie, DB_IM_ZIP)
                archiv.writestr(ZETTEL_IM_ZIP, json.dumps(zettel, ensure_ascii=False, indent=2))

    def describe(self, path: Path) -> Described:
        if path.suffix == ".db":
            zettel = sicherungsliste._notiz_lesen(path)  # noqa: SLF001
            return Described(
                created=sicherungsliste._zeitpunkt(path.name) or None,  # noqa: SLF001
                kind=ART_ZU_KIND.get(zettel.get("art", "update"), "update"),
                note=str(zettel.get("kommentar", "")),
                version=str(zettel.get("version", "")),
            )
        try:
            with zipfile.ZipFile(path) as archiv:
                namen = set(archiv.namelist())
                gesperrt = any(info.flag_bits & 0x1 for info in archiv.infolist())
                if gesperrt:
                    if DB_IM_ZIP not in namen or sicherung.MANIFEST_IM_ARCHIV not in namen:
                        raise BackupError("backup_invalid", "not an archive of nexmail")
                    return Described(created=None, kind="manual", locked=True)
                if DB_IM_ZIP not in namen or ZETTEL_IM_ZIP not in namen:
                    raise BackupError("backup_invalid", "not an archive of nexmail")
                zettel = json.loads(archiv.read(ZETTEL_IM_ZIP).decode("utf-8"))
        except BackupError:
            raise
        except (*tools.DAMAGE, OSError) as fehler:
            raise BackupError("backup_invalid", "not an archive of nexmail") from fehler
        return Described(
            created=str(zettel.get("erstellt") or "") or None,
            kind=ART_ZU_KIND.get(str(zettel.get("art", "manuell")), "manual"),
            note=str(zettel.get("kommentar", "")),
            version=str(zettel.get("version", "")),
        )

    # --- Prüfen -----------------------------------------------------------------------------------------------------

    def check(self, path: Path, *, viewer: Any = None, archive_password: str | None = None) -> Checked:
        if path.suffix == ".zip" and _verschluesselt(path):
            return self._gesperrt_pruefen(path, archive_password)
        with tempfile.TemporaryDirectory() as ordner:
            db_datei = Path(ordner) / DB_IM_ZIP
            if path.suffix == ".db":
                tools.copy_database(path, db_datei)
            else:
                try:
                    _aus_zip(path, db_datei)
                except tools.DAMAGE:
                    return Checked(database_ok=False, damaged=[DB_IM_ZIP])
            ganz = _ganz(db_datei)
            if not ganz:
                return Checked(database_ok=False, damaged=[DB_IM_ZIP])
            # Ein Rücksetzpunkt trägt den Schlüssel nicht; er gehört zu dieser Installation. Kommt er von einer
            # anderen, passt der Schlüssel nicht, und die Postfach-Zugänge wären nach dem Einspielen leer.
            if not _schluessel_passt(db_datei, None):
                return Checked(
                    database_ok=True,
                    blocked="schluessel_passt_nicht",
                    blocked_text="The key of this server does not open this database.",
                )
        return Checked(database_ok=True)

    def _gesperrt_pruefen(self, path: Path, passwort: str | None) -> Checked:
        if not passwort:
            raise BackupError("archive_password_needed", "This archive needs its own password.")
        daten = path.read_bytes()
        try:
            befund = _mit_rueckkehr(sicherung.pruefen(daten, passwort, _jetzige_adresse()))
        except sicherung.SicherungFehler as fehler:
            raise BackupError("archive_password_wrong", "The password of the archive is wrong.") from fehler
        with tempfile.TemporaryDirectory() as ordner:
            ziel = Path(ordner)
            try:
                with pyzipper.AESZipFile(io.BytesIO(daten)) as archiv:
                    archiv.setpassword(passwort.encode("utf-8"))
                    namen = set(archiv.namelist())
                    archiv.extract(DB_IM_ZIP, ziel)
                    manifest = (
                        json.loads(archiv.read(sicherung.MANIFEST_IM_ARCHIV).decode("utf-8"))
                        if sicherung.MANIFEST_IM_ARCHIV in namen
                        else {}
                    )
                    schluessel = (
                        archiv.read(sicherung.SCHLUESSEL_IM_ARCHIV).decode("utf-8").strip()
                        if sicherung.SCHLUESSEL_IM_ARCHIV in namen
                        else None
                    )
            except RuntimeError as fehler:
                raise BackupError("archive_password_wrong", "The password of the archive is wrong.") from fehler
            except (*tools.DAMAGE, OSError, KeyError, ValueError):
                return Checked(database_ok=False, damaged=[DB_IM_ZIP], details=befund)
            # sicherung 1.0.4 (E64): was das geöffnete Archiv über sich sagt (Zeitpunkt, Art, Notiz, Fassung).
            innen = Described(
                created=str(manifest.get("erstellt") or "") or None,
                kind=ART_ZU_KIND.get(str(manifest.get("art", "manuell")), "manual"),
                note=str(manifest.get("kommentar", "")),
                version=str(manifest.get("version", "")),
                locked=True,
            )
            db_datei = ziel / DB_IM_ZIP
            if not _ganz(db_datei):
                return Checked(database_ok=False, damaged=[DB_IM_ZIP], details=befund, described=innen)
            if not _schluessel_passt(db_datei, schluessel):
                return Checked(
                    database_ok=True,
                    blocked="schluessel_passt_nicht",
                    blocked_text="The key in this archive does not open its database.",
                    details=befund,
                    described=innen,
                )
        return Checked(database_ok=True, details=befund, described=innen)

    # --- Zurückspielen, sofort ----------------------------------------------------------------------------------------

    def restore_now(
        self, path: Path, *, archive_password: str | None = None, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """``options`` (sicherung 1.0.1, E38): die Antwort auf nexmails Frage im Fenster. ``address`` an: die
        öffentliche Adresse aus der Sicherung gilt; sonst bleibt die jetzige, wie bisher ab Werk und wie der alte Weg
        (``/api/sicherung/einspielen`` mit ``adresse``) es hielt."""
        uebernehmen = bool((options or {}).get("address"))
        jetzige = _jetzige_adresse()
        if path.suffix == ".zip" and _verschluesselt(path):
            return sicherung.wiederherstellen(path.read_bytes(), archive_password or "", None if uebernehmen else jetzige)
        from ..db import SessionLocal, datenbank_ersetzen, einstellung_schreiben, init_db

        with tempfile.TemporaryDirectory() as ordner:
            db_datei = Path(ordner) / DB_IM_ZIP
            if path.suffix == ".db":
                tools.copy_database(path, db_datei)
            else:
                _aus_zip(path, db_datei)
            datenbank_ersetzen(db_datei)
        crypto.dek_setzen(None)
        # Wie nach dem Einspielen eines Archivs: Schemapflege sofort (eine ältere Sicherung kennt neue Spalten nicht).
        init_db()
        # ⚠️ **Jede Sitzung ist weg.** Die Kopie trägt die Sitzungen ihres Zeitpunkts; ein Rücksetzpunkt, der sie
        # wiederbelebte, höbe jedes „auf allen Geräten abmelden" seit damals wieder auf.
        from sqlalchemy import text

        with SessionLocal() as db:
            db.execute(text("delete from sitzung"))
            if not uebernehmen:
                einstellung_schreiben(db, "oeffentliche_adresse", jetzige)
            db.commit()
        logger.warning("A backup was restored. All sessions from the previous state are gone.")
        return {"schluessel_ersetzt": False}

    # --- Die Liste ----------------------------------------------------------------------------------------------------

    def remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)
        if path.suffix == ".db":
            sicherungsliste._beipack(path).unlink(missing_ok=True)  # noqa: SLF001

    def download(self, path: Path, *, archive_password: str | None = None) -> Path:
        """Das schlanke, verschlüsselte Archiv mit dem Passwort, das der Betreiber gerade gewählt hat. Ein
        hochgeladenes, schon verschlüsseltes Archiv geht, wie es ist."""
        if path.suffix == ".zip" and _verschluesselt(path):
            return path
        ziel = nexsicherung.archives.scratch("download")
        with tempfile.TemporaryDirectory() as ordner:
            quelle = path
            if path.suffix == ".zip":
                quelle = Path(ordner) / DB_IM_ZIP
                _aus_zip(path, quelle)
            # sicherung 1.0.4 (E64): Zeitpunkt, Art und Notiz der Sicherung gehen mit ins verschlüsselte Manifest.
            zettel = self.describe(path)
            daten = sicherung.archiv(
                archive_password or "",
                quelle=quelle,
                erstellt=zettel.created,
                art=KIND_ZU_ART.get(zettel.kind),
                kommentar=zettel.note,
            )
        tools.new_file(ziel)
        ziel.write_bytes(daten)
        fertig = ziel.with_name(f".{path.stem}-schlank.zip")
        ziel.replace(fertig)
        return fertig

    # --- Der Zeitplan -------------------------------------------------------------------------------------------------

    def load_schedule(self) -> Schedule:
        from ..db import SessionLocal, einstellung_lesen

        with SessionLocal() as db:
            takt = einstellung_lesen(db, sicherungsliste.SCHLUESSEL_TAKT) or "aus"
            behalten = einstellung_lesen(db, sicherungsliste.SCHLUESSEL_BEHALTEN)
            uhrzeit = einstellung_lesen(db, SCHLUESSEL_UHRZEIT) or UHRZEIT_VORGABE
        every = TAKT_ZU_EVERY.get(takt, takt if takt in EVERY_ZU_TAKT else "off")
        keep = int(behalten) if behalten.isdigit() and int(behalten) >= 1 else sicherungsliste.BEHALTEN_VORGABE
        return Schedule(every=every, time=uhrzeit, keep=min(keep, 365))

    def save_schedule(self, schedule: Schedule) -> None:
        from ..db import SessionLocal, einstellung_schreiben

        with SessionLocal() as db:
            einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, EVERY_ZU_TAKT.get(schedule.every, "aus"))
            einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_BEHALTEN, str(schedule.keep))
            einstellung_schreiben(db, SCHLUESSEL_UHRZEIT, schedule.time)

    # --- Der Speicher -------------------------------------------------------------------------------------------------

    def places(self) -> dict[str, Path]:
        return {"database": get_settings().db_path.parent}

    # --- Bescheid ----------------------------------------------------------------------------------------------------

    def tell(self, event: str, details: dict[str, Any]) -> None:
        logger.warning("Backup event %s: %s", event, {k: v for k, v in details.items() if k != "reason"})


def _zone():
    """Die Zeitzone des Servers (Einstellung „Zeitzone des Servers", sonst ``NEXMAIL_ZEITZONE``, sonst die des
    Rechners): die Uhrzeit des Zeitplans gilt in ihr."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from ..db import SessionLocal, einstellung_lesen

    try:
        with SessionLocal() as db:
            name = einstellung_lesen(db, "zeitzone") or get_settings().zeitzone
    except Exception:  # noqa: BLE001 (vor der Schemapflege)
        name = get_settings().zeitzone
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def konfigurieren() -> None:
    """Einmal beim Start, vor der Datenbank; danach räumt ``archives.tidy_at_start`` auf, was ein beendeter Lauf
    liegen ließ (bei restore = "now" ruft nexmail es selbst, sicherung 1.0.1)."""
    einstellungen = get_settings()
    nexsicherung.configure(
        nexsicherung.AppConfig(
            app_name="nexmail",
            data_dir=einstellungen.data_dir,
            version=__version__,
            hooks=Haken(),
            folder=einstellungen.data_dir / "sicherungen",
            database_path=einstellungen.db_path,
            restore="now",
            legacy_names=ALTE_NAMEN,
            parts={
                "database": (einstellungen.db_path.name, f"{einstellungen.db_path.name}-wal",
                             f"{einstellungen.db_path.name}-shm"),
                "attachments": ("blobs",),
                "backups": ("sicherungen",),
            },
            time_zone=_zone,
            download_password=True,
            # E38: die Frage im Fenster „Wiederherstellen“, ob die öffentliche Adresse aus der Sicherung gilt.
            restore_options=("address",),
        )
    )
