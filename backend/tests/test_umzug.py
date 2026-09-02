"""Der Umzug: eine mbox einspielen, einen Ordner ausgeben.

⚠️ **Die Wiederholung ist hier die eigentliche Gefahr.** Ein Import bricht ab —
Netz weg, Browser zu, Container neu — und der zweite Anlauf legt ohne
Vorkehrung alles ein zweites Mal ab. Ein doppelter Posteingang mit
zehntausend Mails ist von Hand nicht mehr aufzuräumen.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from app.models import Konto, Nachricht, Ordner
from app.services import (
    abgleich,
    austausch,
    imap as imapdienst,
    konten as kontendienst,
)
from test_abgleich import FalscherServer


class Importserver(FalscherServer):
    """Ein Server, der anhängen kann — und auf Wunsch ablehnt."""

    def __init__(self):
        super().__init__()
        self.angehaengt: list[tuple[str, bytes, tuple, object]] = []
        #: Betreffs, die dieser Server nicht annimmt. Ein echter Server lehnt
        #: ab, was seine Quote sprengt oder was sein Filter nicht mag.
        self.lehnt_ab: set[str] = set()
        #: Wahr: gar nichts geht mehr durch — die gekappte Verbindung.
        self.tot = False
        #: Jede Feldliste, die je abgefragt wurde. Der Wächter über ``PEEK``.
        self.gefragt: list[list[str]] = []

    def append(self, pfad, roh, flags=None, datum=None):
        betreff = austausch._kopf(roh).decode("utf-8", "replace")
        if self.tot:
            raise OSError("connection reset by peer")
        for wort in self.lehnt_ab:
            if wort in betreff:
                raise OSError("over quota")
        self.angehaengt.append((pfad, roh, tuple(flags or ()), datum))
        uid = max(self.ordner[pfad]["nachrichten"], default=0) + 1
        einwerfen(self, pfad, uid, roh, gelesen=any(b"Seen" in f for f in (flags or ())))

    def fetch(self, uids, felder):
        self.gefragt.append([f.decode() if isinstance(f, bytes) else str(f) for f in felder])
        return super().fetch(uids, felder)


def _roh(kennung: str, betreff: str, datum: str = "Thu, 5 Mar 2026 09:00:00 +0000") -> bytes:
    return (
        f"Message-ID: {kennung}\r\nFrom: wer@example.org\r\n"
        f"Date: {datum}\r\nSubject: {betreff}\r\n\r\nInhalt von {betreff}.\r\n"
    ).encode()


def einwerfen(server, pfad: str, uid: int, roh: bytes, gelesen: bool = False) -> None:
    """Eine Mail so ablegen, dass auch ihr HEADER.FIELDS-Abruf stimmt."""
    import re

    betreff = ""
    treffer = re.search(rb"^Subject: (.*)$", roh, re.MULTILINE)
    if treffer:
        betreff = treffer.group(1).decode()
    server.einwerfen(
        pfad,
        uid,
        betreff,
        gelesen=gelesen,
        roh=roh,
        kopfzeilen={"Message-ID": austausch.kennung_lesen(roh)},
    )


def _mbox(*rohe: bytes) -> io.BytesIO:
    return io.BytesIO(b"".join(austausch.als_mbox(iter(rohe))))


@pytest.fixture
def welt(klient, db, monkeypatch):
    """Ein Postfach mit einem leeren Archiv-Ordner."""
    from app.models import Benutzer
    from conftest import einrichten

    einrichten(klient)
    person = db.query(Benutzer).one()

    server = Importserver()
    server.anlegen("Archiv")

    db.add(
        Konto(
            id="k1", benutzer_id=person.id, anzeigename="a@beispiel.example",
            adresse="a@beispiel.example", imap_server="imap.beispiel.example",
            imap_benutzer="a@beispiel.example", smtp_server="smtp.beispiel.example",
            smtp_benutzer="a@beispiel.example",
        )
    )
    db.flush()
    ordner = Ordner(konto_id="k1", pfad="Archiv", name="Archiv", rolle="archiv")
    db.add(ordner)
    db.commit()

    monkeypatch.setattr(kontendienst, "passwoerter_lesen", lambda k: ("pw", "pw"))
    monkeypatch.setattr(imapdienst, "verbinden", lambda *a, **k: server)
    konto = db.get(Konto, "k1")
    return server, konto, ordner


# --- Einspielen ----------------------------------------------------------- #


def test_die_post_landet_im_ordner(db, welt):
    server, konto, ordner = welt

    bericht = austausch.importieren(
        db, konto, ordner, _mbox(_roh("<a@example.org>", "Eins"), _roh("<b@example.org>", "Zwei"))
    )

    assert bericht.importiert == 2
    assert [pfad for pfad, *_ in server.angehaengt] == ["Archiv", "Archiv"]
    assert b"Inhalt von Eins." in server.angehaengt[0][1]


def test_was_schon_da_ist_wird_uebersprungen(db, welt):
    """⚠️ **Der Wiederholungsschutz.** Erkannt an der ``Message-ID``."""
    server, konto, ordner = welt
    einwerfen(server, "Archiv", 1, _roh("<a@example.org>", "Eins"))

    bericht = austausch.importieren(
        db, konto, ordner, _mbox(_roh("<a@example.org>", "Eins"), _roh("<b@example.org>", "Zwei"))
    )

    assert bericht.uebersprungen == 1
    assert bericht.importiert == 1
    assert len(server.angehaengt) == 1


def test_dieselbe_datei_zweimal_gibt_keine_doppelten(db, welt):
    """⚠️ **Der Fall, um den es geht:** Ein abgebrochener Import wird wiederholt.

    Beim zweiten Lauf darf nichts mehr hinzukommen — auch nicht das, was der
    erste Lauf selbst angehängt hat.
    """
    server, konto, ordner = welt
    post = (_roh("<a@example.org>", "Eins"), _roh("<b@example.org>", "Zwei"))

    austausch.importieren(db, konto, ordner, _mbox(*post))
    zweiter = austausch.importieren(db, konto, ordner, _mbox(*post))

    assert zweiter.importiert == 0
    assert zweiter.uebersprungen == 2
    assert len(server.angehaengt) == 2


def test_dieselbe_mail_zweimal_in_EINER_datei(db, welt):
    """Auch innerhalb eines Laufs. Der Server sieht sie ja erst danach."""
    server, konto, ordner = welt
    eins = _roh("<a@example.org>", "Eins")

    bericht = austausch.importieren(db, konto, ordner, _mbox(eins, eins))

    assert bericht.importiert == 1
    assert bericht.uebersprungen == 1


def test_gelesen_und_datum_wandern_mit(db, welt):
    """⚠️ Sonst ist nach dem Umzug alles ungelesen und von heute."""
    server, konto, ordner = welt
    roh = _roh("<a@example.org>", "Eins").replace(
        b"Message-ID:", b"X-Mozilla-Status: 0001\r\nMessage-ID:", 1
    )

    austausch.importieren(db, konto, ordner, _mbox(roh))

    _, _, flags, datum = server.angehaengt[0]
    assert any(b"Seen" in f for f in flags)
    assert datum == datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)


def test_ohne_kennung_wird_angehaengt_und_gezaehlt(db, welt):
    """Bei ihr kann nexmail nicht sagen, ob sie schon da ist — das steht im Bericht."""
    server, konto, ordner = welt
    ohne = b"From: wer@example.org\r\nSubject: Namenlos\r\n\r\nInhalt.\r\n"

    bericht = austausch.importieren(db, konto, ordner, _mbox(ohne))

    assert bericht.ohne_kennung == 1
    assert bericht.importiert == 1


def test_eine_kaputte_mail_kostet_nicht_die_anderen(db, welt):
    """⚠️ Eine abgelehnte Mail unter zehntausend darf die anderen nicht kosten."""
    server, konto, ordner = welt
    server.lehnt_ab = {"Zwei"}

    bericht = austausch.importieren(
        db, konto, ordner,
        _mbox(
            _roh("<a@example.org>", "Eins"),
            _roh("<b@example.org>", "Zwei"),
            _roh("<c@example.org>", "Drei"),
        ),
    )

    assert bericht.importiert == 2
    assert bericht.fehler_gesamt == 1
    # Der Satz des Servers steht wörtlich im Bericht — „ging nicht" sieht aus
    # wie ein kaputtes nexmail.
    assert "over quota" in bericht.fehler[0]
    assert "Zwei" in bericht.fehler[0]


def test_eine_gekappte_verbindung_bricht_ab(db, welt):
    """⚠️ Sonst laufen zwanzigtausend Fehlschläge durch und melden am Ende
    zwanzigtausend Fehler statt „die Verbindung ist weg"."""
    server, konto, ordner = welt
    server.tot = True
    viele = [_roh(f"<n{i}@example.org>", f"Nummer {i}") for i in range(50)]

    with pytest.raises(austausch.AustauschFehler):
        austausch.importieren(db, konto, ordner, _mbox(*viele))

    assert len(server.angehaengt) == 0


