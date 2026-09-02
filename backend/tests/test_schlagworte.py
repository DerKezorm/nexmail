"""Schlagworte an einzelnen Mails — als IMAP-Keywords, gegen den Doppelgänger.

⚠️ **Drei Dinge stehen hier unter Wache**, und jedes davon täte im Betrieb
lautlos weh:

1. **Erst der Server, dann lokal.** Ein Schlagwort, das nur in nexmails
   Datenbank steht, fehlt am Telefon und verschwindet beim nächsten Abgleich.
2. **Fremde Atome legen ihre Definition selbst an.** Sonst klebt ein
   Thunderbird-Keyword unsichtbar an der Mail.
3. **Die Trennung zweier Benutzer.** Schlagworte sind personenbezogen.
"""

from __future__ import annotations

import json

import pytest

from app.models import Nachricht, Ordner, Schlagwort
from app.services import abgleich, imap as imapdienst, schlagworte as dienst
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


class Server(FalscherServer):
    """Der Doppelgänger, jetzt mit STORE für Keywords."""

    def __init__(self):
        super().__init__()
        self.protokoll: list[str] = []

    def add_flags(self, uids, flags):
        woerter = [f.decode() if isinstance(f, bytes) else str(f) for f in flags]
        self.protokoll.append(f"STORE +{woerter} {sorted(uids)}")
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"][uid]
            for wort in woerter:
                if wort.startswith("\\"):
                    continue
                # Keywords gelten ohne Gross/klein — wie beim echten Server.
                if wort.lower() not in {w.lower() for w in eintrag["schlagworte"]}:
                    eintrag["schlagworte"].append(wort)

    def remove_flags(self, uids, flags):
        woerter = [f.decode() if isinstance(f, bytes) else str(f) for f in flags]
        self.protokoll.append(f"STORE -{woerter} {sorted(uids)}")
        klein = {w.lower() for w in woerter}
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"][uid]
            eintrag["schlagworte"] = [
                w for w in eintrag["schlagworte"] if w.lower() not in klein
            ]


@pytest.fixture
def welt(db, konto, monkeypatch):  # noqa: F811
    """Ein Postfach mit drei Mails im Posteingang, schon abgeglichen."""
    server = Server()
    server.anlegen("INBOX")
    for uid, betreff in ((1, "Erste"), (2, "Zweite"), (3, "Dritte")):
        server.einwerfen("INBOX", uid, betreff)

    # ⚠️ Ein Patch genuegt: alle Dienste teilen sich das Modul services/imap.
    monkeypatch.setattr(imapdienst, "verbinden", lambda *a, **k: server)

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)
    return server, konto, posteingang


def _mail(db, betreff: str) -> Nachricht:
    return db.query(Nachricht).filter(Nachricht.betreff == betreff).one()


# --- Das Atom aus dem Namen ---------------------------------------------- #


def test_atom_aus_name_umschreibt_umlaute_und_leerzeichen():
    assert dienst.atom_aus_name("Büro Köln") == "Buero_Koeln"
    assert dienst.atom_aus_name("Straße") == "Strasse"
    assert dienst.atom_aus_name("Zu erledigen!") == "Zu_erledigen"
    assert dienst.atom_aus_name("a/b(c)*d") == "abcd"
    # Ein Name nur aus Sonderzeichen darf kein leeres Flag ergeben.
    assert dienst.atom_aus_name("!!!") == "Schlagwort"


def test_kollision_haengt_eine_zahl_an(klient, db):
    """„Büro" und „Buero" ergeben dasselbe Atom — das zweite wird nummeriert."""
    from conftest import einrichten

    einrichten(klient)
    from app.models import Benutzer

    person = db.query(Benutzer).one()
    erstes = dienst.anlegen(db, person.id, "Büro")
    zweites = dienst.anlegen(db, person.id, "Buero")
    assert erstes.atom == "Buero"
    assert zweites.atom == "Buero2"


def test_gleicher_name_wird_abgewiesen(klient, db):
    """„Privat" und „privat" wären zwei Marken, die gleich aussehen."""
    from conftest import einrichten

    einrichten(klient)
    from app.models import Benutzer

    person = db.query(Benutzer).one()
    dienst.anlegen(db, person.id, "Privat")
    with pytest.raises(dienst.SchlagwortFehler, match="schlagwort_name_vergeben"):
        dienst.anlegen(db, person.id, "privat")


# --- Abgleich: Atome aus FLAGS -------------------------------------------- #


