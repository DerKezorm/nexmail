"""Die Abwesenheitsnotiz — die einzige Stelle, an der nexmail von sich aus
Post an Fremde schickt.

⚠️ **Deshalb steht hier mehr Wache als Funktion.** Drei Katastrophen sind
möglich, und jede hat ihren eigenen Test:

1. **Die Schleife.** Zwei Abwesenheitsnotizen antworten einander, bis jemand
   es merkt.
2. **Der Verteiler.** Eine Notiz an eine Mailingliste geht an alle darauf.
3. **Der Nachzug.** Ein Neustart holt drei Wochen Post und beantwortet sie
   rückwirkend — auf einen Schlag, an alle.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import Abwesenheitsantwort, Konto, Nachricht, Ordner
from app.services import abwesenheit, anbieter, konten
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from test_konten import _eingabe, _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="": _guter_befund())
    yield


def _kopf(**zeilen: str) -> bytes:
    """Ein Kopfzeilen-Block, wie ihn der Server auf BODY[HEADER.FIELDS] gibt."""
    roh = "".join(f"{name.replace('_', '-')}: {wert}\r\n" for name, wert in zeilen.items())
    return (roh + "\r\n").encode()


def _konto(adresse: str = "ich@example.com") -> Konto:
    return Konto(
        id="k1",
        benutzer_id="b1",
        anzeigename="Privat",
        adresse=adresse,
        imap_server="imap.example.com",
        imap_benutzer=adresse,
        smtp_server="smtp.example.com",
        smtp_benutzer=adresse,
        abwesenheit_aktiv=True,
        abwesenheit_text="Bin weg.",
    )


def _nachricht(von: str = "fremd@example.org", **rest) -> Nachricht:
    return Nachricht(
        benutzer_id="b1",
        konto_id="k1",
        ordner_id=1,
        uid=1,
        betreff="Frage",
        von_adresse=von,
        datum=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
        **rest,
    )


# --- Der Zeitraum --------------------------------------------------------- #


def test_bis_ist_einschliesslich(monkeypatch):
    """⚠️ Wer den 14. einträgt, meint den 14. mit.

    Ein „bis 14." wäre am 14. schon aus — und das merkt man erst, wenn schon
    jemand ohne Antwort dastand.
    """
    k = _konto()
    k.abwesenheit_von, k.abwesenheit_bis = "2026-09-05", "2026-09-14"

    for tag, erwartet in (
        ("2026-09-04", False),
        ("2026-09-05", True),
        ("2026-09-14", True),
        ("2026-09-15", False),
    ):
        monkeypatch.setattr(abwesenheit, "_heute", lambda _z, t=tag: date.fromisoformat(t))
        assert abwesenheit.laeuft(k, "Europe/Berlin") is erwartet, tag


def test_ohne_ende_laeuft_es_weiter(monkeypatch):
    k = _konto()
    k.abwesenheit_von, k.abwesenheit_bis = "2026-09-05", ""
    monkeypatch.setattr(abwesenheit, "_heute", lambda _z: date(2027, 3, 1))
    assert abwesenheit.laeuft(k, "Europe/Berlin") is True


def test_ausgeschaltet_laeuft_nie(monkeypatch):
    k = _konto()
    k.abwesenheit_aktiv = False
    monkeypatch.setattr(abwesenheit, "_heute", lambda _z: date(2026, 9, 10))
    assert abwesenheit.laeuft(k, "Europe/Berlin") is False


# --- Der Schleifenschutz -------------------------------------------------- #


@pytest.mark.parametrize(
    "kopfzeilen,grund",
    [
        ({"Auto_Submitted": "auto-replied"}, "automat"),
        ({"Auto_Submitted": "auto-generated"}, "automat"),
        ({"X_Autoreply": "yes"}, "automat"),
        ({"X_Autoresponder": "urlaub"}, "automat"),
        ({"List_Id": "<liste.example.org>"}, "verteiler"),
        ({"List_Unsubscribe": "<mailto:weg@example.org>"}, "verteiler"),
        ({"List_Post": "<mailto:liste@example.org>"}, "verteiler"),
        ({"Precedence": "bulk"}, "massenpost"),
        ({"Precedence": "list"}, "massenpost"),
        ({"Precedence": "junk"}, "massenpost"),
        ({"Return_Path": "<>"}, "unzustellbarkeit"),
    ],
)
def test_worauf_nie_geantwortet_wird(kopfzeilen, grund):
    """⚠️ Jede dieser Zeilen steht für eine Schleife oder einen Verteiler."""
    k = _konto()
    n = _nachricht()
    kopf = _kopf(To="ich@example.com", **kopfzeilen)
    assert abwesenheit.antwort_faellig(k, n, kopf, set()) == grund


def test_auf_gewoehnliche_post_wird_geantwortet():
    k = _konto()
    n = _nachricht()
    kopf = _kopf(To="ich@example.com", Auto_Submitted="no")
    assert abwesenheit.antwort_faellig(k, n, kopf, set()) is None


def test_jeder_absender_nur_einmal():
    k = _konto()
    n = _nachricht("fremd@example.org")
    kopf = _kopf(To="ich@example.com")
    assert abwesenheit.antwort_faellig(k, n, kopf, set()) is None
    assert (
        abwesenheit.antwort_faellig(k, n, kopf, {"fremd@example.org"}) == "schon_beantwortet"
    )


def test_gross_und_kleinschreibung_hilft_der_schleife_nicht():
    """Sonst genügt ein „Fremd@…", um ein zweites Mal zu antworten."""
    k = _konto()
    n = _nachricht("Fremd@Example.ORG")
    kopf = _kopf(To="ich@example.com")
    assert (
        abwesenheit.antwort_faellig(k, n, kopf, {"fremd@example.org"}) == "schon_beantwortet"
    )