def test_die_grenze_zaehlt_das_anhaengen_nicht_das_lesen(db, welt, monkeypatch):
    """⚠️ **Sonst lässt sich ein abgebrochener Import nie fortsetzen.**

    Der zweite Anlauf verbrauchte seine Grenze mit dem Überspringen dessen,
    was schon da ist, und käme nie zum Rest.
    """
    server, konto, ordner = welt
    monkeypatch.setattr(austausch, "MAX_NACHRICHTEN", 2)
    einwerfen(server, "Archiv", 1, _roh("<a@example.org>", "Eins"))
    einwerfen(server, "Archiv", 2, _roh("<b@example.org>", "Zwei"))

    bericht = austausch.importieren(
        db, konto, ordner,
        _mbox(
            _roh("<a@example.org>", "Eins"),
            _roh("<b@example.org>", "Zwei"),
            _roh("<c@example.org>", "Drei"),
            _roh("<d@example.org>", "Vier"),
            _roh("<e@example.org>", "Fuenf"),
        ),
    )

    assert bericht.uebersprungen == 2
    assert bericht.importiert == 2, "Die Grenze wurde vom Überspringen aufgebraucht"
    assert bericht.abgeschnitten is True


def test_abbrechen_haelt_an(db, welt):
    """Was schon angehängt ist, bleibt — rückgängig gibt es nicht."""
    import threading

    server, konto, ordner = welt
    halt = threading.Event()
    echtes_append = server.append

    def append(*a, **k):
        echtes_append(*a, **k)
        halt.set()

    server.append = append
    bericht = austausch.importieren(
        db, konto, ordner,
        _mbox(*[_roh(f"<n{i}@example.org>", f"Nummer {i}") for i in range(5)]),
        halt=halt,
    )

    assert bericht.abgebrochen is True
    assert bericht.importiert == 1


