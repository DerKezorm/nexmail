"""Die Absenderpruefung aus ``Authentication-Results`` — Grundlage des Markenlogos.

⚠️ **Jeder Fall hier ist ein Weg, auf dem eine gefaelschte Mail das Logo einer
Bank bekaeme.** Deshalb stehen die Faelschungen im Vordergrund, nicht der
gute Weg.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Nachricht, Ordner
from app.services import abgleich, absenderpruefung
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture

ECHT = "mx.example.net; dkim=pass header.d=bank.test; dmarc=pass (p=REJECT) header.from=bank.test"


# --- Die Zeile lesen ------------------------------------------------------- #


def test_nur_die_oberste_zeile_zaehlt():
    """⚠️ Eine Zeile kann auch der Absender schreiben; sie steht dann unten."""
    kopf = (
        "Authentication-Results: mx.example.net; dmarc=fail header.from=bank.test\r\n"
        "Authentication-Results: mx.example.net; dmarc=pass header.from=bank.test\r\n\r\n"
    )
    assert absenderpruefung.oberste_zeile(kopf) == "mx.example.net; dmarc=fail header.from=bank.test"


def test_eine_gefaltete_zeile_wird_zusammengesetzt():
    kopf = b"Authentication-Results: mx.example.net;\r\n\tdkim=pass;\r\n dmarc=pass header.from=bank.test\r\n\r\n"
    assert absenderpruefung.oberste_zeile(kopf) == "mx.example.net; dkim=pass; dmarc=pass header.from=bank.test"


def test_bestanden_nur_fuer_genau_diese_domain():
    assert absenderpruefung.deuten(ECHT, "bank.test") == ("mx.example.net", True)
    assert absenderpruefung.deuten(ECHT, "Bank.Test") == ("mx.example.net", True)
    # ⚠️ Bestanden fuer eine andere Domain sagt ueber diese nichts.
    assert absenderpruefung.deuten(ECHT, "andere.example") == ("mx.example.net", False)


def test_durchgefallen_oder_ohne_dmarc_ist_nicht_bestanden():
    assert absenderpruefung.deuten("mx.example.net; dmarc=fail header.from=bank.test", "bank.test")[1] is False
    assert absenderpruefung.deuten("mx.example.net; spf=pass smtp.mailfrom=bank.test", "bank.test")[1] is False
    assert absenderpruefung.deuten("", "bank.test") == ("", False)


def test_ohne_dmarc_zeile_zaehlt_eine_passende_dkim_unterschrift():
    """⚠️ **Gemessen an All-Inkl, 27.09.2026:** Dort steht nur ``dkim=pass``,
    nie ein ``dmarc=``. Eine Unterschrift aus der Domain des Absenders ist
    nach der Definition von DMARC ein Bestehen."""
    zeile = "mx.example.net; dkim=pass (2048-bit key) header.d=bank.test header.i=@bank.test"
    assert absenderpruefung.deuten(zeile, "bank.test") == ("mx.example.net", True)
    # Aus einer Unterdomain derselben Organisation auch.
    assert absenderpruefung.deuten(zeile.replace("header.d=bank.test", "header.d=mail.bank.test"), "bank.test")[1] is True


def test_eine_fremde_dkim_unterschrift_zaehlt_nicht():
    """Ein Versanddienstleister unterschreibt mit seiner eigenen Domain; das
    sagt ueber den Absender nichts."""
    zeile = "mx.example.net; dkim=pass header.d=versand.example header.i=@versand.example"
    assert absenderpruefung.deuten(zeile, "bank.test")[1] is False


def test_ein_dmarc_fail_schlaegt_die_dkim_unterschrift():
    zeile = "mx.example.net; dkim=pass header.d=bank.test; dmarc=fail header.from=bank.test"
    assert absenderpruefung.deuten(zeile, "bank.test")[1] is False
    zeile = "mx.example.net; dkim=fail header.d=bank.test"
    assert absenderpruefung.deuten(zeile, "bank.test")[1] is False


def test_ein_pass_im_kommentar_zaehlt_nicht():
    """RFC 8601 erlaubt Kommentare in Klammern; darin darf alles stehen.

    ⚠️ **Gefaehrlich ist ein Kommentar mit Semikolon**: Ohne Klammerregel
    wuerde daraus ein eigener Teil, der mit ``dmarc=pass`` beginnt und vor dem
    echten ``dmarc=fail`` steht. Der erste Testfall hier trug kein Semikolon
    und liess die Mutation „Kommentare nicht entfernen" durch.
    """
    zeile = "mx.example.net; dmarc=fail (dmarc=pass header.from=bank.test) header.from=bank.test"
    assert absenderpruefung.deuten(zeile, "bank.test")[1] is False
    # Mit Leerzeichen vor der Klammer, sonst haengt sie an der Domain und
    # verhindert den Treffer nur zufaellig.
    zeile = "mx.example.net; spf=none (x; dmarc=pass header.from=bank.test ); dmarc=fail header.from=bank.test"
    assert absenderpruefung.deuten(zeile, "bank.test")[1] is False


# --- Beim Abgleich ---------------------------------------------------------- #


def _abgleichen(db, konto, monkeypatch, *mails):  # noqa: F811
    server = FalscherServer()
    server.anlegen("INBOX")
    for uid, (von, zeilen) in enumerate(mails, start=1):
        server.einwerfen("INBOX", uid, f"Mail {uid}", von=von, kopfzeilen={"Authentication-Results": zeilen})
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)
    posteingang = next(o for o in konto.ordner if o.rolle == "posteingang")
    abgleich.ordner_abgleichen(server, db, konto, posteingang)
    return {n.betreff: n for n in db.query(Nachricht).filter_by(ordner_id=posteingang.id)}


def test_der_abgleich_merkt_sich_pruefer_und_ergebnis(db, konto, monkeypatch):  # noqa: F811
    zeilen = _abgleichen(
        db, konto, monkeypatch,
        ("Bank <info@bank.test>", [ECHT]),
        # Die Faelschung: Der Anbieter hat durchfallen lassen, der Absender
        # hat darunter ein „pass" hineingeschrieben.
        ("Bank <info@bank.test>", [
            "mx.example.net; dmarc=fail header.from=bank.test",
            "mx.example.net; dmarc=pass header.from=bank.test",
        ]),
        ("Bank <info@bank.test>", []),
    )
    assert (zeilen["Mail 1"].pruefer, zeilen["Mail 1"].dmarc_bestanden) == ("mx.example.net", True)
    assert zeilen["Mail 2"].dmarc_bestanden is False
    assert (zeilen["Mail 3"].pruefer, zeilen["Mail 3"].dmarc_bestanden) == ("", False)


# --- Wem geglaubt wird -------------------------------------------------------- #


def _mails(db, konto, pruefer: list[str]):  # noqa: F811
    ordner = db.query(Ordner).filter_by(konto_id=konto.id).first()
    jetzt = datetime(2026, 9, 27, tzinfo=timezone.utc)
    for i, name in enumerate(pruefer):
        db.add(
            Nachricht(
                benutzer_id=konto.benutzer_id, konto_id=konto.id, ordner_id=ordner.id, uid=1000 + i,
                betreff=f"M{i}", datum=jetzt - timedelta(minutes=i), pruefer=name, dmarc_bestanden=True,
            )
        )
    db.commit()


def test_der_gewohnte_pruefer_wird_gelernt(db, konto):  # noqa: F811
    _mails(db, konto, ["mx.example.net"] * 9 + ["faelscher.example"])
    assert absenderpruefung.vertraute_pruefer(db, {konto.id}) == {konto.id: "mx.example.net"}


def test_ohne_gleichbleibenden_pruefer_wird_keinem_geglaubt(db, konto):  # noqa: F811
    """⚠️ Der Anbieter schreibt keine Zeile, jeder Absender seine eigene."""
    _mails(db, konto, ["a.example", "b.example", "c.example", "d.example", "e.example", "a.example"])
    assert absenderpruefung.vertraute_pruefer(db, {konto.id}) == {}


def test_zu_wenige_mails_reichen_nicht(db, konto):  # noqa: F811
    _mails(db, konto, ["mx.example.net"] * (absenderpruefung.MINDESTENS - 1))
    assert absenderpruefung.vertraute_pruefer(db, {konto.id}) == {}


def test_geprueft_nur_vom_gewohnten_pruefer():
    n = Nachricht(konto_id="k", pruefer="mx.example.net", dmarc_bestanden=True)
    assert absenderpruefung.geprueft(n, {"k": "mx.example.net"}) is True
    assert absenderpruefung.geprueft(n, {"k": "anderer.example"}) is False
    assert absenderpruefung.geprueft(n, {}) is False
    n.dmarc_bestanden = False
    assert absenderpruefung.geprueft(n, {"k": "mx.example.net"}) is False


# --- In der Liste ------------------------------------------------------------------ #


def test_die_liste_sagt_welche_mail_geprueft_ist(klient, db, konto):  # noqa: F811
    """Nur Mails vom gewohnten Pruefer mit bestandenem DMARC fragen nach dem Logo."""
    _mails(db, konto, ["mx.example.net"] * 6)
    ordner = db.query(Ordner).filter_by(konto_id=konto.id).first()
    jetzt = datetime(2026, 9, 28, tzinfo=timezone.utc)
    for uid, (betreff, pruefer, bestanden) in enumerate(
        (("Echt", "mx.example.net", True), ("Durchgefallen", "mx.example.net", False),
         ("Fremder Pruefer", "faelscher.example", True)),
        start=2000,
    ):
        db.add(Nachricht(benutzer_id=konto.benutzer_id, konto_id=konto.id, ordner_id=ordner.id, uid=uid,
                         betreff=betreff, datum=jetzt, pruefer=pruefer, dmarc_bestanden=bestanden))
    db.commit()

    zeilen = {z["betreff"]: z for z in klient.get("/api/nachrichten", params={"ordner_id": ordner.id}).json()}

    assert zeilen["Echt"]["absender_geprueft"] is True
    assert zeilen["Durchgefallen"]["absender_geprueft"] is False
    assert zeilen["Fremder Pruefer"]["absender_geprueft"] is False
