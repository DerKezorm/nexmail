"""Die Adressen des Kalenders.

⚠️ **Die Termin-Adressen stehen vor ``/{kalender_id}``.** FastAPI nimmt die
erste passende Route — ohne die Reihenfolge läse es ``termine`` als
Kalender-Kennung, und die Meldung wäre „gibt es nicht".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import Benutzer, Kalender
from conftest import einrichten


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    antwort = klient.post("/api/kalender", json={"name": "Privat"})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _wann(tag: int, stunde: int = 9) -> str:
    return datetime(2026, 9, tag, stunde, tzinfo=timezone.utc).isoformat()


def _fenster(klient, von: int = 1, bis: int = 30, **frage) -> list[dict]:
    antwort = klient.get(
        "/api/kalender/termine", params={"von": _wann(von, 0), "bis": _wann(bis, 0), **frage}
    )
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# --- Kalender ------------------------------------------------------------- #


def test_ein_neuer_kalender_steht_in_der_liste(klient, welt):
    liste = klient.get("/api/kalender").json()
    assert [k["name"] for k in liste] == ["Privat"]
    assert liste[0]["farbe"] == 1
    assert liste[0]["nur_lesen"] is False


def test_umbenennen_und_ausblenden(klient, welt):
    antwort = klient.patch(f"/api/kalender/{welt['id']}", json={"name": "Familie", "sichtbar": False})
    assert antwort.status_code == 200
    assert antwort.json()["name"] == "Familie"
    assert antwort.json()["sichtbar"] is False


def test_nicht_mitgeschickt_heisst_unveraendert(klient, welt):
    """⚠️ Dieselbe Regel wie beim Passwort — sonst verliert jeder seine Farbe,
    der nur den Namen ändert."""
    klient.patch(f"/api/kalender/{welt['id']}", json={"farbe": 4})
    antwort = klient.patch(f"/api/kalender/{welt['id']}", json={"name": "Neu"})
    assert antwort.json()["farbe"] == 4


def test_entfernen_nennt_die_zahl(klient, welt):
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Eins", "beginn": _wann(2)},
    )
    antwort = klient.delete(f"/api/kalender/{welt['id']}")
    assert antwort.status_code == 200
    assert antwort.json() == {"termine": 1}


def test_ein_fremder_kalender_gibt_404(klient, db, welt):
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.flush()
    seiner = Kalender(benutzer_id=anderer.id, name="Privat", farbe=1)
    db.add(seiner)
    db.commit()

    assert klient.patch(f"/api/kalender/{seiner.id}", json={"name": "X"}).status_code == 404
    assert klient.delete(f"/api/kalender/{seiner.id}").status_code == 404


# --- Termine -------------------------------------------------------------- #


def test_ein_termin_laesst_sich_anlegen_und_wiederfinden(klient, welt):
    antwort = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Zahnarzt", "beginn": _wann(2, 8)},
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["titel"] == "Zahnarzt"

    raus = _fenster(klient)
    assert [t["titel"] for t in raus] == ["Zahnarzt"]


def test_die_adresse_termine_wird_nicht_als_kalender_gelesen(klient, welt):
    """⚠️ **Der Reihenfolge-Fallstrick.** Ohne sie käme hier „gibt es nicht"."""
    antwort = klient.get(
        "/api/kalender/termine", params={"von": _wann(1, 0), "bis": _wann(30, 0)}
    )
    assert antwort.status_code == 200


def test_eine_reihe_kommt_ausgerechnet_zurueck(klient, welt):
    klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"], "titel": "Wochenstart",
            "beginn": _wann(7), "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    )
    raus = _fenster(klient)
    assert len(raus) == 4
    assert all(t["aus_reihe"] for t in raus)
    # ⚠️ Die Regel kommt als KENNUNG, nicht als deutscher Satz — und die
    # Wochentage als Liste, damit die Oberfläche daraus einen Satz baut.
    assert raus[0]["wiederholung"] == "woechentlich"
    assert raus[0]["wiederholung_tage"] == ["MO"]


