"""OAuth für Google und Microsoft.

⚠️ **Hier kann ein Zugang still sterben.** Google zieht Auffrischungs-Token
zurück, wenn der Benutzer sein Passwort ändert — und nach sieben Tagen,
solange die App auf „Testing" steht. Das muss als „bitte neu zustimmen"
ankommen, nicht als „Mailserver kaputt".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import Benutzer, OauthAnbieter, OauthZugang
from app.services import mailoauth
from conftest import einrichten


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    mailoauth.anbieter_setzen(db, "google", "kennung.apps.googleusercontent.com", "geheim")
    return person


class Anbieter:
    """Der Token-Endpunkt, den man steuern kann."""

    def __init__(self):
        self.antworten: list[httpx.Response] = []
        self.anfragen: list[dict] = []

    def __call__(self, ziel, data=None, timeout=None):  # noqa: ARG002
        self.anfragen.append(dict(data or {}))
        if self.antworten:
            return self.antworten.pop(0)
        return httpx.Response(
            200,
            json={
                "access_token": "zugriff-1",
                "refresh_token": "auffrischung-1",
                "expires_in": 3600,
                "scope": "https://mail.google.com/",
            },
        )


@pytest.fixture
def anbieter(monkeypatch):
    falsch = Anbieter()
    monkeypatch.setattr(mailoauth.httpx, "post", falsch)
    return falsch


# --- Die App des Betreibers ----------------------------------------------- #


def test_das_geheimnis_liegt_verschluesselt(db, welt):
    eintrag = mailoauth.anbieter(db, "google")
    assert eintrag.client_secret
    assert "geheim" not in eintrag.client_secret
    assert mailoauth._geheimnis(eintrag) == "geheim"


def test_leeres_geheimnis_heisst_unveraendert(db, welt):
    """⚠️ Dieselbe Regel wie beim Passwort — sonst verliert es, wer nur den
    Mandanten ändert."""
    mailoauth.anbieter_setzen(db, "google", "andere-kennung", "", "common")
    assert mailoauth._geheimnis(mailoauth.anbieter(db, "google")) == "geheim"


def test_eine_unbekannte_art_geht_nicht(db, welt):
    with pytest.raises(mailoauth.OauthFehler) as f:
        mailoauth.anbieter_setzen(db, "yahoo", "x", "y")
    assert str(f.value) == "oauth_art_unbekannt"


# --- Der Hinweg ------------------------------------------------------------ #


def test_der_hinweg_traegt_alles_noetige(db, welt):
    ziel = mailoauth.hinweg(db, "google", "https://mail.example.com/zurueck", "anlauf-1")

    assert ziel.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    # ⚠️ **Beides ist Pflicht für ein Auffrischungs-Token.** Ohne
    # ``access_type=offline`` gibt Google gar keines, ohne ``prompt=consent``
    # nur beim allerersten Mal.
    assert "access_type=offline" in ziel
    assert "prompt=consent" in ziel
    assert "state=anlauf-1" in ziel
    # ⚠️ Alle Bereiche auf einmal — sonst muss man für den Kalender ein
    # zweites Mal zustimmen.
    assert "mail.google.com" in ziel
    assert "auth%2Fcalendar" in ziel


def test_ohne_app_geht_gar_nichts(db, klient):
    einrichten(klient)
    with pytest.raises(mailoauth.OauthFehler) as f:
        mailoauth.hinweg(db, "google", "https://mail.example.com/zurueck", "x")
    assert str(f.value) == "oauth_anbieter_fehlt"


def test_microsoft_traegt_den_mandanten(db, klient):
    einrichten(klient)
    mailoauth.anbieter_setzen(db, "microsoft", "kennung", "geheim", "meine-firma")
    ziel = mailoauth.hinweg(db, "microsoft", "https://mail.example.com/zurueck", "x")
    assert "login.microsoftonline.com/meine-firma/" in ziel
    assert "offline_access" in ziel


# --- Der Rückweg ----------------------------------------------------------- #


def _id_token(adresse: str) -> str:
    import base64
    import json

    rumpf = base64.urlsafe_b64encode(json.dumps({"email": adresse}).encode()).decode().rstrip("=")
    return f"kopf.{rumpf}.unterschrift"


def test_der_zugang_wird_verschluesselt_abgelegt(db, welt, anbieter):
    anbieter.antworten.append(
        httpx.Response(
            200,
            json={
                "access_token": "zugriff-1",
                "refresh_token": "auffrischung-1",
                "expires_in": 3600,
                "id_token": _id_token("anja@example.org"),
            },
        )
    )
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")

    assert zugang.adresse == "anja@example.org"
    assert "auffrischung-1" not in zugang.refresh
    assert "zugriff-1" not in zugang.zugriff
    assert mailoauth.zugriffstoken(db, zugang) == "zugriff-1"


def test_ohne_auffrischungstoken_wird_sofort_gemeckert(db, welt, anbieter):
    """⚠️ Ohne es ist der Zugang eine Stunde alt. Das jetzt zu melden ist
    besser als in einer Stunde."""
    anbieter.antworten.append(
        httpx.Response(200, json={"access_token": "zugriff-1", "expires_in": 3600})
    )
    with pytest.raises(mailoauth.OauthFehler) as f:
        mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    assert str(f.value) == "oauth_kein_refresh"


# --- Erneuern -------------------------------------------------------------- #


def test_ein_frisches_token_wird_nicht_erneuert(db, welt, anbieter):
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    anbieter.anfragen.clear()

    mailoauth.zugriffstoken(db, zugang)

    assert anbieter.anfragen == []


def test_kurz_vor_ablauf_wird_erneuert(db, welt, anbieter):
    """⚠️ **Mit Vorlauf, nicht erst beim Ablauf.** Zwischen der Prüfung und der
    IMAP-Anmeldung liegen Sekunden, und ein gerade abgelaufenes Token sieht aus
    wie ein falsches Passwort."""
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    zugang.ablauf = datetime.now(timezone.utc) + timedelta(minutes=1)
    db.commit()
    anbieter.antworten.append(
        httpx.Response(200, json={"access_token": "zugriff-2", "expires_in": 3600})
    )

    assert mailoauth.zugriffstoken(db, zugang) == "zugriff-2"
    assert anbieter.anfragen[-1]["grant_type"] == "refresh_token"


def test_ein_neues_auffrischungstoken_wird_uebernommen(db, welt, anbieter):
    """⚠️ Microsoft schickt bei jeder Erneuerung eines mit. Wer es wegwirft,
    fährt weiter mit dem alten und steht irgendwann ohne da."""
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    zugang.ablauf = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    anbieter.antworten.append(
        httpx.Response(
            200,
            json={
                "access_token": "zugriff-2",
                "refresh_token": "auffrischung-2",
                "expires_in": 3600,
            },
        )
    )

    mailoauth.zugriffstoken(db, zugang)
    zugang.ablauf = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    anbieter.antworten.append(
        httpx.Response(200, json={"access_token": "zugriff-3", "expires_in": 3600})
    )
    mailoauth.zugriffstoken(db, zugang)

    assert anbieter.anfragen[-1]["refresh_token"] == "auffrischung-2"


def test_ein_widerrufener_zugang_wird_benannt(db, welt, anbieter):
    """⚠️ **Der Fall, um den es geht.** Google zieht das Token zurück, wenn der
    Benutzer sein Passwort ändert — oder nach sieben Tagen im Testbetrieb. Das
    muss „bitte neu zustimmen" heißen, nicht „Mailserver kaputt"."""
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    zugang.ablauf = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    anbieter.antworten.append(httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(mailoauth.OauthFehler) as f:
        mailoauth.zugriffstoken(db, zugang)
    assert str(f.value) == "oauth_zustimmung_abgelaufen"

    db.refresh(zugang)
    # ⚠️ Und es steht an der Zeile — sonst sieht man nur, dass „irgendwas" ist.
    assert zugang.letzter_fehler == "oauth_zustimmung_abgelaufen"


# --- XOAUTH2 --------------------------------------------------------------- #


def test_die_sasl_zeichenkette_ist_starr():
    """⚠️ Ein Byte daneben, und der Server antwortet mit demselben
    „Anmeldung fehlgeschlagen" wie bei einem falschen Passwort."""
    assert mailoauth.xoauth2("a@example.com", "T") == "user=a@example.com\x01auth=Bearer T\x01\x01"


