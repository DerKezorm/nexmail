"""MAIL-2: nextasks in der Aufgabenansicht, die eigene Liste und ihr Umzug.

Gesprochen wird mit demselben nachgebauten nextasks wie in
``test_nextasks.py`` (``Nextasks``), gebaut nach nextasks' ``docs/api.md``.
⚠️ **Das prüft nexmails Logik, nicht nextasks** (FALLSTRICKE §8): Ob nextasks
die Felder so versteht, sagt erst ein Lauf gegen eine echte Instanz.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import crypto
from app.models import Aufgabe, Aufgabenverbindung, Benutzer, Nachricht
from app.services import aufgabenziele, nextasks, todoist, webhook
from conftest import anmelden, zweiten_benutzer_anlegen
from test_aufgaben import ohne_netz, welt  # noqa: F401
from test_nextasks import ADRESSE, TOKEN, _anlegen, _verbinden, fern, verbunden  # noqa: F401
from test_todoist import Todoist

A = "/api/nextasks"


def _person(db) -> Benutzer:
    return db.query(Benutzer).filter(Benutzer.benutzername == "betreiber").one()


def _aufgabe(fern, titel: str, liste: str | None = None, **mehr) -> str:
    """Eine Aufgabe direkt im Nachbau, wie in nextasks' Oberfläche angelegt."""
    antwort = fern._anlegen({"title": titel, "list_id": liste or fern.einkauf, **mehr})
    assert antwort.status_code == 201
    return antwort.json()["id"]


def _titel(antwort) -> list[str]:
    assert antwort.status_code == 200, antwort.text
    return [a["titel"] for a in antwort.json()["aufgaben"]]


def _zweite_verbindung(db, person, url="https://tasks2.example.com") -> Aufgabenverbindung:
    """Eine zweite nextasks-Verbindung aus der Zeit vor MAIL-2, direkt in der Datenbank."""
    v = Aufgabenverbindung(
        benutzer_id=person.id,
        art="nextasks",
        name="Alt",
        angelegt=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(v)
    db.flush()
    v.zugang = crypto.verschluesseln(
        nextasks.zugang_schreiben(nextasks.Zugang(url=url, token=TOKEN)), aufgabenziele._kontext(v.id)
    )
    db.commit()
    return v


# --- Lage ----------------------------------------------------------------------- #


def test_ohne_verbindung_sagt_die_lage_es_mit_200(klient, welt, fern):  # noqa: F811
    antwort = klient.get(f"{A}/lage")
    assert antwort.status_code == 200
    assert antwort.json()["verbunden"] is False
    assert klient.get(f"{A}/listen").json()["detail"] == "nextasks_nicht_verbunden"
    assert klient.get(f"{A}/listen").status_code == 409
    assert fern.anfragen == []


def test_die_lage_nennt_konto_zeitzone_und_mitglieder(klient, verbunden, fern):
    lage = klient.get(f"{A}/lage").json()
    assert lage["verbunden"] is True
    assert lage["verbindung_id"] == verbunden
    assert lage["name"] == "Robin"
    assert lage["zeitzone"] == "Europe/Berlin"
    assert lage["mitglieder"] is False
    assert lage["weitere"] == []
    fern.ich["features"].append("members")
    assert klient.get(f"{A}/lage").json()["mitglieder"] is True


def test_klemmt_nextasks_ist_die_lage_trotzdem_200(klient, verbunden, monkeypatch):
    def weg(anfrage):
        raise httpx.ConnectError("nein")

    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(weg))
    antwort = klient.get(f"{A}/lage")
    assert antwort.status_code == 200
    assert antwort.json()["verbunden"] is True
    assert antwort.json()["fehler"] == "nextasks_nicht_erreichbar"
    # Lesen und Schreiben sagen es dagegen deutlich (EC-1).
    assert klient.get(f"{A}/aufgaben").status_code == 502
    assert klient.post(f"{A}/aufgaben", json={"liste_id": "x", "titel": "a"}).status_code == 502


# --- Listen und Auswahl ----------------------------------------------------------- #


def test_bereiche_mit_listen_in_der_reihenfolge_von_nextasks(klient, verbunden, fern):
    bereiche = klient.get(f"{A}/listen").json()["bereiche"]
    # Familie zuerst (erste nicht ausgeblendete Liste), Arbeit ausgeblendet ans Ende,
    # der Bereich ohne Liste fällt weg.
    assert [b["name"] for b in bereiche] == ["Familie", "Garten", "Arbeit"]
    familie = bereiche[0]
    assert familie["geteilt"] is True and familie["symbol"] == "house"
    assert [l["name"] for l in familie["listen"]] == ["Einkauf", "Haushalt"]
    einkauf = familie["listen"][0]
    assert einkauf == {
        "id": fern.einkauf, "name": "Einkauf", "farbe": "green", "symbol": "cart",
        "beschreibbar": True, "offen": 4, "gewaehlt": True,
        "abschnitte": [{"id": fern.abschnitt, "name": "Markt"}],
    }
    assert familie["listen"][1]["farbe"] == "#a1b2c3"
    # Nur lesbar steht da, aber nicht beschreibbar.
    assert bereiche[1]["listen"][0]["beschreibbar"] is False
    assert bereiche[2]["ausgeblendet"] is True