def test_nur_dieser_aendert_genau_einen(klient, welt):
    neu = klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"], "titel": "Wochenstart",
            "beginn": _wann(7), "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    ).json()

    antwort = klient.patch(
        f"/api/kalender/termine/{neu['id']}",
        json={"titel": "Ausnahmsweise", "umfang": "dieser", "vorkommen": _wann(14)},
    )
    assert antwort.status_code == 200, antwort.text

    titel = {t["beginn"][:10]: t["titel"] for t in _fenster(klient)}
    assert titel["2026-09-14"] == "Ausnahmsweise"
    assert titel["2026-09-07"] == "Wochenstart"


def test_nur_diesen_loeschen_klinkt_ihn_aus(klient, welt):
    neu = klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"], "titel": "Wochenstart",
            "beginn": _wann(7), "rrule": "FREQ=WEEKLY;BYDAY=MO",
        },
    ).json()

    antwort = klient.delete(
        f"/api/kalender/termine/{neu['id']}",
        params={"umfang": "dieser", "vorkommen": _wann(14)},
    )
    assert antwort.status_code == 204

    assert [t["beginn"][:10] for t in _fenster(klient)] == [
        "2026-09-07", "2026-09-21", "2026-09-28",
    ]


def test_ein_unbekannter_umfang_gibt_400_mit_kennung(klient, welt):
    neu = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "X", "beginn": _wann(2)},
    ).json()
    antwort = klient.patch(
        f"/api/kalender/termine/{neu['id']}", json={"umfang": "vielleicht", "titel": "Y"}
    )
    assert antwort.status_code == 400
    # ⚠️ Eine Kennung, kein deutscher Satz — die Oberflaeche uebersetzt.
    assert antwort.json()["detail"] == "umfang_unbekannt"


def test_ein_riesiges_fenster_wird_abgewiesen(klient, welt):
    antwort = klient.get(
        "/api/kalender/termine",
        params={
            "von": _wann(1, 0),
            "bis": (datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=3000)).isoformat(),
        },
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "fenster_zu_gross"


def test_ein_abo_weist_das_anlegen_ab(klient, db, welt):
    abo = Kalender(
        benutzer_id=db.query(Benutzer).first().id, name="Feiertage", farbe=5,
        art="ics", url="https://calendar.example.com/f.ics",
    )
    db.add(abo)
    db.commit()

    antwort = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": abo.id, "titel": "Geht nicht", "beginn": _wann(2)},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "kalender_nur_lesen"


def test_auf_kalender_einschraenken(klient, welt):
    zweiter = klient.post("/api/kalender", json={"name": "Arbeit"}).json()
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Privat", "beginn": _wann(2)},
    )
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": zweiter["id"], "titel": "Arbeit", "beginn": _wann(2, 11)},
    )

    raus = _fenster(klient, kalender=[zweiter["id"]])
    assert [t["titel"] for t in raus] == ["Arbeit"]


# --- Suchen --------------------------------------------------------------- #


def _anlegen(klient, welt, titel, tag=10, stunde=9, rrule="", **rest):
    antwort = klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"],
            "titel": titel,
            "beginn": _wann(tag, stunde),
            "rrule": rrule,
            **rest,
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _suchen(klient, wort, **frage):
    antwort = klient.get("/api/kalender/suche", params={"q": wort, **frage})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_die_suche_findet_den_titel(klient, welt):
    _anlegen(klient, welt, "Zahnarzt Kontrolle")
    _anlegen(klient, welt, "Elternabend")
    ergebnis = _suchen(klient, "zahn")
    assert [t["titel"] for t in ergebnis["treffer"]] == ["Zahnarzt Kontrolle"]
    assert ergebnis["abgeschnitten"] is False


