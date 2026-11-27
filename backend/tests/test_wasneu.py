"""„Was ist neu“ in nexmail: wer es sieht und wann es verschwindet.

Seit 0.35.0 über das Modul wasneu 0.1.0. Die Form der Texte, der Release-Stopper (eine x.y.0 bringt ihren Text in
beiden Sprachen mit) und das Einfrieren veröffentlichter Texte prüft der Wächter
``tests/nexwasneu/test_nexwasneu_texts.py``, die neuen Wege die Vertragstests daneben. Hier bleibt, was nur nexmail hat:
das Feld ``wasneu_gesehen`` in ``/api/auth/ich``, der Weg von vorher und die Konten über einen Anbieter.
"""

from __future__ import annotations

from app import __version__
from app.models import Benutzer
from conftest import einrichten


def test_ein_neues_konto_hat_die_laufende_version_schon_gesehen(klient):
    """Eine frische Installation begrüßt nicht mit Neuigkeiten."""
    einrichten(klient)
    ich = klient.get("/api/auth/ich").json()
    assert ich["version"] == __version__
    assert ich["wasneu_gesehen"] == __version__


def test_ein_konto_von_vor_dem_update_sieht_es_bis_zum_wegklicken(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    # ⚠️ Ein Stand, der sicher NICHT die laufende Version ist. Mit "0.23.4"
    # stand hier zuerst genau die laufende, und der Test bestand auch dann,
    # wenn nichts gespeichert wurde.
    person.wasneu_gesehen = "0.0.1"
    db.commit()
    assert __version__ != "0.0.1"  # Bodenschwelle
    assert klient.get("/api/auth/ich").json()["wasneu_gesehen"] == "0.0.1"

    antwort = klient.post("/api/auth/ich/wasneu-gesehen")

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wasneu_gesehen"] == __version__
    # In eigener Anfrage: Die Antwort derselben sieht auch Ungeschriebenes.
    assert klient.get("/api/auth/ich").json()["wasneu_gesehen"] == __version__


def test_gesehen_melden_braucht_eine_anmeldung(klient):
    einrichten(klient)
    klient.cookies.clear()
    assert klient.post("/api/auth/ich/wasneu-gesehen").status_code == 401


def test_ein_konto_ueber_einen_anbieter_startet_ebenso_auf_der_laufenden_version(db):
    from app.services.oidc_store import SqlStore

    nummer = SqlStore(db).create_account("neu-ueber-anbieter", invite=None, email=None)
    db.commit()
    person = db.query(Benutzer).filter(Benutzer.nummer == nummer).one()
    assert person.wasneu_gesehen == __version__


def test_der_neue_weg_und_der_alte_merken_dasselbe(klient, db):
    """Die Oberfläche fragt seit 0.35.0 ``/api/whats-new``; beide Wege setzen dasselbe Feld."""
    einrichten(klient)
    person = db.query(Benutzer).one()
    person.wasneu_gesehen = "0.0.1"
    db.commit()

    stand = klient.get("/api/whats-new").json()
    assert (stand["version"], stand["seen"]) == (__version__, "0.0.1")

    assert klient.post("/api/whats-new/seen").json() == {"seen": __version__}
    assert klient.get("/api/auth/ich").json()["wasneu_gesehen"] == __version__
