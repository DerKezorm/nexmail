"""Betrieb unter einem Unterpfad — ``https://mail.example.org/nexmail``.

⚠️ **Bis zum 01.09.2026 war davon nichts geprueft.** Die Middleware stand, der
Cookie-Pfad stand — und die ausgelieferte ``index.html`` verwies weiter mit
absoluten Pfaden auf sich selbst. Unter einem Vorbau haette der Browser
``/assets/…`` an der **Wurzel der Domain** gesucht, wohin der Proxy gar nicht
zeigt. Getestet war der halbe Weg.

⚠️ **Hier wird die Anwendung nicht neu geladen.** Der erste Anlauf tat das
(``importlib.reload``), um die Umgebungsvariable wirken zu lassen — und riss
damit fuenf fremde Tests um: ``conftest`` bindet ``app`` beim Import, und nach
einem Neuladen halten die Testdateien ein anderes Objekt als das Modul. Statt
dessen wird die **bestehende** Anwendung in die Middleware gewickelt und die
Umschreibung als reine Funktion geprueft. Beides ohne Nebenwirkung.

Den ganzen Weg durch einen **echten nginx** prueft
``pruefstand/unterpfad/`` — was hier schiefgeht, geht im Browser schief.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import _css_mit_vorbau, _index_mit_vorbau, app
from app.middleware import BasisPfadMiddleware, OberflaechePackenMiddleware

VORBAU = "/nexmail"


@pytest.fixture
def hinter_proxy(monkeypatch):
    """Die bestehende Anwendung hinter einem Proxy, der den Vorbau mitschickt.

    ⚠️ **Die Einstellung gehoert dazu, nicht nur die Middleware.** Ohne sie
    setzt der Server das Sitzungs-Cookie mit ``Path=/api`` — und der Browser
    schickt es unter ``/nexmail/api/...`` nicht mit. Beim ersten Anlauf sah
    das aus wie eine kaputte Anmeldung; in Wahrheit fehlte dem Test die halbe
    Aufstellung.

    ``cookie_pfad()`` liest die Einstellung bei **jedem** Aufruf — deshalb
    genuegt der geleerte Zwischenspeicher, und die Anwendung muss nicht neu
    geladen werden.
    """
    from app.config import get_settings

    monkeypatch.setenv("NEXMAIL_URL_BASE", VORBAU)
    get_settings.cache_clear()
    try:
        with TestClient(BasisPfadMiddleware(app, VORBAU)) as klient:
            yield klient
    finally:
        get_settings.cache_clear()


def test_jede_adresse_antwortet_doppelt(hinter_proxy):
    """⚠️ Mit **und** ohne Vorbau.

    Ein durchreichender Proxy schickt ihn mit — der Normalfall. Ein
    abschneidender entfernt ihn vorher, und der Docker-Healthcheck ruft
    ohnehin direkt an der Wurzel an.
    """
    assert hinter_proxy.get("/nexmail/api/health").status_code == 200
    assert hinter_proxy.get("/api/health").status_code == 200


def test_ein_nur_scheinbarer_vorbau_bleibt_unangetastet(hinter_proxy):
    """``/nexmailfoo`` traegt ihn nicht — dort darf nichts abgeschnitten werden."""
    antwort = hinter_proxy.get("/nexmailfoo/api/health")
    assert antwort.status_code != 200 or "status" not in antwort.text


def test_die_anwendung_bleibt_unter_dem_vorbau_bedienbar(hinter_proxy):
    """Der ganze Weg: einrichten, angemeldet bleiben — alles mit Vorbau."""
    angelegt = hinter_proxy.post(
        "/nexmail/api/setup/konto",
        json={"benutzername": "betreiber", "passwort": "sehr-geheim-123"},
    )
    assert angelegt.status_code == 201, angelegt.text
    assert hinter_proxy.get("/nexmail/api/auth/ich").status_code == 200


def test_das_sitzungscookie_traegt_den_vorbau(monkeypatch):
    """⚠️ **Ohne das faehrt es bei keiner Anfrage mit.**

    Ein Cookie mit ``Path=/api`` schickt der Browser unter
    ``/nexmail/api/...`` nicht — und die Anmeldung wirkt, als ginge sie nicht.
    """
    from app.config import get_settings
    from app.services import sitzung

    monkeypatch.setenv("NEXMAIL_URL_BASE", VORBAU)
    get_settings.cache_clear()
    try:
        assert sitzung.cookie_pfad() == "/nexmail/api"
    finally:
        get_settings.cache_clear()


# --- Die Umschreibung, als reine Funktion -------------------------------- #


@pytest.fixture
def gebaute_seite(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><script type="module" src="/assets/x.js"></script>'
        '<link rel="stylesheet" href="/assets/x.css">'
        '<link rel="icon" href="//fremder.example/f.ico"></head><body></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "assets" / "x.css").write_text(
        "@font-face{src:url(/assets/schrift.woff2) format('woff2')}", encoding="utf-8"
    )
    return tmp_path


def test_die_seite_verweist_mit_vorbau_auf_sich_selbst(gebaute_seite):
    """⚠️ **Der Teil, der gefehlt hat.**

    Ohne ihn sucht der Browser ``/assets/…`` an der Wurzel der Domain, findet
    nichts und zeigt eine weisse Seite — ohne eine einzige Meldung, die auf
    den Unterpfad zeigt.
    """
    html = _index_mit_vorbau(gebaute_seite / "index.html", VORBAU)
    assert 'src="/nexmail/assets/x.js"' in html
    assert 'href="/nexmail/assets/x.css"' in html
    assert 'src="/assets/x.js"' not in html


def test_fremde_adressen_bekommen_keinen_vorbau(gebaute_seite):
    """``//fremder.example`` zeigt auf einen anderen Host."""
    html = _index_mit_vorbau(gebaute_seite / "index.html", VORBAU)
    assert 'href="//fremder.example/f.ico"' in html


