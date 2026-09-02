"""Textvorlagen — wiederkehrende Antworten fuer das Verfassen-Fenster.

⚠️ **Zwei Dinge muessen hier sitzen**, und beide sind still, wenn sie fehlen:

1. Der Name ist je Benutzer einmalig — zwei gleichnamige Eintraege saehen im
   Vorlagen-Menue identisch aus, und welcher eingefuegt wird, entschiede der
   Zufall. Die Absage traegt eine KENNUNG, keinen deutschen Satz.
2. Die Trennung zweier Benutzer — eine Vorlage, die beim Nachbarn im Menue
   auftaucht, ist ein Datenleck, das erst beim Oeffnen auffaellt.
"""

from __future__ import annotations

from conftest import anmelden, einrichten, zweiten_benutzer_anlegen


def test_anlegen_wiederfinden_aendern_entfernen(klient):
    einrichten(klient)

    antwort = klient.post(
        "/api/textvorlagen",
        json={"name": "Absage", "inhalt_html": "<p>Leider nein.</p>"},
    )
    assert antwort.status_code == 201, antwort.text
    vorlage = antwort.json()
    assert vorlage["name"] == "Absage"
    assert "Leider nein." in vorlage["inhalt_html"]

    liste = klient.get("/api/textvorlagen").json()
    assert [v["name"] for v in liste] == ["Absage"]

    geaendert = klient.put(
        f"/api/textvorlagen/{vorlage['id']}",
        json={"name": "Zusage", "inhalt_html": "<p>Gerne.</p>"},
    )
    assert geaendert.status_code == 200, geaendert.text
    assert geaendert.json()["name"] == "Zusage"
    assert "Gerne." in geaendert.json()["inhalt_html"]

    weg = klient.delete(f"/api/textvorlagen/{vorlage['id']}")
    assert weg.status_code == 204
    assert klient.get("/api/textvorlagen").json() == []


def test_der_inhalt_wird_bereinigt(klient):
    """Dieselbe Bereinigung wie beim Senden — der Editor ist keine
    Sicherheitsgrenze, und eine Vorlage landet wortwoertlich in einer Mail."""
    einrichten(klient)
    antwort = klient.post(
        "/api/textvorlagen",
        json={"name": "Boese", "inhalt_html": '<p>Hallo</p><script>alert(1)</script>'},
    )
    assert antwort.status_code == 201, antwort.text
    assert "<script" not in antwort.json()["inhalt_html"]
    assert "Hallo" in antwort.json()["inhalt_html"]


def test_ein_doppelter_name_wird_mit_kennung_abgewiesen(klient):
    einrichten(klient)
    erste = klient.post("/api/textvorlagen", json={"name": "Absage", "inhalt_html": "<p>A</p>"})
    assert erste.status_code == 201, erste.text

    # ⚠️ Klein verglichen — „absage" und „Absage" waeren im Menue nicht zu
    # unterscheiden. Dieselbe Entscheidung wie bei den Schlagworten.
    zweite = klient.post("/api/textvorlagen", json={"name": "absage", "inhalt_html": "<p>B</p>"})
    assert zweite.status_code == 409, zweite.text
    # Eine KENNUNG, kein deutscher Satz: Die Oberflaeche uebersetzt sie.
    assert zweite.json()["detail"] == "textvorlage_name_vergeben"

    # Umbenennen auf einen vergebenen Namen faellt genauso.
    dritte = klient.post("/api/textvorlagen", json={"name": "Zusage", "inhalt_html": "<p>C</p>"})
    assert dritte.status_code == 201
    umbenannt = klient.put(
        f"/api/textvorlagen/{dritte.json()['id']}",
        json={"name": "Absage", "inhalt_html": "<p>C</p>"},
    )
    assert umbenannt.status_code == 409
    assert umbenannt.json()["detail"] == "textvorlage_name_vergeben"

    # Der eigene Name ist dabei kein Doppel: Nur den Inhalt zu aendern geht.
    gleich = klient.put(
        f"/api/textvorlagen/{dritte.json()['id']}",
        json={"name": "Zusage", "inhalt_html": "<p>Neu</p>"},
    )
    assert gleich.status_code == 200, gleich.text


