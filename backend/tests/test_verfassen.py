"""Schreiben: bauen, zitieren, senden, in der Warteschlange behalten.

⚠️ **Nichts hier geht ins Netz.** SMTP wird ersetzt, IMAP ebenfalls.
"""

from __future__ import annotations

import json
from email import message_from_bytes

import pytest

from sqlalchemy import select

from app.models import Ausgang, Nachricht, Ordner
from app.services import mime, senden, verfassen
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


def _entwurf(**anders) -> verfassen.Entwurf:
    grund = dict(
        von_name="Anna Beispiel",
        von_adresse="anna@icloud.example",
        an=["anja@example.org"],
        betreff="Wochenende",
        html="<p>Passt bei mir.</p>",
    )
    grund.update(anders)
    return verfassen.Entwurf(**grund)


def _gelesen(roh: bytes):
    return message_from_bytes(roh)


# --- Bauen --------------------------------------------------------------- #


def test_grundgeruest():
    roh, kennung = verfassen.bauen(_entwurf())
    m = _gelesen(roh)

    assert m["To"] == "anja@example.org"
    assert m["Subject"] == "Wochenende"
    assert m["Message-ID"] == kennung
    assert "Anna Beispiel" in m["From"]
    assert m.is_multipart()


def test_text_und_html_liegen_beide_bei():
    """Ein Empfänger ohne HTML-Anzeige soll trotzdem etwas sehen."""
    roh, _ = verfassen.bauen(_entwurf(html="<p>Hallo <b>Welt</b></p>"))
    typen = {t.get_content_type() for t in _gelesen(roh).walk()}

    assert "text/plain" in typen
    assert "text/html" in typen


def test_html_wird_beim_senden_bereinigt():
    """⚠️ In beide Richtungen.

    Eine weitergeleitete Mail trägt fremdes HTML in den eigenen Entwurf — dass
    es aus dem eigenen Fenster kommt, macht es nicht harmlos.
    """
    boese = '<p>Text</p><script>alert(1)</script><img src=x onerror=alert(1)>'
    roh, _ = verfassen.bauen(_entwurf(html=boese))
    text = roh.decode("utf-8", errors="replace").lower()

    assert "<script" not in text
    assert "onerror" not in text
    assert "text" in text


def test_blindkopie_steht_in_keiner_kopfzeile():
    """⚠️ Sonst war „blind" nie blind."""
    roh, _ = verfassen.bauen(_entwurf(blindkopie=["heimlich@example.org"]))
    m = _gelesen(roh)

    assert m["Bcc"] is None
    assert "heimlich@example.org" not in roh.decode("utf-8", errors="replace")


def test_kopie_steht_sehr_wohl_drin():
    roh, _ = verfassen.bauen(_entwurf(kopie=["sabine@example.org"]))
    assert _gelesen(roh)["Cc"] == "sabine@example.org"


def test_kette_wird_gesetzt():
    """⚠️ Ohne In-Reply-To und References hängt die Antwort an keinem Strang."""
    roh, _ = verfassen.bauen(
        _entwurf(in_reply_to="<zwei@x.example>", references=["<eins@x.example>", "<zwei@x.example>"])
    )
    m = _gelesen(roh)

    assert m["In-Reply-To"] == "<zwei@x.example>"
    assert "<eins@x.example>" in m["References"]
    assert "<zwei@x.example>" in m["References"]


def test_anhang():
    roh, _ = verfassen.bauen(
        _entwurf(
            anlagen=[
                verfassen.Anlage("Rechnung.pdf", "application/pdf", b"%PDF-1.4 test")
            ]
        )
    )
    namen = [t.get_filename() for t in _gelesen(roh).walk() if t.get_filename()]
    assert "Rechnung.pdf" in namen


def test_inline_bild_bekommt_eine_cid():
    """Ein eingefügtes Bildschirmfoto steht im Text, nicht als Anhang darunter."""
    roh, _ = verfassen.bauen(
        _entwurf(
            html='<p>Siehe <img src="cid:bild1"></p>',
            anlagen=[verfassen.Anlage("bild.png", "image/png", b"\x89PNG", cid="bild1")],
        )
    )
    m = _gelesen(roh)
    kennungen = [t.get("Content-ID") for t in m.walk() if t.get("Content-ID")]
    assert "<bild1>" in kennungen