def test_abgewaehlte_listen_erscheinen_nirgends(klient, verbunden, welt, fern, db):  # noqa: F811
    _aufgabe(fern, "Brot")
    im_haushalt = _aufgabe(fern, "Staubsaugen", fern.haushalt)
    antwort = klient.patch(f"{A}/listen/{fern.haushalt}", json={"gewaehlt": False})
    assert antwort.status_code == 204
    assert json.loads(db.get(Aufgabenverbindung, verbunden).ohne) == [fern.haushalt]

    familie = klient.get(f"{A}/listen").json()["bereiche"][0]
    assert [l["name"] for l in familie["listen"]] == ["Einkauf"]
    alle = klient.get(f"{A}/listen?alle=true").json()["bereiche"]
    haushalt = next(l for b in alle for l in b["listen"] if l["id"] == fern.haushalt)
    assert haushalt["gewaehlt"] is False
    # Mit ``alle`` auch der Bereich ohne Liste.
    assert "Leer" in [b["name"] for b in alle]

    assert _titel(klient.get(f"{A}/aufgaben")) == ["Brot"]
    assert klient.get(f"{A}/aufgaben?suche=staub").json()["aufgaben"] == []
    assert klient.get(f"{A}/aufgaben?liste={fern.haushalt}").status_code == 404
    assert klient.get(f"{A}/aufgaben/{im_haushalt}").status_code == 404
    neu = klient.post(f"{A}/aufgaben", json={"liste_id": fern.haushalt, "titel": "x"})
    assert neu.status_code == 404
    assert neu.json()["detail"] == "nextasks_liste_unbekannt"
    # Auch nicht als Ziel für „Zu Aufgabe machen" (AC-9).
    ziele = [l["ziel"] for g in klient.get("/api/aufgabenziele/listen").json() for l in g["listen"]]
    assert f"{verbunden}:{fern.haushalt}" not in ziele
    assert f"{verbunden}:{fern.einkauf}" in ziele

    # Wieder gewählt: alles wieder da, in nextasks hat sich nie etwas geändert.
    klient.patch(f"{A}/listen/{fern.haushalt}", json={"gewaehlt": True})
    assert sorted(_titel(klient.get(f"{A}/aufgaben"))) == ["Brot", "Staubsaugen"]
    assert not any(m == "PATCH" and "lists" in p for m, p in fern.anfragen)


def test_eine_neue_liste_in_nextasks_ist_von_selbst_gewaehlt(klient, verbunden, fern):
    klient.patch(f"{A}/listen/{fern.haushalt}", json={"gewaehlt": False})
    fern.listen.append({"id": "neu-1", "space_id": fern.familie, "space_name": "Familie", "name": "Neu",
                        "writable": True, "hidden": False, "sections": []})
    namen = [l["name"] for l in klient.get(f"{A}/listen").json()["bereiche"][0]["listen"]]
    assert namen == ["Einkauf", "Neu"]


# --- Aufgaben lesen --------------------------------------------------------------- #


def test_die_sammlungen_fragen_nextasks_richtig(klient, verbunden, fern):
    berlin = datetime.now(ZoneInfo("Europe/Berlin")).date()
    _aufgabe(fern, "Ohne Datum")
    _aufgabe(fern, "Überfällig", due_date=(berlin - timedelta(days=2)).isoformat())
    _aufgabe(fern, "Heute", due_date=berlin.isoformat(), due_time="09:00")
    _aufgabe(fern, "Morgen", due_date=(berlin + timedelta(days=1)).isoformat())
    _aufgabe(fern, "Markiert", flagged=True)
    _aufgabe(fern, "Meins", assignees=[1])
    _aufgabe(fern, "Maras", assignees=[12])
    fertig = _aufgabe(fern, "Fertig")
    fern.erledigen(fertig)

    assert len(_titel(klient.get(f"{A}/aufgaben"))) == 7
    assert _titel(klient.get(f"{A}/aufgaben?sammlung=offen")) == _titel(klient.get(f"{A}/aufgaben"))
    assert _titel(klient.get(f"{A}/aufgaben?sammlung=heute")) == ["Überfällig", "Heute"]
    assert fern.parameter[-1]["due_before"] == (berlin + timedelta(days=1)).isoformat()
    assert _titel(klient.get(f"{A}/aufgaben?sammlung=datum")) == ["Überfällig", "Heute", "Morgen"]
    assert _titel(klient.get(f"{A}/aufgaben?sammlung=erledigt")) == ["Fertig"]
    assert _titel(klient.get(f"{A}/aufgaben?sammlung=markiert")) == ["Markiert"]
    assert _titel(klient.get(f"{A}/aufgaben?sammlung=mir")) == ["Meins"]
    assert fern.parameter[-1]["assigned"] == "me"
    assert klient.get(f"{A}/aufgaben?sammlung=quatsch").status_code == 400


def test_heute_gilt_im_tag_des_nextasks_kontos(klient, verbunden, fern):
    """⚠️ EC-16: Kiritimati ist UTC+14, dort ist oft schon morgen."""
    fern.ich["time_zone"] = "Pacific/Kiritimati"
    klient.get(f"{A}/aufgaben?sammlung=heute")
    dort = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert fern.parameter[-1]["due_before"] == (dort + timedelta(days=1)).isoformat()


