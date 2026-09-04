"""Schreiben: bauen, zitieren, senden, in der Warteschlange behalten.

⚠️ **Nichts hier geht ins Netz.** SMTP wird ersetzt, IMAP ebenfalls.
"""

from __future__ import annotations

import base64
import json
from email import message_from_bytes
from email.message import EmailMessage

import pytest

from sqlalchemy import select

from app.models import Ausgang, Nachricht, Ordner
from app.services import abgleich, mime, senden, verfassen
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


def test_hohe_wichtigkeit_traegt_beide_kopfzeilen():
    """⚠️ Outlook liest ``Importance``, Thunderbird ``X-Priority`` — nur eine
    zu schreiben hiesse, fuer die Haelfte der Empfaenger normal zu sein."""
    roh, _ = verfassen.bauen(_entwurf(wichtigkeit="hoch"))
    m = _gelesen(roh)

    assert m["Importance"] == "high"
    assert m["X-Priority"] == "1"


def test_niedrige_wichtigkeit_traegt_beide_kopfzeilen():
    roh, _ = verfassen.bauen(_entwurf(wichtigkeit="niedrig"))
    m = _gelesen(roh)

    assert m["Importance"] == "low"
    assert m["X-Priority"] == "5"


def test_ohne_umschalter_keine_wichtigkeits_kopfzeilen():
    """Vorgabe normal heisst: gar keine Kopfzeile — wie in jedem Client."""
    roh, _ = verfassen.bauen(_entwurf())
    m = _gelesen(roh)

    assert m["Importance"] is None
    assert m["X-Priority"] is None


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


# --- Weiterleiten als Anhang --------------------------------------------- #


def _original_mail() -> bytes:
    """Eine Mail, wie sie im Postfach liegt — mit der Message-ID, an der die
    Tests sie wiedererkennen."""
    m = EmailMessage()
    m["From"] = "Anja Kessler <anja@example.org>"
    m["To"] = "anna@icloud.example"
    m["Subject"] = "Rechnung Mai"
    m["Message-ID"] = "<original-42@x.example>"
    m["Date"] = "Mon, 31 Aug 2026 09:14:00 +0200"
    m.set_content("Anbei die Rechnung.")
    return m.as_bytes()


@pytest.fixture
def original_im_posteingang(db, postausgang):
    """Die Originalmail liegt beim Doppelgänger und ist abgeglichen — so wie
    eine echte Mail, auf der jemand „Als Anhang weiterleiten" wählt."""
    konto, smtp, server = postausgang  # noqa: F811 - Fixture-Name
    server.einwerfen("INBOX", 1, "Rechnung Mai", roh=_original_mail())
    posteingang = next(o for o in konto.ordner if o.pfad == "INBOX")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)
    nachricht = (
        db.execute(select(Nachricht).where(Nachricht.ordner_id == posteingang.id))
        .scalars()
        .one()
    )
    return konto, smtp, nachricht


def test_anhang_vorlage_traegt_die_rohe_mail(klient, original_im_posteingang):
    """Die Vorlage für „Als Anhang weiterleiten": Fwd-Betreff, leerer Text,
    keine Empfänger — und die Originalmail **byte-genau** als Anlage."""
    _, _, nachricht = original_im_posteingang

    antwort = klient.get(f"/api/verfassen/vorlage/{nachricht.id}?art=anhang")
    assert antwort.status_code == 200
    vorlage = antwort.json()

    assert vorlage["betreff"] == "Fwd: Rechnung Mai"
    assert vorlage["html"] == ""
    assert vorlage["an"] == []
    assert vorlage["in_reply_to"] == ""

    assert len(vorlage["anlagen"]) == 1
    anlage = vorlage["anlagen"][0]
    assert anlage["mime_typ"] == "message/rfc822"
    # Derselbe Name wie beim .eml-Download.
    assert anlage["dateiname"] == "Rechnung Mai.eml"
    # ⚠️ Unverändert heißt byte-genau — nichts bereinigt, nichts umkodiert.
    assert base64.b64decode(anlage["inhalt_b64"]) == _original_mail()


