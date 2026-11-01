"""Die Postfachwache und die Meldung an offene Fenster.

⚠️ **Der Doppelgänger spielt Antworten ab, in der Reihenfolge eines Skripts.**
So lässt sich auch das prüfen, was im Betrieb nur nachts passiert: eine Leitung,
die still zugeht, und ein Server, der kein IDLE kann.
"""

from __future__ import annotations

import threading

import pytest

from app.models import Konto
from app.services import abgleich, ereignisse, imap as imapdienst, postfachwache as wache
from app.services import konten
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


class Lauscher:
    """Eine Verbindung im IDLE. ``skript`` sind die Antworten je Blick."""

    def __init__(self, skript=(), kann_idle=True, select_platzt=False):
        self.skript = list(skript)
        self.kann_idle = kann_idle
        self.select_platzt = select_platzt
        self.gewaehlt: list[tuple[str, bool]] = []
        self.idle_an = 0
        self.idle_aus = 0
        self.abgemeldet = 0
        self.blicke = 0

    def capabilities(self):
        return (b"IMAP4REV1", b"IDLE") if self.kann_idle else (b"IMAP4REV1",)

    def select_folder(self, pfad, readonly=False):
        if self.select_platzt:
            raise OSError("weg")
        self.gewaehlt.append((pfad, readonly))

    def idle(self):
        self.idle_an += 1

    def idle_check(self, timeout=None):
        self.blicke += 1
        if not self.skript:
            return []
        schritt = self.skript.pop(0)
        if isinstance(schritt, Exception):
            raise schritt
        return schritt

    def idle_done(self):
        self.idle_aus += 1

    def logout(self):
        self.abgemeldet += 1

    def shutdown(self):
        pass


@pytest.fixture
def wachsam(db, konto):  # noqa: F811
    konto.idle_aktiv = True
    db.commit()
    return konto


@pytest.fixture
def verbinden(monkeypatch):
    """``fuer_konto`` liefert den vorbereiteten Lauscher."""
    halter: dict = {}
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda db, konto: halter["klient"])
    return halter


@pytest.fixture(autouse=True)
def frisch():
    wache._zustaende.clear()
    wache._faeden.clear()
    yield
    for _, halt in list(wache._faeden.values()):
        halt.set()
    wache._zustaende.clear()
    wache._faeden.clear()


@pytest.fixture
def schnell(monkeypatch):
    """Damit „nichts kam" im Test keine fünf Sekunden dauert.

    ⚠️ **Die Prüfung auf eine tote Leitung misst Zeit.** Mit null gäbe es sie
    nicht mehr, und ein Skript mit leeren Antworten kreiste bis zur Grenze.
    """
    monkeypatch.setattr(wache, "ERNEUERN_SEKUNDEN", 0.05)
    monkeypatch.setattr(wache, "LAUSCHEN_SEKUNDEN", 0.0)


def test_neue_post_beendet_das_warten(wachsam, verbinden):
    verbinden["klient"] = klient = Lauscher([[(1, b"EXISTS")], []])

    assert wache._lauschen(wachsam.id, threading.Event()) == wache.NEUE_POST
    assert klient.gewaehlt == [("INBOX", True)], "Lesend, nur der Posteingang."
    assert (klient.idle_an, klient.idle_aus, klient.abgemeldet) == (1, 1, 1)


def test_eine_geaenderte_markierung_ist_keine_neue_post(wachsam, verbinden, schnell):
    """⚠️ **Sonst löste jede eigene Handlung eine Anmeldung aus**: Gelesen
    setzen erzeugt ein ``FETCH`` auf der wartenden Leitung."""
    verbinden["klient"] = Lauscher(
        [[(3, b"FETCH", (b"FLAGS", (rb"\Seen",)))], [(2, b"EXPUNGE")], [(b"OK", b"Still here")]]
    )
    assert wache._lauschen(wachsam.id, threading.Event()) == wache.ERNEUERN


def test_das_warten_wird_erneuert_und_legt_auf(wachsam, verbinden, monkeypatch):
    """⚠️ Nur so fällt eine still gekappte Leitung auf."""
    monkeypatch.setattr(wache, "ERNEUERN_SEKUNDEN", 0.0)
    verbinden["klient"] = klient = Lauscher()

    assert wache._lauschen(wachsam.id, threading.Event()) == wache.ERNEUERN
    assert (klient.idle_aus, klient.abgemeldet) == (1, 1)