def test_gross_und_klein_trennt_nicht(klient, welt):
    """⚠️ **Das leistet SQLites ``LIKE`` selbst — fuer ASCII.** Ein eigenes
    ``lower()`` daneben aendert daran nichts; die Mutationsprobe laeuft
    entsprechend durch. Der Test haelt trotzdem die Zusage fest."""
    _anlegen(klient, welt, "Zahnarzt")
    assert len(_suchen(klient, "ZAHNARZT")["treffer"]) == 1


def test_ein_umlaut_wird_gefunden(klient, welt):
    """⚠️ **Die erste Fassung fand ihn nicht.** Sie verglich
    ``lower(Spalte) LIKE python-lower(Wort)``: Python faltet „Ü" zu „ü",
    SQLites ``lower`` laesst es stehen — wer „Übung" richtig tippte, bekam
    nichts. Gemessen am 04.09.2026.

    ⚠️ **Was NICHT geht, steht in SPAETER.md:** „übung" findet „Übung" nicht.
    SQLite faltet nur ASCII, und einen eigenen Zerleger gibt es hier nicht."""
    _anlegen(klient, welt, "Übung Ernstfall")
    assert [t["titel"] for t in _suchen(klient, "Übung")["treffer"]] == ["Übung Ernstfall"]


def test_ein_prozentzeichen_sucht_nicht_alles(klient, welt):
    """⚠️ Ohne Maskierung waere ``%`` ein Platzhalter und faende jeden Termin —
    dieselbe Vorsicht wie in ``schlagworte.traegt_atom``."""
    _anlegen(klient, welt, "Rabatt 20 Prozent")
    _anlegen(klient, welt, "Etwas anderes", tag=11)
    assert _suchen(klient, "%")["treffer"] == []


def test_die_suche_findet_auch_ort_und_beschreibung(klient, welt):
    """⚠️ Wer nach „Rathaus" sucht, meint den Ort — der Titel heißt oft anders."""
    _anlegen(klient, welt, "Termin A", ort="Rathaus, Zimmer 3")
    _anlegen(klient, welt, "Termin B", beschreibung="Unterlagen mitbringen")
    assert [t["titel"] for t in _suchen(klient, "rathaus")["treffer"]] == ["Termin A"]
    assert [t["titel"] for t in _suchen(klient, "unterlagen")["treffer"]] == ["Termin B"]


def test_eine_reihe_steht_einmal_im_ergebnis(klient, welt):
    """⚠️ **Sonst begräbt eine wöchentliche Besprechung alles andere.** Sie
    steht auch in der Datenbank einmal; sie aufzurechnen ergäbe zweihundert
    Treffer für denselben Termin."""
    _anlegen(klient, welt, "Team-Runde", rrule="FREQ=WEEKLY")
    _anlegen(klient, welt, "Team-Klausur", tag=12)
    treffer = _suchen(klient, "team")["treffer"]
    assert sorted(t["titel"] for t in treffer) == ["Team-Klausur", "Team-Runde"]


def test_ohne_wort_gibt_es_nichts(klient, welt):
    """Eine leere Suche ist keine Suche — nicht „alles"."""
    _anlegen(klient, welt, "Irgendwas")
    assert _suchen(klient, "   ")["treffer"] == []


def test_die_suche_bleibt_im_eigenen_bestand(klient, zweiter_klient, db, welt):
    """⚠️ Wie jede Adresse: Der Bestand eines anderen Benutzers ist unsichtbar."""
    from conftest import anmelden, zweiten_benutzer_anlegen

    _anlegen(klient, welt, "Geheime Besprechung")
    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)
    assert zweiter_klient.get("/api/kalender/suche", params={"q": "geheim"}).json()["treffer"] == []


def test_auf_kalender_einschraenken(klient, welt):
    zweiter = klient.post("/api/kalender", json={"name": "Arbeit"}).json()
    _anlegen(klient, welt, "Probe privat")
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": zweiter["id"], "titel": "Probe dienstlich", "beginn": _wann(11)},
    )
    treffer = _suchen(klient, "probe", kalender=[zweiter["id"]])["treffer"]
    assert [t["titel"] for t in treffer] == ["Probe dienstlich"]


