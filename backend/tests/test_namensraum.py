"""Server mit Namensraum-Präfix (Issue #12).

Dovecot bei Hetzner Webhosting meldet als persönlichen Namensraum
``("INBOX.", ".")``. Jeder eigene Ordner liegt dort unter ``INBOX.``; ein
Ordner ``Rechnungen`` ohne Präfix wird abgewiesen:

    Client tried to access nonexistent namespace.
    (Mailbox name should probably be prefixed with: INBOX.)

Der Doppelgänger hier antwortet genauso, sonst prüft der Test nichts.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import Nachricht, Ordner, utcnow
from app.services import abgleich, imap as imapdienst, ordner as ordnerdienst
from app.services import wiedervorlage as wvdienst
from test_abgleich import konto  # noqa: F401 - Fixture
from test_ordner_anlegen import ServerMitOrdnern
from test_wiedervorlage import WiedervorlageServer, _mail, _person

HETZNER_ABWEISUNG = (
    "create failed: Client tried to access nonexistent namespace. "
    "(Mailbox name should probably be prefixed with: INBOX.)"
)


def _namensraum(praefix, trenner="."):
    return SimpleNamespace(personal=((praefix, trenner),), other=None, shared=None)


class Hetzner(ServerMitOrdnern):
    """Dovecot mit ``INBOX.``-Präfix, wie bei Hetzner Webhosting."""

    def __init__(self):
        super().__init__(trenner=b".")

    def namespace(self):
        return _namensraum("INBOX.")

    def create_folder(self, pfad):
        if not pfad.startswith("INBOX."):
            raise RuntimeError(HETZNER_ABWEISUNG)
        super().create_folder(pfad)


@pytest.fixture
def hetzner(db, konto, monkeypatch):  # noqa: F811
    server = Hetzner()
    monkeypatch.setattr(ordnerdienst.imapdienst, "verbinden", lambda *a, **k: server)
    return server, konto


# --- Ordner anlegen -------------------------------------------------------- #


def test_oben_heisst_bei_hetzner_inbox_punkt(db, hetzner):
    server, konto = hetzner  # noqa: F811

    neu = ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert server.angelegt == ["INBOX.Rechnungen"]
    assert neu.pfad == "INBOX.Rechnungen"
    assert neu.name == "Rechnungen"
    db.refresh(konto)
    assert konto.namensraum == "INBOX.", "Der Präfix wurde nicht am Postfach gemerkt."


def test_ein_unterordner_haengt_am_eltern_nicht_noch_einmal_am_praefix(db, hetzner):
    server, konto = hetzner  # noqa: F811
    eltern = ordnerdienst.anlegen(db, konto, "Haus")

    unter = ordnerdienst.anlegen(db, konto, "Rechnungen", eltern)

    assert unter.pfad == "INBOX.Haus.Rechnungen"


def test_ohne_praefix_bleibt_oben_oben(db, konto, monkeypatch):  # noqa: F811
    """Gmail, iCloud und die meisten anderen melden einen leeren Präfix."""
    server = ServerMitOrdnern()
    server.namespace = lambda: _namensraum("", "/")
    monkeypatch.setattr(ordnerdienst.imapdienst, "verbinden", lambda *a, **k: server)

    neu = ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert neu.pfad == "Rechnungen"
    assert konto.namensraum == ""


def test_ein_aussetzer_vergisst_den_bekannten_praefix_nicht(db, hetzner):
    """⚠️ Ohne Antwort auf ``NAMESPACE`` gilt das Gemerkte. Sonst legte ein
    einziger Aussetzer den nächsten Ordner wieder ohne Präfix an."""
    server, konto = hetzner  # noqa: F811
    konto.namensraum = "INBOX."
    db.commit()

    def stumm():
        raise RuntimeError("NAMESPACE failed")

    server.namespace = stumm

    neu = ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert neu.pfad == "INBOX.Rechnungen"
    assert konto.namensraum == "INBOX."


@pytest.mark.parametrize(
    "antwort,erwartet",
    [
        (_namensraum("INBOX."), "INBOX."),
        (_namensraum(b"INBOX/", b"/"), "INBOX/"),
        (_namensraum(""), ""),
        (SimpleNamespace(personal=None, other=None, shared=None), ""),
    ],
)
def test_der_namensraum_wird_gelesen(antwort, erwartet):
    klient = SimpleNamespace(namespace=lambda: antwort)
    assert imapdienst.namensraum_lesen(klient) == erwartet


# --- Der Abgleich merkt ihn, die Ordnerliste nennt ihn --------------------- #


def test_der_abgleich_merkt_den_praefix_und_die_liste_nennt_ihn(db, konto):  # noqa: F811
    server = Hetzner()
    server.pfade += ["INBOX.Sent", "INBOX.Rechnungen"]
    server.abonniert += ["INBOX.Sent", "INBOX.Rechnungen"]
    abgleich._ordnerliste_nachziehen(server, db, konto)
    db.commit()

    assert konto.namensraum == "INBOX."
    # Über die Adresse, die die Oberfläche fragt.
    from app.routers import konten as konten_router

    zeilen = {z.pfad: z for z in konten_router.ordner(konto.id, konto.benutzer, db)}
    assert zeilen["INBOX.Rechnungen"].namensraum == "INBOX."
    assert zeilen["INBOX"].wiedervorlage is False


# --- Die Wiedervorlage ----------------------------------------------------- #


class HetznerWiedervorlage(WiedervorlageServer):
    def list_folders(self, *_a, **_k):
        return [((rb"\HasNoChildren",), b".", p) for p in self.ordner]

    def list_sub_folders(self, *_a, **_k):
        return [((rb"\HasNoChildren",), b".", p) for p in self.abonniert]

    def namespace(self):
        return _namensraum("INBOX.")

    def create_folder(self, pfad):
        if not pfad.startswith("INBOX."):
            raise RuntimeError(HETZNER_ABWEISUNG)
        super().create_folder(pfad)


@pytest.fixture
def wv_welt(db, konto, monkeypatch):  # noqa: F811
    server = HetznerWiedervorlage()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Erste", gelesen=True)
    eintrag = server.ordner["INBOX"]["nachrichten"][1]
    eintrag["message_id"] = "<Erste@example.com>"
    eintrag["kopfzeilen"]["Message-ID"] = eintrag["message_id"]
    monkeypatch.setattr(wvdienst.imapdienst, "verbinden", lambda *a, **k: server)
    monkeypatch.setattr(
        wvdienst.imapdienst,
        "faehigkeiten",
        lambda klient: [c.decode() for c in klient.capabilities()],
    )
    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)
    # ⚠️ Der Doppelgänger leitet die Kennung der Zeile aus dem Betreff ab
    # (``@x.example``); sie muss zu der auf dem Server passen, sonst findet
    # das Aufwachen die Mail nie.
    _mail(db, "Erste").message_id = eintrag["message_id"]
    db.commit()
    return server, konto, posteingang


def test_die_wiedervorlage_liegt_bei_hetzner_unter_inbox_punkt(db, wv_welt):
    """⚠️ Gefunden beim Nachsehen zu Issue #12: Weglegen scheiterte dort immer,
    weil der Ordner ohne Präfix angelegt werden sollte."""
    server, konto, posteingang = wv_welt  # noqa: F811
    person = _person(db)

    wvdienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() - timedelta(minutes=1))

    assert server.angelegt == ["INBOX.Wiedervorlage"]
    assert len(server.ordner["INBOX.Wiedervorlage"]["nachrichten"]) == 1

    # Und das Aufwachen findet sie dort und legt sie zurück.
    assert wvdienst.runde() == 1
    db.expire_all()
    assert _mail(db, "Erste").ordner_id == posteingang.id
    wv = db.query(Ordner).filter(Ordner.pfad == "INBOX.Wiedervorlage").one()
    assert db.query(Nachricht).filter(Nachricht.ordner_id == wv.id).count() == 0


def test_der_vorhandene_ordner_wird_wiedererkannt(db, wv_welt):
    """Zweimal weglegen legt keinen zweiten Ordner an."""
    server, konto, _ = wv_welt  # noqa: F811
    person = _person(db)
    wvdienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() + timedelta(hours=1))

    wvdienst.weglegen(db, person, _mail(db, "Erste").id, utcnow() + timedelta(hours=2))

    assert server.angelegt == ["INBOX.Wiedervorlage"]
    assert wvdienst.ist_ordner("INBOX.Wiedervorlage", konto)
    assert not wvdienst.ist_ordner("INBOX.Rechnungen", konto)
