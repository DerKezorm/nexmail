"""Wie eine Mail aussieht, die nexmail selbst verschickt.

⚠️ **Der wichtigste Test hier ist der ueber die nachgeladenen Bilder.** nexmail
klinkt in fremder Post jedes ``<img src="https://…">`` aus, weil es dem
Absender die Oeffnung meldet. Eine eigene Mail, die genau das tut, waere nicht
nur inkonsequent — sie waere in jedem Client mit Bildblocker ein leerer Kasten.
"""

from __future__ import annotations

import re
from email import message_from_bytes

import pytest

from app.services import mailvorlage, systempost
from app.db import SessionLocal, einstellung_schreiben
from conftest import einrichten


@pytest.fixture
def gefangen(monkeypatch):
    """Faengt die fertige Mail ab, statt sie zu verschicken."""
    kasten: list[bytes] = []

    class Attrappe:
        def starttls(self, context=None):
            pass

        def login(self, *a):
            pass

        def send_message(self, mail):
            kasten.append(mail.as_bytes())

        def quit(self):
            pass

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: Attrappe())
    return kasten


def _mail_bauen(gefangen, html: str | None = None):
    with SessionLocal() as db:
        systempost.schreiben(
            db,
            systempost.Postausgang(server="s.example", absender="nexmail@example.com"),
            "geheim",
        )
        systempost.senden(
            db,
            "wer@example.com",
            "Probe",
            "Nur Text.\nMit Link: https://mail.example/einladung/abc\n",
            html
            if html is not None
            else mailvorlage.rahmen(
                ueberschrift="Hallo Anna",
                absaetze=["Ein Satz."],
                knopf=("Kennwort vergeben", "https://mail.example/einladung/abc"),
                fusszeile="Der Link gilt 7 Tage.",
            ),
        )
    return message_from_bytes(gefangen[0])


def test_die_mail_hat_beide_teile(klient, gefangen):
    """⚠️ Ohne Textteil bekaeme ein Nur-Text-Client eine leere Mail."""
    einrichten(klient)
    mail = _mail_bauen(gefangen)

    arten = [t.get_content_type() for t in mail.walk()]
    assert "text/plain" in arten
    assert "text/html" in arten

    # ⚠️ **Die Reihenfolge zaehlt.** In multipart/alternative gilt der letzte
    # Teil als der beste. Steht der Text hinten, sieht niemand die Gestaltung.
    nur_texte = [a for a in arten if a in ("text/plain", "text/html")]
    assert nur_texte.index("text/plain") < nur_texte.index("text/html")


def test_der_link_steht_auch_im_textteil(klient, gefangen):
    """⚠️ Sonst haette eine Vorlesehilfe eine Einladung ohne Weg hinein."""
    einrichten(klient)
    mail = _mail_bauen(gefangen)

    text = next(
        t for t in mail.walk() if t.get_content_type() == "text/plain"
    ).get_payload(decode=True).decode()
    assert "https://mail.example/einladung/abc" in text


def test_kein_bild_wird_von_aussen_nachgeladen(klient, gefangen):
    """⚠️ **Der Kern.** nexmail klinkt in fremder Post genau solche Bilder aus.

    Ein ``<img src="https://…">`` meldet dem Absender die Oeffnung und wird
    von jedem ordentlichen Client blockiert. Eine eigene Mail, die das tut,
    waere inkonsequent **und** im Postfach ein leerer Kasten.
    """
    einrichten(klient)
    mail = _mail_bauen(gefangen)

    html = next(
        t for t in mail.walk() if t.get_content_type() == "text/html"
    ).get_payload(decode=True).decode()

    quellen = re.findall(r'<img[^>]+src="([^"]+)"', html, re.IGNORECASE)
    assert quellen, "Die Mail hat gar kein Bild — dann fehlt das Logo."
    fremd = [q for q in quellen if not q.startswith("cid:")]
    assert fremd == [], f"Bilder, die von aussen geholt werden: {fremd}"


def test_das_logo_haengt_wirklich_an(klient, gefangen):
    einrichten(klient)
    mail = _mail_bauen(gefangen)

    bilder = [t for t in mail.walk() if t.get_content_type() == "image/png"]
    assert len(bilder) == 1, "Das Logo liegt nicht als Anhang in der Mail."
    assert bilder[0].get("Content-ID") == f"<{mailvorlage.LOGO_KENNUNG}>"
    assert len(bilder[0].get_payload(decode=True)) > 500


def test_keine_stylesheets_und_keine_skripte(klient, gefangen):
    """⚠️ Gmail wirft ``<style>`` teilweise weg, Outlook rendert mit Word.

    Was nicht in jedem Element steht, steht nirgends — und ein ``<script>``
    in einer Mail ist ohnehin nur ein Grund, sie im Spam zu sortieren.
    """
    einrichten(klient)
    mail = _mail_bauen(gefangen)
    html = next(
        t for t in mail.walk() if t.get_content_type() == "text/html"
    ).get_payload(decode=True).decode()

    assert "<script" not in html.lower()
    assert "<style" not in html.lower()
    # Die Gestaltung haengt an den Elementen selbst.
    assert html.count("style=") > 8


def test_fremder_text_wird_entschaerft(klient, gefangen):
    """⚠️ Der Anzeigename kommt aus einem Formular.

    Wer ihn ungeprueft in HTML setzt, hat eine Einladung, die sich von aussen
    umbauen laesst — Knopf woandershin, Text ausgetauscht.
    """
    einrichten(klient)
    html = mailvorlage.rahmen(
        ueberschrift='Hallo <script>alert(1)</script> & "Anna"',
        absaetze=["Ein Satz."],
        knopf=("Los", "https://mail.example/x"),
        fusszeile="Fuss.",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_ohne_logodatei_geht_die_mail_trotzdem(klient, gefangen, monkeypatch):
    """⚠️ Eine Einladung, die an einer fehlenden Datei scheitert, waere das
    schlechteste Ergebnis von allen."""
    from pathlib import Path

    einrichten(klient)
    monkeypatch.setattr(mailvorlage, "LOGO", Path("gibtesnicht.png"))
    mail = _mail_bauen(gefangen)

    arten = [t.get_content_type() for t in mail.walk()]
    assert "text/html" in arten
    assert "image/png" not in arten


def test_die_einladungsmail_traegt_knopf_und_logo(klient, gefangen):
    """Der ganze Weg: Was ``einladung.verschicken`` baut, nicht nur die Vorlage."""
    from app.services import einladung as einladungsdienst

    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example")
        systempost.schreiben(
            db,
            systempost.Postausgang(server="s.example", absender="nexmail@example.com"),
            "geheim",
        )
        gebot, schluessel = einladungsdienst.aussprechen(
            db, benutzername="anna", adresse="anna@example.com", anzeigename="Anna"
        )
        einladungsdienst.verschicken(db, gebot, schluessel, "https://mail.example")

    mail = message_from_bytes(gefangen[0])
    html = next(
        t for t in mail.walk() if t.get_content_type() == "text/html"
    ).get_payload(decode=True).decode()

    assert f"https://mail.example/einladung/{schluessel}" in html
    assert "Kennwort vergeben" in html
    assert 'src="cid:' in html
    assert "image/png" in [t.get_content_type() for t in mail.walk()]
