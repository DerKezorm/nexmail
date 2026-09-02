"""Wiedervorlage — weglegen, aufwachen, und was dazwischen schiefgehen kann.

⚠️ **Erst der Server, dann der Eintrag.** Die Mail wandert in einen echten
IMAP-Ordner „Wiedervorlage"; scheitert das Verschieben, entsteht kein
Eintrag. Und beim Aufwachen gilt: Findet nexmail die Mail dort nicht mehr,
hat der Mensch entschieden — nur der Merker wird weggeraeumt.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Benutzer, Nachricht, Ordner, Wiedervorlage, utcnow
from app.services import abgleich, wiedervorlage as dienst
from conftest import zweiten_benutzer_anlegen
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture
from test_handeln import Server


class WiedervorlageServer(Server):
    """Der Doppelgaenger, jetzt auch mit CREATE, LIST und STORE −Seen."""

    def __init__(self):
        super().__init__()
        self.abonniert: list[str] = ["INBOX"]
        self.angelegt: list[str] = []

    def list_folders(self, *_a, **_k):
        return [((rb"\HasNoChildren",), b"/", p) for p in self.ordner]

    def list_sub_folders(self, *_a, **_k):
        return [((rb"\HasNoChildren",), b"/", p) for p in self.abonniert]

    def create_folder(self, pfad):
        if pfad in self.ordner:
            raise RuntimeError("Mailbox already exists")
        self.angelegt.append(pfad)
        self.anlegen(pfad)

    def subscribe_folder(self, pfad):
        self.abonniert.append(pfad)

    def folder_exists(self, pfad):
        return pfad in self.ordner

    def remove_flags(self, uids, flags):
        self.protokoll.append(f"STORE -{[f.decode() for f in flags]} {sorted(uids)}")
        for uid in uids:
            if rb"\Seen" in flags:
                self.ordner[self._aktuell]["nachrichten"][uid]["gelesen"] = False


@pytest.fixture
def welt(db, konto, monkeypatch):  # noqa: F811
    """Ein Postfach mit Posteingang und zwei Mails — der Wiedervorlage-Ordner
    existiert absichtlich noch nicht, weder lokal noch auf dem Server."""
    server = WiedervorlageServer()
    server.anlegen("INBOX")
    for uid, betreff in ((1, "Erste"), (2, "Zweite")):
        # Gelesen eingeworfen: Beim Aufwachen muss die Mail wieder ungelesen
        # werden, sonst faellt sie nicht auf.
        server.einwerfen("INBOX", uid, betreff, gelesen=True)
        eintrag = server.ordner["INBOX"]["nachrichten"][uid]
        eintrag["message_id"] = f"<{betreff}@x.example>"
        # Der Exakt-Filter beim Aufwachen prueft die Fundstellen am
        # tatsaechlichen Kopf — der Doppelgaenger liefert ihn ueber die
        # Kopfzeilen, wie ein echter Server auf HEADER.FIELDS.
        eintrag["kopfzeilen"]["Message-ID"] = eintrag["message_id"]

    # ⚠️ ``imapdienst`` ist ueberall dasselbe Modul — einmal gepatcht gilt
    # fuer wiedervorlage, handeln und abgleich zugleich.
    monkeypatch.setattr(dienst.imapdienst, "verbinden", lambda *a, **k: server)
    monkeypatch.setattr(
        dienst.imapdienst, "faehigkeiten", lambda klient: [c.decode() for c in klient.capabilities()]
    )

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)
    return server, konto, posteingang


def _mail(db, betreff: str) -> Nachricht:
    return db.query(Nachricht).filter(Nachricht.betreff == betreff).one()


def _person(db) -> Benutzer:
    return db.query(Benutzer).filter(Benutzer.benutzername == "betreiber").one()


def test_weglegen_legt_ordner_an_verschiebt_und_merkt(db, welt):
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    wann = utcnow() + timedelta(hours=3)

    eintrag = dienst.weglegen(db, person, _mail(db, "Erste").id, wann)

    # Der Ordner ist ein echter auf dem Server — angelegt und abonniert.
    assert server.angelegt == [dienst.ORDNER_NAME]
    assert dienst.ORDNER_NAME in server.abonniert
    # Die Mail liegt dort, nicht mehr im Posteingang.
    assert len(server.ordner[dienst.ORDNER_NAME]["nachrichten"]) == 1
    assert 1 not in server.ordner["INBOX"]["nachrichten"]
    # Lokal nachgezogen: eigene Ordnerzeile, Mail darin sichtbar.
    wv_ordner = db.query(Ordner).filter(Ordner.pfad == dienst.ORDNER_NAME).one()
    dort = db.query(Nachricht).filter(Nachricht.ordner_id == wv_ordner.id).all()
    assert [n.betreff for n in dort] == ["Erste"]
    # Und der Merker weiss, wohin es zurueckgeht.
    assert eintrag.zurueck_pfad == "INBOX"
    assert eintrag.betreff_abzug == "Erste"
    assert eintrag.aufwachen == wann
    assert eintrag.message_id == "<Erste@x.example>"


def test_scheitert_das_verschieben_entsteht_kein_eintrag(db, welt, monkeypatch):
    """⚠️ Ein Merker ohne weggelegte Mail wuerde eine Wiedervorlage behaupten,
    die es nicht gibt — und beim Aufwachen ins Leere greifen."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)

    def kaputt(*_a, **_k):
        raise RuntimeError("NO move rejected")

    monkeypatch.setattr(server, "move", kaputt)

    with pytest.raises(Exception, match="move rejected"):
        dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() + timedelta(hours=1))

    assert db.query(Wiedervorlage).count() == 0
    # Die Mail steht weiter im Posteingang — lokal wie auf dem Server.
    assert _mail(db, "Erste").ordner_id == posteingang.id
    assert 1 in server.ordner["INBOX"]["nachrichten"]