# --- Die Adressen ---------------------------------------------------------- #


def test_nur_der_betreiber_darf_die_app_eintragen(klient, db):
    einrichten(klient)
    antwort = klient.get("/api/mailoauth/anbieter")
    assert antwort.status_code == 200
    assert {z["art"] for z in antwort.json()} == {"google", "microsoft"}
    assert all(z["eingerichtet"] is False for z in antwort.json())


def test_die_rueckkehradresse_steht_zum_kopieren_da(klient, db):
    einrichten(klient)
    klient.put(
        "/api/einstellungen",
        json={"oeffentliche_adresse": "https://mail.example.com", "zeitzone": "Europe/Berlin"},
    )
    zeilen = klient.get("/api/mailoauth/anbieter").json()
    google = next(z for z in zeilen if z["art"] == "google")
    assert google["rueckkehr"] == "https://mail.example.com/api/mailoauth/google/zurueck"


def test_ein_abgelehnter_rueckweg_leitet_weiter_statt_json(klient, db):
    """⚠️ Den Rückweg sieht ein Mensch."""
    einrichten(klient)
    antwort = klient.get(
        "/api/mailoauth/google/zurueck?error=access_denied", follow_redirects=False
    )
    assert antwort.status_code == 303
    assert "oauth=abgelehnt" in antwort.headers["location"]