def test_die_oberflaeche_erfaehrt_ihren_vorbau(gebaute_seite):
    """⚠️ Als ``<meta>``, nicht als Inline-Skript.

    Die CSP sagt ``script-src 'self'`` und verwirft eine eingespritzte Zeile
    stumm — die Seite lud dann ohne Vorbau und zeigte gar keine Anmeldemaske.
    Am 01.09.2026 vom Pruefstand gefunden, nicht von Hand.
    """
    html = _index_mit_vorbau(gebaute_seite / "index.html", VORBAU)
    assert '<meta name="nexmail-basis" content="/nexmail">' in html
    assert "<script>window." not in html


def test_die_stilvorlage_verweist_mit_vorbau_auf_die_schriften(gebaute_seite):
    """⚠️ **Die ``index.html`` allein reicht nicht.**

    In der gebauten CSS stehen die Schriften als ``url(/assets/…)`` — ebenfalls
    absolut. Unter einem Unterpfad bekommt der Browser vierzehn 404er und
    faellt still auf Systemschriften zurueck. Die Seite sieht dabei fast
    richtig aus; genau deshalb faellt es von Hand nicht auf.
    """
    umgeschrieben = _css_mit_vorbau(gebaute_seite, VORBAU)
    assert "x.css" in umgeschrieben
    assert "url(/nexmail/assets/schrift.woff2)" in umgeschrieben["x.css"]


def test_ohne_vorbau_wird_nichts_angefasst(gebaute_seite):
    """⚠️ Der Regelfall darf durch die Vorbau-Arbeit nichts abbekommen."""
    assert _index_mit_vorbau(gebaute_seite / "index.html", "") is None
    assert _css_mit_vorbau(gebaute_seite, "") == {}