def test_sich_selbst_antwortet_niemand():
    k = _konto()
    n = _nachricht("ICH@example.com")
    assert abwesenheit.antwort_faellig(k, n, _kopf(To="ich@example.com"), set()) == "eigene_adresse"


def test_verteilerpost_ohne_die_eigene_adresse_bleibt_unbeantwortet():
    """⚠️ Steht die eigene Adresse weder in To noch in Cc, ist es Verteilerpost.

    Darauf antwortet man nicht — die Notiz ginge an einen, der einen gar
    nicht angeschrieben hat.
    """
    k = _konto()
    n = _nachricht()
    kopf = _kopf(To="wer.anders@example.org", Cc="noch.wer@example.org")
    assert abwesenheit.antwort_faellig(k, n, kopf, set()) == "nicht_an_mich"


def test_in_kopie_zaehlt_als_an_mich():
    k = _konto()
    n = _nachricht()
    kopf = _kopf(To="wer.anders@example.org", Cc="Ich <ich@example.com>")
    assert abwesenheit.antwort_faellig(k, n, kopf, set()) is None


# --- Die Notiz selbst ----------------------------------------------------- #


def test_die_notiz_kennzeichnet_sich_als_automat():
    """⚠️ Ohne diese Kopfzeilen antwortet der Automat auf der Gegenseite zurück."""
    from app.services import verfassen

    k = _konto()
    entwurf = abwesenheit.notiz_bauen(k, _nachricht(), "<abc@example.org>")
    assert entwurf.auto_antwort is True
    roh, _ = verfassen.bauen(entwurf)
    kopf = roh.split(b"\r\n\r\n", 1)[0].decode().lower()
    assert "auto-submitted: auto-replied" in kopf
    assert "x-auto-response-suppress: all" in kopf
    assert "precedence: auto_reply" in kopf


def test_die_notiz_ist_reiner_text():
    """Formatierte Post an Fremde, die niemand gegenliest, ist eine
    Fehlerquelle ohne Gewinn."""
    k = _konto()
    assert abwesenheit.notiz_bauen(k, _nachricht()).html == ""


# --- Der ganze Weg -------------------------------------------------------- #