def test_ohne_anlauf_passiert_nichts(klient, db):
    einrichten(klient)
    antwort = klient.get(
        "/api/mailoauth/google/zurueck?code=x&state=y", follow_redirects=False
    )
    assert antwort.status_code == 303
    assert "oauth=anlauf_fehlt" in antwort.headers["location"]


def test_der_verbindungstest_benutzt_das_token(klient, db, welt, anbieter, monkeypatch):
    """⚠️ **Sonst lässt sich ein Google-Postfach gar nicht anlegen.**

    Beim Anlegen ist der Verbindungstest Pflicht (`disabled={!befund?.ok}`).
    Prüft er mit einem leeren Passwort statt mit dem Token, scheitert er
    zwangsläufig — und der Knopf „Hinzufügen" bleibt für immer grau. Am
    03.09.2026 aufgefallen, als das erste echte Konto verbunden war.
    """
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")

    gesehen: dict = {}

    from app.services.imap import Fehlerart, Verbindungsfehler

    def falsches_imap(server, port, sicherheit, benutzer, passwort, wo="", token=""):
        gesehen["imap_token"] = token
        raise Verbindungsfehler(Fehlerart.NICHT_ERREICHBAR, "aus")

    def falsches_smtp(server, port, sicherheit, benutzer, passwort, wo="", token=""):
        gesehen["smtp_token"] = token

    from app.services import imap as imapdienst

    monkeypatch.setattr(imapdienst, "verbinden", falsches_imap)
    monkeypatch.setattr(imapdienst, "smtp_pruefen", falsches_smtp)

    antwort = klient.post(
        "/api/konten/pruefen",
        json={
            "adresse": "anja@example.com",
            "imap_server": "imap.gmail.com",
            "imap_benutzer": "anja@example.com",
            "imap_passwort": "",
            "smtp_server": "smtp.gmail.com",
            "smtp_benutzer": "anja@example.com",
            "smtp_passwort": "",
            "oauth_zugang_id": zugang.id,
        },
    )

    assert antwort.status_code == 200, antwort.text
    assert gesehen["imap_token"] == "zugriff-1"
    assert gesehen["smtp_token"] == "zugriff-1"


def test_ein_fremder_zugang_gibt_404(klient, db, welt, anbieter):
    antwort = klient.post(
        "/api/konten/pruefen",
        json={
            "adresse": "anja@example.com",
            "imap_server": "imap.gmail.com",
            "imap_benutzer": "anja@example.com",
            "smtp_server": "smtp.gmail.com",
            "smtp_benutzer": "anja@example.com",
            "oauth_zugang_id": "gibtesnicht",
        },
    )
    assert antwort.status_code == 404


