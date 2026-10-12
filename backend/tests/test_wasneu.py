"""„Was ist neu“: wer es sieht, wann es verschwindet, und dass es zum Release da ist.

⚠️ **Der Release-Stopper steht hier, nicht in der Oberfläche.** Die Version
kennt nur der Server (``app.__version__``); die ``package.json`` der Oberfläche
steht seit jeher auf 0.1.0. Eine Version mit ``.0`` am Ende bringt Neues mit
und muss einen Text haben, in beiden Sprachen, mit allen vier Feldern. Fehlt
einer, stünde nach dem Update kein Banner da, und niemand merkte es.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import __version__
from app.models import Benutzer
from conftest import einrichten

WASNEU = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "wasneu"


def _eintrag_vollstaendig(e: object) -> bool:
    """Dieselbe Prüfung wie ``istEintrag`` in ``lib/wasneu.ts``."""
    if not isinstance(e, dict):
        return False
    text = lambda w: isinstance(w, str) and w.strip() != ""  # noqa: E731
    abschnitte = e.get("sections")
    klein = e.get("small")
    return (
        text(e.get("lead"))
        and isinstance(abschnitte, list)
        and len(abschnitte) > 0
        and all(
            isinstance(a, dict) and text(a.get("title")) and text(a.get("where")) and text(a.get("body"))
            for a in abschnitte
        )
        and text(e.get("smallTitle"))
        and isinstance(klein, list)
        and all(text(k) for k in klein)
    )


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


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_jeder_eintrag_hat_alle_vier_felder(sprache):
    eintraege = json.loads((WASNEU / f"{sprache}.json").read_text(encoding="utf-8"))
    assert eintraege, "Die Datei ist leer; dann zeigt das Fenster nie etwas."
    kaputt = [v for v, e in eintraege.items() if not _eintrag_vollstaendig(e)]
    assert not kaputt, f"Unvollständig, wird lautlos weggelassen: {kaputt}"


def test_eine_version_mit_neuem_bringt_ihren_text_mit():
    """Der Release-Stopper: X.Y.0 braucht einen Eintrag in beiden Sprachen."""
    if not __version__.endswith(".0"):
        pytest.skip(f"{__version__} ist eine Bugfix-Version; dort ist ein Text freiwillig.")
    for sprache in ("de", "en"):
        eintraege = json.loads((WASNEU / f"{sprache}.json").read_text(encoding="utf-8"))
        assert __version__ in eintraege, f"Kein Text für {__version__} in {sprache}.json"
        assert _eintrag_vollstaendig(eintraege[__version__])
