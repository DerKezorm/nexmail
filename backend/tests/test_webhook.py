"""Webhook als Aufgabenziel (Issue #17), und der Haken zurück über ``/api/v1``.

Gesprochen wird mit einem nachgebauten Empfänger (``Empfaenger`` unten). Was
hier steht, sind die Zusagen an fremde Programme: die Form des POST, die
Unterschrift, dass nichts halb bleibt, und dass der Text der Mail nur mit
beiden Schaltern hinausgeht.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.db import einstellung_schreiben
from app.models import Aufgabe, Aufgabenverbindung, Nachricht
from app.routers import aufgaben as aufgaben_router
from app.services import aufgabenziele, netzfreigabe, webhook
from conftest import anmelden, zweiten_benutzer_anlegen
from test_aufgaben import ohne_netz, welt  # noqa: F401

ADRESSE = "https://praxis.example.com/hooks/nexmail"


class Empfaenger:
    """Ein Empfänger im Speicher: merkt sich jeden Aufruf, antwortet wie eingestellt."""

    def __init__(self) -> None:
        self.aufrufe: list[httpx.Request] = []
        self.status = 200
        self.antwort: dict | str | None = None
        self.kopf: dict[str, str] = {}

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        self.aufrufe.append(anfrage)
        if isinstance(self.antwort, dict):
            return httpx.Response(self.status, json=self.antwort, headers=self.kopf)
        return httpx.Response(self.status, text=self.antwort or "", headers=self.kopf)

    def rumpfe(self, ereignis: str | None = None) -> list[dict]:
        alle = [json.loads(a.content) for a in self.aufrufe]
        return [r for r in alle if ereignis is None or r["event"] == ereignis]


@pytest.fixture
def empfaenger(monkeypatch):
    e = Empfaenger()
    monkeypatch.setattr(webhook, "TRANSPORT", httpx.MockTransport(e))
    return e


def _verbinden(klient, **mehr):
    return klient.post("/api/aufgabenziele/webhook", json={"url": ADRESSE, **mehr})


@pytest.fixture
def verbunden(klient, welt, empfaenger):  # noqa: F811
    antwort = _verbinden(klient, name="Praxis")
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _ziel(verbunden) -> str:
    return f"{verbunden['verbindung']['id']}:webhook"


def _anlegen(klient, nachricht_id, ziel, **mehr):
    return klient.post(
        "/api/aufgaben/mit-ziel", json={"nachricht_id": nachricht_id, "ziel": ziel, **mehr}
    )


# --- Verbinden ------------------------------------------------------------- #


def test_verbinden_schickt_ein_ping_und_gibt_das_geheimnis_einmal_heraus(klient, verbunden, empfaenger, db):
    geheimnis = verbunden["geheimnis"]
    assert geheimnis.startswith("whsec_")
    assert [r["event"] for r in empfaenger.rumpfe()] == ["ping"]

    zeile = db.get(Aufgabenverbindung, verbunden["verbindung"]["id"])
    assert zeile.art == "webhook"
    assert geheimnis not in zeile.zugang
    assert ADRESSE not in zeile.zugang
    # ⚠️ Danach nie wieder: weder im Stand noch in den Einstellungen.
    assert geheimnis not in klient.get("/api/aufgabenziele").text
    einstellung = klient.get(f"/api/aufgabenziele/{zeile.id}/webhook").json()
    assert einstellung == {"url": ADRESSE, "nur_senden": False, "mit_text": False, "mailtext_erlaubt": False}
    assert geheimnis not in json.dumps(einstellung)


def test_ein_eigenes_geheimnis_wird_genommen(klient, welt, empfaenger):  # noqa: F811
    antwort = _verbinden(klient, geheimnis="  mein-geheimnis  ")
    assert antwort.json()["geheimnis"] == "mein-geheimnis"


def test_die_unterschrift_laesst_sich_nachrechnen(klient, verbunden, empfaenger):
    anfrage = empfaenger.aufrufe[0]
    zeit = anfrage.headers["x-nexmail-timestamp"]
    erwartet = hmac.new(
        verbunden["geheimnis"].encode(), zeit.encode() + b"." + anfrage.content, hashlib.sha256
    ).hexdigest()
    assert anfrage.headers["x-nexmail-signature"] == f"sha256={erwartet}"
    assert anfrage.headers["x-nexmail-event"] == "ping"
    assert anfrage.headers["content-type"] == "application/json"
    assert len(anfrage.headers["x-nexmail-delivery"]) == 32


def test_eine_adresse_ohne_2xx_wird_nie_gespeichert(klient, welt, empfaenger, db):  # noqa: F811
    empfaenger.status = 500
    antwort = _verbinden(klient)
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "webhook_fehler"
    assert antwort.json()["werte"] == {"status": 500}
    assert db.query(Aufgabenverbindung).count() == 0


def test_eine_weiterleitung_wird_nicht_verfolgt(klient, welt, empfaenger):  # noqa: F811
    """⚠️ Sonst zeigte eine gepruefte Adresse per 302 doch ins Heimnetz."""
    empfaenger.status = 302
    empfaenger.kopf = {"location": "http://172.16.0.1/"}
    antwort = _verbinden(klient)
    assert antwort.json()["detail"] == "webhook_weiterleitung"
    assert len(empfaenger.aufrufe) == 1


@pytest.mark.parametrize(
    "url, kennung",
    [
        ("http://localhost:8080/x", "webhook_adresse_localhost"),
        ("http://127.0.0.1/x", "webhook_adresse_localhost"),
        ("http://[::1]/x", "webhook_adresse_localhost"),
        ("http://app.localhost/x", "webhook_adresse_localhost"),
        ("ftp://praxis.example.com/x", "webhook_adresse_ungueltig"),
        ("https://nutzer:pw@praxis.example.com/x", "webhook_adresse_ungueltig"),
    ],
)
def test_unpassende_adressen_werden_vor_jedem_aufruf_abgewiesen(klient, welt, empfaenger, url, kennung):  # noqa: F811
    antwort = klient.post("/api/aufgabenziele/webhook", json={"url": url})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == kennung
    assert empfaenger.aufrufe == []


def test_das_eigene_netz_gibt_nur_der_betreiber_frei(klient, welt, db):  # noqa: F811
    """Dieselbe Prüfung wie bei den Kalendern, ohne Transport, also echt."""
    with pytest.raises(webhook.WebhookFehler) as fehler:
        webhook._pruefen("http://172.16.5.10:8080/hook")
    assert fehler.value.kennung == "webhook_adresse_im_eigenen_netz"

    netzfreigabe.erlauben(db, True)
    webhook._pruefen("http://172.16.5.10:8080/hook")
    # ⚠️ Der eigene Rechner bleibt auch mit Freigabe zu, nur mit eigenem Satz.
    with pytest.raises(webhook.WebhookFehler) as fehler:
        webhook._pruefen("http://127.0.0.1:8080/hook")
    assert fehler.value.kennung == "webhook_adresse_localhost"
    with pytest.raises(webhook.WebhookFehler) as fehler:
        webhook._pruefen("http://169.254.169.254/latest")
    assert fehler.value.kennung == "webhook_adresse_im_eigenen_netz"


def test_die_bremse_haelt_viele_versuche_auf(klient, welt, empfaenger):  # noqa: F811
    codes = [_verbinden(klient).status_code for _ in range(12)]
    assert 429 in codes


# --- Listen und Anlegen ---------------------------------------------------- #


def test_ein_webhook_hat_eine_liste_nach_seinem_rechner(klient, verbunden, empfaenger):
    gruppen = klient.get("/api/aufgabenziele/listen").json()
    assert gruppen == [
        {
            "verbindung_id": verbunden["verbindung"]["id"],
            "art": "webhook",
            "name": "Praxis",
            "fehler": "",
            "listen": [{"ziel": _ziel(verbunden), "name": "praxis.example.com"}],
        }
    ]
    # Gefragt wird dafür nicht.
    assert len(empfaenger.aufrufe) == 1


def test_aus_einer_mail_wird_ein_task_created(klient, verbunden, welt, empfaenger, db):  # noqa: F811
    _, _, ids = welt
    einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
    empfaenger.antwort = {"id": 4711, "url": "https://praxis.example.com/aufgaben/4711"}
    antwort = _anlegen(
        klient, ids[0], _ziel(verbunden), titel=" Rechnung  prüfen ", liste_name="Webhook · Praxis › praxis.example.com", faellig="2026-11-10"
    )
    assert antwort.status_code == 200, antwort.text
    zeile = antwort.json()["aufgabe"]
    assert zeile["fern_art"] == "webhook"
    assert zeile["fern_url"] == "https://praxis.example.com/aufgaben/4711"
    assert zeile["betreff"] == "Rechnung prüfen"

    (rumpf,) = empfaenger.rumpfe("task.created")
    assert rumpf["task"] == {
        "id": str(zeile["id"]),
        "external_id": None,
        "title": "Rechnung prüfen",
        "due_date": "2026-11-10",
        "completed_at": None,
    }
    mail = rumpf["message"]
    assert mail["message_id"] == "<mail0@example.com>"
    assert mail["subject"] == "Mail 0"
    assert mail["from"] == "wer@example.com"
    assert mail["from_name"] == "Wer Auch Immer"
    assert mail["date"] == "2026-09-01T12:00:00Z"
    assert mail["link"] == "https://mail.example.com/?mail=%3Cmail0%40example.com%3E"
    assert mail["mailbox"]
    # ⚠️ Ab Werk geht kein Text hinaus.
    assert "text" not in mail and "html" not in mail

    a = db.get(Aufgabe, zeile["id"])
    assert (a.fern_id, a.nur_gesendet) == ("4711", False)


def test_eine_antwort_ohne_json_ist_kein_fehler(klient, verbunden, welt, empfaenger):  # noqa: F811
    _, _, ids = welt
    empfaenger.status, empfaenger.antwort = 204, None
    antwort = _anlegen(klient, ids[0], _ziel(verbunden))
    assert antwort.status_code == 200
    assert antwort.json()["aufgabe"]["fern_url"] == ""


def test_ein_link_aus_der_antwort_muss_http_sein(klient, verbunden, welt, empfaenger):  # noqa: F811
    _, _, ids = welt
    empfaenger.antwort = {"id": "x", "url": "javascript:alert(1)"}
    assert _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["fern_url"] == ""


def test_scheitert_der_post_bleibt_nichts_halb(klient, verbunden, welt, empfaenger, db):  # noqa: F811
    _, _, ids = welt
    empfaenger.status = 503
    antwort = _anlegen(klient, ids[0], _ziel(verbunden))
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "webhook_fehler"
    assert db.query(Aufgabe).count() == 0
    stand = klient.get("/api/aufgabenziele").json()
    assert stand["verbindungen"][0]["fehler"] == "webhook_fehler"

    # Der nächste Versuch klappt und räumt den Fehler weg.
    empfaenger.status = 200
    assert _anlegen(klient, ids[0], _ziel(verbunden)).json()["neu"] is True
    assert klient.get("/api/aufgabenziele").json()["verbindungen"][0]["fehler"] == ""


def test_zweimal_dieselbe_mail_sendet_einmal(klient, verbunden, welt, empfaenger):  # noqa: F811
    _, _, ids = welt
    erste = _anlegen(klient, ids[0], _ziel(verbunden)).json()
    zweite = _anlegen(klient, ids[0], _ziel(verbunden)).json()
    assert (erste["neu"], zweite["neu"]) == (True, False)
    assert zweite["aufgabe"]["id"] == erste["aufgabe"]["id"]
    assert len(empfaenger.rumpfe("task.created")) == 1


# --- Nur senden ------------------------------------------------------------ #


def test_nur_senden_fuehrt_keine_aufgabe_in_nexmail(klient, welt, empfaenger, db):  # noqa: F811
    _, _, ids = welt
    v = _verbinden(klient, nur_senden=True).json()
    erste = _anlegen(klient, ids[0], _ziel(v)).json()
    assert erste["neu"] is True
    assert len(empfaenger.rumpfe("task.created")) == 1

    # ⚠️ Nicht in der Liste, nicht offen gezählt …
    assert klient.get("/api/aufgaben").json() == []
    assert db.get(Aufgabe, erste["aufgabe"]["id"]).nur_gesendet is True
    from app.services import aufgaben as dienst
    from app.models import Benutzer

    person = db.query(Benutzer).one()
    assert dienst.offene(db, person) == 0

    # … aber ein zweiter Klick sendet nicht noch einmal und sagt, wohin es ging.
    zweite = _anlegen(klient, ids[0], _ziel(v)).json()
    assert zweite["neu"] is False
    assert zweite["aufgabe"]["fern_art"] == "webhook"
    assert len(empfaenger.rumpfe("task.created")) == 1


def test_die_einstellungen_lassen_sich_aendern(klient, verbunden, empfaenger, db):
    vid = verbunden["verbindung"]["id"]
    antwort = klient.put(
        f"/api/aufgabenziele/{vid}/webhook", json={"url": ADRESSE, "nur_senden": True, "mit_text": True}
    )
    assert antwort.json() == {"url": ADRESSE, "nur_senden": True, "mit_text": True, "mailtext_erlaubt": False}
    # Gleiche Adresse: kein neues ping.
    assert len(empfaenger.aufrufe) == 1


def test_eine_neue_adresse_braucht_erst_ihr_ping(klient, verbunden, empfaenger):
    vid = verbunden["verbindung"]["id"]
    neu = "https://anders.example.com/hook"
    empfaenger.status = 404
    antwort = klient.put(f"/api/aufgabenziele/{vid}/webhook", json={"url": neu})
    assert antwort.status_code == 502
    assert klient.get(f"/api/aufgabenziele/{vid}/webhook").json()["url"] == ADRESSE

    empfaenger.status = 200
    assert klient.put(f"/api/aufgabenziele/{vid}/webhook", json={"url": neu}).json()["url"] == neu
    assert str(empfaenger.aufrufe[-1].url) == neu


# --- Der Text der Mail ------------------------------------------------------ #


def _mit_koerper(db, nachricht_id, text="Bitte bis Freitag.", html="<p>Bitte bis <b>Freitag</b>.</p>"):
    n = db.get(Nachricht, nachricht_id)
    n.koerper_text, n.koerper_html = text, html
    n.koerper_geholt = datetime(2026, 9, 1, tzinfo=timezone.utc)
    db.commit()


def test_der_text_geht_nur_mit_beiden_schaltern_hinaus(klient, welt, empfaenger, db):  # noqa: F811
    _, _, ids = welt
    _mit_koerper(db, ids[0])
    _mit_koerper(db, ids[1])
    v = _verbinden(klient, mit_text=True).json()

    # Der Benutzer will, der Betreiber hat nicht erlaubt: kein Text.
    _anlegen(klient, ids[0], _ziel(v))
    assert "text" not in empfaenger.rumpfe("task.created")[-1]["message"]

    assert klient.put("/api/einstellungen/webhook-mailtext", json={"erlaubt": True}).json() == {"erlaubt": True}
    vid = v["verbindung"]["id"]
    assert klient.get(f"/api/aufgabenziele/{vid}/webhook").json()["mailtext_erlaubt"] is True
    _anlegen(klient, ids[1], _ziel(v))
    mail = empfaenger.rumpfe("task.created")[-1]["message"]
    assert mail["text"] == "Bitte bis Freitag."
    assert mail["html"] == "<p>Bitte bis <b>Freitag</b>.</p>"
    assert mail["text_truncated"] is False


def test_ohne_textfeld_kommt_der_text_aus_dem_html(klient, welt, empfaenger, db):  # noqa: F811
    _, _, ids = welt
    _mit_koerper(db, ids[0], text="", html="<p>Nur <b>HTML</b> hier</p>")
    einstellung_schreiben(db, webhook.SCHALTER_TEXT, "1")
    v = _verbinden(klient, mit_text=True).json()
    _anlegen(klient, ids[0], _ziel(v))
    assert empfaenger.rumpfe("task.created")[-1]["message"]["text"] == "Nur HTML hier"


def test_zu_langes_html_faellt_weg_statt_mitten_in_einer_marke_zu_enden(klient, welt, empfaenger, db, monkeypatch):  # noqa: F811
    _, _, ids = welt
    monkeypatch.setattr(aufgabenziele, "MAX_MAILTEXT", 20)
    _mit_koerper(db, ids[0], text="x" * 30, html="<p>" + "y" * 30 + "</p>")
    einstellung_schreiben(db, webhook.SCHALTER_TEXT, "1")
    v = _verbinden(klient, mit_text=True).json()
    _anlegen(klient, ids[0], _ziel(v))
    mail = empfaenger.rumpfe("task.created")[-1]["message"]
    assert (mail["text"], mail["html"], mail["text_truncated"]) == ("x" * 20, None, True)


def test_laesst_sich_der_text_nicht_holen_geht_nichts_hinaus(klient, welt, empfaenger, db, monkeypatch):  # noqa: F811
    _, _, ids = welt
    geholt = []
    monkeypatch.setattr(aufgaben_router, "_koerper_sicherstellen", lambda db, n: geholt.append(n.id))
    einstellung_schreiben(db, webhook.SCHALTER_TEXT, "1")
    v = _verbinden(klient, mit_text=True).json()
    antwort = _anlegen(klient, ids[0], _ziel(v))
    assert geholt == [ids[0]]
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "webhook_mailtext_fehlt"
    assert empfaenger.rumpfe("task.created") == []
    assert db.query(Aufgabe).count() == 0


def test_nur_der_betreiber_legt_den_textschalter_um(klient, welt, db):  # noqa: F811
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(klient, "zweiter", "auch-geheim-456", geheimnis)
    assert klient.put("/api/einstellungen/webhook-mailtext", json={"erlaubt": True}).status_code == 403


# --- Der Haken ------------------------------------------------------------- #


def test_abhaken_in_nexmail_geht_als_ereignis_hinaus(klient, verbunden, welt, empfaenger):  # noqa: F811
    _, _, ids = welt
    empfaenger.antwort = {"id": "a-1"}
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]

    zu = klient.patch(f"/api/aufgaben/{aid}", json={"erledigt": True})
    assert zu.status_code == 200 and zu.json()["erledigt"] is not None
    (rumpf,) = empfaenger.rumpfe("task.completed")
    assert rumpf["task"]["id"] == str(aid)
    assert rumpf["task"]["external_id"] == "a-1"
    assert rumpf["task"]["completed_at"]
    assert rumpf["message"]["message_id"] == "<mail0@example.com>"

    klient.patch(f"/api/aufgaben/{aid}", json={"erledigt": False})
    (rumpf,) = empfaenger.rumpfe("task.reopened")
    assert rumpf["task"]["completed_at"] is None


def test_lehnt_der_empfaenger_ab_bleibt_der_haken(klient, verbunden, welt, empfaenger):  # noqa: F811
    _, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    empfaenger.status = 500
    antwort = klient.patch(f"/api/aufgaben/{aid}", json={"erledigt": True})
    assert antwort.status_code == 502
    assert klient.get("/api/aufgaben").json()[0]["erledigt"] is None


def test_der_abgleich_fragt_keinen_webhook_und_laesst_den_fehler_stehen(klient, verbunden, welt, empfaenger, db):  # noqa: F811
    zeile = db.get(Aufgabenverbindung, verbunden["verbindung"]["id"])
    zeile.letzter_fehler = "webhook_fehler"
    db.commit()
    aufgabenziele._zuletzt_beim_oeffnen.clear()
    vorher = len(empfaenger.aufrufe)
    assert klient.post("/api/aufgaben/abgleichen").status_code == 204
    assert len(empfaenger.aufrufe) == vorher
    db.refresh(zeile)
    assert zeile.letzter_fehler == "webhook_fehler"


def test_test_senden_meldet_den_status_und_merkt_ihn(klient, verbunden, empfaenger):
    vid = verbunden["verbindung"]["id"]
    assert klient.post(f"/api/aufgabenziele/{vid}/test").status_code == 204
    empfaenger.status = 401
    antwort = klient.post(f"/api/aufgabenziele/{vid}/test")
    assert antwort.status_code == 502
    assert antwort.json()["werte"] == {"status": 401}
    assert klient.get("/api/aufgabenziele").json()["verbindungen"][0]["fehler"] == "webhook_fehler"


def test_ein_fremder_webhook_ist_unbekannt(klient, verbunden, db):
    vid = verbunden["verbindung"]["id"]
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(klient, "zweiter", "auch-geheim-456", geheimnis)
    assert klient.get(f"/api/aufgabenziele/{vid}/webhook").status_code == 404
    assert klient.post(f"/api/aufgabenziele/{vid}/test").status_code == 404


# --- Zurück über /api/v1 ---------------------------------------------------- #


def _schluessel(klient, konto_id, aufgaben=True) -> dict:
    assert klient.put("/api/apischluessel/erlaubt", json={"erlaubt": True}).status_code == 200
    antwort = klient.post(
        "/api/apischluessel",
        json={"name": "Praxis", "stufe": "anzahl", "konten": [konto_id], "aufgaben": aufgaben},
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["aufgaben"] is aufgaben
    return {"Authorization": f"Bearer {antwort.json()['schluessel']}"}


def test_der_empfaenger_hakt_ueber_die_api_ab_ohne_echo(klient, verbunden, welt, empfaenger):  # noqa: F811
    konto_id, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    assert klient.get("/api/v1/me", headers=kopf).json()["key"]["tasks"] is True

    zu = klient.post(f"/api/v1/tasks/{aid}/complete", headers=kopf)
    assert zu.status_code == 200, zu.text
    assert zu.json()["done"] is True and zu.json()["completed_at"]
    assert klient.get("/api/aufgaben").json()[0]["erledigt"] is not None
    # ⚠️ Kein task.completed zurück an den, der es gerade gemeldet hat.
    assert empfaenger.rumpfe("task.completed") == []

    auf = klient.post(f"/api/v1/tasks/{aid}/reopen", headers=kopf)
    assert auf.json()["done"] is False
    assert empfaenger.rumpfe("task.reopened") == []


def test_ein_schluessel_ohne_aufgaben_darf_nicht_abhaken(klient, verbunden, welt):  # noqa: F811
    konto_id, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id, aufgaben=False)
    antwort = klient.post(f"/api/v1/tasks/{aid}/complete", headers=kopf)
    assert antwort.status_code == 403
    assert antwort.json()["detail"] == "api_schluessel_ohne_aufgaben"


def test_nur_aufgaben_aus_den_postfaechern_am_schluessel(klient, verbunden, welt, db):  # noqa: F811
    konto_id, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    for falsch in ("999999", "abc", "-1"):
        assert klient.post(f"/api/v1/tasks/{falsch}/complete", headers=kopf).status_code == 404
    # Das Postfach fällt vom Schlüssel: dieselbe Aufgabe ist unbekannt.
    a = db.get(Aufgabe, aid)
    a.konto_id = "anderes-postfach"
    db.commit()
    assert klient.post(f"/api/v1/tasks/{aid}/complete", headers=kopf).status_code == 404


def test_eine_sitzung_oeffnet_die_aufgaben_unter_v1_nicht(klient, verbunden, welt):  # noqa: F811
    _, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    assert klient.post(f"/api/v1/tasks/{aid}/complete").status_code == 401


def test_der_generische_weg_nimmt_keinen_webhook(klient, welt, empfaenger):  # noqa: F811
    antwort = klient.post("/api/aufgabenziele", json={"art": "webhook", "zugang": ADRESSE})
    assert antwort.json()["detail"] == "aufgabenart_unbekannt"
    assert empfaenger.aufrufe == []