def test_als_anhang_gesendet_traegt_genau_einen_rfc822_teil(klient, original_im_posteingang):
    """⚠️ Der Kern des Features, an der versendeten MIME gemessen: genau ein
    ``message/rfc822``-Teil, darin die Message-ID des Originals — und der
    Betreff trägt ``Fwd:``."""
    konto, smtp, nachricht = original_im_posteingang  # noqa: F811 - Fixture-Name

    vorlage = klient.get(f"/api/verfassen/vorlage/{nachricht.id}?art=anhang").json()
    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["empfaenger@example.org"],
            "betreff": vorlage["betreff"],
            "html": "<p>Bitte einmal ansehen.</p>",
            "anlagen": vorlage["anlagen"],
        },
    )
    assert antwort.status_code == 200
    assert antwort.json()["stand"] == "gesendet"

    _, _, roh = smtp.gesendet[0]
    m = _gelesen(roh)
    assert m["Subject"].startswith("Fwd:")

    teile = [t for t in m.walk() if t.get_content_type() == "message/rfc822"]
    assert len(teile) == 1, "Es muss genau einen message/rfc822-Teil geben."
    assert teile[0].get_filename() == "Rechnung Mai.eml"

    # ⚠️ Der Teil muss sich als Mail **öffnen** lassen — deshalb hängt `bauen`
    # ihn als Nachricht an, nicht als Base64-Bytes. Ein Base64-kodierter
    # message/rfc822-Teil sähe im Baum gleich aus und wäre für jeden Parser
    # unlesbar; dieser Zugriff hier schlüge dann fehl.
    innen = teile[0].get_payload(0)
    assert innen["Message-ID"] == "<original-42@x.example>"
    assert innen["Subject"] == "Rechnung Mai"


@pytest.mark.parametrize(
    "betreff,erwartet",
    [
        ("Rechnung Mai", "Fwd: Rechnung Mai"),
        # ⚠️ Bewusst KEIN Kürzen auf den Kern: Die Mail im Anhang trägt genau
        # diesen Betreff, der Empfänger soll dieselbe Zeile lesen.
        ("AW: Rechnung Mai", "Fwd: AW: Rechnung Mai"),
        ("", "Fwd:"),
    ],
)
def test_anhang_betreff_behaelt_das_original(betreff, erwartet):
    assert verfassen.weiterleitung_anhang_betreff(betreff) == erwartet


# --- Entwurf weiterschreiben ---------------------------------------------- #


def _entwurfs_mail() -> bytes:
    """Ein Entwurf, wie ihn der Abbruch ablegt: mit ``Bcc``-Zeile, einem
    Anhang und einem Bild im Text."""
    m = EmailMessage()
    m["From"] = "Anna Beispiel <anna@icloud.example>"
    m["To"] = "anja@example.org"
    m["Bcc"] = "heimlich@example.org"
    m["Subject"] = "Halb fertig"
    m["Message-ID"] = "<entwurf-7@x.example>"
    m["Date"] = "Mon, 31 Aug 2026 09:14:00 +0200"
    m.set_content("Siehe Bild.")
    m.add_alternative('<p>Siehe <img src="cid:bild1"></p>', subtype="html")
    m.add_attachment(
        b"\x89PNG", maintype="image", subtype="png", filename="bild.png", cid="<bild1>"
    )
    m.add_attachment(
        b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="Rechnung.pdf"
    )
    return m.as_bytes()


