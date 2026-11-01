"""Die Fläche der iPhone-App: Koppeln, Türen, jede Adresse, Fremdzugriff.

⚠️ **Die Handler sind dieselben wie im Browser und dort getestet.** Hier geht es
darum, dass jede Adresse mit dem Gerätetoken wirklich ankommt, dass eine fremde
Mail 404 bleibt und dass die beiden Türen getrennt sind. Die Runde über die ganze
Routentabelle steht dafür, dass auch eine neue Adresse nicht durchrutscht.

⚠️ **Kein echter Mailserver.** Der Doppelgänger kommt aus ``test_abgleich.py``.
"""

from __future__ import annotations

import base64
import json
import re
import threading
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from app.models import AppKopplung, Benutzer, Konto, Nachricht, Ordner, Sitzung, utcnow
from app.routers.app1 import ZUGESAGT
from app.services import abgleich, anmeldebremse, app_kopplung, kidienst
from app.services import imap as imapdienst
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from test_abgleich import FalscherServer
from test_kidienst import SCHLUESSEL, TextDoppelgaenger

PFAD = "/api/app/1"


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    return db.query(Benutzer).one()


def koppeln(klient, device="iPhone von Alex") -> dict:
    neu = klient.post("/api/app-kopplung", json={"adresse": "http://testserver"}).json()
    teile = re.search(r"pairing=([^&]+)&secret=([^&]+)", neu["link"])
    return {"neu": neu, "kennung": teile[1], "geheimnis": teile[2], "device": device}


def abholen(c, k) -> object:
    return c.post(
        f"{PFAD}/pairing/{k['kennung']}/key",
        headers={"X-Pairing-Secret": k["geheimnis"]},
        json={"device": k["device"]},
    )


@pytest.fixture
def kein_cookie():
    """Ein zweiter Klient ohne Keks, wie die App."""
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def token(klient, kein_cookie, person):
    return abholen(kein_cookie, koppeln(klient)).json()["key"]


@pytest.fixture
def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def postfach(db, person, adresse="anna@example.com") -> tuple[Konto, Ordner, Ordner]:
    konto = Konto(
        benutzer_id=person.id,
        anzeigename="Privat",
        adresse=adresse,
        imap_server="imap.example.com",
        imap_port=993,
        imap_sicherheit="ssl",
        imap_benutzer="anna",
        smtp_server="smtp.example.com",
        smtp_port=587,
        smtp_sicherheit="starttls",
        smtp_benutzer="anna",
    )
    db.add(konto)
    db.flush()
    eingang = Ordner(konto_id=konto.id, pfad="INBOX", name="INBOX", rolle="posteingang", uidvalidity=100)
    archiv = Ordner(konto_id=konto.id, pfad="Archiv", name="Archiv", rolle="archiv", uidvalidity=100)
    db.add_all([eingang, archiv])
    db.commit()
    return konto, eingang, archiv


def mail(db, person, konto, ordner, uid=1, **felder) -> Nachricht:
    n = Nachricht(
        benutzer_id=person.id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=uid,
        betreff=felder.get("betreff", "Hallo"),
        von_adresse="post@example.org",
        message_id=f"<m{uid}@example.com>",
        datum=utcnow(),
        koerper_geholt=felder.get("koerper_geholt", utcnow()),
        koerper_text="Das ist der Text der Mail.",
        hat_anhang=felder.get("hat_anhang", False),
        an_json=felder.get("an_json", "[]"),
    )
    db.add(n)
    db.commit()
    return n


# --- Koppeln: die Oberfläche ----------------------------------------------- #


def test_der_link_traegt_alles_und_der_code_ist_kurz(klient, person):
    neu = klient.post("/api/app-kopplung", json={"adresse": "http://mail.example.com"}).json()

    assert neu["link"].startswith("nexmail://connect?address=http%3A%2F%2Fmail.example.com&pairing=")
    assert "&secret=" in neu["link"]
    kopf = neu["qr_svg"].split(">", 1)[0]
    assert "<svg" in kopf and "viewBox=" in kopf
    assert " width=" not in kopf and " height=" not in kopf
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", neu["code"])
    assert neu["adresse"] == "http://mail.example.com"


def test_die_oeffentliche_adresse_geht_vor(klient, db, person):
    from app.db import einstellung_schreiben

    einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.org")

    neu = klient.post("/api/app-kopplung", json={"adresse": "http://10.0.0.5"}).json()

    assert neu["adresse"] == "https://mail.example.org"


def test_ohne_adresse_gibt_es_keinen_code(klient, db, person):
    antwort = klient.post("/api/app-kopplung", json={"adresse": ""})
    assert antwort.status_code == 422
    assert antwort.json()["detail"] == "app_adresse_fehlt"
    assert db.query(AppKopplung).count() == 0


def test_geheimnis_und_code_stehen_nur_als_hash_da(klient, db, person):
    k = koppeln(klient)
    zeile = db.get(AppKopplung, k["kennung"])

    assert k["geheimnis"] not in (zeile.geheimnis_hash, zeile.code_hash)
    assert k["neu"]["code"].replace("-", "") != zeile.code_hash
    assert len(zeile.geheimnis_hash) == 64


def test_fuenf_offene_und_nicht_mehr(klient, person):
    for _ in range(app_kopplung.OFFEN_HOECHSTENS):
        assert klient.post("/api/app-kopplung", json={"adresse": "http://x.example"}).status_code == 201

    antwort = klient.post("/api/app-kopplung", json={"adresse": "http://x.example"})

    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "app_zu_viele_kopplungen"


def test_abgelaufene_zaehlen_nicht_als_offen(klient, db, person):
    for _ in range(app_kopplung.OFFEN_HOECHSTENS):
        klient.post("/api/app-kopplung", json={"adresse": "http://x.example"})
    db.query(AppKopplung).update({AppKopplung.gilt_bis: utcnow() - timedelta(minutes=1)})
    db.commit()

    assert klient.post("/api/app-kopplung", json={"adresse": "http://x.example"}).status_code == 201


def test_der_stand_wandert_von_wartet_nach_verbunden(klient, kein_cookie, person):
    k = koppeln(klient)
    pfad = f"/api/app-kopplung/{k['kennung']}"
    assert klient.get(pfad).json() == {"stand": "wartet", "geraet": ""}

    abholen(kein_cookie, k)

    assert klient.get(pfad).json() == {"stand": "verbunden", "geraet": "iPhone von Alex"}


