"""Die Ordnerliste wird bei jedem Abgleich nachgezogen.

⚠️ **Bis zum 18.09.2026 las nexmail sie nur beim Anlegen des Postfachs** und
wenn hier ein Ordner angelegt, umbenannt oder entfernt wurde. Ein Ordner vom
Telefon tauchte nie auf; einer, der dort gelöscht wurde, blieb stehen.

⚠️ **Der teure Fehler ist hier das Löschen auf Zuruf.** Übernehmen heißt auch
wegwerfen, samt Nachrichten. Eine Antwort, die nicht stimmt (leer, ohne
Posteingang, gar keine), darf deshalb nichts kosten; jeder dieser Fälle hat
seinen Test, und jeder läuft mit einem Ordner, der dabei verloren ginge.
"""

from __future__ import annotations

import pytest

from app.models import Nachricht, Ordner
from app.services import abgleich
from app.services import ordner as ordnerdienst
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


@pytest.fixture
def server(monkeypatch):
    s = FalscherServer()
    s.anlegen("INBOX")
    s.einwerfen("INBOX", 1, "Kommt an")
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: s)
    return s


def _pfade(db, konto) -> set[str]:  # noqa: F811
    db.refresh(konto)
    return {o.pfad for o in konto.ordner}


def _ablage_mit_post(db, konto, server) -> None:  # noqa: F811
    """Ein zweiter Ordner mit einer Nachricht, beim Server und hier."""
    server.anlegen("Ablage")
    server.einwerfen("Ablage", 7, "Liegt in der Ablage")
    abgleich.konto_abgleichen(db, konto)
    assert "Ablage" in _pfade(db, konto)
    assert db.query(Nachricht).count() == 2


def test_ein_ordner_vom_telefon_taucht_auf(db, konto, server):  # noqa: F811
    server.anlegen("Vom Telefon")
    server.einwerfen("Vom Telefon", 3, "Dort abgelegt")

    abgleich.konto_abgleichen(db, konto)

    assert "Vom Telefon" in _pfade(db, konto)
    # Und er wird in derselben Runde schon abgeglichen, nicht erst in der
    # nächsten: Die Liste wird VOR der Schleife nachgezogen.
    betreffs = {n.betreff for n in db.query(Nachricht).all()}
    assert betreffs == {"Kommt an", "Dort abgelegt"}


def test_auch_der_takt_zieht_nach(db, konto, server):  # noqa: F811
    """Der Takt gleicht nur den Posteingang ab. Die Liste zieht er trotzdem
    nach; sonst erschiene ein neuer Ordner erst nach „Aktualisieren"."""
    server.anlegen("Vom Telefon")

    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    assert "Vom Telefon" in _pfade(db, konto)


def test_die_rolle_kommt_mit(db, konto, server):  # noqa: F811
    server.anlegen("Ablage 2019", kennzeichen=(rb"\Archive",))
    server.anlegen("Deleted")

    abgleich.konto_abgleichen(db, konto)

    db.refresh(konto)
    rollen = {o.pfad: o.rolle for o in konto.ordner}
    assert rollen == {"INBOX": "posteingang", "Ablage 2019": "archiv", "Deleted": "papierkorb"}


def test_ein_woanders_geloeschter_ordner_verschwindet(db, konto, server):  # noqa: F811
    _ablage_mit_post(db, konto, server)

    del server.ordner["Ablage"]
    abgleich.konto_abgleichen(db, konto)

    assert _pfade(db, konto) == {"INBOX"}
    assert {n.betreff for n in db.query(Nachricht).all()} == {"Kommt an"}


def test_eine_zuweisung_von_hand_uebersteht_den_takt(db, konto, server):  # noqa: F811
    """⚠️ Ohne das hätte jeder Takt die Rolle zurückgesetzt, alle zwei
    Minuten."""
    server.anlegen("Weg damit")
    abgleich.konto_abgleichen(db, konto)
    db.refresh(konto)
    ziel = next(o for o in konto.ordner if o.pfad == "Weg damit")
    ordnerdienst.rolle_zuweisen(db, konto, ziel, "papierkorb")

    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    db.refresh(konto)
    assert {o.pfad: o.rolle for o in konto.ordner}["Weg damit"] == "papierkorb"


# --- Was nichts kosten darf ------------------------------------------------ #


def test_eine_leere_liste_loescht_nichts(db, konto, server):  # noqa: F811
    _ablage_mit_post(db, konto, server)

    server.liste_leer = True
    abgleich.konto_abgleichen(db, konto)

    assert _pfade(db, konto) == {"INBOX", "Ablage"}
    assert db.query(Nachricht).count() == 2


def test_eine_liste_ohne_posteingang_loescht_nichts(db, konto, server):  # noqa: F811
    """``INBOX`` gibt es auf jedem Server. Fehlt er, stimmt die Antwort nicht."""
    _ablage_mit_post(db, konto, server)

    echt = server.list_folders
    server.list_folders = lambda: [z for z in echt() if z[2] == "Entwurf von gestern"]
    abgleich.konto_abgleichen(db, konto)

    assert _pfade(db, konto) == {"INBOX", "Ablage"}
    assert db.query(Nachricht).count() == 2


def test_ein_klemmendes_list_haelt_den_abgleich_nicht_auf(db, konto, server):  # noqa: F811
    """Die Liste ist Beiwerk, die Post ist der Zweck."""
    _ablage_mit_post(db, konto, server)
    server.einwerfen("INBOX", 2, "Trotzdem angekommen")

    server.liste_klemmt = True
    abgleich.konto_abgleichen(db, konto)

    assert _pfade(db, konto) == {"INBOX", "Ablage"}
    assert "Trotzdem angekommen" in {n.betreff for n in db.query(Nachricht).all()}


def test_ein_abbestellter_ordner_bleibt_in_der_datenbank(db, konto, server):  # noqa: F811
    """Abbestellen ist nicht löschen: Die Zeile bleibt, die Oberfläche blendet
    sie aus, und abgeglichen wird sie nicht mehr."""
    _ablage_mit_post(db, konto, server)

    server.list_sub_folders = lambda: [((), b"/", "INBOX")]
    abgleich.konto_abgleichen(db, konto)

    db.refresh(konto)
    ablage = next(o for o in konto.ordner if o.pfad == "Ablage")
    assert ablage.abonniert is False
    assert db.query(Nachricht).count() == 2
    assert isinstance(ablage, Ordner)