# --- Antworten ----------------------------------------------------------- #


def _eingehend(von="anja@example.org", an=None, kopie=None) -> mime.Zerlegt:
    zeilen = [
        f"From: Anja Kessler <{von}>",
        f"To: {', '.join(an or ['anna@icloud.example'])}",
        "Subject: Wochenende am See",
        "Message-ID: <urspruenglich@x.example>",
        "Date: Mon, 31 Aug 2026 09:14:00 +0200",
    ]
    if kopie:
        zeilen.append(f"Cc: {', '.join(kopie)}")
    roh = ("\r\n".join(zeilen) + "\r\n\r\nWollen wir um elf?\r\n").encode()
    return mime.zerlegen(roh)


def test_antwort_geht_an_den_absender():
    an, kopie = verfassen.antwort_empfaenger(
        _eingehend(), {"anna@icloud.example"}, allen=False
    )
    assert an == ["anja@example.org"]
    assert kopie == []


def test_allen_antworten_nimmt_alle_mit_ausser_mir():
    """⚠️ Die eigene Adresse fliegt heraus.

    Sonst schickt man sich bei jedem „Allen antworten" eine Kopie an sich
    selbst — und in einem Verteiler verdoppelt sich das mit jeder Runde.
    """
    eingehend = _eingehend(
        an=["anna@icloud.example", "tobias@example.org"],
        kopie=["sabine@example.org", "anna@icloud.example"],
    )
    an, kopie = verfassen.antwort_empfaenger(eingehend, {"anna@icloud.example"}, allen=True)

    assert "anja@example.org" in an
    assert "tobias@example.org" in an
    assert "anna@icloud.example" not in an
    assert "anna@icloud.example" not in kopie
    assert kopie == ["sabine@example.org"]


@pytest.mark.parametrize(
    "betreff,erwartet",
    [
        ("Wochenende", "AW: Wochenende"),
        ("AW: Wochenende", "AW: Wochenende"),
        ("Re: Wochenende", "AW: Wochenende"),
        ("WG: AW: Wochenende", "AW: Wochenende"),
    ],
)
def test_antwortbetreff_verdoppelt_nichts(betreff, erwartet):
    assert verfassen.antwort_betreff(betreff) == erwartet


def test_kette_waechst_und_wird_nicht_ersetzt():
    """⚠️ Wer nur die letzte Kennung einträgt, reißt den Strang beim dritten
    Hin und Her ab."""
    roh = (
        b"From: a@b.example\r\nSubject: Re: X\r\n"
        b"Message-ID: <drei@x.example>\r\n"
        b"References: <eins@x.example> <zwei@x.example>\r\n\r\nText\r\n"
    )
    kette = verfassen.references_fuer_antwort(mime.zerlegen(roh))
    assert kette == ["<eins@x.example>", "<zwei@x.example>", "<drei@x.example>"]


def test_lange_kette_behaelt_die_wurzel():
    """Sie hält den Strang zusammen — die Mitte tut es nicht."""
    viele = " ".join(f"<n{i}@x.example>" for i in range(40))
    roh = (
        f"From: a@b.example\r\nSubject: X\r\nMessage-ID: <letzte@x.example>\r\n"
        f"References: {viele}\r\n\r\nText\r\n"
    ).encode()
    kette = verfassen.references_fuer_antwort(mime.zerlegen(roh))

    assert len(kette) <= 20
    assert kette[0] == "<n0@x.example>"
    assert kette[-1] == "<letzte@x.example>"


def test_zitat_wird_bereinigt():
    """⚠️ Das Zitat ist fremdes HTML, auch im eigenen Entwurf."""
    roh = (
        b"From: a@b.example\r\nSubject: X\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>Hallo</p><script>alert(1)</script>\r\n"
    )
    html = verfassen.zitat_html(mime.zerlegen(roh))
    assert "<script" not in html.lower()
    assert "Hallo" in html
    assert "<blockquote" in html


def test_weiterleitung_traegt_den_kopfblock():
    html = verfassen.weiterleitung_html(_eingehend())
    assert "Weitergeleitete Nachricht" in html
    assert "anja@example.org" in html
    assert "Wochenende am See" in html