def test_auch_das_ANLEGEN_benutzt_das_token(klient, db, welt, anbieter, monkeypatch):
    """⚠️ **Derselbe Fehler ein zweites Mal — deshalb dieser Test.**

    Das Anlegen prüft **noch einmal** (es glaubt der Oberfläche bewusst
    nicht). Am 03.09.2026 hatte nur der Prüf-Aufruf den Token bekommen: Der
    Test wurde grün, und das Anlegen scheiterte danach mit „app-spezifisches
    Passwort nötig" — an einem Postfach, das gerade zweimal grün gemeldet
    hatte.
    """
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    gesehen: list[str] = []

    from app.services import konten as kontendienst
    from app.services.imap import Ordnerangabe

    def falsches_pruefen(daten, wo="", token=""):
        gesehen.append(token)
        return kontendienst.Befund(
            imap=kontendienst.Teilbefund(ok=True),
            smtp=kontendienst.Teilbefund(ok=True),
            ordner=[Ordnerangabe(pfad="INBOX", name="INBOX", rolle="posteingang")],
            faehigkeiten=[],
        )

    monkeypatch.setattr(kontendienst, "pruefen", falsches_pruefen)

    antwort = klient.post(
        "/api/konten",
        json={
            "anzeigename": "Gmail",
            "adresse": "anja@example.com",
            "imap_server": "imap.gmail.com",
            "imap_benutzer": "anja@example.com",
            "smtp_server": "smtp.gmail.com",
            "smtp_benutzer": "anja@example.com",
            "oauth_zugang_id": zugang.id,
        },
    )

    assert antwort.status_code == 201, antwort.text
    assert gesehen == ["zugriff-1"]


def test_mit_zustimmung_faellt_der_app_passwort_hinweis_weg(db, welt, anbieter, klient):
    """⚠️ Er schickte den Betreiber ein Passwort erzeugen, das gar nicht
    gebraucht wird."""
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")

    from app.routers.konten import Eingabe, _wie_anmelden

    eingabe = Eingabe(
        adresse="anja@example.com",
        imap_server="imap.gmail.com",
        imap_benutzer="anja@example.com",
        smtp_server="smtp.gmail.com",
        smtp_benutzer="anja@example.com",
        oauth_zugang_id=zugang.id,
    )
    wo, token = _wie_anmelden(db, welt, eingabe)
    assert wo == ""
    assert token == "zugriff-1"


# --- Trennen: was daran haengt, geht mit ---------------------------------- #


def _postfach_und_kalender(db, person, zugang):
    """Ein Postfach und ein Kalender, beide an dieser Zustimmung."""
    from app.models import Kalender, Konto

    konto = Konto(
        benutzer_id=person.id,
        anzeigename="Anja",
        adresse="anja@example.com",
        imap_server="imap.gmail.com",
        imap_benutzer="anja@example.com",
        smtp_server="smtp.gmail.com",
        smtp_benutzer="anja@example.com",
        oauth_zugang_id=zugang.id,
    )
    kalender = Kalender(
        benutzer_id=person.id,
        name="Privat",
        art="caldav",
        url="https://apidata.googleusercontent.com/caldav/v2/x/events",
        oauth_zugang_id=zugang.id,
    )
    db.add_all([konto, kalender])
    db.commit()
    return konto, kalender


def test_trennen_nimmt_postfach_und_kalender_mit(db, welt, anbieter):
    """⚠️ **Ein Postfach ohne Zustimmung hat keinen Anmeldeweg mehr.**

    Der Fremdschlüssel steht auf ``SET NULL``; ohne das Aufräumen bliebe die
    Zeile stehen und meldete bei jedem Takt „Anmeldung fehlgeschlagen" —
    dieselbe Meldung wie bei einem Tippfehler im Passwort, und niemand brächte
    sie mit dem Trennen in Verbindung.
    """
    from app.models import Kalender, Konto

    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    _postfach_und_kalender(db, welt, zugang)

    mailoauth.entfernen(db, welt, zugang.id)

    assert db.query(Konto).count() == 0
    assert db.query(Kalender).count() == 0
    assert db.query(OauthZugang).count() == 0