def test_eine_fernaufgabe_traegt_alles_aus_dem_vertrag(klient, verbunden, fern):
    kennung = _aufgabe(
        fern, "Brot", section_id=fern.abschnitt, notes="**Vollkorn**", due_date="2026-11-25",
        due_time="09:00", priority=2, flagged=True, tags=["einkauf"], assignees=[12, 99],
        url="javascript:alert(1)",
    )
    _aufgabe(fern, "Teil", parent_id=kennung)
    a = klient.get(f"{A}/aufgaben").json()["aufgaben"]
    # Nur oberste Aufgaben.
    assert [x["titel"] for x in a] == ["Brot"]
    x = a[0]
    assert x["liste_name"] == "Einkauf" and x["bereich_name"] == "Familie"
    assert x["bereich_id"] == fern.familie
    assert x["abschnitt_id"] == fern.abschnitt and x["abschnitt_name"] == "Markt"
    assert x["notiz"] == "**Vollkorn**" and x["notiz_text"] == "Vollkorn"
    # Kein ``javascript:`` als Link (EC-8).
    assert x["url"] is None
    assert (x["faellig_tag"], x["faellig_zeit"]) == ("2026-11-25", "09:00")
    assert (x["prioritaet"], x["markiert"], x["schlagworte"]) == (2, True, ["einkauf"])
    # Ehemaliges Mitglied: Name leer (EC-12).
    assert x["zustaendige"] == [{"id": 12, "name": "Mara"}, {"id": 99, "name": ""}]
    assert x["teilaufgaben"] == {"offen": 1, "gesamt": 1}
    assert x["link"].startswith(ADRESSE)
    assert x["beschreibbar"] is True
    assert x["mail"] is None and x["papierkorb"] is False and x["erledigt"] is False

    voll = klient.get(f"{A}/aufgaben/{kennung}").json()
    assert [t["titel"] for t in voll["teilaufgaben_liste"]] == ["Teil"]
    assert voll["teilaufgaben_liste"][0]["eltern_id"] == kennung


def test_ein_name_ohne_anzeigenamen_nimmt_den_kontonamen(klient, verbunden, fern):
    _aufgabe(fern, "Jo", assignees=[13])
    assert klient.get(f"{A}/aufgaben").json()["aufgaben"][0]["zustaendige"] == [{"id": 13, "name": "jo"}]


def test_eine_nur_lesbare_liste_ist_nicht_beschreibbar(klient, verbunden, fern):
    # Im Nachbau direkt: Anlegen darf das Token dort ja nicht.
    fern.aufgaben["b1"] = {"id": "b1", "list_id": fern.beete, "title": "Gießen", "completed": False,
                           "trashed": False, "parent_id": None}
    a = klient.get(f"{A}/aufgaben?liste={fern.beete}").json()["aufgaben"]
    assert [(x["titel"], x["beschreibbar"]) for x in a] == [("Gießen", False)]


def test_die_suche_findet_titel_und_notiz_ohne_gross_und_klein(klient, verbunden, fern):
    _aufgabe(fern, "BROT kaufen")
    _aufgabe(fern, "Milch", notes="Für das **Frühstücksbrot**")
    _aufgabe(fern, "Äpfel")
    fern.seitengroesse = 1
    antwort = klient.get(f"{A}/aufgaben?suche=brot")
    assert sorted(_titel(antwort)) == ["BROT kaufen", "Milch"]
    # Die Suche holt alle Seiten und gibt keinen Cursor.
    assert antwort.json()["weiter"] is None


def test_seitenweise_mit_cursor(klient, verbunden, fern):
    for n in range(5):
        _aufgabe(fern, f"A{n}")
    fern.seitengroesse = 2
    erste = klient.get(f"{A}/aufgaben").json()
    assert [a["titel"] for a in erste["aufgaben"]] == ["A0", "A1"]
    zweite = klient.get(f"{A}/aufgaben", params={"cursor": erste["weiter"]}).json()
    assert [a["titel"] for a in zweite["aufgaben"]] == ["A2", "A3"]


def test_eine_seite_nur_mit_abgewaehltem_wird_uebersprungen(klient, verbunden, fern):
    _aufgabe(fern, "H1", fern.haushalt)
    _aufgabe(fern, "H2", fern.haushalt)
    _aufgabe(fern, "Brot")
    klient.patch(f"{A}/listen/{fern.haushalt}", json={"gewaehlt": False})
    fern.seitengroesse = 2
    assert _titel(klient.get(f"{A}/aufgaben")) == ["Brot"]


def test_eine_aufgabe_aus_einer_mail_traegt_die_mail(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    zeile = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}").json()["aufgabe"]
    _aufgabe(fern, "Ohne Mail")
    a = {x["titel"]: x for x in klient.get(f"{A}/aufgaben").json()["aufgaben"]}
    assert a["Ohne Mail"]["mail"] is None
    assert a["Mail 0"]["mail"] == {
        "aufgabe_id": zeile["id"], "nachricht_id": ids[0], "konto_id": zeile["konto_id"],
        "betreff": "Mail 0", "von_name": "Wer Auch Immer", "von_adresse": "wer@example.com",
        "verwaist": False,
    }
    db.delete(db.get(Nachricht, ids[0]))
    db.commit()
    mail = {x["titel"]: x for x in klient.get(f"{A}/aufgaben").json()["aufgaben"]}["Mail 0"]["mail"]
    assert mail["verwaist"] is True and mail["nachricht_id"] is None and mail["betreff"] == "Mail 0"


# --- Anlegen, Ändern, Löschen ------------------------------------------------------- #


