"""Schlagworte über ``/api/v1``, für den Empfänger eines Webhooks (Issue #17).

Der Melder hakt Aufgaben in seiner Praxissoftware ab und will dabei an der
Mail ein Schlagwort „traité" setzen. Was hier steht, sind die Zusagen an ihn:
ein eigenes Recht am Schlüssel, die Kennung statt des Namens, erst der
Mailserver und dann nexmail, jede Fassung der Mail im Postfach, und kein
Ereignis zurück an den Webhook.
"""

from __future__ import annotations

import json

import pytest

from app.models import Aufgabe, Nachricht, Ordner
from app.services import imap as imapdienst
from test_aufgaben import ohne_netz, welt  # noqa: F401
from test_konten import _eingabe
from test_webhook import _anlegen, _ziel, empfaenger, verbunden  # noqa: F401


class Klient:
    """Ein Mailserver, der STORE annimmt und mitschreibt."""

    def __init__(self) -> None:
        self.protokoll: list[str] = []
        self.ordner = ""
        self.mit_stern = True

    def select_folder(self, pfad, readonly=False):
        self.ordner = pfad
        perma = (b"\\Seen", b"\\*") if self.mit_stern else (b"\\Seen", b"\\Flagged")
        return {b"PERMANENTFLAGS": perma}

    def add_flags(self, uids, flags):
        self.protokoll.append(f"{self.ordner} +{[f.decode() for f in flags]} {sorted(uids)}")

    def remove_flags(self, uids, flags):
        self.protokoll.append(f"{self.ordner} -{[f.decode() for f in flags]} {sorted(uids)}")

    def logout(self):
        pass


@pytest.fixture
def server(monkeypatch):
    k = Klient()
    monkeypatch.setattr(imapdienst, "fuer_konto", lambda db, konto, *a, **kw: k)
    return k


def _schluessel(klient, konto_id, *, aufgaben=False, schlagworte=True) -> dict:
    assert klient.put("/api/apischluessel/erlaubt", json={"erlaubt": True}).status_code == 200
    antwort = klient.post(
        "/api/apischluessel",
        json={
            "name": "Praxis",
            "stufe": "anzahl",
            "konten": [konto_id],
            "aufgaben": aufgaben,
            "schlagworte": schlagworte,
        },
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["schlagworte"] is schlagworte
    return {"Authorization": f"Bearer {antwort.json()['schluessel']}"}


def _schlagwort(klient, name: str) -> dict:
    antwort = klient.post("/api/schlagworte", json={"name": name})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _atome(db, nachricht_id) -> list[str]:
    db.expire_all()
    return json.loads(db.get(Nachricht, nachricht_id).schlagworte or "[]")


# --- Lesen ------------------------------------------------------------------ #


def test_die_liste_nennt_kennung_name_und_keyword(klient, welt):  # noqa: F811
    konto_id, _, _ = welt
    traite = _schlagwort(klient, "traité")
    kopf = _schluessel(klient, konto_id)

    assert klient.get("/api/v1/me", headers=kopf).json()["key"]["tags"] is True
    antwort = klient.get("/api/v1/tags", headers=kopf)
    assert antwort.status_code == 200, antwort.text
    # ⚠️ Aus „traité" wird das Keyword „trait": Wer nach dem Namen sucht,
    # findet es auf dem Server nicht. Deshalb die Kennung.
    assert antwort.json() == {"tags": [{"id": traite["id"], "name": "traité", "keyword": "trait"}]}


def test_ohne_das_recht_gibt_es_keine_schlagworte(klient, verbunden, welt, server):  # noqa: F811
    konto_id, _, ids = welt
    traite = _schlagwort(klient, "traité")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id, aufgaben=True, schlagworte=False)

    assert klient.get("/api/v1/me", headers=kopf).json()["key"]["tags"] is False
    for antwort in (
        klient.get("/api/v1/tags", headers=kopf),
        klient.get(f"/api/v1/tasks/{aid}/tags", headers=kopf),
        klient.post(f"/api/v1/tasks/{aid}/tags/{traite['id']}", headers=kopf),
        klient.delete(f"/api/v1/tasks/{aid}/tags/{traite['id']}", headers=kopf),
    ):
        assert antwort.status_code == 403
        assert antwort.json()["detail"] == "api_schluessel_ohne_schlagworte"
    assert server.protokoll == []


def test_das_schlagwortrecht_hakt_nicht_ab(klient, verbunden, welt):  # noqa: F811
    konto_id, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id, aufgaben=False, schlagworte=True)
    antwort = klient.post(f"/api/v1/tasks/{aid}/complete", headers=kopf)
    assert antwort.json()["detail"] == "api_schluessel_ohne_aufgaben"


