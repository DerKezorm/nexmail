"""Die Druckansicht einer Nachricht.

⚠️ **Warum hier so misstrauisch geprüft wird:** Das Druckdokument rendert
unter nexmails eigener Herkunft, nicht im abgeschotteten Rahmen des
Lesebereichs. Was dort durchkäme, liefe hier als Code der Anwendung. Deshalb
wird nicht nur geprüft, dass der Betreff ankommt, sondern vor allem, dass ein
vergifteter Bestand — eine ältere Datenbank, eine fremde Sicherung — nicht
zu ausführbarem Inhalt wird.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db import SessionLocal
from app.models import Anhang, Nachricht, Ordner
from app.services import anbieter, konten
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from test_konten import _eingabe, _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="": _guter_befund())
    yield


def _mail_anlegen(
    klient,
    html: str = "<p>Der Inhalt der Mail.</p>",
    text: str = "",
    betreff: str = "Rechnung Neunzehn",
    anhang_name: str = "",
) -> int:
    """Ein Postfach anlegen und eine Mail mit geholtem Körper hineinlegen.

    ⚠️ ``koerper_geholt`` ist gesetzt — sonst versuchte die Route, den Körper
    per IMAP nachzuholen, und der Test prüfte eine Verbindung statt des
    Dokuments.
    """
    konto_id = klient.post("/api/konten", json=_eingabe("druck@beispiel.example")).json()["id"]
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        nachricht = Nachricht(
            benutzer_id=posteingang.konto.benutzer_id,
            konto_id=konto_id,
            ordner_id=posteingang.id,
            uid=1,
            betreff=betreff,
            von_name="Absenderin",
            von_adresse="absenderin@example.com",
            an_json='[{"n": "Empfaenger", "a": "empfaenger@example.com"}]',
            kopie_json='[{"n": "", "a": "kopie@example.com"}]',
            datum=datetime(2026, 3, 5, 12, 30, tzinfo=timezone.utc),
            koerper_html=html,
            koerper_text=text,
            koerper_geholt=datetime.now(timezone.utc),
        )
        db.add(nachricht)
        db.flush()
        if anhang_name:
            db.add(
                Anhang(
                    nachricht_id=nachricht.id,
                    dateiname=anhang_name,
                    mime="application/pdf",
                    groesse=1234,
                )
            )
        db.commit()
        return nachricht.id


def test_die_druckseite_traegt_betreff_und_kopf(klient, ohne_netz):
    einrichten(klient)
    kennung = _mail_anlegen(klient, anhang_name="vertrag.pdf")

    antwort = klient.get(f"/api/nachrichten/{kennung}/druck")
    assert antwort.status_code == 200, antwort.text
    assert antwort.headers["content-type"].startswith("text/html")

    rumpf = antwort.text
    assert "Rechnung Neunzehn" in rumpf
    assert "absenderin@example.com" in rumpf
    assert "empfaenger@example.com" in rumpf
    assert "kopie@example.com" in rumpf
    assert "Der Inhalt der Mail." in rumpf
    # Der Anhangsname steht als Zeile im Kopf — der Ausdruck soll sagen,
    # was zur Mail gehörte, auch wenn es nicht mitgedruckt werden kann.
    assert "vertrag.pdf" in rumpf


def test_ein_vergifteter_bestand_wird_trotzdem_bereinigt(klient, ohne_netz):
    """⚠️ Der wichtigste Test der Gruppe — und der mit der Mutationsprobe.

    ``koerper_html`` ist bereinigt gespeichert; dieser Test legt trotzdem
    Gift hinein, wie es eine ältere Fassung oder eine fremde Sicherung
    hinterlassen könnte. Die Route muss selbst noch einmal säubern: Das
    Dokument rendert unter der eigenen Herkunft, ein ``<script>`` darin wäre
    Code der Anwendung.
    """
    einrichten(klient)
    kennung = _mail_anlegen(
        klient,
        html=(
            "<p>Harmlos</p>"
            "<script>alert('drin')</script>"
            '<img src="https://boese.example/pixel.gif" onerror="alert(2)">'
        ),
    )

    rumpf = klient.get(f"/api/nachrichten/{kennung}/druck").text
    assert "Harmlos" in rumpf
    assert "<script" not in rumpf
    assert "onerror=" not in rumpf
    # Und die Bildadresse bleibt ausgeklinkt: Der Browser, der das Dokument
    # lädt, darf sie gar nicht erst sehen.
    assert "boese.example" not in rumpf


def test_die_seite_selbst_bringt_kein_script_mit(klient, ohne_netz):
    """Auch das eigene Gerüst ist skriptfrei — drucken stößt die Oberfläche an."""
    einrichten(klient)
    kennung = _mail_anlegen(klient)

    antwort = klient.get(f"/api/nachrichten/{kennung}/druck")
    assert "<script" not in antwort.text
    assert "default-src 'none'" in antwort.headers["content-security-policy"]


def test_ohne_html_kommt_der_text_entschaerft(klient, ohne_netz):
    """Der Nur-Text-Rückfall wird entschärft, nicht als Markup gedeutet."""
    einrichten(klient)
    kennung = _mail_anlegen(klient, html="", text="Zeile mit <b>spitzen</b> Klammern")

    rumpf = klient.get(f"/api/nachrichten/{kennung}/druck").text
    assert "&lt;b&gt;spitzen&lt;/b&gt;" in rumpf
    assert "<b>spitzen</b>" not in rumpf


def test_ein_verlogener_bildtyp_wird_nicht_eingebettet(klient, ohne_netz):
    """⚠️ **Der Injektionspunkt hinter der Bereinigung.**

    ``get_content_type()`` reicht ``image/png" onerror="alert(1)`` wörtlich
    durch, und ``cid_einsetzen`` schreibt den Typ unmaskiert in ein
    ``src``-Attribut — **nach** ``fuer_druck``, die nh3-Bereinigung sieht das
    Attribut also nie. Deshalb kommt nur ein streng geprüfter Medientyp in
    die Einbettung; ein echtes Bild muss trotzdem ankommen.
    """
    from app.config import get_settings

    einrichten(klient)
    kennung = _mail_anlegen(
        klient,
        html='<p>Echt: <img src="cid:gut"> Boese: <img src="cid:schlecht"></p>',
    )

    blob_dir = get_settings().blob_dir
    blob_dir.mkdir(parents=True, exist_ok=True)
    (blob_dir / ("aa" * 32)).write_bytes(b"\x89PNGecht")
    (blob_dir / ("bb" * 32)).write_bytes(b"\x89PNGboese")
    with SessionLocal() as db:
        nachricht_id = kennung
        db.add(
            Anhang(
                nachricht_id=nachricht_id,
                dateiname="gut.png",
                mime="image/png",
                groesse=8,
                cid="gut",
                blob_hash="aa" * 32,
            )
        )
        db.add(
            Anhang(
                nachricht_id=nachricht_id,
                dateiname="schlecht.png",
                mime='image/png" onerror="alert(1)',
                groesse=9,
                cid="schlecht",
                blob_hash="bb" * 32,
            )
        )
        db.commit()

    rumpf = klient.get(f"/api/nachrichten/{kennung}/druck").text

    # Das ehrliche Bild ist eingebettet …
    assert "data:image/png;base64," in rumpf
    # … der gelogene Typ kommt nirgends unter — weder als Attribut noch als Text.
    assert "onerror" not in rumpf


def test_ein_fremder_benutzer_bekommt_404(klient, zweiter_klient, ohne_netz, db):
    einrichten(klient)
    kennung = _mail_anlegen(klient)

    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.get(f"/api/nachrichten/{kennung}/druck")
    assert antwort.status_code == 404


def test_ohne_anmeldung_401(klient, ohne_netz):
    einrichten(klient)
    kennung = _mail_anlegen(klient)

    klient.cookies.clear()
    antwort = klient.get(f"/api/nachrichten/{kennung}/druck")
    assert antwort.status_code == 401