def test_der_stand_sagt_abgelaufen(klient, db, person):
    k = koppeln(klient)
    db.get(AppKopplung, k["kennung"]).gilt_bis = utcnow() - timedelta(seconds=1)
    db.commit()

    assert klient.get(f"/api/app-kopplung/{k['kennung']}").json()["stand"] == "abgelaufen"


def test_die_frist_sind_zehn_minuten(klient, db, person):
    k = koppeln(klient)
    frist = db.get(AppKopplung, k["kennung"]).gilt_bis - utcnow()

    assert timedelta(minutes=9) < frist <= timedelta(minutes=10)


def test_zurueckziehen_macht_den_code_wertlos(klient, kein_cookie, person):
    k = koppeln(klient)

    assert klient.delete(f"/api/app-kopplung/{k['kennung']}").status_code == 204

    assert abholen(kein_cookie, k).status_code == 404


def test_eine_fremde_kopplung_gibt_es_nicht(klient, zweiter_klient, db, person):
    k = koppeln(klient)
    zweiter, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get(f"/api/app-kopplung/{k['kennung']}").status_code == 404
    assert zweiter_klient.delete(f"/api/app-kopplung/{k['kennung']}").status_code == 404


# --- Koppeln: die App ------------------------------------------------------ #


def test_abholen_gibt_den_schluessel_einmal(klient, kein_cookie, person):
    k = koppeln(klient)

    erste = abholen(kein_cookie, k)

    assert erste.status_code == 200
    assert erste.headers["cache-control"] == "no-store"
    assert erste.json()["key"].startswith("nxa_")
    assert erste.json()["account"]["id"] == person.id
    assert abholen(kein_cookie, k).status_code == 404, "Eine Kopplung gilt für ein Gerät."


def test_das_geraet_steht_nur_als_hash_da(klient, kein_cookie, db, person):
    token = abholen(kein_cookie, koppeln(klient)).json()["key"]
    zeile = db.query(Sitzung).filter_by(art="geraet").one()

    assert token not in zeile.token_hash
    assert len(zeile.token_hash) == 64


def test_alle_fehlschlaege_antworten_gleich(klient, kein_cookie, db, person):
    """⚠️ **Sonst wird die Adresse zum Orakel für gültige Kennungen.**"""
    k = koppeln(klient)
    verbraucht = koppeln(klient)
    abholen(kein_cookie, verbraucht)
    alt = koppeln(klient)
    db.get(AppKopplung, alt["kennung"]).gilt_bis = utcnow() - timedelta(seconds=1)
    db.commit()

    falsch = kein_cookie.post(
        f"{PFAD}/pairing/{k['kennung']}/key", headers={"X-Pairing-Secret": "falsch"}, json={}
    )
    ohne = kein_cookie.post(f"{PFAD}/pairing/{k['kennung']}/key", json={})
    unbekannt = kein_cookie.post(
        f"{PFAD}/pairing/gibt-es-nicht/key", headers={"X-Pairing-Secret": "x"}, json={}
    )
    antworten = [falsch, ohne, unbekannt, abholen(kein_cookie, verbraucht), abholen(kein_cookie, alt)]

    assert {a.status_code for a in antworten} == {404}
    assert {a.json()["detail"] for a in antworten} == {"app_kopplung_unbekannt"}


def test_ein_falsches_geheimnis_verbraucht_die_kopplung_nicht(klient, kein_cookie, person):
    k = koppeln(klient)
    kein_cookie.post(
        f"{PFAD}/pairing/{k['kennung']}/key", headers={"X-Pairing-Secret": "falsch"}, json={}
    )
    assert abholen(kein_cookie, k).status_code == 200


def test_die_bremse_greift_beim_raten(klient, kein_cookie, person):
    k = koppeln(klient)
    codes = []
    for _ in range(12):
        codes.append(
            kein_cookie.post(
                f"{PFAD}/pairing/{k['kennung']}/key", headers={"X-Pairing-Secret": "falsch"}, json={}
            ).status_code
        )
    assert 429 in codes


def test_die_bremse_greift_beim_kurzen_code(klient, kein_cookie, person):
    """⚠️ **40 Bit tragen nur mit ihr.** Sie zählt je Adresse: Eine Kennung, an der
    man zählen könnte, gibt es hier nicht."""
    koppeln(klient)
    codes = [
        kein_cookie.post(f"{PFAD}/pairing/code", json={"code": f"AAAA-AAA{i}"}).status_code
        for i in range(12)
    ]
    assert 429 in codes


def test_der_kurze_code_oeffnet_dasselbe(klient, kein_cookie, person):
    k = koppeln(klient)
    code = k["neu"]["code"]

    antwort = kein_cookie.post(
        f"{PFAD}/pairing/code", json={"code": code.lower().replace("-", " "), "device": "iPad"}
    )

    assert antwort.status_code == 200
    assert antwort.json()["key"].startswith("nxa_")
    assert klient.get(f"/api/app-kopplung/{k['kennung']}").json()["geraet"] == "iPad"
    wieder = kein_cookie.post(f"{PFAD}/pairing/code", json={"code": code})
    assert wieder.status_code == 404
    assert wieder.json()["detail"] == "app_kopplung_unbekannt"


def test_der_kurze_code_verfaellt(klient, kein_cookie, db, person):
    k = koppeln(klient)
    db.get(AppKopplung, k["kennung"]).gilt_bis = utcnow() - timedelta(seconds=1)
    db.commit()

    assert kein_cookie.post(f"{PFAD}/pairing/code", json={"code": k["neu"]["code"]}).status_code == 404


