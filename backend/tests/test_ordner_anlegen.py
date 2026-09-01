"""Ordner anlegen.

⚠️ **Der Ebenentrenner ist die teure Stelle.** All-Inkl trennt mit ``.``,
Gmail und iCloud mit ``/``. Wer ihn rät, legt bei der Hälfte der Anbieter einen
Ordner an, der wörtlich „Haus/Rechnungen" heißt, statt eines Unterordners — und
das fällt erst auf, wenn jemand mit einem anderen Client hineinsieht.
"""

from __future__ import annotations

import pytest

from app.models import Ordner
from app.services import konten as kontendienst, ordner as ordnerdienst
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


class ServerMitOrdnern(FalscherServer):
    """Ein Server, der ``CREATE`` und ``LIST`` beherrscht."""

    def __init__(self, trenner: bytes = b"/"):
        super().__init__()
        self.trenner = trenner
        self.pfade: list[str] = ["INBOX"]
        self.abonniert: list[str] = ["INBOX"]
        self.angelegt: list[str] = []

    def list_folders(self, *_a, **_k):
        return [((rb"\HasNoChildren",), self.trenner, p) for p in self.pfade]

    def list_sub_folders(self, *_a, **_k):
        return [((rb"\HasNoChildren",), self.trenner, p) for p in self.abonniert]

    def create_folder(self, pfad):
        if pfad in self.pfade:
            raise RuntimeError("Mailbox already exists")
        self.angelegt.append(pfad)
        self.pfade.append(pfad)

    def subscribe_folder(self, pfad):
        self.abonniert.append(pfad)

    def capabilities(self):
        return [b"IMAP4rev1"]


@pytest.fixture
def welt(db, konto, monkeypatch):  # noqa: F811
    server = ServerMitOrdnern()
    monkeypatch.setattr(ordnerdienst.imapdienst, "verbinden", lambda *a, **k: server)
    return server, konto


def test_ordner_entsteht_beim_anbieter(db, welt):
    """⚠️ Ein Ordner, den nur nexmail kennt, wäre beim nächsten Abgleich weg."""
    server, konto = welt  # noqa: F811

    neu = ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert server.angelegt == ["Rechnungen"]
    assert neu.pfad == "Rechnungen"
    assert neu.name == "Rechnungen"


def test_der_neue_ordner_gilt_als_abonniert(db, welt):
    """⚠️ nexmail zeigt nur abonnierte Ordner — sonst ist er sofort unsichtbar."""
    server, konto = welt  # noqa: F811

    neu = ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert "Rechnungen" in server.abonniert
    assert neu.abonniert is True


def test_unterordner_nimmt_den_trenner_des_servers(db, welt):
    server, konto = welt  # noqa: F811
    eltern = ordnerdienst.anlegen(db, konto, "Haus")

    unter = ordnerdienst.anlegen(db, konto, "Rechnungen", eltern)

    assert unter.pfad == "Haus/Rechnungen"


def test_ein_server_mit_punkt_bekommt_einen_punkt(db, konto, monkeypatch):  # noqa: F811
    """⚠️ **All-Inkl trennt mit ``.``** — geraten wäre hier falsch."""
    server = ServerMitOrdnern(trenner=b".")
    monkeypatch.setattr(ordnerdienst.imapdienst, "verbinden", lambda *a, **k: server)

    eltern = ordnerdienst.anlegen(db, konto, "Haus")
    unter = ordnerdienst.anlegen(db, konto, "Rechnungen", eltern)

    assert unter.pfad == "Haus.Rechnungen"


@pytest.mark.parametrize("name", ["", "   ", "a" * 101])
def test_unbrauchbare_namen_werden_abgewiesen(db, welt, name):
    _server, konto = welt  # noqa: F811
    with pytest.raises(ordnerdienst.OrdnerFehler):
        ordnerdienst.anlegen(db, konto, name)


def test_ein_trenner_im_namen_wird_abgewiesen(db, welt):
    """⚠️ Sonst entstehen unbeabsichtigt zwei Ebenen — oder ein Serverfehler."""
    _server, konto = welt  # noqa: F811

    with pytest.raises(ordnerdienst.OrdnerFehler) as fehler:
        ordnerdienst.anlegen(db, konto, "Haus/Rechnungen")

    assert "übergeordneten" in str(fehler.value)