def test_eine_sitzung_oeffnet_die_schlagworte_unter_v1_nicht(klient, welt):  # noqa: F811
    assert klient.get("/api/v1/tags").status_code == 401


# --- Setzen und nehmen --------------------------------------------------------- #


def test_setzen_schreibt_zum_server_und_dann_lokal_ohne_echo(klient, verbunden, welt, server, empfaenger, db):  # noqa: F811
    konto_id, posteingang, ids = welt
    traite = _schlagwort(klient, "traité")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    aufrufe = len(empfaenger.aufrufe)

    antwort = klient.post(f"/api/v1/tasks/{aid}/tags/{traite['id']}", headers=kopf)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {
        "task_id": str(aid),
        "tags": [{"id": traite["id"], "name": "traité", "keyword": "trait"}],
    }
    uid = db.get(Nachricht, ids[0]).uid
    assert server.protokoll == [f"{posteingang.pfad} +['trait'] [{uid}]"]
    assert _atome(db, ids[0]) == ["trait"]
    # Die anderen Mails bleiben, wie sie waren.
    assert _atome(db, ids[1]) == []
    assert klient.get(f"/api/v1/tasks/{aid}/tags", headers=kopf).json()["tags"][0]["id"] == traite["id"]
    # ⚠️ Kein Ereignis zurück an den, der gerade selbst gesetzt hat.
    assert len(empfaenger.aufrufe) == aufrufe

    weg = klient.delete(f"/api/v1/tasks/{aid}/tags/{traite['id']}", headers=kopf)
    assert weg.status_code == 200, weg.text
    assert weg.json()["tags"] == []
    assert server.protokoll[-1] == f"{posteingang.pfad} -['trait'] [{uid}]"
    assert _atome(db, ids[0]) == []


def test_jede_fassung_der_mail_im_postfach_bekommt_es(klient, verbunden, welt, server, db):  # noqa: F811
    konto_id, posteingang, ids = welt
    archiv = Ordner(konto_id=konto_id, pfad="Archiv", name="Archiv", rolle="archiv")
    db.add(archiv)
    db.flush()
    erste = db.get(Nachricht, ids[0])
    kopie = Nachricht(
        benutzer_id=erste.benutzer_id,
        konto_id=konto_id,
        ordner_id=archiv.id,
        uid=900,
        message_id=erste.message_id,
        betreff=erste.betreff,
        datum=erste.datum,
    )
    db.add(kopie)
    db.commit()
    kopie_id = kopie.id

    wichtig = _schlagwort(klient, "Wichtig")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    assert klient.post(f"/api/v1/tasks/{aid}/tags/{wichtig['id']}", headers=kopf).status_code == 200

    assert sorted(server.protokoll) == sorted(
        [f"{posteingang.pfad} +['Wichtig'] [{erste.uid}]", "Archiv +['Wichtig'] [900]"]
    )
    assert _atome(db, ids[0]) == ["Wichtig"]
    assert _atome(db, kopie_id) == ["Wichtig"]


def test_ein_zweites_postfach_bleibt_unberuehrt(klient, verbunden, welt, server, db):  # noqa: F811
    """Dieselbe Mail an zwei eigene Adressen: Geschrieben wird nur im Postfach
    der Aufgabe. Das zweite steht vielleicht gar nicht am Schlüssel."""
    konto_id, posteingang, ids = welt
    zweites = klient.post("/api/konten", json=_eingabe("zweite@example.com")).json()["id"]
    dort = db.query(Ordner).filter(Ordner.konto_id == zweites, Ordner.rolle == "posteingang").one()
    erste = db.get(Nachricht, ids[0])
    fremd = Nachricht(
        benutzer_id=erste.benutzer_id,
        konto_id=zweites,
        ordner_id=dort.id,
        uid=901,
        message_id=erste.message_id,
        betreff=erste.betreff,
        datum=erste.datum,
    )
    db.add(fremd)
    db.commit()
    fremd_id = fremd.id

    wichtig = _schlagwort(klient, "Wichtig")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    assert klient.post(f"/api/v1/tasks/{aid}/tags/{wichtig['id']}", headers=kopf).status_code == 200

    assert server.protokoll == [f"{posteingang.pfad} +['Wichtig'] [{erste.uid}]"]
    assert _atome(db, fremd_id) == []


@pytest.mark.parametrize("falsch", ["999999", "abc", "-1"])
def test_ein_unbekanntes_schlagwort_ist_404(klient, verbunden, welt, server, falsch):  # noqa: F811
    konto_id, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    antwort = klient.post(f"/api/v1/tasks/{aid}/tags/{falsch}", headers=kopf)
    assert antwort.status_code == 404
    assert antwort.json()["detail"] == "schlagwort_unbekannt"
    assert server.protokoll == []


