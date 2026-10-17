"""Anhänge mit Content-ID (Issue #14).

⚠️ **Eine Content-ID heißt nicht „steht im Text“.** Outlook und Exchange geben
auch gewöhnlichen Anhängen eine. Bis 0.24.3 galt jeder solche Teil als
eingebettet und verschwand aus der Anhangsleiste; ein weitergeleitetes PDF war
dann nirgends zu sehen, obwohl Apple Mail es zeigte.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import Anhang, Nachricht
from app.services import mime
from conftest import einrichten
from test_druck import _mail_anlegen, ohne_netz  # noqa: F401 - Fixture

#: Das Beispiel aus dem Issue, wörtlich bis auf die Zeilenenden.
PDF_MIT_CID = (
    b"From: sender@example.invalid\r\n"
    b"To: recipient@example.invalid\r\n"
    b"Subject: PDF with Content-ID\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: multipart/mixed; boundary=test\r\n"
    b"\r\n"
    b"--test\r\n"
    b"Content-Type: text/plain\r\n"
    b"\r\n"
    b"See attachment.\r\n"
    b"--test\r\n"
    b'Content-Type: application/pdf; name="example.pdf"\r\n'
    b'Content-Disposition: attachment; filename="example.pdf"\r\n'
    b"Content-ID: <pdf@example.invalid>\r\n"
    b"\r\n"
    b"%PDF-1.4\r\n"
    b"--test--\r\n"
)


@pytest.mark.parametrize(
    "cid,typ,html,erwartet",
    [
        # Der Fall aus dem Issue: ein PDF ist nie ein Bild im Text.
        ("pdf@x", "application/pdf", '<a href="cid:pdf@x">PDF</a>', False),
        # Ein Bild, auf das der Text zeigt, steht im Text.
        ("bild1", "image/png", '<img src="cid:bild1">', True),
        # Groß und klein: manche Programme schreiben ``CID:``.
        ("Bild1", "image/png", '<img src="CID:bild1">', True),
        # Ein Bild, auf das nichts zeigt, sähe sonst niemand.
        ("bild1", "image/png", "<p>Kein Bild.</p>", False),
        ("bild1", "image/png", "", False),
        # Ohne Content-ID kann nichts darauf zeigen.
        ("", "image/png", '<img src="cid:">', False),
    ],
)
def test_eingebettet_ist_nur_ein_bild_mit_verweis(cid, typ, html, erwartet):
    assert mime.ist_eingebettet(cid, typ, html) is erwartet


def test_das_pdf_aus_dem_issue_ist_ein_anhang():
    z = mime.zerlegen(PDF_MIT_CID)
    assert [(a.dateiname, a.mime, a.cid) for a in z.anhaenge] == [
        ("example.pdf", "application/pdf", "pdf@example.invalid")
    ]
    assert z.anhaenge[0].eingebettet(z.html) is False


def _anhang(klient, mime_typ: str, cid: str, html: str, name: str) -> tuple[int, int]:
    """Eine geholte Mail mit einem Anhang, ``hat_anhang`` noch auf dem alten Stand."""
    einrichten(klient)
    kennung = _mail_anlegen(klient, html=html)
    with SessionLocal() as db:
        anhang = Anhang(
            nachricht_id=kennung, dateiname=name, mime=mime_typ, groesse=10, cid=cid
        )
        db.add(anhang)
        db.get(Nachricht, kennung).hat_anhang = False
        db.commit()
        return kennung, anhang.id


def test_die_anzeige_zeigt_das_pdf_und_heilt_die_bueroklammer(klient, ohne_netz):  # noqa: F811
    kennung, _ = _anhang(
        klient, "application/pdf", "pdf@example.invalid", "<p>Siehe Anhang.</p>", "example.pdf"
    )
    antwort = klient.get(f"/api/nachrichten/{kennung}")
    assert antwort.status_code == 200
    anhaenge = antwort.json()["anhaenge"]
    assert [(a["dateiname"], a["inline"]) for a in anhaenge] == [("example.pdf", False)], (
        "Ein PDF mit Content-ID wurde als eingebettet gemeldet und damit versteckt."
    )
    # ⚠️ In der eigenen Anfrage nachsehen: Die Antwort derselben Anfrage sähe
    # auch einen Wert, der nie festgeschrieben wurde.
    with SessionLocal() as db:
        assert db.get(Nachricht, kennung).hat_anhang is True, (
            "Die Büroklammer in der Liste blieb nach dem Öffnen aus."
        )


def test_ein_bild_im_text_bleibt_aus_der_leiste(klient, ohne_netz):  # noqa: F811
    kennung, _ = _anhang(
        klient, "image/png", "logo1", '<p><img src="cid:logo1"> Gruß</p>', "logo.png"
    )
    anhaenge = klient.get(f"/api/nachrichten/{kennung}").json()["anhaenge"]
    assert [(a["dateiname"], a["inline"]) for a in anhaenge] == [("logo.png", True)]
    with SessionLocal() as db:
        assert db.get(Nachricht, kennung).hat_anhang is False


def test_die_druckseite_nennt_das_pdf(klient, ohne_netz):  # noqa: F811
    kennung, _ = _anhang(
        klient, "application/pdf", "pdf@example.invalid", "<p>Siehe Anhang.</p>", "beleg.pdf"
    )
    rumpf = klient.get(f"/api/nachrichten/{kennung}/druck").text
    assert "beleg.pdf" in rumpf