def test_derselbe_name_kommt_nicht_zweimal(db, welt):
    _server, konto = welt  # noqa: F811
    ordnerdienst.anlegen(db, konto, "Rechnungen")

    with pytest.raises(ordnerdienst.OrdnerFehler) as fehler:
        ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert "schon" in str(fehler.value)


def test_die_meldung_des_servers_kommt_durch(db, konto, monkeypatch):  # noqa: F811
    """⚠️ „Ging nicht" hilft niemandem. „Mailbox already exists" schon."""
    server = ServerMitOrdnern()

    def bockig(pfad):  # noqa: ARG001
        raise RuntimeError("Permission denied")

    server.create_folder = bockig
    monkeypatch.setattr(ordnerdienst.imapdienst, "verbinden", lambda *a, **k: server)

    with pytest.raises(ordnerdienst.OrdnerFehler) as fehler:
        ordnerdienst.anlegen(db, konto, "Verboten")

    assert "Permission denied" in str(fehler.value)


def test_ein_gescheitertes_abonnement_wirft_den_ordner_nicht_weg(db, konto, monkeypatch):  # noqa: F811
    """Manche Server kennen Abonnements gar nicht — der Ordner ist trotzdem da."""
    server = ServerMitOrdnern()

    def bockig(pfad):  # noqa: ARG001
        raise RuntimeError("SUBSCRIBE not supported")

    server.subscribe_folder = bockig
    monkeypatch.setattr(ordnerdienst.imapdienst, "verbinden", lambda *a, **k: server)

    neu = ordnerdienst.anlegen(db, konto, "Rechnungen")

    assert neu.pfad == "Rechnungen"


def test_ein_anderer_kann_hier_nichts_anlegen(klient):
    """Die Adresse ist ohne Anmeldung zu."""
    antwort = klient.post("/api/konten/fremd/ordner", json={"name": "Test"})
    assert antwort.status_code == 401


# --- Entfernen ------------------------------------------------------------- #


def _mit_loeschen(server: ServerMitOrdnern) -> ServerMitOrdnern:
    server.entfernt = []

    def delete_folder(pfad):
        server.entfernt.append(pfad)
        server.pfade = [p for p in server.pfade if p != pfad]

    def unsubscribe_folder(pfad):
        server.abonniert = [p for p in server.abonniert if p != pfad]

    server.delete_folder = delete_folder
    server.unsubscribe_folder = unsubscribe_folder
    return server


def test_ein_eigener_ordner_laesst_sich_entfernen(db, welt):
    server, konto = welt  # noqa: F811
    _mit_loeschen(server)
    neu = ordnerdienst.anlegen(db, konto, "Weg damit")

    anzahl = ordnerdienst.entfernen(db, konto, neu)

    assert server.entfernt == ["Weg damit"]
    assert anzahl == 0
    assert "Weg damit" not in [o.pfad for o in konto.ordner]


def test_der_papierkorb_laesst_sich_nicht_entfernen(db, welt):
    """⚠️ Wer seinen Papierkorb löscht, kann danach keine Mail mehr löschen —
    und die Fehlermeldung bringt niemand mit dieser Handlung in Verbindung."""
    server, konto = welt  # noqa: F811
    _mit_loeschen(server)
    papierkorb = Ordner(
        konto_id=konto.id, pfad="Papierkorb", name="Papierkorb", rolle="papierkorb"
    )
    db.add(papierkorb)
    db.commit()

    with pytest.raises(ordnerdienst.OrdnerFehler) as fehler:
        ordnerdienst.entfernen(db, konto, papierkorb)

    assert "braucht" in str(fehler.value)
    assert server.entfernt == []


def test_ein_ordner_mit_unterordnern_wird_nicht_stillschweigend_mitgenommen(db, welt):
    """⚠️ Sonst verschwinden Ordner, nach denen niemand gefragt wurde."""
    server, konto = welt  # noqa: F811
    _mit_loeschen(server)
    eltern = ordnerdienst.anlegen(db, konto, "Haus")
    ordnerdienst.anlegen(db, konto, "Rechnungen", eltern)

    with pytest.raises(ordnerdienst.OrdnerFehler) as fehler:
        ordnerdienst.entfernen(db, konto, eltern)

    assert "Unterordner" in str(fehler.value)
    assert server.entfernt == []