def test_ohne_namen_kommt_die_kennung(klient):
    einrichten(klient)
    antwort = klient.post("/api/textvorlagen", json={"name": "   ", "inhalt_html": "<p>A</p>"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "textvorlage_name_fehlt"


def test_die_reihenfolge_laesst_sich_ziehen(klient):
    einrichten(klient)
    ids = [
        klient.post("/api/textvorlagen", json={"name": n, "inhalt_html": "<p>x</p>"}).json()["id"]
        for n in ("Eins", "Zwei", "Drei")
    ]

    antwort = klient.put("/api/textvorlagen/reihenfolge", json={"ids": list(reversed(ids))})
    assert antwort.status_code == 204, antwort.text

    liste = klient.get("/api/textvorlagen").json()
    assert [v["name"] for v in liste] == ["Drei", "Zwei", "Eins"]


def test_zwei_benutzer_sind_getrennt(klient, zweiter_klient, db):
    """Die Trennung — hierauf laeuft die Mutationsprobe."""
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    # Zwei Vorlagen, und „Absage" steht bewusst auf Platz 1: Nur so faellt
    # unten auf, wenn das fremde Ziehen sie auf Platz 0 zoege — bei Platz 0
    # waere die Mutation (ordnen() laedt ungefiltert) unsichtbar.
    zuerst = klient.post(
        "/api/textvorlagen", json={"name": "Zusage", "inhalt_html": "<p>Zuerst</p>"}
    )
    assert zuerst.status_code == 201, zuerst.text
    meine = klient.post(
        "/api/textvorlagen", json={"name": "Absage", "inhalt_html": "<p>Geheim</p>"}
    )
    assert meine.status_code == 201, meine.text
    vorlage_id = meine.json()["id"]

    # Der Zweite sieht sie nicht.
    assert zweiter_klient.get("/api/textvorlagen").json() == []

    # Er kann sie weder aendern noch entfernen — und die Antwort verraet
    # nicht, dass es sie gibt.
    fremd_aendern = zweiter_klient.put(
        f"/api/textvorlagen/{vorlage_id}",
        json={"name": "Gekapert", "inhalt_html": "<p>X</p>"},
    )
    assert fremd_aendern.status_code == 404
    fremd_weg = zweiter_klient.delete(f"/api/textvorlagen/{vorlage_id}")
    assert fremd_weg.status_code == 404

    # Auch das Ziehen der Reihenfolge fasst fremde Zeilen nicht an — die
    # Antwort ist trotzdem 204: Unbekannte Kennungen stellen still nichts um.
    umgeordnet = zweiter_klient.put(
        "/api/textvorlagen/reihenfolge", json={"ids": [vorlage_id]}
    )
    assert umgeordnet.status_code == 204, umgeordnet.text

    # ⚠️ Und derselbe Name ist beim Nachbarn KEIN Doppel — die Einmaligkeit
    # gilt je Benutzer, nicht ueber alle.
    seine = zweiter_klient.post(
        "/api/textvorlagen", json={"name": "Absage", "inhalt_html": "<p>Seine</p>"}
    )
    assert seine.status_code == 201, seine.text

    # Beim Ersten steht alles unveraendert — auch die Reihenfolge: Haette
    # das fremde Ziehen „Absage" auf Platz 0 gezogen, stuende sie jetzt vorn.
    meine_liste = klient.get("/api/textvorlagen").json()
    assert [v["name"] for v in meine_liste] == ["Zusage", "Absage"]
    assert [v["reihenfolge"] for v in meine_liste] == [0, 1]
    assert "Geheim" in meine_liste[1]["inhalt_html"]