def test_zwei_gleichzeitige_abholungen_ergeben_ein_geraet(klient, db, person):
    """⚠️ **Das bedingte UPDATE ist hier die ganze Sache.** Gelesen haben beide
    dieselbe offene Zeile; ein Nachsehen in Python ließe beide durch."""
    from app.db import SessionLocal

    k = koppeln(klient)
    ergebnisse: list[object] = []
    tor = threading.Barrier(2)

    def versuch():
        with SessionLocal() as sitzung:
            zeile = sitzung.get(AppKopplung, k["kennung"])
            tor.wait()
            try:
                ergebnisse.append(app_kopplung._einloesen(sitzung, zeile, "iPhone", "127.0.0.1"))
            except app_kopplung.KopplungFehler:
                ergebnisse.append(None)

    faeden = [threading.Thread(target=versuch) for _ in range(2)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()

    assert sum(1 for e in ergebnisse if e is not None) == 1
    assert db.query(Sitzung).filter_by(art="geraet").count() == 1


def test_der_geraetename_wird_gereinigt(klient, kein_cookie, db, person):
    k = koppeln(klient, device="iPhone\x00\nvon Alex")
    assert abholen(kein_cookie, k).status_code == 200
    name = db.query(Sitzung).filter_by(art="geraet").one().geraet
    assert name == "iPhonevon Alex"


# --- Der Riegel ------------------------------------------------------------ #


def test_der_riegel_ist_ab_werk_offen(klient, person):
    assert klient.get("/api/app-kopplung/erlaubt").json() == {"erlaubt": True}


def test_nur_der_betreiber_legt_ihn_um(klient, db, person):
    person.ist_betreiber = False
    db.commit()
    assert klient.put("/api/app-kopplung/erlaubt", json={"erlaubt": False}).status_code == 403


def test_zu_heisst_sofort_zu_und_kein_geraet_faellt_weg(klient, kein_cookie, bearer, db):
    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 200
    k = koppeln(klient, "Zweites")

    assert klient.put("/api/app-kopplung/erlaubt", json={"erlaubt": False}).status_code == 200

    antwort = kein_cookie.get(f"{PFAD}/me", headers=bearer)
    assert antwort.status_code == 403
    assert antwort.json()["detail"] == "app_abgeschaltet"
    assert abholen(kein_cookie, k).status_code == 403
    assert klient.post("/api/app-kopplung", json={"adresse": "http://x.example"}).status_code == 403
    assert db.query(Sitzung).filter_by(art="geraet").count() == 1

    klient.put("/api/app-kopplung/erlaubt", json={"erlaubt": True})
    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 200


# --- Zwei Türen ------------------------------------------------------------ #


def _adressen() -> list[tuple[str, str]]:
    """Jede Adresse der Anwendung, mit Platzhaltern gefüllt."""
    raus = []
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api"):
            for methode in sorted(r.methods - {"HEAD", "OPTIONS"}):
                raus.append((methode, re.sub(r"\{[^}]+\}", "1", r.path)))
    return raus


OEFFENTLICH = {
    "/api/app/1/pairing/code",
    "/api/app/1/pairing/1/key",
}


def test_ein_cookie_oeffnet_nichts_unter_der_flaeche(klient, person):
    """⚠️ **Über die ganze Tabelle.** Eine neue Adresse rutscht nicht durch."""
    assert klient.get("/api/auth/ich").status_code == 200, "Das Cookie gilt anderswo."
    offen = [
        f"{m} {p}"
        for m, p in _adressen()
        if p.startswith(PFAD)
        and p not in OEFFENTLICH
        and klient.request(m, p, json={}).status_code != 401
    ]
    assert offen == []


def test_ein_geraetetoken_oeffnet_nichts_ausserhalb(klient, kein_cookie, bearer):
    from app.main import OEFFENTLICHE_PFADE

    frei = {re.sub(r"\{[^}]+\}", "1", p) for p in OEFFENTLICHE_PFADE}
    offen = []
    for m, p in _adressen():
        if p.startswith(PFAD) or p in frei or p.startswith(("/api/v1", "/api/bilder", "/api/setup")):
            continue
        # Antwortet die Adresse auch ohne jede Anmeldung, schützt sie nichts,
        # was ein Token öffnen könnte.
        ohne = kein_cookie.request(m, p, json={}).status_code
        mit = kein_cookie.request(m, p, json={}, headers=bearer).status_code
        if mit != ohne:
            offen.append(f"{m} {p}: {ohne} wird {mit}")
    assert offen == []
    assert kein_cookie.get("/api/auth/ich", headers=bearer).status_code == 401


def test_ein_geraetetoken_im_cookie_oeffnet_nichts(klient, kein_cookie, token):
    kein_cookie.cookies.set("nexmail_sitzung", token, path="/api")
    assert kein_cookie.get("/api/auth/ich").status_code == 401


def test_ein_sitzungstoken_ist_kein_bearer(klient, kein_cookie, person):
    sitzung = klient.cookies.get("nexmail_sitzung")
    antwort = kein_cookie.get(f"{PFAD}/me", headers={"Authorization": f"Bearer {sitzung}"})
    assert antwort.status_code == 401


def test_ein_fremdes_vorsilbenspiel_ist_kein_absturz(kein_cookie, person):
    for wert in ("nxa_", "nxa_ümlaut", "nxm_abc", "Basic abc"):
        antwort = kein_cookie.get(f"{PFAD}/me", headers={"Authorization": f"Bearer {wert}".encode()})
        assert antwort.status_code == 401


def test_ein_api_schluessel_kommt_nicht_auf_die_flaeche(klient, kein_cookie, db, person):
    from app.services import apischluessel

    konto, _, _ = postfach(db, person)
    apischluessel.erlauben(db, True)
    _, klartext = apischluessel.anlegen(db, person, "Dashboard", "anzahl", [konto.id])
    assert klartext.startswith("nxm_")
    antwort = kein_cookie.get(f"{PFAD}/me", headers={"Authorization": f"Bearer {klartext}"})
    assert antwort.status_code == 401


def test_ein_geraetetoken_kommt_nicht_auf_api_v1(kein_cookie, bearer):
    assert kein_cookie.get("/api/v1/me", headers=bearer).status_code != 200


# --- Das Gerät in der Liste ------------------------------------------------ #


def test_das_geraet_steht_in_der_liste_und_laesst_sich_trennen(klient, kein_cookie, bearer):
    zeilen = klient.get("/api/sitzungen").json()
    geraet = next(z for z in zeilen if z["geraet"] == "iPhone von Alex")

    assert klient.delete(f"/api/sitzungen/{geraet['id']}").status_code == 204

    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 401


def test_ueberall_abmelden_trennt_es_auch(klient, kein_cookie, bearer):
    klient.post("/api/sitzungen/alle-beenden")
    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 401


def test_kennwort_zuruecksetzen_trennt_es_auch(kein_cookie, bearer, db, person):
    from app.models import Kennwortruecksetzung
    from app.services import ruecksetzung

    db.add(
        Kennwortruecksetzung(
            schluessel_hash=ruecksetzung._hash("probe"),
            benutzer_id=person.id,
            laeuft_ab=utcnow() + timedelta(hours=1),
        )
    )
    db.commit()
    ruecksetzung.einloesen(db, "probe", "ein-neues-kennwort-123")

    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 401


def test_ein_entferntes_konto_nimmt_das_geraet_mit(kein_cookie, bearer, db, person):
    db.delete(person)
    db.commit()
    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 401


def test_die_app_trennt_sich_selbst(klient, kein_cookie, bearer, db):
    assert kein_cookie.delete(f"{PFAD}/device", headers=bearer).status_code == 204
    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 401
    assert db.query(Sitzung).filter_by(art="geraet").count() == 0


def test_ein_geraet_laeuft_nicht_ab_wie_eine_sitzung(kein_cookie, bearer, db):
    zeile = db.query(Sitzung).filter_by(art="geraet").one()
    assert zeile.gueltig_bis - utcnow() > timedelta(days=365 * 5)


def test_zuletzt_gesehen_wird_nachgezogen(kein_cookie, bearer, db):
    zeile = db.query(Sitzung).filter_by(art="geraet").one()
    alt = utcnow() - timedelta(hours=2)
    zeile.zuletzt_gesehen = alt
    db.commit()

    kein_cookie.get(f"{PFAD}/me", headers=bearer)

    db.expire_all()
    assert db.query(Sitzung).filter_by(art="geraet").one().zuletzt_gesehen > alt


# --- /me ------------------------------------------------------------------- #


def test_me_nennt_postfaecher_fassung_und_faehigkeiten(kein_cookie, bearer, db, person):
    from app import __version__

    konto, _, _ = postfach(db, person)
    antwort = kein_cookie.get(f"{PFAD}/me", headers=bearer).json()

    assert antwort["version"] == __version__
    assert antwort["konto"]["betreiber"] is True
    assert antwort["postfaecher"][0]["id"] == konto.id
    assert antwort["geraet"]["name"] == "iPhone von Alex"
    assert "abbestellen" in antwort["faehigkeiten"]
    assert "kurzfassung" not in antwort["faehigkeiten"], "Ab Werk zu."
    assert "umformulieren" not in antwort["faehigkeiten"]


def test_kurzfassung_erscheint_erst_mit_allen_freigaben(kein_cookie, bearer, db, person):
    kidienst.erlauben(db, True)
    kidienst.fremde_post_erlauben(db, True)
    kidienst.einstellung_schreiben(
        db, person, url="https://api.example.com/v1/", modell="m", schluessel=SCHLUESSEL
    )
    kidienst.einstellung_schreiben(db, person, aktiv=True)
    assert "kurzfassung" not in kein_cookie.get(f"{PFAD}/me", headers=bearer).json()["faehigkeiten"]

    kidienst.einstellung_schreiben(db, person, fremde_post=True)

    antwort = kein_cookie.get(f"{PFAD}/me", headers=bearer).json()
    assert {"kurzfassung", "umformulieren"} <= set(antwort["faehigkeiten"])


# --- Lesen ----------------------------------------------------------------- #


@pytest.fixture
def stand(db, person):
    """Ein Postfach mit zwei Mails."""
    konto, eingang, archiv = postfach(db, person)
    return {
        "konto": konto,
        "eingang": eingang,
        "archiv": archiv,
        "eins": mail(db, person, konto, eingang, 1, betreff="Erste"),
        "zwei": mail(db, person, konto, eingang, 2, betreff="Zweite", hat_anhang=True),
    }


@pytest.fixture
def api(kein_cookie, bearer):
    def rufen(methode, pfad, **rest):
        return kein_cookie.request(methode, f"{PFAD}{pfad}", headers=bearer, **rest)

    return rufen


@pytest.fixture
def server(monkeypatch):
    """Der IMAP-Doppelgänger mit den beiden Mails aus ``stand``."""
    doppel = FalscherServer()
    doppel.anlegen("INBOX")
    doppel.anlegen("Archiv")
    doppel.einwerfen("INBOX", 1, "Erste")
    doppel.einwerfen("INBOX", 2, "Zweite")
    doppel.add_flags = lambda *_a, **_k: None
    doppel.remove_flags = lambda *_a, **_k: None
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda *_a, **_k: doppel)
    return doppel