def test_eine_geschlossene_leitung_kreist_nicht(wachsam, verbinden):
    """⚠️ **Der teuerste Fehler dieser Datei.** ``idle_check`` schluckt das
    Dateiende und kehrt sofort leer zurück. Ohne die Prüfung liefe die
    Schleife neun Minuten lang mit voller Last."""
    verbinden["klient"] = klient = Lauscher([[]])

    with pytest.raises(wache.LeitungWeg):
        wache._lauschen(wachsam.id, threading.Event())

    assert klient.blicke == 1
    assert klient.abgemeldet == 1


def test_ein_server_ohne_idle_wird_benannt(wachsam, verbinden):
    verbinden["klient"] = klient = Lauscher(kann_idle=False)

    assert wache._lauschen(wachsam.id, threading.Event()) == wache.KEIN_IDLE
    assert klient.idle_an == 0
    assert klient.abgemeldet == 1


def test_abgeschaltet_wird_gar_nicht_erst_verbunden(db, wachsam, monkeypatch):
    wachsam.idle_aktiv = False
    db.commit()

    def nie(*_a):
        raise AssertionError("verbunden")

    monkeypatch.setattr(imapdienst, "fuer_konto", nie)
    assert wache._lauschen(wachsam.id, threading.Event()) == wache.NICHT_MEHR


def test_ein_entferntes_postfach_beendet_die_wache():
    assert wache._lauschen("gibt-es-nicht", threading.Event()) == wache.NICHT_MEHR


def test_das_halten_beendet_das_warten(wachsam, verbinden):
    halt = threading.Event()
    halt.set()
    verbinden["klient"] = klient = Lauscher()

    assert wache._lauschen(wachsam.id, halt) == wache.ERNEUERN
    assert klient.blicke == 0


def test_die_leitung_wird_auch_nach_einem_fehler_geschlossen(wachsam, verbinden):
    verbinden["klient"] = klient = Lauscher(select_platzt=True)

    with pytest.raises(OSError):
        wache._lauschen(wachsam.id, threading.Event())

    assert klient.abgemeldet == 1


# --- Der Faden ------------------------------------------------------------- #


def faden_laufen(konto_id, gruende, monkeypatch):
    """Den Faden mit einem Skript von Gründen laufen lassen, ohne zu warten."""
    halt = threading.Event()
    pausen: list[float] = []
    abgleiche: list[str] = []

    class Uhr:
        def is_set(self):
            return not gruende

        def wait(self, sekunden):
            pausen.append(sekunden)

    def lauschen(_konto_id, _halt):
        grund = gruende.pop(0)
        if isinstance(grund, Exception):
            raise grund
        return grund

    monkeypatch.setattr(wache, "_lauschen", lauschen)
    monkeypatch.setattr(wache, "_abgleichen", abgleiche.append)
    wache._wachen(konto_id, "anna@example.org", Uhr())
    assert not halt.is_set()
    return pausen, abgleiche


def test_neue_post_wird_geholt_und_danach_gewartet(monkeypatch):
    pausen, abgleiche = faden_laufen("k1", [wache.NEUE_POST, wache.NEUE_POST], monkeypatch)

    assert abgleiche == ["k1", "k1"]
    assert pausen == [wache.MINDESTABSTAND_SEKUNDEN] * 2


def test_ein_fehlschlag_verdoppelt_die_pause_bis_zur_grenze(monkeypatch):
    """⚠️ **Ein Server sperrt, wer im Sekundentakt anklopft.**"""
    pausen, _ = faden_laufen("k1", [OSError("weg")] * 8, monkeypatch)

    assert pausen[:3] == [30.0, 60.0, 120.0]
    assert max(pausen) == wache.PAUSE_HOECHSTENS


def test_ein_erfolg_setzt_die_pause_zurueck(monkeypatch):
    pausen, _ = faden_laufen(
        "k1", [OSError("weg"), OSError("weg"), wache.ERNEUERN, OSError("weg")], monkeypatch
    )
    assert pausen == [30.0, 60.0, 30.0]


