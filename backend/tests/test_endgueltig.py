"""Ausgewählte Mails endgültig löschen, und den Papierkorb leeren über die App.

⚠️ **Der einzige Weg neben dem Leeren, auf dem Post ohne Rückweg verschwindet.**
Deshalb nur aus Papierkorb und Junk, und eine einzige Mail von woanders hält die
ganze Auswahl auf. Gewünscht aus TestFlight: Im Papierkorb löschen meldete „Die
Nachricht liegt schon dort.“
"""

from __future__ import annotations

import pytest

from app.main import app
from app.models import Benutzer, Nachricht
from app.services import anmeldebremse
from test_app_flaeche import PFAD, abholen, koppeln
from test_gemischte_auswahl import Zugserver
from test_gemischte_auswahl import welt as _welt  # noqa: F401  (die Welt dort)


class Loeschserver(Zugserver):
    """Kennt ``\\Deleted`` so, wie ein echter Server es behandelt."""

    def __init__(self, name: str, uidplus: bool = True):
        super().__init__(name)
        self.uidplus = uidplus
        self.expunge_gerufen = 0

    def capabilities(self):
        return [b"IMAP4REV1", b"MOVE"] + ([b"UIDPLUS"] if self.uidplus else [])

    def _hier(self):
        return self.ordner[self._aktuell]["nachrichten"]

    def remove_flags(self, uids, flags):
        for uid in uids:
            if uid in self._hier() and any(b"Deleted" in f for f in flags):
                self._hier()[uid]["geloescht"] = False

    def uid_expunge(self, uids):
        # ⚠️ Wie RFC 4315: nur die genannten, und nur, wenn sie markiert sind.
        for uid in uids:
            if self._hier().get(uid, {}).get("geloescht"):
                del self._hier()[uid]
                self.geloescht.append(uid)

    def expunge(self):
        self.expunge_gerufen += 1
        for uid in [u for u, e in self._hier().items() if e.get("geloescht")]:
            del self._hier()[uid]
            self.geloescht.append(uid)

    def search(self, kriterien):
        if kriterien == ["DELETED"]:
            return sorted(u for u, e in self._hier().items() if e.get("geloescht"))
        return super().search(kriterien)


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def welt(_welt):
    """Dieselbe Welt wie bei der gemischten Auswahl, mit Servern, die ``\\Deleted`` kennen.

    Dazu ein Junk in kb und je Papierkorb eine Mail."""
    for kennung, alt in list(_welt.server.items()):
        neu = Loeschserver(kennung)
        neu.ordner = alt.ordner
        _welt.server[kennung] = neu
    _welt.ordner_anlegen("kb", "Junk", "junk")
    _welt.weg_a = _welt.mail("ka", "Trash", "Weg-A")
    _welt.weg_b = _welt.mail("kb", "Trash", "Weg-B")
    return _welt


def _endgueltig(klient, *ids):
    return klient.post("/api/nachrichten/endgueltig", json={"ids": list(ids)})


def _markiert(welt, konto, pfad) -> list[int]:
    return sorted(u for u, e in welt.server[konto].ordner[pfad]["nachrichten"].items() if e.get("geloescht"))


# --- Nur Papierkorb und Junk ------------------------------------------------ #


def test_aus_dem_papierkorb_ist_sie_weg(klient, welt):
    antwort = _endgueltig(klient, welt.weg_a)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"bewegt": 1, "nicht_bewegt": 0, "rueckweg": None}
    assert welt.zahl("ka", "Trash") == 0
    assert welt.zeilen("ka", "Trash") == []
    assert welt.ordner[("ka", "Trash")].anzahl == 0


def test_aus_dem_junk_geht_es_auch(klient, welt):
    spam = welt.mail("kb", "Junk", "Spam")

    antwort = _endgueltig(klient, spam)

    assert antwort.status_code == 200, antwort.text
    assert welt.zahl("kb", "Junk") == 0


@pytest.mark.parametrize("woanders", ["a", "archiv"])
def test_eine_mail_von_woanders_haelt_alles_auf(klient, welt, woanders):
    antwort = _endgueltig(klient, welt.weg_a, getattr(welt, woanders), welt.weg_b)

    assert antwort.status_code == 400, antwort.text
    assert antwort.json()["detail"] == "nur_papierkorb_und_junk"
    # ⚠️ Nichts angefasst, auch nicht markiert: Die Prüfung kommt vor dem Server.
    assert (welt.zahl("ka", "Trash"), welt.zahl("kb", "Trash")) == (1, 1)
    assert _markiert(welt, "ka", "Trash") == [] and _markiert(welt, "kb", "Trash") == []
    assert welt.zeilen("ka", "Trash") == ["Weg-A"]
    assert welt.zahl("ka", "INBOX") == 1 and welt.zahl("ka", "Archive") == 1


def test_nichts_ausgewaehlt(klient, welt):
    assert _endgueltig(klient).status_code == 400


# --- Nur die gewählten ------------------------------------------------------ #


def test_uid_expunge_nimmt_nur_die_gewaehlten(klient, welt):
    welt.mail("ka", "Trash", "Bleibt")
    welt.server["ka"].ordner["Trash"]["nachrichten"][2]["geloescht"] = True  # von einem anderen Programm
    zweite = welt.mail("ka", "Trash", "Weg-Zwei")

    antwort = _endgueltig(klient, welt.weg_a, zweite)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 2
    assert welt.zahl("ka", "Trash") == 1
    assert welt.zeilen("ka", "Trash") == ["Bleibt"]
    assert welt.server["ka"].expunge_gerufen == 0


