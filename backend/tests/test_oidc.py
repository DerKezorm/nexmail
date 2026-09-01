"""Anmelden über einen fremden Anbieter.

⚠️ **Jeder Test hier hat in nexview einmal Geld gekostet.** Die Fallstricke
stehen im Kopf von ``services/oidc.py``; hier werden sie festgenagelt, damit
sie beim naechsten Umbau nicht wieder aufgehen.
"""

from __future__ import annotations

import pytest

from app.models import Benutzer, OidcAnbieter, OidcVerknuepfung
from app.services import anmeldebremse, oidc
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from oidc_attrappe import CLIENT_ID, ISSUER, Attrappe, einspannen

PASSWORT = "sehr-geheim-123"


@pytest.fixture(autouse=True)
def freie_bremse():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def anbieter_da(klient, monkeypatch):
    """Ein eingerichteter Anbieter samt oeffentlicher Adresse."""
    from app.db import SessionLocal, einstellung_schreiben

    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")

    antwort = klient.post(
        "/api/oidc/anbieter",
        json={
            "kuerzel": "keycloak",
            "anzeigename": "Keycloak",
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": "geheim",
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _lauf(klient, attrappe, monkeypatch, *, kuerzel="keycloak"):
    """Hin- und Rueckweg — wie ein Browser ihn geht."""
    einspannen(monkeypatch, attrappe)

    hin = klient.get(f"/api/oidc/{kuerzel}/start", follow_redirects=False)
    assert hin.status_code == 303, hin.text

    from urllib.parse import parse_qs, urlparse

    # ⚠️ Scheitert schon der Hinweg, ist **das** das Ergebnis — sonst
    # scheitert der Test an einem ``KeyError: nonce`` statt an der Sache.
    if "oidc_fehler" in hin.headers["location"]:
        return hin

    frage = parse_qs(urlparse(hin.headers["location"]).query)
    attrappe._nonce = frage["nonce"][0]
    zustand = frage["state"][0]

    return klient.get(
        f"/api/oidc/{kuerzel}/zurueck?code=abc&state={zustand}", follow_redirects=False
    )


# --- Hilfen --------------------------------------------------------------- #


def _einladung(db, adresse: str = "anna@example.com", benutzername: str = "anna"):
    """Eine offene Einladung anlegen - ohne Mailversand."""
    from app.services import einladung as einladungsdienst

    gebot, _ = einladungsdienst.aussprechen(
        db, benutzername=benutzername, adresse=adresse, anzeigename="Anna Beispiel"
    )
    return gebot


# --- Der gute Weg --------------------------------------------------------- #


def test_der_hinweg_fuehrt_zum_anbieter(klient, anbieter_da, monkeypatch):
    einspannen(monkeypatch, Attrappe())
    antwort = klient.get("/api/oidc/keycloak/start", follow_redirects=False)

    assert antwort.status_code == 303
    ziel = antwort.headers["location"]
    assert ziel.startswith(f"{ISSUER}/auth")
    # PKCE gehoert dazu - ohne den Praegewert nuetzt ein abgefangener Code.
    assert "code_challenge=" in ziel and "code_challenge_method=S256" in ziel
    assert "nonce=" in ziel and "state=" in ziel
    assert "scope=openid" in ziel
    kekse = antwort.headers.get_list("set-cookie")
    assert any("nexmail_oidc=" in k and "HttpOnly" in k and "SameSite=lax" in k for k in kekse)


def test_angemeldet_heisst_verknuepfen(klient, anbieter_da, monkeypatch, db):
    """Der Hauptweg fuer bestehende Konten (01.09.2026).

    Wer angemeldet ist und den Anbieter aufruft, verknuepft - einen Abgleich
    ueber Adressen gibt es nicht mehr, und genau deshalb braucht es diesen Weg.
    """
    antwort = _lauf(klient, Attrappe(), monkeypatch)

    assert antwort.headers["location"].endswith("oidc=verknuepft"), antwort.headers["location"]
    assert db.query(OidcVerknuepfung).count() == 1
    assert db.query(Benutzer).count() == 1
    assert klient.get("/api/oidc/meine").json()[0]["anzeigename"] == "Keycloak"


def test_ein_zweiter_lauf_geht_ueber_die_verknuepfung(klient, anbieter_da, monkeypatch, db):
    """Einmal verknuepft, danach meldet dieselbe Identitaet an."""
    _lauf(klient, Attrappe(), monkeypatch)
    klient.cookies.clear()

    # Beim zweiten Mal meldet der Anbieter eine andere Adresse - die
    # Verknuepfung traegt trotzdem, sie haengt an (issuer, subject).
    antwort = _lauf(klient, Attrappe(email="andere@example.com"), monkeypatch)

    assert "oidc_fehler" not in antwort.headers["location"]
    assert klient.get("/api/auth/ich").json()["benutzername"] == "betreiber"
    assert db.query(OidcVerknuepfung).count() == 1


def test_eine_offene_einladung_wird_eingeloest(klient, anbieter_da, monkeypatch, db):
    """Der zweite und einzige andere Weg herein.

    Eine Einladung IST die Erlaubnis, und der Betreiber hat sie bewusst an
    genau diese Adresse ausgesprochen.
    """
    _einladung(db)
    klient.cookies.clear()

    antwort = _lauf(klient, Attrappe(email="anna@example.com"), monkeypatch)

    assert "oidc_fehler" not in antwort.headers["location"], antwort.headers["location"]
    neuer = db.query(Benutzer).filter(Benutzer.benutzername == "anna").one()
    # Kein zufaelliges Passwort - das waere ein Zugang, den niemand kennt.
    assert neuer.passwort_hash == ""
    assert neuer.ist_betreiber is False


def test_die_adresse_darf_auch_nur_aus_userinfo_kommen(klient, anbieter_da, monkeypatch, db):
    """Authelia und Zitadel.

    Authelia legt ``email`` gar nicht in den Ausweis; Zitadel liefert sie dort
    nur bei einem anderen Ablauf. Ohne die Nachfrage faende keine Einladung je
    ihren Menschen.
    """
    _einladung(db)
    klient.cookies.clear()
    attrappe = Attrappe(
        email=None,
        email_bestaetigt=None,
        userinfo={"email": "anna@example.com", "email_verified": True},
    )
    antwort = _lauf(klient, attrappe, monkeypatch)

    assert "oidc_fehler" not in antwort.headers["location"], antwort.headers["location"]
    assert db.query(Benutzer).filter(Benutzer.benutzername == "anna").count() == 1


# --- Was NICHT durchkommen darf ------------------------------------------- #


def test_eine_adresse_oeffnet_kein_bestehendes_konto(klient, anbieter_da, monkeypatch, db):
    """Die Bruecke ist weg (01.09.2026), und das ist der Gewinn.

    Vorher galt "bestaetigte Adresse trifft vorhandenes Konto". Das war die
    Stelle, an der ein Anbieter mit einer erschwindelten Adresse ein fremdes
    Konto haette oeffnen koennen - und die ganze email_verified-Pruefung
    existierte nur, um sie abzusichern. Ohne Bruecke faellt der ganze
    Risikobereich weg.
    """
    person = db.query(Benutzer).one()
    person.benutzername = "anna@example.com"
    db.commit()

    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(email="anna@example.com"), monkeypatch)

    assert "oidc_kein_konto" in antwort.headers["location"]
    assert klient.get("/api/auth/ich").status_code == 401
    assert db.query(OidcVerknuepfung).count() == 0


def test_eine_unbestaetigte_adresse_loest_keine_einladung_ein(klient, anbieter_da, monkeypatch, db):
    """Sonst genuegte ein Anbieter, bei dem man sich eine beliebige Adresse
    eintragen darf, um eine fremde Einladung einzuloesen."""
    _einladung(db)
    klient.cookies.clear()

    antwort = _lauf(klient, Attrappe(email_bestaetigt=False), monkeypatch)

    assert "oidc_kein_konto" in antwort.headers["location"]
    assert db.query(Benutzer).count() == 1


def test_eine_einladung_an_eine_andere_adresse_zaehlt_nicht(klient, anbieter_da, monkeypatch, db):
    _einladung(db, adresse="berta@example.com", benutzername="berta")
    klient.cookies.clear()

    antwort = _lauf(klient, Attrappe(email="anna@example.com"), monkeypatch)
    assert "oidc_kein_konto" in antwort.headers["location"]
    assert db.query(Benutzer).count() == 1


def test_eine_abgelaufene_einladung_zaehlt_nicht(klient, anbieter_da, monkeypatch, db):
    from datetime import datetime, timedelta, timezone

    from app.models import Einladung

    _einladung(db)
    zeile = db.query(Einladung).one()
    zeile.laeuft_ab = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(email="anna@example.com"), monkeypatch)
    assert "oidc_kein_konto" in antwort.headers["location"]
    assert db.query(Benutzer).count() == 1


