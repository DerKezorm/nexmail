"""nextasks als Aufgabenziel: Aufgaben aus Mails in nextasks, und der Haken kommt zurück.

Gesprochen wird mit einem nachgebauten nextasks (``Nextasks`` unten), gebaut
nach dessen ``docs/api.md`` vom 07.11.2026. ⚠️ **Das prüft nexmails Logik,
nicht nextasks** (FALLSTRICKE §8): Ob nextasks die Felder so versteht, sagt
erst ein Lauf gegen eine echte Instanz.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from app.models import Aufgabe, Aufgabenverbindung, Nachricht
from app.services import aufgabenziele, netzfreigabe, nextasks
from conftest import anmelden, zweiten_benutzer_anlegen
from test_aufgaben import ohne_netz, welt  # noqa: F401

#: Bewusst kein echt aussehendes Token: Die Scanner vor dem Push sollen hier
#: nicht anschlagen.
TOKEN = "probe-token-nur-fuer-tests"
ADRESSE = "https://tasks.example.com"


def _uuid() -> str:
    return str(uuid.uuid4())


class Nextasks:
    """Ein kleines nextasks im Speicher, mit den Pfaden, die nexmail benutzt."""

    def __init__(self) -> None:
        self.familie, self.garten, self.arbeit = _uuid(), _uuid(), _uuid()
        self.einkauf, self.haushalt, self.beete, self.projekte = _uuid(), _uuid(), _uuid(), _uuid()
        self.abschnitt = _uuid()
        self.listen = [
            # Ausgeblendeter Bereich: ans Ende. Hier absichtlich nicht am Ende
            # geliefert, damit nexmail selbst sortieren muss.
            {"id": self.projekte, "space_id": self.arbeit, "space_name": "Arbeit", "name": "Projekte",
             "writable": True, "hidden": True, "sections": []},
            {"id": self.einkauf, "space_id": self.familie, "space_name": "Familie", "name": "Einkauf",
             "writable": True, "hidden": False, "sections": [{"id": self.abschnitt, "name": "Markt"}]},
            {"id": self.haushalt, "space_id": self.familie, "space_name": "Familie", "name": "Haushalt",
             "writable": True, "hidden": False, "sections": []},
            # Nur lesbar: gehört nicht in die Auswahl.
            {"id": self.beete, "space_id": self.garten, "space_name": "Garten", "name": "Beete",
             "writable": False, "hidden": False, "sections": []},
        ]
        self.ich = {"name": "robin", "display_name": "Robin", "level": "write", "time_zone": "Europe/Berlin",
                    "spaces": [], "version": "0.1.0", "features": ["tasks", "dashboard", "external_ref"]}
        self.aufgaben: dict[str, dict] = {}
        #: Aufgaben, die endgültig weg sind.
        self.fort: set[str] = set()
        self.refs: dict[str, str] = {}
        self.anfragen: list[tuple[str, str]] = []
        self.parameter: list[dict] = []
        self.rumpfe: list[dict] = []
        #: ``(status, code)`` für jede Anfrage, z. B. ``(401, "token_invalid")``.
        self.stoerung: tuple[int, str] | None = None
        self.kopf_extra: dict[str, str] = {}
        #: Fehlt eine Kennung in der Antwort auf ``?ids=``, bleibt sie draußen.
        self.verschweigen: set[str] = set()
        self.mit_link = True
        self.liste_fehlt_als_422 = False

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        assert anfrage.url.host == "tasks.example.com"
        pfad = anfrage.url.path.removeprefix("/api/v1/")
        self.anfragen.append((anfrage.method, pfad))
        self.parameter.append(dict(anfrage.url.params))
        if "origin" in anfrage.headers:
            return self._fehler(403, "origin_refused")
        if self.stoerung:
            return self._fehler(*self.stoerung, kopf=self.kopf_extra)
        if anfrage.headers.get("authorization") != f"Bearer {TOKEN}":
            return self._fehler(401, "token_invalid")

        if anfrage.method == "GET" and pfad == "me":
            return httpx.Response(200, json=self.ich)
        if anfrage.method == "GET" and pfad == "lists":
            return httpx.Response(200, json={"lists": self.listen})
        if anfrage.method == "POST" and pfad == "tasks":
            return self._anlegen(json.loads(anfrage.content))
        if anfrage.method == "GET" and pfad == "tasks":
            ids = [i for i in anfrage.url.params.get("ids", "").split(",") if i]
            assert len(ids) <= 200
            zeilen = [
                {"id": i, "gone": True} if i in self.fort or i not in self.aufgaben else self.aufgaben[i]
                for i in ids
                if i not in self.verschweigen
            ]
            return httpx.Response(200, json={"tasks": zeilen, "next_cursor": None, "as_of": "2026-11-07T08:00:00.000Z"})
        if pfad.startswith("tasks/") and anfrage.method == "PATCH":
            kennung = pfad.split("/")[1]
            a = self.aufgaben.get(kennung)
            if a is None or kennung in self.fort:
                return self._fehler(404, "not_found")
            rumpf = json.loads(anfrage.content)
            self.rumpfe.append(rumpf)
            if rumpf.get("completed") is True and a.get("repeat"):
                # Wie nextasks: dieselbe Kennung bleibt offen, mit neuem Datum.
                naechstes = date.fromisoformat(a["due_date"]) + timedelta(days=7)
                a["due_date"] = naechstes.isoformat()
                return httpx.Response(200, json={**a, "next": kennung, "completed_copy": _uuid()})
            if "completed" in rumpf:
                a["completed"] = rumpf["completed"]
                a["completed_at"] = "2026-11-07T09:00:00.000Z" if rumpf["completed"] else None
            return httpx.Response(200, json=a)
        return self._fehler(404, "not_found")

    def _fehler(self, status: int, code: str, *, felder: list | None = None, kopf: dict | None = None):
        detail = {"code": code, "message": "nope"}
        if felder is not None:
            detail["fields"] = felder
        return httpx.Response(status, json={"detail": detail}, headers=kopf or {})

    def _anlegen(self, rumpf: dict) -> httpx.Response:
        self.rumpfe.append(rumpf)
        ref = rumpf.get("external_ref")
        if ref and ref in self.refs and self.refs[ref] not in self.fort:
            return httpx.Response(200, json=self.aufgaben[self.refs[ref]])
        if "list_id" in rumpf and not any(
            l["id"] == rumpf["list_id"] and l["writable"] for l in self.listen
        ):
            # So antwortet das echte nextasks (gemessen 07.11.2026); seine
            # ``api.md`` nennt 422 mit ``fields: ["list_id"]``.
            if self.liste_fehlt_als_422:
                return self._fehler(422, "invalid_input", felder=["list_id"])
            return self._fehler(404, "not_found")
        kennung = _uuid()
        self.aufgaben[kennung] = {
            "id": kennung,
            "list_id": rumpf.get("list_id", self.haushalt),
            "section_id": rumpf.get("section_id"),
            "title": rumpf["title"],
            "notes": rumpf.get("notes", ""),
            "url": rumpf.get("url"),
            "due_date": rumpf.get("due_date"),
            "due_time": None,
            "repeat": None,
            "completed": False,
            "completed_at": None,
            "trashed": False,
            "external_ref": ref,
            "link": f"{ADRESSE}/lists/x?task={kennung}" if self.mit_link else None,
        }
        if ref:
            self.refs[ref] = kennung
        return httpx.Response(201, json=self.aufgaben[kennung])

    # Was ein Mensch in nextasks tut.
    def erledigen(self, kennung: str) -> None:
        self.aufgaben[kennung].update(completed=True, completed_at="2026-11-07T08:30:00.000Z")

    def oeffnen(self, kennung: str) -> None:
        self.aufgaben[kennung].update(completed=False, completed_at=None)

    def zaehlen(self, methode: str, pfad: str) -> int:
        return sum(1 for a in self.anfragen if a == (methode, pfad))


@pytest.fixture
def fern(monkeypatch):
    dienst = Nextasks()
    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(dienst))
    aufgabenziele._zuletzt_beim_oeffnen.clear()
    return dienst


def _verbinden(klient, **mehr):
    return klient.post(
        "/api/aufgabenziele/nextasks", json={"url": ADRESSE + "/", "token": TOKEN, **mehr}
    )


@pytest.fixture
def verbunden(klient, welt, fern):  # noqa: F811
    antwort = _verbinden(klient)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def _anlegen(klient, nachricht_id, ziel, **mehr):
    return klient.post(
        "/api/aufgaben/mit-ziel", json={"nachricht_id": nachricht_id, "ziel": ziel, **mehr}
    )


def _eine(klient, verbunden, fern, nachricht_id, **mehr) -> tuple[int, str]:
    """Eine Aufgabe in „Familie › Einkauf"; gibt nexmails und nextasks' Kennung."""
    antwort = _anlegen(klient, nachricht_id, f"{verbunden}:{fern.einkauf}", **mehr)
    assert antwort.status_code == 200, antwort.text
    zeile = antwort.json()["aufgabe"]
    return zeile["id"], next(iter(k for k, a in fern.aufgaben.items() if a["title"] == zeile["betreff"]))