def test_ein_fehler_beim_holen_toetet_den_faden_nicht(monkeypatch):
    aufrufe = []
    gruende = [wache.NEUE_POST, wache.NICHT_MEHR]

    class Uhr:
        def is_set(self):
            return False

        def wait(self, _sekunden):
            pass

    monkeypatch.setattr(wache, "_lauschen", lambda *_a: gruende.pop(0))

    def platzen(konto_id):
        aufrufe.append(konto_id)
        raise RuntimeError("kaputt")

    monkeypatch.setattr(wache, "_abgleichen", platzen)
    wache._wachen("k1", "anna@example.org", Uhr())

    assert aufrufe == ["k1"]
    assert gruende == [], "Der Faden lief nach dem Fehler weiter."


def test_ohne_idle_endet_der_faden_und_der_grund_bleibt(monkeypatch):
    faden_laufen("k1", [wache.KEIN_IDLE], monkeypatch)
    assert wache.zustand("k1") == wache.KEIN_IDLE


def test_der_zustand_sagt_wenn_die_leitung_weg_ist(monkeypatch):
    gesehen = []

    class Uhr:
        def is_set(self):
            return len(gesehen) > 0

        def wait(self, _sekunden):
            gesehen.append(wache.zustand("k1"))

    def platzen(*_a):
        raise OSError("weg")

    monkeypatch.setattr(wache, "_lauschen", platzen)
    wache._wachen("k1", "anna@example.org", Uhr())

    assert gesehen == [wache.GETRENNT]
    assert wache.zustand("k1") == "", "Am Ende räumt der Faden auf."


# --- Der Rundblick --------------------------------------------------------- #


@pytest.fixture
def stille_faeden(monkeypatch):
    """Fäden, die nur warten, bis man sie anhält."""
    gestartet: list[str] = []

    def warten(konto_id, _adresse, halt):
        gestartet.append(konto_id)
        halt.wait(5)

    monkeypatch.setattr(wache, "_wachen", warten)
    return gestartet


def test_der_rundblick_startet_nur_eingeschaltete(konto, stille_faeden):  # noqa: F811
    wache.rundblick()
    assert wache._faeden == {}, "Ab Werk gibt es keine zweite Verbindung."


def test_der_rundblick_startet_einmal(wachsam, stille_faeden):
    wache.rundblick()
    wache.rundblick()
    assert list(wache._faeden) == [wachsam.id]


def test_der_rundblick_haelt_abgeschaltete_an(db, wachsam, stille_faeden):
    wache.rundblick()
    faden, halt = wache._faeden[wachsam.id]

    wachsam.idle_aktiv = False
    db.commit()
    wache.rundblick()

    assert halt.is_set()
    faden.join(timeout=2)
    wache.rundblick()
    assert wache._faeden == {}


def test_ein_abgeschaltetes_postfach_verliert_den_merker(db, wachsam, stille_faeden):
    """Sonst bliebe „kann kein IDLE" für immer stehen, auch nach einem
    Serverwechsel. Ausschalten und Einschalten ist der Weg zurück."""
    wache._zustaende[wachsam.id] = wache.KEIN_IDLE
    wache.rundblick()
    assert wache._faeden == {}, "Der Merker verhindert den nächsten Versuch."

    wachsam.idle_aktiv = False
    db.commit()
    wache.rundblick()
    assert wache.zustand(wachsam.id) == ""


def test_der_abgeschaltete_takt_schaltet_die_wache_mit_ab():
    """⚠️ In den Tests steht ``NEXMAIL_TAKT_SEKUNDEN`` auf 0, wie bei jedem, der
    meint: nicht dauernd Post holen."""
    wache.starten()
    assert wache._rundblick is None or not wache._rundblick.is_alive()


# --- Das Postfach ---------------------------------------------------------- #


def test_ab_werk_aus_und_aenderbar_ueber_die_adresse(klient, db, konto):  # noqa: F811
    zeile = next(k for k in klient.get("/api/konten").json() if k["id"] == konto.id)
    assert zeile["idle_aktiv"] is False
    assert zeile["idle_zustand"] == ""

    daten = {
        "anzeigename": "Privat",
        "adresse": konto.adresse,
        "imap_server": "imap.example",
        "imap_benutzer": "betreiber",
        "smtp_server": "smtp.example",
        "smtp_benutzer": konto.adresse,
    }
    assert klient.put(f"/api/konten/{konto.id}", json={**daten, "idle_aktiv": True}).json()[
        "idle_aktiv"
    ]
    # ⚠️ Nicht mitgeschickt heisst unverändert, wie beim Passwort.
    assert klient.put(f"/api/konten/{konto.id}", json=daten).json()["idle_aktiv"]