def test_ohne_konto_und_ohne_einladung_kommt_niemand_herein(klient, anbieter_da, monkeypatch, db):
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(email="fremd@example.com"), monkeypatch)

    assert "oidc_kein_konto" in antwort.headers["location"]
    assert db.query(Benutzer).count() == 1


def test_eine_falsche_unterschrift_kommt_nicht_durch(klient, anbieter_da, monkeypatch):
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(falsche_unterschrift=True), monkeypatch)
    assert "oidc_ausweis" in antwort.headers["location"]
    assert klient.get("/api/auth/ich").status_code == 401


def test_der_verwechslungs_angriff_kommt_nicht_durch(klient, anbieter_da, monkeypatch):
    """⚠️ **Der bekannteste JWT-Angriff.**

    Wer den ``alg``-Kopf auf ``HS256`` umbiegt, laesst den Ausweis symmetrisch
    pruefen — mit dem **oeffentlichen** Schluessel als Geheimnis. Den kennt
    jeder, er steht im JWKS. Stuende HS256 in ``VERFAHREN``, koennte sich damit
    jeder einen Ausweis bauen und sich als beliebiger Mensch anmelden.

    Deshalb fehlt HS256 dort mit Absicht — und deshalb steht dieser Test hier.
    """
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(alg_verwechslung=True), monkeypatch)
    assert "oidc_ausweis" in antwort.headers["location"]
    assert klient.get("/api/auth/ich").status_code == 401


