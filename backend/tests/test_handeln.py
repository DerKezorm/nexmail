"""Verschieben, archivieren, löschen — und zurücknehmen.

⚠️ **Jeder Test hier prüft, dass der Server es auch erfahren hat.** Eine
Anwendung, die eine Mail nur lokal wegräumt, macht ihrem Besitzer etwas vor:
Auf dem Telefon liegt sie weiter im Posteingang, und beim nächsten Abgleich
springt sie hier zurück.
"""

from __future__ import annotations

import pytest

from app.models import Nachricht, Ordner
from app.services import abgleich, handeln
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


class Server(FalscherServer):
    """Der Doppelgänger, jetzt auch mit Schreibbefehlen."""

    def __init__(self, kann_move: bool = True):
        super().__init__()
        self.kann_move = kann_move
        self.protokoll: list[str] = []

    def capabilities(self):
        grund = [b"IMAP4REV1", b"IDLE", b"UIDPLUS"]
        return grund + ([b"MOVE"] if self.kann_move else [])

    def move(self, uids, ziel):
        self.protokoll.append(f"MOVE {sorted(uids)} -> {ziel}")
        self._umhaengen(uids, ziel)

    def copy(self, uids, ziel):
        self.protokoll.append(f"COPY {sorted(uids)} -> {ziel}")
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"][uid]
            neue = max(self.ordner[ziel]["nachrichten"] or [0]) + 1
            self.ordner[ziel]["nachrichten"][neue] = dict(eintrag)

    def add_flags(self, uids, flags):
        self.protokoll.append(f"STORE +{[f.decode() for f in flags]} {sorted(uids)}")
        for uid in uids:
            if rb"\Deleted" in flags:
                self.ordner[self._aktuell]["nachrichten"][uid]["geloescht"] = True

    def remove_flags(self, uids, flags):  # noqa: ARG002
        self.protokoll.append("STORE -")

    def uid_expunge(self, uids):
        self.protokoll.append(f"UID EXPUNGE {sorted(uids)}")
        for uid in uids:
            self.ordner[self._aktuell]["nachrichten"].pop(uid, None)

    def expunge(self):
        self.protokoll.append("EXPUNGE (blank)")
        weg = [
            uid
            for uid, e in self.ordner[self._aktuell]["nachrichten"].items()
            if e.get("geloescht")
        ]
        for uid in weg:
            del self.ordner[self._aktuell]["nachrichten"][uid]

    def _umhaengen(self, uids, ziel):
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"].pop(uid)
            neue = max(self.ordner[ziel]["nachrichten"] or [0]) + 1
            self.ordner[ziel]["nachrichten"][neue] = eintrag

    def search(self, kriterien):
        if kriterien and kriterien[0] == "HEADER":
            gesucht = kriterien[2]
            # ⚠️ Wie ein echter Server: ``SEARCH HEADER`` ist nach RFC 3501
            # ein TEILSTRING-Vergleich. Ein Doppelgaenger, der exakt
            # vergleicht, machte den Exakt-Filter im Code unpruefbar — und
            # verdeckte, dass eine Kennung in einer anderen stecken kann.
            return [
                uid
                for uid, e in self.ordner[self._aktuell]["nachrichten"].items()
                if gesucht in (e.get("message_id") or "")
            ]
        return sorted(self.ordner[self._aktuell]["nachrichten"])


