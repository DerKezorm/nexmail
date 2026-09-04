"""Mehrbenutzer: einladen, annehmen, entfernen.

⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
einzeln — nexmail ist der Mail-Client eines Haushalts, keine Plattform.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal, einstellung_schreiben
from app.models import Benutzer, Einladung
from app.services import anmeldebremse, systempost
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

PASSWORT = "sehr-geheim-123"


@pytest.fixture(autouse=True)
def freie_bremse():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def postausgang(monkeypatch, klient):
    """Ein eingerichteter Systempostausgang, der nichts wirklich verschickt."""
    versandt: list[tuple[str, str, str, str]] = []

    def merken(db, an, betreff, text, html=""):
        versandt.append((an, betreff, text, html))

    monkeypatch.setattr(systempost, "senden", merken)
    # Die Einladung ruft ihn ueber ihr eigenes Modul auf.
    from app.services import einladung as einladungsdienst

    monkeypatch.setattr(einladungsdienst.systempost, "senden", merken)
    monkeypatch.setattr(
        systempost, "lesen", lambda db: systempost.Postausgang(server="s.example", absender="a@b.example")
    )
    monkeypatch.setattr(
        einladungsdienst.systempost,
        "lesen",
        lambda db: systempost.Postausgang(server="s.example", absender="a@b.example"),
    )
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")
    return versandt


def _schluessel_aus(link_text: str) -> str:
    for wort in link_text.split():
        if "/einladung/" in wort:
            return wort.rsplit("/", 1)[1]
    raise AssertionError(f"Kein Einladungslink in der Mail:\n{link_text}")


# --- Wer darf hier ueberhaupt hin --------------------------------------- #


def test_nur_der_betreiber_verwaltet_benutzer(klient, zweiter_klient, db):
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert klient.get("/api/benutzer").status_code == 200
    assert zweiter_klient.get("/api/benutzer").status_code == 403
    assert (
        zweiter_klient.post(
            "/api/benutzer/einladungen",
            json={"benutzername": "dritter", "adresse": "wer@example.com"},
        ).status_code
        == 403
    )


def test_ohne_anmeldung_gar_nichts(klient):
    einrichten(klient)
    klient.cookies.clear()
    assert klient.get("/api/benutzer").status_code == 401


# --- Einladen ------------------------------------------------------------ #


def test_ohne_postausgang_wird_vorher_gewarnt(klient):
    """⚠️ Die Oberflaeche soll es sagen koennen, **bevor** jemand tippt."""
    einrichten(klient)
    stand = klient.get("/api/benutzer").json()
    assert stand["postausgang_da"] is False
    assert stand["adresse_da"] is False


def test_ohne_oeffentliche_adresse_geht_keine_einladung(klient, postausgang):
    """Der Link in der Mail waere sonst unbrauchbar."""
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "")

    antwort = klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "oeffentliche_adresse_fehlt"


def test_einladen_verschickt_eine_mail_mit_link(klient, postausgang):
    einrichten(klient)
    antwort = klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com", "anzeigename": "Anna"},
    )
    assert antwort.status_code == 201, antwort.text
    assert len(postausgang) == 1

    an, _betreff, text, _html = postausgang[0]
    assert an == "anna@example.com"
    assert "https://mail.example/einladung/" in text
    # ⚠️ Der Benutzername gehoert hinein — sonst weiss der Eingeladene beim
    # ersten Anmelden nicht, wer er ist.
    assert "anna" in text


def test_der_schluessel_liegt_nur_als_hash_da(klient, postausgang, db):
    """⚠️ Er oeffnet ein Konto — das ist ein Passwort, kein Merkmal."""
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    schluessel = _schluessel_aus(postausgang[0][2])

    zeile = db.query(Einladung).one()
    assert schluessel not in zeile.schluessel_hash
    assert len(zeile.schluessel_hash) == 64


def test_gescheiterter_versand_laesst_keine_leiche_zurueck(klient, monkeypatch):
    """⚠️ **Die schlimmste Sorte Einladung**: steht in der Liste, kam nie an.

    Der Betreiber wartet, der Eingeladene weiss von nichts, und in der
    Oberflaeche sieht alles richtig aus.
    """
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")

    from app.services import einladung as einladungsdienst

    def scheitern(db, an, betreff, text, html=""):
        raise systempost.PostFehler("Der Postausgang ist nicht erreichbar.")

    monkeypatch.setattr(einladungsdienst.systempost, "senden", scheitern)

    antwort = klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    assert antwort.status_code == 502
    assert klient.get("/api/benutzer").json()["einladungen"] == []


def test_ein_belegter_name_wird_abgewiesen(klient, postausgang):
    einrichten(klient)
    antwort = klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "betreiber", "adresse": "wer@example.com"},
    )
    assert antwort.status_code == 400


def test_zweimal_einladen_ersetzt_den_alten_link(klient, postausgang, db):
    """⚠️ Sonst gelten zwei Links fuer dasselbe Konto.

    Der Betreiber verschickt einen neuen, weil der alte verloren ging — und der
    alte oeffnet weiter.
    """
    einrichten(klient)
    for _ in range(2):
        klient.post(
            "/api/benutzer/einladungen",
            json={"benutzername": "anna", "adresse": "anna@example.com"},
        )

    assert db.query(Einladung).count() == 1
    alter = _schluessel_aus(postausgang[0][2])
    neuer = _schluessel_aus(postausgang[1][2])
    assert alter != neuer

    klient.cookies.clear()
    assert klient.get(f"/api/einladung/{alter}").status_code == 404
    assert klient.get(f"/api/einladung/{neuer}").status_code == 200


# --- Annehmen ------------------------------------------------------------ #


def test_annehmen_macht_ein_konto_und_meldet_an(klient, zweiter_klient, postausgang):
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com", "anzeigename": "Anna"},
    )
    schluessel = _schluessel_aus(postausgang[0][2])

    vorschau = zweiter_klient.get(f"/api/einladung/{schluessel}")
    assert vorschau.status_code == 200
    assert vorschau.json() == {"benutzername": "anna", "anzeigename": "Anna"}

    fertig = zweiter_klient.post(
        f"/api/einladung/{schluessel}", json={"passwort": "annas-kennwort-1"}
    )
    assert fertig.status_code == 201, fertig.text

    # ⚠️ **Ohne zweiten Faktor** — er ist eine Wahl, keine Pflicht.
    ich = zweiter_klient.get("/api/auth/ich")
    assert ich.status_code == 200
    assert ich.json()["benutzername"] == "anna"
    assert ich.json()["ist_betreiber"] is False
    assert ich.json()["zwei_faktor_aktiv"] is False


def test_derselbe_schluessel_gilt_kein_zweites_mal(klient, zweiter_klient, postausgang):
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    schluessel = _schluessel_aus(postausgang[0][2])

    assert (
        zweiter_klient.post(
            f"/api/einladung/{schluessel}", json={"passwort": "annas-kennwort-1"}
        ).status_code
        == 201
    )
    zweiter_klient.cookies.clear()
    zweite = zweiter_klient.post(
        f"/api/einladung/{schluessel}", json={"passwort": "noch-ein-kennwort"}
    )
    assert zweite.status_code == 400


def test_abgelaufene_einladung_oeffnet_nichts(klient, zweiter_klient, postausgang, db):
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    schluessel = _schluessel_aus(postausgang[0][2])

    zeile = db.query(Einladung).one()
    zeile.laeuft_ab = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    assert zweiter_klient.get(f"/api/einladung/{schluessel}").status_code == 404
    assert (
        zweiter_klient.post(
            f"/api/einladung/{schluessel}", json={"passwort": "annas-kennwort-1"}
        ).status_code
        == 400
    )


def test_ein_erfundener_schluessel_verraet_nichts(klient, zweiter_klient, postausgang):
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    echt = _schluessel_aus(postausgang[0][2])

    erfunden = zweiter_klient.get("/api/einladung/gibtesnicht")
    abgelaufen_wie = zweiter_klient.get(f"/api/einladung/{echt}x")
    # ⚠️ Dieselbe Antwort, egal was schiefging.
    assert erfunden.status_code == abgelaufen_wie.status_code == 404
    assert erfunden.json()["detail"] == abgelaufen_wie.json()["detail"]


def test_ein_zu_kurzes_kennwort_wird_abgewiesen(klient, zweiter_klient, postausgang):
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    schluessel = _schluessel_aus(postausgang[0][2])

    antwort = zweiter_klient.post(f"/api/einladung/{schluessel}", json={"passwort": "kurz"})
    assert antwort.status_code == 400
    assert "passwort_zu_kurz" == antwort.json()["detail"]


def test_der_schluessel_ist_lang_genug_um_nicht_geraten_zu_werden(klient, postausgang):
    """⚠️ **Hier schuetzt die Laenge, nicht die Bremse.**

    Beim ersten Anlauf am 01.09.2026 stand im Kommentar, die Anmeldebremse
    verhindere das Raten. Der Test zeigte, dass sie das nicht tut: Sie zaehlt
    je Kennung, und beim Raten ist jede Kennung eine andere. Ohne
    ``NEXMAIL_CLIENT_IP`` zaehlt sie auch nicht nach Herkunft.

    Ein gemeinsamer Zaehler waere die falsche Antwort — er waere ein billiger
    Weg, das Einladen fuer eine Viertelstunde lahmzulegen. Die richtige ist die
    Schluessellaenge, und die wird hier geprueft.
    """
    einrichten(klient)
    klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "anna@example.com"},
    )
    schluessel = _schluessel_aus(postausgang[0][2])
    # token_urlsafe(32) sind 256 Bit, base64url-kodiert 43 Zeichen.
    assert len(schluessel) >= 40, f"Der Schlüssel ist zu kurz: {len(schluessel)} Zeichen"


def test_derselbe_falsche_schluessel_wird_gebremst(klient, zweiter_klient):
    """Wer denselben falschen Link hundertmal aufruft, wird ausgebremst."""
    einrichten(klient)
    codes = set()
    for _ in range(15):
        codes.add(zweiter_klient.get("/api/einladung/immer-derselbe-falsche").status_code)
        if 429 in codes:
            break
    assert 429 in codes, "Die Bremse greift nicht einmal beim selben Schlüssel."


# --- Entfernen ----------------------------------------------------------- #


def test_umfang_nennt_zahlen_vor_dem_entfernen(klient, db):
    """⚠️ „Wirklich entfernen?" beantwortet man mit Ja, ohne nachzudenken."""
    einrichten(klient)
    person, _ = zweiten_benutzer_anlegen(db)

    antwort = klient.get(f"/api/benutzer/{person.id}/umfang")
    assert antwort.status_code == 200
    assert set(antwort.json()) == {
        "postfaecher",
        "nachrichten",
        "kontakte",
        "regeln",
        "signaturen",
    }