def test_ein_abgesagter_termin_wird_nicht_gefunden(klient, db, welt):
    """Er steht auch im Raster nicht — die Suche darf ihn nicht zurückholen."""
    from app.models import Termin

    angelegt = _anlegen(klient, welt, "Fällt aus")
    db.get(Termin, angelegt["id"]).status = "CANCELLED"
    db.commit()
    assert _suchen(klient, "fällt")["treffer"] == []


def test_zu_viele_treffer_werden_abgeschnitten_und_sagen_es(klient, welt):
    """⚠️ **Sonst ist „nichts mehr da" nicht von „mehr wird nicht gezeigt" zu
    unterscheiden** — dieselbe Regel wie am Fuß der Nachrichtenliste."""
    from app.services.termine import SUCHE_HOECHSTENS

    for i in range(SUCHE_HOECHSTENS + 3):
        _anlegen(klient, welt, f"Reihenprobe {i}", tag=(i % 27) + 1)
    ergebnis = _suchen(klient, "Reihenprobe")
    assert len(ergebnis["treffer"]) == SUCHE_HOECHSTENS
    assert ergebnis["abgeschnitten"] is True


def _dienstsuche(db, klient, wort, jetzt):
    """Am Dienst statt ueber die Adresse — nur so laesst sich „jetzt" setzen.

    ⚠️ **Ohne festes „jetzt" prueft der Test die Uhr.** Er waere heute gruen und
    in einem Jahr rot, ohne dass jemand etwas geaendert hat.
    """
    from app.models import Benutzer
    from app.services import termine as dienst

    person = db.query(Benutzer).one()
    treffer, _ = dienst.suchen(db, person, wort, jetzt=jetzt)
    return treffer


def test_eine_reihe_zeigt_ihr_naechstes_vorkommen(klient, db, welt):
    """⚠️ **Das naechste, nicht das erste.** „Team-Runde" gibt es zweihundertmal;
    wer sie sucht, meint fast immer die naechste. Das erste Vorkommen liegt bei
    einer alten Reihe Jahre zurueck und beantwortet keine Frage."""
    _anlegen(klient, welt, "Team-Runde", tag=1, rrule="FREQ=WEEKLY")
    # Zwei Wochen spaeter: der 15. September ist der naechste Montagstermin.
    treffer = _dienstsuche(db, klient, "team", datetime(2026, 9, 12, tzinfo=timezone.utc))
    assert len(treffer) == 1
    assert treffer[0].beginn.date() == date(2026, 9, 15)
    assert treffer[0].aus_reihe is True