@pytest.fixture
def welt(db, konto, monkeypatch):  # noqa: F811
    """Ein Postfach mit Posteingang, Archiv und Papierkorb — und drei Mails."""
    for pfad, rolle in (("Archive", "archiv"), ("Deleted Messages", "papierkorb"),
                        ("Junk", "junk")):
        db.add(Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle=rolle))
    db.commit()
    db.refresh(konto)

    server = Server()
    for pfad in ("INBOX", "Archive", "Deleted Messages", "Junk"):
        server.anlegen(pfad)
    for uid, betreff in ((1, "Erste"), (2, "Zweite"), (3, "Dritte")):
        server.einwerfen("INBOX", uid, betreff)
        server.ordner["INBOX"]["nachrichten"][uid]["message_id"] = f"<{betreff[:8]}@x.example>"

    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)
    monkeypatch.setattr(handeln.imapdienst, "verbinden", lambda *a, **k: server)
    monkeypatch.setattr(handeln.imapdienst, "faehigkeiten",
                        lambda klient: [c.decode() for c in klient.capabilities()])

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)
    return server, konto, posteingang


def _mail(db, betreff: str) -> Nachricht:
    return db.query(Nachricht).filter(Nachricht.betreff == betreff).one()


def test_verschieben_geht_ueber_move(db, welt):
    server, konto, posteingang = welt
    archiv = next(o for o in konto.ordner if o.rolle == "archiv")

    weg = handeln.verschieben(db, [_mail(db, "Zweite")], archiv)

    assert any(z.startswith("MOVE") for z in server.protokoll)
    assert len(server.ordner["Archive"]["nachrichten"]) == 1
    assert weg.ziel_pfad == "Archive"
    # Nicht mehr im Posteingang ...
    im_posteingang = [n.betreff for n in db.query(Nachricht).filter_by(ordner_id=posteingang.id)]
    assert "Zweite" not in im_posteingang
    # ... aber sehr wohl im Archiv.
    im_archiv = [n.betreff for n in db.query(Nachricht).filter_by(ordner_id=archiv.id)]
    assert im_archiv == ["Zweite"]


def test_rueckfall_ohne_move(db, welt):
    """⚠️ Ältere Server kennen MOVE nicht.

    Ohne Rückfallebene funktioniert das Verschieben dann bei manchen
    Postfächern und bei anderen nicht.
    """
    server, konto, _ = welt
    server.kann_move = False
    archiv = next(o for o in konto.ordner if o.rolle == "archiv")

    handeln.verschieben(db, [_mail(db, "Erste")], archiv)

    assert any(z.startswith("COPY") for z in server.protokoll)
    assert any("Deleted" in z for z in server.protokoll)
    # ⚠️ UID EXPUNGE, nicht das blanke EXPUNGE: Das räumt sonst alles ab, was
    # irgendwer als gelöscht markiert hat.
    assert any(z.startswith("UID EXPUNGE") for z in server.protokoll)
    assert not any(z.startswith("EXPUNGE (blank)") for z in server.protokoll)

    assert len(server.ordner["Archive"]["nachrichten"]) == 1
    assert 1 not in server.ordner["INBOX"]["nachrichten"]


def test_loeschen_geht_in_den_papierkorb(db, welt):
    """Nicht endgültig — dafür gibt es „Ordner leeren"."""
    server, konto, _ = welt
    papierkorb = next(o for o in konto.ordner if o.rolle == "papierkorb")

    handeln.in_rolle(db, [_mail(db, "Dritte")], "papierkorb")

    assert len(server.ordner["Deleted Messages"]["nachrichten"]) == 1
    # ⚠️ **Der Punkt dieses Tests, seit dem 31.08.2026.** Früher stand hier
    # ``count() == 2``: Die Zeile verschwand lokal und der Papierkorb blieb
    # leer, bis jemand von Hand abglich. Wer eine Mail löscht und sie nirgends
    # wiederfindet, hält das für Datenverlust - zu Recht.
    im_papierkorb = [n.betreff for n in db.query(Nachricht).filter_by(ordner_id=papierkorb.id)]
    assert im_papierkorb == ["Dritte"], (
        "Die gelöschte Nachricht steht nicht im Papierkorb. In der Oberfläche "
        "wäre sie damit spurlos weg."
    )