def test_der_import_setzt_nichts_auf_gelesen(db, welt):
    """⚠️ Ohne ``PEEK`` machte das Nachsehen ein ganzes Postfach gelesen."""
    server, konto, ordner = welt
    einwerfen(server, "Archiv", 1, _roh("<a@example.org>", "Eins"))

    austausch.importieren(db, konto, ordner, _mbox(_roh("<b@example.org>", "Zwei")))

    for felder in server.gefragt:
        for feld in felder:
            assert not feld.startswith("BODY["), f"{feld} holt ohne PEEK"


def test_danach_steht_die_post_auch_in_nexmail(db, welt):
    """⚠️ Eine Handlung ist erst fertig, wenn nexmails Datenbank es weiß."""
    _, konto, ordner = welt

    austausch.importieren(db, konto, ordner, _mbox(_roh("<a@example.org>", "Eins")))

    betreffe = {
        n.betreff for n in db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id)
    }
    assert "Eins" in betreffe


# --- Ausgeben ------------------------------------------------------------- #


def test_ausgegeben_wird_in_der_reihenfolge_der_liste(db, welt):
    server, konto, _ = welt
    for uid, betreff in ((1, "Eins"), (2, "Zwei"), (3, "Drei")):
        einwerfen(server, "Archiv", uid, _roh(f"<n{uid}@example.org>", betreff))

    raus = list(austausch.roh_stroemen(konto, "Archiv", [3, 1, 2]))

    assert [uid for uid, *_ in raus] == [3, 1, 2]
    assert b"Inhalt von Drei." in raus[0][1]


def test_eine_verschwundene_mail_bricht_den_export_nicht_ab(db, welt):
    """Der Export ist eine Momentaufnahme; wer nebenbei am Telefon löscht,
    soll keinen Abbruch bekommen."""
    server, konto, _ = welt
    einwerfen(server, "Archiv", 1, _roh("<a@example.org>", "Eins"))

    raus = list(austausch.roh_stroemen(konto, "Archiv", [1, 99]))

    assert [uid for uid, *_ in raus] == [1]