def _zeile(klient, aufgabe_id: int) -> dict:
    return next(z for z in klient.get("/api/aufgaben").json() if z["id"] == aufgabe_id)


def _abgleichen(db, klient) -> None:
    from app.models import Benutzer

    person = db.query(Benutzer).one()
    aufgabenziele.abgleichen(db, person)


# --- Verbinden ------------------------------------------------------------- #


def test_ein_gutes_token_wird_verschluesselt_gespeichert(klient, verbunden, fern, db):
    zeile = db.get(Aufgabenverbindung, verbunden)
    assert zeile.art == "nextasks"
    assert TOKEN not in zeile.zugang
    zugang = nextasks.zugang_lesen(aufgabenziele._zugang(zeile))
    # Der Schrägstrich am Ende fällt weg, sonst hieße es ``//api/v1``.
    assert zugang == nextasks.Zugang(url=ADRESSE, token=TOKEN)
    assert fern.anfragen[0] == ("GET", "me")

    for pfad in ("/api/aufgabenziele", f"/api/aufgabenziele/{verbunden}/nextasks"):
        text = klient.get(pfad).text
        assert TOKEN not in text
        assert TOKEN[-4:] not in text
    assert klient.get(f"/api/aufgabenziele/{verbunden}/nextasks").json() == {"url": ADRESSE}