def test_mehrere_auf_einmal(db, welt):
    server, konto, _ = welt
    archiv = next(o for o in konto.ordner if o.rolle == "archiv")

    weg = handeln.verschieben(db, [_mail(db, "Erste"), _mail(db, "Zweite")], archiv)

    assert len(weg.message_ids) == 2
    assert len(server.ordner["Archive"]["nachrichten"]) == 2
    im_archiv = sorted(n.betreff for n in db.query(Nachricht).filter_by(ordner_id=archiv.id))
    assert im_archiv == ["Erste", "Zweite"]


def test_zurueck_holt_die_mail_wieder(db, welt):
    """⚠️ Gesucht wird über die Message-ID.

    Beim Verschieben vergibt der Zielordner eine neue Nummer — die alte gilt
    dort nicht, und bei einem Server ohne UIDPLUS erfährt man die neue nie.
    """
    server, konto, _ = welt
    archiv = next(o for o in konto.ordner if o.rolle == "archiv")

    weg = handeln.verschieben(db, [_mail(db, "Zweite")], archiv)
    assert len(server.ordner["Archive"]["nachrichten"]) == 1

    zurueck = handeln.zurueck(db, weg)

    assert zurueck == 1
    assert len(server.ordner["Archive"]["nachrichten"]) == 0
    assert len(server.ordner["INBOX"]["nachrichten"]) == 3


def test_verschieben_zwischen_postfaechern_geht_einen_anderen_weg(db, welt, klient):
    """⚠️ **Diese Regel wurde am 02.09.2026 aufgehoben, nicht vergessen.**

    Hier stand bis dahin „geht gar nicht", und der Grund war richtig: Ein
    ``MOVE`` oder ``COPY`` wirkt nur innerhalb einer Verbindung, und eine
    Oberfläche, die es trotzdem anbietet, sähe aus, als ginge es.

    Der Ausweg ist ein anderer Vorgang, kein aufgeweichter alter: holen, beim
    Ziel anhängen, nachsehen, dann bei der Quelle löschen
    (``handeln.ueber_konten``). Was dieser Test noch festhält, ist die
    Weiterleitung dorthin — dass ``verschieben`` die Grenze erkennt und **nicht**
    versucht, sie mit einem COPY zu überfahren. Der Vorgang selbst steht unter
    Wache in ``test_ueber_konten.py``.
    """
    from app.models import Benutzer
    from app.services import konten

    _, konto, _ = welt
    person = db.query(Benutzer).one()
    zweites = konten.anlegen(
        db,
        person,
        konten.Zugangsdaten("Zweit", "zweit@b.example", "i", 993, "ssl", "u", "p",
                            "s", 587, "starttls", "u", "p"),
    )
    fremd = Ordner(konto_id=zweites.id, pfad="Archive", name="Archive", rolle="archiv")
    db.add(fremd)
    db.commit()

    gerufen: list[str] = []
    import app.services.handeln as modul

    echt = modul.ueber_konten
    monkey = pytest.MonkeyPatch()
    monkey.setattr(modul, "ueber_konten", lambda *a, **k: gerufen.append("ueber_konten") or echt(*a, **k))
    try:
        with pytest.raises(Exception):
            # Der Doppelgaenger dieses Tests kennt kein APPEND — der Vorgang
            # scheitert also. Wichtig ist, DASS er gewaehlt wurde.
            handeln.verschieben(db, [_mail(db, "Erste")], fremd)
    finally:
        monkey.undo()

    assert gerufen == ["ueber_konten"], (
        "Der Zug ueber die Kontogrenze wurde nicht an ueber_konten weitergereicht."
    )


def test_nicht_in_denselben_ordner(db, welt):
    _, konto, posteingang = welt
    with pytest.raises(handeln.HandelnFehler, match="liegt_schon_dort"):
        handeln.verschieben(db, [_mail(db, "Erste")], posteingang)


