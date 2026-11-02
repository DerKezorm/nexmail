"""Todo-Apps: Aufgaben aus Mails in Todoist, und der Haken kommt zurück.

Gesprochen wird mit einem nachgebauten Todoist (``Todoist`` unten), nicht mit
dem echten. ⚠️ **Das prüft nexmails Logik, nicht Todoist** (FALLSTRICKE §8):
Ob Todoist die Felder so versteht, sagt erst ein Lauf gegen ein echtes Konto.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from app.db import einstellung_schreiben
from app.models import Aufgabe, Aufgabenverbindung, Benutzer
from app.services import aufgabenziele, todoist
from conftest import anmelden, zweiten_benutzer_anlegen
from test_aufgaben import ohne_netz, welt  # noqa: F401

#: Bewusst kein echt aussehender Schlüssel: Die Scanner vor dem Push sollen
#: hier nicht anschlagen.
TOKEN = "probe-token-nur-fuer-tests"


class Todoist:
    """Ein kleines Todoist im Speicher, mit den Pfaden, die nexmail benutzt."""

    def __init__(self) -> None:
        self.projekte = [
            {"id": "p-arbeit", "name": "Arbeit", "parent_id": None},
            {"id": "p-eingang", "name": "Inbox", "inbox_project": True},
            {"id": "p-kunden", "name": "Kunden", "parent_id": "p-arbeit"},
            {"id": "p-alt", "name": "Alt", "is_archived": True},
        ]
        self.aufgaben: dict[str, dict] = {}
        self.anfragen: list[tuple[str, str]] = []
        self.rumpfe: list[dict] = []
        self.seitengroesse = 2
        self.naechste = 1
        #: Was jede Anfrage stattdessen bekommt, z. B. 401 oder 429.
        self.stoerung: int | None = None
        #: Liefert ``GET /tasks`` auch Erledigte? Das echte Todoist tut es
        #: nicht; nexmail soll sich darauf aber nicht verlassen.
        self.liste_mit_erledigten = False

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        pfad = anfrage.url.path.removeprefix("/api/v1/")
        self.anfragen.append((anfrage.method, pfad))
        assert anfrage.url.host == "api.todoist.com"
        if self.stoerung:
            return httpx.Response(self.stoerung, json={"error": "nope"})
        if anfrage.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error_tag": "UNAUTHORIZED", "http_code": 401})

        if anfrage.method == "GET" and pfad == "projects":
            return self._seite(self.projekte, anfrage)
        if anfrage.method == "POST" and pfad == "tasks":
            rumpf = json.loads(anfrage.content)
            self.rumpfe.append(rumpf)
            kennung = f"t{self.naechste}"
            self.naechste += 1
            due = {"date": rumpf["due_date"]} if "due_date" in rumpf else None
            self.aufgaben[kennung] = {
                "id": kennung,
                "content": rumpf["content"],
                "project_id": rumpf.get("project_id", "p-eingang"),
                "due": due,
                "checked": False,
                "completed_at": None,
            }
            return httpx.Response(200, json=self.aufgaben[kennung])
        if anfrage.method == "GET" and pfad == "tasks":
            ids = anfrage.url.params.get("ids", "").split(",")
            offen = [
                a
                for k, a in self.aufgaben.items()
                if k in ids
                and (self.liste_mit_erledigten or not a["checked"])
                and not a.get("is_deleted")
            ]
            return self._seite(offen, anfrage)
        if pfad.startswith("tasks/"):
            teile = pfad.split("/")
            a = self.aufgaben.get(teile[1])
            if a is None or a.get("is_deleted"):
                return httpx.Response(404, json={"error": "Task not found"})
            if anfrage.method == "GET" and len(teile) == 2:
                return httpx.Response(200, json=a)
            if anfrage.method == "POST" and teile[2:] == ["close"]:
                a["checked"], a["completed_at"] = True, "2026-11-02T10:00:00.000000Z"
                return httpx.Response(204)
            if anfrage.method == "POST" and teile[2:] == ["reopen"]:
                a["checked"], a["completed_at"] = False, None
                return httpx.Response(204)
        return httpx.Response(404)

    def _seite(self, zeilen: list[dict], anfrage: httpx.Request) -> httpx.Response:
        start = int(anfrage.url.params.get("cursor") or 0)
        ende = start + self.seitengroesse
        return httpx.Response(
            200,
            json={
                "results": zeilen[start:ende],
                "next_cursor": str(ende) if ende < len(zeilen) else None,
            },
        )

    def erledigen(self, kennung: str) -> None:
        self.aufgaben[kennung]["checked"] = True
        self.aufgaben[kennung]["completed_at"] = "2026-11-03T08:30:00Z"


@pytest.fixture
def fern(monkeypatch):
    dienst = Todoist()
    monkeypatch.setattr(todoist, "TRANSPORT", httpx.MockTransport(dienst))
    aufgabenziele._zuletzt_beim_oeffnen.clear()
    return dienst


@pytest.fixture
def verbunden(klient, welt, fern):  # noqa: F811
    antwort = klient.post("/api/aufgabenziele", json={"art": "todoist", "zugang": TOKEN})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def _anlegen(klient, nachricht_id, ziel, **mehr):
    return klient.post(
        "/api/aufgaben/mit-ziel", json={"nachricht_id": nachricht_id, "ziel": ziel, **mehr}
    )


# --- Verbinden ------------------------------------------------------------- #


def test_ein_guter_token_wird_verschluesselt_gespeichert(klient, verbunden, db):
    zeile = db.get(Aufgabenverbindung, verbunden)
    assert zeile.art == "todoist"
    assert TOKEN not in zeile.zugang
    assert aufgabenziele._zugang(zeile) == TOKEN

    stand = klient.get("/api/aufgabenziele").text
    assert TOKEN not in stand
    assert TOKEN[-4:] not in stand


def test_ein_abgelehnter_token_wird_nie_gespeichert(klient, welt, fern, db):  # noqa: F811
    antwort = klient.post("/api/aufgabenziele", json={"art": "todoist", "zugang": "falsch"})
    # ⚠️ 409, nicht 401: Die Oberfläche meldete bei 401 aus nexmail ab.
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "todoist_zugang_ungueltig"
    assert db.query(Aufgabenverbindung).count() == 0


def test_eine_unbekannte_art_wird_abgewiesen(klient, welt, fern):  # noqa: F811
    antwort = klient.post("/api/aufgabenziele", json={"art": "anderswo", "zugang": TOKEN})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "aufgabenart_unbekannt"


def test_die_listen_kommen_ueber_alle_seiten_eingang_zuerst(klient, verbunden, fern):
    gruppen = klient.get("/api/aufgabenziele/listen").json()
    assert len(gruppen) == 1
    namen = [l["name"] for l in gruppen[0]["listen"]]
    # Drei offene Projekte auf zwei Seiten; das archivierte fehlt.
    assert namen == ["Inbox", "Arbeit", "Arbeit › Kunden"]
    assert gruppen[0]["listen"][0]["ziel"] == f"{verbunden}:p-eingang"
    assert ("GET", "projects") in fern.anfragen
    assert sum(1 for a in fern.anfragen if a == ("GET", "projects")) >= 3  # verbinden + 2 Seiten


def test_eine_klemmende_verbindung_steht_mit_ihrem_grund_da(klient, verbunden, fern):
    fern.stoerung = 401
    gruppen = klient.get("/api/aufgabenziele/listen").json()
    assert gruppen[0]["fehler"] == "todoist_zugang_ungueltig"
    assert gruppen[0]["listen"] == []
    assert klient.get("/api/aufgabenziele").json()["verbindungen"][0]["fehler"] == (
        "todoist_zugang_ungueltig"
    )


# --- Anlegen ----------------------------------------------------------------- #


def test_aus_einer_mail_wird_eine_todoist_aufgabe(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
    antwort = _anlegen(
        klient,
        ids[0],
        f"{verbunden}:p-kunden",
        titel="  Angebot   schicken ",
        liste_name="Arbeit › Kunden",
        faellig="2026-11-05",
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["neu"] is True

    rumpf = fern.rumpfe[-1]
    assert rumpf["content"] == "Angebot schicken"
    assert rumpf["project_id"] == "p-kunden"
    assert rumpf["due_date"] == "2026-11-05"
    assert "Wer Auch Immer <wer@example.com>" in rumpf["description"]

    # Der Link führt über die Message-ID zurück, nicht über die Zeilennummer.
    link = rumpf["description"].split("(", 1)[1].rstrip(")")
    teile = urlsplit(link)
    assert f"{teile.scheme}://{teile.netloc}" == "https://mail.example.com"
    assert unquote(parse_qs(teile.query)["mail"][0]) == "<mail0@example.com>"
    assert str(ids[0]) not in link

    zeile = daten["aufgabe"]
    assert zeile["fern_art"] == "todoist"
    assert zeile["fern_url"] == "https://app.todoist.com/app/task/t1"
    assert zeile["fern_liste"] == "Arbeit › Kunden"
    assert zeile["fern_verbunden"] is True
    assert zeile["faellig"].startswith("2026-11-05")
    assert zeile["betreff"] == "Angebot schicken"


def test_ohne_titel_gilt_der_betreff(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    _anlegen(klient, ids[1], f"{verbunden}:p-eingang")
    assert fern.rumpfe[-1]["content"] == "Mail 1"
    assert "due_date" not in fern.rumpfe[-1]


def test_der_text_der_mail_geht_nicht_hinaus(klient, verbunden, welt, fern, db):  # noqa: F811
    from app.models import Nachricht

    _, _, ids = welt
    mail = db.get(Nachricht, ids[0])
    mail.anreisser = "Streng vertraulicher Inhalt"
    db.commit()
    _anlegen(klient, ids[0], f"{verbunden}:p-eingang")
    assert "vertraulich" not in json.dumps(fern.rumpfe[-1])


def test_ohne_oeffentliche_adresse_nimmt_der_link_die_des_browsers(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    _anlegen(klient, ids[0], f"{verbunden}:p-eingang", adresse="https://heim.example.net/")
    assert "https://heim.example.net/?mail=%3Cmail0%40example.com%3E" in fern.rumpfe[-1]["description"]


def test_ohne_jede_adresse_steht_die_message_id_da(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    _anlegen(klient, ids[0], f"{verbunden}:p-eingang", adresse="kaputt")
    beschreibung = fern.rumpfe[-1]["description"]
    assert "Message-ID: <mail0@example.com>" in beschreibung
    assert "](" not in beschreibung


def test_zweimal_dieselbe_mail_gibt_keine_zweite_aufgabe(klient, verbunden, welt, fern):  # noqa: F811
    """⚠️ Auch nicht in einem anderen Ziel: eine Mail, eine Aufgabe."""
    _, _, ids = welt
    erste = _anlegen(klient, ids[0], f"{verbunden}:p-eingang").json()
    zweite = _anlegen(klient, ids[0], f"{verbunden}:p-arbeit").json()
    dritte = _anlegen(klient, ids[0], "").json()

    assert zweite["neu"] is False and dritte["neu"] is False
    assert erste["aufgabe"]["id"] == zweite["aufgabe"]["id"] == dritte["aufgabe"]["id"]
    assert len(fern.rumpfe) == 1
    assert len(klient.get("/api/aufgaben").json()) == 1


def test_die_eigene_liste_nimmt_titel_und_datum(klient, welt, fern):  # noqa: F811
    _, _, ids = welt
    antwort = _anlegen(klient, ids[2], "", titel="Selbst merken", faellig="2026-12-01")
    zeile = antwort.json()["aufgabe"]
    assert zeile["fern_art"] == ""
    assert zeile["betreff"] == "Selbst merken"
    assert zeile["faellig"].startswith("2026-12-01")
    assert fern.anfragen == []


def test_scheitert_todoist_entsteht_hier_nichts(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    fern.stoerung = 429
    antwort = _anlegen(klient, ids[0], f"{verbunden}:p-eingang")
    assert antwort.status_code == 429
    assert antwort.json()["detail"] == "todoist_zu_viele_anfragen"
    assert db.query(Aufgabe).count() == 0


def test_ein_netzfehler_wird_zu_502(klient, verbunden, welt, monkeypatch):  # noqa: F811
    _, _, ids = welt

    def tot(anfrage):
        raise httpx.ConnectError("kein Netz", request=anfrage)

    monkeypatch.setattr(todoist, "TRANSPORT", httpx.MockTransport(tot))
    antwort = _anlegen(klient, ids[0], f"{verbunden}:p-eingang")
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "todoist_nicht_erreichbar"


def test_ein_kaputtes_ziel_wird_abgewiesen(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    assert _anlegen(klient, ids[0], verbunden).json()["detail"] == "aufgabenziel_unbekannt"
    antwort = _anlegen(klient, ids[0], "gibtsnicht:p-eingang")
    assert antwort.status_code == 404
    assert antwort.json()["detail"] == "aufgabenverbindung_unbekannt"


def test_der_token_steht_nie_im_protokoll(klient, verbunden, welt, fern, caplog):  # noqa: F811
    _, _, ids = welt
    caplog.set_level(logging.DEBUG)
    _anlegen(klient, ids[0], f"{verbunden}:p-eingang")
    fern.stoerung = 500
    _anlegen(klient, ids[1], f"{verbunden}:p-eingang")
    assert TOKEN not in caplog.text


# --- Der Haken ----------------------------------------------------------------- #


def _eine_fernaufgabe(klient, verbunden, welt):  # noqa: F811
    _, _, ids = welt
    return _anlegen(klient, ids[0], f"{verbunden}:p-eingang").json()["aufgabe"]["id"]


def test_abhaken_in_nexmail_schliesst_die_aufgabe_in_todoist(klient, verbunden, welt, fern):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    antwort = klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True})
    assert antwort.status_code == 200
    assert antwort.json()["erledigt"] is not None
    assert fern.aufgaben["t1"]["checked"] is True

    klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": False})
    assert fern.aufgaben["t1"]["checked"] is False


def test_lehnt_todoist_den_haken_ab_bleibt_er_hier_wie_er_war(klient, verbunden, welt, fern):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    fern.stoerung = 401
    antwort = klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True})
    assert antwort.status_code == 409
    assert klient.get("/api/aufgaben").json()[0]["erledigt"] is None


def test_das_datum_einer_todoist_aufgabe_aendert_man_dort(klient, verbunden, welt, fern):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    antwort = klient.patch(
        f"/api/aufgaben/{aufgabe_id}",
        json={"faellig": "2026-11-09T00:00:00Z", "faellig_setzen": True},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "aufgabe_datum_in_der_app"


# --- Der Rückweg ---------------------------------------------------------------- #


def test_in_todoist_abgehakt_ist_hier_erledigt(klient, verbunden, welt, fern):  # noqa: F811
    _eine_fernaufgabe(klient, verbunden, welt)
    fern.erledigen("t1")
    assert klient.post("/api/aufgaben/abgleichen").status_code == 204
    zeile = klient.get("/api/aufgaben").json()[0]
    assert zeile["erledigt"].startswith("2026-11-03T08:30")


def test_in_todoist_wieder_geoeffnet_ist_hier_wieder_offen(klient, verbunden, welt, fern, db):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    fern.erledigen("t1")
    person = db.query(Benutzer).first()
    aufgabenziele.abgleichen(db, person)
    assert db.get(Aufgabe, aufgabe_id).erledigt is not None

    fern.aufgaben["t1"].update(checked=False, completed_at=None, due={"date": "2026-11-20"})
    aufgabenziele.abgleichen(db, person)
    db.expire_all()
    zeile = db.get(Aufgabe, aufgabe_id)
    assert zeile.erledigt is None
    assert zeile.faellig.date() == date(2026, 11, 20)


def test_in_todoist_geloescht_sagt_die_zeile_es(klient, verbunden, welt, fern):  # noqa: F811
    _eine_fernaufgabe(klient, verbunden, welt)
    fern.aufgaben["t1"]["is_deleted"] = True
    klient.post("/api/aufgaben/abgleichen")
    zeile = klient.get("/api/aufgaben").json()[0]
    assert zeile["fern_geloescht"] is True
    assert zeile["erledigt"] is None


def test_erledigtes_kostet_beim_naechsten_lauf_keine_anfrage_je_aufgabe(
    klient, verbunden, welt, fern, db  # noqa: F811
):
    _eine_fernaufgabe(klient, verbunden, welt)
    fern.erledigen("t1")
    person = db.query(Benutzer).first()
    aufgabenziele.abgleichen(db, person)
    vorher = len(fern.anfragen)
    aufgabenziele.abgleichen(db, person)
    neu = fern.anfragen[vorher:]
    assert ("GET", "tasks/t1") not in neu
    assert neu == [("GET", "tasks")]


def test_lange_erledigtes_wird_nicht_mehr_nachgesehen(klient, verbunden, welt, fern, db):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    db.get(Aufgabe, aufgabe_id).erledigt = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    vorher = len(fern.anfragen)
    aufgabenziele.abgleichen(db, db.query(Benutzer).first())
    assert fern.anfragen[vorher:] == []


def test_beim_oeffnen_wird_nicht_bei_jedem_klick_gefragt(klient, verbunden, welt, fern):  # noqa: F811
    _eine_fernaufgabe(klient, verbunden, welt)
    klient.post("/api/aufgaben/abgleichen")
    vorher = len(fern.anfragen)
    klient.post("/api/aufgaben/abgleichen")
    assert len(fern.anfragen) == vorher


def test_ein_scheiternder_abgleich_steht_an_der_verbindung(klient, verbunden, welt, fern, db):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    fern.stoerung = 401
    assert klient.post("/api/aufgaben/abgleichen").status_code == 204
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == "todoist_zugang_ungueltig"
    assert db.get(Aufgabe, aufgabe_id).erledigt is None


def test_der_takt_gleicht_ab(klient, verbunden, welt, fern, db):  # noqa: F811
    from app.services import takt

    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    fern.erledigen("t1")
    takt.kalender_runde(db)
    db.expire_all()
    assert db.get(Aufgabe, aufgabe_id).erledigt is not None


# --- Trennen und Standard ------------------------------------------------------- #


def test_trennen_laesst_die_aufgaben_mit_link_stehen(klient, verbunden, welt, fern, db):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    klient.put("/api/aufgabenziele/standard", json={"ziel": f"{verbunden}:p-eingang"})

    assert klient.delete(f"/api/aufgabenziele/{verbunden}").status_code == 204
    zeile = klient.get("/api/aufgaben").json()[0]
    assert zeile["fern_art"] == "todoist"
    assert zeile["fern_url"].endswith("/t1")
    assert zeile["fern_verbunden"] is False
    assert klient.get("/api/aufgabenziele").json()["standard"] == ""

    # Danach ist der Haken ein eigener: kein Ruf mehr nach Todoist.
    vorher = len(fern.anfragen)
    assert klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True}).status_code == 200
    assert len(fern.anfragen) == vorher


def test_der_standard_muss_auf_eine_eigene_verbindung_zeigen(klient, verbunden):
    antwort = klient.put("/api/aufgabenziele/standard", json={"ziel": "fremd:p-eingang"})
    assert antwort.status_code == 404
    gut = klient.put("/api/aufgabenziele/standard", json={"ziel": f"{verbunden}:p-arbeit"})
    assert gut.json()["standard"] == f"{verbunden}:p-arbeit"


# --- Zwei Benutzer ------------------------------------------------------------- #


def test_ein_anderer_kommt_nicht_an_meine_verbindung(
    klient, zweiter_klient, verbunden, welt, fern, db  # noqa: F811
):
    _, _, ids = welt
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get("/api/aufgabenziele").json()["verbindungen"] == []
    assert zweiter_klient.delete(f"/api/aufgabenziele/{verbunden}").status_code == 404
    # Weder mit meiner Mail noch mit meiner Verbindung.
    assert _anlegen(zweiter_klient, ids[0], f"{verbunden}:p-eingang").status_code == 404
    assert fern.rumpfe == []
    assert (
        zweiter_klient.get("/api/aufgaben/mail", params={"message_id": "<mail0@example.com>"}).status_code
        == 404
    )


def test_der_link_findet_die_mail_wo_sie_heute_liegt(klient, welt):  # noqa: F811
    _, _, ids = welt
    antwort = klient.get("/api/aufgaben/mail", params={"message_id": "<mail1@example.com>"})
    assert antwort.json() == {"nachricht_id": ids[1]}
    assert klient.get("/api/aufgaben/mail", params={"message_id": "<nie@example.com>"}).status_code == 404


def test_die_app_bekommt_beim_anlegen_ihre_alte_zeile(klient, welt):  # noqa: F811
    """⚠️ ``POST /api/aufgaben`` ist die Zweitschrift der iPhone-App; ihre
    Antwort darf keine neuen Felder bekommen (Abdruck)."""
    _, _, ids = welt
    zeile = klient.post("/api/aufgaben", json={"nachricht_id": ids[0]}).json()
    assert "fern_art" not in zeile


def test_das_datum_wird_als_tag_geschickt():
    assert todoist._datum({"date": "2026-11-05T10:00:00"}) == date(2026, 11, 5)
    assert todoist._datum({"date": "kaputt"}) is None
    assert todoist._datum(None) is None


def test_die_oeffentliche_adresse_geht_vor_der_des_browsers(klient, verbunden, welt, fern, db):  # noqa: F811
    """Wie beim QR-Code der App: Zu Hause über eine IP aufgerufen, soll der
    Link in Todoist trotzdem der sein, der auch unterwegs geht."""
    _, _, ids = welt
    einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
    _anlegen(klient, ids[0], f"{verbunden}:p-eingang", adresse="http://192.0.2.10:5174")
    beschreibung = fern.rumpfe[-1]["description"]
    assert "https://mail.example.com/?mail=" in beschreibung
    assert "192.0.2.10" not in beschreibung


def test_abgehakt_ohne_zeitpunkt_ist_trotzdem_erledigt(klient, verbunden, welt, fern, db):  # noqa: F811
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    fern.aufgaben["t1"].update(checked=True, completed_at=None)
    aufgabenziele.abgleichen(db, db.query(Benutzer).first())
    db.expire_all()
    assert db.get(Aufgabe, aufgabe_id).erledigt is not None


def test_eine_erledigte_in_der_liste_der_offenen_bleibt_erledigt(klient, verbunden, welt, fern, db):  # noqa: F811
    """⚠️ Liefert Todoist eines Tages Erledigte mit, darf nexmail sie nicht
    wieder öffnen."""
    aufgabe_id = _eine_fernaufgabe(klient, verbunden, welt)
    fern.liste_mit_erledigten = True
    fern.erledigen("t1")
    aufgabenziele.abgleichen(db, db.query(Benutzer).first())
    db.expire_all()
    assert db.get(Aufgabe, aufgabe_id).erledigt is not None