class FalscherKlient:
    """Gibt für jede UID denselben Kopfzeilen-Block zurück."""

    def __init__(self, kopf: bytes):
        self.kopf = kopf

    def fetch(self, uids, felder):
        schluessel = f"BODY[HEADER.FIELDS ({abwesenheit.KOPFZEILEN})]".encode()
        return {u: {schluessel: self.kopf} for u in uids}


def _welt(klient, monkeypatch, tage_zurueck: int = 0):
    """Ein Postfach mit Posteingang, Abwesenheit an, heute im Zeitraum."""
    konto_id = klient.post("/api/konten", json=_eingabe("weg@beispiel.example")).json()["id"]
    heute = date(2026, 9, 10)
    monkeypatch.setattr(abwesenheit, "_heute", lambda _z: heute)
    with SessionLocal() as db:
        konto = db.get(Konto, konto_id)
        konto.abwesenheit_aktiv = True
        konto.abwesenheit_von = (heute - timedelta(days=tage_zurueck)).isoformat()
        konto.abwesenheit_text = "Bin bis Montag weg."
        db.commit()
    return konto_id, heute


def _einwerfen(konto_id: str, rolle: str, von: str, wann: datetime) -> int:
    with SessionLocal() as db:
        ordner = (
            db.query(Ordner).filter(Ordner.konto_id == konto_id, Ordner.rolle == rolle).one()
        )
        n = Nachricht(
            benutzer_id=ordner.konto.benutzer_id,
            konto_id=konto_id,
            ordner_id=ordner.id,
            uid=int(wann.timestamp()) % 100000,
            betreff="Frage",
            von_adresse=von,
            datum=wann,
            message_id="<abc@example.org>",
        )
        db.add(n)
        db.commit()
        return n.id


def _erledigen(konto_id: str, rolle: str, kopf: bytes) -> int:
    with SessionLocal() as db:
        konto = db.get(Konto, konto_id)
        ordner = (
            db.query(Ordner).filter(Ordner.konto_id == konto_id, Ordner.rolle == rolle).one()
        )
        neue = db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id).all()
        return abwesenheit.erledigen(FalscherKlient(kopf), db, konto, ordner, neue)


def test_auf_neue_post_geht_eine_notiz_hinaus(klient, ohne_netz, monkeypatch):
    einrichten(klient)
    konto_id, heute = _welt(klient, monkeypatch)
    _einwerfen(konto_id, "posteingang", "fremd@example.org", datetime(2026, 9, 10, 9, tzinfo=timezone.utc))

    verschickt = _erledigen(konto_id, "posteingang", _kopf(To="weg@beispiel.example"))
    assert verschickt == 1

    with SessionLocal() as db:
        gemerkt = db.query(Abwesenheitsantwort).all()
        assert [z.adresse for z in gemerkt] == ["fremd@example.org"]


def test_zweimal_derselbe_absender_gibt_eine_notiz(klient, ohne_netz, monkeypatch):
    einrichten(klient)
    konto_id, _ = _welt(klient, monkeypatch)
    for stunde in (9, 10):
        _einwerfen(
            konto_id, "posteingang", "fremd@example.org",
            datetime(2026, 9, 10, stunde, tzinfo=timezone.utc),
        )
    assert _erledigen(konto_id, "posteingang", _kopf(To="weg@beispiel.example")) == 1


def test_ausserhalb_des_posteingangs_wird_nicht_geantwortet(klient, ohne_netz, monkeypatch):
    """⚠️ Nur der Posteingang.

    Was eine Regel schon weggeräumt hat oder was im Papierkorb liegt, verlangt
    keine Antwort — und wer auf Junk antwortet, bestätigt dem Absender sogar
    die Adresse.
    """
    einrichten(klient)
    konto_id, _ = _welt(klient, monkeypatch)
    _einwerfen(
        konto_id, "papierkorb", "spam@example.org",
        datetime(2026, 9, 10, 9, tzinfo=timezone.utc),
    )
    assert _erledigen(konto_id, "papierkorb", _kopf(To="weg@beispiel.example")) == 0