def test_ein_fremder_nonce_kommt_nicht_durch(klient, anbieter_da, monkeypatch):
    """⚠️ Ohne diese Pruefung liesse sich ein abgefangener Ausweis ein zweites
    Mal einloesen."""
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(falscher_nonce="etwas-anderes"), monkeypatch)
    assert "oidc_ausweis" in antwort.headers["location"]


def test_ein_anderer_aussteller_wird_abgewiesen(klient, anbieter_da, monkeypatch):
    """⚠️ Sonst koennte ein Anbieter Ausweise im Namen eines anderen ausstellen."""
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(falscher_aussteller="https://boeser.example"), monkeypatch)
    assert "oidc_falscher_aussteller" in antwort.headers["location"]


def test_userinfo_mit_fremdem_sub_wird_verworfen(klient, anbieter_da, monkeypatch, db):
    """⚠️ **OIDC Core 5.3.2.** Ohne die Pruefung liesse sich einer beglaubigten
    Anmeldung die Adresse einer fremden anhaengen."""
    person = db.query(Benutzer).one()
    person.benutzername = "anna@example.com"
    db.commit()

    klient.cookies.clear()
    attrappe = Attrappe(
        email=None,
        email_bestaetigt=None,
        userinfo={"email": "anna@example.com", "email_verified": True},
        userinfo_fremdes_sub=True,
    )
    antwort = _lauf(klient, attrappe, monkeypatch)
    assert "oidc_kein_konto" in antwort.headers["location"]


def test_ohne_anlauf_cookie_geht_nichts(klient, anbieter_da, monkeypatch):
    """Eine Rueckkehr, die dieser Browser nie begonnen hat."""
    einspannen(monkeypatch, Attrappe())
    klient.cookies.clear()
    antwort = klient.get("/api/oidc/keycloak/zurueck?code=abc&state=xyz", follow_redirects=False)
    assert antwort.status_code == 303
    assert "oidc_anlauf_fehlt" in antwort.headers["location"]


def test_ein_abgeschalteter_anbieter_ist_zu(klient, anbieter_da, monkeypatch):
    """⚠️ Abschalten blendet nicht nur den Knopf aus."""
    klient.put(
        f"/api/oidc/anbieter/{anbieter_da['id']}",
        json={
            "kuerzel": "keycloak",
            "anzeigename": "Keycloak",
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "aktiv": False,
        },
    )
    assert klient.get("/api/oidc/keycloak/start", follow_redirects=False).status_code == 404
    assert klient.get("/api/oidc/keycloak/zurueck?code=a&state=b", follow_redirects=False).status_code == 404
    assert klient.get("/api/oidc/knoepfe").json() == []


# --- Wie ein Fehler ankommt ----------------------------------------------- #