def test_anlegen_ohne_mail_mit_allen_feldern(klient, verbunden, fern):
    antwort = klient.post(f"{A}/aufgaben", json={
        "liste_id": fern.einkauf, "abschnitt_id": fern.abschnitt, "titel": "  Brot  holen ",
        "notiz": "Vollkorn", "faellig_tag": "2026-11-25", "faellig_zeit": "09:30",
        "prioritaet": 3, "markiert": True, "zustaendige": [12],
    })
    assert antwort.status_code == 201, antwort.text
    assert fern.rumpfe[-1] == {
        "list_id": fern.einkauf, "title": "Brot holen", "section_id": fern.abschnitt, "notes": "Vollkorn",
        "due_date": "2026-11-25", "due_time": "09:30", "priority": 3, "flagged": True, "assignees": [12],
    }
    x = antwort.json()
    assert x["titel"] == "Brot holen" and x["zustaendige"] == [{"id": 12, "name": "Mara"}]
    assert x["mail"] is None


def test_eine_teilaufgabe_ueber_eltern_id(klient, verbunden, fern):
    oben = _aufgabe(fern, "Oben")
    antwort = klient.post(f"{A}/aufgaben", json={"liste_id": fern.einkauf, "eltern_id": oben, "titel": "Unten"})
    assert antwort.status_code == 201
    assert antwort.json()["eltern_id"] == oben
    assert fern.rumpfe[-1]["parent_id"] == oben


def test_doppelklick_mit_derselben_anfrage_gibt_eine_aufgabe(klient, verbunden, fern):
    wunsch = {"liste_id": fern.einkauf, "titel": "Einmal", "anfrage": "k-1"}
    eins = klient.post(f"{A}/aufgaben", json=wunsch).json()
    zwei = klient.post(f"{A}/aufgaben", json=wunsch).json()
    assert eins["id"] == zwei["id"]
    assert sum(1 for a in fern.aufgaben.values() if a["title"] == "Einmal") == 1


@pytest.mark.parametrize("wunsch", [
    {"titel": "   "},
    {"titel": "a", "faellig_zeit": "09:00"},
])
def test_unpassende_eingaben_beim_anlegen(klient, verbunden, fern, wunsch):
    antwort = klient.post(f"{A}/aufgaben", json={"liste_id": fern.einkauf, **wunsch})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "nextasks_eingabe_ungueltig"
    assert fern.zaehlen("POST", "tasks") == 0


def test_eine_unbekannte_liste_beim_anlegen(klient, verbunden, fern):
    antwort = klient.post(f"{A}/aufgaben", json={"liste_id": "gibt-es-nicht", "titel": "a"})
    assert antwort.status_code == 404
    assert antwort.json()["detail"] == "nextasks_liste_unbekannt"
    assert fern.zaehlen("POST", "tasks") == 0


def test_aendern_schickt_nur_die_geaenderten_felder(klient, verbunden, fern):
    kennung = _aufgabe(fern, "Alt", notes="bleibt", due_date="2026-11-25", priority=1)
    antwort = klient.patch(f"{A}/aufgaben/{kennung}", json={"titel": "Neu"})
    assert antwort.status_code == 200, antwort.text
    assert fern.rumpfe[-1] == {"title": "Neu"}
    assert antwort.json()["notiz"] == "bleibt" and antwort.json()["prioritaet"] == 1

    klient.patch(f"{A}/aufgaben/{kennung}", json={"prioritaet": 3, "markiert": True, "schlagworte": ["a"]})
    assert fern.rumpfe[-1] == {"priority": 3, "flagged": True, "tags": ["a"]}


def test_null_leert(klient, verbunden, fern):
    kennung = _aufgabe(fern, "Mit Datum", due_date="2026-11-25", due_time="09:00", notes="weg")
    antwort = klient.patch(f"{A}/aufgaben/{kennung}", json={"faellig_tag": None, "notiz": None})
    assert fern.rumpfe[-1] == {"due_date": None, "notes": None}
    x = antwort.json()
    assert (x["faellig_tag"], x["faellig_zeit"], x["notiz"]) == (None, None, "")


@pytest.mark.parametrize("wunsch", [
    {"titel": None}, {"titel": "  "}, {"erledigt": None}, {"papierkorb": True}, {"liste_id": None},
])
def test_was_sich_nicht_leeren_laesst(klient, verbunden, fern, wunsch):
    kennung = _aufgabe(fern, "Bleibt")
    antwort = klient.patch(f"{A}/aufgaben/{kennung}", json=wunsch)
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "nextasks_eingabe_ungueltig"
    assert not any(m == "PATCH" for m, _ in fern.anfragen)


def test_verschieben_nur_in_eine_gewaehlte_liste(klient, verbunden, fern):
    kennung = _aufgabe(fern, "Wandert")
    klient.patch(f"{A}/listen/{fern.haushalt}", json={"gewaehlt": False})
    assert klient.patch(f"{A}/aufgaben/{kennung}", json={"liste_id": fern.haushalt}).status_code == 404
    klient.patch(f"{A}/listen/{fern.haushalt}", json={"gewaehlt": True})
    antwort = klient.patch(f"{A}/aufgaben/{kennung}", json={"liste_id": fern.haushalt, "abschnitt_id": None})
    assert antwort.status_code == 200
    assert fern.rumpfe[-1] == {"list_id": fern.haushalt, "section_id": None}
    assert antwort.json()["liste_name"] == "Haushalt"