def test_atome_kommen_aus_den_flags(db, konto):  # noqa: F811
    """Nicht-Systemflags werden übernommen — Systemflags nie."""
    server = Server()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Markiert", gelesen=True, schlagworte=["Arbeit", "Projekt-X"])

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)

    zeile = db.query(Nachricht).one()
    atome = json.loads(zeile.schlagworte)
    assert atome == ["Arbeit", "Projekt-X"]
    # ⚠️ \Seen ist als gelesen angekommen, nicht als Schlagwort.
    assert zeile.gelesen is True
    assert not any(a.startswith("\\") for a in atome)


def test_fremdes_atom_legt_selbst_eine_definition_an(db, konto):  # noqa: F811
    """⚠️ Der Interop-Gewinn: Was Thunderbird vergibt, erscheint hier —
    statt unsichtbar an der Mail zu kleben."""
    server = Server()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Von drüben", schlagworte=["Steuern2026"])

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)

    zeile = db.query(Schlagwort).one()
    assert zeile.name == "Steuern2026"
    assert zeile.atom == "Steuern2026"
    assert zeile.farbe == 1
    assert zeile.benutzer_id == konto.benutzer_id


def test_thunderbird_marken_bekommen_ihre_namen(db, konto):  # noqa: F811
    """$label1..$label5 heißen Important, Work, Personal, To Do, Later."""
    server = Server()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Getaggt", schlagworte=["$label1", "$label4"])

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)

    namen = {z.atom: z.name for z in db.query(Schlagwort).all()}
    assert namen == {"$label1": "Important", "$label4": "To Do"}
    # Zwei Definitionen, zwei verschiedene Farben aus der Palette.
    farben = [z.farbe for z in db.query(Schlagwort).all()]
    assert sorted(farben) == [1, 2]


def test_technische_keywords_bleiben_draussen(db, konto):  # noqa: F811
    """$Forwarded und NonJunk setzt Software — kein Client zeigt sie als Marke."""
    server = Server()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Weitergeleitet", schlagworte=["$Forwarded", "NonJunk"])

    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)

    assert db.query(Schlagwort).count() == 0
    assert json.loads(db.query(Nachricht).one().schlagworte) == []


def test_das_flags_fenster_zieht_schlagworte_nach(db, welt):
    """Wer am Telefon eine Marke setzt, sieht sie hier nach dem nächsten
    Abgleich — ohne dass die Mail neu geholt wird."""
    server, konto, posteingang = welt
    server.ordner["INBOX"]["nachrichten"][1]["schlagworte"] = ["Reise"]

    abgleich.ordner_abgleichen(server, db, konto, posteingang)

    db.expire_all()
    assert json.loads(_mail(db, "Erste").schlagworte) == ["Reise"]
    # Und auch hier entsteht die Definition von selbst.
    assert db.query(Schlagwort).filter(Schlagwort.atom == "Reise").count() == 1


# --- Zuweisen: erst der Server, dann lokal --------------------------------- #


def _definition_anlegen(klient, name: str = "Wichtig") -> dict:
    antwort = klient.post("/api/schlagworte", json={"name": name})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_zuweisen_schreibt_zum_server_und_dann_lokal(klient, db, welt):
    server, _, _ = welt
    _definition_anlegen(klient)
    mail = _mail(db, "Zweite")

    antwort = klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": [mail.id]})

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["beruehrt"] == 1
    # Beim Server angekommen ...
    assert any(z.startswith("STORE +['Wichtig']") for z in server.protokoll)
    assert server.ordner["INBOX"]["nachrichten"][2]["schlagworte"] == ["Wichtig"]
    # ... und lokal nachgezogen.
    db.expire_all()
    assert json.loads(_mail(db, "Zweite").schlagworte) == ["Wichtig"]


def test_wegnehmen_geht_denselben_weg(klient, db, welt):
    server, _, _ = welt
    _definition_anlegen(klient)
    mail = _mail(db, "Zweite")
    klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": [mail.id]})

    antwort = klient.request(
        "DELETE", "/api/nachrichten/schlagworte/Wichtig", json={"ids": [mail.id]}
    )

    assert antwort.status_code == 200, antwort.text
    assert any(z.startswith("STORE -['Wichtig']") for z in server.protokoll)
    assert server.ordner["INBOX"]["nachrichten"][2]["schlagworte"] == []
    db.expire_all()
    assert json.loads(_mail(db, "Zweite").schlagworte) == []


