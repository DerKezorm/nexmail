"""Entwürfe im Postfach.

⚠️ **Der teure Fall ist nicht „wird gespeichert", sondern „wird ersetzt".** Wer
an einer Mail zehnmal weiterschreibt, hat sonst zehn Fassungen im Ordner und
weiß nicht, welche die aktuelle ist. Und nach dem Senden muss der Entwurf
verschwinden, sonst steht dieselbe Nachricht zweimal im Postfach.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Nachricht, Ordner
from app.services import entwuerfe, verfassen
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture


def _entwurf(betreff: str = "Angefangen", an: list[str] | None = None) -> verfassen.Entwurf:
    return verfassen.Entwurf(
        von_name="Ich",
        von_adresse="ich@example.org",
        an=an if an is not None else [],
        kopie=[],
        blindkopie=[],
        betreff=betreff,
        html="<p>halb fertig</p>",
        text="halb fertig",
        anlagen=[],
        in_reply_to="",
        references=[],
    )


@pytest.fixture
def entwurfsordner(db, konto, monkeypatch):  # noqa: F811
    """Ein Postfach mit Entwurfsordner und einem Server, der wirklich ablegt."""
    db.add(Ordner(konto_id=konto.id, pfad="Drafts", name="Drafts", rolle="entwuerfe"))
    db.commit()
    db.refresh(konto)

    server = FalscherServer()
    server.anlegen("Drafts")
    server.kennzeichen: list = []
    server.geloescht: list = []

    def append(pfad, roh, flags, zeitpunkt):  # noqa: ARG001
        server.kennzeichen.append(list(flags))
        # ⚠️ Der Doppelgänger muss die Nachricht wirklich behalten - sonst
        # prüft der Abgleich danach gegen einen leeren Ordner, und der Test
        # besteht hohl.
        neue = max((u for u, _ in server.ordner["Drafts"]["nachrichten"].items()), default=0) + 1
        server.einwerfen(pfad, neue, "Angefangen", gelesen=True, roh=roh)

    def add_flags(uids, flags):
        if any(b"Deleted" in f for f in flags):
            server.geloescht.extend(uids)

    def uid_expunge(uids):
        for u in uids:
            server.ordner["Drafts"]["nachrichten"].pop(u, None)

    server.append = append
    server.add_flags = add_flags
    server.uid_expunge = uid_expunge
    monkeypatch.setattr(entwuerfe.imapdienst, "verbinden", lambda *a, **k: server)
    return konto, server


def _im_ordner(db, konto) -> list[Nachricht]:  # noqa: F811
    ordner = (
        db.execute(select(Ordner).where(Ordner.konto_id == konto.id, Ordner.rolle == "entwuerfe"))
        .scalars()
        .one()
    )
    return db.execute(select(Nachricht).where(Nachricht.ordner_id == ordner.id)).scalars().all()


def test_entwurf_landet_im_postfach(db, entwurfsordner):
    """Nicht im Browser — beim Anbieter, sonst ist er auf dem Telefon nicht da."""
    konto, server = entwurfsordner

    uid = entwuerfe.ablegen(db, konto, _entwurf())

    assert uid > 0
    assert len(_im_ordner(db, konto)) == 1
    assert len(server.kennzeichen) == 1


def test_entwurf_wird_als_entwurf_gekennzeichnet(db, entwurfsordner):
    r"""⚠️ Ohne ``\Draft`` bietet kein anderer Client das Weiterschreiben an."""
    konto, server = entwurfsordner

    entwuerfe.ablegen(db, konto, _entwurf())

    gesetzt = b" ".join(server.kennzeichen[0])
    assert b"Draft" in gesetzt


def test_zweites_speichern_ersetzt_statt_zu_haeufen(db, entwurfsordner):
    """⚠️ **Der eigentliche Test.**

    Wer an einer Mail weiterschreibt, will eine Fassung im Ordner sehen, nicht
    zehn. Ohne das Wegwerfen der alten Fassung wächst der Entwurfsordner mit
    jedem Tastendruck-Intervall.
    """
    konto, _ = entwurfsordner

    erste = entwuerfe.ablegen(db, konto, _entwurf("Erster Wurf"))
    entwuerfe.ablegen(db, konto, _entwurf("Zweiter Wurf"), ersetzt_uid=erste)

    liegen = _im_ordner(db, konto)
    assert len(liegen) == 1, f"Es liegen {len(liegen)} Fassungen im Entwurfsordner statt einer."


def test_ein_entwurf_braucht_keinen_empfaenger(db, entwurfsordner):
    """Genau das unterscheidet ihn von einer Mail — man fängt oft beim Text an."""
    konto, _ = entwurfsordner

    entwuerfe.ablegen(db, konto, _entwurf(an=[]))

    assert len(_im_ordner(db, konto)) == 1


def test_wegwerfen_raeumt_ihn_ab(db, entwurfsordner):
    """Nach dem Senden muss er weg — sonst steht die Mail zweimal im Postfach."""
    konto, _ = entwurfsordner

    uid = entwuerfe.ablegen(db, konto, _entwurf())
    entwuerfe.wegwerfen(db, konto, uid)

    assert _im_ordner(db, konto) == []


def test_ohne_entwurfsordner_kommt_ein_lesbarer_satz(db, konto, monkeypatch):  # noqa: F811
    """Kein Absturz, sondern eine Anweisung — der Betreiber ist nicht der Entwickler."""
    monkeypatch.setattr(entwuerfe.imapdienst, "verbinden", lambda *a, **k: FalscherServer())

    with pytest.raises(entwuerfe.EntwurfFehler) as fehler:
        entwuerfe.ablegen(db, konto, _entwurf())

    assert "Entwurfsordner" in str(fehler.value)


def test_eine_gescheiterte_aufraeumung_kostet_nicht_den_text(db, entwurfsordner):
    """⚠️ Die neue Fassung liegt schon auf dem Server, wenn die alte wegfällt.

    Bricht das Wegwerfen ab, ist eine Fassung zu viel da — ärgerlich. Wer hier
    durchreicht, nimmt dem Betreiber stattdessen den gerade geschriebenen Text.
    """
    konto, server = entwurfsordner
    erste = entwuerfe.ablegen(db, konto, _entwurf("Erster Wurf"))

    def bockig(uids, flags):  # noqa: ARG001
        raise RuntimeError("Der Server mag gerade nicht.")

    server.add_flags = bockig

    # Kein Fehler nach außen, und die neue Fassung ist da.
    entwuerfe.ablegen(db, konto, _entwurf("Zweiter Wurf"), ersetzt_uid=erste)
    assert len(_im_ordner(db, konto)) == 2