def test_eine_fremde_aufgabe_ist_unbekannt(klient, verbunden, welt, server, db):  # noqa: F811
    konto_id, _, ids = welt
    wichtig = _schlagwort(klient, "Wichtig")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    for falsch in ("999999", "abc"):
        antwort = klient.post(f"/api/v1/tasks/{falsch}/tags/{wichtig['id']}", headers=kopf)
        assert antwort.json()["detail"] == "aufgabe_unbekannt"
    # Das Postfach fällt vom Schlüssel: dieselbe Aufgabe ist unbekannt.
    a = db.get(Aufgabe, aid)
    a.konto_id = "anderes-postfach"
    db.commit()
    assert klient.post(f"/api/v1/tasks/{aid}/tags/{wichtig['id']}", headers=kopf).status_code == 404
    assert server.protokoll == []


def test_ohne_mail_ist_es_409(klient, verbunden, welt, server, db):  # noqa: F811
    konto_id, _, ids = welt
    wichtig = _schlagwort(klient, "Wichtig")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)
    db.delete(db.get(Nachricht, ids[0]))
    db.commit()

    antwort = klient.post(f"/api/v1/tasks/{aid}/tags/{wichtig['id']}", headers=kopf)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "aufgabe_ohne_mail"
    assert klient.get(f"/api/v1/tasks/{aid}/tags", headers=kopf).status_code == 409
    assert server.protokoll == []


def test_nimmt_der_server_keine_keywords_bleibt_lokal_alles(klient, verbunden, welt, server, db):  # noqa: F811
    konto_id, _, ids = welt
    server.mit_stern = False
    wichtig = _schlagwort(klient, "Wichtig")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)

    antwort = klient.post(f"/api/v1/tasks/{aid}/tags/{wichtig['id']}", headers=kopf)
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "schlagworte_nicht_unterstuetzt"
    assert _atome(db, ids[0]) == []


def test_ein_nicht_erreichbarer_server_ist_502(klient, verbunden, welt, db, monkeypatch):  # noqa: F811
    konto_id, _, ids = welt
    wichtig = _schlagwort(klient, "Wichtig")
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    kopf = _schluessel(klient, konto_id)

    def tot(*a, **k):
        raise imapdienst.Verbindungsfehler(imapdienst.Fehlerart.UNERWARTET, "Weg.", "weg")

    monkeypatch.setattr(imapdienst, "fuer_konto", tot)
    antwort = klient.post(f"/api/v1/tasks/{aid}/tags/{wichtig['id']}", headers=kopf)
    assert antwort.status_code == 502
    assert _atome(db, ids[0]) == []


# --- Im Webhook ------------------------------------------------------------- #


def test_der_webhook_nennt_die_schlagworte_der_mail(klient, verbunden, welt, empfaenger, db):  # noqa: F811
    konto_id, _, ids = welt
    wichtig = _schlagwort(klient, "Wichtig")
    _schlagwort(klient, "Später")
    mail = db.get(Nachricht, ids[0])
    # Ein technisches Keyword ist kein Schlagwort und bleibt draußen.
    mail.schlagworte = json.dumps(["wichtig", "$Forwarded"])
    db.commit()

    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    (rumpf,) = empfaenger.rumpfe("task.created")
    # ⚠️ Ohne Groß/klein, wie IMAP vergleicht.
    assert rumpf["message"]["tags"] == [{"id": wichtig["id"], "name": "Wichtig", "keyword": "Wichtig"}]

    assert klient.patch(f"/api/aufgaben/{aid}", json={"erledigt": True}).status_code == 200, "abhaken"
    (zu,) = empfaenger.rumpfe("task.completed")
    assert zu["message"]["tags"] == rumpf["message"]["tags"]


def test_ohne_mail_sind_die_schlagworte_null(klient, verbunden, welt, empfaenger, db):  # noqa: F811
    _, _, ids = welt
    aid = _anlegen(klient, ids[0], _ziel(verbunden)).json()["aufgabe"]["id"]
    assert empfaenger.rumpfe("task.created")[0]["message"]["tags"] == []
    db.delete(db.get(Nachricht, ids[0]))
    db.commit()

    assert klient.patch(f"/api/aufgaben/{aid}", json={"erledigt": True}).status_code == 200
    (zu,) = empfaenger.rumpfe("task.completed")
    # ⚠️ ``null``, nicht ``[]``: Ob die Mail Schlagworte trägt, weiß keiner mehr.
    assert zu["message"]["tags"] is None
