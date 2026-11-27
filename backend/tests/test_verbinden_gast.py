"""V18: was nexmail heute über eine von Hand eingetragene Verbindung mit nextasks und nextime tut, tut es genauso über
eine per „Verbinden“ gemachte (Modul verbinden 0.1.2). Dazu nexfolk (CardDAV-Abgleich mit dem Token der Verbindung statt
eines Gerätepassworts) und, als neues Paar (V19), „Als Dokument an nexpaper“ (``documents.add``). Je Partner dieselbe Nutzung zweimal: über den alten Zugang
(Adresse plus API-Schlüssel, ``TRANSPORT`` der App) und über die Klick-Verbindung (``nexverbinden.call``), gegen einen
Ersatz, der antwortet wie nextasks bzw. nextime und sich merkt, mit welchem Schlüssel gefragt wurde.

Die Verbindung selbst entsteht über die echten Wege beider Seiten (Start, Zustimmung bei der Partner-App der
Vertragstests, Rücksprung); der Ersatz beantwortet nur die ``/api/v1``-Wege, die die Partner-App der Tests nicht hat.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent / "nexverbinden"))

import verbinden_contract as contract  # noqa: E402
from nexverbinden_adapter import Adapter  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import Adressbuch, Anhang, Aufgabenverbindung, Benutzer, Kontakt, Konto, Nachricht, NextimeVerbindung, Ordner  # noqa: E402
from app.services import adressbuchabgleich, aufgabenziele, carddav, nexpaper, nextasks, nextime, nextimeverbindung  # noqa: E402
from test_adressbuchabgleich import BUCH, VOLL, Buchserver, _buch, _karte  # noqa: E402

LISTEN = {"lists": [{"id": "l1", "name": "Einkauf", "space_name": "Zuhause", "writable": True, "sections": []}]}
ICH_TASKS = {"display_name": "Kim", "level": "write", "features": ["tasks", "external_ref"]}


def _antwort(pfad: str) -> Any:
    if pfad.endswith("/me"):
        return ICH_TASKS
    if pfad.endswith("/lists"):
        return LISTEN
    return None


class Ersatz:
    """Antwortet auf ``/api/v1/me`` und ``/api/v1/lists`` und merkt sich die Schlüssel."""

    def __init__(self) -> None:
        self.gesehen: list[tuple[str, str]] = []

    def antworten(self, anfrage: httpx.Request) -> httpx.Response | None:
        pfad = anfrage.url.path
        daten = _antwort(pfad)
        if daten is None:
            return None
        self.gesehen.append((pfad, anfrage.headers.get("authorization", "")))
        return httpx.Response(200, json=daten)


def _welt(tmp_path: Path, partner: str = "nextasks"):
    adapter = Adapter()
    adapter.partner = partner
    ersatz = Ersatz()
    for gefunden in contract.world(contract.package(adapter), adapter, tmp_path):
        original = gefunden._handle

        def handle(anfrage: httpx.Request, original=original, gefunden=gefunden) -> httpx.Response:
            if anfrage.headers.get("host", "") in gefunden.down:
                raise httpx.ConnectError("down", request=anfrage)
            return ersatz.antworten(anfrage) or original(anfrage)

        gefunden._handle = handle  # type: ignore[method-assign]
        contract.package(adapter).reach.TRANSPORT = httpx.MockTransport(handle)
        yield gefunden, ersatz


@pytest.fixture
def welt(tmp_path: Path):
    yield from _welt(tmp_path)


def _person(rolle: str = "kim") -> Benutzer:
    with SessionLocal() as db:
        person = db.query(Benutzer).filter_by(benutzername=rolle).one()
        db.expunge(person)
        return person


def test_nextasks_von_hand_und_per_klick_gleich(welt, monkeypatch):
    gefunden, ersatz = welt
    # Von Hand: Adresse plus Schlüssel, über nexmails eigenen Weg hinaus.
    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(lambda a: ersatz.antworten(a) or httpx.Response(404)))
    hand = nextasks.Zugang(url="https://nextasks.example.com", token="ntk_" + "h" * 40)
    von_hand = nextasks.listen(hand)
    assert ersatz.gesehen[-1] == ("/api/v1/lists", f"Bearer {hand.token}")

    # Per Klick: die Verbindung über die echten Wege, dann dieselbe Liste über ``nexverbinden.call``.
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        v = db.query(Aufgabenverbindung).filter_by(art="nextasks").one()
        zugang = aufgabenziele._nextasks_zugang(v)  # noqa: SLF001
    assert zugang.ueber and not zugang.token
    per_klick = nextasks.listen(zugang)
    assert [(l.id, l.name) for l in per_klick] == [(l.id, l.name) for l in von_hand]
    pfad, schluessel = ersatz.gesehen[-1]
    assert pfad == "/api/v1/lists" and schluessel.startswith("Bearer ") and hand.token not in schluessel
    # Die Karte des Moduls steht danach auf „verbunden“.
    assert gefunden.card("app")["state"] == "connected"


def test_nextasks_nicht_erreichbar_ueber_den_klick_heisst_wie_vorher(welt):
    gefunden, _ = welt
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        zugang = aufgabenziele._nextasks_zugang(db.query(Aufgabenverbindung).filter_by(art="nextasks").one())  # noqa: SLF001
    gefunden.down.add(gefunden.host(gefunden.partner.base))
    with pytest.raises(nextasks.NextasksFehler) as fehler:
        nextasks.listen(zugang)
    assert fehler.value.kennung == "nextasks_nicht_erreichbar"


def test_nextime_zugang_ueber_den_klick(welt, monkeypatch):
    """nextime geht denselben Weg (``nextime._anfrage``); der Zugang trägt ``ueber`` und keinen Schlüssel."""
    gefunden, ersatz = welt
    gesehen: list[tuple[str, str, str]] = []

    def anfragen(partner, konto, methode, pfad, *, params=None, rumpf=None):
        gesehen.append((partner, konto, pfad))
        return httpx.Response(200, json={"ok": True})

    from app.services import verbinden_store

    monkeypatch.setattr(verbinden_store, "anfragen", anfragen)
    zugang = nextime.Zugang(url="https://time.example.com", token="", ueber="konto-1")
    assert nextime.zugang_lesen(nextime.zugang_schreiben(zugang)) == zugang
    nextime._anfrage(zugang, "GET", "me")  # noqa: SLF001
    assert gesehen == [("nextime", "konto-1", "/api/v1/me")]
    with SessionLocal() as db:
        assert db.query(NextimeVerbindung).count() == 0
    assert json.loads(nextime.zugang_schreiben(nextime.Zugang(url="u", token="t")))["token"] == "t"
    _ = nextimeverbindung


# --- nexfolk: dieselben Bücher über CardDAV, einmal mit Gerätepasswort, einmal mit dem Token der Verbindung ---------- #

NEXFOLK_BUCH = "https://nexfolk.example.com/dav/books/kim/familie/"


@pytest.fixture
def nexfolk_welt(tmp_path: Path, monkeypatch):
    server = Buchserver()
    server.karten["/dav/books/kim/familie/k2.vcf"] = ("e2", _karte("k2", "Uli Beispiel", "uli@example.org"))
    server.karten["/dav/vera/buecher/privat/k1.vcf"] = ("e1", VOLL)
    monkeypatch.setattr(adressbuchabgleich, "NEXFOLK_TRANSPORT", server.transport())
    gesucht: list[carddav.Zugang] = []

    def finden(zugang: carddav.Zugang, klient=None):
        gesucht.append(zugang)
        return [carddav.FernBuch(url=NEXFOLK_BUCH, name="Familie")]

    monkeypatch.setattr(carddav, "buecher_finden", finden)
    for gefunden, _ in _welt(tmp_path, "nexfolk"):
        yield gefunden, server, gesucht


def test_nexfolk_per_klick_gleicht_ab_wie_von_hand(nexfolk_welt, monkeypatch):
    gefunden, server, gesucht = nexfolk_welt
    # Von Hand: Adresse, Benutzer und Gerätepasswort (Basic), wie bisher.
    with SessionLocal() as db:
        person = db.query(Benutzer).filter_by(benutzername="kim").one()
        hand = _buch(db, person, "Von Hand", BUCH)
        echt = adressbuchabgleich.zugang

        def mit_transport(b, db=None, **kw):
            z = echt(b, db, **kw)
            z.transport = z.transport or server.transport()
            return z

        monkeypatch.setattr(adressbuchabgleich, "zugang", mit_transport)
        adressbuchabgleich.abgleichen(db, hand)
        assert hand.letzter_fehler == ""
        assert server.koepfe[-1]["authorization"].startswith("Basic ")

    # Per Klick: die Verbindung legt das Buch an, mit dem Konto der Verbindung statt eines Passworts.
    assert gefunden.connect("app").status_code == 200
    assert gesucht and gesucht[0].token and gesucht[0].url == "https://nexfolk.example.com/dav/"
    with SessionLocal() as db:
        klick = db.query(Adressbuch).filter_by(herkunft="nexfolk").one()
        assert klick.ueber and klick.url == NEXFOLK_BUCH and not klick.passwort
        adressbuchabgleich.abgleichen(db, klick)
        assert klick.letzter_fehler == ""
        assert server.koepfe[-1]["authorization"].startswith("Bearer ")
        # Jede Karte landet in ihrem Buch, auf beiden Wegen gleich.
        namen = {(k.adressbuch_id, k.name) for k in db.query(Kontakt).all()}
        assert (hand.id, "Vera Beispiel") in namen and (klick.id, "Uli Beispiel") in namen
    assert gefunden.card("app")["state"] == "connected"


def test_nexfolk_nicht_erreichbar_steht_am_buch_und_in_der_karte(nexfolk_welt, monkeypatch):
    gefunden, _server, _ = nexfolk_welt
    assert gefunden.connect("app").status_code == 200
    monkeypatch.setattr(
        adressbuchabgleich, "NEXFOLK_TRANSPORT", httpx.MockTransport(lambda a: (_ for _ in ()).throw(httpx.ConnectError("x", request=a)))
    )
    with SessionLocal() as db:
        klick = db.query(Adressbuch).filter_by(herkunft="nexfolk").one()
        adressbuchabgleich.abgleichen(db, klick)
        assert klick.letzter_fehler == "caldav_nicht_erreichbar"
    assert gefunden.card("app")["state"] == "unreachable"


# --- nexpaper: ein Anhang als Dokument (V19) ------------------------------------------------------------------------ #


class Papier:
    """Antwortet wie nexpapers ``POST /api/v1/documents`` und merkt sich Schlüssel, Datei und Weg."""

    def __init__(self, erstes_mal_401: bool = False) -> None:
        self.gesehen: list[tuple[str, str, bytes]] = []
        self.abfragen: list[dict[str, str]] = []
        self.erstes_mal_401 = erstes_mal_401

    #: V38: zwei Tresore zum Ablegen, einer nur zum Lesen.
    TRESORE = [
        {"id": 3, "name": "Zuhause", "my_right": "manage"},
        {"id": 7, "name": "Verein", "my_right": "edit"},
        {"id": 9, "name": "Nur lesen", "my_right": "read"},
    ]

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        self.gesehen.append((anfrage.url.path, anfrage.headers.get("authorization", ""), anfrage.read()))
        self.abfragen.append(dict(anfrage.url.params))
        if self.erstes_mal_401 and len(self.gesehen) == 1:
            return httpx.Response(401, json={"detail": {"code": "token_invalid"}})
        if anfrage.method == "GET" and anfrage.url.path == "/api/v1/vaults":
            return httpx.Response(200, json=self.TRESORE)
        return httpx.Response(201, json={"items": [{"filename": "rechnung.pdf", "status": "created"}]})


@pytest.fixture
def nexpaper_welt(tmp_path: Path):
    yield from _welt(tmp_path, "nexpaper")


def _mail_mit_anhang(rolle: str = "kim") -> tuple[int, int]:
    with SessionLocal() as db:
        person = db.query(Benutzer).filter_by(benutzername=rolle).one()
        konto = Konto(
            benutzer_id=person.id, anzeigename="Post", adresse=f"{rolle}@example.com", imap_server="imap.example.com",
            imap_benutzer=rolle, smtp_server="smtp.example.com", smtp_benutzer=rolle,
        )  # fmt: skip
        db.add(konto)
        db.flush()
        ordner = Ordner(konto_id=konto.id, pfad="INBOX", name="Posteingang", rolle="posteingang")
        db.add(ordner)
        db.flush()
        nachricht = Nachricht(benutzer_id=person.id, konto_id=konto.id, ordner_id=ordner.id, uid=1, betreff="Rechnung",
                              von_adresse="laden@example.com", koerper_text="Anbei.")
        db.add(nachricht)
        db.flush()
        blob = get_settings().blob_dir
        blob.mkdir(parents=True, exist_ok=True)
        (blob / ("cd" * 32)).write_bytes(b"%PDF-1.4 rechnung")
        anhang = Anhang(nachricht_id=nachricht.id, dateiname="rechnung.pdf", mime="application/pdf", groesse=17,
                        blob_hash="cd" * 32)
        db.add(anhang)
        db.commit()
        return nachricht.id, anhang.id


def test_ein_anhang_geht_als_dokument_an_nexpaper(nexpaper_welt, monkeypatch):
    gefunden, _ = nexpaper_welt
    papier = Papier()
    monkeypatch.setattr(nexpaper, "TRANSPORT", httpx.MockTransport(papier))
    nachricht, anhang = _mail_mit_anhang()
    klient = gefunden.app.client("owner")
    # Ohne Verbindung sagt nexmail, dass es keine gibt, und nichts geht hinaus.
    antwort = klient.post(f"/api/nachrichten/{nachricht}/anhang/{anhang}/nexpaper")
    assert antwort.status_code == 409 and antwort.json()["detail"] == "nexpaper_nicht_verbunden"
    assert papier.gesehen == []

    assert gefunden.connect("app").status_code == 200
    antwort = klient.post(f"/api/nachrichten/{nachricht}/anhang/{anhang}/nexpaper")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"status": "created"}
    pfad, schluessel, rumpf = papier.gesehen[-1]
    assert pfad == "/api/v1/documents" and schluessel.startswith("Bearer ")
    assert b'filename="rechnung.pdf"' in rumpf and b"%PDF-1.4 rechnung" in rumpf
    assert gefunden.card("app")["state"] == "connected"


def test_nexpaper_nach_einem_401_einmal_mit_frischem_token(nexpaper_welt, monkeypatch):
    gefunden, _ = nexpaper_welt
    papier = Papier(erstes_mal_401=True)
    monkeypatch.setattr(nexpaper, "TRANSPORT", httpx.MockTransport(papier))
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        kim = db.query(Benutzer).filter_by(benutzername="kim").one().id
    assert nexpaper.senden(kim, "rechnung.pdf", b"%PDF")["status"] == "created"
    assert len(papier.gesehen) == 2 and papier.gesehen[0][1] != papier.gesehen[1][1]


def test_eine_fremde_mail_geht_nicht_an_nexpaper(nexpaper_welt, monkeypatch):
    gefunden, _ = nexpaper_welt
    papier = Papier()
    monkeypatch.setattr(nexpaper, "TRANSPORT", httpx.MockTransport(papier))
    nachricht, anhang = _mail_mit_anhang("sam")
    assert gefunden.connect("app").status_code == 200
    assert gefunden.app.client("owner").post(f"/api/nachrichten/{nachricht}/anhang/{anhang}/nexpaper").status_code == 404
    assert papier.gesehen == []


def test_der_tresor_wird_gewaehlt_und_gemerkt(nexpaper_welt, monkeypatch):
    """V38: nexmail nennt die Tresore, in die die Verbindung ablegen darf (nicht die nur lesbaren); der gewählte geht
    als ``vault_id`` mit und ist danach je Konto vorgewählt. Ohne Wahl entscheidet nexpaper wie bisher."""
    gefunden, _ = nexpaper_welt
    papier = Papier()
    monkeypatch.setattr(nexpaper, "TRANSPORT", httpx.MockTransport(papier))
    nachricht, anhang = _mail_mit_anhang()
    klient = gefunden.app.client("owner")
    assert gefunden.connect("app").status_code == 200

    liste = klient.get("/api/nexpaper/tresore")
    assert liste.status_code == 200, liste.text
    assert liste.json() == {"tresore": [{"id": 3, "name": "Zuhause"}, {"id": 7, "name": "Verein"}], "zuletzt": None}

    assert klient.post(f"/api/nachrichten/{nachricht}/anhang/{anhang}/nexpaper", json={"tresor": 7}).status_code == 200
    assert papier.gesehen[-1][0] == "/api/v1/documents" and papier.abfragen[-1] == {"vault_id": "7"}
    assert klient.get("/api/nexpaper/tresore").json()["zuletzt"] == 7

    # Ohne Wahl (ein Tresor oder ältere Seite): kein ``vault_id``, das Gemerkte bleibt.
    assert klient.post(f"/api/nachrichten/{nachricht}/anhang/{anhang}/nexpaper").status_code == 200
    assert "vault_id" not in papier.abfragen[-1]
    assert klient.get("/api/nexpaper/tresore").json()["zuletzt"] == 7
    # Ein anderes Konto hat seine eigene Wahl.
    with SessionLocal() as db:
        from app.routers import nexpaper as wege

        assert wege.zuletzt(db, db.query(Benutzer).filter_by(benutzername="sam").one().id) is None



# --- Frage 11 (verbinden 0.1.4, V-13): endet die Klick-Verbindung, löst nexmail seine Zeilen davon ----------------- #


def test_trennen_loest_die_nextasks_verbindung_per_klick_die_von_hand_bleibt(welt):
    gefunden, _ = welt
    with SessionLocal() as db:
        kim = db.query(Benutzer).filter_by(benutzername="kim").one()
        hand = Aufgabenverbindung(benutzer_id=kim.id, art="todoist", name="Todoist")
        db.add(hand)
        db.commit()
        hand_id = hand.id
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        assert db.query(Aufgabenverbindung).filter_by(art="nextasks").count() == 1
    # In nexmail getrennt: die Zeile der Klick-Verbindung ist weg, die andere bleibt.
    weg = gefunden.app.client("owner").delete(f"{gefunden.pkg.PREFIX}/partners/{gefunden.partner.name}")
    assert weg.status_code == 200, weg.text
    with SessionLocal() as db:
        assert db.query(Aufgabenverbindung).filter_by(art="nextasks").count() == 0
        assert db.get(Aufgabenverbindung, hand_id) is not None


def test_ein_spaeter_von_hand_eingetragener_schluessel_endet_mit_dem_trennen(welt):
    """verbinden 0.2.0 (B9, V56): wer nach dem Klick unter „Von Hand verbinden“ wieder einen Schlüssel eingetragen hat,
    hat eine alte Verbindung neben der Klick-Verbindung; „Trennen“ beendet beide (bis 0.1.18 blieb die von Hand)."""
    from app import crypto

    gefunden, _ = welt
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        v = db.query(Aufgabenverbindung).filter_by(art="nextasks").one()
        zugang = nextasks.Zugang(url="https://nextasks.example.com", token="ntk_" + "h" * 40)
        v.zugang = crypto.verschluesseln(nextasks.zugang_schreiben(zugang), f"aufgabenverbindung:{v.id}:zugang")
        db.commit()
        hand_id = v.id
    assert [a.partner for a in gefunden.app.store.legacy(gefunden.app.account_id("owner"))] == ["nextasks"]
    weg = gefunden.app.client("owner").delete(f"{gefunden.pkg.PREFIX}/partners/{gefunden.partner.name}")
    assert weg.status_code == 200, weg.text
    assert weg.json()["state"] == "none" and weg.json()["legacy"] is None
    with SessionLocal() as db:
        assert db.get(Aufgabenverbindung, hand_id) is None


# --- verbinden 0.2.0 (B9, V56): ``forget_legacy`` beendet die Verbindung von Hand ------------------------------------- #


def _von_hand_nextasks(benutzer: str = "kim") -> tuple[str, int]:
    """Eine nextasks-Verbindung von Hand mit abgewählter Liste, Standard und einer verknüpften Aufgabe."""
    from app import crypto
    from app.models import Aufgabe

    with SessionLocal() as db:
        person = db.query(Benutzer).filter_by(benutzername=benutzer).one()
        v = Aufgabenverbindung(benutzer_id=person.id, art="nextasks", name="nextasks", ohne='["l9"]')
        db.add(v)
        db.flush()
        zugang = nextasks.Zugang(url="https://nextasks.example.com", token="ntk_" + "h" * 40)
        v.zugang = crypto.verschluesseln(nextasks.zugang_schreiben(zugang), f"aufgabenverbindung:{v.id}:zugang")
        aufgabe = Aufgabe(benutzer_id=person.id, betreff="Rechnung zahlen", verbindung_id=v.id, fern_art="nextasks")
        db.add(aufgabe)
        person.aufgaben_standard = f"{v.id}:l1"
        person.aufgaben_eigene = False
        db.commit()
        return v.id, aufgabe.id


def test_per_klick_geht_die_verbindung_von_hand_mit_listen_und_aufgaben_ueber(welt):
    """Gegenprobe ``forget_legacy`` nach dem Klick: dieselbe Zeile läuft jetzt über die Klick-Verbindung, Listenwahl,
    Standard und verknüpfte Aufgaben bleiben; die Karte nennt keine alte Verbindung mehr."""
    from app.models import Aufgabe

    gefunden, _ = welt
    hand_id, aufgabe_id = _von_hand_nextasks()
    konto = gefunden.app.account_id("owner")
    assert [a.partner for a in gefunden.app.store.legacy(konto)] == ["nextasks"]
    assert gefunden.connect("app").status_code == 200
    assert gefunden.app.store.legacy(konto) == []
    with SessionLocal() as db:
        v = db.query(Aufgabenverbindung).filter_by(art="nextasks").one()
        assert v.id == hand_id and v.ohne == '["l9"]'
        zugang = aufgabenziele._nextasks_zugang(v)  # noqa: SLF001
        assert zugang.ueber == konto and zugang.token == ""
        assert db.get(Aufgabe, aufgabe_id).verbindung_id == hand_id
        assert db.get(Benutzer, konto).aufgaben_standard == f"{hand_id}:l1"


def test_trennen_ohne_klick_loest_die_verbindung_von_hand_wie_von_hand(welt):
    """Gegenprobe ``forget_legacy`` ohne Klick-Verbindung: wie „Trennen“ unter Aufgaben-Apps, die Aufgabe behält ihren
    Abzug ohne Verbindung, der Standard fällt, die eigene Liste geht wieder an."""
    from app.models import Aufgabe

    gefunden, _ = welt
    hand_id, aufgabe_id = _von_hand_nextasks()
    weg = gefunden.app.client("owner").delete(f"{gefunden.pkg.PREFIX}/partners/{gefunden.partner.name}")
    assert weg.status_code == 200, weg.text
    with SessionLocal() as db:
        assert db.get(Aufgabenverbindung, hand_id) is None
        aufgabe = db.get(Aufgabe, aufgabe_id)
        assert aufgabe is not None and aufgabe.verbindung_id is None
        person = db.query(Benutzer).filter_by(benutzername="kim").one()
        assert person.aufgaben_standard == "" and person.aufgaben_eigene is True


def test_forget_legacy_nimmt_nur_das_eigene_konto_und_nur_von_hand(welt):
    """Ein anderes Konto behält seine Verbindung von Hand; eine Zeile, die schon über die Klick-Verbindung läuft, bleibt;
    nextime von Hand endet ohne Klick-Verbindung ganz."""
    from app import crypto

    gefunden, _ = welt
    eigen_id, _a = _von_hand_nextasks("kim")
    fremd_id, _b = _von_hand_nextasks("sam")
    with SessionLocal() as db:
        kim = db.query(Benutzer).filter_by(benutzername="kim").one()
        nt = NextimeVerbindung(benutzer_id=kim.id, sichtbar="{}")
        db.add(nt)
        db.flush()
        zugang = nextime.Zugang(url="https://kalender.example.com", token="nt_api_" + "k" * 40)
        nt.zugang = crypto.verschluesseln(nextime.zugang_schreiben(zugang), f"nextime_verbindung:{nt.id}:zugang")
        db.commit()
        nt_id = nt.id
    store = gefunden.app.store
    konto = gefunden.app.account_id("owner")
    assert sorted(a.partner for a in store.legacy(konto)) == ["nextasks", "nextime"]
    store.forget_legacy(konto, "nextime")
    store.forget_legacy(konto, "nexfolk")
    store.commit()
    assert [a.partner for a in store.legacy(konto)] == ["nextasks"]
    with SessionLocal() as db:
        assert db.get(NextimeVerbindung, nt_id) is None
        assert db.get(Aufgabenverbindung, eigen_id) is not None
    store.forget_legacy(konto, "nextasks")
    store.commit()
    assert store.legacy(konto) == []
    with SessionLocal() as db:
        assert db.get(Aufgabenverbindung, eigen_id) is None
        assert db.get(Aufgabenverbindung, fremd_id) is not None
        # Über die Klick-Verbindung (``ueber``) bleibt eine Zeile stehen.
        kim = db.query(Benutzer).filter_by(benutzername="kim").one()
        klick = Aufgabenverbindung(benutzer_id=kim.id, art="nextasks", name="nextasks")
        db.add(klick)
        db.flush()
        ueber = nextasks.Zugang(url="https://nextasks.example.com", token="", ueber=kim.id)
        klick.zugang = crypto.verschluesseln(nextasks.zugang_schreiben(ueber), f"aufgabenverbindung:{klick.id}:zugang")
        db.commit()
        klick_id = klick.id
    store.forget_legacy(konto, "nextasks")
    store.commit()
    with SessionLocal() as db:
        assert db.get(Aufgabenverbindung, klick_id) is not None


def test_beendet_nextasks_die_verbindung_loest_nexmail_sie_auch(welt):
    gefunden, _ = welt
    assert gefunden.connect("app").status_code == 200
    weg = gefunden.partner.client("owner").delete(f"{gefunden.pkg.PREFIX}/partners/nexmail")
    assert weg.status_code == 200, weg.text
    with SessionLocal() as db:
        assert db.query(Aufgabenverbindung).filter_by(art="nextasks").count() == 0


def test_trennen_nimmt_die_buecher_von_nexfolk_mit(nexfolk_welt, monkeypatch):
    gefunden, server, _ = nexfolk_welt
    assert gefunden.connect("app").status_code == 200
    with SessionLocal() as db:
        kim = db.query(Benutzer).filter_by(benutzername="kim").one()
        hand = _buch(db, kim, "Von Hand", BUCH)
        hand_id = hand.id
        assert db.query(Adressbuch).filter_by(herkunft="nexfolk").count() == 1
    weg = gefunden.app.client("owner").delete(f"{gefunden.pkg.PREFIX}/partners/nexfolk")
    assert weg.status_code == 200, weg.text
    with SessionLocal() as db:
        assert db.query(Adressbuch).filter_by(herkunft="nexfolk").count() == 0
        assert db.get(Adressbuch, hand_id) is not None


def test_die_zustimmung_zeigt_das_konto_wie_die_profilzeile(welt, monkeypatch):
    """verbinden 0.1.8 (B1, V43): „Angemeldet als Kim (kim)“ mit dem eigenen Profilbild, unter derselben Adresse wie
    ``profilbildAdresse`` in der Oberfläche (Vorbau, ``?v=`` mit dem Stand), und die lässt sich auch laden."""
    from datetime import UTC, datetime
    from urllib.parse import quote

    gefunden, _ = welt
    kim = _person()
    stand = datetime(2026, 11, 27, 9, 30, tzinfo=UTC)
    with SessionLocal() as db:
        zeile = db.get(Benutzer, kim.id)
        zeile.profilbild, zeile.profilbild_am = b"RIFF-bild", stand
        db.commit()
        stand_text = db.get(Benutzer, kim.id).profilbild_am.isoformat()

    def karte() -> dict:
        params = gefunden.consent_params(gefunden.start("partner").json()["go"])
        gefunden.pkg.connect.BRAKE.forget()
        return gefunden.app.client("owner").get(f"{gefunden.pkg.PREFIX}/consent", params=params).json()["account_card"]

    adresse = f"/api/auth/profilbild/{kim.id}?v={quote(stand_text, safe='')}"
    assert karte() == {"name": "Kim", "username": "kim", "picture": adresse, "color": None}
    assert gefunden.app.client("owner").get(adresse).content == b"RIFF-bild"
    # Unter einem Unterpfad trägt die Adresse den Vorbau, wie in der Oberfläche.
    monkeypatch.setattr(get_settings(), "url_base", "/nexmail")
    assert karte()["picture"] == f"/nexmail{adresse}"
    # Ohne Bild: kein Bild, das Modul zeigt den Buchstaben.
    with SessionLocal() as db:
        zeile = db.get(Benutzer, kim.id)
        zeile.profilbild, zeile.profilbild_am = None, None
        db.commit()
    assert karte()["picture"] is None


def test_nexpaper_im_eigenen_netz_mit_dem_haken_der_verbindung(nexpaper_welt, monkeypatch):
    """Ist nur „Verbindungen ins eigene Netz“ an (nicht die Freigabe für Kalender und Webhooks), geht das Ablegen wie
    das Verbinden; ohne den Haken bleibt eine Adresse im eigenen Netz zu (Fund vor 0.35.0)."""
    from app.services import netzfreigabe, verbinden_store

    monkeypatch.setattr(netzfreigabe, "erlaubt_jetzt", lambda: False)
    adresse = "http://" + ".".join(("172", "16", "0", "20")) + ":8560"
    with SessionLocal() as db:
        verbinden_store.store_fuer(db).set_local_allowed(False)
        db.commit()
    with pytest.raises(nexpaper.NexpaperFehler):
        nexpaper._pruefen(adresse)
    with SessionLocal() as db:
        verbinden_store.store_fuer(db).set_local_allowed(True)
        db.commit()
    nexpaper._pruefen(adresse)
    with pytest.raises(nexpaper.NexpaperFehler):
        nexpaper._pruefen("http://127.0.0.1:8560")