@pytest.mark.parametrize(
    ("stoerung", "kennung"),
    [
        ((401, "token_invalid"), "nextasks_zugang_ungueltig"),
        ((401, "api_off"), "nextasks_api_aus"),
        ((404, "not_found"), "nextasks_zu_alt"),
    ],
)
def test_ein_abgelehnter_zugang_wird_nie_gespeichert(klient, welt, fern, db, stoerung, kennung):  # noqa: F811
    fern.stoerung = stoerung
    antwort = _verbinden(klient)
    # ⚠️ 409, nicht 401: Die Oberfläche meldete bei 401 aus nexmail ab.
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == kennung
    assert db.query(Aufgabenverbindung).count() == 0


def test_ein_lese_token_wird_abgewiesen(klient, welt, fern, db):  # noqa: F811
    fern.ich["level"] = "read"
    antwort = _verbinden(klient)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_nur_lesen"
    assert db.query(Aufgabenverbindung).count() == 0


@pytest.mark.parametrize("fehlt", ["tasks", "external_ref"])
def test_ein_zu_altes_nextasks_wird_abgewiesen(klient, welt, fern, db, fehlt):  # noqa: F811
    fern.ich["features"].remove(fehlt)
    antwort = _verbinden(klient)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_zu_alt"
    assert db.query(Aufgabenverbindung).count() == 0


def test_eine_seite_statt_nextasks_ist_unlesbar(klient, welt, monkeypatch, db):  # noqa: F811
    monkeypatch.setattr(
        nextasks, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(200, text="<html>hallo</html>"))
    )
    antwort = _verbinden(klient)
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "nextasks_antwort_unlesbar"
    assert db.query(Aufgabenverbindung).count() == 0


@pytest.mark.parametrize(
    ("url", "kennung"),
    [
        ("ftp://tasks.example.com", "nextasks_adresse_ungueltig"),
        ("https://robin:geheim@tasks.example.com", "nextasks_adresse_ungueltig"),
        ("https://tasks.example.com/?x=1", "nextasks_adresse_ungueltig"),
        ("tasks.example.com", "nextasks_adresse_ungueltig"),
        ("http://localhost:8510", "nextasks_adresse_localhost"),
        ("http://127.0.0.1:8510", "nextasks_adresse_localhost"),
    ],
)
def test_unpassende_adressen_werden_vor_jedem_aufruf_abgewiesen(klient, welt, fern, url, kennung):  # noqa: F811
    antwort = klient.post("/api/aufgabenziele/nextasks", json={"url": url, "token": TOKEN})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == kennung
    assert fern.anfragen == []