# --- Senden und Warteschlange -------------------------------------------- #


class FalscherSmtp:
    def __init__(self):
        self.gesendet: list[tuple[str, list[str], bytes]] = []
        self.scheitert = False

    def __call__(self, konto, passwort, empfaenger, roh):  # noqa: ARG002
        if self.scheitert:
            raise RuntimeError("Der Server nimmt gerade nichts an.")
        self.gesendet.append((konto.adresse, empfaenger, roh))


@pytest.fixture
def postausgang(db, konto, monkeypatch):  # noqa: F811
    db.add(Ordner(konto_id=konto.id, pfad="Sent Messages", name="Sent", rolle="gesendet"))
    db.commit()
    db.refresh(konto)

    server = FalscherServer()
    server.anlegen("INBOX")
    server.anlegen("Sent Messages")
    server.abgelegt: list = []

    def append(pfad, roh, flags, zeitpunkt):  # noqa: ARG001
        server.abgelegt.append((pfad, roh))
        # ⚠️ Der Doppelgänger muss die Mail auch wirklich **haben**, nicht
        # nur ihren Empfang quittieren. Sonst prüft der Test den Abgleich
        # danach gegen einen leeren Ordner und besteht hohl.
        server.einwerfen(pfad, len(server.abgelegt), "AW: TEST", gelesen=True, roh=roh)

    server.append = append

    smtp = FalscherSmtp()
    monkeypatch.setattr(senden, "_smtp_senden", smtp)
    monkeypatch.setattr(senden.imapdienst, "verbinden", lambda *a, **k: server)
    return konto, smtp, server


def test_senden_legt_in_gesendet_ab(db, postausgang):
    """⚠️ Ohne APPEND sieht es auf dem Telefon aus, als hätte man nie geantwortet."""
    konto, smtp, server = postausgang

    zeile = senden.einreihen(db, konto, _entwurf())
    senden.versenden(db, zeile)

    assert len(smtp.gesendet) == 1
    assert zeile.stand == "gesendet"
    assert len(server.abgelegt) == 1
    assert server.abgelegt[0][0] == "Sent Messages"


def test_blindkopie_bekommt_die_mail_trotzdem(db, postausgang):
    """Die Empfängerliste kommt beim Versand mit, nicht aus den Kopfzeilen."""
    konto, smtp, _ = postausgang

    zeile = senden.einreihen(db, konto, _entwurf(blindkopie=["heimlich@example.org"]))
    senden.versenden(db, zeile)

    _, empfaenger, roh = smtp.gesendet[0]
    assert "heimlich@example.org" in empfaenger
    assert "heimlich@example.org" not in roh.decode("utf-8", errors="replace")


def test_gescheiterter_versand_bleibt_liegen(db, postausgang):
    """⚠️ Die Mail ist nicht weg — sie liegt im Ausgang."""
    konto, smtp, _ = postausgang
    smtp.scheitert = True

    zeile = senden.einreihen(db, konto, _entwurf())
    with pytest.raises(senden.SendeFehler):
        senden.versenden(db, zeile)

    db.refresh(zeile)
    assert zeile.stand == "wartet"
    assert zeile.versuche == 1
    assert "nimmt gerade nichts an" in zeile.letzter_fehler
    assert senden._datei(zeile.id).is_file()


def test_warteschlange_wird_nachgeholt(db, postausgang):
    """Genau das rettet die Mail nach einem Neustart."""
    konto, smtp, _ = postausgang
    smtp.scheitert = True

    zeile = senden.einreihen(db, konto, _entwurf())
    with pytest.raises(senden.SendeFehler):
        senden.versenden(db, zeile)

    smtp.scheitert = False
    ergebnis = senden.warteschlange_abarbeiten(db)

    assert ergebnis["gesendet"] == 1
    db.refresh(zeile)
    assert zeile.stand == "gesendet"
    assert not senden._datei(zeile.id).exists()


def test_nach_zu_vielen_versuchen_gescheitert(db, postausgang):
    konto, smtp, _ = postausgang
    smtp.scheitert = True

    zeile = senden.einreihen(db, konto, _entwurf())
    for _ in range(senden.MAX_VERSUCHE):
        with pytest.raises(senden.SendeFehler):
            senden.versenden(db, zeile)

    db.refresh(zeile)
    assert zeile.stand == "gescheitert"
    # ⚠️ Die Datei bleibt liegen: Sie ist der einzige Ort, an dem die Mail
    # noch steht.
    assert senden._datei(zeile.id).is_file()