def test_jeder_ausgang_ist_eine_weiterleitung(klient, anbieter_da, monkeypatch):
    """⚠️ **Den Rueckweg sieht ein Mensch.** Nacktes JSON waere die falsche
    Antwort — der Browser zeigt es einfach an."""
    klient.cookies.clear()
    for attrappe in (
        Attrappe(tausch_scheitert=True),
        Attrappe(ohne_ausweis=True),
        Attrappe(falsche_unterschrift=True),
    ):
        antwort = _lauf(klient, attrappe, monkeypatch)
        assert antwort.status_code == 303, attrappe
        assert antwort.headers["location"].startswith("/?oidc_fehler="), attrappe


def test_der_anbieter_lehnt_selbst_ab(klient, anbieter_da, monkeypatch):
    """⚠️ **Diese Pruefung steht vor der des ``state``.**

    Ein Rueckweg mit ``error`` traegt keinen brauchbaren ``state``; sonst
    entstuende daraus „Anlauf fehlt" — und der Anmeldende wiederholt vergeblich,
    statt zu erfahren, dass der Anbieter abgelehnt hat.
    """
    einspannen(monkeypatch, Attrappe())
    klient.cookies.clear()
    antwort = klient.get(
        "/api/oidc/keycloak/zurueck?error=access_denied&error_description=abgebrochen",
        follow_redirects=False,
    )
    assert "oidc_abgelehnt" in antwort.headers["location"]


def test_html_statt_json_wird_benannt(klient, anbieter_da, monkeypatch):
    """⚠️ **Der haeufigste Fall.** Ein Proxy oder eine Anmeldeseite vor dem
    Anbieter — zurueck kommt HTML, oft mit Status 200."""
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(html_statt_json=True), monkeypatch)
    assert "oidc_kein_json" in antwort.headers["location"]


def test_ohne_oeffentliche_adresse_faengt_es_gar_nicht_an(klient, anbieter_da, monkeypatch):
    """⚠️ Aus ihr entsteht die Rueckkehr-Adresse."""
    from app.db import SessionLocal, einstellung_schreiben

    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "")

    einspannen(monkeypatch, Attrappe())
    antwort = klient.get("/api/oidc/keycloak/start", follow_redirects=False)
    assert "oidc_keine_adresse" in antwort.headers["location"]


# --- Die Bremse ------------------------------------------------------------ #


def test_die_bremse_haengt_nicht_am_anbieter(klient, anbieter_da, monkeypatch, db):
    """⚠️ **Der Fehler, der aus der Bremse eine Waffe machte.**

    In nexview zaehlte sie am Anbieter-Kuerzel. Ein Fremder holte sich ein
    eigenes Anlauf-Cookie, kehrte zehnmal mit erfundenem Code zurueck — und
    danach kam **niemand** mehr ueber diesen Anbieter herein.
    """
    _lauf(klient, Attrappe(), monkeypatch)  # erst verknuepfen

    einspannen(monkeypatch, Attrappe(tausch_scheitert=True))
    # Zwanzig gescheiterte Laeufe eines Fremden.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as fremder:
        for _ in range(20):
            _lauf(fremder, Attrappe(tausch_scheitert=True), monkeypatch)

    # Und danach kommt ein ehrlicher Lauf trotzdem durch.
    klient.cookies.clear()
    antwort = _lauf(klient, Attrappe(), monkeypatch)
    assert "oidc_fehler" not in antwort.headers["location"], antwort.headers["location"]


# --- Verwaltung und Verknuepfungen ---------------------------------------- #


def test_nur_der_betreiber_verwaltet_anbieter(klient, zweiter_klient, anbieter_da, db):
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get("/api/oidc/anbieter").status_code == 403
    assert (
        zweiter_klient.delete(f"/api/oidc/anbieter/{anbieter_da['id']}").status_code == 403
    )
    # Die Knoepfe fuer die Anmeldeseite sieht dagegen jeder — sie stehen ohnehin
    # offen auf der Anmeldemaske.
    assert zweiter_klient.get("/api/oidc/knoepfe").status_code == 200


def test_das_geheimnis_verlaesst_den_server_nie(klient, anbieter_da, db):
    """Auch nicht verschluesselt."""
    zeilen = klient.get("/api/oidc/anbieter").json()
    assert zeilen[0]["geheimnis_liegt_vor"] is True
    assert "client_secret" not in zeilen[0]

    roh = db.query(OidcAnbieter).one().client_secret
    assert "geheim" not in roh
    assert roh.startswith("v1:")