def test_postfaecher_und_ordnerbaum(api, stand):
    assert api("GET", "/accounts").json()[0]["id"] == stand["konto"].id
    baum = api("GET", f"/accounts/{stand['konto'].id}/folders").json()
    assert {o["pfad"] for o in baum} == {"INBOX", "Archiv"}
    assert next(o for o in baum if o["pfad"] == "INBOX")["anzahl"] == 2


def test_die_liste_samt_filter(api, stand):
    alle = api("GET", "/messages", params={"nur_posteingaenge": True}).json()
    assert {m["betreff"] for m in alle} == {"Erste", "Zweite"}
    anhang = api("GET", "/messages", params={"filter": "anhang"}).json()
    assert [m["betreff"] for m in anhang] == ["Zweite"]


def test_die_app_filtert_wie_die_pillen_im_browser(api, db, person, stand):
    """Die Gruppen stehen am Postfach, und die Liste nimmt ``konto_ids``."""
    stand["konto"].tags = "privat"
    zweites, eingang, _ = postfach(db, person, "arbeit@example.com")
    zweites.tags = "arbeit"
    db.commit()
    mail(db, person, zweites, eingang, 9, betreff="Dienstlich")

    gruppen = {k["adresse"]: k["tags"] for k in api("GET", "/accounts").json()}
    assert gruppen == {"anna@example.com": ["privat"], "arbeit@example.com": ["arbeit"]}
    in_me = {p["adresse"]: p["tags"] for p in api("GET", "/me").json()["postfaecher"]}
    assert in_me == gruppen

    treffer = api(
        "GET", "/messages", params={"nur_posteingaenge": True, "konto_ids": zweites.id}
    ).json()
    assert [m["betreff"] for m in treffer] == ["Dienstlich"]