def test_mehrfachauswahl_ist_ein_store_je_ordner(klient, db, welt):
    server, _, _ = welt
    _definition_anlegen(klient)
    ids = [_mail(db, "Erste").id, _mail(db, "Dritte").id]

    antwort = klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": ids})

    assert antwort.json()["beruehrt"] == 2
    stores = [z for z in server.protokoll if z.startswith("STORE +")]
    assert len(stores) == 1, "Je Ordner ein STORE — nicht einer je Nachricht."


def test_wirft_der_server_bleibt_lokal_alles_wie_es_war(klient, db, welt, monkeypatch):
    """⚠️ **Die Reihenfolge, prüfbar gemacht.** Weist der Server den STORE ab,
    darf nexmails Datenbank nichts wissen, was der Server nie erfahren hat.
    Wer die Reihenfolge im Dienst umdreht, sieht diesen Test rot.

    ⚠️ **Es scheitert der STORE selbst, nicht schon das Verbinden.** Ein Test,
    der nur die Verbindung kappt, ist gegen die umgedrehte Reihenfolge blind:
    Dann läuft auch die lokale Änderung nie an, und die Mutation bliebe grün —
    genau so beim ersten Probelauf passiert."""
    server, _, _ = welt
    _definition_anlegen(klient)
    mail_id = _mail(db, "Zweite").id

    def abgewiesen(*_a, **_k):
        raise imapdienst.Verbindungsfehler(
            imapdienst.Fehlerart.UNERWARTET,
            "Unerwartete Antwort des Servers.",
            "NO STORE rejected",
        )

    monkeypatch.setattr(server, "add_flags", abgewiesen)
    antwort = klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": [mail_id]})

    assert antwort.status_code == 502
    db.expire_all()
    assert json.loads(db.get(Nachricht, mail_id).schlagworte) == [], (
        "Der Server hat abgelehnt, aber lokal steht das Schlagwort trotzdem da — "
        "die Reihenfolge „erst der Server, dann lokal“ ist verletzt."
    )


def test_server_ohne_stern_gibt_die_kennung(klient, db, welt):
    """⚠️ PERMANENTFLAGS ohne \\* heißt: keine eigenen Keywords. Die Antwort
    ist eine KENNUNG, kein deutscher Satz — die Oberfläche übersetzt sie."""
    server, _, _ = welt
    server.eigene_keywords = False
    _definition_anlegen(klient)
    mail_id = _mail(db, "Zweite").id

    antwort = klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": [mail_id]})

    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "schlagworte_nicht_unterstuetzt"
    # Kein STORE hinausgegangen, lokal nichts geändert.
    assert not any(z.startswith("STORE") for z in server.protokoll)
    db.expire_all()
    assert json.loads(db.get(Nachricht, mail_id).schlagworte) == []


def test_gewechselte_uidvalidity_stoppt_den_store(klient, db, welt):
    """⚠️ Nach einem UIDVALIDITY-Wechsel zaehlt der Server neu — ein STORE
    auf die gespeicherten UIDs traefe ANDERE Nachrichten, wuerde mit OK
    beantwortet, und lokal wuerde die gemeinte verbucht. Bis der Abgleich
    den Ordner neu aufgebaut hat, wird abgelehnt."""
    server, _, _ = welt
    _definition_anlegen(klient)
    mail_id = _mail(db, "Zweite").id
    server.ordner["INBOX"]["uidvalidity"] = 999  # der Server hat neu gezaehlt

    antwort = klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": [mail_id]})

    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "schlagwort_ordner_veraltet"
    # Kein STORE hinausgegangen, lokal nichts geaendert.
    assert not any(z.startswith("STORE") for z in server.protokoll)
    db.expire_all()
    assert json.loads(db.get(Nachricht, mail_id).schlagworte) == []


def test_auch_das_loeschen_prueft_die_uidvalidity(klient, db, welt):
    """Dasselbe Loch beim Loeschen: remove_flags auf alten UIDs traefe nach
    dem Wechsel andere Mails. Die Definition bleibt dann stehen."""
    server, _, _ = welt
    zeile = _definition_anlegen(klient)
    klient.post(
        "/api/nachrichten/schlagworte/Wichtig", json={"ids": [_mail(db, "Erste").id]}
    )
    server.protokoll.clear()
    server.ordner["INBOX"]["uidvalidity"] = 999

    antwort = klient.delete(f"/api/schlagworte/{zeile['id']}")

    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "schlagwort_ordner_veraltet"
    assert not any(z.startswith("STORE") for z in server.protokoll)
    assert db.query(Schlagwort).count() == 1
    # Und das Keyword steht weiter auf der Server-Mail.
    assert server.ordner["INBOX"]["nachrichten"][1]["schlagworte"] == ["Wichtig"]