def test_einer_weiterleitung_wird_nicht_gefolgt(klient, welt, monkeypatch, db):  # noqa: F811
    """⚠️ Sonst zeigte eine geprüfte Adresse per 302 doch ins Heimnetz."""
    ziele: list[str] = []

    def umleiten(anfrage: httpx.Request) -> httpx.Response:
        ziele.append(str(anfrage.url))
        return httpx.Response(302, headers={"Location": "https://elsewhere.example.com/api/v1/me"})

    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(umleiten))
    antwort = _verbinden(klient)
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "nextasks_weiterleitung"
    assert ziele == [f"{ADRESSE}/api/v1/me"]
    assert db.query(Aufgabenverbindung).count() == 0


def test_ein_unterpfad_bleibt_teil_der_adresse(klient, welt, fern):  # noqa: F811
    gesehen: list[str] = []

    def mitschreiben(anfrage: httpx.Request) -> httpx.Response:
        gesehen.append(anfrage.url.path)
        return fern(httpx.Request(anfrage.method, str(anfrage.url).replace("/nextasks/api", "/api"),
                                  headers=anfrage.headers, content=anfrage.content))

    nextasks.TRANSPORT = httpx.MockTransport(mitschreiben)
    antwort = klient.post(
        "/api/aufgabenziele/nextasks", json={"url": ADRESSE + "/nextasks/", "token": TOKEN}
    )
    assert antwort.status_code == 201, antwort.text
    assert gesehen == ["/nextasks/api/v1/me"]


def test_das_eigene_netz_gibt_nur_der_betreiber_frei(klient, welt, db):  # noqa: F811
    """Dieselbe Prüfung wie beim Webhook, ohne Transport, also echt."""
    with pytest.raises(nextasks.NextasksFehler) as fehler:
        nextasks._pruefen("http://172.16.5.10:8510")
    assert fehler.value.kennung == "nextasks_adresse_im_eigenen_netz"

    netzfreigabe.erlauben(db, True)
    nextasks._pruefen("http://172.16.5.10:8510")
    with pytest.raises(nextasks.NextasksFehler) as fehler:
        nextasks._pruefen("http://169.254.169.254")
    assert fehler.value.kennung == "nextasks_adresse_im_eigenen_netz"


def test_ohne_transport_wird_jede_anfrage_geprueft(klient, welt, monkeypatch):  # noqa: F811
    """⚠️ Nicht nur beim Speichern: Ein Abgleich gegen eine Adresse im eigenen
    Netz scheitert, sobald der Betreiber die Freigabe zurücknimmt."""
    monkeypatch.setattr(nextasks, "TRANSPORT", None)
    zugang = nextasks.Zugang(url="http://172.16.5.10:8510", token=TOKEN)
    with pytest.raises(nextasks.NextasksFehler) as fehler:
        nextasks.staende(zugang, ["a"])
    assert fehler.value.kennung == "nextasks_adresse_im_eigenen_netz"


def test_die_bremse_haelt_viele_versuche_auf(klient, welt, fern):  # noqa: F811
    codes = [_verbinden(klient).status_code for _ in range(12)]
    assert 429 in codes


