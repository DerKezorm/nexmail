"""Der KI-Dienst je Benutzer.

⚠️ **Hier geht zum ersten Mal Text nach draußen, den ein Mensch geschrieben
hat.** nexmail blockt sonst Zählpixel, liefert Schriften mit und holt Bilder
über den eigenen Server. Deshalb steht der Schalter ab Werk aus, und deshalb
prüfen die Tests hier vor allem, dass nichts von selbst passiert.

⚠️ **Nichts geht ins echte Netz.** Der Doppelgänger unten ist ein
httpx-Transport; ein Test, der eine echte Adresse anruft, misst die Leitung.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.models import Benutzer
from app.services import anmeldebremse
from app.services import kidienst as dienst
from conftest import einrichten

SCHLUESSEL = "sk-probe-XXXXXXXX"


class Doppelgaenger:
    """Ein Dienst, der antwortet, wie man ihn einstellt."""

    def __init__(self, status=200, koerper=None, listet=True):
        self.status = status
        self.listet = listet
        self.koerper = koerper
        self.anfragen: list[tuple[str, dict]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._antworten)

    def _antworten(self, anfrage: httpx.Request) -> httpx.Response:
        self.anfragen.append((str(anfrage.url), dict(anfrage.headers)))
        if not self.listet:
            return httpx.Response(404)
        if self.status != 200:
            return httpx.Response(self.status)
        if self.koerper is not None:
            return httpx.Response(200, content=json.dumps(self.koerper).encode())
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-opus-5", "display_name": "Claude Opus 5"},
                    {"id": "gpt-4.1-mini"},
                ]
            },
        )


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    return db.query(Benutzer).one()


# --- Die Adresse ---------------------------------------------------------- #


def test_der_schraegstrich_wird_ergaenzt():
    """⚠️ **Ohne ihn fragt ``urljoin`` die falsche Adresse.** Aus
    ``…/v1`` + ``models`` wird ``…/models`` — das ``v1`` fällt weg, und die
    Meldung dazu lautet „nicht gefunden"."""
    assert dienst.adresse_pruefen("https://api.example.com/v1") == "https://api.example.com/v1/"
    assert dienst.adresse_pruefen("https://api.example.com/v1/") == "https://api.example.com/v1/"


def test_nur_http_und_https():
    for schlecht in ("file:///etc/passwd", "ftp://example.com/", "nicht mal eine Adresse"):
        with pytest.raises(dienst.KiFehler):
            dienst.adresse_pruefen(schlecht)


def test_das_eigene_netz_ist_hier_erlaubt():
    """⚠️ **Anders als beim Bildvermittler, und mit Absicht.** Genau dort steht
    Ollama — es zu sperren hieße, den einzigen Weg zu sperren, bei dem nichts
    das Haus verlässt.

    ⚠️ **Keine Adresse aus einem privaten Netz im Test.** Sie stünde im
    öffentlichen Repo, und `test_veroeffentlichung.py` kann eine erfundene
    `192.168.…` nicht von einer echten unterscheiden — genau das ist seine
    Aufgabe. `localhost` und ein `.local`-Name sagen dasselbe und verraten
    nichts."""
    assert dienst.adresse_pruefen("http://localhost:11434/v1") == "http://localhost:11434/v1/"
    assert dienst.adresse_pruefen("http://nas.local:11434/v1") == "http://nas.local:11434/v1/"


# --- Die Modellliste ------------------------------------------------------ #


def test_die_liste_kommt_mit_lesbaren_namen():
    server = Doppelgaenger()
    raus = dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())

    assert [m["id"] for m in raus] == ["claude-opus-5", "gpt-4.1-mini"]
    # ⚠️ Wo der Dienst einen Namen liefert, wird er gezeigt; sonst die Kennung.
    assert raus[0]["name"] == "Claude Opus 5"
    assert raus[1]["name"] == ""


def test_gefragt_wird_unter_models():
    server = Doppelgaenger()
    dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())
    assert server.anfragen[0][0] == "https://api.example.com/v1/models"


