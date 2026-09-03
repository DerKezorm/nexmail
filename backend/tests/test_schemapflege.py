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

from sqlalchemy import inspect, text

from app.db import _fehlende_indizes, engine, init_db
from app.models import Base


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