def test_der_betreiber_laesst_sich_nicht_entfernen(klient, db):
    """Danach koennte niemand mehr die Verwaltung oeffnen."""
    einrichten(klient)
    ich = db.query(Benutzer).filter(Benutzer.ist_betreiber.is_(True)).one()

    antwort = klient.delete(f"/api/benutzer/{ich.id}")
    assert antwort.status_code == 400
    assert db.query(Benutzer).count() == 1


def test_entfernen_nimmt_alles_mit(klient, db):
    """⚠️ **Der Waechter ueber die Vollstaendigkeit.**

    Geprueft wird nicht eine Liste von Tabellen, sondern die Regel: Nach dem
    Entfernen darf in **keiner** Tabelle mit ``benutzer_id`` noch eine Zeile
    dieses Benutzers stehen. Eine handgeschriebene Liste altert — wer spaeter
    eine Tabelle dazunimmt, denkt an die Loeschstelle nicht.
    """
    from app.models import Base, Konto, Kontakt

    einrichten(klient)
    person, _ = zweiten_benutzer_anlegen(db)
    ihre_id = person.id

    db.add(Konto(
        benutzer_id=ihre_id, anzeigename="X", adresse="x@example.com",
        imap_server="s", imap_benutzer="x", smtp_server="s", smtp_benutzer="x",
    ))
    db.add(Kontakt(benutzer_id=ihre_id, name="Wer", adresse="wer@example.com"))
    db.commit()

    assert klient.delete(f"/api/benutzer/{ihre_id}").status_code == 204

    reste = {}
    for tabelle in Base.metadata.sorted_tables:
        if "benutzer_id" not in tabelle.columns:
            continue
        anzahl = db.execute(
            tabelle.select().where(tabelle.c.benutzer_id == ihre_id)
        ).rowcount
        uebrig = len(db.execute(tabelle.select().where(tabelle.c.benutzer_id == ihre_id)).all())
        if uebrig:
            reste[tabelle.name] = uebrig
    assert reste == {}, f"Nach dem Entfernen blieben Zeilen liegen: {reste}"
    assert db.query(Benutzer).filter(Benutzer.id == ihre_id).count() == 0