def test_eine_wiederholte_aufgabe_rueckt_weiter(klient, verbunden, fern):
    kennung = _aufgabe(fern, "Müll", due_date="2026-11-24")
    fern.aufgaben[kennung]["repeat"] = "weekly"
    x = klient.patch(f"{A}/aufgaben/{kennung}", json={"erledigt": True}).json()
    assert x["erledigt"] is False
    assert x["faellig_tag"] == "2026-12-01"
    assert x["wiederholung"] == "weekly"


def test_haken_an_einer_aufgabe_aus_einer_mail_zieht_die_zeile_nach(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    zeile = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}").json()["aufgabe"]
    kennung = db.get(Aufgabe, zeile["id"]).fern_id
    klient.patch(f"{A}/aufgaben/{kennung}", json={"erledigt": True, "faellig_tag": "2026-12-24"})
    db.expire_all()
    a = db.get(Aufgabe, zeile["id"])
    assert a.erledigt is not None
    assert a.faellig.date().isoformat() == "2026-12-24"
    klient.patch(f"{A}/aufgaben/{kennung}", json={"erledigt": False})
    db.expire_all()
    assert db.get(Aufgabe, zeile["id"]).erledigt is None


def test_loeschen_legt_in_den_papierkorb_und_zurueck(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    zeile = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}").json()["aufgabe"]
    kennung = db.get(Aufgabe, zeile["id"]).fern_id
    assert klient.delete(f"{A}/aufgaben/{kennung}").status_code == 204
    assert fern.aufgaben[kennung]["trashed"] is True
    db.expire_all()
    assert db.get(Aufgabe, zeile["id"]).fern_geloescht is True
    assert _titel(klient.get(f"{A}/aufgaben")) == []
    assert klient.get(f"{A}/aufgaben/{kennung}").json()["papierkorb"] is True

    zurueck = klient.patch(f"{A}/aufgaben/{kennung}", json={"papierkorb": False})
    assert zurueck.status_code == 200
    assert fern.rumpfe[-1] == {"trashed": False}
    db.expire_all()
    assert db.get(Aufgabe, zeile["id"]).fern_geloescht is False


def test_eine_endgueltig_verschwundene_aufgabe(klient, verbunden, fern):
    kennung = _aufgabe(fern, "Weg")
    fern.fort.add(kennung)
    for antwort in (
        klient.get(f"{A}/aufgaben/{kennung}"),
        klient.patch(f"{A}/aufgaben/{kennung}", json={"erledigt": True}),
        klient.delete(f"{A}/aufgaben/{kennung}"),
    ):
        assert antwort.status_code == 404
        assert antwort.json()["detail"] == "nextasks_nicht_gefunden"


def test_eine_kennung_mit_fremden_zeichen_geht_nie_hinaus(klient, verbunden, fern):
    fern.anfragen.clear()
    for pfad in (f"{A}/aufgaben/a.b", f"{A}/aufgaben/a%3Fb", f"{A}/bereiche/a.b/mitglieder"):
        assert klient.get(pfad).status_code == 404
    assert fern.anfragen == []


# --- Mitglieder ------------------------------------------------------------------- #


def test_ohne_members_keine_mitglieder(klient, verbunden, fern):
    antwort = klient.get(f"{A}/bereiche/{fern.familie}/mitglieder")
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_ohne_mitglieder"
    assert not any("members" in p for _, p in fern.anfragen)


def test_mitglieder_mit_anzeigenamen(klient, verbunden, fern):
    fern.ich["features"].append("members")
    antwort = klient.get(f"{A}/bereiche/{fern.familie}/mitglieder")
    assert antwort.json() == [{"id": 1, "name": "Robin"}, {"id": 12, "name": "Mara"}, {"id": 13, "name": "jo"}]
    assert klient.get(f"{A}/bereiche/{fern.garten}/mitglieder").status_code == 404


# --- Absagen ---------------------------------------------------------------------- #


def test_ein_abgelehnter_token_ist_409_und_steht_an_der_verbindung(klient, verbunden, fern, db):
    fern.stoerung = (401, "token_invalid")
    antwort = klient.get(f"{A}/aufgaben")
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_zugang_ungueltig"
    db.expire_all()
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == "nextasks_zugang_ungueltig"
    # nexmail selbst bleibt angemeldet.
    assert klient.get("/api/auth/ich").status_code == 200
    fern.stoerung = None
    klient.get(f"{A}/lage")
    db.expire_all()
    assert db.get(Aufgabenverbindung, verbunden).letzter_fehler == ""


def test_eine_bitte_um_pause_bleibt_429(klient, verbunden, fern):
    fern.stoerung = (429, "slow_down")
    fern.kopf_extra = {"Retry-After": "17"}
    antwort = klient.get(f"{A}/listen")
    assert antwort.status_code == 429
    assert antwort.headers["retry-after"] == "17"


def test_nicht_erreichbar_ist_502(klient, verbunden, monkeypatch):
    def weg(anfrage):
        raise httpx.ConnectError("nein")

    monkeypatch.setattr(nextasks, "TRANSPORT", httpx.MockTransport(weg))
    antwort = klient.get(f"{A}/listen")
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "nextasks_nicht_erreichbar"


