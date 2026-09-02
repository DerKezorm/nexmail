"""Echte Mails auseinandernehmen.

Die Prüfsteine hier sind keine Erfindungen: Umlaute in Betreff und Dateiname,
``quoted-printable``, verschachteltes ``multipart/related`` mit Inline-Bild,
eine Mail ganz ohne Textteil, ein gelogener Zeichensatz. Alles davon steht in
jedem gewachsenen Postfach.

⚠️ **Die Regel ist: niemals abstürzen, immer etwas zurückgeben.** Eine Mail,
die nexmail nicht anzeigen kann, ist schlimmer als eine, die schief aussieht.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

import pytest

from app.services import mime


def _einfach() -> bytes:
    m = EmailMessage()
    m["Subject"] = "Wartung der Heizungsanlage"
    m["From"] = "Hausverwaltung Brandt <service@brandt.example>"
    m["To"] = "Anna <anna@icloud.example>"
    m["Date"] = "Mon, 31 Aug 2026 09:14:00 +0200"
    m["Message-ID"] = "<abc123@brandt.example>"
    m.set_content("Guten Tag Frau Beispiel,\n\ndie Wartung ist am 12. September.\n")
    return m.as_bytes()


def test_einfache_mail():
    z = mime.zerlegen(_einfach())
    assert z.betreff == "Wartung der Heizungsanlage"
    assert z.von.name == "Hausverwaltung Brandt"
    assert z.von.adresse == "service@brandt.example"
    assert z.an[0].adresse == "anna@icloud.example"
    assert "12. September" in z.text
    assert z.datum.year == 2026
    assert z.anhaenge == []


def test_umlaute_im_betreff():
    """⚠️ Kodierte Kopfzeilen. Ohne Behandlung steht `=?utf-8?B?…?=` in der Liste."""
    roh = (
        b"Subject: =?utf-8?B?" + base64.b64encode("Grüße aus Köln".encode()) + b"?=\r\n"
        b"From: a@b.example\r\n"
        b"Date: Mon, 31 Aug 2026 09:14:00 +0200\r\n"
        b"\r\n"
        b"Text\r\n"
    )
    assert mime.zerlegen(roh).betreff == "Grüße aus Köln"


def test_quoted_printable():
    roh = (
        b"Subject: Test\r\n"
        b"From: a@b.example\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n"
        b"\r\n"
        b"Gr=C3=BC=C3=9Fe aus K=C3=B6ln=\r\n"
    )
    assert "Grüße aus Köln" in mime.zerlegen(roh).text


def test_gelogener_zeichensatz():
    """⚠️ „iso-8859-1" steht in unzähligen Mails, die UTF-8 sind.

    Wer dem Wert blind glaubt, zeigt „Ã¼" statt „ü".
    """
    roh = (
        "Subject: Test\r\nFrom: a@b.example\r\n"
        "Content-Type: text/plain; charset=iso-8859-1\r\n\r\n"
    ).encode() + "Grüße aus Köln, das ist ein längerer Satz zum Erkennen.".encode("utf-8")

    text = mime.zerlegen(roh).text
    assert "Ã¼" not in text
    assert "Grüße" in text or "ü" in text


def test_anhang_mit_umlaut_im_dateinamen():
    m = EmailMessage()
    m["Subject"] = "Rechnung"
    m["From"] = "a@b.example"
    m.set_content("Im Anhang.")
    m.add_attachment(
        b"%PDF-1.4 nur so getan",
        maintype="application",
        subtype="pdf",
        filename="Wartungsankündigung.pdf",
    )
    z = mime.zerlegen(m.as_bytes())

    assert len(z.anhaenge) == 1
    assert z.anhaenge[0].dateiname == "Wartungsankündigung.pdf"
    assert z.anhaenge[0].mime == "application/pdf"
    assert z.anhaenge[0].groesse > 0


def test_verschachteltes_multipart_mit_inline_bild():
    """multipart/related mit cid: — der Newsletter-Normalfall."""
    roh = b"""From: a@b.example
Subject: Newsletter
Content-Type: multipart/related; boundary="AUSSEN"

--AUSSEN
Content-Type: multipart/alternative; boundary="INNEN"

--INNEN
Content-Type: text/plain; charset=utf-8

Nur Text.
--INNEN
Content-Type: text/html; charset=utf-8

<p>Bunt <img src="cid:bild1"></p>
--INNEN--
--AUSSEN
Content-Type: image/png
Content-ID: <bild1>
Content-Transfer-Encoding: base64

aVZCT1J3MEtHZ289
--AUSSEN--
"""
    z = mime.zerlegen(roh)
    assert "Nur Text." in z.text
    assert "<p>Bunt" in z.html
    assert len(z.anhaenge) == 1
    assert z.anhaenge[0].cid == "bild1"
    assert z.anhaenge[0].inline is True


def test_mail_ganz_ohne_textteil():
    """Kommt vor — und darf nicht dazu führen, dass gar nichts erscheint."""
    roh = b"""From: a@b.example
Subject: Nur ein Anhang
Content-Type: application/pdf
Content-Disposition: attachment; filename="x.pdf"