def test_die_eigenen_daten_bleiben_unberuehrt(klient, db):
    """Ein Loeschvorgang, der zu weit greift, faellt erst viel spaeter auf."""
    from app.models import Kontakt

    einrichten(klient)
    ich = db.query(Benutzer).filter(Benutzer.ist_betreiber.is_(True)).one()
    db.add(Kontakt(benutzer_id=ich.id, name="Meiner", adresse="meiner@example.com"))
    person, _ = zweiten_benutzer_anlegen(db)
    db.add(Kontakt(benutzer_id=person.id, name="Ihrer", adresse="ihrer@example.com"))
    db.commit()

    klient.delete(f"/api/benutzer/{person.id}")

    uebrig = db.query(Kontakt).all()
    assert [k.name for k in uebrig] == ["Meiner"]


def test_ein_abgelehnter_empfaenger_sagt_warum(klient, monkeypatch):
    """⚠️ **Der haeufigste Fall, und der mit der nutzlosesten Meldung.**

    Am 01.09.2026 sah ein Tippfehler in der Adresse aus wie „Die Mail liess
    sich nicht absenden" — also wie ein kaputter Postausgang. Der Betreiber
    sucht dann am falschen Ende. Der Server sagt genau, was er nicht mag.
    """
    import smtplib

    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")
        systempost.schreiben(
            db,
            systempost.Postausgang(server="s.example", absender="nexmail@example.com"),
            "geheim",
        )

    class Attrappe:
        def starttls(self, context=None):
            pass

        def login(self, *a):
            pass

        def send_message(self, mail):
            raise smtplib.SMTPRecipientsRefused(
                {"zz@example.com": (550, b"5.1.1 Recipient address rejected")}
            )

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: Attrappe())

    antwort = klient.post(
        "/api/benutzer/einladungen",
        json={"benutzername": "anna", "adresse": "zz@example.com"},
    )
    assert antwort.status_code == 502
    detail = antwort.json()["detail"]
    # ⚠️ **Der Satz des Servers muss durchkommen.** Er steht jetzt als Wert
    # neben der Kennung — „Der Postausgang hat den Empfänger abgelehnt"
    # allein sagt nicht, welchen und warum.
    assert antwort.json()["detail"] == "empfaenger_abgelehnt"
    assert "zz@example.com" in antwort.json()["werte"]["an"]
    assert "Recipient address rejected" in antwort.json()["werte"]["grund"]
    # Und keine Leiche in der Liste.
    assert klient.get("/api/benutzer").json()["einladungen"] == []