def test_beide_kopfzeilen_gehen_mit():
    """⚠️ **Bearer UND x-api-key.** Die Norm will das erste, Anthropic nimmt
    daneben das zweite; beides zu schicken erspart eine Fallunterscheidung nach
    Anbieter — und die wäre eine Anbieterliste im Server."""
    server = Doppelgaenger()
    dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())

    kopf = server.anfragen[0][1]
    assert kopf["authorization"] == f"Bearer {SCHLUESSEL}"
    assert kopf["x-api-key"] == SCHLUESSEL


def test_ohne_schluessel_geht_keine_kopfzeile_mit():
    """Ollama verlangt keinen — eine leere Kopfzeile weisen manche Server ab."""
    server = Doppelgaenger()
    dienst.modelle_holen("http://localhost:11434/v1/", "", server.transport())
    assert "authorization" not in server.anfragen[0][1]


def test_ein_falscher_schluessel_wird_benannt():
    """⚠️ **401 heißt Schlüssel, 404 heißt Adresse.** „Es hat nicht geklappt"
    schickt den Menschen an die falsche Stelle."""
    for code, kennung in (
        (401, "ki_schluessel_abgewiesen"),
        (403, "ki_schluessel_abgewiesen"),
        (429, "ki_zu_viele_anfragen"),
    ):
        server = Doppelgaenger(status=code)
        with pytest.raises(dienst.KiFehler) as f:
            dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())
        assert f.value.kennung == kennung


def test_ein_dienst_ohne_liste_ist_keine_sackgasse():
    """⚠️ Manche Vermittler können ``/models`` nicht. Dann trägt man den Namen
    von Hand ein — dafür braucht es eine eigene Kennung, nicht „ging nicht"."""
    server = Doppelgaenger(listet=False)
    with pytest.raises(dienst.KiFehler) as f:
        dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())
    assert f.value.kennung == "ki_kennt_keine_liste"


def test_eine_unlesbare_antwort_wird_benannt():
    for koerper in ({"modelle": []}, [], {"data": "nichts"}):
        server = Doppelgaenger(koerper=koerper)
        with pytest.raises(dienst.KiFehler) as f:
            dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())
        assert f.value.kennung == "ki_antwort_unlesbar"


def test_eine_leere_liste_ist_kein_erfolg():
    """Bei Ollama heisst das: Es wurde noch kein Modell geholt."""
    server = Doppelgaenger(koerper={"data": []})
    with pytest.raises(dienst.KiFehler) as f:
        dienst.modelle_holen("https://api.example.com/v1/", SCHLUESSEL, server.transport())
    assert f.value.kennung == "ki_keine_modelle"


def test_ein_stummer_dienst_wirft_keine_rohe_ausnahme():
    def stumm(anfrage):
        raise httpx.ConnectError("nichts da")

    with pytest.raises(dienst.KiFehler) as f:
        dienst.modelle_holen(
            "https://api.example.com/v1/", SCHLUESSEL, httpx.MockTransport(stumm)
        )
    assert f.value.kennung == "ki_nicht_erreichbar"


# --- Die Einstellung ------------------------------------------------------ #


def test_ab_werk_ist_alles_aus(person):
    """⚠️ **Die wichtigste Zusicherung dieser Datei.** Wer nexmail installiert,
    schickt nichts an einen fremden Dienst, bis er es selbst einschaltet."""
    stand = dienst.einstellung_lesen(person)
    assert stand == {"aktiv": False, "url": "", "modell": "", "schluessel_da": False}


def test_der_schluessel_liegt_verschluesselt_da(db, person):
    dienst.einstellung_schreiben(db, person, schluessel=SCHLUESSEL)

    assert person.ki_schluessel != SCHLUESSEL
    assert SCHLUESSEL not in person.ki_schluessel
    assert dienst.schluessel_lesen(person) == SCHLUESSEL


def test_der_schluessel_kommt_nie_zurueck(db, person):
    dienst.einstellung_schreiben(db, person, schluessel=SCHLUESSEL)
    stand = dienst.einstellung_lesen(person)

    assert stand["schluessel_da"] is True
    assert SCHLUESSEL not in json.dumps(stand)


