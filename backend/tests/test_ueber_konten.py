"""Verschieben über Kontogrenzen.

⚠️ **Hier kann Post verlorengehen, und nur hier.** Innerhalb eines Postfachs
macht der Server den Zug in einem Stück; über die Grenze sind zwei Server
beteiligt, und keiner kennt den anderen. Die Reihenfolge ist die ganze
Sicherheit: holen, beim Ziel anhängen, **nachsehen**, erst dann bei der Quelle
löschen.

Wer zuerst löscht, verliert die Mail, sobald der zweite Schritt scheitert — und
er scheitert irgendwann. Andersherum ist der schlimmste Fall eine Mail, die
zweimal da ist. Das sieht man und kann es aufräumen; das andere sieht man
nicht.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app.models import Konto, Nachricht, Ordner
from app.services import abgleich, handeln, imap as imapdienst, konten as kontendienst
from test_abgleich import FalscherServer


class Postserver(FalscherServer):
    """Ein Server, der auch anhängen und löschen kann — und auf Wunsch mogelt."""

    def __init__(self, name: str = "server"):
        super().__init__()
        self.name = name
        self.angehaengt: list[tuple[str, bytes, tuple, object]] = []
        self.geloescht: list[int] = []
        #: ⚠️ Steuert den Fall, in dem ``APPEND`` keinen Fehler wirft und die
        #: Nachricht trotzdem nicht im Ordner landet: Quote, ein Filter auf dem
        #: Zielserver, ein stiller Ablagekorb. Genau dafür wird nachgesehen.
        self.nimmt_wirklich_an = True

    def append(self, pfad, roh, flags=None, datum=None):
        self.angehaengt.append((pfad, roh, tuple(flags or ()), datum))
        if not self.nimmt_wirklich_an:
            return
        uid = max(self.ordner[pfad]["nachrichten"], default=0) + 1
        gelesen = any(b"Seen" in f for f in (flags or ()))
        betreff = ""
        treffer = re.search(rb"^Subject: (.*)$", roh, re.MULTILINE)
        if treffer:
            betreff = treffer.group(1).decode()
        self.einwerfen(pfad, uid, betreff, gelesen=gelesen, roh=roh)

    def add_flags(self, uids, flags):
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"].get(uid)
            if eintrag is not None and any(b"Deleted" in f for f in flags):
                eintrag["geloescht"] = True

    def uid_expunge(self, uids):
        for uid in uids:
            if self.ordner[self._aktuell]["nachrichten"].pop(uid, None) is not None:
                self.geloescht.append(uid)

    def search(self, kriterien):
        """``HEADER Message-ID <…>`` sucht wirklich, alles andere wie bisher."""
        if isinstance(kriterien, list) and len(kriterien) == 3 and kriterien[0] == "HEADER":
            gesucht = kriterien[2].encode()
            return [
                uid
                for uid, e in self.ordner[self._aktuell]["nachrichten"].items()
                if e.get("roh") and gesucht in e["roh"]
            ]
        return super().search(kriterien)

    def fetch(self, uids, felder):
        antwort = super().fetch(uids, felder)
        if any("INTERNALDATE" == str(f) for f in felder):
            for zeile in antwort.values():
                zeile[b"INTERNALDATE"] = datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)
        return antwort


def _roh(kennung: str, betreff: str) -> bytes:
    return (
        f"Message-ID: {kennung}\r\nFrom: wer@example.org\r\n"
        f"Subject: {betreff}\r\n\r\nInhalt.\r\n"
    ).encode()


@pytest.fixture
def welt(klient, db, monkeypatch):
    """Zwei Postfächer, jedes mit eigenem Server, zwei Mails im Ausgang."""
    from app.models import Benutzer
    from conftest import einrichten

    einrichten(klient)
    person = db.query(Benutzer).one()

    quelle_srv, ziel_srv = Postserver("quelle"), Postserver("ziel")
    quelle_srv.anlegen("INBOX")
    ziel_srv.anlegen("INBOX")
    ziel_srv.anlegen("Archiv")

    for kennung, adresse in (("ka", "a@beispiel.example"), ("kb", "b@beispiel.example")):
        db.add(
            Konto(
                id=kennung, benutzer_id=person.id, anzeigename=adresse, adresse=adresse,
                imap_server=f"imap.{kennung}.example", imap_benutzer=adresse,
                smtp_server=f"smtp.{kennung}.example", smtp_benutzer=adresse,
            )
        )
    db.flush()

    quelle = Ordner(konto_id="ka", pfad="INBOX", name="INBOX", rolle="posteingang")
    ziel = Ordner(konto_id="kb", pfad="Archiv", name="Archiv", rolle="archiv")
    db.add_all([quelle, ziel])
    db.flush()

    nachrichten = []
    for i, (uid, kennung) in enumerate(((1, "<eins@example.org>"), (2, "<zwei@example.org>"))):
        roh = _roh(kennung, f"Nummer {i + 1}")
        quelle_srv.einwerfen("INBOX", uid, f"Nummer {i + 1}", gelesen=True, roh=roh)
        n = Nachricht(
            benutzer_id=person.id, konto_id="ka", ordner_id=quelle.id, uid=uid,
            betreff=f"Nummer {i + 1}", von_adresse="wer@example.org",
            datum=datetime(2026, 3, 5, 9, tzinfo=timezone.utc),
            message_id=kennung, gelesen=True,
        )
        db.add(n)
        nachrichten.append(n)
    quelle.anzahl = 2
    db.commit()

    monkeypatch.setattr(kontendienst, "passwoerter_lesen", lambda k: ("pw", "pw"))
    monkeypatch.setattr(
        imapdienst, "verbinden",
        lambda server, *a, **k: quelle_srv if "ka" in server else ziel_srv,
    )
    return quelle_srv, ziel_srv, quelle, ziel, nachrichten


def test_die_mail_kommt_beim_anderen_postfach_an(db, welt):
    quelle_srv, ziel_srv, quelle, ziel, nachrichten = welt

    weg = handeln.verschieben(db, nachrichten, ziel)

    assert len(ziel_srv.angehaengt) == 2
    assert all(pfad == "Archiv" for pfad, *_ in ziel_srv.angehaengt)
    # Und bei der Quelle ist sie weg — aber erst danach.
    assert sorted(quelle_srv.geloescht) == [1, 2]
    assert db.query(Nachricht).filter(Nachricht.ordner_id == quelle.id).count() == 0
    # Der Rückweg kennt beide Postfächer.
    assert weg.konto_id == "ka"
    assert weg.ziel_konto_id == "kb"


def test_flags_und_datum_wandern_mit(db, welt):
    """⚠️ Ohne sie ist nach einem Umzug jede Mail ungelesen und von heute.

    Bei tausend Mails ist das Postfach damit unbrauchbar.
    """
    _, ziel_srv, _, ziel, nachrichten = welt

    handeln.verschieben(db, nachrichten, ziel)

    _, _, flags, datum = ziel_srv.angehaengt[0]
    assert any(b"Seen" in f for f in flags)
    assert datum == datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)


def test_recent_wird_nicht_mitgeschickt(db, welt):
    """``\\Recent`` gehört dem Server, nicht der Nachricht — manche weisen es ab."""
    quelle_srv, ziel_srv, _, ziel, nachrichten = welt
    for eintrag in quelle_srv.ordner["INBOX"]["nachrichten"].values():
        eintrag["schlagworte"] = ["\\Recent"]

    handeln.verschieben(db, nachrichten, ziel)

    for _, _, flags, _ in ziel_srv.angehaengt:
        assert not any(b"ecent" in f for f in flags)


def test_kommt_nichts_an_wird_nichts_geloescht(db, welt):
    """⚠️ **Der Test, um den es geht.**

    ``APPEND`` ohne Fehler heißt nicht, dass die Mail im Ordner liegt: Quote,
    ein Filter auf dem Zielserver, ein stiller Ablagekorb. Wer sich darauf
    verlässt und löscht, hat die Post vernichtet.
    """
    quelle_srv, ziel_srv, quelle, ziel, nachrichten = welt
    ziel_srv.nimmt_wirklich_an = False

    with pytest.raises(handeln.HandelnFehler) as fehler:
        handeln.verschieben(db, nachrichten, ziel)

    assert "gelöscht" in str(fehler.value)
    # Nichts weg, weder auf dem Server noch in der Datenbank.
    assert quelle_srv.geloescht == []
    assert sorted(quelle_srv.ordner["INBOX"]["nachrichten"]) == [1, 2]
    assert db.query(Nachricht).filter(Nachricht.ordner_id == quelle.id).count() == 2


def test_geloescht_wird_erst_nach_dem_nachsehen(db, welt, monkeypatch):
    """Die Reihenfolge selbst, nicht ihr Ergebnis."""
    quelle_srv, ziel_srv, _, ziel, nachrichten = welt
    ablauf: list[str] = []

    echtes_append = ziel_srv.append
    echtes_search = ziel_srv.search
    echtes_expunge = quelle_srv.uid_expunge

    def append(*a, **k):
        ablauf.append("anhaengen")
        return echtes_append(*a, **k)

    def search(*a, **k):
        ablauf.append("nachsehen")
        return echtes_search(*a, **k)

    def expunge(*a, **k):
        ablauf.append("loeschen")
        return echtes_expunge(*a, **k)

    monkeypatch.setattr(ziel_srv, "append", append)
    monkeypatch.setattr(ziel_srv, "search", search)
    monkeypatch.setattr(quelle_srv, "uid_expunge", expunge)

    handeln.verschieben(db, nachrichten, ziel)

    assert ablauf.index("anhaengen") < ablauf.index("nachsehen")
    assert ablauf.index("nachsehen") < ablauf.index("loeschen")


def test_aus_zwei_ordnern_auf_einmal_geht_nicht(db, welt):
    _, _, quelle, ziel, nachrichten = welt
    nachrichten[1].ordner_id = quelle.id + 99
    with pytest.raises(handeln.HandelnFehler):
        handeln.verschieben(db, nachrichten, ziel)