def test_eine_abgelaufene_reihe_zeigt_ihr_letztes_vorkommen(klient, db, welt):
    """⚠️ Sonst stuende dort das Startdatum von vor drei Jahren, und der Termin
    saehe aus, als faende er noch statt."""
    _anlegen(klient, welt, "Alte Runde", tag=1, rrule="FREQ=WEEKLY;COUNT=3")
    treffer = _dienstsuche(db, klient, "alte", datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert treffer[0].beginn.date() == date(2026, 9, 15)


def test_das_naechstliegende_steht_oben(klient, db, welt):
    """⚠️ Nicht das aelteste. Wer sucht, meint in aller Regel etwas, das noch
    kommt; eine Sortierung nach Datum begoenne mit der aeltesten Karteileiche."""
    _anlegen(klient, welt, "Probe frueh", tag=2)
    _anlegen(klient, welt, "Probe spaet", tag=28)
    treffer = _dienstsuche(db, klient, "probe", datetime(2026, 9, 26, tzinfo=timezone.utc))
    assert [t.termin.titel for t in treffer] == ["Probe spaet", "Probe frueh"]


# --- Absage beim Loeschen -------------------------------------------------- #
#
# ⚠️ **Hier entscheidet sich, ob nexmail ungefragt Post verschickt.** Die
# Dienstschicht daneben prueft nur, dass die Absage richtig gebaut ist; ob sie
# ueberhaupt hinausgeht, entscheidet allein diese Adresse.


def _termin_mit_einladung(klient, db, welt):
    from app.models import Termin

    neu = klient.post(
        "/api/kalender/termine",
        json={
            "kalender_id": welt["id"],
            "titel": "Quartalsrunde",
            "beginn": _wann(20),
            "teilnehmer": [{"adresse": "anja@example.org"}],
        },
    )
    assert neu.status_code == 201, neu.text
    # ⚠️ Der Absender wird beim Anlegen gegen die Postfaecher gehalten, und
    # hier gibt es keine. Fuer diese Adresse zaehlt nur, OB abgesagt wird —
    # der Dienst dahinter ist untergeschoben.
    termin = db.get(Termin, neu.json()["id"])
    termin.eingeladen_am = datetime(2026, 9, 5, tzinfo=timezone.utc)
    db.commit()
    return neu.json()


def test_ohne_den_wunsch_geht_keine_absage_hinaus(klient, db, welt, monkeypatch):
    from app.services import termineinladung

    neu = _termin_mit_einladung(klient, db, welt)
    gerufen = []
    monkeypatch.setattr(
        termineinladung, "absagen", lambda *a, **k: gerufen.append(1) or 0
    )

    assert klient.delete(f"/api/kalender/termine/{neu['id']}").status_code == 204
    assert gerufen == []


def test_mit_dem_wunsch_geht_sie_hinaus_und_zwar_vorher(klient, db, welt, monkeypatch):
    """⚠️ **Erst absagen, dann loeschen.** Danach ist der Termin fort, samt
    Teilnehmerliste und Nummer — die Absage waere nicht mehr zu bauen."""
    from app.models import Termin
    from app.services import termineinladung

    neu = _termin_mit_einladung(klient, db, welt)
    stand = []

    def merken(db_, person, termin):
        stand.append(termin.titel)
        return 1

    monkeypatch.setattr(termineinladung, "absagen", merken)

    antwort = klient.delete(f"/api/kalender/termine/{neu['id']}?absagen=true")
    assert antwort.status_code == 204, antwort.text
    assert stand == ["Quartalsrunde"]
    assert db.get(Termin, neu["id"]) is None


def test_ein_fremder_termin_wird_auch_hier_nicht_abgesagt(klient, db, welt, monkeypatch):
    from app.models import Benutzer as Person
    from app.models import Termin
    from app.services import termineinladung

    neu = _termin_mit_einladung(klient, db, welt)
    # Der Termin gehoert ab jetzt jemand anderem.
    fremd = Person(benutzername="fremd", passwort_hash="x")
    db.add(fremd)
    db.commit()
    db.get(Termin, neu["id"]).benutzer_id = fremd.id
    db.commit()

    gerufen = []
    monkeypatch.setattr(
        termineinladung, "absagen", lambda *a, **k: gerufen.append(1) or 0
    )

    klient.delete(f"/api/kalender/termine/{neu['id']}?absagen=true")
    assert gerufen == []


def test_eine_fremde_antwort_steht_in_der_termin_zeile(klient, db, welt):
    """⚠️ Ohne den Weg nach oben sieht der Betreiber sie nur im Protokoll —
    und dort sieht niemand nach, der einen Termin ansieht."""
    import json as _json

    from app.models import Termin

    neu = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Runde", "beginn": _wann(20)},
    ).json()
    termin = db.get(Termin, neu["id"])
    termin.fremde_antworten = _json.dumps(
        [{"adresse": "fremd@example.net", "antwort": "ACCEPTED", "am": "2026-09-04T10:00:00+00:00"}]
    )
    db.commit()

    zeile = [t for t in _fenster(klient) if t["id"] == neu["id"]][0]
    assert zeile["fremde_antworten"] == [
        {"adresse": "fremd@example.net", "antwort": "ACCEPTED", "am": "2026-09-04T10:00:00+00:00"}
    ]