def test_nicht_mitgeschickt_heisst_unveraendert(db, person):
    """⚠️ Ohne diese Regel verlöre jeder seinen Schlüssel, der nur das Modell
    wechselt — dieselbe Regel wie beim Passwort und bei den Aliassen."""
    dienst.einstellung_schreiben(
        db, person, url="https://api.example.com/v1/", modell="a", schluessel=SCHLUESSEL
    )
    dienst.einstellung_schreiben(db, person, modell="b")

    assert person.ki_modell == "b"
    assert dienst.schluessel_lesen(person) == SCHLUESSEL
    assert person.ki_url == "https://api.example.com/v1/"


def test_eine_leere_zeichenkette_heisst_weg(db, person):
    dienst.einstellung_schreiben(db, person, schluessel=SCHLUESSEL)
    dienst.einstellung_schreiben(db, person, schluessel="")
    assert person.ki_schluessel == ""


def test_einschalten_geht_nur_mit_vollstaendigem_zugang(db, person):
    """⚠️ Ein Schalter, der „an" steht und beim ersten Umformulieren scheitert,
    ist schlimmer als einer, der sich nicht umlegen lässt."""
    with pytest.raises(dienst.KiFehler) as f:
        dienst.einstellung_schreiben(db, person, aktiv=True)
    assert f.value.kennung == "ki_zugang_unvollstaendig"
    assert person.ki_aktiv is False

    dienst.einstellung_schreiben(db, person, url="https://api.example.com/v1/", modell="a")
    dienst.einstellung_schreiben(db, person, aktiv=True)
    assert person.ki_aktiv is True


def test_ausschalten_geht_immer(db, person):
    """⚠️ Der Weg hinaus darf nie an einer Bedingung hängen."""
    dienst.einstellung_schreiben(db, person, url="https://api.example.com/v1/", modell="a")
    dienst.einstellung_schreiben(db, person, aktiv=True)
    dienst.einstellung_schreiben(db, person, aktiv=False, url="")
    assert person.ki_aktiv is False


# --- Über die Adressen ---------------------------------------------------- #


def test_die_adressen_gehoeren_dem_benutzer(klient, person):
    """⚠️ **Einstellungen des Benutzers, nicht der Verwaltung.** Jeder bringt
    seinen eigenen Zugang mit; der Betreiber gibt nichts vor und sieht nichts."""
    assert klient.get("/api/ki").json() == {
        "aktiv": False,
        "url": "",
        "modell": "",
        "schluessel_da": False,
    }


def test_der_schluessel_steht_in_keiner_antwort(klient, db, person):
    klient.put("/api/ki", json={"url": "https://api.example.com/v1", "schluessel": SCHLUESSEL})

    for antwort in (klient.get("/api/ki"), klient.put("/api/ki", json={"modell": "a"})):
        assert SCHLUESSEL not in antwort.text


def test_ohne_anmeldung_geht_nichts(klient, person):
    klient.post("/api/auth/abmelden")
    assert klient.get("/api/ki").status_code == 401
    assert klient.post("/api/ki/modelle", json={"url": "https://api.example.com/v1"}).status_code == 401


def test_die_bremse_haengt_vor_dem_modellabruf(klient, person, monkeypatch):
    """⚠️ **Der Server ruft hier eine Adresse aus der Anfrage auf.** Ohne
    Bremse liesse sich nexmail als Werkzeug benutzen, um jemand anderen mit
    Anfragen zu belegen."""
    monkeypatch.setattr(
        dienst, "modelle_holen", lambda *a, **k: [{"id": "x", "name": ""}]
    )
    codes = [
        klient.post("/api/ki/modelle", json={"url": "https://api.example.com/v1"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes


def test_der_gespeicherte_schluessel_wird_genommen(klient, db, person, monkeypatch):
    """⚠️ Sonst müsste man ihn zum Modellwechsel neu eintippen — und wer ihn
    nicht zur Hand hat, kommt nicht mehr an seine Liste."""
    klient.put("/api/ki", json={"url": "https://api.example.com/v1", "schluessel": SCHLUESSEL})

    gesehen = []
    monkeypatch.setattr(
        dienst,
        "modelle_holen",
        lambda url, schluessel, *a, **k: gesehen.append(schluessel) or [{"id": "x", "name": ""}],
    )
    klient.post("/api/ki/modelle", json={"url": "https://api.example.com/v1"})

    assert gesehen == [SCHLUESSEL]