def test_ein_neues_token_haelt_die_aufgaben_an_der_verbindung(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, _ = _eine(klient, verbunden, fern, ids[0])
    zeile = db.get(Aufgabenverbindung, verbunden)
    zeile.letzter_fehler = "nextasks_zugang_ungueltig"
    db.commit()

    falsch = klient.put(
        f"/api/aufgabenziele/{verbunden}/nextasks", json={"url": ADRESSE, "token": "abgelaufen"}
    )
    assert falsch.status_code == 409
    db.expire_all()
    # Das alte bleibt, solange das neue nicht angenommen ist.
    assert nextasks.zugang_lesen(aufgabenziele._zugang(db.get(Aufgabenverbindung, verbunden))).token == TOKEN

    gut = klient.put(f"/api/aufgabenziele/{verbunden}/nextasks", json={"url": ADRESSE, "token": TOKEN})
    assert gut.status_code == 200, gut.text
    assert gut.json()["fehler"] == ""
    assert db.get(Aufgabe, aufgabe_id).verbindung_id == verbunden


def test_ein_anderer_kommt_nicht_an_meine_verbindung(
    klient, zweiter_klient, verbunden, welt, fern, db  # noqa: F811
):
    _, _, ids = welt
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    fern.anfragen.clear()

    pfad = f"/api/aufgabenziele/{verbunden}/nextasks"
    assert zweiter_klient.get(pfad).status_code == 404
    assert zweiter_klient.put(pfad, json={"url": ADRESSE, "token": TOKEN}).status_code == 404
    assert _anlegen(zweiter_klient, ids[0], f"{verbunden}:{fern.einkauf}").status_code == 404
    # ⚠️ Auch der neue Zugang wird nicht erst bei nextasks geprüft.
    assert fern.anfragen == []


# --- Listen ------------------------------------------------------------------- #


def test_die_listen_kommen_mit_bereich_und_abschnitt(klient, verbunden, fern):
    gruppen = klient.get("/api/aufgabenziele/listen").json()
    assert len(gruppen) == 1
    assert gruppen[0]["art"] == "nextasks"
    listen = gruppen[0]["listen"]
    assert [l["name"] for l in listen] == [
        "Familie › Einkauf",
        "Familie › Einkauf › Markt",
        "Familie › Haushalt",
        # Ausgeblendet ans Ende; die nur lesbare fehlt.
        "Arbeit › Projekte",
    ]
    assert listen[0]["ziel"] == f"{verbunden}:{fern.einkauf}"
    assert listen[1]["ziel"] == f"{verbunden}:{fern.einkauf}/{fern.abschnitt}"


def test_eine_klemmende_verbindung_steht_mit_ihrem_grund_da(klient, verbunden, fern):
    fern.stoerung = (401, "token_invalid")
    gruppen = klient.get("/api/aufgabenziele/listen").json()
    assert gruppen[0]["fehler"] == "nextasks_zugang_ungueltig"
    assert gruppen[0]["listen"] == []
    assert klient.get("/api/aufgabenziele").json()["verbindungen"][0]["fehler"] == (
        "nextasks_zugang_ungueltig"
    )


# --- Anlegen ----------------------------------------------------------------- #


def test_aus_einer_mail_wird_eine_nextasks_aufgabe(klient, verbunden, welt, fern, db):  # noqa: F811
    from app.db import einstellung_schreiben

    _, _, ids = welt
    einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
    antwort = _anlegen(
        klient,
        ids[0],
        f"{verbunden}:{fern.einkauf}/{fern.abschnitt}",
        titel="  Brot   kaufen ",
        liste_name="Familie › Einkauf › Markt",
        faellig="2026-11-08",
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["neu"] is True

    rumpf = fern.rumpfe[-1]
    assert rumpf["title"] == "Brot kaufen"
    assert rumpf["list_id"] == fern.einkauf
    assert rumpf["section_id"] == fern.abschnitt
    assert rumpf["due_date"] == "2026-11-08"
    assert "due_time" not in rumpf
    assert rumpf["external_ref"] == "nexmail:<mail0@example.com>"
    assert rumpf["notes"] == "Wer Auch Immer <wer@example.com>"

    # Der Link führt über die Message-ID zurück, nicht über die Zeilennummer.
    teile = urlsplit(rumpf["url"])
    assert f"{teile.scheme}://{teile.netloc}" == "https://mail.example.com"
    assert unquote(parse_qs(teile.query)["mail"][0]) == "<mail0@example.com>"
    assert str(ids[0]) not in rumpf["url"]

    zeile = daten["aufgabe"]
    kennung = next(iter(fern.aufgaben))
    assert zeile["fern_art"] == "nextasks"
    assert zeile["fern_url"] == f"{ADRESSE}/lists/x?task={kennung}"
    assert zeile["fern_liste"] == "Familie › Einkauf › Markt"
    assert zeile["fern_verbunden"] is True
    assert zeile["faellig"].startswith("2026-11-08")
    assert db.get(Aufgabe, zeile["id"]).fern_id == kennung


def test_ohne_link_steht_die_message_id_in_der_notiz(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    _anlegen(klient, ids[1], f"{verbunden}:{fern.einkauf}")
    rumpf = fern.rumpfe[-1]
    assert "url" not in rumpf
    assert "Message-ID: <mail1@example.com>" in rumpf["notes"]
    assert rumpf["title"] == "Mail 1"
    assert "due_date" not in rumpf


def test_ohne_oeffentliche_adresse_nimmt_der_link_die_des_browsers(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}", adresse="http://10.0.0.20:5174")
    assert fern.rumpfe[-1]["url"].startswith("http://10.0.0.20:5174/?mail=")


def test_ohne_link_von_nextasks_bleibt_der_link_leer(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    fern.mit_link = False
    zeile = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}").json()["aufgabe"]
    assert zeile["fern_url"] == ""


def test_der_text_der_mail_geht_nicht_hinaus(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    mail = db.get(Nachricht, ids[0])
    mail.anreisser = "Streng vertraulicher Inhalt"
    mail.koerper_text = "Streng vertraulicher Inhalt"
    db.commit()
    _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    assert "vertraulich" not in json.dumps(fern.rumpfe)


def test_zweimal_dieselbe_mail_gibt_keine_zweite_aufgabe(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    erste = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}").json()
    zweite = _anlegen(klient, ids[0], f"{verbunden}:{fern.haushalt}").json()
    assert zweite["neu"] is False
    assert zweite["aufgabe"]["id"] == erste["aufgabe"]["id"]
    assert fern.zaehlen("POST", "tasks") == 1


def test_nach_dem_entfernen_hier_findet_nextasks_seine_aufgabe_wieder(klient, verbunden, welt, fern, db):  # noqa: F811
    """⚠️ Entfernen nimmt die Aufgabe nur aus nexmail. Macht man die Mail
    wieder zur Aufgabe, antwortet nextasks über ``external_ref`` mit der alten,
    samt Haken, statt eine zweite anzulegen."""
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0])
    fern.erledigen(kennung)
    assert klient.delete(f"/api/aufgaben/{aufgabe_id}").status_code == 204

    wieder = _anlegen(klient, ids[0], f"{verbunden}:{fern.haushalt}")
    assert wieder.status_code == 200, wieder.text
    assert len(fern.aufgaben) == 1
    zeile = wieder.json()["aufgabe"]
    assert zeile["erledigt"] is not None
    assert db.get(Aufgabe, zeile["id"]).fern_id == kennung


def test_eine_lange_message_id_gibt_einen_festen_kurzen_schluessel(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    mail = db.get(Nachricht, ids[0])
    mail.message_id = "<" + "x" * 300 + "@example.com>"
    db.commit()
    _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    schluessel = fern.rumpfe[-1]["external_ref"]
    assert len(schluessel) <= 200
    assert schluessel.startswith("nexmail:")
    assert schluessel == nextasks.schluessel_fuer(mail.message_id)
    assert nextasks.schluessel_fuer("<kurz@example.com>") == "nexmail:<kurz@example.com>"
    # ⚠️ Gekürzt hieße: zwei lange Message-IDs mit gleichem Anfang wären eine Aufgabe.
    anfang = "<" + "y" * 300
    assert nextasks.schluessel_fuer(anfang + "a@example.com>") != nextasks.schluessel_fuer(
        anfang + "b@example.com>"
    )


def test_scheitert_nextasks_entsteht_hier_nichts(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    fern.stoerung = (500, "boom")
    antwort = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "nextasks_fehler"
    assert db.query(Aufgabe).count() == 0
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == "nextasks_fehler"


@pytest.mark.parametrize("als_422", [False, True])
def test_eine_verschwundene_liste_sagt_es(klient, verbunden, welt, fern, als_422):  # noqa: F811
    _, _, ids = welt
    fern.liste_fehlt_als_422 = als_422
    antwort = _anlegen(klient, ids[0], f"{verbunden}:{_uuid()}")
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_liste_unbekannt"


def test_eine_bitte_um_pause_nennt_die_sekunden(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    fern.stoerung, fern.kopf_extra = (429, "slow_down"), {"Retry-After": "42"}
    antwort = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    assert antwort.status_code == 429
    assert antwort.json()["detail"] == "nextasks_zu_viele_anfragen"
    assert antwort.json()["werte"] == {"sekunden": 42}


def test_ein_netzfehler_wird_zu_502(klient, verbunden, welt, monkeypatch):  # noqa: F811
    _, _, ids = welt

    def kaputt(anfrage):
        raise httpx.ConnectError("weg", request=anfrage)

    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(kaputt))
    antwort = _anlegen(klient, ids[0], f"{verbunden}:egal")
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "nextasks_nicht_erreichbar"


def test_das_token_steht_nie_im_protokoll(klient, verbunden, welt, fern, caplog):  # noqa: F811
    _, _, ids = welt
    caplog.set_level(logging.DEBUG)
    fern.stoerung = (401, "token_invalid")
    _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    fern.stoerung = None
    _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    assert TOKEN not in caplog.text
    assert "Mail 0" not in caplog.text


# --- Haken -------------------------------------------------------------------- #


def test_abhaken_in_nexmail_hakt_in_nextasks_ab(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0])
    antwort = klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["erledigt"] is not None
    assert fern.aufgaben[kennung]["completed"] is True
    assert ("PATCH", f"tasks/{kennung}") in fern.anfragen

    antwort = klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": False})
    assert antwort.json()["erledigt"] is None
    assert fern.aufgaben[kennung]["completed"] is False


def test_lehnt_nextasks_den_haken_ab_bleibt_er_hier_wie_er_war(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, _ = _eine(klient, verbunden, fern, ids[0])
    fern.stoerung = (403, "token_reads_only")
    antwort = klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True})
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_nur_lesen"
    assert _zeile(klient, aufgabe_id)["erledigt"] is None
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == "nextasks_nur_lesen"


def test_eine_wiederholte_aufgabe_bleibt_offen_mit_neuem_datum(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0], faellig="2026-11-08")
    fern.aufgaben[kennung]["repeat"] = "weekly"
    antwort = klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["erledigt"] is None
    assert antwort.json()["faellig"].startswith("2026-11-15")


def test_das_datum_einer_nextasks_aufgabe_aendert_man_dort(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, _ = _eine(klient, verbunden, fern, ids[0])
    antwort = klient.patch(
        f"/api/aufgaben/{aufgabe_id}",
        json={"faellig_setzen": True, "faellig": "2026-12-01T00:00:00Z"},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "aufgabe_datum_in_der_app"


# --- Abgleich ----------------------------------------------------------------- #


def test_in_nextasks_abgehakt_ist_hier_erledigt_und_wieder_offen(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0])
    fern.erledigen(kennung)
    _abgleichen(db, klient)
    assert _zeile(klient, aufgabe_id)["erledigt"].startswith("2026-11-07T08:30")

    fern.oeffnen(kennung)
    fern.aufgaben[kennung]["due_date"] = "2026-11-20"
    _abgleichen(db, klient)
    zeile = _zeile(klient, aufgabe_id)
    assert zeile["erledigt"] is None
    assert zeile["faellig"].startswith("2026-11-20")


def test_eine_frage_fuer_alle_aufgaben_in_jedem_zustand(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    for n in ids:
        _eine(klient, verbunden, fern, n)
    fern.anfragen.clear()
    fern.parameter.clear()
    _abgleichen(db, klient)
    assert fern.anfragen == [("GET", "tasks")]
    gefragt = fern.parameter[0]
    assert len(gefragt["ids"].split(",")) == 3
    # Erledigtes und der Papierkorb gehören dazu, sonst fehlten sie still.
    assert gefragt["state"] == "all"
    assert gefragt["include_trashed"] == "true"


def test_mehr_als_200_gehen_in_mehreren_fragen(fern):
    zugang = nextasks.Zugang(url=ADRESSE, token=TOKEN)
    staende = nextasks.staende(zugang, [f"k{n}" for n in range(250)])
    assert fern.zaehlen("GET", "tasks") == 2
    assert len(staende) == 250
    assert all(s.weg for s in staende.values())


def test_der_papierkorb_ist_nicht_das_ende(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0])
    fern.aufgaben[kennung]["trashed"] = True
    _abgleichen(db, klient)
    assert _zeile(klient, aufgabe_id)["fern_geloescht"] is True

    # Im Papierkorb gehört der Haken hier, und der Abgleich nimmt ihn nicht zurück.
    assert klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True}).status_code == 200
    _abgleichen(db, klient)
    assert _zeile(klient, aufgabe_id)["erledigt"] is not None
    assert fern.aufgaben[kennung]["completed"] is False

    # Zurückgeholt: Die Zeile ist wieder verbunden und nimmt den Stand von dort.
    fern.aufgaben[kennung]["trashed"] = False
    _abgleichen(db, klient)
    zeile = _zeile(klient, aufgabe_id)
    assert zeile["fern_geloescht"] is False
    assert zeile["erledigt"] is None