def test_faellig_heisst_zurueck_ungelesen_und_merker_weg(db, welt):
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))

    zurueck = dienst.runde()

    assert zurueck == 1
    db.expire_all()
    # Auf dem Server: wieder im Posteingang, und zwar ungelesen.
    inbox = server.ordner["INBOX"]["nachrichten"]
    assert len(inbox) == 2
    zurueckgelegt = next(
        e for e in inbox.values() if e.get("message_id") == "<Erste@x.example>"
    )
    assert zurueckgelegt["gelesen"] is False
    # Lokal: Zeile im Posteingang, ungelesen; im Wiedervorlage-Ordner nichts.
    mail = _mail(db, "Erste")
    assert mail.ordner_id == posteingang.id
    assert mail.gelesen is False
    wv_ordner = db.query(Ordner).filter(Ordner.pfad == dienst.ORDNER_NAME).one()
    assert db.query(Nachricht).filter(Nachricht.ordner_id == wv_ordner.id).count() == 0
    # Und der Merker ist weg.
    assert db.query(Wiedervorlage).count() == 0


def test_von_hand_entfernte_mail_raeumt_nur_den_merker_weg(db, welt):
    """⚠️ Der Mensch hat entschieden — nexmail sucht der Mail nicht hinterher."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))

    # Ein anderes Geraet hat die Mail aus dem Wiedervorlage-Ordner geschoben.
    server.ordner[dienst.ORDNER_NAME]["nachrichten"].clear()

    zurueck = dienst.runde()

    assert zurueck == 0
    db.expire_all()
    assert db.query(Wiedervorlage).count() == 0
    # Nichts ist im Posteingang aufgetaucht — die Mail liegt, wo der Mensch
    # sie hingelegt hat, und das geht nexmail nichts an.
    assert len(server.ordner["INBOX"]["nachrichten"]) == 1


def test_zweimal_weggelegt_ersetzt_den_eintrag(db, welt):
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    erste_zeit = utcnow() + timedelta(hours=1)
    dienst.weglegen(db, person, _mail(db, "Erste").id, erste_zeit)

    # Die Mail liegt jetzt (mit neuer Zeile) im Wiedervorlage-Ordner.
    zweite_zeit = utcnow() + timedelta(days=2)
    dienst.weglegen(db, person, _mail(db, "Erste").id, zweite_zeit)

    eintraege = db.query(Wiedervorlage).all()
    assert len(eintraege) == 1
    assert eintraege[0].aufwachen == zweite_zeit
    # Der Rueckweg bleibt der urspruengliche — nicht der Wiedervorlage-Ordner.
    assert eintraege[0].zurueck_pfad == "INBOX"


def test_fremde_nachricht_laesst_sich_nicht_weglegen(db, welt):
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    zweiter, _ = zweiten_benutzer_anlegen(db)

    with pytest.raises(dienst.WiedervorlageFehler, match="wiedervorlage_nachricht_fehlt"):
        dienst.weglegen(db, zweiter, _mail(db, "Erste").id, utcnow() + timedelta(hours=1))

    assert db.query(Wiedervorlage).count() == 0
    # Und die Liste des Zweiten bleibt leer, auch wenn der Erste etwas weglegt.
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() + timedelta(hours=1))
    assert dienst.alle(db, zweiter) == []
    assert len(dienst.alle(db, person)) == 1


def test_die_adressen_haengen_am_router(db, welt, klient):
    """Die Oberflaeche holt Zahl und Marken ueber /api/nachrichten/wiedervorlage."""
    server, konto, posteingang = welt  # noqa: F811
    mail = _mail(db, "Zweite")

    antwort = klient.post(
        "/api/nachrichten/wiedervorlage",
        json={"nachricht_id": mail.id, "aufwachen": "2030-01-01T08:00:00Z"},
    )
    assert antwort.status_code == 201, antwort.text

    liste = klient.get("/api/nachrichten/wiedervorlage")
    assert liste.status_code == 200
    zeilen = liste.json()
    assert len(zeilen) == 1
    assert zeilen[0]["zurueck_pfad"] == "INBOX"
    assert zeilen[0]["betreff"] == "Zweite"
    assert zeilen[0]["konto_id"] == konto.id
    # Die aktuelle Zeile der Mail im Wiedervorlage-Ordner ist nachgeschlagen —
    # daran haengt die Aufwach-Marke in der Liste.
    db.expire_all()
    assert zeilen[0]["nachricht_id"] == _mail(db, "Zweite").id


def test_ein_voruebergehender_fehler_loescht_den_merker_nicht(db, welt, monkeypatch):
    """⚠️ Ein Timeout oder ein BAD auf das SEARCH ist keine Entscheidung des
    Menschen — der Merker bleibt liegen und bekommt einen Rueckstau, statt als
    „von Hand verschoben" geloescht zu werden."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))

    heil = server.search

    def klemmt(*_a, **_k):
        raise RuntimeError("BAD temporary failure")

    monkeypatch.setattr(server, "search", klemmt)
    assert dienst.runde() == 0

    db.expire_all()
    eintrag = db.query(Wiedervorlage).one()
    assert eintrag.fehlversuche == 1
    assert eintrag.naechster_versuch is not None
    # Die Mail liegt unangetastet im Wiedervorlage-Ordner.
    assert len(server.ordner[dienst.ORDNER_NAME]["nachrichten"]) == 1

    # ⚠️ Rueckstau: Die naechste Runde macht NICHT sofort die naechste
    # frische IMAP-Anmeldung — sonst waeren es 1440 am Tag.
    versuche = {"n": 0}

    def zaehlt(*a, **k):
        versuche["n"] += 1
        return heil(*a, **k)

    monkeypatch.setattr(server, "search", zaehlt)
    assert dienst.runde() == 0
    assert versuche["n"] == 0

    # Nach Ablauf des Rueckstaus kommt die Mail zurueck.
    eintrag.naechster_versuch = utcnow() - timedelta(seconds=1)
    db.commit()
    assert dienst.runde() == 1
    db.expire_all()
    assert db.query(Wiedervorlage).count() == 0