def test_ohne_zielordner_klare_ansage(db, welt, konto):  # noqa: F811
    """Nicht jedes Postfach hat ein Archiv. Dann sagt es das."""
    _, konto_aus_welt, _ = welt
    archiv = next(o for o in konto_aus_welt.ordner if o.rolle == "archiv")
    db.delete(archiv)
    db.commit()
    db.refresh(konto_aus_welt)

    with pytest.raises(handeln.HandelnFehler, match="rolle_ohne_ordner"):
        handeln.in_rolle(db, [_mail(db, "Erste")], "archiv")


def test_leeren_nur_fuer_papierkorb_und_junk(db, welt):
    """⚠️ Der einzige Vorgang ohne Rückweg — deshalb eng begrenzt."""
    _, konto, posteingang = welt
    with pytest.raises(handeln.HandelnFehler, match="nur_papierkorb_und_junk"):
        handeln.ordner_leeren(db, posteingang)


def test_papierkorb_leeren(db, welt):
    server, konto, _ = welt
    handeln.in_rolle(db, [_mail(db, "Erste")], "papierkorb")

    papierkorb = next(o for o in konto.ordner if o.rolle == "papierkorb")
    abgleich.ordner_abgleichen(server, db, konto, papierkorb)
    assert db.query(Nachricht).filter(Nachricht.ordner_id == papierkorb.id).count() == 1

    weg = handeln.ordner_leeren(db, papierkorb)

    assert weg == 1
    assert len(server.ordner["Deleted Messages"]["nachrichten"]) == 0
    assert db.query(Nachricht).filter(Nachricht.ordner_id == papierkorb.id).count() == 0


def test_zaehler_stimmen_nach_dem_zug(db, welt):
    _, konto, posteingang = welt
    db.refresh(posteingang)
    vorher = posteingang.anzahl

    handeln.in_rolle(db, [_mail(db, "Erste")], "papierkorb")

    db.refresh(posteingang)
    assert posteingang.anzahl == vorher - 1
    assert posteingang.ungelesen == 2


# --- Über die Schnittstelle ---------------------------------------------- #


def test_fremde_nachricht_laesst_sich_nicht_verschieben(klient, zweiter_klient, db, welt):
    """⚠️ Eine Liste von Kennungen ist der bequemste Weg, fremde Post mitzunehmen."""
    from conftest import anmelden, zweiten_benutzer_anlegen

    _, konto, _ = welt
    meine = _mail(db, "Erste").id
    archiv = next(o for o in konto.ordner if o.rolle == "archiv")

    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    antwort = zweiter_klient.post(
        "/api/nachrichten/verschieben", json={"ids": [meine], "ordner_id": archiv.id}
    )
    assert antwort.status_code == 404
    assert db.query(Nachricht).filter(Nachricht.id == meine).count() == 1


def test_fremde_mail_in_den_eigenen_ordner_geht_nicht(klient, zweiter_klient, db, welt):
    """⚠️ **Der eigentliche Angriff** — und der Test, der gefehlt hat.

    Der vorige prüft zu wenig: Dort gehört auch der Zielordner dem anderen,
    also greift schon dessen Prüfung. Gefährlich ist der andere Fall: Der
    Angreifer nennt **seinen eigenen** Ordner als Ziel und fremde Nachrichten
    als Fracht. Ohne Besitzprüfung an jeder einzelnen Kennung wandert dann
    fremde Post in sein Postfach.

    Geprüft wird auf **404**, nicht nur „geht nicht": Ein 400 mit „gehört zu
    einem anderen Postfach" verrät bereits, dass es diese Nachricht gibt.
    """
    from conftest import anmelden, zweiten_benutzer_anlegen
    from app.services import konten

    _, konto, _ = welt
    fremde_mail = _mail(db, "Erste").id

    zweiter, geheimnis2 = zweiten_benutzer_anlegen(db)
    eigenes = konten.anlegen(
        db,
        zweiter,
        konten.Zugangsdaten("Meins", "zweit@b.example", "i", 993, "ssl", "u", "p",
                            "s", 587, "starttls", "u", "p"),
    )
    eigener_ordner = Ordner(konto_id=eigenes.id, pfad="Archive", name="Archive", rolle="archiv")
    db.add(eigener_ordner)
    db.commit()

    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)
    antwort = zweiter_klient.post(
        "/api/nachrichten/verschieben",
        json={"ids": [fremde_mail], "ordner_id": eigener_ordner.id},
    )

    assert antwort.status_code == 404, (
        "Die fremde Nachricht wurde nicht als „gibt es nicht“ abgewiesen - "
        f"stattdessen {antwort.status_code}: {antwort.text}"
    )
    assert db.query(Nachricht).filter(Nachricht.id == fremde_mail).count() == 1


