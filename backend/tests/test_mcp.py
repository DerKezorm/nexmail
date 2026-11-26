"""nexmails KI-Werkzeuge (Modul mcp 1.1.0): der Pflichttest je Werkzeug und was nur nexmail hat.

Die Vertragstests des Moduls (``tests/nexmcp``) pruefen Protokoll, Waende, Rechte, Rueckfragen und OAuth ueber die
echten Wege. Hier steht, was nexmails Werkzeuge versprechen (Bauplan „Entwurf MCP-Modul“, nexmail):

* jedes Werkzeug sieht nur, was das Konto sieht, und nur die Postfaecher am Schluessel; alles andere ist „Not found.“;
* Mailtext nur mit dem Extra „Mailtext lesen“ (ab Werk aus), und die Suche sucht nie im Text;
* Entwuerfe landen im Ordner „Entwürfe“, gesendet wird nie;
* lesen mit ``read``, entwerfen erst ab ``draft``, aendern erst mit ``write``;
* kein Inhalt im Log; verbundene Programme enden beim Sperren (E42), MCP-Schluessel ruhen und gehen danach wieder.

Wege, die den Mailserver brauchen (Entwurf ablegen, Schlagwort setzen, verschieben), laufen hier ueber die Dienste der
Oberflaeche mit einem Ersatz an ihrer Stelle: geprueft wird, was das Werkzeug ihnen gibt.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent / "nexmcp"))

from mcp_contract import call, connect, mcp_key, names, rpc, switch_mcp  # noqa: E402
from nexmcp_adapter import Adapter  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Aufgabe, McpSchluessel, Nachricht, Ordner, Schlagwort  # noqa: E402


@pytest.fixture
def app():
    adapter = Adapter()
    from app.vendor.nexmcp import brake

    brake.BRAKE.forget()
    adapter.start()
    switch_mcp(adapter, True)
    try:
        yield adapter
    finally:
        adapter.stop()
        brake.BRAKE.forget()


def _schluessel(app: Any, stufe: str = "write", **mehr: Any) -> str:
    return mcp_key(app, right=stufe, **mehr)["secret"]


def _text(antwort: dict) -> str:
    return antwort["content"][0]["text"]


def _ordner_von(app: Any, rolle: str) -> int:
    with SessionLocal() as db:
        return db.query(Ordner).filter(Ordner.konto_id == app.postfach[rolle]).first().id


# --- sehen, was das Konto sieht ----------------------------------------------------------------------------------------


def test_lesen_sieht_nur_die_postfaecher_am_schluessel(app):
    geheim = _schluessel(app, "read")
    zusammen = call(app, geheim, "mailbox_summary", {})["structuredContent"]
    assert [p["id"] for p in zusammen["mailboxes"]] == [app.postfach["owner"]]
    assert zusammen["unread"] == 1
    gefunden = call(app, geheim, "search_messages", {})["structuredContent"]["messages"]
    assert [m["id"] for m in gefunden] == [app.mail["owner"]]
    for name, argumente in (
        ("search_messages", {"mailbox_id": app.postfach["other"]}),
        ("search_messages", {"folder_id": _ordner_von(app, "other")}),
        ("complete_task", {"task_id": 999_999}),
        ("move_message", {"message_id": app.mail["other"], "folder_id": _ordner_von(app, "owner")}),
        ("move_message", {"message_id": app.mail["owner"], "folder_id": _ordner_von(app, "other")}),
        ("set_tags", {"message_id": app.mail["other"], "add": [1]}),
    ):
        stufe_hoch = _schluessel(app, "write")
        antwort = call(app, stufe_hoch, name, argumente)
        assert antwort["isError"] and _text(antwort) == "Not found.", (name, antwort)


def test_ein_postfach_nicht_am_schluessel_ist_auch_fuer_das_eigene_konto_unbekannt(app):
    """Ein zweites Postfach des Kontos, nicht am Schluessel: seine Mails findet das Werkzeug nicht."""
    from app.models import Konto

    with SessionLocal() as db:
        zweites = Konto(
            benutzer_id=app.ids["owner"],
            anzeigename="Arbeit",
            adresse="arbeit@example.com",
            imap_server="imap.example.com",
            imap_benutzer="o",
            smtp_server="smtp.example.com",
            smtp_benutzer="o",
        )
        db.add(zweites)
        db.commit()
        zweites_id = zweites.id
    geheim = _schluessel(app, "read")
    antwort = call(app, geheim, "search_messages", {"mailbox_id": zweites_id})
    assert antwort["isError"] and _text(antwort) == "Not found."


def test_mailtext_nur_mit_dem_extra_und_die_suche_sucht_nie_im_text(app, monkeypatch):
    ohne = _schluessel(app, "read")
    assert "read_message" not in names(app, ohne)
    antwort = call(app, ohne, "read_message", {"message_id": app.mail["owner"]})
    assert antwort["isError"] and _text(antwort) == "No tool called 'read_message'."
    # Das Wort steht nur im Text der Mail (``Milch``): die Suche findet es nicht, und ein Feld fuer Text gibt es nicht.
    assert call(app, ohne, "search_messages", {"subject": "Milch"})["structuredContent"]["messages"] == []
    assert call(app, ohne, "search_messages", {"text": "Milch"})["isError"]

    from app.routers import nachrichten

    with SessionLocal() as db:
        db.get(Nachricht, app.mail["owner"]).koerper_geholt = __import__("datetime").datetime.now()
        db.commit()
    monkeypatch.setattr(nachrichten, "_koerper_sicherstellen", lambda db, n: None)
    mit = _schluessel(app, "read", options={"mailtext": True})
    gelesen = call(app, mit, "read_message", {"message_id": app.mail["owner"]})["structuredContent"]
    assert gelesen["text"] == "Milch" and gelesen["attachments"] == 0
    fremd = call(app, mit, "read_message", {"message_id": app.mail["other"]})
    assert fremd["isError"] and _text(fremd) == "Not found."


def test_die_stufen_trennen_lesen_entwerfen_aendern(app):
    lesen = names(app, _schluessel(app, "read"))
    entwerfen = names(app, _schluessel(app, "draft"))
    aendern = names(app, _schluessel(app, "write"))
    assert {"mailbox_summary", "search_messages", "list_tags", "list_tasks"} <= lesen
    assert not lesen & {"draft_reply", "create_draft", "set_tags", "move_message", "complete_task"}
    assert {"draft_reply", "create_draft"} <= entwerfen and not entwerfen & {"set_tags", "move_message", "complete_task"}
    assert {"set_tags", "move_message", "complete_task"} <= aendern
    # Senden gibt es nicht, auf keiner Stufe.
    assert not any("send" in name for name in aendern)


# --- entwerfen: nie senden ---------------------------------------------------------------------------------------------


def test_ein_entwurf_landet_im_postfach_und_geht_nie_hinaus(app, monkeypatch):
    from app.services import entwuerfe, senden

    abgelegt: list[Any] = []
    monkeypatch.setattr(entwuerfe, "ablegen", lambda db, konto, entwurf, ersetzt=None: abgelegt.append((konto.id, entwurf)) or 7)
    monkeypatch.setattr(senden, "senden", lambda *a, **k: pytest.fail("ein Werkzeug hat gesendet"), raising=False)
    geheim = _schluessel(app, "draft")
    antwort = call(
        app,
        geheim,
        "create_draft",
        {"mailbox_id": app.postfach["owner"], "to": ["kim@example.com"], "subject": "Hallo", "text": "Erste <Zeile>"},
    )["structuredContent"]
    assert antwort == {"stored": True, "mailbox_id": app.postfach["owner"], "draft_uid": 7, "sent": False}
    konto_id, entwurf = abgelegt[0]
    assert konto_id == app.postfach["owner"] and entwurf.von_adresse == "owner@example.com"
    assert entwurf.an == ["kim@example.com"] and "&lt;Zeile&gt;" in entwurf.html
    fremd = call(app, geheim, "create_draft", {"mailbox_id": app.postfach["other"]})
    assert fremd["isError"] and _text(fremd) == "Not found."


def test_eine_antwort_als_entwurf_zitiert_und_haengt_an_die_kette(app, monkeypatch):
    from app.routers import verfassen as verfassen_router
    from app.services import entwuerfe

    roh = (
        b"From: Kim <kim@example.com>\r\nTo: owner@example.com\r\nSubject: Frage\r\n"
        b"Message-ID: <frage@example.com>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nGeht morgen?\r\n"
    )
    monkeypatch.setattr(verfassen_router, "_roh", lambda db, konto, nachricht: roh)
    abgelegt: list[Any] = []
    monkeypatch.setattr(entwuerfe, "ablegen", lambda db, konto, entwurf, ersetzt=None: abgelegt.append(entwurf) or 3)
    geheim = _schluessel(app, "draft")
    antwort = call(app, geheim, "draft_reply", {"message_id": app.mail["owner"], "text": "Ja, gern."})
    assert not antwort["isError"], antwort
    entwurf = abgelegt[0]
    assert entwurf.an == ["kim@example.com"] and entwurf.in_reply_to == "<frage@example.com>"
    assert entwurf.betreff == "AW: Frage" and "Ja, gern." in entwurf.html and "Geht morgen?" in entwurf.html


# --- aendern -----------------------------------------------------------------------------------------------------------


def test_schlagworte_gehen_ueber_den_dienst_der_oberflaeche(app, monkeypatch):
    from app.services import schlagworte

    with SessionLocal() as db:
        eigenes = Schlagwort(benutzer_id=app.ids["owner"], name="Wichtig", atom="$label1")
        fremdes = Schlagwort(benutzer_id=app.ids["other"], name="Fremd", atom="$label2")
        db.add_all([eigenes, fremdes])
        db.commit()
        eigen_id, fremd_id = eigenes.id, fremdes.id
    gesetzt: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        schlagworte, "zuweisen", lambda db, person, mails, atom, setzen: gesetzt.append((atom, setzen)) or len(mails)
    )
    geheim = _schluessel(app, "write")
    assert [t["id"] for t in call(app, geheim, "list_tags", {})["structuredContent"]["tags"]] == [eigen_id]
    antwort = call(app, geheim, "set_tags", {"message_id": app.mail["owner"], "add": [eigen_id], "remove": [eigen_id]})
    assert not antwort["isError"], antwort
    assert gesetzt == [("$label1", True), ("$label1", False)]
    fremd = call(app, geheim, "set_tags", {"message_id": app.mail["owner"], "add": [fremd_id]})
    assert fremd["isError"] and _text(fremd) == "Not found."


def test_verschieben_geht_ueber_den_dienst_der_oberflaeche(app, monkeypatch):
    from app.services import handeln

    with SessionLocal() as db:
        archiv = Ordner(konto_id=app.postfach["owner"], pfad="Archive", name="Archiv", rolle="archiv")
        db.add(archiv)
        db.commit()
        archiv_id = archiv.id
    bewegt: list[tuple[list[int], int]] = []
    monkeypatch.setattr(handeln, "verschieben", lambda db, mails, ziel, text="": bewegt.append(([m.id for m in mails], ziel.id)))
    geheim = _schluessel(app, "write")
    antwort = call(app, geheim, "move_message", {"message_id": app.mail["owner"], "folder_id": archiv_id})
    assert antwort["structuredContent"]["folder"] == "Archiv"
    assert bewegt == [([app.mail["owner"]], archiv_id)]


def test_eine_aufgabe_abhaken_und_wieder_oeffnen(app):
    geheim = _schluessel(app, "write")
    erledigt = call(app, geheim, "complete_task", {"task_id": app.aufgabe})["structuredContent"]
    assert erledigt["done"] is True
    offen = call(app, geheim, "complete_task", {"task_id": app.aufgabe, "done": False})["structuredContent"]
    assert offen["done"] is False
    with SessionLocal() as db:
        assert db.get(Aufgabe, app.aufgabe).erledigt is None
    listed = call(app, geheim, "list_tasks", {"open_only": True})["structuredContent"]["tasks"]
    assert all(t["mailbox_id"] == app.postfach["owner"] for t in listed)


# --- Log, Sperre, Schalter ---------------------------------------------------------------------------------------------


def test_kein_inhalt_im_log(app, caplog):
    geheim = _schluessel(app, "write")
    with caplog.at_level(logging.DEBUG):
        call(app, geheim, "search_messages", {"subject": "Einkaufsliste"})
        call(app, geheim, "complete_task", {"task_id": app.aufgabe})
    text = caplog.text
    assert "Einkaufsliste" not in text and "Milch" not in text and geheim not in text


def test_sperren_trennt_programme_und_laesst_schluessel_ruhen(app):
    geheim = _schluessel(app, "read")
    _, tokens = connect(app)
    assert rpc(app, tokens["access_token"], "ping").status_code == 200
    betreiber = app.client("operator")
    passwort = {"passwort": "betreib-geheim-789"}
    assert betreiber.post(f"/api/benutzer/{app.ids['owner']}/sperren", json=passwort).status_code == 200
    assert rpc(app, geheim, "ping").status_code == 401
    assert rpc(app, tokens["access_token"], "ping").status_code == 401
    with SessionLocal() as db:
        assert db.query(McpSchluessel).filter(McpSchluessel.programm_id.is_not(None)).count() == 0
    assert betreiber.post(f"/api/benutzer/{app.ids['owner']}/entsperren", json=passwort).status_code == 200
    assert rpc(app, geheim, "ping").status_code == 200
    assert rpc(app, tokens["access_token"], "ping").status_code == 401


def test_mcp_ist_ab_werk_aus_und_bleibt_es_nach_dem_update(app):
    """MCP-Entscheidung 5: nexmail hatte kein MCP; eine Installation von vorher startet wie eine neue mit „aus“."""
    from app.db import einstellung_lesen

    switch_mcp(app, False)
    with SessionLocal() as db:
        assert einstellung_lesen(db, "mcp_zugang") == "0"
    neu = Adapter()
    with SessionLocal() as db:
        from app.models import Einstellung

        db.query(Einstellung).filter(Einstellung.schluessel == "mcp_zugang").delete()
        db.commit()
    assert neu.keys_config().kind("mcp") is not None
    assert app.client("operator").get("/api/connections/interfaces").json()["mcp"] is False


def test_die_seite_kennt_jedes_werkzeug_des_servers():
    """``frontend/src/lib/mcpWorte.ts`` nennt jedes Werkzeug mit einem Wort (DE/EN prueft vitest); ein neues Werkzeug
    ohne Wort stuende sonst englisch in „Rechte je Werkzeug“."""
    import re

    from app.services.mcp_werkzeuge import MCP

    quelle = (Path(__file__).parents[2] / "frontend" / "src" / "lib" / "mcpWorte.ts").read_text(encoding="utf-8")
    liste = re.search(r"WERKZEUGE = \[(.*?)\] as const", quelle, re.S)
    assert liste is not None
    genannt = set(re.findall(r"'([a-z_]+)'", liste.group(1)))
    assert genannt == {tool.name for tool in MCP.tools} | {"request_status"}


def test_eine_wartende_rueckfrage_kommt_als_mitteilung_in_den_browser(app, monkeypatch):
    """MCP 14: nexmail hat keine Glocke, aber Mitteilungen im Browser; „Ein Programm wartet auf dein Ja“ geht dorthin,
    mit der Seite der Rückfrage als Ziel, nie mit Argumenten aus Mails, nie an die iPhone-App."""
    from app.models import PushAnmeldung
    from app.services import push

    with SessionLocal() as db:
        db.add(PushAnmeldung(benutzer_id=app.ids["owner"], endpunkt="https://push.example.com/a", p256dh="x", auth="y"))
        db.commit()
    gesendet: list[Any] = []
    monkeypatch.setattr(push, "zustellen", lambda db, anmeldung, meldung: gesendet.append(meldung))
    monkeypatch.setattr(push, "an_geraet", lambda *a, **k: pytest.fail("an die iPhone-App"))
    made = mcp_key(app, right="write")
    name, args = app.change_call()
    app.client("owner").put(f"{app.prefix}/keys/{made['key']['id']}/rights", json={"rights": {name: "ask"}})
    wartet = call(app, made["secret"], name, args)["structuredContent"]
    assert wartet["status"] == "waiting"
    assert len(gesendet) == 1
    meldung = gesendet[0]
    assert meldung.ziel == f"/mcp/requests/{wartet['request']}" and "Probe" in meldung.text
    assert "Einkaufsliste" not in meldung.text


def test_die_zeile_der_rueckfrage_spricht_die_sprache_des_kontos_und_nennt_namen(app):
    """mcp 1.1.1 (M-12): „Was es tun will“ nennt die Aufgabe beim Namen, in der Sprache des Kontos; ein Ding eines
    anderen Kontos bleibt eine Nummer."""
    from app.models import Benutzer, McpAnfrage

    with SessionLocal() as db:
        db.get(Benutzer, app.ids["owner"]).sprache = "de"
        db.commit()
    made = mcp_key(app, right="write")
    name, args = app.change_call()
    assert name == "complete_task"
    app.client("owner").put(f"{app.prefix}/keys/{made['key']['id']}/rights", json={"rights": {name: "ask"}})
    assert call(app, made["secret"], name, args)["structuredContent"]["status"] == "waiting"
    with SessionLocal() as db:
        zeile = db.query(McpAnfrage).order_by(McpAnfrage.id.desc()).first().zusammenfassung
    assert zeile == "Aufgabe „Einkaufsliste von owner“ abhaken"

    with SessionLocal() as db:
        fremd = Aufgabe(benutzer_id=app.ids["other"], betreff="Geheimes von other")
        db.add(fremd)
        db.commit()
        fremd_id = fremd.id
    assert call(app, made["secret"], name, {"task_id": fremd_id})["structuredContent"]["status"] == "waiting"
    with SessionLocal() as db:
        zeile = db.query(McpAnfrage).order_by(McpAnfrage.id.desc()).first().zusammenfassung
    assert zeile == f"Aufgabe „#{fremd_id}“ abhaken"