def test_geloeschter_ordner_raeumt_nur_den_merker_weg(db, welt):
    """Der ganze Wiedervorlage-Ordner wurde von einem anderen Client
    geloescht — dann ist auch die Mail nicht mehr dort."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))

    del server.ordner[dienst.ORDNER_NAME]

    assert dienst.runde() == 0
    db.expire_all()
    assert db.query(Wiedervorlage).count() == 0


def test_ein_abbruch_mitten_im_aufwecken_committet_keine_reste(db, welt, monkeypatch):
    """⚠️ Reisst die Verbindung mitten im Nachziehen ab, liegen halbe Zeilen
    in der geteilten Session — der Commit des naechsten Eintrags darf sie
    nicht stillschweigend festschreiben."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=2))
    dienst.weglegen(db, person, _mail(db, "Zweite").id, utcnow() - timedelta(minutes=1))

    echt = dienst._aufwecken

    def halb(db_, eintrag):
        if eintrag.message_id == "<Erste@x.example>":
            # Eine halb geschriebene AEnderung liegt in der Session, dann
            # reisst die Verbindung ab.
            eintrag.betreff_abzug = "halb geschrieben"
            raise RuntimeError("connection lost mid-sync")
        return echt(db_, eintrag)

    monkeypatch.setattr(dienst, "_aufwecken", halb)

    assert dienst.runde() == 1  # nur „Zweite" kam durch

    db.expire_all()
    uebrig = db.query(Wiedervorlage).one()
    assert uebrig.message_id == "<Erste@x.example>"
    # ⚠️ Ohne rollback haette ein spaeterer Commit die halbe Zeile
    # festgeschrieben.
    assert uebrig.betreff_abzug == "Erste"
    assert uebrig.fehlversuche == 1