def test_die_rueckkehr_adresse_steht_zum_abschreiben_da(klient, anbieter_da):
    """⚠️ Sie muss beim Anbieter hinterlegt werden — wer sie abtippt, vertippt
    sich."""
    zeile = klient.get("/api/oidc/anbieter").json()[0]
    assert zeile["rueckkehr_adresse"] == "https://mail.example/api/oidc/keycloak/zurueck"


def test_die_letzte_verknuepfung_laesst_sich_nicht_loesen(klient, anbieter_da, monkeypatch, db):
    """Wer kein Kennwort hat, sperrt sich damit selbst aus."""
    _einladung(db)
    klient.cookies.clear()
    _lauf(klient, Attrappe(email="anna@example.com"), monkeypatch)

    meine = klient.get("/api/oidc/meine").json()
    assert len(meine) == 1
    antwort = klient.delete(f"/api/oidc/meine/{meine[0]['id']}")
    assert antwort.status_code == 400
    assert "Kennwort" in antwort.json()["detail"]


def test_verknuepfen_ueberlebt_den_strengen_rueckweg(klient, anbieter_da, monkeypatch, db):
    """⚠️ **Der Test, den es bis zum 01.09.2026 nicht gab — und der Grund dafuer.**

    Das Sitzungs-Cookie steht auf ``SameSite=strict``. Der Rueckweg vom
    Anbieter ist eine Navigation von **fremder** Seite, also schickt der
    Browser es nicht mit. Der Rueckweg holte die Person aber aus der Sitzung
    und fand keine: ``oidc_abgemeldet — the session is gone; nothing was
    linked``. Der Verknuepfen-Knopf im Profil sah damit aus, als taete er
    etwas, und tat nie etwas.

    ⚠️ **Kein bestehender Test konnte das sehen**, denn ``TestClient``
    schickt seine Cookies ohne Ruecksicht auf ``SameSite``. Hier wird das
    Cookie deshalb von Hand entfernt — genau zwischen Hinweg und Rueckweg,
    so wie der Browser es tut.

    Aufgefallen ist es erst am echten Keycloak im Pruefstand.
    """
    from urllib.parse import parse_qs, urlparse

    from app.services.sitzung import COOKIE_NAME

    attrappe = Attrappe()
    einspannen(monkeypatch, attrappe)

    hin = klient.get("/api/oidc/keycloak/start", follow_redirects=False)
    assert hin.status_code == 303, hin.text
    frage = parse_qs(urlparse(hin.headers["location"]).query)
    attrappe._nonce = frage["nonce"][0]

    # Der Browser laesst das strenge Cookie beim Rueckweg zu Hause.
    sitzungswert = klient.cookies.get(COOKIE_NAME)
    assert sitzungswert, "Ohne Sitzung prueft dieser Test nichts."
    del klient.cookies[COOKIE_NAME]

    zurueck = klient.get(
        f"/api/oidc/keycloak/zurueck?code=abc&state={frage['state'][0]}",
        follow_redirects=False,
    )

    assert zurueck.headers["location"].endswith("oidc=verknuepft"), zurueck.headers["location"]
    assert db.query(OidcVerknuepfung).count() == 1
    assert db.query(Benutzer).count() == 1, "Es ist ein zweites Konto entstanden."


def test_ohne_anlauf_wird_nichts_verknuepft(klient, anbieter_da, monkeypatch, db):
    """Die Gegenprobe: Die Kennung kommt aus dem **signierten** Anlauf.

    Ohne ihn — oder mit einer Kennung, zu der es niemanden gibt — entsteht
    keine Verknuepfung. Sonst haette der Umbau die Sitzungspruefung durch gar
    keine ersetzt.
    """
    from app.services import oidc as oidcdienst

    einspannen(monkeypatch, Attrappe())
    echt = oidcdienst.anlauf_erzeugen
    monkeypatch.setattr(
        oidcdienst,
        "anlauf_erzeugen",
        lambda k, a, b="": echt(k, a, "gibt-es-nicht"),
    )

    antwort = _lauf(klient, Attrappe(), monkeypatch)
    assert "oidc_fehler=oidc_abgemeldet" in antwort.headers["location"], antwort.headers["location"]
    assert db.query(OidcVerknuepfung).count() == 0
