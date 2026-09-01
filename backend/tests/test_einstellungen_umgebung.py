"""Was aus der Umgebung kommt — und was passiert, wenn es krumm ist.

Diese Tests hängen nicht am Server, sondern an ``Settings``. Sie sind der
billigste Ort, an dem sich ein Container-Start retten lässt: Ein
Validierungsfehler hier heißt draußen „Container startet und stirbt sofort",
und die Meldung im Protokoll spricht von ``bool_parsing``.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def _mit(**umgebung) -> Settings:
    return Settings(**umgebung)


@pytest.mark.parametrize("leer", ["", "   "])
def test_leerer_notausgang_startet_trotzdem(leer):
    """⚠️ Genau der Fall aus der compose-Datei.

    Dort steht ``NEXMAIL_ZWEI_FAKTOR_AUS: ${...:-}`` — der Normalfall ist also
    eine **gesetzte, leere** Variable. Ohne diese Behandlung kommt der
    Container nicht hoch.
    """
    assert _mit(zwei_faktor_aus=leer).zwei_faktor_aus is False


@pytest.mark.parametrize("an", ["1", "true", "yes", "on"])
def test_notausgang_laesst_sich_setzen(an):
    assert _mit(zwei_faktor_aus=an).zwei_faktor_aus is True


@pytest.mark.parametrize(
    "eingabe,erwartet",
    [
        ("", ""),
        ("/", ""),
        ("nexmail", "/nexmail"),
        ("/nexmail/", "/nexmail"),
        ("https://example.com/nexmail/", "/nexmail"),
        ("/a/b", "/a/b"),
    ],
)
def test_unterpfad_wird_aufgeraeumt(eingabe, erwartet):
    """Wer eine ganze Adresse einträgt, bekommt deren Pfad.

    Das ist keine Bequemlichkeit: Ein Unterpfad mit Schema hätte Adressen wie
    ``/https://example.com/nexmail/api/health`` erzeugt, und der Fehler wäre
    erst im Browser aufgefallen.
    """
    assert _mit(url_base=eingabe).url_base == erwartet


def test_api_ist_als_unterpfad_verboten():
    """Er fiele mit der Schnittstelle zusammen."""
    with pytest.raises(ValueError, match="api"):
        _mit(url_base="/api")


@pytest.mark.parametrize("krumm", ["/mit leerzeichen", "/mit%20prozent", "/frage?"])
def test_krummer_unterpfad_wird_abgelehnt(krumm):
    with pytest.raises(ValueError):
        _mit(url_base=krumm)


@pytest.mark.parametrize("wert", ["auto", "on", "off"])
def test_cookie_secure_kennt_drei_werte(wert):
    assert _mit(cookie_secure=wert).cookie_secure == wert


def test_cookie_secure_lehnt_unsinn_ab():
    """Lieber gar nicht starten als raten.

    Ein falsch verstandenes „ja" hier heißt: Der Browser wirft das Cookie über
    http weg, und niemand kommt mehr hinein.
    """
    with pytest.raises(ValueError):
        _mit(cookie_secure="ja")


@pytest.mark.parametrize(
    "wert,proxys", [("", 0), ("direct", 0), ("proxy", 1), ("proxy:2", 2), ("proxy:3", 3)]
)
def test_proxy_tiefe(wert, proxys):
    assert _mit(client_ip=wert).anzahl_proxys() == proxys


def test_client_ip_lehnt_unsinn_ab():
    with pytest.raises(ValueError):
        _mit(client_ip="vielleicht")