def test_eingebettete_schriften_sind_erlaubt(klient):
    """⚠️ **Betraf auch die gewoehnliche Installation.**

    Der Schriftsatz bringt einzelne Schnitte als ``data:``-URI mit. Mit
    ``font-src 'self'`` verwarf der Browser sie stumm, und die Oberflaeche fiel
    bei diesen Schnitten auf Systemschriften zurueck — auf **jeder**
    Installation, nicht nur unter einem Unterpfad.
    """
    regeln = klient.get("/api/health").headers.get("content-security-policy", "")
    assert "font-src 'self' data:" in regeln


# --- Der Auffangweg darf sein Verzeichnis nicht verlassen ---------------- #


def test_der_auffangweg_bleibt_in_seinem_verzeichnis(tmp_path):
    """⚠️ **Am 03.09.2026 gemessen: er tat es nicht.**

    ``/{pfad:path}`` baute ``_frontend / pfad`` und reichte die Datei durch.
    Ein ``..`` darin fuehrt aus dem Verzeichnis heraus, und im Abbild liegt
    zwei Ebenen ueber ``/app/static`` das Datenverzeichnis. Ein
    ``GET /../../data/secret.key`` kam mit HTTP 200 und dem Schluessel zurueck,
    ohne Anmeldung; die Datenbank kam denselben Weg. Nachgestellt wurde es an
    einem abbildaehnlichen Aufbau mit ``curl --path-as-is`` - ein Browser
    raeumt ``..`` vor dem Senden weg, deshalb faellt es beim Bedienen nie auf.

    ⚠️ **Der Rechte-Waechter sieht diesen Weg nicht.**
    ``test_waechter.py`` filtert auf ``r.path.startswith("/api")``, und der
    Auffangweg faengt nicht mit ``/api`` an. Deshalb steht die Zusicherung hier.
    """
    from app.main import _datei_im_haus

    haus = tmp_path / "app" / "static"
    haus.mkdir(parents=True)
    (haus / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "secret.key").write_text("nicht-fuer-fremde", encoding="utf-8")

    # Was drinnen liegt, wird weiterhin ausgeliefert.
    assert _datei_im_haus(haus, "index.html") == (haus / "index.html").resolve()

    # ⚠️ Jede Schreibweise desselben Weges. Der umgekehrte
    # Schraegstrich gilt nur unter Windows als Trenner, schadet anderswo aber
    # nichts - dort ist er schlicht ein Zeichen im Dateinamen.
    RUECKWAERTS = chr(92)
    ausbrueche = [
        "../../data/secret.key",
        # ⚠️ Der umgekehrte Schraegstrich wird ausdruecklich gebaut, nicht
        # maskiert: Eine Maskierung mehr oder weniger faellt in einer
        # Zeichenkette niemandem auf, und der Test pruefte dann einen
        # Pfad, den es gar nicht gibt.
        RUECKWAERTS.join(['..', '..', 'data', 'secret.key']),
        "./../../data/secret.key",
        "../data/../../data/secret.key",
    ]
    for ausbruch in ausbrueche:
        assert _datei_im_haus(haus, ausbruch) is None, (
            "Dieser Pfad fuehrt aus dem statischen Verzeichnis heraus: " + ausbruch
        )

    # Und das Verzeichnis selbst ist keine Datei.
    assert _datei_im_haus(haus, "..") is None


def test_der_auffangweg_folgt_keiner_verknuepfung_nach_draussen(tmp_path):
    """Eine Verknuepfung ist derselbe Ausbruch, nur ohne ``..``.

    ``resolve()`` loest sie mit auf, deshalb greift dieselbe Pruefung. Ohne
    diesen Test waere nirgends festgehalten, dass sie es tut.
    """
    from app.main import _datei_im_haus

    haus = tmp_path / "static"
    haus.mkdir()
    geheim = tmp_path / "geheim.txt"
    geheim.write_text("nicht-fuer-fremde", encoding="utf-8")
    try:
        (haus / "abkuerzung.txt").symlink_to(geheim)
    except (OSError, NotImplementedError):
        pytest.skip("Dieses System laesst keine Verknuepfungen ohne Sonderrechte zu.")

    assert _datei_im_haus(haus, "abkuerzung.txt") is None


