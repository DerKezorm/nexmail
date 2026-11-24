"""nextime verbinden: Kalender, Termine, Einladungen, Termin aus Mail (MAIL-1).

Gesprochen wird mit einem nachgebauten nextime (``Nextime`` unten), gebaut
nach der Beschreibung des nextime-Agenten vom 23.11.2026 (nextime 0.2.0,
``/api/v1``). ⚠️ **Das prüft nexmails Logik, nicht nextime** (FALLSTRICKE §8):
Ob nextime die Felder so versteht, sagt erst ein Lauf gegen eine echte Instanz.

Die IDs (AC-n, EC-n) beziehen sich auf die Spec „MAIL-1 nextime verbinden“.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.models import Ausgang, Benutzer, MailTermin, NextimeVerbindung, Terminantwort
from app.services import nextime, nextimeverbindung
from conftest import einrichten
from test_kalender import _ics, _mail_mit_einladung, ohne_netz  # noqa: F401

#: Bewusst kein echt aussehender Schlüssel: Die Scanner vor dem Push sollen hier
#: nicht anschlagen.
TOKEN = "probe-schluessel-nur-fuer-tests"
ADRESSE = "https://zeit.example.com"
WEB = "https://zeit.example.com/day?day=2026-12-01&event="


class Nextime:
    """Ein kleines nextime im Speicher, mit den Pfaden, die nexmail benutzt."""

    def __init__(self) -> None:
        self.ich = {"app": "nextime", "name": "robin", "display_name": "Robin", "level": "write",
                    "calendars": None, "time_zone": "Europe/Berlin", "version": "0.2.0",
                    "features": ["calendars", "events", "write", "search", "free", "dashboard",
                                 "client_ref", "series", "calendar_groups", "uid_lookup", "answer",
                                 "ical_import", "state"]}
        self.kalender = [
            {"id": 1, "name": "Persönlich", "color": "red", "icon": "", "background": False, "right": "owner",
             "writable": True, "busy_only": False, "source": "nextime", "owner": None, "default": True,
             "group": "own", "source_name": "", "hidden": False},
            {"id": 2, "name": "D&M", "color": "blue", "icon": "", "background": False, "right": "owner",
             "writable": True, "busy_only": False, "source": "icloud", "owner": None, "default": False,
             "group": "icloud", "source_name": "iCloud", "hidden": False},
            {"id": 3, "name": "Feiertage", "color": "gray", "icon": "", "background": True, "right": "owner",
             "writable": False, "busy_only": False, "source": "subscription", "owner": None, "default": False,
             "group": "subscriptions", "source_name": "Feiertage Deutschland", "hidden": False},
            {"id": 4, "name": "Kollegin", "color": "teal", "icon": "", "background": False, "right": "busy",
             "writable": False, "busy_only": True, "source": "nextime", "owner": "Kim", "default": False,
             "group": "shared", "source_name": "", "hidden": False},
            {"id": 5, "name": "Versteckt", "color": "pink", "icon": "", "background": False, "right": "owner",
             "writable": True, "busy_only": False, "source": "nextime", "owner": None, "default": False,
             "group": "own", "source_name": "", "hidden": True},
        ]
        self.termine: dict[int, dict] = {}
        self.naechste = 100
        self.anfragen: list[tuple[str, str]] = []
        self.parameter: list[dict] = []
        self.rumpfe: list[tuple[str, dict]] = []
        self.stoerung: tuple[int, str] | None = None
        self.version = "v1"
        self.refs: dict[str, int] = {}
        #: Wer bei einer Antwort auf einen vorhandenen Termin antwortet.
        self.antwort_durch = "source"

    def termin(self, **felder) -> dict:
        kennung = felder.pop("id", None) or self.naechste
        self.naechste = max(self.naechste, kennung) + 1
        e = {"id": kennung, "occurrence": None, "calendar_id": 1, "title": "Termin", "location": "",
             "busy": True, "busy_only": False, "all_day": False, "start": "2026-12-01T09:00:00Z",
             "end": "2026-12-01T10:00:00Z", "time_zone": "Europe/Berlin", "recurring": False,
             "writable": True, "etag": "e1", "waiting": False, "background": False, "person": None,
             "invitation": None, "uid": f"uid-{kennung}@example.org", "origin": None,
             "web_url": f"{WEB}{kennung}", "also_in": [], "notes": "", "rule": None,
             "organizer": None, "attendees": []}
        e.update(felder)
        self.termine[kennung] = e
        return e

    @staticmethod
    def wand(e: dict) -> dict:
        """Wie nextime einen Termin im Einzelabruf und in Antworten auf Schreibwege
        zeigt (``events.ui_times``): Wanduhr ``YYYY-MM-DDTHH:MM`` in ``time_zone``,
        ``series_start`` als Objekt. ⚠️ Nur Liste, Suche und UID-Suche liefern UTC
        mit ``Z`` (Prüfbericht MAIL-1, Befunde 2 und 3)."""
        raus = dict(e)
        zone = ZoneInfo(e.get("time_zone") or "UTC")

        def zeit(wert: str) -> str:
            if len(wert) == 10:
                return wert
            return datetime.fromisoformat(wert.replace("Z", "+00:00")).astimezone(zone).strftime("%Y-%m-%dT%H:%M")

        raus["start"], raus["end"] = zeit(e["start"]), zeit(e["end"])
        if isinstance(e.get("series_start"), str):
            raus["series_start"] = {"all_day": e["all_day"], "start": zeit(e["series_start"]),
                                    "end": zeit(e["series_start"]), "time_zone": e.get("time_zone") or ""}
        return raus

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        assert anfrage.url.host == "zeit.example.com"
        pfad = anfrage.url.path.removeprefix("/api/v1/")
        self.anfragen.append((anfrage.method, pfad))
        self.parameter.append(dict(anfrage.url.params))
        if "origin" in anfrage.headers:
            return self._fehler(403, "origin_refused")
        if self.stoerung:
            return self._fehler(*self.stoerung)
        if anfrage.headers.get("authorization") != f"Bearer {TOKEN}":
            return self._fehler(401, "token_invalid")
        rumpf = json.loads(anfrage.content) if anfrage.content else {}
        if rumpf:
            self.rumpfe.append((pfad, rumpf))

        if anfrage.method == "GET" and pfad == "me":
            return httpx.Response(200, json=self.ich)
        if anfrage.method == "GET" and pfad == "calendars":
            return httpx.Response(200, json={"calendars": self.kalender})
        if anfrage.method == "GET" and pfad == "state":
            return httpx.Response(200, json={"version": self.version})
        if anfrage.method == "GET" and pfad == "search":
            q = anfrage.url.params.get("q", "").lower()
            treffer = [{k: e[k] for k in ("id", "occurrence", "calendar_id", "title", "all_day", "start", "end",
                                          "time_zone", "recurring")} | {"coming": True}
                       for e in self.termine.values() if q in e["title"].lower()]
            return httpx.Response(200, json={"total": len(treffer), "events": treffer})
        if anfrage.method == "GET" and pfad == "events":
            uid = anfrage.url.params.get("uid")
            if uid is not None:
                return httpx.Response(200, json={"events": [e for e in self.termine.values() if e["uid"] == uid]})
            nummern = {int(n) for n in anfrage.url.params.get("calendars", "").split(",") if n}
            raus = []
            for e in self.termine.values():
                if e["calendar_id"] not in nummern:
                    continue
                if e["busy_only"]:
                    raus.append({"calendar_id": e["calendar_id"], "busy_only": True, "busy": True,
                                 "all_day": e["all_day"], "start": e["start"], "end": e["end"],
                                 "time_zone": e["time_zone"]})
                else:
                    raus.append({k: w for k, w in e.items() if k not in ("notes", "rule", "organizer", "attendees")})
            return httpx.Response(200, json={"events": raus})
        if anfrage.method == "POST" and pfad == "events":
            ref = rumpf.get("client_ref")
            if ref and ref in self.refs:
                return httpx.Response(200, json=self.wand(self.termine[self.refs[ref]]))
            ganz = rumpf.get("all_day", False)

            def utc(wand: str) -> str:
                # Wie nextime: eine Zeit ohne Versatz ist Wanduhr in ``time_zone``.
                zone = ZoneInfo(rumpf.get("time_zone") or "UTC")
                return datetime.fromisoformat(wand).replace(tzinfo=zone).astimezone(timezone.utc) \
                    .strftime("%Y-%m-%dT%H:%M:%SZ")

            e = self.termin(calendar_id=rumpf["calendar_id"], title=rumpf["title"], notes=rumpf.get("notes", ""),
                            location=rumpf.get("location", ""), all_day=ganz,
                            start=rumpf["start"] if ganz else utc(rumpf["start"]),
                            end=rumpf["end"] if ganz else utc(rumpf["end"]),
                            rule=rumpf.get("rule"), recurring=bool(rumpf.get("rule")))
            if ref:
                self.refs[ref] = e["id"]
            return httpx.Response(201, json=self.wand(e))
        if anfrage.method == "POST" and pfad == "events/ical":
            return self._ical(rumpf)
        teile = pfad.split("/")
        if teile[0] == "events" and len(teile) >= 2 and teile[1].isdigit():
            e = self.termine.get(int(teile[1]))
            if e is None:
                return self._fehler(404, "not_found")
            if len(teile) == 3 and teile[2] == "answer" and anfrage.method == "POST":
                if e["invitation"] is None:
                    return self._fehler(409, "not_an_invitation")
                geaendert = e["invitation"] != rumpf["answer"]
                e["invitation"] = rumpf["answer"]
                durch = "client" if e["origin"] == "imip" else self.antwort_durch
                return httpx.Response(200, json={"event": self.wand(e), "reply_by": durch, "changed": geaendert})
            if anfrage.method == "GET":
                return httpx.Response(200, json=self.wand(e))
            if anfrage.method == "PATCH":
                for von, nach in (("title", "title"), ("notes", "notes"), ("location", "location")):
                    if von in rumpf:
                        e[nach] = rumpf[von]
                if "start" in rumpf and not rumpf.get("all_day"):
                    zone = ZoneInfo(rumpf.get("time_zone") or e["time_zone"] or "UTC")
                    for feld in ("start", "end"):
                        e[feld] = datetime.fromisoformat(rumpf[feld]).replace(tzinfo=zone) \
                            .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                return httpx.Response(200, json=self.wand(e))
            if anfrage.method == "DELETE":
                del self.termine[e["id"]]
                return httpx.Response(204)
        return self._fehler(404, "not_found")

    def _ical(self, rumpf: dict) -> httpx.Response:
        text = rumpf["ical"]
        uid = next(z.split(":", 1)[1] for z in text.splitlines() if z.startswith("UID:"))
        vorhanden = [e for e in self.termine.values() if e["uid"] == uid]
        if "METHOD:CANCEL" in text:
            weg = [e for e in vorhanden if e["origin"] == "imip"]
            if not weg:
                return self._fehler(404, "not_found")
            for e in weg:
                del self.termine[e["id"]]
            return httpx.Response(200, json={"status": "cancelled", "event": None, "reply_by": "client",
                                             "trash": True})
        quelle = [e for e in vorhanden if e["origin"] != "imip"]
        if quelle:
            return httpx.Response(200, json={"status": "existing", "event": self.wand(quelle[0]),
                                             "reply_by": "source", "trash": None})
        # Wie nextime: Titel, Ort und Zeiten kommen aus der Einladung.
        def feld(name: str) -> str:
            return next((z.split(":", 1)[1] for z in text.splitlines() if z.split(";")[0].split(":")[0] == name), "")

        def zeit(wert: str) -> str:
            return f"{wert[0:4]}-{wert[4:6]}-{wert[6:8]}T{wert[9:11]}:{wert[11:13]}:{wert[13:15]}Z" if wert else ""

        aus_mail = {"title": feld("SUMMARY"), "location": feld("LOCATION"),
                    "start": zeit(feld("DTSTART")) or "2026-12-01T09:00:00Z",
                    "end": zeit(feld("DTEND")) or "2026-12-01T10:00:00Z"}
        if vorhanden:
            vorhanden[0].update(aus_mail, invitation=rumpf["answer"])
            return httpx.Response(200, json={"status": "updated", "event": self.wand(vorhanden[0]),
                                             "reply_by": "client", "trash": None})
        e = self.termin(calendar_id=rumpf.get("calendar_id", 1), uid=uid, origin="imip",
                        invitation=rumpf["answer"], **aus_mail)
        return httpx.Response(201, json={"status": "created", "event": self.wand(e), "reply_by": "client",
                                         "trash": None})

    def _fehler(self, status: int, code: str) -> httpx.Response:
        return httpx.Response(status, json={"detail": {"code": code, "message": "nope"}})

    def zaehlen(self, methode: str, pfad: str) -> int:
        return sum(1 for a in self.anfragen if a == (methode, pfad))


@pytest.fixture
def fern(monkeypatch):
    dienst = Nextime()
    monkeypatch.setattr(nextime, "TRANSPORT", httpx.MockTransport(dienst))
    return dienst


def _verbinden(klient, adresse: str = ADRESSE + "/", schluessel: str = TOKEN):
    return klient.post("/api/nextime/verbindung", json={"adresse": adresse, "schluessel": schluessel})


@pytest.fixture
def verbunden(klient, ohne_netz, fern):  # noqa: F811
    einrichten(klient)
    antwort = _verbinden(klient)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# --- Verbinden (AC-1, AC-13, AC-14, EC-2 bis EC-4, EC-17, EC-18) ------------ #


def test_verbinden_speichert_verschluesselt_und_nennt_die_kalender(klient, verbunden, fern, db):
    """AC-1, EC-17."""
    assert verbunden["kalender"] == 5
    assert verbunden["adresse"] == ADRESSE
    assert verbunden["name"] == "Robin"
    zeile = db.query(NextimeVerbindung).one()
    assert TOKEN not in zeile.zugang
    assert zeile.zeitzone == "Europe/Berlin"
    assert nextimeverbindung.zugang(zeile) == nextime.Zugang(url=ADRESSE, token=TOKEN)
    for pfad in ("/api/nextime/verbindung", "/api/nextime/kalender"):
        assert TOKEN not in klient.get(pfad).text
    assert fern.anfragen[0] == ("GET", "me")


def test_die_adresse_darf_mit_api_v1_kommen(klient, ohne_netz, fern):  # noqa: F811
    einrichten(klient)
    antwort = _verbinden(klient, adresse=f"  {ADRESSE}/api/v1/  ")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["adresse"] == ADRESSE


@pytest.mark.parametrize(
    ("stoerung", "kennung"),
    [((401, "token_invalid"), "nextime_zugang_ungueltig"), ((401, "api_off"), "nextime_api_aus"),
     ((404, "not_found"), "nextime_zu_alt")],
)
def test_ein_abgelehnter_zugang_wird_nie_gespeichert(klient, ohne_netz, fern, db, stoerung, kennung):  # noqa: F811
    """EC-2, EC-3: 409, nie 401 (sonst meldete die Oberfläche aus nexmail ab)."""
    einrichten(klient)
    fern.stoerung = stoerung
    antwort = _verbinden(klient)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == kennung
    assert db.query(NextimeVerbindung).count() == 0


@pytest.mark.parametrize(
    ("aendern", "kennung"),
    [(lambda ich: ich.update(level="read"), "nextime_nur_lesen"),
     (lambda ich: ich["features"].remove("ical_import"), "nextime_zu_alt"),
     (lambda ich: ich["features"].remove("state"), "nextime_zu_alt"),
     (lambda ich: ich.update(calendars=[{"id": 1, "name": "Persönlich"}]), "nextime_schluessel_nicht_fuer_alle"),
     (lambda ich: ich.update(app="nextasks"), "nextime_keine_antwort_von_nextime")],
)
def test_was_nexmail_nicht_tragen_kann_wird_abgewiesen(klient, ohne_netz, fern, db, aendern, kennung):  # noqa: F811
    """EC-2, EC-3: Nur lesen, zu alt, nur einzelne Kalender, kein nextime."""
    einrichten(klient)
    aendern(fern.ich)
    antwort = _verbinden(klient)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == kennung
    assert db.query(NextimeVerbindung).count() == 0


@pytest.mark.parametrize(
    ("adresse", "kennung"),
    [("http://localhost:8600", "nextime_adresse_localhost"), ("ftp://zeit.example.com", "nextime_adresse_ungueltig"),
     ("https://ich:geheim@zeit.example.com", "nextime_adresse_ungueltig")],
)
def test_eine_falsche_adresse_wird_benannt(klient, ohne_netz, fern, db, adresse, kennung):  # noqa: F811
    """EC-4."""
    einrichten(klient)
    antwort = _verbinden(klient, adresse=adresse)
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == kennung
    assert fern.anfragen == []


def test_das_eigene_netz_bleibt_ohne_freigabe_zu(klient, ohne_netz, monkeypatch):  # noqa: F811
    """EC-4: ohne Nachbau, also mit der echten Adressprüfung."""
    monkeypatch.setattr(nextime, "TRANSPORT", None)
    einrichten(klient)
    antwort = _verbinden(klient, adresse="https://10.0.0.20")
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextime_adresse_im_eigenen_netz"


def test_kein_origin_kopf(klient, verbunden, fern):
    """Sonst lehnt nextime ab; der Nachbau antwortet darauf mit 403."""
    assert klient.get("/api/nextime/kalender").status_code == 200


def test_trennen_nimmt_nur_hier_weg(klient, verbunden, fern, db):
    """AC-14."""
    fern.termin(title="Bleibt")
    vorher = len(fern.anfragen)
    assert klient.delete("/api/nextime/verbindung").status_code == 204
    assert db.query(NextimeVerbindung).count() == 0
    assert klient.get("/api/nextime/verbindung").json()["verbunden"] is False
    assert len(fern.anfragen) == vorher
    assert len(fern.termine) == 1
    assert klient.get("/api/nextime/kalender").status_code == 404


def test_ohne_verbindung_gibt_es_nichts(klient, ohne_netz, fern):  # noqa: F811
    """AC-13."""
    einrichten(klient)
    assert klient.get("/api/nextime/verbindung").json() == {
        "verbunden": False, "adresse": "", "name": "", "version": "", "letzter_fehler": ""}
    assert klient.get("/api/nextime/kalender").json()["detail"] == "nextime_nicht_verbunden"
    assert fern.anfragen == []


def test_ein_zweites_konto_sieht_nichts(klient, zweiter_klient, verbunden, fern, db):
    """EC-18."""
    from conftest import anmelden, zweiten_benutzer_anlegen

    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    assert zweiter_klient.get("/api/nextime/verbindung").json()["verbunden"] is False
    assert zweiter_klient.get("/api/nextime/kalender").status_code == 404


def test_ein_abgelaufener_schluessel_steht_an_der_verbindung(klient, verbunden, fern):
    """EC-2: „Verbindungen“ sagt es; ein Netzaussetzer dagegen nicht."""
    fern.stoerung = (500, "boom")
    assert klient.get("/api/nextime/kalender").status_code == 502
    assert klient.get("/api/nextime/verbindung").json()["letzter_fehler"] == ""
    fern.stoerung = (401, "token_invalid")
    assert klient.get("/api/nextime/kalender").status_code == 409
    assert klient.get("/api/nextime/verbindung").json()["letzter_fehler"] == "nextime_zugang_ungueltig"
    fern.stoerung = None
    assert klient.get("/api/nextime/kalender").status_code == 200
    assert klient.get("/api/nextime/verbindung").json()["letzter_fehler"] == ""


# --- Kalender (AC-3) --------------------------------------------------------- #


def test_die_kalender_kommen_mit_gruppe_farbe_und_haken(klient, verbunden, fern):
    liste = klient.get("/api/nextime/kalender").json()
    assert [k["id"] for k in liste] == ["nt:1", "nt:2", "nt:3", "nt:4", "nt:5"]
    d_m = liste[1]
    assert (d_m["art"], d_m["gruppe"], d_m["herkunft"], d_m["farbe_nextime"]) == ("nextime", "icloud", "iCloud", "blue")
    assert liste[0]["standard"] is True and liste[0]["nur_lesen"] is False
    assert liste[2]["hintergrund"] is True and liste[2]["nur_lesen"] is True
    assert liste[3]["nur_belegt"] is True
    # In nextime ausgeblendet: anfangs auch hier.
    assert [k["sichtbar"] for k in liste] == [True, True, True, True, False]


def test_der_haken_gilt_nur_in_nexmail(klient, verbunden, fern):
    assert klient.patch("/api/nextime/kalender/nt:5", json={"sichtbar": True}).status_code == 200
    assert klient.patch("/api/nextime/kalender/nt:1", json={"sichtbar": False}).status_code == 200
    liste = klient.get("/api/nextime/kalender").json()
    assert [k["sichtbar"] for k in liste] == [False, True, True, True, True]
    assert all(m == "GET" for m, _ in fern.anfragen)
    assert klient.patch("/api/nextime/kalender/abc", json={"sichtbar": True}).status_code == 404


# --- Termine (AC-4 bis AC-8, EC-7, EC-8) -------------------------------------- #


def _fenster(klient, **mehr):
    params = {"von": "2026-11-30T00:00:00Z", "bis": "2026-12-07T00:00:00Z", **mehr}
    return klient.get("/api/nextime/termine", params=params)


def test_das_fenster_fragt_nur_sichtbare_kalender_und_nennt_sie(klient, verbunden, fern):
    """AC-4: ohne ``calendars`` lieferte nextime ausgeblendete nicht mit; also immer nennen."""
    fern.termin(title="Sichtbar", calendar_id=1)
    fern.termin(title="Versteckt", calendar_id=5)
    antwort = _fenster(klient)
    assert antwort.status_code == 200, antwort.text
    assert [t["titel"] for t in antwort.json()] == ["Sichtbar"]
    assert fern.parameter[-1]["calendars"] == "1,2,3,4"
    gewaehlt = klient.get("/api/nextime/termine", params=[
        ("von", "2026-11-30T00:00:00Z"), ("bis", "2026-12-07T00:00:00Z"), ("kalender", "nt:5"), ("kalender", "x")])
    assert [t["titel"] for t in gewaehlt.json()] == ["Versteckt"]


def test_zeiten_kommen_richtig_an(klient, verbunden, fern):
    """EC-7: Uhrzeit in UTC; ganztägig mit dem LETZTEN Tag als Ende."""
    fern.termin(title="Besprechung", start="2026-12-01T14:00:00Z", end="2026-12-01T15:30:00Z")
    fern.termin(title="Urlaub", all_day=True, start="2026-12-02", end="2026-12-04")
    zeilen = {t["titel"]: t for t in _fenster(klient).json()}
    assert zeilen["Besprechung"]["beginn"].startswith("2026-12-01T14:00:00")
    assert zeilen["Besprechung"]["ende"].startswith("2026-12-01T15:30:00")
    urlaub = zeilen["Urlaub"]
    assert urlaub["ganztaegig"] is True
    assert urlaub["beginn"].startswith("2026-12-02T00:00:00")
    # nexmails Ende ist ausschließend: der Tag NACH dem letzten.
    assert urlaub["ende"].startswith("2026-12-05T00:00:00")


def test_ein_termin_traegt_was_die_oberflaeche_zum_aendern_braucht(klient, verbunden, fern):
    e = fern.termin(title="Zahnarzt", calendar_id=2, etag="abc", invitation="accepted", origin="imip")
    z = _fenster(klient).json()[0]
    assert z["kalender_id"] == "nt:2"
    assert z["id"] < 0
    f = z["fern"]
    assert (f["id"], f["etag"], f["link"], f["beschreibbar"]) == (e["id"], "abc", f"{WEB}{e['id']}", True)
    assert (f["einladung"], f["herkunft"], f["zeitzone"]) == ("accepted", "imip", "Europe/Berlin")
    assert z["aus_einladung"] is True
    # Dieselbe Nummer bei jedem Laden: Auswahl und offenes Fenster bleiben.
    assert _fenster(klient).json()[0]["id"] == z["id"]


def test_nur_belegt_zeigt_nur_die_zeit(klient, verbunden, fern):
    """AC-4: Kalender „nur belegt“ ohne Titel, nicht zu öffnen."""
    fern.termin(title="Geheim", calendar_id=4, busy_only=True, location="Irgendwo")
    z = _fenster(klient).json()[0]
    assert z["titel"] == "" and z["ort"] == ""
    assert z["fern"]["nur_belegt"] is True
    assert z["fern"]["id"] is None
    assert z["fern"]["beschreibbar"] is False


def test_hintergrund_und_reihe_werden_gekennzeichnet(klient, verbunden, fern):
    fern.termin(title="Advent", calendar_id=3, background=True, writable=False)
    fern.termin(title="Training", recurring=True, occurrence="20261201T090000Z")
    zeilen = {t["titel"]: t for t in _fenster(klient).json()}
    assert zeilen["Advent"]["fern"]["hintergrund"] is True
    assert zeilen["Advent"]["fern"]["beschreibbar"] is False
    assert zeilen["Training"]["aus_reihe"] is True
    assert zeilen["Training"]["fern"]["vorkommen"] == "20261201T090000Z"


def test_ein_kaputter_eintrag_kostet_nicht_die_woche(klient, verbunden, fern):
    fern.termin(title="Gut")
    fern.termin(title="Kaputt", start="gestern")
    assert [t["titel"] for t in _fenster(klient).json()] == ["Gut"]


def test_ein_zu_langes_fenster_wird_abgewiesen(klient, verbunden, fern):
    antwort = _fenster(klient, bis="2028-06-01T00:00:00Z")
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "nextime_zeitraum_zu_lang"


def test_der_einzelabruf_bringt_notiz_regel_und_leute(klient, verbunden, fern):
    """Vor dem Bearbeiten geholt, sonst löschte ein leeres Feld die Notiz."""
    e = fern.termin(
        title="Jour fixe", notes="Agenda im Wiki", recurring=True, occurrence="20261201T090000Z",
        series_start="2026-11-03T09:00:00Z",
        rule={"freq": "weekly", "interval": 2, "weekdays": ["MO", "WE"], "monthly": "date", "end": "count",
              "until": None, "count": 10},
        organizer={"name": "Chefin", "email": "Chefin@example.org"},
        attendees=[{"name": "Robin", "email": "robin@example.org", "status": "accepted"},
                   {"name": "", "email": "kim@example.org", "status": "open"}],
    )
    z = klient.get(f"/api/nextime/termine/{e['id']}", params={"vorkommen": "20261201T090000Z"}).json()
    assert z["beschreibung"] == "Agenda im Wiki"
    assert z["rrule"] == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=10"
    assert (z["regel_freq"], z["regel_intervall"], z["regel_tage"]) == ("woechentlich", 2, ["MO", "WE"])
    assert z["regel_fremd"] is False
    assert z["organisator"]["adresse"] == "chefin@example.org"
    assert [(t["adresse"], t["antwort"]) for t in z["teilnehmer"]] == [
        ("robin@example.org", "ACCEPTED"), ("kim@example.org", "NEEDS-ACTION")]
    assert fern.parameter[-1] == {"occurrence": "20261201T090000Z"}


def test_monatlich_am_n_ten_wochentag(klient, verbunden, fern):
    e = fern.termin(title="Stammtisch", recurring=True, series_start="2026-11-19T18:00:00Z",
                    rule={"freq": "monthly", "interval": 1, "weekdays": [], "monthly": "nth", "end": "never",
                          "until": None, "count": None})
    z = klient.get(f"/api/nextime/termine/{e['id']}").json()
    assert z["rrule"] == "FREQ=MONTHLY;BYDAY=3TH"
    assert (z["regel_monatsart"], z["regel_ordinal"]) == ("wochentag", 3)


def test_anlegen_in_der_zone_des_kontos(klient, verbunden, fern):
    """AC-5: Wanduhr in Europe/Berlin, nicht UTC; Regel als nextime-Regel."""
    antwort = klient.post("/api/nextime/termine", json={
        "kalender_id": "nt:2", "titel": "Training", "beginn": "2026-12-01T08:00:00Z",
        "ende": "2026-12-01T09:30:00Z", "ort": "Halle", "beschreibung": "Mit Ball",
        "rrule": "FREQ=WEEKLY;BYDAY=TU;UNTIL=20270301", "anfrage": "abc-1"})
    assert antwort.status_code == 201, antwort.text
    _pfad, rumpf = fern.rumpfe[-1]
    assert rumpf["calendar_id"] == 2
    assert (rumpf["start"], rumpf["end"], rumpf["time_zone"]) == ("2026-12-01T09:00", "2026-12-01T10:30", "Europe/Berlin")
    assert rumpf["rule"] == {"freq": "weekly", "interval": 1, "weekdays": ["TU"], "monthly": "date",
                             "end": "until", "until": "2027-03-01"}
    assert rumpf["client_ref"] == "nexmail:abc-1"
    assert antwort.json()["kalender_id"] == "nt:2"


def test_ganztaegig_geht_mit_dem_letzten_tag_hinaus(klient, verbunden, fern):
    klient.post("/api/nextime/termine", json={
        "kalender_id": "nt:1", "titel": "Messe", "beginn": "2026-12-02T00:00:00Z",
        "ende": "2026-12-05T00:00:00Z", "ganztaegig": True})
    _pfad, rumpf = fern.rumpfe[-1]
    assert (rumpf["all_day"], rumpf["start"], rumpf["end"]) == (True, "2026-12-02", "2026-12-04")
    assert "time_zone" not in rumpf


def test_doppelt_angelegt_ist_einmal_da(klient, verbunden, fern):
    """EC-15: derselbe Schlüssel gibt den Termin vom ersten Mal."""
    wunsch = {"kalender_id": "nt:1", "titel": "Einmal", "beginn": "2026-12-01T08:00:00Z", "anfrage": "dop-1"}
    eins = klient.post("/api/nextime/termine", json=wunsch).json()
    zwei = klient.post("/api/nextime/termine", json=wunsch).json()
    assert eins["fern"]["id"] == zwei["fern"]["id"]
    assert len(fern.termine) == 1


def test_eine_regel_die_nextime_nicht_kennt_geht_nicht_hinaus(klient, verbunden, fern):
    antwort = klient.post("/api/nextime/termine", json={
        "kalender_id": "nt:1", "titel": "Seltsam", "beginn": "2026-12-01T08:00:00Z",
        "rrule": "FREQ=MONTHLY;BYDAY=1MO,3MO"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "nextime_regel_nicht_abbildbar"
    assert fern.zaehlen("POST", "events") == 0


def test_aendern_schickt_nur_was_kam(klient, verbunden, fern):
    """AC-6, EC-5: Umfang, Vorkommen und gelesene Fassung gehen mit."""
    e = fern.termin(title="Alt", notes="bleibt", recurring=True)
    antwort = klient.patch(f"/api/nextime/termine/{e['id']}", json={
        "titel": "Neu", "umfang": "dieser", "vorkommen": "20261201T090000Z", "etag": "e1",
        "rrule": "FREQ=DAILY"})
    assert antwort.status_code == 200, antwort.text
    _pfad, rumpf = fern.rumpfe[-1]
    # Bei „nur dieser“ gehört die Regel der Reihe und bleibt draußen.
    assert rumpf == {"scope": "this", "occurrence": "20261201T090000Z", "etag": "e1", "title": "Neu"}
    assert fern.termine[e["id"]]["notes"] == "bleibt"


def test_zeiten_gehen_zusammen_und_die_regel_auf_wunsch_weg(klient, verbunden, fern):
    e = fern.termin(title="Reihe", recurring=True)
    klient.patch(f"/api/nextime/termine/{e['id']}", json={
        "beginn": "2026-12-01T13:00:00Z", "ende": "2026-12-01T14:00:00Z", "ganztaegig": False,
        "zeitzone": "America/New_York", "rrule": "", "umfang": "alle"})
    _pfad, rumpf = fern.rumpfe[-1]
    assert (rumpf["start"], rumpf["end"], rumpf["time_zone"]) == ("2026-12-01T08:00", "2026-12-01T09:00", "America/New_York")
    assert rumpf["all_day"] is False
    # ``null`` heißt bei nextime: keine Wiederholung mehr.
    assert "rule" in rumpf and rumpf["rule"] is None


def test_nur_dieser_ohne_vorkommen_geht_nicht(klient, verbunden, fern):
    e = fern.termin(title="Reihe", recurring=True)
    antwort = klient.patch(f"/api/nextime/termine/{e['id']}", json={"titel": "x", "umfang": "dieser"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "vorkommen_fehlt"


def test_loeschen_mit_umfang(klient, verbunden, fern):
    e = fern.termin(title="Weg")
    antwort = klient.delete(f"/api/nextime/termine/{e['id']}", params={"umfang": "folgende", "vorkommen": "20261201T090000Z"})
    assert antwort.status_code == 204
    assert fern.parameter[-1] == {"scope": "following", "occurrence": "20261201T090000Z"}
    assert klient.delete(f"/api/nextime/termine/{e['id']}").status_code == 404


def test_die_suche_findet_nur_in_sichtbaren(klient, verbunden, fern):
    """AC-8."""
    fern.termin(title="Steuer abgeben", calendar_id=1)
    fern.termin(title="Steuer heimlich", calendar_id=5)
    treffer = klient.get("/api/nextime/suche", params={"q": "steuer"}).json()["treffer"]
    assert [t["titel"] for t in treffer] == ["Steuer abgeben"]
    assert klient.get("/api/nextime/suche", params={"q": "s"}).json()["treffer"] == []


def test_der_stand_ist_eine_zeichenkette(klient, verbunden, fern):
    """EC-6."""
    assert klient.get("/api/nextime/stand").json() == {"version": "v1"}
    fern.version = "v2"
    assert klient.get("/api/nextime/stand").json() == {"version": "v2"}


@pytest.mark.parametrize(("stoerung", "status", "kennung"), [
    ((500, "boom"), 502, "nextime_fehler"),
    ((429, "slow_down"), 429, "nextime_zu_viele_anfragen"),
    ((403, "token_reads_only"), 409, "nextime_nur_lesen"),
])
def test_absagen_von_nextime_werden_benannt(klient, verbunden, fern, stoerung, status, kennung):
    """EC-1, EC-2."""
    fern.stoerung = stoerung
    antwort = _fenster(klient)
    assert antwort.status_code == status
    assert antwort.json()["detail"] == kennung


# --- Einladungen (AC-9 bis AC-12, AC-18, EC-11 bis EC-16) ----------------------- #

KONTO = "termin@example.com"


def _einladung(klient, uid: str = "einl-1@example.org", *mehr: str, methode: str = "REQUEST") -> int:
    zeilen = [f"UID:{uid}", "SUMMARY:Quartalsrunde", "DTSTART:20261201T090000Z", "DTEND:20261201T100000Z",
              "ORGANIZER;CN=Chefin:mailto:chefin@example.org", f"ATTENDEE;CN=Robin:mailto:{KONTO}", *mehr]
    ics = _ics(*zeilen).replace("METHOD:REQUEST", f"METHOD:{methode}")
    return _mail_mit_einladung(klient, ics)


def _ausgang(db) -> list[str]:
    db.expire_all()
    return [a.betreff for a in db.query(Ausgang).all()]


@pytest.fixture
def leise(monkeypatch):
    """Antworten bleiben im Ausgang, statt hinauszugehen."""
    from app.services import termineinladung

    monkeypatch.setattr(termineinladung, "hinausschicken", lambda db, zeile: None)


def test_ohne_nextime_bleibt_die_karte_wie_sie_war(klient, ohne_netz, fern):  # noqa: F811
    einrichten(klient)
    kennung = _einladung(klient)
    assert klient.get(f"/api/termine/{kennung}").json()["nextime"] is None
    assert fern.anfragen == []


def test_die_karte_kennt_den_termin_in_nextime(klient, verbunden, fern):
    """AC-9."""
    e = fern.termin(uid="einl-1@example.org", calendar_id=2, invitation="tentative", title="Quartalsrunde")
    lage = klient.get(f"/api/termine/{_einladung(klient)}").json()["nextime"]
    assert (lage["termin_id"], lage["kalender_id"], lage["kalender_name"]) == (e["id"], "nt:2", "D&M")
    assert (lage["antwort"], lage["aus_mail"], lage["link"]) == ("vorbehalt", False, f"{WEB}{e['id']}")


def test_ueberschneidungen_ohne_hintergrund_und_ohne_sich_selbst(klient, verbunden, fern):
    """AC-12."""
    fern.termin(uid="einl-1@example.org", title="Quartalsrunde")
    fern.termin(title="Zahnarzt", calendar_id=2, start="2026-12-01T09:30:00Z", end="2026-12-01T10:30:00Z")
    fern.termin(title="Advent", calendar_id=3, background=True, start="2026-12-01T00:00:00Z", end="2026-12-02T00:00:00Z")
    fern.termin(title="Kim", calendar_id=4, busy_only=True)
    fern.termin(title="Später", start="2026-12-01T10:00:00Z", end="2026-12-01T11:00:00Z")
    lage = klient.get(f"/api/termine/{_einladung(klient)}").json()["nextime"]
    assert [(t["titel"], t["kalender"]) for t in lage["ueberschneidungen"]] == [("", "Kollegin"), ("Zahnarzt", "D&M")]


def test_ist_nextime_weg_kommt_die_karte_trotzdem(klient, verbunden, fern):
    """EC-1."""
    kennung = _einladung(klient)
    fern.stoerung = (500, "boom")
    daten = klient.get(f"/api/termine/{kennung}").json()
    assert daten["titel"] == "Quartalsrunde"
    assert daten["nextime"]["fehler"] == "nextime_fehler"


def test_antwort_ueber_die_quelle_schickt_keine_mail(klient, verbunden, fern, db, leise):
    """AC-9, EC-16: iCloud antwortet, nexmail nicht."""
    e = fern.termin(uid="einl-1@example.org", calendar_id=2, invitation="open")
    kennung = _einladung(klient)
    daten = klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage"}).json()
    assert fern.termine[e["id"]]["invitation"] == "accepted"
    assert _ausgang(db) == []
    assert daten["antwort"] == "zusage"
    assert daten["nextime"]["antwort"] == "zusage"


def test_antwort_an_einer_mail_kopie_geht_per_mail(klient, verbunden, fern, db, leise):
    fern.termin(uid="einl-1@example.org", invitation="open", origin="imip")
    kennung = _einladung(klient)
    klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "vorbehalt"})
    assert _ausgang(db) == ["Mit Vorbehalt: Quartalsrunde"]


def test_zusagen_traegt_in_einem_schritt_ein(klient, verbunden, fern, db, leise):
    """AC-10, AC-5: Eintragen ohne Senden durch nextime, Antwort per Mail, Vorwahl gemerkt."""
    kennung = _einladung(klient)
    daten = klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage", "kalender_id": "nt:2"}).json()
    pfad, rumpf = fern.rumpfe[-1]
    assert pfad == "events/ical"
    assert (rumpf["calendar_id"], rumpf["answer"], rumpf["attendee"]) == (2, "accepted", KONTO)
    assert "UID:einl-1@example.org" in rumpf["ical"]
    assert _ausgang(db) == ["Zugesagt: Quartalsrunde"]
    assert daten["nextime"]["kalender_id"] == "nt:2" and daten["nextime"]["aus_mail"] is True
    person = db.query(Benutzer).one()
    db.refresh(person)
    assert list(nextimeverbindung.vorwahl_lesen(person).values()) == ["nt:2"]
    assert daten["nextime"]["vorwahl"] == "nt:2"


def test_absagen_traegt_nichts_ein(klient, verbunden, fern, db, leise):
    kennung = _einladung(klient)
    klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "absage", "kalender_id": "nt:2"})
    assert fern.zaehlen("POST", "events/ical") == 0
    assert fern.termine == {}
    assert _ausgang(db) == ["Abgesagt: Quartalsrunde"]


def test_dieselbe_antwort_zweimal_schickt_nur_eine_mail(klient, verbunden, fern, db, leise):
    """EC-15."""
    fern.termin(uid="einl-1@example.org", invitation="open", origin="imip")
    kennung = _einladung(klient)
    klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage"})
    klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage"})
    assert _ausgang(db) == ["Zugesagt: Quartalsrunde"]


def test_kennt_die_quelle_ihn_schon_antwortet_sie(klient, verbunden, fern, db, leise):
    """EC-16: nextime meldet beim Eintragen ``existing`` mit ``source``.

    Der Nachbau liefert den Quell-Termin bei der UID-Suche nur, wenn er schon
    da ist; hier taucht er erst zwischen Suche und Eintragen auf."""
    kennung = _einladung(klient)
    echt = fern._ical

    def dazwischen(rumpf):
        fern.termin(uid="einl-1@example.org", calendar_id=2, invitation="open")
        return echt(rumpf)

    fern._ical = dazwischen
    klient.post(f"/api/termine/{kennung}/antwort", json={"antwort": "zusage", "kalender_id": "nt:1"})
    assert _ausgang(db) == []
    assert sum(1 for m, p in fern.anfragen if m == "POST" and p.endswith("/answer")) == 1


def test_eine_abgesagte_mail_kopie_geht_erst_auf_klick(klient, verbunden, fern):
    """AC-18: Erst die Karte, dann der Klick."""
    fern.termin(uid="einl-1@example.org", invitation="accepted", origin="imip")
    kennung = _einladung(klient, "einl-1@example.org", methode="CANCEL")
    lage = klient.get(f"/api/termine/{kennung}").json()
    assert lage["abgesagt"] is True and lage["nextime"]["aus_mail"] is True
    assert len(fern.termine) == 1
    daten = klient.post(f"/api/termine/{kennung}/nextime-entfernen").json()
    assert fern.termine == {}
    assert "METHOD:CANCEL" in fern.rumpfe[-1][1]["ical"]
    assert daten["nextime"]["termin_id"] is None


def test_einen_quell_termin_fasst_nexmail_nicht_an(klient, verbunden, fern):
    fern.termin(uid="einl-1@example.org", calendar_id=2, invitation="accepted")
    kennung = _einladung(klient, "einl-1@example.org", methode="CANCEL")
    antwort = klient.post(f"/api/termine/{kennung}/nextime-entfernen")
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextime_nicht_aus_mail"
    assert len(fern.termine) == 1


def test_eine_aenderung_wird_gezeigt_und_auf_klick_uebernommen(klient, verbunden, fern, db, leise):
    """AC-11."""
    fern.termin(uid="einl-1@example.org", invitation="accepted", origin="imip", title="Quartalsrunde",
                start="2026-12-01T08:00:00Z", end="2026-12-01T09:00:00Z")
    kennung = _einladung(klient)
    assert klient.get(f"/api/termine/{kennung}").json()["nextime"]["abweichungen"] == ["zeit"]
    klient.post(f"/api/termine/{kennung}/nextime-aktualisieren")
    pfad, rumpf = fern.rumpfe[-1]
    assert pfad == "events/ical" and rumpf["answer"] == "accepted"
    assert _ausgang(db) == []


# --- Termin aus einer Mail (AC-17, EC-15, EC-20, EC-21) --------------------------- #


def _mail(klient, db, text: str = "Treffen am Dienstag um 9 im Büro.") -> int:
    from app.models import Nachricht

    kennung = _einladung(klient, "ohne@example.org")
    m = db.get(Nachricht, kennung)
    m.message_id = "<plan@example.org>"
    m.betreff = "Planung"
    m.von_name = "Chefin"
    m.von_adresse = "chefin@example.org"
    m.koerper_text = text
    db.commit()
    return kennung


def test_aus_einer_mail_wird_ein_termin_in_nextime(klient, verbunden, fern, db):
    kennung = _mail(klient, db)
    antwort = klient.post(f"/api/termine/{kennung}/aus-mail", json={
        "kalender_id": "nt:2", "titel": "", "beginn": "2026-12-08T08:00:00Z", "anfrage": "f-1"})
    assert antwort.status_code == 201, antwort.text
    _pfad, rumpf = fern.rumpfe[-1]
    assert rumpf["title"] == "Planung"
    assert rumpf["notes"].startswith("From: Chefin <chefin@example.org>\nDate: ")
    assert "Subject: Planung" in rumpf["notes"] and rumpf["notes"].endswith("im Büro.")
    assert rumpf["client_ref"] == "nexmail:f-1"
    daten = antwort.json()
    assert daten["vorwahl"] == "nt:2"
    assert [(t["titel"], t["kalender"]) for t in daten["termine"]] == [("Planung", "nt:2")]
    assert daten["termine"][0]["link"].startswith(WEB)
    # Doppelklick: dieselbe Anfrage legt nichts Zweites an.
    klient.post(f"/api/termine/{kennung}/aus-mail", json={
        "kalender_id": "nt:2", "titel": "", "beginn": "2026-12-08T08:00:00Z", "anfrage": "f-1"})
    assert db.query(MailTermin).count() == 1
    assert len(fern.termine) == 1
    # Ein zweiter, bewusster Termin aus derselben Mail ist erlaubt.
    klient.post(f"/api/termine/{kennung}/aus-mail", json={
        "kalender_id": "nt:1", "titel": "Nachtreffen", "beginn": "2026-12-15T08:00:00Z", "anfrage": "f-2"})
    assert len(klient.get(f"/api/termine/{kennung}/aus-mail").json()["termine"]) == 2


def test_ein_langer_text_wird_gekuerzt(klient, verbunden, fern, db):
    """EC-21."""
    from app.routers import termine as router

    kennung = _mail(klient, db, text="x" * (router.NOTIZ_HOECHSTENS + 500))
    klient.post(f"/api/termine/{kennung}/aus-mail", json={
        "kalender_id": "nt:1", "titel": "Lang", "beginn": "2026-12-08T08:00:00Z"})
    notiz = fern.rumpfe[-1][1]["notes"]
    assert notiz.endswith(" …")
    assert len(notiz) < router.NOTIZ_HOECHSTENS + 300


def test_aus_einer_mail_auch_ohne_nextime(klient, ohne_netz, db):  # noqa: F811
    einrichten(klient)
    kalender_id = klient.post("/api/kalender", json={"name": "Eigen"}).json()["id"]
    kennung = _mail(klient, db)
    antwort = klient.post(f"/api/termine/{kennung}/aus-mail", json={
        "kalender_id": kalender_id, "titel": "Planung", "beginn": "2026-12-08T08:00:00Z"})
    assert antwort.status_code == 201, antwort.text
    termine = klient.get("/api/kalender/termine", params={
        "von": "2026-12-01T00:00:00Z", "bis": "2026-12-31T00:00:00Z"}).json()
    assert [t["titel"] for t in termine] == ["Planung"]
    assert "chefin@example.org" in termine[0]["beschreibung"]
    assert antwort.json()["termine"][0]["link"] == ""


# --- Nach dem Prüfbericht (23.11.2026) ------------------------------------------------ #


def test_alle_schickt_das_vorkommen_mit(klient, verbunden, fern):
    """Befund 1: Ohne Vorkommen verschiebt nextime bei „alle" die Reihe ab ihrem
    ersten Termin; die früheren Termine wären weg."""
    e = fern.termin(title="Reihe", recurring=True, occurrence="20261124T080000Z")
    antwort = klient.patch(f"/api/nextime/termine/{e['id']}", json={
        "beginn": "2026-11-24T09:00:00Z", "ende": "2026-11-24T10:00:00Z", "ganztaegig": False,
        "zeitzone": "Europe/Berlin", "umfang": "alle", "vorkommen": "20261124T080000Z", "etag": "e1"})
    assert antwort.status_code == 200, antwort.text
    _pfad, rumpf = fern.rumpfe[-1]
    assert (rumpf["scope"], rumpf["occurrence"]) == ("all", "20261124T080000Z")


def test_der_einzelabruf_liest_die_wanduhr_in_der_zone(klient, verbunden, fern):
    """Befund 2: nextime antwortet dort mit Ortszeit, nicht mit UTC."""
    e = fern.termin(title="Zahnarzt", start="2026-12-01T08:30:00Z", end="2026-12-01T09:30:00Z",
                    time_zone="Europe/Berlin")
    z = klient.get(f"/api/nextime/termine/{e['id']}").json()
    assert z["beginn"].startswith("2026-12-01T08:30:00")
    assert z["ende"].startswith("2026-12-01T09:30:00")


def test_ein_angelegter_termin_kommt_mit_der_richtigen_zeit_zurueck(klient, verbunden, fern, db):
    """Befund 2: Die Antwort auf das Anlegen ist Wanduhr; der Hinweis an der Mail
    zeigte sonst eine Stunde später."""
    antwort = klient.post("/api/nextime/termine", json={
        "kalender_id": "nt:1", "titel": "Training", "beginn": "2026-12-01T08:00:00Z"})
    assert antwort.json()["beginn"].startswith("2026-12-01T08:00:00")


def test_der_serienbeginn_kommt_als_objekt(klient, verbunden, fern):
    """Befund 3: ``series_start`` ist bei nextime ein Objekt mit Wanduhr."""
    e = fern.termin(title="Stammtisch", recurring=True, series_start="2026-11-19T18:00:00Z",
                    rule={"freq": "monthly", "interval": 1, "weekdays": [], "monthly": "last", "end": "never",
                          "until": None, "count": None})
    z = klient.get(f"/api/nextime/termine/{e['id']}").json()
    assert z["rrule"] == "FREQ=MONTHLY;BYDAY=-1TH"


def test_suchtreffer_aus_nur_belegt_sind_belegt(klient, verbunden, fern):
    """Befund 10: Die Suche nennt ``busy_only`` nicht; der Kalender sagt es."""
    fern.termin(title="Steuer Kim", calendar_id=4)
    treffer = klient.get("/api/nextime/suche", params={"q": "steuer"}).json()["treffer"]
    assert [(t["titel"], t["fern"]["nur_belegt"], t["fern"]["id"]) for t in treffer] == [("", True, None)]


def test_ueberschneidungen_nur_aus_sichtbaren_kalendern(klient, verbunden, fern):
    """Befund 11."""
    fern.termin(title="Ausgeblendet", calendar_id=5, start="2026-12-01T09:30:00Z", end="2026-12-01T10:30:00Z")
    fern.termin(title="Sichtbar", calendar_id=2, start="2026-12-01T09:30:00Z", end="2026-12-01T10:30:00Z")
    lage = klient.get(f"/api/termine/{_einladung(klient)}").json()["nextime"]
    assert [t["titel"] for t in lage["ueberschneidungen"]] == ["Sichtbar"]


# --- Auswahl der Kalender (Entscheidung 23.11.2026) ------------------------------------ #


def test_nicht_gewaehlte_kalender_erscheinen_nirgends(klient, verbunden, fern):
    assert klient.patch("/api/nextime/kalender/nt:2", json={"gewaehlt": False}).status_code == 200
    fern.termin(title="Elternabend", calendar_id=2)
    fern.termin(title="Zahnarzt", calendar_id=1)
    assert [k["id"] for k in klient.get("/api/nextime/kalender").json()] == ["nt:1", "nt:3", "nt:4", "nt:5"]
    alle = {k["id"]: k["gewaehlt"] for k in klient.get("/api/nextime/kalender", params={"alle": "true"}).json()}
    assert alle == {"nt:1": True, "nt:2": False, "nt:3": True, "nt:4": True, "nt:5": True}
    # Auch ausdrücklich verlangt, kommt er nicht.
    gewaehlt = klient.get("/api/nextime/termine", params=[
        ("von", "2026-11-30T00:00:00Z"), ("bis", "2026-12-07T00:00:00Z"), ("kalender", "nt:1"), ("kalender", "nt:2")])
    assert [t["titel"] for t in gewaehlt.json()] == ["Zahnarzt"]
    assert "2" not in fern.parameter[-1]["calendars"].split(",")
    assert [t["titel"] for t in klient.get("/api/nextime/suche", params={"q": "abend", "kalender": "nt:2"}).json()["treffer"]] == []
    antwort = klient.post("/api/nextime/termine", json={"kalender_id": "nt:2", "titel": "x", "beginn": "2026-12-01T08:00:00Z"})
    assert antwort.status_code == 404
    lage = klient.get(f"/api/termine/{_einladung(klient)}").json()["nextime"]
    assert all(t["kalender"] != "D&M" for t in lage["ueberschneidungen"])
    # Ein neuer Kalender in nextime ist von selbst dabei; zurück wählen geht auch.
    fern.kalender.append({**fern.kalender[0], "id": 6, "name": "Neu", "default": False})
    assert "nt:6" in [k["id"] for k in klient.get("/api/nextime/kalender").json()]
    klient.patch("/api/nextime/kalender/nt:2", json={"gewaehlt": True})
    assert "nt:2" in [k["id"] for k in klient.get("/api/nextime/kalender").json()]


def test_zwei_gleichzeitige_zusagen_schicken_eine_antwort(klient, verbunden, fern, db, leise):
    """Befund 4: nacheinander unter einem Schloss sieht die zweite die erste."""
    import threading

    kennung = _einladung(klient)
    ergebnisse = []

    def zusagen():
        ergebnisse.append(klient.post(f"/api/termine/{kennung}/antwort",
                                      json={"antwort": "zusage", "kalender_id": "nt:2"}).status_code)

    faeden = [threading.Thread(target=zusagen) for _ in range(2)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()
    assert ergebnisse == [200, 200]
    assert _ausgang(db) == ["Zugesagt: Quartalsrunde"]
    assert len([e for e in fern.termine.values() if e["uid"] == "einl-1@example.org"]) == 1