def test_das_token_steht_nie_im_protokoll(klient, verbunden, welt, fern, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    kennung = _aufgabe(fern, "Geheimer Titel", notes="geheime Notiz")
    klient.get(f"{A}/lage")
    klient.get(f"{A}/listen")
    klient.get(f"{A}/aufgaben?suche=geheim")
    klient.patch(f"{A}/aufgaben/{kennung}", json={"titel": "Noch geheimer"})
    klient.delete(f"{A}/aufgaben/{kennung}")
    fern.stoerung = (401, "token_invalid")
    klient.get(f"{A}/aufgaben")
    text = caplog.text
    assert TOKEN not in text
    assert "geheim" not in text.casefold()


# --- Eine Verbindung, zweites Konto ------------------------------------------------- #


def test_eine_zweite_nextasks_verbindung_wird_abgewiesen(klient, verbunden, fern, db):
    fern.anfragen.clear()
    antwort = _verbinden(klient)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "nextasks_schon_verbunden"
    assert fern.anfragen == []
    assert db.query(Aufgabenverbindung).filter(Aufgabenverbindung.art == "nextasks").count() == 1
    # Token erneuern bleibt.
    assert klient.put(f"/api/aufgabenziele/{verbunden}/nextasks",
                      json={"url": ADRESSE, "token": TOKEN}).status_code == 200


def test_alte_weitere_verbindungen_stehen_in_der_lage(klient, verbunden, fern, db):
    alt = _zweite_verbindung(db, _person(db))
    lage = klient.get(f"{A}/lage").json()
    assert lage["verbindung_id"] == verbunden
    assert lage["weitere"] == [{"id": alt.id, "name": "Alt", "adresse": "https://tasks2.example.com"}]
    # Gefragt wird nur die erste: Die zweite Adresse sähe der Nachbau mit einem Fehler.
    klient.get(f"{A}/listen")
    assert klient.get(f"{A}/aufgaben").status_code == 200


def test_ein_zweites_konto_sieht_nichts(klient, zweiter_klient, verbunden, fern, db):
    _aufgabe(fern, "Privat")
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    fern.anfragen.clear()
    assert zweiter_klient.get(f"{A}/lage").json() == {
        "verbunden": False, "verbindung_id": "", "name": "", "mitglieder": False, "fehler": "",
        "zeitzone": "", "weitere": [],
    }
    for antwort in (
        zweiter_klient.get(f"{A}/aufgaben"),
        zweiter_klient.get(f"{A}/listen"),
        zweiter_klient.patch(f"{A}/listen/{fern.einkauf}", json={"gewaehlt": False}),
        zweiter_klient.post(f"{A}/aufgaben", json={"liste_id": fern.einkauf, "titel": "x"}),
    ):
        assert antwort.status_code == 409
        assert antwort.json()["detail"] == "nextasks_nicht_verbunden"
    assert fern.anfragen == []


def test_ohne_anmeldung_nichts(verbunden, zweiter_klient, fern):
    fern.anfragen.clear()
    assert zweiter_klient.get(f"{A}/lage").status_code == 401
    assert zweiter_klient.get(f"{A}/aufgaben").status_code == 401
    assert fern.anfragen == []


# --- „Zu Aufgabe machen" mit mehr Feldern ------------------------------------------- #


def test_zu_aufgabe_machen_mit_uhrzeit_prioritaet_markiert_zustaendigen(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    antwort = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}/{fern.abschnitt}", faellig="2026-11-25",
                       faellig_zeit="08:15", prioritaet=2, markiert=True, zustaendige=[12])
    assert antwort.status_code == 200, antwort.text
    rumpf = fern.rumpfe[-1]
    assert (rumpf["due_date"], rumpf["due_time"], rumpf["priority"], rumpf["flagged"], rumpf["assignees"]) == (
        "2026-11-25", "08:15", 2, True, [12])
    assert rumpf["section_id"] == fern.abschnitt
    assert rumpf["external_ref"] == "nexmail:<mail0@example.com>"


def test_eine_uhrzeit_ohne_datum_geht_nicht_hinaus(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}", faellig_zeit="08:15", prioritaet=0, markiert=False)
    assert "due_time" not in fern.rumpfe[-1]
    assert "priority" not in fern.rumpfe[-1] and "flagged" not in fern.rumpfe[-1]


def test_eine_kaputte_uhrzeit_im_wunsch(klient, verbunden, welt, fern):  # noqa: F811
    _, _, ids = welt
    assert _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}", faellig_zeit="25:00").status_code == 422
    assert fern.zaehlen("POST", "tasks") == 0


# --- Eigene Liste ----------------------------------------------------------------- #


def _eigene(klient, an: bool, umziehen: bool = False):
    return klient.put("/api/aufgabenziele/eigene", json={"an": an, "umziehen": umziehen})


def _eigene_drei(klient, welt):  # noqa: F811
    """Drei eigene Aufgaben, die letzte erledigt."""
    _, _, ids = welt
    zeilen = [klient.post("/api/aufgaben", json={"nachricht_id": i}).json()["id"] for i in ids]
    klient.patch(f"/api/aufgaben/{zeilen[2]}", json={"erledigt": True})
    return zeilen


def test_ohne_verbindung_laesst_sich_die_eigene_liste_nicht_ausschalten(klient, welt, db):  # noqa: F811
    antwort = _eigene(klient, False)
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "eigene_aufgaben_ohne_verbindung"
    assert klient.get("/api/aufgabenziele").json()["eigene"] is True