def test_der_export_holt_blockweise(db, welt, monkeypatch):
    """⚠️ Ein Block liegt vollständig im Speicher — 2000 Mails können ein
    Gigabyte sein."""
    server, konto, _ = welt
    monkeypatch.setattr(austausch, "BLOCK_MAILS", 2)
    for uid in range(1, 6):
        einwerfen(server, "Archiv", uid, _roh(f"<n{uid}@example.org>", f"Nummer {uid}"))

    server.gefragt.clear()
    list(austausch.roh_stroemen(konto, "Archiv", [1, 2, 3, 4, 5]))

    ganze = [f for f in server.gefragt if abgleich.GANZE_MAIL in f]
    assert len(ganze) == 3, "Es wurde nicht in Blöcken zu zwei geholt"


# --- Die Adressen --------------------------------------------------------- #


def _hochladen(klient, ordner_id: int, inhalt: bytes, name: str = "Archiv.mbox"):
    return klient.post(
        "/api/austausch/import",
        files={"datei": (name, inhalt, "application/mbox")},
        data={"ordner_id": str(ordner_id)},
    )


def _abwarten(klient, kennung: str) -> dict:
    vorgang = austausch.stand(kennung, austausch._VORGAENGE[kennung].benutzer_id)
    if vorgang is not None and vorgang.faden is not None:
        vorgang.faden.join(timeout=30)
    antwort = klient.get(f"/api/austausch/vorgang/{kennung}")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_hochladen_spielt_ein_und_raeumt_die_datei_weg(klient, db, welt):
    from app.config import get_settings

    server, _, ordner = welt
    daten = _mbox(_roh("<a@example.org>", "Eins"), _roh("<b@example.org>", "Zwei")).getvalue()

    antwort = _hochladen(klient, ordner.id, daten)
    assert antwort.status_code == 200, antwort.text
    stand = _abwarten(klient, antwort.json()["id"])

    assert stand["laeuft"] is False
    assert stand["fehler"] == ""
    assert stand["importiert"] == 2
    assert len(server.angehaengt) == 2
    # ⚠️ Ein liegengebliebenes Gigabyte-Archiv im Datenverzeichnis findet
    # niemand wieder.
    einfuhr = get_settings().data_dir / "einfuhr"
    assert not einfuhr.is_dir() or list(einfuhr.iterdir()) == []


def test_eine_leere_datei_wird_abgewiesen(klient, welt):
    _, _, ordner = welt
    antwort = _hochladen(klient, ordner.id, b"")
    assert antwort.status_code == 400


def test_zwei_importe_gleichzeitig_gehen_nicht(klient, db, welt, monkeypatch):
    """⚠️ Beide holen die vorhandenen Kennungen, bevor der andere angehängt
    hat — und legen alles doppelt ab."""
    import threading

    _, _, ordner = welt
    los = threading.Event()
    echtes = austausch.vorhandene_kennungen
    monkeypatch.setattr(
        austausch,
        "vorhandene_kennungen",
        lambda k, p: (los.wait(timeout=10), echtes(k, p))[1],
    )

    erste = _hochladen(klient, ordner.id, _mbox(_roh("<a@example.org>", "Eins")).getvalue())
    assert erste.status_code == 200
    zweite = _hochladen(klient, ordner.id, _mbox(_roh("<b@example.org>", "Zwei")).getvalue())
    los.set()

    assert zweite.status_code == 409
    _abwarten(klient, erste.json()["id"])


def test_ein_fremder_ordner_ist_nicht_zu_finden(klient, db, welt):
    from app.models import Benutzer

    _, _, _ = welt
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.flush()
    fremd = Konto(
        id="fremd", benutzer_id=anderer.id, anzeigename="x@example.com",
        adresse="x@example.com", imap_server="imap.example.com",
        imap_benutzer="x@example.com", smtp_server="smtp.example.com",
        smtp_benutzer="x@example.com",
    )
    db.add(fremd)
    db.flush()
    seiner = Ordner(konto_id="fremd", pfad="INBOX", name="INBOX", rolle="posteingang")
    db.add(seiner)
    db.commit()

    assert _hochladen(klient, seiner.id, b"From x\r\n\r\nX\r\n").status_code == 404
    assert klient.get(f"/api/austausch/export/{seiner.id}").status_code == 404