def test_alte_post_wird_nicht_rueckwirkend_beantwortet(klient, ohne_netz, monkeypatch):
    """⚠️ **Die dritte Katastrophe.**

    Ein Neustart holt drei Wochen Post nach. Ohne diese Wache bekäme jeder
    Absender daraus eine Abwesenheitsnotiz, auf einen Schlag.
    """
    einrichten(klient)
    konto_id, _ = _welt(klient, monkeypatch)
    _einwerfen(
        konto_id, "posteingang", "alt@example.org",
        datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
    )
    assert _erledigen(konto_id, "posteingang", _kopf(To="weg@beispiel.example")) == 0


def test_ausserhalb_des_zeitraums_geht_nichts_hinaus(klient, ohne_netz, monkeypatch):
    einrichten(klient)
    konto_id, heute = _welt(klient, monkeypatch)
    with SessionLocal() as db:
        konto = db.get(Konto, konto_id)
        konto.abwesenheit_bis = (heute - timedelta(days=1)).isoformat()
        db.commit()
    _einwerfen(
        konto_id, "posteingang", "fremd@example.org",
        datetime(2026, 9, 10, 9, tzinfo=timezone.utc),
    )
    assert _erledigen(konto_id, "posteingang", _kopf(To="weg@beispiel.example")) == 0


# --- Die Adressen --------------------------------------------------------- #


def test_einschalten_ohne_text_wird_abgewiesen(klient, ohne_netz):
    """Eine leere Abwesenheitsnotiz ist schlimmer als keine: Der Empfänger
    denkt, er habe etwas kaputtgemacht."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("weg@beispiel.example")).json()["id"]
    antwort = klient.put(
        f"/api/abwesenheit/{konto_id}", json={"aktiv": True, "text": "   "}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "abwesenheit_ohne_text"


def test_verdrehter_zeitraum_wird_abgewiesen(klient, ohne_netz):
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("weg@beispiel.example")).json()["id"]
    antwort = klient.put(
        f"/api/abwesenheit/{konto_id}",
        json={"aktiv": True, "text": "weg", "von": "2026-09-14", "bis": "2026-09-05"},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "abwesenheit_zeitraum_verdreht"


def test_einschalten_leert_die_merkliste(klient, ohne_netz):
    """⚠️ „Einmal" gilt je Abwesenheit, nicht je Lebenszeit des Postfachs."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("weg@beispiel.example")).json()["id"]
    with SessionLocal() as db:
        db.add(Abwesenheitsantwort(konto_id=konto_id, adresse="alt@example.org"))
        db.commit()

    klient.put(f"/api/abwesenheit/{konto_id}", json={"aktiv": True, "text": "Bin weg."})
    with SessionLocal() as db:
        assert db.query(Abwesenheitsantwort).count() == 0


def test_nachbessern_waehrend_der_abwesenheit_leert_nichts(klient, ohne_netz):
    """Sonst bekämen alle ein zweites Mal eine Notiz, nur weil ein Komma fehlte."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("weg@beispiel.example")).json()["id"]
    klient.put(f"/api/abwesenheit/{konto_id}", json={"aktiv": True, "text": "Bin weg."})
    with SessionLocal() as db:
        db.add(Abwesenheitsantwort(konto_id=konto_id, adresse="wer@example.org"))
        db.commit()

    klient.put(f"/api/abwesenheit/{konto_id}", json={"aktiv": True, "text": "Bin bis Montag weg."})
    with SessionLocal() as db:
        assert db.query(Abwesenheitsantwort).count() == 1


def test_fremde_postfaecher_bleiben_zu(klient, zweiter_klient, db, ohne_netz):
    """⚠️ Die Trennung wird gegen einen ZWEITEN Benutzer geprüft, nicht behauptet."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("weg@beispiel.example")).json()["id"]

    person, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, person.benutzername, "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.put(
        f"/api/abwesenheit/{konto_id}", json={"aktiv": True, "text": "Bin weg."}
    )
    assert antwort.status_code == 404
    # Und in seiner eigenen Liste steht das fremde Postfach auch nicht.
    assert zweiter_klient.get("/api/abwesenheit").json() == []