def test_ohne_uidplus_und_allein_markiert_geht_expunge(klient, welt):
    welt.server["ka"].uidplus = False
    welt.mail("ka", "Trash", "Bleibt")

    antwort = _endgueltig(klient, welt.weg_a)

    assert antwort.status_code == 200, antwort.text
    assert welt.server["ka"].expunge_gerufen == 1
    assert welt.zeilen("ka", "Trash") == ["Bleibt"]
    assert welt.zahl("ka", "Trash") == 1


def test_ohne_uidplus_bleibt_alles_wenn_andere_markiert_sind(klient, welt):
    welt.server["ka"].uidplus = False
    welt.mail("ka", "Trash", "Fremd markiert")
    welt.server["ka"].ordner["Trash"]["nachrichten"][2]["geloescht"] = True

    antwort = _endgueltig(klient, welt.weg_a)

    assert antwort.status_code == 400, antwort.text
    assert antwort.json()["detail"] == "endgueltig_nicht_allein"
    assert welt.server["ka"].expunge_gerufen == 0
    assert welt.zahl("ka", "Trash") == 2
    # Die eigene Markierung ist zurückgenommen, die fremde bleibt.
    assert _markiert(welt, "ka", "Trash") == [2]
    assert welt.zeilen("ka", "Trash") == ["Fremd markiert", "Weg-A"]


# --- Gemischte Auswahl ------------------------------------------------------ #


def test_zwei_postfaecher_auf_einmal(klient, welt):
    spam = welt.mail("kb", "Junk", "Spam")

    antwort = _endgueltig(klient, welt.weg_a, welt.weg_b, spam)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 3
    assert (welt.zahl("ka", "Trash"), welt.zahl("kb", "Trash"), welt.zahl("kb", "Junk")) == (0, 0, 0)


def test_ein_stummes_postfach_haelt_das_andere_nicht_auf(klient, welt):
    welt.gesperrt.add("kb")

    antwort = _endgueltig(klient, welt.weg_a, welt.weg_b)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 1
    assert antwort.json()["nicht_bewegt"] == 1
    assert welt.zahl("ka", "Trash") == 0
    assert welt.zeilen("kb", "Trash") == ["Weg-B"]


def test_scheitert_alles_kommt_der_grund_heraus(klient, welt):
    welt.gesperrt.update({"ka", "kb"})

    antwort = _endgueltig(klient, welt.weg_a, welt.weg_b)

    assert antwort.status_code == 502, antwort.text
    assert welt.zeilen("ka", "Trash") == ["Weg-A"]
    assert welt.zeilen("kb", "Trash") == ["Weg-B"]


def test_doppelt_genannt_zaehlt_einmal(klient, welt):
    antwort = _endgueltig(klient, welt.weg_a, welt.weg_a)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 1


def test_fremde_post_gibt_404_und_nichts_verschwindet(klient, welt, db):
    fremd = Benutzer(id="f" * 32, benutzername="fremd", anzeigename="Fremd", passwort_hash="x")
    db.add(fremd)
    db.flush()
    db.get(Nachricht, welt.weg_b).benutzer_id = fremd.id
    db.commit()

    antwort = _endgueltig(klient, welt.weg_a, welt.weg_b)

    assert antwort.status_code == 404, antwort.text
    assert welt.zahl("ka", "Trash") == 1 and welt.zahl("kb", "Trash") == 1


# --- Die App ---------------------------------------------------------------- #


@pytest.fixture
def kein_cookie():
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def bearer(klient, kein_cookie, welt):
    schluessel = abholen(kein_cookie, koppeln(klient)).json()["key"]
    return {"Authorization": f"Bearer {schluessel}"}


def test_die_app_loescht_endgueltig(kein_cookie, bearer, welt):
    antwort = kein_cookie.post(
        f"{PFAD}/messages/delete-forever", headers=bearer, json={"ids": [welt.weg_a, welt.weg_b]}
    )

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 2
    assert welt.zahl("ka", "Trash") == 0 and welt.zahl("kb", "Trash") == 0


def test_die_app_haelt_sich_an_dieselbe_regel(kein_cookie, bearer, welt):
    antwort = kein_cookie.post(
        f"{PFAD}/messages/delete-forever", headers=bearer, json={"ids": [welt.weg_a, welt.a]}
    )

    assert antwort.status_code == 400, antwort.text
    assert antwort.json()["detail"] == "nur_papierkorb_und_junk"
    assert welt.zahl("ka", "Trash") == 1


def test_die_app_leert_den_papierkorb(kein_cookie, bearer, welt):
    papierkorb = welt.ordner[("ka", "Trash")]
    welt.mail("ka", "Trash", "Noch eine")

    antwort = kein_cookie.post(f"{PFAD}/folders/{papierkorb.id}/empty", headers=bearer)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["bewegt"] == 2
    assert welt.zahl("ka", "Trash") == 0
    assert welt.zahl("kb", "Trash") == 1


def test_die_app_leert_keinen_posteingang(kein_cookie, bearer, welt):
    eingang = welt.ordner[("ka", "INBOX")]

    antwort = kein_cookie.post(f"{PFAD}/folders/{eingang.id}/empty", headers=bearer)

    assert antwort.status_code == 400, antwort.text
    assert antwort.json()["detail"] == "nur_papierkorb_und_junk"
    assert welt.zahl("ka", "INBOX") == 1


def test_die_app_erfaehrt_es_aus_me(kein_cookie, bearer):
    antwort = kein_cookie.get(f"{PFAD}/me", headers=bearer)

    assert "endgueltig_loeschen" in antwort.json()["faehigkeiten"]


def test_ein_cookie_oeffnet_die_app_wege_nicht(klient, welt):
    antwort = klient.post(f"{PFAD}/messages/delete-forever", json={"ids": [welt.weg_a]})

    assert antwort.status_code == 401
    assert welt.zahl("ka", "Trash") == 1
