"""Antworten auf eigene Einladungen einsammeln.

⚠️ **Ohne das bleibt die Teilnehmerliste eine Namensliste**, und man weiß nicht,
wer kommt.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from app.models import Benutzer, Kalender, Nachricht, Termin
from app.services import terminantwort as dienst
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


@pytest.fixture
def welt(klient, db, konto):  # noqa: F811
    person = db.query(Benutzer).one()
    kal = Kalender(benutzer_id=person.id, name="Privat", farbe=1)
    db.add(kal)
    db.commit()
    termin = Termin(
        kalender_id=kal.id,
        benutzer_id=person.id,
        uid="runde@nexmail",
        titel="Quartalsrunde",
        beginn=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
        zeitzone="Europe/Berlin",
        sequenz=1,
        organisator=json.dumps({"name": "", "adresse": "anna@icloud.example"}),
        teilnehmer=json.dumps(
            [
                {"name": "", "adresse": "anja@example.org", "antwort": "NEEDS-ACTION"},
                {"name": "", "adresse": "jan@example.org", "antwort": "NEEDS-ACTION"},
            ]
        ),
    )
    db.add(termin)
    db.commit()
    return person, konto, termin


def _antwortmail(uid="runde@nexmail", wer="anja@example.org", stand="ACCEPTED", sequenz=1) -> bytes:
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "METHOD:REPLY",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SEQUENCE:{sequenz}",
            "SUMMARY:Quartalsrunde",
            f"ATTENDEE;PARTSTAT={stand}:mailto:{wer}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    ) + "\r\n"
    mail = EmailMessage()
    mail["From"] = wer
    mail["To"] = "anna@icloud.example"
    mail["Subject"] = "Zugesagt: Quartalsrunde"
    mail.set_content("Bin dabei.")
    mail.add_alternative(ics, subtype="calendar", params={"method": "REPLY", "charset": "utf-8"})
    return mail.as_bytes()


def _nachricht(db, konto, ordner_id) -> Nachricht:  # noqa: F811
    n = Nachricht(
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        ordner_id=ordner_id,
        uid=99,
        message_id="<antwort@example.org>",
        betreff="Zugesagt",
        datum=datetime(2026, 9, 5, tzinfo=timezone.utc),
        hat_kalender=True,
    )
    db.add(n)
    db.commit()
    return n


def test_eine_zusage_wird_nachgetragen(db, welt):
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, termin.kalender_id and konto.ordner[0].id)

    assert dienst.verarbeiten(db, konto, nachricht, _antwortmail()) is True

    leute = {p["adresse"]: p["antwort"] for p in json.loads(termin.teilnehmer)}
    assert leute["anja@example.org"] == "ACCEPTED"
    # ⚠️ Und nur der eine — eine Antwort spricht für eine Person.
    assert leute["jan@example.org"] == "NEEDS-ACTION"


def test_eine_absage_genauso(db, welt):
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)
    dienst.verarbeiten(db, konto, nachricht, _antwortmail(stand="DECLINED"))
    leute = {p["adresse"]: p["antwort"] for p in json.loads(termin.teilnehmer)}
    assert leute["anja@example.org"] == "DECLINED"


def test_wer_nicht_eingeladen_war_kommt_nicht_dazu(db, welt):
    """⚠️ Sonst trägt sich ein Fremder in eine Teilnehmerliste ein, indem er
    eine Antwort schickt."""
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    assert dienst.verarbeiten(db, konto, nachricht, _antwortmail(wer="fremd@example.net")) is False
    assert len(json.loads(termin.teilnehmer)) == 2


def test_eine_antwort_auf_eine_aeltere_fassung_wird_verworfen(db, welt):
    """⚠️ Wer den Termin verschoben und neu eingeladen hat, bekäme sonst die
    Zusage zum alten Termin als Zusage zum neuen angezeigt."""
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    assert dienst.verarbeiten(db, konto, nachricht, _antwortmail(sequenz=0)) is False
    leute = {p["adresse"]: p["antwort"] for p in json.loads(termin.teilnehmer)}
    assert leute["anja@example.org"] == "NEEDS-ACTION"


def test_ein_fremder_termin_wird_nicht_angefasst(db, welt):
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)
    assert dienst.verarbeiten(db, konto, nachricht, _antwortmail(uid="gibtesnicht")) is False


def test_eine_einladung_ist_keine_antwort(db, welt):
    """⚠️ Ohne die Prüfung auf ``METHOD:REPLY`` würde eine hereinkommende
    **Einladung** als Antwort gedeutet."""
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)
    mail = _antwortmail().replace(b"METHOD:REPLY", b"METHOD:REQUEST")
    assert dienst.verarbeiten(db, konto, nachricht, mail) is False


def test_eine_gewoehnliche_mail_stoert_nicht(db, welt):
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)
    mail = EmailMessage()
    mail["From"] = "wer@example.org"
    mail.set_content("Nur Text.")
    assert dienst.verarbeiten(db, konto, nachricht, mail.as_bytes()) is False


def test_die_ics_wird_auch_als_anhang_gefunden(db, welt):
    """⚠️ Manche Programme hängen sie an, statt sie danebenzulegen. Wer nur auf
    die Alternative sieht, verliert deren Antworten."""
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
        "UID:runde@nexmail\r\nSEQUENCE:1\r\n"
        "ATTENDEE;PARTSTAT=TENTATIVE:mailto:jan@example.org\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    mail = EmailMessage()
    mail["From"] = "jan@example.org"
    mail.set_content("Vielleicht.")
    mail.add_attachment(
        ics.encode("utf-8"), maintype="application", subtype="octet-stream", filename="antwort.ics"
    )
    assert dienst.verarbeiten(db, konto, nachricht, mail.as_bytes()) is True
    leute = {p["adresse"]: p["antwort"] for p in json.loads(termin.teilnehmer)}
    assert leute["jan@example.org"] == "TENTATIVE"


# --- Der Durchstich ---------------------------------------------------- #
#
# ⚠️ **Die Bausteine oben beweisen den Abgleich nicht.** Er entscheidet an
# ``BODYSTRUCTURE``, ob eine Mail ueberhaupt geholt wird — ein zu enger Blick
# dort laesst jede Zusage liegen, ohne dass ein Baustein-Test etwas merkt.


def _antwort_einwerfen(server, uid=41):
    server.einwerfen(
        "INBOX",
        uid,
        "Zugesagt: Quartalsrunde",
        roh=_antwortmail(),
        struktur=(
            [
                ("text", "plain", (), None, None, "7bit", 20),
                ("text", "calendar", ("method", "REPLY"), None, None, "7bit", 300),
            ],
            "alternative",
        ),
    )


def test_ein_abgleich_traegt_die_zusage_nach(db, welt, monkeypatch):
    from app.services import abgleich

    person, konto, termin = welt  # noqa: F811
    server = FalscherServer()
    server.anlegen("INBOX")
    _antwort_einwerfen(server)
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)

    abgleich.konto_abgleichen(db, konto)

    db.refresh(termin)
    leute = {p["adresse"]: p["antwort"] for p in json.loads(termin.teilnehmer)}
    assert leute["anja@example.org"] == "ACCEPTED"


def test_eine_mail_ohne_kalender_wird_nicht_heruntergeladen(db, welt, monkeypatch):
    """⚠️ **Die Vorauswahl ist der ganze Sinn von ``hat_kalender``.** Ohne sie
    holt der Abgleich jede eingegangene Mail ein zweites Mal vom Server."""
    from app.services import abgleich

    person, konto, termin = welt  # noqa: F811
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 42, "Nur Text", roh=b"Subject: x\r\n\r\nnix")
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)

    # ⚠️ Nicht an ``geholt`` messen — das Flag-Fenster fasst dieselbe UID
    # ohnehin ein zweites Mal an. Gemessen wird, ob der Antwortdienst
    # ueberhaupt gefragt wurde.
    gefragt = []
    from app.services import terminantwort as antwortdienst

    monkeypatch.setattr(
        antwortdienst, "verarbeiten", lambda *a, **k: gefragt.append(1) or False
    )

    abgleich.konto_abgleichen(db, konto)

    assert gefragt == []
    assert db.query(Nachricht).filter_by(uid=42).one().hat_kalender is False


def test_ein_fehlschlag_wirft_den_abgleich_nicht_um(db, welt, monkeypatch):
    """⚠️ **Der Antwortdienst laeuft am Ende einer Abgleichrunde.** Platzt er,
    darf nicht die ganze Runde verloren sein — dieselbe Lehre wie bei den
    Regeln daneben."""
    from app.services import abgleich
    from app.services import terminantwort as antwortdienst

    person, konto, termin = welt  # noqa: F811
    server = FalscherServer()
    server.anlegen("INBOX")
    _antwort_einwerfen(server, uid=43)
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)

    def platzt(*a, **k):
        raise RuntimeError("kaputte Einladung")

    monkeypatch.setattr(antwortdienst, "verarbeiten", platzt)

    ergebnis = abgleich.konto_abgleichen(db, konto)
    assert len(ergebnis["INBOX"].neue_ids) == 1


def test_eine_verworfene_antwort_steht_im_protokoll(db, welt, caplog):
    """⚠️ **Die Stille war das Schlimme.** Am 04.09.2026 antwortete Outlook
    unter der eigenen Absenderidentitaet statt unter der eingeladenen Adresse.
    Die Antwort war einwandfrei, nur die Adresse stand nicht auf der Liste —
    und von aussen sah es aus, als sei der Rueckkanal kaputt."""
    import logging

    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    with caplog.at_level(logging.INFO, logger="nexmail.terminantwort"):
        assert dienst.verarbeiten(db, konto, nachricht, _antwortmail(wer="fremd@example.net")) is False

    text = " ".join(r.getMessage() for r in caplog.records)
    # Beide Adressen — sonst raet der Betreiber, welche gemeint war.
    assert "fremd@example.net" in text
    assert "anja@example.org" in text


def test_eine_verworfene_antwort_steht_am_termin(db, welt):
    """⚠️ **Verworfen, aber nicht verschwiegen.** Nur das Protokoll genuegt
    nicht — dort sieht niemand nach, der einen Termin ansieht."""
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    assert dienst.verarbeiten(db, konto, nachricht, _antwortmail(wer="fremd@example.net")) is False

    vermerkt = json.loads(termin.fremde_antworten)
    assert len(vermerkt) == 1
    assert vermerkt[0]["adresse"] == "fremd@example.net"
    assert vermerkt[0]["antwort"] == "ACCEPTED"
    assert vermerkt[0]["am"]
    # ⚠️ Und die Teilnehmerliste bleibt unberuehrt.
    assert len(json.loads(termin.teilnehmer)) == 2


def test_je_adresse_nur_der_letzte_stand(db, welt):
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    dienst.verarbeiten(db, konto, nachricht, _antwortmail(wer="fremd@example.net"))
    dienst.verarbeiten(
        db, konto, nachricht, _antwortmail(wer="fremd@example.net", stand="DECLINED")
    )

    vermerkt = json.loads(termin.fremde_antworten)
    assert len(vermerkt) == 1
    assert vermerkt[0]["antwort"] == "DECLINED"


def test_die_liste_waechst_nicht_unbegrenzt(db, welt):
    """⚠️ Sonst waechst sie, solange jemand schickt."""
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    for n in range(dienst.FREMDE_HOECHSTENS + 3):
        dienst.verarbeiten(db, konto, nachricht, _antwortmail(wer=f"nr{n}@example.net"))

    vermerkt = json.loads(termin.fremde_antworten)
    assert len(vermerkt) == dienst.FREMDE_HOECHSTENS
    # Die aeltesten sind weg, die neuesten da.
    assert vermerkt[-1]["adresse"] == f"nr{dienst.FREMDE_HOECHSTENS + 2}@example.net"


def test_eine_uebernommene_antwort_wird_nicht_als_fremd_vermerkt(db, welt):
    person, konto, termin = welt  # noqa: F811
    nachricht = _nachricht(db, konto, konto.ordner[0].id)

    assert dienst.verarbeiten(db, konto, nachricht, _antwortmail()) is True
    assert json.loads(termin.fremde_antworten) == []