def test_leeren_fremder_ordner_geht_nicht(klient, zweiter_klient, db, welt):
    from conftest import anmelden, zweiten_benutzer_anlegen

    _, konto, _ = welt
    papierkorb = next(o for o in konto.ordner if o.rolle == "papierkorb")

    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    antwort = zweiter_klient.post(f"/api/nachrichten/ordner/{papierkorb.id}/leeren")
    assert antwort.status_code == 404


# --- Wenn das Postfach nicht antwortet -------------------------------------- #


def test_ein_unerreichbares_postfach_gibt_keinen_500(klient, db, monkeypatch):
    """⚠️ **Aus Schaden entstanden, 01.09.2026.**

    „Markieren" gab einen nackten 500er zurück, weil das Postfach-Passwort
    nicht mehr stimmte. Die Oberfläche zeigte „Das hat nicht geklappt", und im
    Protokoll stand ein Stacktrace. Dabei ist ein Postfach, das die Anmeldung
    abweist, kein Programmfehler — sondern etwas, das der Betreiber richten
    kann, sobald man es ihm sagt.

    Der Auffangbehandler in ``main.py`` macht daraus 502 mit einem Satz.
    Geprüft wird an **einer** Adresse stellvertretend für alle: Genau darum
    steht er zentral und nicht je Route.
    """
    from datetime import datetime, timezone

    from app.models import Konto, Nachricht, Ordner, neue_id
    from app.services import imap as imapdienst
    from conftest import einrichten

    daten = einrichten(klient)
    assert daten

    person = db.query(__import__("app.models", fromlist=["Benutzer"]).Benutzer).first()
    konto = Konto(
        id=neue_id(),
        benutzer_id=person.id,
        anzeigename="Test",
        adresse="ich@example.org",
        imap_server="imap.example.org",
        imap_port=993,
        imap_sicherheit="ssl",
        imap_benutzer="ich@example.org",
        smtp_server="smtp.example.org",
        smtp_port=465,
        smtp_sicherheit="ssl",
        smtp_benutzer="ich@example.org",
    )
    db.add(konto)
    db.flush()
    ordner = Ordner(konto_id=konto.id, pfad="INBOX", name="INBOX", rolle="posteingang")
    db.add(ordner)
    db.flush()
    nachricht = Nachricht(
        benutzer_id=person.id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=1,
        betreff="Egal",
        datum=datetime.now(timezone.utc),
    )
    db.add(nachricht)
    db.commit()

    def abgewiesen(*_a, **_k):
        raise imapdienst.Verbindungsfehler(
            imapdienst.Fehlerart.ANMELDUNG,
            "Benutzername oder Passwort wurde abgewiesen.",
            "AUTHENTICATIONFAILED",
        )

    monkeypatch.setattr(imapdienst, "verbinden", abgewiesen)

    antwort = klient.post(f"/api/nachrichten/{nachricht.id}/flags", json={"markiert": True})

    assert antwort.status_code == 502, f"Erwartet 502, bekommen {antwort.status_code}."
    assert "abgewiesen" in antwort.json()["detail"], "Die Meldung sagt nicht, was los ist."