def test_die_wache_sagt_der_oberflaeche_was_sie_tut(klient, konto):  # noqa: F811
    wache._zustaende[konto.id] = wache.KEIN_IDLE
    zeile = next(k for k in klient.get("/api/konten").json() if k["id"] == konto.id)
    assert zeile["idle_zustand"] == "kein_idle"


def test_anlegen_bleibt_ohne_angabe_aus(db, konto):  # noqa: F811
    assert konten.Zugangsdaten.__dataclass_fields__["idle_aktiv"].default is None
    assert db.get(Konto, konto.id).idle_aktiv is False


# --- Die Meldung an offene Fenster ----------------------------------------- #


def test_der_erste_blick_antwortet_sofort(klient, konto):  # noqa: F811
    antwort = klient.get("/api/nachrichten/ereignisse")
    assert antwort.status_code == 200
    assert antwort.json()["stand"] == ereignisse.stand(konto.benutzer_id)


def test_eine_aenderung_kommt_an(klient, konto, monkeypatch):  # noqa: F811
    from app.routers import nachrichten

    monkeypatch.setattr(nachrichten, "EREIGNIS_WARTEN", 0.0)
    vorher = klient.get("/api/nachrichten/ereignisse").json()["stand"]

    assert klient.get(f"/api/nachrichten/ereignisse?seit={vorher}").json()["stand"] == vorher

    ereignisse.melden(konto.benutzer_id)
    assert klient.get(f"/api/nachrichten/ereignisse?seit={vorher}").json()["stand"] == vorher + 1


def test_die_antwort_kommt_vor_dem_ende_des_wartens(klient, konto, monkeypatch):  # noqa: F811
    """⚠️ **Gezählt wird das Warten, nicht das Ergebnis.** Die Antwort wäre auch
    nach acht Sekunden richtig; eben diese Sekunden sind hier der Fehler."""
    from app.routers import nachrichten

    gewartet = []

    async def warten(sekunden):
        gewartet.append(sekunden)

    monkeypatch.setattr(nachrichten, "EREIGNIS_WARTEN", 0.05)
    monkeypatch.setattr(nachrichten.asyncio, "sleep", warten)
    ereignisse.melden(konto.benutzer_id)

    jetzt = ereignisse.stand(konto.benutzer_id)
    assert klient.get(f"/api/nachrichten/ereignisse?seit={jetzt - 1}").json()["stand"] == jetzt
    assert gewartet == []


def test_das_warten_liegt_unter_der_frist_von_docker_stop():
    """⚠️ **Sonst endet jedes Stoppen des Containers hart.** uvicorn wartet auf
    laufende Anfragen, Docker nur zehn Sekunden."""
    from app.routers import nachrichten

    assert nachrichten.EREIGNIS_WARTEN < 10


def test_fremde_zaehler_bleiben_fremd():
    vorher = ereignisse.stand("der-andere")
    ereignisse.melden("der-eine")
    assert ereignisse.stand("der-andere") == vorher


def test_die_adresse_verlangt_eine_anmeldung(zweiter_klient):
    assert zweiter_klient.get("/api/nachrichten/ereignisse").status_code == 401


def test_ein_abgleich_mit_neuer_post_meldet_sich(db, konto, monkeypatch):  # noqa: F811
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Hallo")
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda *_a, **_k: server)

    vorher = ereignisse.stand(konto.benutzer_id)
    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    assert ereignisse.stand(konto.benutzer_id) == vorher + 1


def test_ein_abgleich_ohne_aenderung_bleibt_still(db, konto, monkeypatch):  # noqa: F811
    """⚠️ **Sonst lüde jedes offene Fenster alle zwei Minuten alles neu.**"""
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Hallo")
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda *_a, **_k: server)
    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    vorher = ereignisse.stand(konto.benutzer_id)
    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    assert ereignisse.stand(konto.benutzer_id) == vorher