def test_die_zahlen_stehen_vor_der_frage(db, welt, anbieter, klient):
    """⚠️ **„2 Postfächer und 3 Kalender werden entfernt" ist eine andere
    Entscheidung als „Zustimmung entfernen".** Wer das erst hinterher erfährt,
    hat es nicht entschieden — deshalb liefert die Liste die Zahlen mit."""
    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    _postfach_und_kalender(db, welt, zugang)

    zeile = klient.get("/api/mailoauth/zugaenge").json()[0]
    assert zeile["postfaecher"] == 1
    assert zeile["kalender"] == 1


def test_ein_fremdes_postfach_bleibt_stehen(db, welt, anbieter):
    """Nur was an DIESER Zustimmung hängt. Ein Postfach mit Passwort geht das
    Trennen nichts an."""
    from app.models import Konto

    zugang = mailoauth.einloesen(db, welt, "google", "code-1", "https://mail.example.com/z")
    _postfach_und_kalender(db, welt, zugang)
    db.add(
        Konto(
            benutzer_id=welt.id,
            anzeigename="Arbeit",
            adresse="anja@example.com",
            imap_server="imap.example.com",
            imap_benutzer="anja@example.com",
            smtp_server="smtp.example.com",
            smtp_benutzer="anja@example.com",
        )
    )
    db.commit()

    mailoauth.entfernen(db, welt, zugang.id)

    uebrig = db.query(Konto).all()
    assert [k.adresse for k in uebrig] == ["anja@example.com"]


# --- Der Zweck faehrt im Anlauf mit --------------------------------------- #


def test_der_zweck_ueberlebt_den_rueckweg(db, welt, anbieter, klient):
    """⚠️ **Der Rückweg vom Anbieter ist eine ganze Seitennavigation.** Was die
    Oberfläche offen hatte, ist danach weg; ohne diesen Hinweis landete jeder
    wieder am Anfang und müsste den Weg von vorn beginnen."""
    hin = klient.post("/api/mailoauth/google/start", json={"zweck": "postfach"})
    assert hin.status_code == 200, hin.text
    anlauf = klient.cookies.get("nexmail_oauth")
    zustand = anlauf.split(":")[0]

    zurueck = klient.get(
        f"/api/mailoauth/google/zurueck?state={zustand}&code=code-1",
        follow_redirects=False,
    )
    ziel = zurueck.headers["location"]
    assert "oauth=ok" in ziel
    assert "weiter=postfach" in ziel
    # Ohne die Kennung wüsste das Fenster nicht, welche Zustimmung gerade
    # entstanden ist — bei zwei Google-Konten wäre das geraten.
    assert f"zugang={db.query(OauthZugang).one().id}" in ziel


def test_ohne_zweck_bleibt_der_rueckweg_schlicht(db, welt, anbieter, klient):
    """Aus Einstellungen → Sicherheit kommt kein Zweck; dann soll auch keiner
    in der Adresse stehen."""
    klient.post("/api/mailoauth/google/start", json={})
    zustand = klient.cookies.get("nexmail_oauth").split(":")[0]

    ziel = klient.get(
        f"/api/mailoauth/google/zurueck?state={zustand}&code=code-1",
        follow_redirects=False,
    ).headers["location"]
    assert "weiter=" not in ziel


def test_ein_erfundener_zweck_wird_abgewiesen(db, welt, anbieter, klient):
    """⚠️ Der Wert landet in einer Weiterleitungsadresse. Eine freie
    Zeichenkette wäre eine Einladung, dort etwas anderes unterzubringen."""
    antwort = klient.post("/api/mailoauth/google/start", json={"zweck": "https://example.com"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "oauth_zweck"


def test_moeglich_steht_jedem_offen_und_verraet_nichts(db, welt, klient):
    """⚠️ **Ein Knopf, der nur in eine Fehlermeldung führt, ist eine Sackgasse
    mit Beschriftung.** Auch ein gewöhnlicher Benutzer muss erfahren, welche
    Anbieter offenstehen — aber nicht, wie die Installation eingerichtet ist."""
    zeilen = klient.get("/api/mailoauth/moeglich").json()
    google = next(z for z in zeilen if z["art"] == "google")

    assert google["eingerichtet"] is True
    assert next(z for z in zeilen if z["art"] == "microsoft")["eingerichtet"] is False
    # Client-ID, Mandant und Rückkehr-Adresse bleiben beim Betreiber.
    assert set(google) == {"art", "name", "eingerichtet"}