def test_entwurfs_vorlage_behaelt_blindkopie_und_anhaenge(klient, db, postausgang):
    """⚠️ **Der wieder geöffnete Entwurf ist die ganze Nachricht.**

    Die ``Bcc``-Zeile schreibt ``senden._mit_blindkopie`` beim Abbruch eigens
    in die Roh-Bytes; die Anhänge liegen im Entwurf. Fällt hier eines weg,
    verliert das Weiterschreiben stillschweigend Empfänger oder Dateien — und
    weil die ``entwurf_uid`` mitkommt, räumt das Senden der verstümmelten
    Fassung die vollständige auch noch weg.
    """
    konto, _, server = postausgang

    db.add(Ordner(konto_id=konto.id, pfad="Drafts", name="Drafts", rolle="entwuerfe"))
    db.commit()
    db.refresh(konto)
    server.anlegen("Drafts")
    server.einwerfen("Drafts", 7, "Halb fertig", gelesen=True, roh=_entwurfs_mail())
    entwuerfe_ordner = next(o for o in konto.ordner if o.rolle == "entwuerfe")
    abgleich.ordner_abgleichen(server, db, konto, entwuerfe_ordner)
    nachricht = (
        db.execute(select(Nachricht).where(Nachricht.ordner_id == entwuerfe_ordner.id))
        .scalars()
        .one()
    )

    antwort = klient.get(f"/api/verfassen/vorlage/{nachricht.id}?art=entwurf")
    assert antwort.status_code == 200
    vorlage = antwort.json()

    assert vorlage["an"] == ["anja@example.org"]
    assert vorlage["blindkopie"] == ["heimlich@example.org"], (
        "Die Blindkopie des Entwurfs ist beim Wieder-Öffnen verloren gegangen."
    )
    assert vorlage["entwurf_uid"] == nachricht.uid

    namen = {a["dateiname"]: a for a in vorlage["anlagen"]}
    assert "Rechnung.pdf" in namen, "Der Anhang des Entwurfs fehlt in der Vorlage."
    assert base64.b64decode(namen["Rechnung.pdf"]["inhalt_b64"]) == b"%PDF-1.4 test"
    # Das Bild im Text trägt seine cid — daraus baut die Oberfläche wieder
    # eine anzeigbare Adresse.
    assert namen["bild.png"]["cid"] == "bild1"


def test_eml_dateiname_ist_dateinamensicher():
    """Der Betreff kommt von außen — Pfadzeichen formen den Namen nicht mit."""
    assert mime.eml_dateiname("Re: was/geht?") == "Re_ was_geht_.eml"
    assert mime.eml_dateiname('a\\b"c') == "a_b_c.eml"
    assert mime.eml_dateiname("") == "nachricht.eml"
    assert mime.eml_dateiname("   ") == "nachricht.eml"


def test_eml_dateiname_laesst_keine_steuerzeichen_durch():
    r"""⚠️ Ein kodierter Betreff (``=?utf-8?B?…?=``) kann nach dem Entziffern
    ``\r\n`` enthalten — und der Name landet wörtlich im
    ``content-disposition``-Kopf. Ein Zeilenumbruch dort ist eine
    eingeschleuste Kopfzeile, kein Dateiname."""
    name = mime.eml_dateiname("Vor\r\nSet-Cookie: boese")
    assert "\r" not in name and "\n" not in name
    assert mime.eml_dateiname("a\x00b\x1fc\x7fd") == "a_b_c_d.eml"


def test_die_disposition_uebersteht_emoji_und_cjk():
    """⚠️ Der Kopf verträgt nur Latin-1. Ein Betreff mit Emoji ließ den
    ``.eml``-Download vorher mit einem 500 umfallen (``UnicodeEncodeError``
    beim Serialisieren). RFC 5987: ASCII-Rückfall plus ``filename*``."""
    from app.routers.nachrichten import _anhang_disposition

    wert = _anhang_disposition("Grüße 🎉.eml")
    wert.encode("latin-1")  # darf nicht werfen — genau das war der 500
    assert "filename*=UTF-8''" in wert

    # Der gewöhnliche Fall bleibt schlicht.
    assert _anhang_disposition("Rechnung Mai.eml") == 'attachment; filename="Rechnung Mai.eml"'

    # Und Steuerzeichen kommen auch hier nicht durch.
    boese = _anhang_disposition("a\r\nSet-Cookie: x")
    assert "\r" not in boese and "\n" not in boese


def test_die_trennzeile_ist_ein_vertrag_mit_der_oberflaeche():
    """⚠️ ``frontend/src/lib/eigenerteil.ts`` (``ZITAT_MARKEN``) schneidet den
    eigenen Text an genau dieser Zeichenkette ab. Daran hängen **zwei** Dinge:
    die Anhang-Erinnerung, und seit dem 04.09.2026 der KI-Knopf — was hinter
    der Marke steht, geht nicht zu einem KI-Anbieter hinaus. Wer eine Seite
    umformuliert, ohne die andere nachzuziehen, macht die Erinnerung zur
    Falschnachfrage **und** schickt fremde Post nach draußen.

    ⚠️ **Die Datei hiess bis zum 04.09.2026 ``anhang.ts``.** Die Marken sind in
    ein eigenes Modul gewandert, weil zwei Stellen dieselbe Antwort in
    verschiedenen Formen brauchen. Dieser Test war der Einzige, der die
    Verschiebung gemeldet hat — genau dafür steht er da."""
    from pathlib import Path

    marke = "---------- Weitergeleitete Nachricht ----------"
    assert marke in verfassen.weiterleitung_html(_eingehend())

    quelle = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "eigenerteil.ts"
    assert marke in quelle.read_text(encoding="utf-8"), (
        "Die Marke in eigenerteil.ts weicht vom Server ab — die "
        "Anhang-Erinnerung saehe den weitergeleiteten Text als eigenen, und "
        "der KI-Knopf schickte ihn mit hinaus."
    )