def test_die_suche_trifft_nur_die_genaue_kennung(db, welt):
    """⚠️ ``SEARCH HEADER`` ist ein Teilstring-Vergleich — eine Mail, deren
    Kennung die gesuchte ENTHAELT, darf nicht mitwandern."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))

    # Ein anderes Geraet legt eine zweite Mail in den Ordner, deren Kennung
    # die der weggelegten als Teilstring enthaelt.
    server.einwerfen(dienst.ORDNER_NAME, 41, "Doppelgaenger", gelesen=True)
    doppel = server.ordner[dienst.ORDNER_NAME]["nachrichten"][41]
    doppel["message_id"] = "x<Erste@x.example>y"
    doppel["kopfzeilen"]["Message-ID"] = doppel["message_id"]

    assert dienst.runde() == 1

    # Nur die weggelegte Mail ist zurueck — der Doppelgaenger blieb liegen.
    uebrig = list(server.ordner[dienst.ORDNER_NAME]["nachrichten"].values())
    assert [e["betreff"] for e in uebrig] == ["Doppelgaenger"]
    inbox = server.ordner["INBOX"]["nachrichten"].values()
    assert sorted(e["betreff"] for e in inbox) == ["Erste", "Zweite"]


def test_geloeschter_rueckweg_faellt_auf_den_posteingang(db, welt):
    """⚠️ Ein geloeschter oder umbenannter Rueckkehr-Ordner darf den Eintrag
    nicht unsterblich machen — die Mail geht dann in den Posteingang."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    eintrag = dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))
    eintrag.zurueck_pfad = "Verschwunden"
    db.commit()

    assert dienst.runde() == 1
    db.expire_all()
    assert db.query(Wiedervorlage).count() == 0
    # Die Mail liegt im Posteingang, nicht im Nirgendwo.
    betreffs = [e["betreff"] for e in server.ordner["INBOX"]["nachrichten"].values()]
    assert sorted(betreffs) == ["Erste", "Zweite"]


def test_die_marke_haengt_an_der_kopie_im_wiedervorlage_ordner(db, welt):
    """⚠️ Bei Duplikaten (dieselbe Message-ID in zwei Ordnern) muss die
    Aufwach-Marke an der Kopie im Wiedervorlage-Ordner haengen."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    dienst.weglegen(db, person, _mail(db, "Zweite").id, utcnow() + timedelta(hours=1))

    # Ein Duplikat mit derselben Kennung liegt (mit AELTERER Zeilennummer)
    # im Posteingang — etwa die an sich selbst gesendete Mail.
    erste = _mail(db, "Erste")
    erste.message_id = "<Zweite@x.example>"
    db.commit()

    sichten = dienst.alle(db, person)
    assert len(sichten) == 1
    wv_ordner = db.query(Ordner).filter(Ordner.pfad == dienst.ORDNER_NAME).one()
    zeile = db.get(Nachricht, sichten[0].nachricht_id)
    assert zeile.ordner_id == wv_ordner.id


def test_eine_unbrauchbare_kennung_wird_beim_weglegen_abgewiesen(db, welt):
    """⚠️ Nicht-ASCII (U+FFFD aus dem Abgleich) oder rohe Klammern wuerfen
    das IMAP-SEARCH beim Aufwachen um — das wird beim Weglegen gesagt, nicht
    spaeter still verschluckt."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    mail = _mail(db, "Erste")

    for kaputt in ("<a�b@x.example>", "<a(b@x.example>", '<a"b@x.example>'):
        mail.message_id = kaputt
        db.commit()
        with pytest.raises(dienst.WiedervorlageFehler, match="wiedervorlage_kennung_unbrauchbar"):
            dienst.weglegen(db, person, mail.id, utcnow() + timedelta(hours=1))
    assert db.query(Wiedervorlage).count() == 0


