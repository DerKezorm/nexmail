"""Wer SQLites Schreibsperre hält (Issue #9).

⚠️ **Mit echten Sperren, nicht mit nachgestellten Ausnahmen.** Die Wache
hängt an SQLAlchemys Ereignissen; ob sie dort richtig hängt, zeigt nur eine
Datenbank, die wirklich gesperrt ist.
"""

from __future__ import annotations

import logging
import time

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError

from app import sperrwache
from app.db import SessionLocal
from app.models import Einstellung


@pytest.fixture
def kurz(monkeypatch):
    monkeypatch.setattr(sperrwache, "SCHWELLE", 0.2)


def _schreiben(sitzung) -> None:
    """Eine Anweisung, die die Schreibsperre nimmt."""
    sitzung.execute(update(Einstellung).values(wert=Einstellung.wert))
    sitzung.execute(text("INSERT INTO einstellung (schluessel, wert) VALUES ('sperrprobe', '1')"))


def test_eine_lange_sperre_wird_mit_anweisung_und_stelle_gemeldet(klient, kurz, caplog):
    with caplog.at_level(logging.WARNING, logger="nexmail.db"), SessionLocal() as sitzung:
        _schreiben(sitzung)
        time.sleep(0.3)
        sitzung.commit()
    meldungen = [r.getMessage() for r in caplog.records if "held the database" in r.getMessage()]
    assert len(meldungen) == 1, meldungen
    assert "UPDATE einstellung" in meldungen[0]
    assert "test_sperrwache" not in meldungen[0]  # nur nexmails eigener Code zählt als Stelle


def test_eine_kurze_sperre_bleibt_still(klient, kurz, caplog):
    with caplog.at_level(logging.WARNING, logger="nexmail.db"), SessionLocal() as sitzung:
        _schreiben(sitzung)
        sitzung.commit()
    assert not [r for r in caplog.records if "held the database" in r.getMessage()]


def test_lesen_nimmt_keine_sperre(klient, kurz, caplog):
    with caplog.at_level(logging.WARNING, logger="nexmail.db"), SessionLocal() as sitzung:
        sitzung.execute(text("SELECT count(*) FROM einstellung")).scalar()
        time.sleep(0.3)
        sitzung.commit()
    assert not [r for r in caplog.records if "held the database" in r.getMessage()]


def test_auch_zurueckrollen_beendet_die_sperre(klient, kurz, caplog):
    with caplog.at_level(logging.WARNING, logger="nexmail.db"), SessionLocal() as sitzung:
        _schreiben(sitzung)
        time.sleep(0.3)
        sitzung.rollback()
        # Noch in der Sitzung: Das Zurückrollen selbst beendet die Sperre,
        # nicht erst das Schließen.
        assert [r for r in caplog.records if "held the database" in r.getMessage()]
        assert not sperrwache._offen


def test_schliessen_mit_offenem_schreiben_beendet_die_sperre(klient, kurz, caplog):
    with caplog.at_level(logging.WARNING, logger="nexmail.db"):
        sitzung = SessionLocal()
        _schreiben(sitzung)
        time.sleep(0.3)
        sitzung.close()
    assert [r for r in caplog.records if "held the database" in r.getMessage()]
    assert not sperrwache._offen


def test_wer_aufgeben_muss_erfaehrt_wer_die_sperre_haelt(klient, caplog):
    """Der Kern: Neben „database is locked" steht, wer sie hielt."""
    from app.services import apischluessel

    halter = SessionLocal()
    wartender = SessionLocal()
    try:
        # Über nexmails eigenen Code schreiben, damit eine Stelle entsteht,
        # und dort nicht festschreiben: So hält der Halter die Sperre weiter.
        halter.commit = halter.flush
        apischluessel.erlauben(halter, True)
        wartender.execute(text("PRAGMA busy_timeout = 0"))
        with caplog.at_level(logging.WARNING, logger="nexmail.db"), pytest.raises(OperationalError):
            _schreiben(wartender)
    finally:
        wartender.rollback()
        wartender.execute(text("PRAGMA busy_timeout = 10000"))
        wartender.close()
        halter.rollback()
        halter.close()

    meldungen = [r.getMessage() for r in caplog.records if "gave up on a locked database" in r.getMessage()]
    assert len(meldungen) == 1, meldungen
    assert "Holding it for" in meldungen[0]
    assert "INTO einstellung" in meldungen[0] or "UPDATE einstellung" in meldungen[0]
    assert "db.py:" in meldungen[0] and "einstellung_schreiben < services/apischluessel.py:" in meldungen[0]


def test_ohne_halter_sagt_die_meldung_das_auch(klient, caplog, tmp_path):
    """Hält ein fremder Prozess die Sperre, kennt die Wache ihn nicht, und
    sagt genau das, statt zu schweigen."""
    import sqlite3

    from app.db import engine

    fremd = sqlite3.connect(engine.url.database, timeout=0)
    fremd.execute("BEGIN IMMEDIATE")
    wartender = SessionLocal()
    try:
        wartender.execute(text("PRAGMA busy_timeout = 0"))
        with caplog.at_level(logging.WARNING, logger="nexmail.db"), pytest.raises(OperationalError):
            _schreiben(wartender)
    finally:
        fremd.rollback()
        fremd.close()
        wartender.rollback()
        wartender.execute(text("PRAGMA busy_timeout = 10000"))
        wartender.close()

    meldungen = [r.getMessage() for r in caplog.records if "gave up on a locked database" in r.getMessage()]
    assert len(meldungen) == 1, meldungen
    assert "outside nexmail's connections" in meldungen[0]