def test_ein_scheiternder_zweiter_ordner_rollt_den_ersten_nicht_zurueck(
    klient, db, welt, monkeypatch
):
    """⚠️ Der erste Ordner ist auf dem Server schon angenommen — scheitert
    der zweite, darf die Datenbank das Angenommene nicht wieder vergessen,
    sonst laufen Server und nexmail auseinander. Und ein roher IMAP-Fehler
    auf stehender Verbindung kommt als Verbindungsfehler heraus (502), nicht
    als nackter 500."""
    from app.models import Benutzer

    server, konto, posteingang = welt
    _definition_anlegen(klient)

    server.anlegen("Archiv")
    server.einwerfen("Archiv", 1, "Abgelegt")
    archiv = Ordner(konto_id=konto.id, pfad="Archiv", name="Archiv", rolle="")
    db.add(archiv)
    db.commit()
    db.refresh(konto)
    abgleich.ordner_abgleichen(server, db, konto, archiv)

    echt = server.add_flags

    def waehlerisch(uids, flags):
        if server._aktuell == "Archiv":
            raise RuntimeError("NO STORE failed")
        return echt(uids, flags)

    monkeypatch.setattr(server, "add_flags", waehlerisch)
    person = db.query(Benutzer).filter(Benutzer.benutzername == "betreiber").one()

    with pytest.raises(imapdienst.Verbindungsfehler):
        dienst.zuweisen(
            db, person, [_mail(db, "Erste"), _mail(db, "Abgelegt")], "Wichtig", True
        )

    db.rollback()
    db.expire_all()
    # Der Posteingang war durch — Server UND Datenbank wissen es.
    assert server.ordner["INBOX"]["nachrichten"][1]["schlagworte"] == ["Wichtig"]
    assert json.loads(_mail(db, "Erste").schlagworte) == ["Wichtig"]
    # Das Archiv hat nie angenommen — lokal steht dort auch nichts.
    assert dienst.atome_lesen(_mail(db, "Abgelegt")) == []


def test_unbekanntes_atom_gibt_404(klient, db, welt):
    mail_id = _mail(db, "Erste").id
    antwort = klient.post("/api/nachrichten/schlagworte/GibtEsNicht", json={"ids": [mail_id]})
    assert antwort.status_code == 404


# --- Filter ----------------------------------------------------------------- #


def test_der_filter_liefert_nur_markierte(klient, db, welt):
    _, _, posteingang = welt
    _definition_anlegen(klient)
    klient.post(
        "/api/nachrichten/schlagworte/Wichtig", json={"ids": [_mail(db, "Zweite").id]}
    )

    antwort = klient.get(
        f"/api/nachrichten?ordner_id={posteingang.id}&schlagwort=Wichtig"
    )

    betreffe = [z["betreff"] for z in antwort.json()]
    assert betreffe == ["Zweite"], (
        "Der Schlagwort-Filter muss im Server greifen und genau die markierten "
        f"Mails liefern — bekommen: {betreffe}"
    )
    # Und die Zeilen tragen ihre Atome für die Farbmarken.
    assert antwort.json()[0]["schlagworte"] == ["Wichtig"]


def test_der_filter_laeuft_ohne_gross_klein(klient, db, welt):
    """IMAP-Keywords gelten ohne Groß/klein — der Filter auch."""
    _, _, posteingang = welt
    _definition_anlegen(klient)
    klient.post(
        "/api/nachrichten/schlagworte/Wichtig", json={"ids": [_mail(db, "Dritte").id]}
    )

    antwort = klient.get(
        f"/api/nachrichten?ordner_id={posteingang.id}&schlagwort=wichtig"
    )
    assert [z["betreff"] for z in antwort.json()] == ["Dritte"]


# --- Verwalten -------------------------------------------------------------- #


def test_umbenennen_aendert_nur_den_namen(klient, db, welt):
    zeile = _definition_anlegen(klient, "Büro")
    assert zeile["atom"] == "Buero"

    antwort = klient.patch(f"/api/schlagworte/{zeile['id']}", json={"name": "Kanzlei"})

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["name"] == "Kanzlei"
    # ⚠️ Das Atom bleibt — es steht als Keyword auf dem Server.
    assert antwort.json()["atom"] == "Buero"