def test_der_stand_nennt_die_eigene_liste(klient, verbunden, welt, fern):  # noqa: F811
    _eigene_drei(klient, welt)
    stand = klient.get("/api/aufgabenziele").json()
    assert (stand["eigene"], stand["eigene_offen"]) == (True, 2)


def test_eigene_liste_aus_und_wieder_an(klient, verbunden, welt, fern, db):  # noqa: F811
    _, _, ids = welt
    eigene = _eigene_drei(klient, welt)
    app_zeile = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}").json()["aufgabe"]
    assert app_zeile["id"] == eigene[0]  # Dieselbe Mail: die eigene kam zurück.

    antwort = _eigene(klient, False)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["umgezogen"] == 0 and antwort.json()["stand"]["eigene"] is False
    assert fern.zaehlen("POST", "tasks") == 0
    # Weg aus der Liste, im Browser und in der App.
    assert klient.get("/api/aufgaben").json() == []
    # Eine neue eigene geht nicht mehr.
    neu = klient.post("/api/aufgaben", json={"nachricht_id": ids[1]})
    assert (neu.status_code, neu.json()["detail"]) == (409, "eigene_aufgaben_aus")
    leer = _anlegen(klient, ids[1], "")
    assert (leer.status_code, leer.json()["detail"]) == (409, "eigene_aufgaben_aus")
    # Der Standard ist nie leer, sondern das erste Ziel.
    assert klient.get("/api/aufgabenziele").json()["standard"] == f"{verbunden}:{fern.einkauf}"
    # Gespeichert bleibt alles.
    assert db.query(Aufgabe).count() == 3

    wieder = _eigene(klient, True)
    assert wieder.json()["stand"]["eigene"] is True
    assert sorted(z["id"] for z in klient.get("/api/aufgaben").json()) == sorted(eigene)
    assert klient.get("/api/aufgabenziele").json()["standard"] == ""


def test_umzug_nach_nextasks(klient, verbunden, welt, fern, db):  # noqa: F811
    eigene = _eigene_drei(klient, welt)
    klient.put("/api/aufgabenziele/standard", json={"ziel": f"{verbunden}:{fern.haushalt}"})
    antwort = _eigene(klient, False, umziehen=True).json()
    assert (antwort["umgezogen"], antwort["fehlgeschlagen"]) == (2, 0)
    assert antwort["stand"]["eigene_offen"] == 0
    db.expire_all()
    for zeile in eigene[:2]:
        a = db.get(Aufgabe, zeile)
        assert (a.fern_art, a.verbindung_id) == ("nextasks", verbunden)
        assert fern.aufgaben[a.fern_id]["list_id"] == fern.haushalt
        assert fern.aufgaben[a.fern_id]["external_ref"] == nextasks.schluessel_fuer(a.message_id)
        assert a.fern_liste == "Familie › Haushalt"
    # Erledigte ziehen nicht um (EC-19).
    assert db.get(Aufgabe, eigene[2]).fern_art == ""
    assert fern.zaehlen("POST", "tasks") == 2
    # Keine zweite Zeile, und die umgezogenen stehen als App-Aufgaben da.
    assert db.query(Aufgabe).count() == 3
    zeilen = {z["id"]: z for z in klient.get("/api/aufgaben").json()}
    assert set(zeilen) == set(eigene[:2])
    assert all(z["fern_art"] == "nextasks" for z in zeilen.values())


def test_abbruch_mittendrin_und_zweiter_versuch_ohne_doppel(klient, verbunden, welt, fern, db):  # noqa: F811
    eigene = _eigene_drei(klient, welt)
    klient.patch(f"/api/aufgaben/{eigene[2]}", json={"erledigt": False})
    fern.anlegen_scheitert = {"Mail 1"}
    erste = _eigene(klient, False, umziehen=True).json()
    assert (erste["umgezogen"], erste["fehlgeschlagen"]) == (2, 1)
    db.expire_all()
    assert db.get(Aufgabe, eigene[1]).fern_art == ""
    assert erste["stand"]["eigene_offen"] == 1

    fern.anlegen_scheitert = set()
    zweite = _eigene(klient, False, umziehen=True).json()
    assert (zweite["umgezogen"], zweite["fehlgeschlagen"]) == (1, 0)
    # Je Mail genau eine Aufgabe in nextasks.
    titel = sorted(a["title"] for a in fern.aufgaben.values())
    assert titel == ["Mail 0", "Mail 1", "Mail 2"]


def test_bittet_nextasks_um_pause_endet_der_umzug(klient, verbunden, welt, fern, db):  # noqa: F811
    eigene = _eigene_drei(klient, welt)
    klient.patch(f"/api/aufgaben/{eigene[2]}", json={"erledigt": False})
    klient.put("/api/aufgabenziele/standard", json={"ziel": f"{verbunden}:{fern.einkauf}"})
    fern.stoerung = (429, "slow_down")
    fern.kopf_extra = {"Retry-After": "5"}
    fern.anfragen.clear()
    antwort = _eigene(klient, False, umziehen=True).json()
    assert (antwort["umgezogen"], antwort["fehlgeschlagen"]) == (0, 3)
    # Nach der ersten Absage nicht weiter gefragt (der Listenname kommt davor).
    assert fern.zaehlen("POST", "tasks") == 1