# --- .ics herunterladen und einspielen ------------------------------------ #


def _ics(uid: str = "probe-1@example.org") -> bytes:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        f"UID:{uid}\r\nDTSTART:20260920T090000Z\r\nDTEND:20260920T100000Z\r\n"
        "SUMMARY:Aus der Datei\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode("utf-8")


def test_der_download_traegt_dateinamen_und_typ(klient, welt):
    klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Zahnarzt", "beginn": _wann(20)},
    )
    antwort = klient.get(f"/api/kalender/{welt['id']}/ics")

    assert antwort.status_code == 200, antwort.text
    assert antwort.headers["content-type"].startswith("text/calendar")
    # ⚠️ Ohne den Dateinamen speichert der Browser sie als „ics" ohne Endung.
    assert ".ics" in antwort.headers["content-disposition"]
    assert antwort.text.startswith("BEGIN:VCALENDAR")
    assert "SUMMARY:Zahnarzt" in antwort.text


def test_eine_datei_wird_eingespielt(klient, welt):
    antwort = klient.post(
        f"/api/kalender/{welt['id']}/ics",
        files={"datei": ("umzug.ics", _ics(), "text/calendar")},
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["angelegt"] == 1
    assert any(t["titel"] == "Aus der Datei" for t in _fenster(klient))


def test_eine_leere_datei_wird_benannt(klient, welt):
    antwort = klient.post(
        f"/api/kalender/{welt['id']}/ics",
        files={"datei": ("leer.ics", b"", "text/calendar")},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "datei_leer"


def test_ein_fremder_kalender_gibt_nichts_heraus(klient, db, welt):
    """⚠️ Ohne diese Prüfung lädt jeder Angemeldete jeden Kalender herunter."""
    from app.models import Benutzer as Person
    from app.models import Kalender

    fremd = Person(benutzername="zweiter", passwort_hash="x")
    db.add(fremd)
    db.commit()
    seiner = Kalender(benutzer_id=fremd.id, name="Fremd", farbe=1)
    db.add(seiner)
    db.commit()

    assert klient.get(f"/api/kalender/{seiner.id}/ics").status_code == 404
    assert (
        klient.post(
            f"/api/kalender/{seiner.id}/ics",
            files={"datei": ("x.ics", _ics(), "text/calendar")},
        ).status_code
        == 404
    )


# --- Der Konflikt über die Adressen --------------------------------------- #


def test_die_fremde_fassung_gibt_es_nur_fuer_den_eigenen_termin(klient, db, welt):
    """⚠️ Sonst sähe jeder Angemeldete in jeden fremden Kalender."""
    from app.models import Benutzer as Person
    from app.models import Kalender, Termin

    fremd = Person(benutzername="zweiter", passwort_hash="x")
    db.add(fremd)
    db.commit()
    seiner = Kalender(benutzer_id=fremd.id, name="Fremd", farbe=1)
    db.add(seiner)
    db.commit()
    seinTermin = Termin(
        kalender_id=seiner.id,
        benutzer_id=fremd.id,
        uid="fremd@example.org",
        titel="Nicht meiner",
        beginn=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
    )
    db.add(seinTermin)
    db.commit()

    assert klient.get(f"/api/kalender/termine/{seinTermin.id}/konflikt").status_code == 404
    assert klient.post(f"/api/kalender/termine/{seinTermin.id}/konflikt").status_code == 404


def test_ohne_gegenstelle_gibt_es_keine_fremde_fassung(klient, welt):
    """Ein Kalender, der nur hier lebt, kann nicht woanders geändert werden."""
    neu = klient.post(
        "/api/kalender/termine",
        json={"kalender_id": welt["id"], "titel": "Nur hier", "beginn": _wann(20)},
    ).json()

    antwort = klient.get(f"/api/kalender/termine/{neu['id']}/konflikt")

    assert antwort.status_code == 200
    assert antwort.json()["vorhanden"] is False