def test_farbe_nur_aus_der_palette(klient, welt):
    zeile = _definition_anlegen(klient)
    gut = klient.patch(f"/api/schlagworte/{zeile['id']}", json={"farbe": 4})
    assert gut.status_code == 200
    assert gut.json()["farbe"] == 4

    schlecht = klient.patch(f"/api/schlagworte/{zeile['id']}", json={"farbe": 7})
    assert schlecht.status_code == 400
    assert schlecht.json()["detail"] == "schlagwort_farbe_unbekannt"


def test_loeschen_raeumt_server_flags_und_definition(klient, db, welt):
    """⚠️ Erst remove_flags auf allen bekannten Mails (je Ordner gebündelt),
    dann die lokale Spalte, dann die Definition."""
    server, _, _ = welt
    zeile = _definition_anlegen(klient)
    ids = [_mail(db, "Erste").id, _mail(db, "Dritte").id]
    klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": ids})

    # Die Liste nennt die Zahl, die die Rückfrage braucht.
    liste = klient.get("/api/schlagworte").json()
    assert liste[0]["anzahl"] == 2

    antwort = klient.delete(f"/api/schlagworte/{zeile['id']}")

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["entfernt"] == 2
    entfernt = [z for z in server.protokoll if z.startswith("STORE -['Wichtig']")]
    assert entfernt, "Das Keyword wurde nie vom Server genommen."
    for uid in (1, 3):
        assert server.ordner["INBOX"]["nachrichten"][uid]["schlagworte"] == []
    db.expire_all()
    for betreff in ("Erste", "Dritte"):
        assert json.loads(_mail(db, betreff).schlagworte) == []
    assert db.query(Schlagwort).count() == 0


def test_scheitert_der_server_bleibt_die_definition(klient, db, welt, monkeypatch):
    """Sonst stünde das Keyword weiter auf den Mails, wäre hier aber
    unsichtbar — und käme beim nächsten Abgleich als fremdes Atom wieder."""
    zeile = _definition_anlegen(klient)
    klient.post(
        "/api/nachrichten/schlagworte/Wichtig", json={"ids": [_mail(db, "Erste").id]}
    )

    def tot(*_a, **_k):
        raise imapdienst.Verbindungsfehler(
            imapdienst.Fehlerart.NICHT_ERREICHBAR, "Der Server antwortet nicht.", ""
        )

    monkeypatch.setattr(imapdienst, "verbinden", tot)
    antwort = klient.delete(f"/api/schlagworte/{zeile['id']}")

    assert antwort.status_code == 502
    assert db.query(Schlagwort).count() == 1


# --- Trennung zweier Benutzer ----------------------------------------------- #


def test_trennung_zweier_benutzer(klient, zweiter_klient, db, welt):
    """⚠️ Schlagworte sind personenbezogen: Der zweite sieht nichts, setzt
    nichts und löscht nichts vom ersten."""
    from conftest import anmelden, zweiten_benutzer_anlegen

    zeile = _definition_anlegen(klient)
    meine_mail = _mail(db, "Erste").id

    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    # Sehen: die Liste des zweiten ist leer.
    assert zweiter_klient.get("/api/schlagworte").json() == []

    # Setzen: fremde Mail und fremde Definition — 404, nichts verändert.
    antwort = zweiter_klient.post(
        "/api/nachrichten/schlagworte/Wichtig", json={"ids": [meine_mail]}
    )
    assert antwort.status_code == 404
    db.expire_all()
    assert json.loads(db.get(Nachricht, meine_mail).schlagworte) == []

    # Löschen: fremde Definition — 404, sie bleibt stehen.
    antwort = zweiter_klient.delete(f"/api/schlagworte/{zeile['id']}")
    assert antwort.status_code == 404
    assert db.query(Schlagwort).count() == 1

    # Und der Listenfilter des zweiten holt keine fremde Post heraus.
    klient.post("/api/nachrichten/schlagworte/Wichtig", json={"ids": [meine_mail]})
    fremd = zweiter_klient.get("/api/nachrichten?schlagwort=Wichtig")
    assert fremd.json() == []


def test_zwei_benutzer_koennen_dasselbe_atom_haben(klient, zweiter_klient, db, welt):
    """Die Eindeutigkeit gilt je Benutzer, nicht über alle."""
    from conftest import anmelden, zweiten_benutzer_anlegen

    _definition_anlegen(klient, "Wichtig")
    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    antwort = zweiter_klient.post("/api/schlagworte", json={"name": "Wichtig"})
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["atom"] == "Wichtig"