# --- Die Oberflaeche geht gepackt hinaus, die Schnittstelle nicht --------- #


def _grosse_antwort(pfad_gesehen: list[str]):
    """Ein winziger ASGI-Dienst, der genug Text fuer die Packung liefert."""

    async def dienst(scope, receive, send):
        # ⚠️ ``TestClient`` schickt zuerst einen ``lifespan``-Scope, und
        # der hat gar keinen Pfad. Wer das uebersieht, bekommt einen KeyError
        # und haelt ihn fuer einen Fehler der Middleware.
        if scope["type"] == "lifespan":
            nachricht = await receive()
            while True:
                if nachricht["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif nachricht["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
                nachricht = await receive()

        pfad_gesehen.append(scope["path"])
        rumpf = ("nexmail " * 500).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": rumpf})

    return dienst


def test_die_oberflaeche_geht_gepackt_hinaus():
    """⚠️ **Ohne Reverse Proxy packt sonst niemand.**

    Gemessen am 03.09.2026: Der Einstieg wiegt 1.134.849 Byte roh und 342.188
    gepackt, also 70 Prozent weniger. Die mitgelieferte ``docker-compose.yml``
    stellt keinen Proxy davor, und der Server selbst packte nichts - bei einer
    Erstinstallation ging die ganze Oberflaeche ungepackt ueber die Leitung.
    """
    gesehen: list[str] = []
    mit = OberflaechePackenMiddleware(_grosse_antwort(gesehen))
    with TestClient(mit) as klient:
        antwort = klient.get("/einstellungen", headers={"Accept-Encoding": "gzip"})

    assert antwort.status_code == 200
    assert antwort.headers.get("content-encoding") == "gzip", (
        "Die Oberflaeche geht ungepackt hinaus."
    )
    assert gesehen == ["/einstellungen"]


def test_die_schnittstelle_bleibt_ungepackt():
    """⚠️ **Und das ist Absicht, kein Versehen.**

    Gepackte Antworten sind die Voraussetzung fuer BREACH: Wer eine Eingabe
    steuert, die zusammen mit einem Geheimnis in derselben Antwort landet,
    liest es an der Laenge ab. Bei einem Mailclient steuert ein Fremder die
    Eingabe muehelos - er schickt eine Mail mit dem Betreff seiner Wahl.
    Der Gewinn waere ohnehin klein: eine Listenantwort sind gemessen 36 kB.
    """
    gesehen: list[str] = []
    mit = OberflaechePackenMiddleware(_grosse_antwort(gesehen))
    with TestClient(mit) as klient:
        antwort = klient.get("/api/nachrichten", headers={"Accept-Encoding": "gzip"})

    assert antwort.status_code == 200
    assert "content-encoding" not in {k.lower() for k in antwort.headers}, (
        "Eine API-Antwort kam gepackt zurueck."
    )


def test_unter_einem_vorbau_bleibt_die_schnittstelle_ungepackt():
    """⚠️ **Die Reihenfolge der Middleware entscheidet das.**

    ``BasisPfadMiddleware`` haengt weiter aussen und streift den Vorbau ab,
    bevor die Packung den Pfad sieht. Waere es andersherum, hiesse der Pfad
    hier ``/nexmail/api/...``, die Ausnahme fuer ``/api`` traefe nicht, und
    unter einem Unterpfad waere die Schnittstelle doch gepackt - ein
    Unterschied, den man nur bei genau dieser Installation faende.
    """
    gesehen: list[str] = []
    innen = OberflaechePackenMiddleware(_grosse_antwort(gesehen))
    aussen = BasisPfadMiddleware(innen, VORBAU)
    with TestClient(aussen) as klient:
        antwort = klient.get(f"{VORBAU}/api/nachrichten", headers={"Accept-Encoding": "gzip"})

    assert antwort.status_code == 200
    assert gesehen == ["/api/nachrichten"], (
        "Der Vorbau war noch dran, als die Packung entschieden hat."
    )
    assert "content-encoding" not in {k.lower() for k in antwort.headers}