# --- Absender-Aliasse ----------------------------------------------------- #


def test_eine_fremde_absenderadresse_wird_abgewiesen(klient, db, postausgang):
    """⚠️ **Die sicherheitsrelevante Stelle.** Die Adresse kommt aus dem
    Browser; ohne Prüfung verschickte nexmail Post unter jeder Adresse, die
    jemand in die Anfrage schreibt. Der Mailserver sieht nur unsere Anmeldung."""
    konto, _, _ = postausgang
    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["wer@example.org"],
            "betreff": "Nicht ich",
            "html": "<p>x</p>",
            "von_adresse": "chef@fremde-firma.example",
        },
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "alias_unbekannt"
    assert db.query(Ausgang).count() == 0


def test_ein_hinterlegter_alias_steht_im_absender(klient, db, postausgang):
    from app.services import aliase as aliasdienst
    from app.services.aliase import Alias

    konto, smtp, _ = postausgang
    aliasdienst.schreiben(konto, [Alias("verein@example.com", "Der Vorstand")])
    db.commit()

    antwort = klient.post(
        "/api/verfassen/senden",
        json={
            "konto_id": konto.id,
            "an": ["wer@example.org"],
            "betreff": "Aus dem Verein",
            "html": "<p>x</p>",
            "von_adresse": "verein@example.com",
        },
    )
    assert antwort.status_code == 200, antwort.text
    _, _, roh = smtp.gesendet[0]
    von = message_from_bytes(roh)["From"]
    assert "verein@example.com" in von
    # ⚠️ Der Name des Alias, nicht der des Kontos — sonst stünde der falsche
    # Absendername an einer richtigen Adresse.
    assert "Der Vorstand" in von


def test_ohne_wahl_bleibt_es_bei_der_hauptadresse(klient, db, postausgang):
    konto, smtp, _ = postausgang
    klient.post(
        "/api/verfassen/senden",
        json={"konto_id": konto.id, "an": ["wer@example.org"], "betreff": "x", "html": "<p>x</p>"},
    )
    von = message_from_bytes(smtp.gesendet[0][2])["From"]
    assert konto.adresse in von


def test_die_antwort_kommt_von_der_angeschriebenen_zweitadresse(
    klient, db, original_im_posteingang
):
    """⚠️ **Der ganze Zweck der Aliasse.** Ohne das erfährt der andere bei
    jeder Antwort die Hauptadresse, und die Trennung ist dahin.

    ⚠️ Die Mail muss beim Doppelgänger liegen: ``/vorlage`` holt die Roh-Mail,
    und ohne sie läuft der Abruf in den Mailserver — im Testlauf ein 502.
    """
    from app.services import aliase as aliasdienst
    from app.services.aliase import Alias

    konto, _, nachricht = original_im_posteingang
    aliasdienst.schreiben(konto, [Alias("verein@example.com", "Vorstand")])
    # Die Mail ging an die Zweitadresse, nicht an die Hauptadresse.
    nachricht.an_json = json.dumps([{"n": "", "a": "verein@example.com"}])
    db.commit()

    vorlage = klient.get(f"/api/verfassen/vorlage/{nachricht.id}?art=antwort").json()
    assert vorlage["von_adresse"] == "verein@example.com"


def test_ohne_treffer_bleibt_der_absender_leer(klient, db, original_im_posteingang):
    """Leer heißt: die Hauptadresse. Die Oberfläche muss nichts umschalten."""
    konto, _, nachricht = original_im_posteingang
    vorlage = klient.get(f"/api/verfassen/vorlage/{nachricht.id}?art=antwort").json()
    assert vorlage["von_adresse"] == ""