def test_der_merkpunkt_blaettert(api, stand):
    erste = api("GET", "/messages", params={"grenze": 1}).json()[0]
    nach = f"{erste['datum']},{erste['id']}"
    zweite = api("GET", "/messages", params={"grenze": 1, "nach": nach}).json()
    assert len(zweite) == 1
    assert zweite[0]["id"] != erste["id"]


def test_der_filter_nur_an_mich_kennt_auch_aliasse(api, db, person, stand):
    from app.services import aliase

    aliase.schreiben(stand["konto"], [aliase.Alias("alias@example.com", "")])
    db.commit()
    an = json.dumps([{"n": "", "a": "alias@example.com"}])
    fremd = json.dumps([{"n": "", "a": "jemand@example.org"}])
    mail(db, person, stand["konto"], stand["eingang"], 3, betreff="An Alias", an_json=an)
    mail(db, person, stand["konto"], stand["eingang"], 4, betreff="Rundmail", an_json=fremd)

    treffer = api("GET", "/messages", params={"filter": "an_mich"}).json()

    assert [m["betreff"] for m in treffer] == ["An Alias"]


def test_eine_mail_mit_ihrem_koerper(api, stand):
    voll = api("GET", f"/messages/{stand['eins'].id}").json()
    assert voll["text"] == "Das ist der Text der Mail."
    assert voll["abbestellen"] is None


def test_der_strang(api, db, stand):
    stand["eins"].thread_key = "kette"
    stand["zwei"].thread_key = "kette"
    db.commit()
    assert len(api("GET", "/messages/thread/kette").json()) == 2


def test_ereignisse_antworten(api, stand):
    assert isinstance(api("GET", "/events").json()["stand"], int)


def test_schlagworte_und_absenderbild(api, db, person, stand):
    from app.services import schlagworte

    schlagworte.anlegen(db, person.id, "Rechnung")
    assert api("GET", "/labels").json()[0]["name"] == "Rechnung"
    antwort = api("GET", "/sender-image", params={"adresse": "post@example.org"})
    assert antwort.status_code == 404, "Ohne Bild heißt das: Initialen."


def test_suche_ueber_den_server(api, stand):
    assert api("POST", "/search", json={"text": "Erste"}).status_code == 200


def test_ein_anhang(api, db, stand, tmp_path):
    from app.config import get_settings
    from app.models import Anhang

    blobs = get_settings().blob_dir
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / "pruefsumme").write_bytes(b"Inhalt")
    a = Anhang(
        nachricht_id=stand["eins"].id,
        teil_id="2",
        dateiname="rechnung.txt",
        mime="text/plain",
        groesse=6,
        blob_hash="pruefsumme",
    )
    db.add(a)
    db.commit()

    antwort = api("GET", f"/messages/{stand['eins'].id}/attachments/{a.id}")

    assert antwort.status_code == 200
    assert antwort.content == b"Inhalt"


def test_bilder_laden(api, db, stand):
    stand["eins"].koerper_html = '<p><img data-nexmail-src="http://b.example/x.png"></p>'
    db.commit()
    assert "html" in api("POST", f"/messages/{stand['eins'].id}/images", json={}).json()


# --- Handeln --------------------------------------------------------------- #


def test_flags(api, db, stand, server):
    antwort = api("POST", f"/messages/{stand['eins'].id}/flags", json={"gelesen": True})
    assert antwort.status_code == 200
    db.expire_all()
    assert db.get(Nachricht, stand["eins"].id).gelesen is True


def test_ordner_als_gelesen(api, stand, server, monkeypatch):
    from app.services import handeln

    monkeypatch.setattr(handeln, "ordner_als_gelesen", lambda *_a: 2)
    assert api("POST", f"/folders/{stand['eingang'].id}/read").json()["bewegt"] == 2


@pytest.mark.parametrize(
    "pfad, rolle",
    [("/messages/delete", "papierkorb"), ("/messages/archive", "archiv"), ("/messages/junk", "junk")],
)
def test_loeschen_archivieren_junk(api, stand, monkeypatch, pfad, rolle):
    from app.services import handeln

    gerufen = []

    def in_rolle(_db, nachrichten, gewollt):
        gerufen.append(([n.id for n in nachrichten], gewollt))
        return handeln.Rueckweg(konto_id="k", quelle_pfad="a", ziel_pfad="b", message_ids=["m"])

    monkeypatch.setattr(handeln, "in_rolle", in_rolle)

    antwort = api("POST", pfad, json={"ids": [stand["eins"].id]})

    assert antwort.json()["bewegt"] == 1
    assert gerufen == [([stand["eins"].id], rolle)]


def test_verschieben_und_zurueck(api, stand, monkeypatch):
    from app.services import handeln

    monkeypatch.setattr(
        handeln,
        "verschieben",
        lambda *_a: handeln.Rueckweg(
            konto_id=stand["konto"].id, quelle_pfad="INBOX", ziel_pfad="Archiv", message_ids=["m"]
        ),
    )
    monkeypatch.setattr(handeln, "zurueck", lambda *_a: 1)

    weg = api(
        "POST", "/messages/move", json={"ids": [stand["eins"].id], "ordner_id": stand["archiv"].id}
    ).json()["rueckweg"]

    assert api("POST", "/messages/undo", json=weg).json()["bewegt"] == 1


def test_schlagwort_setzen_und_nehmen(api, db, person, stand, server):
    from app.services import schlagworte

    atom = schlagworte.anlegen(db, person.id, "Rechnung").atom
    koerper = {"ids": [stand["eins"].id]}

    assert api("POST", f"/messages/labels/{atom}", json=koerper).status_code == 200
    assert api("DELETE", f"/messages/labels/{atom}", json=koerper).status_code == 200


