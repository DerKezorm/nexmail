"""Ein Modell, das erst nachdenkt, im eigenen Netz.

Qwen3 oder DeepSeek-R1 über Ollama verbrauchten die Tokens einer Antwort mit
ihren Gedanken; eine Zusammenfassung (1.000) kam leer zurück, und nexmail
sagte nur „Der Dienst hat nichts zurückgegeben". Wie in nexpaper 1.5.1:
``reasoning_effort: "none"`` an einen Dienst im eigenen Netz, einmal ohne,
wenn ein Server das Feld ablehnt, und ein eigener Satz, wenn die Grenze die
Antwort aufgebraucht hat.

⚠️ **Nichts geht ins echte Netz, auch keine Namensauflösung.** Der Dienst ist
ein Doppelgänger, und ``getaddrinfo`` antwortet aus einer Tabelle.
"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from app.models import Benutzer
from app.services import anmeldebremse
from app.services import kidienst as dienst
from conftest import einrichten
from test_kidienst import SCHLUESSEL, TextDoppelgaenger

#: Modul ki 0.1.0: eine Installation von vorher („Jedes Konto selbst“, Rechner auf der Liste, DNS der Tests).
pytestmark = pytest.mark.usefixtures("ki_wie_vorher")

LOKAL = "http://10.0.0.20:11434/v1/"
DRAUSSEN = "https://api.example.com/v1/"

#: Was die Namensauflösung je Name liefert. Nicht darin heisst: unbekannt.
NAMEN = {
    "api.example.com": ["8.8.8.8"],
    "ollama": ["172.16.5.9"],
    "ki.intern.example": ["10.0.0.20"],
    "halb.example": ["10.0.0.20", "8.8.4.4"],
    "localhost": ["127.0.0.1", "::1"],
}


@pytest.fixture(autouse=True)
def namen(monkeypatch):
    def aufloesen(host, *_args, **_kwargs):
        if host not in NAMEN:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0))
            for a in NAMEN[host]
        ]

    monkeypatch.setattr(dienst.socket, "getaddrinfo", aufloesen)
    # Das Modul ki löst selbst auf (``nexki.client.resolver``), aus derselben Tabelle.
    from app.vendor import nexki
    from conftest import ki_aufloesen

    monkeypatch.setattr(nexki.client, "resolver", ki_aufloesen(NAMEN))


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    return db.query(Benutzer).one()


def _bereit(db, person, url):
    dienst.erlauben(db, True)
    dienst.fremde_post_erlauben(db, True)
    dienst.einstellung_schreiben(db, person, url=url, modell="qwen3:8b", schluessel=SCHLUESSEL)
    dienst.einstellung_schreiben(db, person, aktiv=True, fremde_post=True)
    return person


def _bearbeiten(db, person, transport):
    return dienst.text_bearbeiten(
        person, "<p>Hallo, hier steht Text</p>", auftrag="rechtschreibung",
        transport=transport, db=db,
    )


def _fassen(db, person, transport):
    return dienst.zusammenfassen(
        person, db, absender="Anja <anja@example.org>", betreff="Rechnung",
        text="Bitte zahlen Sie die Rechnung 4711 bis zum 15. November.",
        sprache="de", transport=transport,
    )


class Pingelig(TextDoppelgaenger):
    """Weist jeden Rumpf ab, der eines der genannten Felder trägt, mit dem
    Satz, den ein Server dazu sagt."""

    def __init__(self, absagen: dict[str, str], **kw):
        super().__init__(**kw)
        self.absagen = absagen

    def transport(self):
        weiter = super().transport()

        def antworten(anfrage: httpx.Request) -> httpx.Response:
            rumpf = json.loads(anfrage.content or b"{}")
            for feld, satz in self.absagen.items():
                if feld in rumpf:
                    self.anfragen.append((str(anfrage.url), {}, rumpf))
                    return httpx.Response(400, json={"error": {"message": satz}})
            return weiter.handle_request(anfrage)

        return httpx.MockTransport(antworten)


# --- Wo der Dienst steht --------------------------------------------------- #


@pytest.mark.parametrize(
    "url, erwartet",
    [
        ("http://10.0.0.20:11434/v1/", True),
        ("http://172.16.5.9:1234/v1/", True),
        ("http://127.0.0.1:11434/v1/", True),
        ("http://[::1]:11434/v1/", True),
        ("http://100.101.102.103:11434/v1/", True),  # Tailscale
        ("http://[fd00::20]:11434/v1/", True),
        ("http://ollama:11434/v1/", True),  # Dienst im selben Docker-Netz
        ("http://localhost:11434/v1/", True),
        ("https://ki.intern.example/v1/", True),  # eigenes DNS zeigt ins LAN
        ("https://api.example.com/v1/", False),
        ("http://8.8.8.8/v1/", False),
        ("https://halb.example/v1/", False),  # ein Ziel draussen reicht
        ("https://unbekannt.example/v1/", False),  # nicht auflösbar
        ("", False),
    ],
)
def test_im_eigenen_netz(url, erwartet):
    assert dienst.im_eigenen_netz(url) is erwartet


# --- Was hinausgeht -------------------------------------------------------- #


def test_ein_dienst_im_eigenen_netz_soll_nicht_nachdenken(db, person):
    _bereit(db, person, LOKAL)
    server = TextDoppelgaenger()
    _bearbeiten(db, person, server.transport())
    assert server.anfragen[0][2]["reasoning_effort"] == "none"
    # In „Was hinausging" stehen seit dem Modul ki Anweisungen und Text (K5), nicht die Felder der Anfrage.
    assert dienst.vorgaenge_lesen(db, person)[0]["rumpf"]["messages"] == server.anfragen[0][2]["messages"]


def test_auch_beim_zusammenfassen(db, person):
    """⚠️ **Hier ist die Grenze am knappsten** (1.000 Tokens)."""
    _bereit(db, person, LOKAL)
    server = TextDoppelgaenger(inhalt="Eine Rechnung ist offen.")
    assert _fassen(db, person, server.transport()) == ("Eine Rechnung ist offen.", False)
    assert server.anfragen[0][2]["reasoning_effort"] == "none"
    assert server.anfragen[0][2]["max_tokens"] == dienst.MAX_TOKEN_ZUSAMMENFASSUNG


def test_ein_dienst_draussen_bekommt_das_feld_nicht(db, person):
    """⚠️ **Claude, Gemini und OpenAI bleiben, wie sie waren.** Dort ist das
    Feld je nach Modell unbekannt, abgelehnt oder ändert die Antwort."""
    _bereit(db, person, DRAUSSEN)
    server = TextDoppelgaenger()
    _bearbeiten(db, person, server.transport())
    _fassen(db, person, server.transport())
    assert len(server.anfragen) == 2
    assert all("reasoning_effort" not in rumpf for _, _, rumpf in server.anfragen)


@pytest.mark.parametrize(
    "satz",
    [
        "Unrecognized request argument supplied: reasoning_effort",
        'invalid reasoning value: "none"',
        '"llama3.1:8b" does not support thinking',
    ],
)
def test_wer_das_feld_ablehnt_wird_einmal_ohne_gefragt(db, person, satz):
    _bereit(db, person, LOKAL)
    server = Pingelig({"reasoning_effort": satz}, inhalt="<p>Korrigiert.</p>")
    assert _bearbeiten(db, person, server.transport()) == "<p>Korrigiert.</p>"
    erste, zweite = (rumpf for _, _, rumpf in server.anfragen)
    assert "reasoning_effort" in erste and "reasoning_effort" not in zweite
    assert {k: v for k, v in erste.items() if k != "reasoning_effort"} == zweite
    # In der Liste steht der Rumpf, der die Antwort gebracht hat.
    assert "reasoning_effort" not in dienst.vorgaenge_lesen(db, person)[0]["rumpf"]


def test_beide_felder_abgelehnt_heisst_drei_anfragen(db, person):
    _bereit(db, person, LOKAL)
    server = Pingelig(
        {
            "reasoning_effort": "Unrecognized request argument supplied: reasoning_effort",
            "temperature": "`temperature` is deprecated for this model.",
        }
    )
    assert _bearbeiten(db, person, server.transport()) == "<p>Sauber.</p>"
    assert len(server.anfragen) == 3
    letzte = server.anfragen[-1][2]
    assert "reasoning_effort" not in letzte and "temperature" not in letzte


def test_jedes_feld_hoechstens_einmal(db, person):
    """Wer auch ohne das Feld weiter von Nachdenken spricht, bekommt keine
    dritte Anfrage: zwei, dann der Fehler mit seinem Satz."""
    _bereit(db, person, LOKAL)
    anfragen = []

    def stur(anfrage):
        anfragen.append(json.loads(anfrage.content))
        return httpx.Response(400, json={"error": {"message": "thinking is not supported"}})

    with pytest.raises(dienst.KiFehler) as f:
        _bearbeiten(db, person, httpx.MockTransport(stur))
    assert len(anfragen) == 2
    # Modul ki: die eigenen Worte eines Dienstes nur aus dem Internet; im eigenen Netz bleibt es bei der Kennung.
    assert f.value.kennung == "ki_dienst_antwortet_nicht"


def test_eine_andere_400_geht_nicht_noch_einmal_hinaus(db, person):
    _bereit(db, person, LOKAL)
    server = TextDoppelgaenger(code=400, roh={"error": {"message": 'model "qwen3:8b" not found'}})
    with pytest.raises(dienst.KiFehler):
        _bearbeiten(db, person, server.transport())
    assert len(server.anfragen) == 1


def test_draussen_loest_ein_satz_ueber_nachdenken_nichts_aus(db, person):
    """Ohne das Feld im Rumpf gibt es nichts wegzulassen."""
    _bereit(db, person, DRAUSSEN)
    server = TextDoppelgaenger(code=400, roh={"error": {"message": "reasoning is not supported"}})
    with pytest.raises(dienst.KiFehler):
        _bearbeiten(db, person, server.transport())
    assert len(server.anfragen) == 1


# --- Wenn die Gedanken alles aufbrauchen ----------------------------------- #


def _aufgebraucht(inhalt, grund):
    """So antwortet Ollama, wenn das Nachdenken die Grenze erreicht hat."""
    return TextDoppelgaenger(
        roh={
            "choices": [
                {
                    "message": {"role": "assistant", "content": inhalt, "reasoning": "Okay, let me think"},
                    "finish_reason": grund,
                }
            ]
        }
    )


@pytest.mark.parametrize("inhalt", ["", None, "   "])
@pytest.mark.parametrize("weg", [_bearbeiten, _fassen])
def test_aufgebraucht_hat_einen_eigenen_satz(db, person, weg, inhalt):
    _bereit(db, person, LOKAL)
    with pytest.raises(dienst.KiFehler) as f:
        weg(db, person, _aufgebraucht(inhalt, "length").transport())
    assert f.value.kennung == "ki_antwort_aufgebraucht"
    # Der Text war draussen, also steht der Vorgang in der Liste.
    assert dienst.vorgaenge_lesen(db, person)[0]["fehler"] == "ki_antwort_aufgebraucht"


@pytest.mark.parametrize("weg", [_bearbeiten, _fassen])
def test_leer_ohne_grenze_bleibt_leer(db, person, weg):
    _bereit(db, person, LOKAL)
    with pytest.raises(dienst.KiFehler) as f:
        weg(db, person, _aufgebraucht("", "stop").transport())
    assert f.value.kennung == "ki_antwort_leer"


def test_auch_draussen_gilt_der_satz(db, person):
    """Ein Modell, dessen Nachdenken sich nicht abschalten lässt, kann auch
    bei einem Dienst draussen die Grenze aufbrauchen."""
    _bereit(db, person, DRAUSSEN)
    with pytest.raises(dienst.KiFehler) as f:
        _fassen(db, person, _aufgebraucht("", "length").transport())
    assert f.value.kennung == "ki_antwort_aufgebraucht"


def test_die_adresse_meldet_den_satz(klient, db, person, monkeypatch):
    """Über den echten Weg: Die Kennung kommt bei der Oberfläche an, und in der
    Liste steht der Rumpf mit dem Feld."""
    _bereit(db, person, LOKAL)
    server = _aufgebraucht("", "length")
    echt = dienst.text_bearbeiten
    monkeypatch.setattr(
        dienst, "text_bearbeiten",
        lambda *a, **k: echt(*a, **{**k, "transport": server.transport()}),
    )
    antwort = klient.post(
        "/api/ki/text", json={"text": "<p>Hallo, hier steht Text</p>", "auftrag": "rechtschreibung"}
    )
    assert antwort.status_code >= 400
    assert antwort.json()["detail"] == "ki_antwort_aufgebraucht"
    zeile = klient.get("/api/ki/vorgaenge").json()[0]
    assert zeile["fehler"] == "ki_antwort_aufgebraucht"
    assert server.anfragen[0][2]["reasoning_effort"] == "none" and zeile["rumpf"]["messages"]
