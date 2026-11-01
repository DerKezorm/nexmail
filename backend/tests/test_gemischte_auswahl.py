"""Eine Auswahl aus mehreren Postfächern und Ordnern.

⚠️ **Bis 0.24.7 scheiterte das mit „lassen sich nicht zusammen verschieben".**
„Alle Posteingänge", „Markiert" und jede Suche mischen aber genau das, und
Löschen hat dort eine klare Bedeutung: Jede Mail geht in den Papierkorb ihres
eigenen Postfachs. Geprüft über die Adressen, denn der Rückweg reist durch den
Browser und kommt unverändert zurück.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Benutzer, Konto, Nachricht, Ordner
from app.services import imap as imapdienst, konten as kontendienst
from conftest import einrichten
from test_ueber_konten import Postserver, _roh


class Zugserver(Postserver):
    """Kann zusätzlich innerhalb eines Postfachs verschieben."""

    def capabilities(self):
        return [b"IMAP4REV1", b"UIDPLUS", b"MOVE"]

    def move(self, uids, ziel):
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"].pop(uid)
            neu = max(self.ordner[ziel]["nachrichten"], default=0) + 1
            self.ordner[ziel]["nachrichten"][neu] = eintrag


class Welt:
    def __init__(self, db, person):
        self.db = db
        self.person = person
        self.server = {"ka": Zugserver("ka"), "kb": Zugserver("kb")}
        self.gesperrt: set[str] = set()
        self.ordner: dict[tuple[str, str], Ordner] = {}

    def ordner_anlegen(self, konto: str, pfad: str, rolle: str) -> Ordner:
        self.server[konto].anlegen(pfad)
        ordner = Ordner(konto_id=konto, pfad=pfad, name=pfad, rolle=rolle)
        self.db.add(ordner)
        self.db.flush()
        self.ordner[(konto, pfad)] = ordner
        return ordner

    def mail(self, konto: str, pfad: str, betreff: str) -> int:
        ordner = self.ordner[(konto, pfad)]
        uid = max(self.server[konto].ordner[pfad]["nachrichten"], default=0) + 1
        kennung = f"<{betreff}@example.org>"
        self.server[konto].einwerfen(pfad, uid, betreff, gelesen=True, roh=_roh(kennung, betreff))
        nachricht = Nachricht(
            benutzer_id=self.person.id, konto_id=konto, ordner_id=ordner.id, uid=uid,
            betreff=betreff, von_adresse="wer@example.org", message_id=kennung, gelesen=True,
            datum=datetime(2026, 3, 5, 9, tzinfo=timezone.utc),
        )
        self.db.add(nachricht)
        ordner.anzahl += 1
        self.db.commit()
        return nachricht.id

    def auf_dem_server(self, konto: str, pfad: str) -> list[bytes]:
        return sorted(e["roh"] for e in self.server[konto].ordner[pfad]["nachrichten"].values())

    def zahl(self, konto: str, pfad: str) -> int:
        return len(self.server[konto].ordner[pfad]["nachrichten"])

    def zeilen(self, konto: str, pfad: str) -> list[str]:
        ordner = self.ordner[(konto, pfad)]
        self.db.expire_all()
        return sorted(n.betreff for n in self.db.query(Nachricht).filter_by(ordner_id=ordner.id))


@pytest.fixture
def welt(klient, db, monkeypatch):
    """Zwei Postfächer: ka mit Eingang, Archiv, Papierkorb, kb mit Eingang, Papierkorb.

    Je Eingang eine Mail, dazu eine im Archiv von ka."""
    einrichten(klient)
    person = db.query(Benutzer).one()
    for kennung, adresse in (("ka", "a@example.org"), ("kb", "b@example.org")):
        db.add(
            Konto(
                id=kennung, benutzer_id=person.id, anzeigename=adresse, adresse=adresse,
                imap_server=f"imap.{kennung}.example", imap_benutzer=adresse,
                smtp_server=f"smtp.{kennung}.example", smtp_benutzer=adresse,
            )
        )
    db.flush()

    w = Welt(db, person)
    w.ordner_anlegen("ka", "INBOX", "posteingang")
    w.ordner_anlegen("ka", "Archive", "archiv")
    w.ordner_anlegen("ka", "Trash", "papierkorb")
    w.ordner_anlegen("kb", "INBOX", "posteingang")
    w.ordner_anlegen("kb", "Trash", "papierkorb")
    w.a = w.mail("ka", "INBOX", "Alpha")
    w.archiv = w.mail("ka", "Archive", "Altes")
    w.b = w.mail("kb", "INBOX", "Beta")

    def verbinden(name, *a, **k):
        kennung = "ka" if ".ka." in name else "kb"
        if kennung in w.gesperrt:
            raise imapdienst.Verbindungsfehler(art="netz", text="Server not reachable.")
        return w.server[kennung]

    monkeypatch.setattr(kontendienst, "passwoerter_lesen", lambda k: ("pw", "pw"))
    monkeypatch.setattr(imapdienst, "verbinden", verbinden)
    monkeypatch.setattr(
        imapdienst, "faehigkeiten", lambda klient: [c.decode() for c in klient.capabilities()]
    )
    return w


def _loeschen(klient, *ids):
    return klient.post("/api/nachrichten/loeschen", json={"ids": list(ids)})


def test_jede_mail_geht_in_den_eigenen_papierkorb(klient, welt):
    antwort = _loeschen(klient, welt.a, welt.archiv, welt.b)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 3
    assert antwort.json()["nicht_bewegt"] == 0
    assert welt.zahl("ka", "Trash") == 2
    assert welt.zahl("kb", "Trash") == 1
    assert (welt.zahl("ka", "INBOX"), welt.zahl("ka", "Archive"), welt.zahl("kb", "INBOX")) == (0, 0, 0)
    # ⚠️ Keine Mail hat dabei das Postfach gewechselt.
    assert welt.server["ka"].angehaengt == [] and welt.server["kb"].angehaengt == []
    assert welt.zeilen("ka", "Trash") == ["Alpha", "Altes"]
    assert welt.zeilen("kb", "Trash") == ["Beta"]


def test_rueckgaengig_bringt_alles_an_seinen_platz(klient, welt):
    weg = _loeschen(klient, welt.a, welt.archiv, welt.b).json()["rueckweg"]

    antwort = klient.post("/api/nachrichten/zurueck", json=weg)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 3
    assert (welt.zahl("ka", "INBOX"), welt.zahl("ka", "Archive"), welt.zahl("kb", "INBOX")) == (1, 1, 1)
    assert welt.zahl("ka", "Trash") == 0 and welt.zahl("kb", "Trash") == 0
    assert welt.zeilen("ka", "INBOX") == ["Alpha"]
    assert welt.zeilen("ka", "Archive") == ["Altes"]
    assert welt.zeilen("kb", "INBOX") == ["Beta"]


def test_ein_ziel_nimmt_mails_aus_beiden_postfaechern(klient, welt):
    """Das Eigene mit MOVE, das Fremde über ``ueber_konten``."""
    ziel = welt.ordner[("ka", "Archive")]

    antwort = klient.post(
        "/api/nachrichten/verschieben", json={"ids": [welt.a, welt.b], "ordner_id": ziel.id}
    )

    assert antwort.status_code == 200, antwort.text
    assert welt.zahl("ka", "Archive") == 3
    assert welt.zahl("ka", "INBOX") == 0 and welt.zahl("kb", "INBOX") == 0
    assert [pfad for pfad, *_ in welt.server["ka"].angehaengt] == ["Archive"]

    zurueck = klient.post("/api/nachrichten/zurueck", json=antwort.json()["rueckweg"])

    assert zurueck.status_code == 200, zurueck.text
    assert welt.zahl("ka", "INBOX") == 1 and welt.zahl("kb", "INBOX") == 1
    assert welt.zahl("ka", "Archive") == 1


def test_zwei_ordner_gehen_zusammen_ueber_die_grenze(klient, welt):
    ziel = welt.ordner[("kb", "Trash")]

    antwort = klient.post(
        "/api/nachrichten/verschieben", json={"ids": [welt.a, welt.archiv], "ordner_id": ziel.id}
    )

    assert antwort.status_code == 200, antwort.text
    assert welt.zahl("kb", "Trash") == 2
    assert welt.zahl("ka", "INBOX") == 0 and welt.zahl("ka", "Archive") == 0


def test_ein_postfach_ohne_papierkorb_haelt_das_andere_nicht_auf(klient, welt, db):
    welt.ordner[("kb", "Trash")].rolle = "eigen"
    db.commit()

    antwort = _loeschen(klient, welt.a, welt.b)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 1
    assert antwort.json()["nicht_bewegt"] == 1
    assert welt.zahl("ka", "Trash") == 1
    assert welt.zahl("kb", "INBOX") == 1


def test_ein_postfach_ohne_verbindung_haelt_das_andere_nicht_auf(klient, welt):
    welt.gesperrt.add("kb")

    antwort = _loeschen(klient, welt.a, welt.b)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["nicht_bewegt"] == 1
    assert welt.zahl("ka", "Trash") == 1
    assert welt.zahl("kb", "INBOX") == 1

    # Der Rückweg kennt nur, was wirklich ging.
    welt.gesperrt.clear()
    weg = antwort.json()["rueckweg"]
    assert [teil["konto_id"] for teil in weg["teile"]] == ["ka"]
    assert klient.post("/api/nachrichten/zurueck", json=weg).status_code == 200
    assert welt.zahl("ka", "INBOX") == 1


def test_scheitert_alles_kommt_der_grund_heraus(klient, welt):
    welt.gesperrt.update({"ka", "kb"})

    antwort = _loeschen(klient, welt.a, welt.b)

    assert antwort.status_code == 502, antwort.text
    assert antwort.json()["detail"] == "Server not reachable."
    assert welt.zahl("ka", "INBOX") == 1 and welt.zahl("kb", "INBOX") == 1


def test_was_schon_dort_liegt_ist_kein_fehlschlag(klient, welt):
    weg = _loeschen(klient, welt.a).json()["rueckweg"]
    assert weg["teile"] == []
    im_papierkorb = welt.mail("ka", "Trash", "Liegt")

    antwort = _loeschen(klient, im_papierkorb, welt.b)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 1
    assert antwort.json()["nicht_bewegt"] == 0
    assert welt.zahl("kb", "Trash") == 1


def test_liegt_alles_schon_dort_sagt_es_das(klient, welt):
    erste = welt.mail("ka", "Trash", "Erste")
    zweite = welt.mail("kb", "Trash", "Zweite")

    antwort = _loeschen(klient, erste, zweite)

    assert antwort.status_code == 400, antwort.text
    assert antwort.json()["detail"] == "liegt_schon_dort"


def test_ein_rueckweg_kann_scheitern_und_sagt_es(klient, welt):
    weg = _loeschen(klient, welt.a, welt.b).json()["rueckweg"]
    # ⚠️ Der ERSTE Teil scheitert. Beim letzten sähe „gibt auf" genauso aus.
    welt.gesperrt.add("ka")

    antwort = klient.post("/api/nachrichten/zurueck", json=weg)

    assert antwort.status_code == 502, antwort.text
    # Das andere Postfach ist trotzdem zurück.
    assert welt.zahl("kb", "INBOX") == 1
    assert welt.zahl("ka", "Trash") == 1


def test_ein_teil_des_rueckwegs_wird_geprueft_nicht_geglaubt(klient, welt, db):
    """⚠️ **``teile`` kommt aus dem Browser**, wie ``ziel_konto_id``. Ungeprüft
    holte eine fremde Kennung darin fremde Post."""
    weg = _loeschen(klient, welt.a, welt.b).json()["rueckweg"]
    fremd = Benutzer(id="f" * 32, benutzername="fremd", anzeigename="Fremd", passwort_hash="x")
    db.add(fremd)
    db.flush()
    db.get(Konto, "kb").benutzer_id = fremd.id
    db.commit()

    antwort = klient.post("/api/nachrichten/zurueck", json=weg)

    assert antwort.status_code == 404, antwort.text
    assert welt.zahl("ka", "Trash") == 1 and welt.zahl("kb", "Trash") == 1
    assert welt.zahl("ka", "INBOX") == 0