def test_fehlender_gesendet_ordner_bricht_nichts_ab(db, postausgang):
    """Die Mail ist draußen. Sie fehlt nur in der Ablage."""
    konto, smtp, _ = postausgang
    gesendet = next(o for o in konto.ordner if o.rolle == "gesendet")
    db.delete(gesendet)
    db.commit()
    db.refresh(konto)

    zeile = senden.einreihen(db, konto, _entwurf())
    senden.versenden(db, zeile)

    assert zeile.stand == "gesendet"
    assert len(smtp.gesendet) == 1


def test_verwaiste_dateien_werden_aufgeraeumt(db, postausgang):
    fremd = senden.ausgangsordner() / "gehoert-zu-nichts.eml"
    fremd.write_bytes(b"alt")

    assert senden.aufraeumen(db) == 1
    assert not fremd.exists()


def test_ausgang_ueber_die_schnittstelle(klient, db, postausgang):
    konto, smtp, _ = postausgang
    smtp.scheitert = True
    zeile = senden.einreihen(db, konto, _entwurf(betreff="Bleibt liegen"))
    with pytest.raises(senden.SendeFehler):
        senden.versenden(db, zeile)

    antwort = klient.get("/api/verfassen/ausgang")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert len(daten) == 1
    assert daten[0]["betreff"] == "Bleibt liegen"
    assert daten[0]["stand"] == "wartet"


def test_fremder_ausgang_bleibt_unsichtbar(klient, zweiter_klient, db, postausgang):
    from conftest import anmelden, zweiten_benutzer_anlegen

    konto, smtp, _ = postausgang
    smtp.scheitert = True
    zeile = senden.einreihen(db, konto, _entwurf())
    with pytest.raises(senden.SendeFehler):
        senden.versenden(db, zeile)

    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    assert zweiter_klient.get("/api/verfassen/ausgang").json() == []


def test_senden_ohne_empfaenger_wird_abgelehnt(klient, db, postausgang):
    konto, _, _ = postausgang
    antwort = klient.post(
        "/api/verfassen/senden",
        json={"konto_id": konto.id, "an": [], "betreff": "Leer", "html": "<p>x</p>"},
    )
    assert antwort.status_code == 400
    assert db.query(Ausgang).count() == 0


def test_fremdes_konto_kann_nicht_senden(klient, zweiter_klient, db, postausgang):
    from conftest import anmelden, zweiten_benutzer_anlegen

    konto, _, _ = postausgang
    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    antwort = zweiter_klient.post(
        "/api/verfassen/senden",
        json={"konto_id": konto.id, "an": ["x@y.example"], "betreff": "Fremd", "html": "<p>x</p>"},
    )
    assert antwort.status_code == 404
    assert db.query(Ausgang).count() == 0


def test_gesendetes_steht_sofort_in_gesendet(db, postausgang):
    """⚠️ **Aus Schaden entstanden, 31.08.2026.**

    ``APPEND`` legt die Mail beim Anbieter ab — nicht in nexmails Datenbank.
    Ohne den Abgleich danach blieb „Gesendet“ leer, bis jemand von Hand
    aktualisierte. Der Betreiber hatte geantwortet und seine Antwort nirgends
    gefunden; wer das erlebt, schickt sie ein zweites Mal.
    """
    konto, _, _ = postausgang

    zeile = senden.einreihen(db, konto, _entwurf())
    senden.versenden(db, zeile)

    gesendet = (
        db.execute(select(Ordner).where(Ordner.konto_id == konto.id, Ordner.rolle == "gesendet"))
        .scalars()
        .one()
    )
    liegen = db.execute(select(Nachricht).where(Nachricht.ordner_id == gesendet.id)).scalars().all()

    assert len(liegen) == 1, (
        "Die gesendete Mail steht nicht in der Datenbank. Die Oberfläche liest "
        "nur von dort - „Gesendet“ bliebe leer."
    )
    assert liegen[0].betreff == "AW: TEST"
