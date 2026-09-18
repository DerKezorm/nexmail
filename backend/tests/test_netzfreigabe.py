"""Der Riegel fürs eigene Netz — Kalender, Adressbücher, ICS-Abos.

⚠️ **Geprüft wird in beide Richtungen.** Zu muss zu bleiben, auf muss
aufgehen, und was auch mit Freigabe nie erreichbar sein darf (der eigene
Rechner, die Metadaten-Adresse der Cloud-Anbieter), bekommt seinen eigenen
Test. Ein Schalter, der alles öffnet, bestünde sonst die ersten beiden.
"""

from __future__ import annotations

import pytest

from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

from app.services import bildvermittler, caldav, netzfreigabe

LAN = "https://10.0.0.5/remote.php/dav/"


def test_ab_werk_ist_das_eigene_netz_zu(db):
    assert netzfreigabe.erlaubt(db) is False
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav._pruefen(LAN)
    assert str(f.value) == "caldav_adresse_im_eigenen_netz"


def test_mit_freigabe_geht_das_lan(db):
    netzfreigabe.erlauben(db, True)
    caldav._pruefen(LAN)
    caldav._pruefen("https://172.16.4.4/dav/")


def test_mit_freigabe_geht_das_vpn(db):
    """Tailscale vergibt aus ``100.64.0.0/10``; dort steht der Server genauso
    oft wie im LAN."""
    netzfreigabe.erlauben(db, True)
    caldav._pruefen("https://100.100.20.30/dav/")


def test_zusperren_wirkt_sofort(db):
    netzfreigabe.erlauben(db, True)
    caldav._pruefen(LAN)
    netzfreigabe.erlauben(db, False)
    with pytest.raises(caldav.CaldavFehler):
        caldav._pruefen(LAN)


@pytest.mark.parametrize(
    "adresse",
    [
        "https://127.0.0.1/dav/",
        "https://[::1]/dav/",
        # ⚠️ Hier liegen die Metadaten-Dienste der Cloud-Anbieter, samt
        # Zugangsdaten. Ein Kalenderserver steht dort nie.
        "http://169.254.169.254/latest/meta-data/",
        "https://0.0.0.0/dav/",
        "https://0.1.2.3/dav/",
        "https://240.0.0.1/dav/",
    ],
)
def test_auch_mit_freigabe_bleibt_der_eigene_rechner_zu(db, adresse):
    netzfreigabe.erlauben(db, True)
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav._pruefen(adresse)
    assert str(f.value) == "caldav_adresse_im_eigenen_netz"


def test_ein_name_ins_lan_geht_mit_freigabe(db, monkeypatch):
    """Der gemeldete Fall: Nextcloud hinter einem Proxy, unter einem eigenen
    Namen, der auf eine Adresse im LAN zeigt."""
    monkeypatch.setattr(
        bildvermittler.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.20", 443))],
    )
    with pytest.raises(caldav.CaldavFehler):
        caldav._pruefen("https://cloud.example.com/remote.php/dav/")
    netzfreigabe.erlauben(db, True)
    caldav._pruefen("https://cloud.example.com/remote.php/dav/")


def test_jede_antwort_des_namensdienstes_zaehlt_auch_mit_freigabe(db, monkeypatch):
    """⚠️ Ein Name, der ins LAN **und** auf den eigenen Rechner zeigt, bleibt
    zu. Sonst genügte ein zweiter DNS-Eintrag, um die Ausnahme oben zu
    umgehen."""
    netzfreigabe.erlauben(db, True)
    monkeypatch.setattr(
        bildvermittler.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("10.0.0.20", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(caldav.CaldavFehler):
        caldav._pruefen("https://zweideutig.example.com/dav/")


def test_das_abo_folgt_demselben_riegel(db, monkeypatch):
    netzfreigabe.erlauben(db, True)
    gesehen: list[str] = []

    def kein_netz(*a, **k):
        gesehen.append("geprueft")
        raise caldav.httpx.ConnectError("kein Netz im Test")

    monkeypatch.setattr(caldav.httpx.Client, "stream", kein_netz)
    # Die Prüfung ist durch, sobald der Abruf überhaupt versucht wird.
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.abo_holen("https://10.0.0.5/f.ics")
    assert str(f.value) == "abo_nicht_erreichbar"
    assert gesehen == ["geprueft"]


def test_der_bildvermittler_bleibt_zu_egal_wie_der_schalter_steht(db):
    """⚠️ Dort kommt die Adresse aus einer fremden Mail."""
    netzfreigabe.erlauben(db, True)
    with pytest.raises(bildvermittler.Abgelehnt):
        bildvermittler.adresse_pruefen("http://10.0.0.5/bild.png")


# --- Die Adressen --------------------------------------------------------- #


def test_nur_der_betreiber_legt_den_schalter_um(klient, zweiter_klient, db):
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get("/api/einstellungen/eigenes-netz").status_code == 403
    antwort = zweiter_klient.put("/api/einstellungen/eigenes-netz", json={"erlaubt": True})
    assert antwort.status_code == 403
    assert netzfreigabe.erlaubt(db) is False

    antwort = klient.put("/api/einstellungen/eigenes-netz", json={"erlaubt": True})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"erlaubt": True}
    assert klient.get("/api/einstellungen/eigenes-netz").json() == {"erlaubt": True}


def test_die_oeffentliche_adresse_aendert_nur_der_betreiber(klient, zweiter_klient, db):
    """⚠️ Aus ihr entsteht der Link in der Mail „Kennwort vergessen". Wer sie
    umbiegen darf, lenkt den Rücksetz-Link des Betreibers auf einen fremden
    Server."""
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.put(
        "/api/einstellungen",
        json={"oeffentliche_adresse": "https://fremd.example.org", "zeitzone": ""},
    )
    assert antwort.status_code == 403
    assert klient.get("/api/einstellungen").json()["oeffentliche_adresse"] == ""

    # Lesen darf jeder Angemeldete weiterhin: Die Zeitzone braucht die
    # Oberfläche bei jedem Datum.
    assert zweiter_klient.get("/api/einstellungen").status_code == 200