nur bytes
"""
    z = mime.zerlegen(roh)
    assert z.text == ""
    assert z.html == ""
    assert len(z.anhaenge) == 1
    assert z.betreff == "Nur ein Anhang"


def test_kaputte_mail_stuerzt_nicht_ab():
    """Ohne Kopfzeilen, ohne alles."""
    z = mime.zerlegen(b"das ist keine mail")
    assert z.betreff == ""
    assert isinstance(z.datum.year, int)


def test_fehlendes_datum_bekommt_jetzt():
    roh = b"From: a@b.example\r\nSubject: Ohne Datum\r\n\r\nText\r\n"
    z = mime.zerlegen(roh)
    assert z.datum is not None


def test_kaputtes_datum_stuerzt_nicht_ab():
    roh = b"From: a@b.example\r\nDate: gestern irgendwann\r\nSubject: X\r\n\r\nText\r\n"
    assert mime.zerlegen(roh).datum is not None


def test_text_wird_gedeckelt():
    """Eine Mail mit einem angehängten Roman soll den Index nicht sprengen."""
    lang = "x" * (mime.TEXT_GRENZE * 2)
    roh = f"From: a@b.example\r\nSubject: Lang\r\n\r\n{lang}".encode()
    assert len(mime.zerlegen(roh).text) <= mime.TEXT_GRENZE


# --- Stränge ------------------------------------------------------------- #


@pytest.mark.parametrize(
    "betreff,kern",
    [
        ("Re: Wochenende", "Wochenende"),
        ("AW: Wochenende", "Wochenende"),
        ("WG: Wochenende", "Wochenende"),
        ("Fwd: Wochenende", "Wochenende"),
        ("AW: Re: WG: Wochenende", "Wochenende"),
        ("Re[2]: Wochenende", "Wochenende"),
        ("Wochenende", "Wochenende"),
        ("Antw: Wochenende", "Wochenende"),
    ],
)
def test_betreffkern(betreff, kern):
    """⚠️ Deutsch gehört dazu.

    Wer nur „Re:" und „Fwd:" abschneidet, macht aus einem deutschen Hin und
    Her drei verschiedene Stränge.
    """
    assert mime.betreff_kern(betreff) == kern


def test_strang_folgt_den_references():
    """Die Kette ist eindeutig, der Betreff nur wahrscheinlich."""
    roh = (
        b"From: a@b.example\r\nSubject: Re: Etwas\r\n"
        b"References: <wurzel@x.example> <zweig@x.example>\r\n"
        b"In-Reply-To: <zweig@x.example>\r\n\r\nText\r\n"
    )
    assert mime.strang_kennung(mime.zerlegen(roh)) == "<wurzel@x.example>"


def test_strang_ueber_betreff_wenn_keine_kette():
    eins = mime.zerlegen(b"From: a@b.example\r\nSubject: Wochenende am See\r\n\r\nA\r\n")
    zwei = mime.zerlegen(b"From: c@d.example\r\nSubject: AW: Wochenende am See\r\n\r\nB\r\n")
    assert mime.strang_kennung(eins) == mime.strang_kennung(zwei)


def test_verschiedene_betreffe_verschiedene_straenge():
    eins = mime.zerlegen(b"From: a@b.example\r\nSubject: Wochenende\r\n\r\nA\r\n")
    zwei = mime.zerlegen(b"From: a@b.example\r\nSubject: Rechnung\r\n\r\nB\r\n")
    assert mime.strang_kennung(eins) != mime.strang_kennung(zwei)


def test_eine_angehaengte_mail_ist_ein_anhang_und_kein_text():
    """⚠️ **message/rfc822 meldet is_multipart() und ist doch ein Anhang.**

    Die Zerlege-Schleife stieg bis zum 02.09.2026 in die angehaengte Mail
    HINEIN: Ihr Text wurde Teil des eigenen Textes, in der Anhangsleiste
    erschien nichts — waehrend die Liste die Bueroklammer zeigte, denn die
    kommt vom Server aus BODYSTRUCTURE. Aufgefallen beim ersten
    „Als Anhang weiterleiten" an ein eigenes Postfach.
    """
    from email.message import EmailMessage

    innen = EmailMessage()
    innen["Subject"] = "Die Originalmail"
    innen["Message-ID"] = "<original@example.com>"
    innen.set_content("Geheimer Innentext, der NICHT im Aussentext stehen darf.")

    aussen = EmailMessage()
    aussen["Subject"] = "Fwd: Die Originalmail"
    aussen.set_content("Mein eigener Begleittext.")
    aussen.add_attachment(innen)  # macht daraus message/rfc822

    ergebnis = mime.zerlegen(aussen.as_bytes())

    assert "Mein eigener Begleittext." in ergebnis.text
    assert "Geheimer Innentext" not in ergebnis.text, (
        "Der Text der angehaengten Mail ist in den eigenen Text gerutscht."
    )
    assert len(ergebnis.anhaenge) == 1, "Die angehaengte Mail fehlt in der Anhangsleiste."
    anhang = ergebnis.anhaenge[0]
    assert anhang.mime == "message/rfc822"
    assert anhang.dateiname.endswith(".eml")
    assert b"<original@example.com>" in anhang.inhalt, (
        "Der Anhang traegt nicht die vollstaendige Originalmail."
    )


def test_die_aeussere_mail_selbst_ist_kein_anhang():
    """Die Gegenprobe: Nur ein EINGEBETTETES message/rfc822 ist ein Anhang.

    Die aeusserste Ebene traegt nummer == "" — wer die Weiche auch dort
    greifen laesst, macht aus jeder gewoehnlichen Mail einen Anhang ihrer
    selbst und verliert saemtlichen Text.
    """
    from email.message import EmailMessage

    schlicht = EmailMessage()
    schlicht["Subject"] = "Ganz normale Mail"
    schlicht.set_content("Nur Text.")

    ergebnis = mime.zerlegen(schlicht.as_bytes())
    assert "Nur Text." in ergebnis.text
    assert ergebnis.anhaenge == []