def _bestand(db, ordner, server, anzahl: int) -> None:
    """Denselben Bestand beim Anbieter und in nexmails Datenbank anlegen."""
    from app.models import Benutzer

    person = db.query(Benutzer).first()
    for uid in range(1, anzahl + 1):
        roh = _roh(f"<n{uid}@example.org>", f"Nummer {uid}")
        einwerfen(server, "Archiv", uid, roh)
        db.add(
            Nachricht(
                benutzer_id=person.id, konto_id="k1", ordner_id=ordner.id, uid=uid,
                betreff=f"Nummer {uid}", von_adresse="wer@example.org",
                datum=datetime(2026, 3, uid, 9, tzinfo=timezone.utc),
                message_id=f"<n{uid}@example.org>",
            )
        )
    db.commit()


def test_export_als_mbox_laesst_sich_wieder_lesen(klient, db, welt):
    """⚠️ **Der eigentliche Beweis.** Hinaus und wieder herein, ohne Verlust."""
    server, _, ordner = welt
    _bestand(db, ordner, server, 3)

    antwort = klient.get(f"/api/austausch/export/{ordner.id}")

    assert antwort.status_code == 200
    assert "Archiv.mbox" in antwort.headers["content-disposition"]
    wieder = list(austausch.mbox_lesen(io.BytesIO(antwort.content)))
    assert len(wieder) == 3
    assert b"Inhalt von Nummer 1." in wieder[0]


def test_export_als_zip_traegt_je_eine_eml(klient, db, welt):
    import zipfile

    server, _, ordner = welt
    _bestand(db, ordner, server, 2)

    antwort = klient.get(f"/api/austausch/export/{ordner.id}?form=zip")

    assert antwort.status_code == 200
    with zipfile.ZipFile(io.BytesIO(antwort.content)) as archiv:
        assert sorted(archiv.namelist()) == ["Nummer 1.eml", "Nummer 2.eml"]


def test_ein_zu_grosser_ordner_wird_auf_mbox_verwiesen(klient, db, welt, monkeypatch):
    """⚠️ Ein ZIP entsteht vollständig im Speicher — die Grenze ist echt, und
    die Meldung nennt den Ausweg."""
    from app.routers import austausch as router

    server, _, ordner = welt
    monkeypatch.setattr(router, "MAX_ZIP", 1)
    _bestand(db, ordner, server, 2)

    antwort = klient.get(f"/api/austausch/export/{ordner.id}?form=zip")

    assert antwort.status_code == 400
    assert "mbox" in antwort.json()["detail"]


def test_ein_leerer_ordner_gibt_keine_leere_datei(klient, db, welt):
    """Eine 0-Byte-Datei sieht aus wie ein kaputter Export."""
    _, _, ordner = welt
    assert klient.get(f"/api/austausch/export/{ordner.id}").status_code == 404


def test_gelesen_wandert_auch_HINAUS(db, welt):
    """⚠️ **Am 02.09.2026 gegen ein echtes Postfach gemessen und gefunden.**

    Die Leseseite konnte ``X-Mozilla-Status`` laengst — nur schrieb sie beim
    Export niemand. Hinaus und wieder herein, und alles war ungelesen.
    """
    server, konto, ordner = welt
    einwerfen(server, "Archiv", 1, _roh("<a@example.org>", "Eins"), gelesen=True)
    einwerfen(server, "Archiv", 2, _roh("<b@example.org>", "Zwei"), gelesen=False)

    datei = b"".join(
        austausch.als_mbox(
            austausch.status_einsetzen(roh, flags)
            for _, roh, flags in austausch.roh_stroemen(konto, "Archiv", [1, 2])
        )
    )
    wieder = list(austausch.mbox_lesen(io.BytesIO(datei)))

    assert austausch.flags_lesen(wieder[0]) == [rb"\Seen"]
    assert austausch.flags_lesen(wieder[1]) == []
    # Und der Rest der Mail bleibt heil.
    assert austausch.kennung_lesen(wieder[0]) == "<a@example.org>"
    assert b"Inhalt von Eins." in wieder[0]


def test_eine_zweite_statuszeile_entsteht_nicht(db, welt):
    """Aus Thunderbird eingespielt und wieder ausgegeben: eine Zeile, nicht zwei."""
    roh = b"X-Mozilla-Status: 0000\r\nSubject: X\r\n\r\nText"

    einmal = austausch.status_einsetzen(roh, (rb"\Seen",))
    zweimal = austausch.status_einsetzen(einmal, (rb"\Seen",))

    assert austausch._kopf(zweimal).count(b"X-Mozilla-Status") == 1
    assert austausch.flags_lesen(zweimal) == [rb"\Seen"]
