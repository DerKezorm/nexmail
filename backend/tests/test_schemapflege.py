"""Die Schemapflege beim Start: Tabellen, Spalten - und Indizes.

⚠️ **Indizes waren die Luecke, und sie war unsichtbar.**
``Base.metadata.create_all`` legt einen Index nur zusammen mit einer NEUEN
Tabelle an. Steht die Tabelle schon, sieht es sie nicht an. Ein Index, der
spaeter zu ``models.py`` dazukommt, entsteht damit auf einer frischen
Installation und auf keiner gewachsenen - also genau dort nicht, wo er
gebraucht wird. Nichts meldet einen Fehler; die Anwendung wird nur langsam.

Am 03.09.2026 belegt: ``models.py`` deklariert ``betreff_kern`` mit
``index=True``, in der gewachsenen ``data-dev/nexmail.db`` fehlte
``ix_nachricht_betreff_kern``.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, _einstellungen, _fehlende_indizes, _kontakt_umbauen, engine, init_db
from app.models import Base, Kontakt


def _indizes(tabelle: str) -> set[str]:
    return {i["name"] for i in inspect(engine).get_indexes(tabelle)}


def test_ein_fehlender_index_wird_beim_start_nachgelegt():
    """Der Fall aus dem Betrieb: Spalte da, Index nicht."""
    assert "ix_nachricht_betreff_kern" in _indizes("nachricht")

    with engine.begin() as verbindung:
        verbindung.execute(text("DROP INDEX ix_nachricht_betreff_kern"))
    assert "ix_nachricht_betreff_kern" not in _indizes("nachricht")

    init_db()

    assert "ix_nachricht_betreff_kern" in _indizes("nachricht"), (
        "Die Schemapflege hat den fehlenden Index nicht nachgelegt."
    )


def test_ein_zweiter_start_legt_nichts_noch_einmal_an():
    """⚠️ **Sonst waere jeder Start ein Indexbau.**

    Der Teilindex ``ix_nachricht_ungelesen`` traegt ein ``sqlite_where``. Wer
    ihn beim Vergleich nicht wiedererkennt, legt ihn bei jedem Hochfahren neu
    an - auf einer grossen Tabelle sind das Sekunden bei jedem Start, und der
    Grund stuende nirgends.
    """
    assert "ix_nachricht_ungelesen" in _indizes("nachricht")
    assert _fehlende_indizes() == [], (
        "Direkt nach init_db() gilt noch etwas als fehlend: "
        + ", ".join(_fehlende_indizes())
    )


def test_jeder_index_aus_dem_modell_steht_wirklich_in_der_datenbank():
    """Die Bodenschwelle: Der Test muss ueberhaupt etwas angesehen haben.

    ⚠️ Ohne die untere Grenze bestuende er auch dann, wenn das Modell
    gar keine Indizes mehr deklariert - und genau dann waere er wertlos.
    """
    gezaehlt = 0
    pruefer = inspect(engine)
    vorhandene = set(pruefer.get_table_names())
    for tabelle in Base.metadata.sorted_tables:
        if tabelle.name not in vorhandene:
            continue
        da = {i["name"] for i in pruefer.get_indexes(tabelle.name)}
        for index in tabelle.indexes:
            gezaehlt += 1
            assert index.name in da, f"{index.name} fehlt in {tabelle.name}."
    assert gezaehlt >= 20, f"Nur {gezaehlt} Indizes angesehen - da stimmt etwas nicht."


def test_das_ankunftsdatum_wird_genau_einmal_nachgetragen(klient, db):
    """⚠️ **Und danach nie wieder über die ganze Tabelle.**

    Die Spalte ``angekommen`` kam nach den ersten Abgleichen dazu; Zeilen davor
    stehen auf NULL, und das Papierkorb-Aufräumen misst daran die Verweildauer.
    Nachgetragen werden muss das, aber genau einmal: Ohne Marke lief bei jedem
    Hochfahren ein ``UPDATE ... WHERE angekommen IS NULL`` über die ganze
    Tabelle, auch wenn es null Zeilen trifft. Es gibt keinen Index auf
    ``angekommen``; gemessen 327 ms bei 250.000 Zeilen, bei jedem Start.
    """
    from app.db import einstellung_lesen

    assert einstellung_lesen(db, "ankunft_nachgetragen") == "1", (
        "Der Start hat die Marke nicht gesetzt — dann läuft der Scan wieder bei jedem Mal."
    )


# --- Der Umbau der Kontakttabelle ------------------------------------------ #
#
# ⚠️ **Der erste Umbau, den die Schemapflege selbst macht.** Bis zum
# 05.09.2026 legte sie nur an. ``kontakt.adresse`` darf seither leer sein, und
# die alte Tabellenbedingung ``UNIQUE (benutzer_id, adresse)`` liesse je
# Benutzer genau EINEN Kontakt ohne Adresse zu. SQLite kann sie nicht loeschen;
# die Tabelle wird neu angelegt und umkopiert.

#: Die Tabelle, wie sie bis zum 04.09.2026 angelegt wurde: ohne die
#: CardDAV-Spalten, mit der Tabellenbedingung auf der Adresse. Woertlich aus
#: einer gewachsenen Entwicklungsdatenbank.
ALTE_KONTAKTTABELLE = (
    "CREATE TABLE kontakt (id INTEGER NOT NULL, benutzer_id VARCHAR(32) NOT NULL, "
    "name VARCHAR(320) NOT NULL, adresse VARCHAR(320) NOT NULL, firma VARCHAR(320) NOT NULL, "
    "telefon VARCHAR(120) NOT NULL, notiz TEXT NOT NULL, quelle VARCHAR(16) NOT NULL, "
    "verwendet INTEGER NOT NULL, angelegt DATETIME NOT NULL, PRIMARY KEY (id), "
    "CONSTRAINT uq_kontakt_adresse UNIQUE (benutzer_id, adresse))"
)


def _alte_kontakttabelle(zeilen: list[tuple[str, str, str]]) -> None:
    with engine.begin() as verbindung:
        verbindung.execute(text("DROP TABLE kontakt"))
        verbindung.execute(text(ALTE_KONTAKTTABELLE))
        verbindung.execute(text("CREATE INDEX ix_kontakt_name ON kontakt (benutzer_id, name)"))
        verbindung.execute(text("CREATE INDEX ix_kontakt_benutzer_id ON kontakt (benutzer_id)"))
        for benutzer, name, adresse in zeilen:
            verbindung.execute(
                text(
                    "INSERT INTO kontakt (benutzer_id, name, adresse, firma, telefon, notiz, "
                    "quelle, verwendet, angelegt) VALUES (:b, :n, :a, '', '', '', 'hand', 3, "
                    "'2026-09-01 10:00:00')"
                ),
                {"b": benutzer, "n": name, "a": adresse},
            )


def _anlage(tabelle: str) -> str:
    with engine.connect() as verbindung:
        return (
            verbindung.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :t"),
                {"t": tabelle},
            ).scalar()
            or ""
        )


def test_die_kontakttabelle_wird_beim_start_umgebaut():
    """⚠️ **Der Fall beim Update.** Die Zeilen bleiben mit ihren Werten, die
    neuen Spalten tragen ihre Vorgabe statt NULL, zwei Kontakte ohne Adresse
    stehen nebeneinander, und eine gefuellte Adresse gibt es weiterhin nur
    einmal."""
    _alte_kontakttabelle([("u1", "Anna", "anna@example.org"), ("u1", "Bernd", "bernd@example.org")])
    assert "UNIQUE" in _anlage("kontakt")

    init_db()

    assert "UNIQUE" not in _anlage("kontakt").upper()
    with SessionLocal() as db:
        alle = db.query(Kontakt).order_by(Kontakt.name).all()
        assert [(k.name, k.adresse, k.verwendet) for k in alle] == [
            ("Anna", "anna@example.org", 3),
            ("Bernd", "bernd@example.org", 3),
        ]
        assert alle[0].roh == "" and alle[0].href == "" and alle[0].schmutzig is False

        db.add_all([Kontakt(benutzer_id="u1", name="Werkstatt"), Kontakt(benutzer_id="u1", name="Oma")])
        db.commit()
        assert db.query(Kontakt).filter(Kontakt.adresse == "").count() == 2

        db.add(Kontakt(benutzer_id="u1", name="Anna II", adresse="anna@example.org"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    # Jeder Index des Modells steht an der neuen Tabelle, nicht an der alten.
    assert {i.name for i in Kontakt.__table__.indexes} <= _indizes("kontakt")


def test_der_umbau_laeuft_nur_einmal():
    """⚠️ Sonst waere jeder Start ein Umbau samt Ruecksetzpunkt, und nach
    fuenf Starts bestuende die Liste der Ruecksetzpunkte nur noch daraus."""
    _alte_kontakttabelle([("u1", "Anna", "anna@example.org")])
    init_db()

    assert _kontakt_umbauen() is False
    with SessionLocal() as db:
        assert db.query(Kontakt).count() == 1


def test_vor_dem_umbau_liegt_ein_ruecksetzpunkt_mit_dem_alten_stand():
    """Geht der Umbau schief, muss der Stand von DAVOR greifbar sein.

    ⚠️ **Mit den Zeilen, nicht nur mit der Tabelle.** Frisch geschriebene
    Zeilen liegen im WAL, und eine Kopie der Hauptdatei allein hat sie nicht;
    ``_sichern`` spielt das Journal vorher ein.
    """
    _alte_kontakttabelle([("u1", "Anna", "anna@example.org")])
    ordner = _einstellungen.data_dir / "sicherungen"
    vorher = set(ordner.glob("*.db")) if ordner.is_dir() else set()

    init_db()

    neu = set(ordner.glob("*.db")) - vorher
    assert len(neu) == 1
    kopie = sqlite3.connect(neu.pop())
    try:
        alt = kopie.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'kontakt'"
        ).fetchone()[0]
        assert "UNIQUE" in alt
        assert kopie.execute("SELECT count(*) FROM kontakt").fetchone()[0] == 1
    finally:
        kopie.close()
