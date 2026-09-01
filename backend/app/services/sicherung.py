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


def _schlank_machen(db_datei: Path) -> dict:
    """Alles herauswerfen, was das Postfach selbst wieder hergibt.

    ⚠️ **Nachrichten sind ein Zwischenspeicher, kein Bestand.** Gemessen am
    01.09.2026: 1890 Nachrichten machen aus einer 0,36 MB großen Datenbank eine
    von 2,79 MB — 87 % davon liegen noch im Postfach auf dem Server. Der
    unersetzliche Teil (Konten, Kontakte, Regeln, Signaturen, Aufgaben,
    Benutzer, Einstellungen) **wächst nicht mit dem Postfach**, sondern nur mit
    dem, was von Hand gepflegt wurde.

    Ein Archiv, das mit jedem Jahr Post größer wird, lädt irgendwann niemand
    mehr herunter — und eine Sicherung, die auf demselben Rechner liegen
    bleibt, ist keine.

    ⚠️ **``hoechste_uid`` muss dabei zurück auf 0.** Sonst holt der Abgleich
    nach dem Einspielen nur noch, was *neuer* ist als der weggeworfene Stand:
    Das Postfach bliebe halb leer, und es sähe aus, als hätte alles geklappt.
    Dasselbe gilt für ``uidvalidity`` — sie gehört zu UIDs, die es hier nicht
    mehr gibt.

    ⚠️ **Sitzungen kommen nicht mit.** Sie sind Anmelde-Token für Geräte. Ein
    Archiv, das sie wiederbelebt, hebt jedes „auf allen Geräten abmelden"
    nachträglich wieder auf — und niemand rechnet damit.
    """
    verbindung = sqlite3.connect(str(db_datei))
    try:
        vorher = verbindung.execute("select count(*) from nachricht").fetchone()[0]

        verbindung.execute("delete from nachricht")
        # ⚠️ Ein ``delete`` auf der FTS-Tabelle raeumt bei ``content='…'``
        # nicht auf - der Index blieb dabei mit 1,03 MB stehen. Erst dieser
        # Befehl leert ihn wirklich.
        verbindung.execute("insert into nachricht_fts(nachricht_fts) values('delete-all')")
        verbindung.execute("delete from sitzung")
        verbindung.execute("update ordner set hoechste_uid = 0, uidvalidity = 0")
        verbindung.execute("update ordner set anzahl = 0, ungelesen = 0")
        # Die Straenge entstehen beim Schreiben. Ohne Nachrichten gibt es
        # nichts zu ordnen - der Neuaufbau muss nach dem Abgleich laufen.
        verbindung.execute("delete from einstellung where schluessel = 'straenge_aufgebaut'")
        verbindung.commit()
        verbindung.execute("vacuum")

        adresse = verbindung.execute(
            "select wert from einstellung where schluessel = 'oeffentliche_adresse'"
        ).fetchone()
        anbieter = [
            {"kuerzel": k, "anzeigename": a, "issuer": i}
            for k, a, i in verbindung.execute(
                "select kuerzel, anzeigename, issuer from oidc_anbieter order by kuerzel"
            )
        ]
    except sqlite3.DatabaseError as fehler:  # pragma: no cover - eigene Kopie
        raise SicherungFehler(f"Die Kopie liess sich nicht aufraeumen: {fehler}") from fehler
    finally:
        verbindung.close()

    return {
        "nachrichten_entfernt": vorher,
        "oeffentliche_adresse": adresse[0] if adresse else "",
        "oidc_anbieter": anbieter,
    }


def archiv(passwort: str, quelle: Path | None = None) -> bytes:
    """Ein verschlüsseltes ZIP mit allem, was den Stand ausmacht.

    ``quelle`` nimmt statt der laufenden Datenbank einen Rücksetzpunkt aus
    ``/data/sicherungen``. Er ist bereits eine abgeschlossene Datei — eine
    zweite konsistente Kopie davon wäre nur Arbeit ohne Wirkung.
    """
    if not passwort:
        raise SicherungFehler("Ein Archiv ohne Passwort wäre keine Sicherung.")

    einstellungen = get_settings()
    puffer = io.BytesIO()

    with tempfile.TemporaryDirectory() as ordner:
        db_kopie = Path(ordner) / DATENBANK_IM_ARCHIV
        if quelle is None:
            _konsistente_kopie(db_kopie)
        else:
            shutil.copy2(quelle, db_kopie)
        befund = _schlank_machen(db_kopie)

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
                        # ⚠️ **Die Adresse steht im Manifest, nicht nur in der
                        # Datenbank.** Beim Einspielen wird sie mit der
                        # verglichen, ueber die gerade eingespielt wird - und
                        # dafuer muss sie lesbar sein, *bevor* etwas ersetzt
                        # ist. Aus der Datenbank im Archiv liesse sie sich
                        # zwar auch holen, aber dann haengt der Vergleich an
                        # einer Datei, die man erst auspacken muss.
                        "oeffentliche_adresse": befund["oeffentliche_adresse"],
                        "oidc_anbieter": befund["oidc_anbieter"],
                        "nachrichten_entfernt": befund["nachrichten_entfernt"],
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