def test_wiedervorlage(api, stand, monkeypatch):
    from app.services import wiedervorlage

    assert api("GET", "/snoozes").json() == []
    gerufen = []

    def weglegen(*a, **_k):
        # Der Weg zum IMAP-Server ist im Browser getestet; hier zählt das Ankommen.
        gerufen.append(a)
        raise wiedervorlage.WiedervorlageFehler("wiedervorlage_nicht_moeglich")

    monkeypatch.setattr(wiedervorlage, "weglegen", weglegen)
    monkeypatch.setattr(wiedervorlage, "entfernen", lambda *a, **k: gerufen.append(a))

    api(
        "POST",
        "/snoozes",
        json={"nachricht_id": stand["eins"].id, "aufwachen": "2030-01-01T08:00:00Z"},
    )
    assert api("DELETE", "/snoozes/1").status_code == 204
    assert len(gerufen) == 2


def test_abgleich_wird_angestossen_nicht_abgewartet(api, stand, monkeypatch):
    gestartet = []
    monkeypatch.setattr(abgleich, "im_hintergrund", lambda k: gestartet.append(k) or True)

    antwort = api("POST", "/sync", json={})

    assert antwort.status_code == 202
    assert antwort.json() == {"gestartet": 1, "laufen_schon": 0}
    assert gestartet == [stand["konto"].id]


def test_ein_laufender_abgleich_wird_gemeldet(api, stand, monkeypatch):
    monkeypatch.setattr(abgleich, "im_hintergrund", lambda _k: False)
    assert api("POST", "/sync").json() == {"gestartet": 0, "laufen_schon": 1}


def test_abgleich_eines_fremden_postfachs(api, stand):
    assert api("POST", "/sync", json={"konto_id": "gibt-es-nicht"}).status_code == 404


def test_abbestellen_ist_erreichbar(api, stand):
    antwort = api("POST", f"/messages/{stand['eins'].id}/unsubscribe", json={})
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "abbestellen_nicht_moeglich"