def test_endgueltig_weg_sagt_die_zeile_und_es_wird_nicht_mehr_gefragt(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0])
    fern.fort.add(kennung)
    _abgleichen(db, klient)
    assert _zeile(klient, aufgabe_id)["fern_geloescht"] is True
    fern.anfragen.clear()
    _abgleichen(db, klient)
    assert fern.anfragen == []


def test_was_in_der_antwort_fehlt_bleibt_wie_es_war(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, kennung = _eine(klient, verbunden, fern, ids[0])
    fern.verschweigen.add(kennung)
    _abgleichen(db, klient)
    zeile = _zeile(klient, aufgabe_id)
    assert zeile["fern_geloescht"] is False
    assert zeile["erledigt"] is None


def test_lange_erledigtes_wird_nicht_mehr_nachgesehen(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, _ = _eine(klient, verbunden, fern, ids[0])
    zeile = db.get(Aufgabe, aufgabe_id)
    zeile.erledigt = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    fern.anfragen.clear()
    _abgleichen(db, klient)
    assert fern.anfragen == []


def test_ein_scheiternder_abgleich_steht_an_der_verbindung(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, _ = _eine(klient, verbunden, fern, ids[0])
    fern.stoerung = (401, "api_off")
    _abgleichen(db, klient)
    db.expire_all()
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == "nextasks_api_aus"
    assert _zeile(klient, aufgabe_id)["erledigt"] is None

    fern.stoerung = None
    _abgleichen(db, klient)
    db.expire_all()
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == ""


def test_trennen_laesst_die_aufgaben_mit_link_stehen(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    aufgabe_id, _ = _eine(klient, verbunden, fern, ids[0])
    assert klient.delete(f"/api/aufgabenziele/{verbunden}").status_code == 204
    zeile = _zeile(klient, aufgabe_id)
    assert zeile["fern_art"] == "nextasks"
    assert zeile["fern_url"].startswith(ADRESSE)
    assert zeile["fern_verbunden"] is False
    # Abhaken ist jetzt nur noch hier.
    fern.anfragen.clear()
    assert klient.patch(f"/api/aufgaben/{aufgabe_id}", json={"erledigt": True}).status_code == 200
    assert fern.anfragen == []


# --- Die iPhone-App ------------------------------------------------------------ #


@pytest.fixture
def geraet(klient, verbunden):
    """Ein gekoppeltes Gerät: nur Bearer, kein Keks."""
    from fastapi.testclient import TestClient

    from app.main import app
    from test_app_flaeche import abholen, koppeln

    with TestClient(app, base_url="http://testserver") as c:
        schluessel = abholen(c, koppeln(klient)).json()["key"]
        c.headers["Authorization"] = f"Bearer {schluessel}"
        yield c


def test_die_app_sieht_nextasks_wie_todoist(geraet, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    stand = geraet.get("/api/app/1/task-apps").json()
    assert [(v["id"], v["art"]) for v in stand["verbindungen"]] == [(verbunden, "nextasks")]
    assert TOKEN not in json.dumps(stand)
    listen = geraet.get("/api/app/1/task-lists").json()
    assert listen[0]["listen"][0]["name"] == "Familie › Einkauf"

    wunsch = {"nachricht_id": ids[0], "ziel": f"{verbunden}:{fern.einkauf}"}
    erste = geraet.post("/api/app/1/tasks/with-target", json=wunsch)
    assert erste.status_code == 200, erste.text
    assert erste.json()["aufgabe"]["fern_art"] == "nextasks"
    assert geraet.post("/api/app/1/tasks/with-target", json=wunsch).json()["neu"] is False
    assert fern.zaehlen("POST", "tasks") == 1


def test_ein_abgelehntes_token_wirft_die_app_nicht_hinaus(geraet, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    fern.stoerung = (401, "token_invalid")
    antwort = geraet.post(
        "/api/app/1/tasks/with-target", json={"nachricht_id": ids[0], "ziel": f"{verbunden}:{fern.einkauf}"}
    )
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_zugang_ungueltig"
    assert geraet.get("/api/app/1/me").status_code == 200


def test_verbinden_geht_nicht_ueber_die_app(geraet):
    antwort = geraet.post("/api/aufgabenziele/nextasks", json={"url": ADRESSE, "token": TOKEN})
    assert antwort.status_code == 401