def _manifest_lesen(daten: bytes, passwort: str) -> dict:
    """Was das Archiv über sich selbst sagt — ohne etwas anzufassen."""
    try:
        with pyzipper.AESZipFile(io.BytesIO(daten)) as zip_datei:
            zip_datei.setpassword(passwort.encode("utf-8"))
            if MANIFEST_IM_ARCHIV not in set(zip_datei.namelist()):
                return {}
            return json.loads(zip_datei.read(MANIFEST_IM_ARCHIV).decode("utf-8"))
    except RuntimeError as fehler:
        raise SicherungFehler("Das Passwort passt nicht zu diesem Archiv.") from fehler
    except SicherungFehler:
        raise
    except Exception:
        return {}


def pruefen(daten: bytes, passwort: str, jetzige_adresse: str) -> dict:
    """Was beim Einspielen passieren würde — **bevor** etwas ersetzt ist.

    ⚠️ **Der Grund für diesen eigenen Schritt ist die öffentliche Adresse.**
    Aus ihr baut nexmail die Einladungslinks *und* die Rückkehr-Adresse für
    OIDC. Wandert ein Archiv auf eine andere Installation, zeigt sie auf den
    alten Ort — Einladungen gehen ins Leere, und die Anmeldung über den
    Anbieter scheitert mit einer Meldung, die nach einem kaputten Anbieter
    aussieht statt nach einer falschen Einstellung.

    Auf **derselben** Maschine — kaputte Platte, neuer Container, missglücktes
    Update — ist die Adresse aus dem Archiv die richtige. Deshalb wird nicht
    pauschal verworfen, sondern verglichen und gefragt.

    ⚠️ **Was nexmail dabei nicht reparieren kann:** Die Rückkehr-Adresse ist
    beim Anbieter hinterlegt, nicht hier. Nach einem Umzug muss sie dort von
    Hand nachgetragen werden — deshalb steht sie in diesem Bericht.
    """
    manifest = _manifest_lesen(daten, passwort)
    alte = (manifest.get("oeffentliche_adresse") or "").rstrip("/")
    jetzige = (jetzige_adresse or "").rstrip("/")

    return {
        "version": manifest.get("version", ""),
        "erstellt": manifest.get("erstellt", ""),
        "schluessel_dabei": manifest.get("schluessel_dabei", False),
        "nachrichten_entfernt": manifest.get("nachrichten_entfernt", 0),
        "adresse_im_archiv": alte,
        "adresse_jetzt": jetzige,
        "adresse_weicht_ab": bool(alte and jetzige and alte != jetzige),
        "oidc_anbieter": manifest.get("oidc_anbieter", []),
    }


def wiederherstellen(
    daten: bytes,
    passwort: str,
    adresse: str | None = None,
) -> dict:
    """Ein Archiv einspielen. Erst prüfen, dann ersetzen.

    ``adresse`` überschreibt nach dem Einspielen die öffentliche Adresse aus
    dem Archiv. ``None`` heißt: die aus dem Archiv behalten.
    """
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

        # ⚠️ **Erst hier, nicht in der Kopie im Archiv.** Die Entscheidung
        # faellt beim Einspielen, nicht beim Sichern - dasselbe Archiv kann
        # einmal auf dieselbe Maschine und einmal auf eine andere gehen.
        if adresse is not None:
            from ..db import einstellung_schreiben

            einstellung_schreiben(db, "oeffentliche_adresse", adresse.rstrip("/"))
            db.commit()
            logger.warning("The public address was set to the current one after a restore.")

    logger.warning("A backup was restored. All sessions from the previous state are gone.")
    return {"schluessel_ersetzt": aus_archiv is not None, "adresse_gesetzt": adresse}


def datenverzeichnis_eintraege() -> list[str]:
    """Was gerade im Datenverzeichnis liegt - für den Wächter-Test."""
    return sorted(p.name for p in get_settings().data_dir.iterdir())


def engine_schliessen() -> None:
    """Nur für Tests: Verbindungen loslassen, damit Dateien ersetzbar sind."""
    engine.dispose()