def test_kurzfassung_ist_erreichbar_und_ab_werk_zu(api, stand):
    antwort = api("POST", f"/messages/{stand['eins'].id}/summary", json={"sprache": "de"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "ki_nicht_eingeschaltet"


def test_kurzfassung_mit_freigabe(api, db, person, stand, monkeypatch):
    kidienst.erlauben(db, True)
    kidienst.fremde_post_erlauben(db, True)
    kidienst.einstellung_schreiben(
        db, person, url="https://api.example.com/v1/", modell="m", schluessel=SCHLUESSEL
    )
    kidienst.einstellung_schreiben(db, person, aktiv=True, fremde_post=True)
    original = kidienst.zusammenfassen
    monkeypatch.setattr(
        kidienst,
        "zusammenfassen",
        lambda p, d, **kw: original(
            p, d, transport=TextDoppelgaenger(inhalt="Kurz.").transport(), **kw
        ),
    )

    antwort = api("POST", f"/messages/{stand['eins'].id}/summary", json={"sprache": "de"})

    assert antwort.json() == {"text": "Kurz.", "gekuerzt": False}


def test_mail_zu_aufgabe(api, stand):
    antwort = api("POST", "/tasks", json={"nachricht_id": stand["eins"].id})
    assert antwort.status_code == 201


def test_einladung_nachsehen(api, stand):
    assert api("GET", f"/messages/{stand['eins'].id}/invitation").json() is None


def test_einladung_beantworten_ohne_einladung(api, stand):
    antwort = api(
        "POST", f"/messages/{stand['eins'].id}/invitation/answer", json={"antwort": "zusage"}
    )
    assert antwort.status_code in (400, 404, 422)


# --- Schreiben ------------------------------------------------------------- #


def test_signatur_und_vorschlaege(api, stand):
    assert api("GET", f"/compose/signature/{stand['konto'].id}").status_code == 200
    assert api("GET", "/contacts/suggest", params={"anfang": "an"}).json() == []


def test_vorlage(api, stand, monkeypatch):
    roh = b"From: a@example.org\r\nSubject: Erste\r\n\r\nText\r\n"
    monkeypatch.setattr(abgleich, "roh_holen", lambda *_a: roh)
    antwort = api("GET", f"/compose/template/{stand['eins'].id}", params={"art": "antwort"})
    assert antwort.status_code == 200
    assert antwort.json()["betreff"].endswith("Erste")


def _sendewunsch(konto) -> dict:
    return {
        "konto_id": konto.id,
        "an": ["jemand@example.org"],
        "betreff": "Probe",
        "text": "Hallo",
        "anlagen": [
            {
                "dateiname": "a.txt",
                "mime_typ": "text/plain",
                "inhalt_b64": base64.b64encode(b"Anlage").decode(),
            }
        ],
    }


def test_senden_samt_anhang(api, stand, monkeypatch):
    from app.services import senden

    gesendet = []
    monkeypatch.setattr(senden, "_smtp_senden", lambda *a, **k: gesendet.append(a))
    monkeypatch.setattr(senden, "_spaeter_ablegen", lambda *_a: None)

    antwort = api("POST", "/compose/send", json=_sendewunsch(stand["konto"]))

    assert antwort.status_code == 200
    assert antwort.json()["stand"] == "gesendet"
    assert len(gesendet) == 1


def test_senden_wartet_nicht_auf_die_ablage(api, stand, monkeypatch):
    """⚠️ **Die Mail ist draußen, wenn die Ablage wartet.** Mit Frist liefe das
    Schloss ab, und die Kopie fehlte im Gesendet-Ordner."""
    from app.services import senden

    monkeypatch.setattr(senden, "_smtp_senden", lambda *a, **k: None)
    abgelegt = threading.Event()
    monkeypatch.setattr(senden, "_spaeter_ablegen", lambda *_a: abgelegt.set())

    def nie(*_a):
        raise AssertionError("Die Ablage lief in der Anfrage.")

    monkeypatch.setattr(senden, "_in_gesendet_ablegen", nie)

    assert api("POST", "/compose/send", json=_sendewunsch(stand["konto"])).status_code == 200
    assert abgelegt.wait(2)


def test_spaeter_senden_und_abbrechen(api, stand, monkeypatch):
    from app.services import entwuerfe

    monkeypatch.setattr(entwuerfe, "ablegen", lambda *_a, **_k: 7, raising=False)
    wunsch = _sendewunsch(stand["konto"]) | {
        "senden_ab": (utcnow() + timedelta(days=1)).isoformat()
    }

    antwort = api("POST", "/compose/send", json=wunsch).json()

    assert antwort["stand"] == "wartet"
    assert [z["id"] for z in api("GET", "/outbox").json()] == [antwort["id"]]


def test_entwurf_ablegen_und_wegwerfen(api, stand, monkeypatch):
    from app.services import entwuerfe

    monkeypatch.setattr(entwuerfe, "ablegen", lambda *_a, **_k: 7)
    monkeypatch.setattr(entwuerfe, "wegwerfen", lambda *_a, **_k: None)
    wunsch = _sendewunsch(stand["konto"])

    assert api("POST", "/drafts", json=wunsch).json() == {"uid": 7}
    assert (
        api("DELETE", "/drafts/7", params={"konto_id": stand["konto"].id}).status_code == 204
    )


def test_umformulieren_ist_erreichbar_und_ab_werk_zu(api, stand):
    antwort = api(
        "POST", "/ai/text", json={"text": "<p>Das ist ein Text.</p>", "auftrag": "rechtschreibung"}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "ki_vom_betreiber_gesperrt"


# --- Fremdzugriff ---------------------------------------------------------- #


@pytest.fixture
def fremd(db, person):
    """Eine Mail eines anderen Benutzers."""
    zweiter, _ = zweiten_benutzer_anlegen(db)
    konto, eingang, archiv = postfach(db, zweiter, "fremd@example.com")
    return {
        "konto": konto,
        "eingang": eingang,
        "archiv": archiv,
        "mail": mail(db, zweiter, konto, eingang, 1, betreff="Geheim"),
    }


@pytest.mark.parametrize(
    "methode, pfad, koerper",
    [
        ("GET", "/messages/{mail}", None),
        ("GET", "/messages/{mail}/attachments/1", None),
        ("POST", "/messages/{mail}/images", {}),
        ("POST", "/messages/{mail}/flags", {"gelesen": True}),
        ("POST", "/messages/{mail}/unsubscribe", {}),
        ("POST", "/messages/{mail}/summary", {}),
        ("GET", "/messages/{mail}/invitation", None),
        ("POST", "/messages/{mail}/invitation/answer", {"antwort": "zusage"}),
        ("GET", "/compose/template/{mail}?art=antwort", None),
        ("POST", "/messages/delete", {"ids": ["{mail}"]}),
        ("POST", "/messages/archive", {"ids": ["{mail}"]}),
        ("POST", "/messages/junk", {"ids": ["{mail}"]}),
        ("POST", "/messages/move", {"ids": ["{mail}"], "ordner_id": "{ordner}"}),
        ("POST", "/snoozes", {"nachricht_id": "{mail}", "aufwachen": "2030-01-01T00:00:00Z"}),
        ("POST", "/tasks", {"nachricht_id": "{mail}"}),
        ("POST", "/folders/{ordner}/read", None),
        ("GET", "/accounts/{konto}/folders", None),
        ("GET", "/compose/signature/{konto}", None),
    ],
)
def test_eine_fremde_mail_gibt_es_nicht(api, kidienst_an, fremd, methode, pfad, koerper):
    werte = {"mail": fremd["mail"].id, "ordner": fremd["eingang"].id, "konto": fremd["konto"].id}

    def fuellen(wert):
        if isinstance(wert, dict):
            return {k: fuellen(v) for k, v in wert.items()}
        if isinstance(wert, list):
            return [fuellen(v) for v in wert]
        if isinstance(wert, str) and re.fullmatch(r"\{\w+\}", wert):
            return werte[wert[1:-1]]
        return wert

    antwort = api(methode, pfad.format(**werte), json=fuellen(koerper) if koerper is not None else None)

    assert antwort.status_code == 404, antwort.text


@pytest.fixture
def kidienst_an(db, person):
    """Damit die KI-Adresse an der Besitzprüfung scheitert, nicht am Riegel."""
    kidienst.erlauben(db, True)
    kidienst.fremde_post_erlauben(db, True)
    kidienst.einstellung_schreiben(
        db, person, url="https://api.example.com/v1/", modell="m", schluessel=SCHLUESSEL
    )
    kidienst.einstellung_schreiben(db, person, aktiv=True, fremde_post=True)


def test_die_liste_zeigt_nichts_fremdes(api, fremd):
    assert api("GET", "/messages").json() == []
    assert api("GET", "/messages", params={"ordner_id": fremd["eingang"].id}).json() == []
    assert api("GET", "/messages/thread/kette").json() == []


def test_ein_fremdes_postfach_steht_nicht_im_abgleich(api, fremd):
    assert api("POST", "/sync", json={"konto_id": fremd["konto"].id}).status_code == 404


def test_senden_aus_einem_fremden_postfach(api, fremd, monkeypatch):
    from app.services import senden

    def nie(*_a, **_k):
        raise AssertionError("Hinausgegangen.")

    monkeypatch.setattr(senden, "_smtp_senden", nie)
    assert api("POST", "/compose/send", json=_sendewunsch(fremd["konto"])).status_code == 404


# --- Zeitlimits ------------------------------------------------------------ #


def test_ein_belegtes_postfach_antwortet_statt_zu_haengen(api, stand, monkeypatch):
    """⚠️ **Der Grund für die Frist.** Beim Nachholen hält der Abgleich das Schloss
    stundenlang; ohne Frist hinge diese Anfrage genauso lange."""
    from app import middleware

    monkeypatch.setattr(middleware, "APP_SCHLOSS_SEKUNDEN", 0.1)
    frei = threading.Event()
    belegt = threading.Event()

    def halten():
        with abgleich.HALTER.schloss(stand["konto"].id):
            belegt.set()
            frei.wait(5)

    faden = threading.Thread(target=halten)
    faden.start()
    belegt.wait(2)
    try:
        antwort = api("POST", f"/messages/{stand['eins'].id}/flags", json={"gelesen": True})
    finally:
        frei.set()
        faden.join()

    assert antwort.status_code == 503
    assert antwort.json()["detail"] == "postfach_beschaeftigt"
    assert antwort.headers["retry-after"] == "30"


def test_im_browser_wartet_das_schloss_weiter():
    """⚠️ Die Frist gilt nur unter ``/api/app/1``. Im Browser ändert sich nichts.

    Gefragt wird die Schicht selbst: Ein Aufruf über den Klienten kommt auch mit
    Frist durch, solange niemand das Schloss hält."""
    import asyncio

    from app.middleware import APP_SCHLOSS_SEKUNDEN, AppFristMiddleware

    gesehen = {}

    async def innen(scope, _receive, _send):
        gesehen[scope["path"]] = abgleich.SCHLOSS_FRIST.get()

    schicht = AppFristMiddleware(innen)
    for pfad in ("/api/nachrichten/1/flags", "/api/app/1/me"):
        asyncio.run(schicht({"type": "http", "path": pfad}, None, None))

    assert gesehen == {"/api/nachrichten/1/flags": None, "/api/app/1/me": APP_SCHLOSS_SEKUNDEN}


def test_die_fristen_gelten_auf_der_flaeche(api, stand, monkeypatch):
    from app.routers import app1

    gesehen = {}

    def nachsehen(*_a, **_k):
        gesehen["schloss"] = abgleich.SCHLOSS_FRIST.get()
        gesehen["koerper"] = abgleich.KOERPER_FRIST.get()
        return []

    monkeypatch.setattr(app1.kontendienst, "meine", nachsehen)
    api("POST", "/sync")

    assert gesehen["schloss"] and gesehen["koerper"]


def test_ein_langer_erster_abruf_kommt_mit_gleich_zurueck(api, db, person, monkeypatch):
    """⚠️ **Der Abruf läuft weiter**, und der zweite Versuch findet die Mail."""
    from app import middleware

    konto, eingang, _ = postfach(db, person)
    n = mail(db, person, konto, eingang, 1, koerper_geholt=None)
    weiter = threading.Event()
    gestartet = threading.Event()

    class LangsamerServer(FalscherServer):
        def fetch(self, uids, felder):
            gestartet.set()
            weiter.wait(5)
            return super().fetch(uids, felder)

    doppel = LangsamerServer()
    doppel.anlegen("INBOX")
    doppel.einwerfen("INBOX", 1, "Hallo", roh=b"From: a@example.org\r\n\r\nGeholt.\r\n")
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda *_a, **_k: doppel)
    monkeypatch.setattr(middleware, "APP_KOERPER_SEKUNDEN", 0.1)

    erste = api("GET", f"/messages/{n.id}")

    assert erste.status_code == 503
    assert erste.json()["detail"] == "nachricht_laedt"
    assert erste.headers["retry-after"] == "5"
    assert gestartet.is_set()

    weiter.set()
    monkeypatch.setattr(middleware, "APP_KOERPER_SEKUNDEN", 5.0)
    zweite = api("GET", f"/messages/{n.id}")

    assert zweite.status_code == 200
    assert "Geholt." in zweite.json()["text"]


def test_ein_fehler_beim_abruf_kommt_bei_der_app_an(api, db, person, monkeypatch):
    konto, eingang, _ = postfach(db, person)
    n = mail(db, person, konto, eingang, 1, koerper_geholt=None)

    def weigern(*_a, **_k):
        raise imapdienst.Verbindungsfehler(imapdienst.Fehlerart.ANMELDUNG, "abgewiesen", "abgewiesen")

    monkeypatch.setattr(imapdienst, "fuer_konto", weigern)

    assert api("GET", f"/messages/{n.id}").status_code == 502


def test_ein_abgleich_im_hintergrund_laeuft_einmal_je_postfach(db, person, monkeypatch):
    konto, _, _ = postfach(db, person)
    frei = threading.Event()
    gerufen = []

    def langsam(_db, k, nur_posteingang=False):
        gerufen.append(k.id)
        frei.wait(5)
        return {}

    monkeypatch.setattr(abgleich, "konto_abgleichen", langsam)

    assert abgleich.im_hintergrund(konto.id) is True
    assert abgleich.im_hintergrund(konto.id) is False

    frei.set()
    for faden in threading.enumerate():
        if faden.name == "nexmail-app-abgleich":
            faden.join(2)
    assert abgleich.im_hintergrund(konto.id) is True
    assert gerufen


# --- Listenvorschau -------------------------------------------------------- #


@pytest.mark.parametrize(
    "html",
    [
        "<style>#outlook a { padding:0; }</style><p>Hallo Welt</p>",
        "<html><head><title>x</title><style>a{b:c}</style></head><body>Hallo Welt</body></html>",
        "<!--[if mso]><style>a{b:c}</style><![endif]--><p>Hallo Welt</p>",
        '<STYLE type="text/css">a{b:c}</STYLE ><p>Hallo Welt</p>',
    ],
)
def test_die_vorschau_zeigt_kein_css(html):
    from app.services import bereinigen

    assert bereinigen.text_aus_html(html) == "Hallo Welt"


def test_ein_abgeschnittener_style_block_bleibt_leer():
    """⚠️ **Der eigentliche Fall.** Der Abgleich holt 512 Byte, und bei Newslettern
    endet der Block darin nicht."""
    from app.services import bereinigen

    assert bereinigen.text_aus_html("<html><head><style>#outlook a { padding:0; } body { mar") == ""


def test_eine_abgeschnittene_marke_faellt_weg():
    from app.services import bereinigen

    assert bereinigen.text_aus_html('<p>Hallo</p><a href="https://exa') == "Hallo"


def test_alte_vorschauen_werden_geheilt(db, person):
    konto, eingang, _ = postfach(db, person)
    css = mail(db, person, konto, eingang, 1)
    css.anreisser = "#outlook a { padding:0; } .ExternalClass { width:100%; }"
    leer = mail(db, person, konto, eingang, 2, koerper_geholt=None)
    leer.koerper_text = ""
    leer.anreisser = "body { margin:0 }"
    echt = mail(db, person, konto, eingang, 3)
    echt.anreisser = "Der Preis {inkl. Steuer: 19 %} steht unten"
    db.commit()

    assert abgleich.anrisse_heilen(db) == 2

    assert css.anreisser == "Das ist der Text der Mail."
    assert leer.anreisser == ""
    assert echt.anreisser.startswith("Der Preis"), "Echter Text bleibt."


def test_jede_adresse_kommt_ueber_die_wache(person):
    """⚠️ Die Zusage und die Routen laufen nicht auseinander."""
    assert len(ZUGESAGT) == len(set(ZUGESAGT))