def test_der_merker_laesst_sich_von_hand_entfernen(db, welt, klient):
    """Die DELETE-Route: Der eine Ausweg, wenn das Aufwecken dauerhaft
    scheitert. Nur der Merker faellt — die Mail bleibt, wo sie liegt."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    eintrag = dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() + timedelta(hours=1))

    antwort = klient.delete(f"/api/nachrichten/wiedervorlage/{eintrag.id}")
    assert antwort.status_code == 204, antwort.text

    db.expire_all()
    assert db.query(Wiedervorlage).count() == 0
    # Die Mail liegt weiter im Wiedervorlage-Ordner — niemand hat sie bewegt.
    assert len(server.ordner[dienst.ORDNER_NAME]["nachrichten"]) == 1


def test_fremde_merker_lassen_sich_nicht_entfernen(db, welt):
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    eintrag = dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() + timedelta(hours=1))
    zweiter, _ = zweiten_benutzer_anlegen(db)

    with pytest.raises(dienst.WiedervorlageFehler, match="wiedervorlage_eintrag_fehlt"):
        dienst.entfernen(db, zweiter, eintrag.id)
    assert db.query(Wiedervorlage).count() == 1


def test_regeln_fassen_den_wiedervorlage_ordner_nicht_an(db, welt, monkeypatch):
    """⚠️ Eine von einem anderen Geraet in den Wiedervorlage-Ordner gelegte
    Mail ist fuer den naechsten Abgleich „neu" — eine Regel darf die bewusste
    Ablage nicht wieder herausschieben."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    # Einmal weglegen und aufwecken, damit der Ordner existiert und
    # abonniert ist.
    dienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))
    dienst.runde()
    # ⚠️ runde() lief auf einer EIGENEN Session; die Test-Session beendet
    # ihre alte Lese-Transaktion, sonst sieht der Abgleich einen veralteten
    # Stand und legt Zeilen doppelt an.
    db.rollback()
    db.expire_all()

    # Ein anderes Geraet legt eine Mail direkt hinein, eine zweite kommt
    # regulaer im Posteingang an.
    server.einwerfen(dienst.ORDNER_NAME, 51, "Von woanders")
    server.einwerfen("INBOX", 52, "Frisch")

    gerufen: list[int] = []
    monkeypatch.setattr(
        abgleich, "_regeln_laufen_lassen", lambda db_, konto_, ks: gerufen.extend(ks)
    )
    abgleich.konto_abgleichen(db, konto)

    db.expire_all()
    wv_ordner = db.query(Ordner).filter(Ordner.pfad == dienst.ORDNER_NAME).one()
    abgelegt = (
        db.query(Nachricht)
        .filter(Nachricht.ordner_id == wv_ordner.id, Nachricht.betreff == "Von woanders")
        .one()
    )
    frisch = db.query(Nachricht).filter(Nachricht.betreff == "Frisch").one()
    # Die frische Posteingangs-Mail laeuft durch die Regeln ...
    assert frisch.id in gerufen
    # ... die bewusste Ablage nicht.
    assert abgelegt.id not in gerufen


def test_ohne_message_id_gibt_es_eine_kennung(db, welt):
    """⚠️ Ohne Message-ID gibt es keinen Weg zurueck — als KENNUNG gemeldet,
    kein deutscher Satz als detail."""
    server, konto, posteingang = welt  # noqa: F811
    person = _person(db)
    mail = _mail(db, "Erste")
    mail.message_id = ""
    db.commit()

    with pytest.raises(dienst.WiedervorlageFehler, match="wiedervorlage_ohne_kennung"):
        dienst.weglegen(db, person, mail.id, utcnow() + timedelta(hours=1))
    assert db.query(Wiedervorlage).count() == 0
