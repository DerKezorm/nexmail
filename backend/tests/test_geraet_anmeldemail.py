"""geraete 0.1.1 (G50): die Mail „Neue Anmeldung“ für ein neues iPhone, iPad oder einen Mac nennt das Gerät
(„„Kims iPhone“ (iPhone 16 Pro)“) über ``nexgeraete.notices.letter``, nicht einen Browser aus einem User-Agent."""

from __future__ import annotations

from conftest import einrichten

from app.models import Benutzer
from app.services import geraete_store, kontenpost, post_store
from app.vendor.nexgeraete import Device


def _neues_geraet(klient, db, monkeypatch, *, will: bool) -> list:
    einrichten(klient)
    person = db.query(Benutzer).one()
    person.kontaktadresse = "kim@example.com"
    person.mail_neue_anmeldung = will
    db.commit()
    briefe: list = []
    monkeypatch.setattr(kontenpost, "mail_moeglich", lambda _db: True)
    monkeypatch.setattr(post_store, "einreihen", lambda _db, brief: briefe.append(brief))
    inhaber = geraete_store.store_fuer(db).holder(person.id)
    geraet = Device(id="g1", account_id=person.id, name="Kims iPhone", kind="ios", model="iPhone 16 Pro")
    geraete_store.nach_kopplung(inhaber, geraet)
    return briefe


def test_die_mail_nennt_das_geraet_und_fuehrt_zur_seite_sicherheit(klient, db, monkeypatch):
    briefe = _neues_geraet(klient, db, monkeypatch, will=True)
    assert len(briefe) == 1
    brief = briefe[0]
    assert brief.to == "kim@example.com"
    # In der Sprache des Kontos (hier Englisch): “Kims iPhone” (iPhone 16 Pro).
    assert "Kims iPhone" in brief.text and "(iPhone 16 Pro)" in brief.text
    assert kontenpost.SEITE_SICHERHEIT in brief.text


def test_ohne_den_schalter_geht_keine_mail(klient, db, monkeypatch):
    assert _neues_geraet(klient, db, monkeypatch, will=False) == []