def test_die_zahl_der_nachrichten_kommt_zurueck(db, welt):
    """Die Oberfläche nennt sie in der Rückfrage — vorher, nicht hinterher."""
    from datetime import datetime, timezone

    from app.models import Nachricht

    server, konto = welt  # noqa: F811
    _mit_loeschen(server)
    neu = ordnerdienst.anlegen(db, konto, "Voll")
    for uid in (1, 2, 3):
        db.add(
            Nachricht(
                benutzer_id=konto.benutzer_id,
                konto_id=konto.id,
                ordner_id=neu.id,
                uid=uid,
                betreff=f"Nr {uid}",
                datum=datetime.now(timezone.utc),
            )
        )
    db.commit()

    assert ordnerdienst.entfernen(db, konto, neu) == 3


# --- Umbenennen ------------------------------------------------------------ #


def _mit_umbenennen(server: ServerMitOrdnern) -> ServerMitOrdnern:
    server.umbenannt = []

    def rename_folder(alt, neu):
        server.umbenannt.append((alt, neu))
        # ⚠️ RENAME nimmt die Unterordner mit - das muss der Doppelgänger auch
        # tun, sonst prüft der Test einen Fall, den es nicht gibt.
        server.pfade = [
            (neu + p[len(alt) :]) if p == alt or p.startswith(alt + "/") else p
            for p in server.pfade
        ]
        server.abonniert = [
            (neu + p[len(alt) :]) if p == alt or p.startswith(alt + "/") else p
            for p in server.abonniert
        ]

    server.rename_folder = rename_folder
    return server


def test_ein_ordner_laesst_sich_umbenennen(db, welt):
    server, konto = welt  # noqa: F811
    _mit_umbenennen(server)
    alt = ordnerdienst.anlegen(db, konto, "Alter Name")

    neu = ordnerdienst.umbenennen(db, konto, alt, "Neuer Name")

    assert server.umbenannt == [("Alter Name", "Neuer Name")]
    assert neu.pfad == "Neuer Name"
    assert neu.name == "Neuer Name"


def test_umbenennen_laesst_den_ordner_wo_er_ist(db, welt):
    """⚠️ Nur der letzte Teil des Pfades wechselt — Verschieben ist etwas anderes."""
    server, konto = welt  # noqa: F811
    _mit_umbenennen(server)
    eltern = ordnerdienst.anlegen(db, konto, "Haus")
    kind = ordnerdienst.anlegen(db, konto, "Alt", eltern)

    neu = ordnerdienst.umbenennen(db, konto, kind, "Neu")

    assert neu.pfad == "Haus/Neu"


def test_unterordner_kommen_beim_umbenennen_mit(db, welt):
    server, konto = welt  # noqa: F811
    _mit_umbenennen(server)
    eltern = ordnerdienst.anlegen(db, konto, "Haus")
    ordnerdienst.anlegen(db, konto, "Rechnungen", eltern)

    ordnerdienst.umbenennen(db, konto, eltern, "Zuhause")

    pfade = sorted(o.pfad for o in konto.ordner)
    assert "Zuhause" in pfade
    assert "Zuhause/Rechnungen" in pfade


def test_ein_sonderordner_behaelt_seinen_namen(db, welt):
    """⚠️ Bei manchen Servern hängt die Rolle am Namen — ein umbenannter
    „Papierkorb" wäre danach ein gewöhnlicher Ordner, und das Löschen einer
    Mail fände sein Ziel nicht mehr."""
    server, konto = welt  # noqa: F811
    _mit_umbenennen(server)
    papierkorb = Ordner(
        konto_id=konto.id, pfad="Papierkorb", name="Papierkorb", rolle="papierkorb"
    )
    db.add(papierkorb)
    db.commit()

    with pytest.raises(ordnerdienst.OrdnerFehler):
        ordnerdienst.umbenennen(db, konto, papierkorb, "Mülleimer")

    assert server.umbenannt == []


def test_ein_belegter_name_wird_abgewiesen(db, welt):
    server, konto = welt  # noqa: F811
    _mit_umbenennen(server)
    ordnerdienst.anlegen(db, konto, "Eins")
    zwei = ordnerdienst.anlegen(db, konto, "Zwei")

    with pytest.raises(ordnerdienst.OrdnerFehler) as fehler:
        ordnerdienst.umbenennen(db, konto, zwei, "Eins")

    assert "schon" in str(fehler.value)
    assert server.umbenannt == []
