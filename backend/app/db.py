"""SQLite-Verbindung, Schemapflege und das Laden des Daten-Schluessels.

⚠️ **``/data`` gehoert auf lokale Platte, nie auf eine SMB- oder
NFS-Freigabe.** Das ist der eine Weg, auf dem SQLite tatsaechlich Daten
verliert - die Sperren funktionieren ueber Netzlaufwerke nicht zuverlaessig.
Steht so auch in der README; hier, weil es hier passiert.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from . import crypto
from .config import get_settings
from .models import Base, Geheimnis

logger = logging.getLogger("nexmail.db")

_einstellungen = get_settings()

engine = create_engine(
    f"sqlite:///{_einstellungen.db_path}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_einstellen(dbapi_connection, _record) -> None:
    """WAL, Fremdschluessel, und eine Wartezeit statt eines Fehlers.

    ⚠️ ``busy_timeout`` ist kein Detail. Ohne ihn scheitert ein Schreiber
    sofort, wenn gerade ein anderer schreibt - bei mehreren Abgleich-Faeden
    also staendig. Mit ihm wartet er; gemessen lagen 95 % der Bloecke unter
    4 ms, der schlechteste bei 179 ms.
    """
    zeiger = dbapi_connection.cursor()
    zeiger.execute("PRAGMA journal_mode=WAL")
    zeiger.execute("PRAGMA foreign_keys=ON")
    zeiger.execute("PRAGMA busy_timeout=10000")
    zeiger.execute("PRAGMA synchronous=NORMAL")
    zeiger.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Schemapflege ------------------------------------------------------- #


def _fehlende_tabellen() -> list[str]:
    vorhanden = set(inspect(engine).get_table_names())
    return [name for name in Base.metadata.tables if name not in vorhanden]


def _leere_installation() -> bool:
    """Gibt es ueberhaupt schon etwas, das man verlieren koennte?

    ⚠️ **Gezaehlt werden Tabellen, nicht Bytes.** Der naheliegende Weg - "ist
    die Datei leer?" - ist falsch, und zwar unauffaellig: Sobald sich irgendwer
    verbunden und ``journal_mode=WAL`` gesetzt hat, steht ein Dateikopf drin,
    und die Datei ist nicht mehr null Byte gross. Beim allerersten Start wurde
    damit gehorsam eine Kopie einer leeren Datenbank angelegt - sie schuetzt
    nichts und verbraucht einen der fuenf Plaetze. Genau so steht es in
    Nexview, und genau so ist es hier beim ersten Probelauf passiert.
    """
    return not inspect(engine).get_table_names()


def _sichern() -> None:
    """Kopie vor einer Schemaaenderung.

    ⚠️ **Bei einer brandneuen Installation wird nicht gesichert.** Die Pruefung
    meldet dort zwangslaeufig "alles fehlt", und es entstuende die Kopie einer
    leeren Datenbank: Sie schuetzt nichts, verbraucht aber einen der fuenf
    Plaetze - und wer nach dem ersten Start in die Liste sieht, fragt sich zu
    Recht, wovor die schuetzen soll. (Genau dieser Fehler steckte in Nexview.)
    """
    ordner = _einstellungen.data_dir / "sicherungen"
    ordner.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ziel = ordner / f"nexmail-{stempel}.db"
    shutil.copy2(_einstellungen.db_path, ziel)
    logger.info("Database backed up to %s before a schema change.", ziel)

    # ⚠️ **Hier wird nicht aufgeraeumt.** Wie viele Ruecksetzpunkte liegen
    # bleiben, stellt der Betreiber ein - und diese Funktion laeuft, bevor die
    # Datenbank lesbar ist, kennt die Zahl also nicht. Zwei Aufraeumer mit
    # verschiedenen Zahlen waeren schlimmer als einer: Die Zahl in der
    # Oberflaeche waere dann eine Behauptung, die ein Update stillschweigend
    # widerruft. Geraeumt wird einmal beim Start, in
    # ``services.sicherungsliste.aufraeumen``.


def _dek_laden(db: Session) -> None:
    """Den Daten-Schluessel holen oder beim ersten Start anlegen.

    ⚠️ Passt der KEK nicht zum verpackten DEK, wird hier **abgebrochen** und
    nicht weitergemacht. Ein Server, der mit falschem Schluessel hochfaehrt,
    zeigt lauter leere Zugangsdaten an - und der erste Reflex ist dann, sie
    neu einzutragen und damit die alten zu ueberschreiben.
    """
    zeile = db.get(Geheimnis, "dek")
    if zeile is None:
        dek = crypto.dek_erzeugen()
        db.add(Geheimnis(schluessel="dek", wert=crypto.dek_verpacken(dek)))
        db.commit()
        logger.info("A new data key was created and wrapped with the current secret key.")
    else:
        dek = crypto.dek_auspacken(zeile.wert)
    crypto.dek_setzen(dek)


def kek_wechseln(db: Session) -> None:
    """Den DEK mit dem *aktuellen* KEK neu verpacken.

    Das ist der ganze Aufwand eines Schluesselwechsels: Der Daten-Schluessel
    bleibt derselbe, alle verschluesselten Werte bleiben gueltig. Aufzurufen,
    nachdem ``NEXMAIL_SECRET_KEY`` geaendert wurde - **waehrend der alte noch
    geladen ist**.
    """
    zeile = db.get(Geheimnis, "dek")
    if zeile is None:
        raise RuntimeError("Es gibt keinen Daten-Schluessel zum Umverpacken.")
    get_settings.cache_clear()
    zeile.wert = crypto.dek_verpacken(crypto._dek())  # noqa: SLF001 - bewusst
    db.commit()
    logger.info("The data key was re-wrapped with the new secret key.")


def _fehlende_spalten() -> list[str]:
    """Spalten, die das Modell kennt und die Datenbank noch nicht.

    ⚠️ **``create_all`` legt nur Tabellen an, keine Spalten.** Nach einem
    Update mit einem neuen Feld läuft die Anwendung sonst gegen ein „no such
    column" — und zwar erst beim ersten Zugriff, weit weg vom Start. SQLite
    kann ``ADD COLUMN`` ohne Umbau; mehr braucht es hier nicht.

    Nur **Hinzufügen**. Umbenennen und Löschen bleiben Handarbeit: Beides kann
    Daten kosten, und das soll keine Automatik entscheiden.
    """
    pruefer = inspect(engine)
    ergaenzt: list[str] = []
    vorhandene_tabellen = set(pruefer.get_table_names())

    for tabelle in Base.metadata.sorted_tables:
        if tabelle.name not in vorhandene_tabellen:
            continue  # Die legt create_all gleich ganz an.
        da = {s["name"] for s in pruefer.get_columns(tabelle.name)}
        for spalte in tabelle.columns:
            if spalte.name in da:
                continue
            if not spalte.nullable and spalte.default is None and spalte.server_default is None:
                # Ohne Vorgabe ließe sich die Spalte nicht füllen - das muss
                # jemand von Hand entscheiden.
                logger.warning(
                    "Column %s.%s is missing and has no default; add it manually.",
                    tabelle.name,
                    spalte.name,
                )
                continue
            typ = spalte.type.compile(engine.dialect)
            vorgabe = spalte.default.arg if spalte.default is not None else None
            if callable(vorgabe):
                vorgabe = None
            teile = [f'ALTER TABLE "{tabelle.name}" ADD COLUMN "{spalte.name}" {typ}']
            if isinstance(vorgabe, str):
                teile.append(f"DEFAULT '{vorgabe}'")
            elif isinstance(vorgabe, bool):
                teile.append(f"DEFAULT {1 if vorgabe else 0}")
            elif isinstance(vorgabe, (int, float)):
                teile.append(f"DEFAULT {vorgabe}")
            with engine.begin() as verbindung:
                verbindung.execute(text(" ".join(teile)))
            ergaenzt.append(f"{tabelle.name}.{spalte.name}")
    return ergaenzt


def init_db() -> None:
    """Datenbank auf den Stand der laufenden Fassung bringen.

    Wird bei jedem Start aufgerufen: Nach einem Update fehlen der bestehenden
    Datenbank die Tabellen, die inzwischen dazugekommen sind.
    """
    fehlend = _fehlende_tabellen()
    if fehlend and not _leere_installation():
        _sichern()

    Base.metadata.create_all(bind=engine)

    neue_spalten = _fehlende_spalten()
    if neue_spalten:
        logger.info("Schema updated, columns added: %s", ", ".join(neue_spalten))

    if fehlend:
        logger.info("Schema updated, tables added: %s", ", ".join(sorted(fehlend)))

    # ⚠️ **Der Volltextindex steht nicht in ``Base.metadata``.** FTS5 ist eine
    # virtuelle Tabelle; SQLAlchemy kennt sie nicht und ``create_all`` legt
    # sie nicht an. Wer das vergisst, hat eine Suche, die beim ersten Start
    # mit „no such table" umfällt.
    from .services.suche import schema_anlegen

    schema_anlegen(engine)

    _einstellungen.blob_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        _dek_laden(db)


def datenbank_ersetzen(neue_datei: Path) -> None:
    """Die laufende Datenbank durch eine andere ersetzen (Wiederherstellung).

    ⚠️ **Erst alle Verbindungen schliessen.** Solange eine offen ist, haelt
    SQLite die Begleitdatei ``-wal`` fest: Unter Windows scheitert das
    Loeschen sichtbar, unter Linux ginge es still durch und liesse einen
    Schreiber an einer geloeschten Datei zurueck.
    """
    engine.dispose()
    ziel = _einstellungen.db_path
    for rest in ("-wal", "-shm"):
        Path(str(ziel) + rest).unlink(missing_ok=True)
    shutil.copy2(neue_datei, ziel)
    logger.info("Database replaced from a backup.")


def einstellung_lesen(db: Session, schluessel: str, vorgabe: str = "") -> str:
    from .models import Einstellung

    zeile = db.get(Einstellung, schluessel)
    return zeile.wert if zeile is not None else vorgabe


def einstellung_schreiben(db: Session, schluessel: str, wert: str) -> None:
    from .models import Einstellung

    zeile = db.get(Einstellung, schluessel)
    if zeile is None:
        db.add(Einstellung(schluessel=schluessel, wert=wert))
    else:
        zeile.wert = wert
    db.commit()


def hat_benutzer(db: Session) -> bool:
    """Gibt es schon ein Konto? Entscheidet, ob die Einrichtung offen ist."""
    from .models import Benutzer

    return db.execute(select(Benutzer.id).limit(1)).first() is not None