def test_ein_zweiter_versuch_findet_die_aufgabe_in_nextasks_wieder(klient, verbunden, welt, fern, db):  # noqa: F811
    """⚠️ Ging die Aufgabe hinaus, aber das Festschreiben hier nicht, legt der
    nächste Versuch über ``external_ref`` nichts doppelt an."""
    eigene = _eigene_drei(klient, welt)
    a = db.get(Aufgabe, eigene[0])
    fern._anlegen({"title": "Mail 0", "list_id": fern.einkauf,
                   "external_ref": nextasks.schluessel_fuer(a.message_id)})
    _eigene(klient, False, umziehen=True)
    assert sorted(x["title"] for x in fern.aufgaben.values()) == ["Mail 0", "Mail 1"]


def test_umzug_nach_todoist(klient, welt, monkeypatch, db):  # noqa: F811
    dienst = Todoist()
    monkeypatch.setattr(todoist, "TRANSPORT", httpx.MockTransport(dienst))
    v = klient.post("/api/aufgabenziele", json={"art": "todoist", "zugang": TOKEN}).json()["id"]
    eigene = _eigene_drei(klient, welt)
    klient.put("/api/aufgabenziele/standard", json={"ziel": f"{v}:p-arbeit"})
    antwort = _eigene(klient, False, umziehen=True).json()
    assert (antwort["umgezogen"], antwort["fehlgeschlagen"]) == (2, 0)
    db.expire_all()
    a = db.get(Aufgabe, eigene[0])
    assert (a.fern_art, a.fern_liste) == ("todoist", "Arbeit")
    assert dienst.aufgaben[a.fern_id]["project_id"] == "p-arbeit"
    assert "wer@example.com" in dienst.rumpfe[0]["description"]
    assert db.get(Aufgabe, eigene[2]).fern_art == ""


def test_mit_einem_webhook_als_standard_zieht_nichts_um(klient, welt, db):  # noqa: F811
    person = _person(db)
    v = Aufgabenverbindung(benutzer_id=person.id, art="webhook")
    db.add(v)
    db.flush()
    v.zugang = crypto.verschluesseln(
        webhook.zugang_schreiben(webhook.Zugang(url="https://hook.example.com/x", geheimnis="g")),
        aufgabenziele._kontext(v.id),
    )
    db.commit()
    eigene = _eigene_drei(klient, welt)
    antwort = _eigene(klient, False, umziehen=True).json()
    assert (antwort["umgezogen"], antwort["fehlgeschlagen"]) == (0, 0)
    assert antwort["stand"]["eigene"] is False
    assert antwort["stand"]["standard"] == f"{v.id}:{webhook.LISTE}"
    db.expire_all()
    assert all(db.get(Aufgabe, z).fern_art == "" for z in eigene)


def test_die_letzte_verbindung_trennen_schaltet_die_eigene_liste_wieder_an(klient, verbunden, welt, fern, db):  # noqa: F811
    eigene = _eigene_drei(klient, welt)
    _eigene(klient, False)
    assert klient.delete(f"/api/aufgabenziele/{verbunden}").status_code == 204
    stand = klient.get("/api/aufgabenziele").json()
    assert stand["eigene"] is True
    assert sorted(z["id"] for z in klient.get("/api/aufgaben").json()) == sorted(eigene)


def test_mit_zwei_verbindungen_bleibt_sie_aus_beim_trennen_der_ersten(klient, verbunden, welt, fern, db):  # noqa: F811
    alt = _zweite_verbindung(db, _person(db))
    _eigene(klient, False)
    klient.delete(f"/api/aufgabenziele/{alt.id}")
    assert klient.get("/api/aufgabenziele").json()["eigene"] is False


def test_eine_versteckte_eigene_aufgabe_zieht_beim_zu_aufgabe_machen_um(klient, verbunden, welt, fern, db):  # noqa: F811
    eigene = _eigene_drei(klient, welt)
    _eigene(klient, False)
    _, _, ids = welt
    antwort = _anlegen(klient, ids[0], f"{verbunden}:{fern.einkauf}")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["aufgabe"]["id"] == eigene[0]
    assert antwort.json()["aufgabe"]["fern_art"] == "nextasks"
    assert fern.zaehlen("POST", "tasks") == 1
    assert [z["id"] for z in klient.get("/api/aufgaben").json()] == [eigene[0]]


# --- Schemapflege ------------------------------------------------------------------- #


def test_die_neuen_spalten_kommen_beim_start_mit_ihrer_vorgabe(klient, verbunden, db):
    """Eine gewachsene Datenbank ohne die Spalten: Der Start legt sie an, die
    eigene Liste ist an, abgewählt ist nichts."""
    from sqlalchemy import text

    from app.db import _fehlende_spalten, engine

    db.close()
    with engine.begin() as verbindung:
        verbindung.execute(text('ALTER TABLE benutzer DROP COLUMN "aufgaben_eigene"'))
        verbindung.execute(text('ALTER TABLE aufgabenverbindung DROP COLUMN "ohne"'))
    assert set(_fehlende_spalten()) >= {"benutzer.aufgaben_eigene", "aufgabenverbindung.ohne"}
    with engine.begin() as verbindung:
        assert verbindung.execute(text("SELECT aufgaben_eigene FROM benutzer")).scalars().all() == [1]
        assert verbindung.execute(text("SELECT ohne FROM aufgabenverbindung")).scalars().all() == ["[]"]
    assert klient.get("/api/aufgabenziele").json()["eigene"] is True
