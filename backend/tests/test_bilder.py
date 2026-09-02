"""Das Bilder-Paket: Vermittler, signierte Adresse, Absender-Freigaben.

⚠️ **Warum es diese Datei überhaupt gibt.** Der Knopf „Bilder anzeigen" hat
von 0.1.0 bis 0.3.0 sichtbar nichts getan, und **kein einziger Test hat es
gezeigt** — weil alle prüften, dass die Adresse wieder im ``src`` steht. Genau
das war der Fehler: Der Lesebereich erbt ``img-src 'self' data: blob:``, und
der Browser verwarf jede fremde Adresse. Stumm, ohne Konsolenmeldung, weil aus
einem abgeschotteten Rahmen keine Verstoßmeldung herauskommt.

Die Lehre steht in jedem Test hier: Geprüft wird, was **beim Browser ankommt**,
nicht was der Server sich dabei gedacht hat.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.models import Anhang, Benutzer, Nachricht, Ordner
from app.services import anbieter, bildfreigaben, bildvermittler, konten
from conftest import einrichten
from test_konten import _eingabe, _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="": _guter_befund())
    yield


def _mail_anlegen(
    klient,
    html: str,
    von: str = "werbung@beispiel.example",
    cid_anhang: str = "",
    postfach: str = "leser@beispiel.example",
    anhang_mime: str = "image/png",
    anhang_name: str = "logo.png",
) -> int:
    """Eine Mail mit geholtem Körper — sonst ginge die Route ins IMAP."""
    antwort = klient.post("/api/konten", json=_eingabe(postfach))
    assert antwort.status_code < 300, antwort.text
    konto_id = antwort.json()["id"]
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        nachricht = Nachricht(
            benutzer_id=posteingang.konto.benutzer_id,
            konto_id=konto_id,
            ordner_id=posteingang.id,
            uid=1,
            betreff="Newsletter",
            von_name="Werbung",
            von_adresse=von,
            datum=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
            koerper_html=html,
            koerper_text="",
            koerper_geholt=datetime.now(timezone.utc),
            geblockte_bilder=1,
        )
        db.add(nachricht)
        db.flush()
        if cid_anhang:
            # Ein echter Blob muss dafür auf der Platte liegen — ohne ihn
            # überspringt ``_inline_quellen`` den Anhang, und der Test wäre
            # gegen die Regel blind, die er prüfen soll.
            ordner = get_settings().blob_dir
            ordner.mkdir(parents=True, exist_ok=True)
            (ordner / "abc123").write_bytes(b"PNG!")
            db.add(
                Anhang(
                    nachricht_id=nachricht.id,
                    dateiname=anhang_name,
                    mime=anhang_mime,
                    groesse=4,
                    cid=cid_anhang,
                    blob_hash="abc123",
                )
            )
        db.commit()
        return nachricht.id


# --- Die signierte Adresse ----------------------------------------------- #


def test_die_marke_traegt_die_adresse_zurueck():
    marke = bildvermittler.marke_ausstellen("https://absender.example/pixel.gif?a=1&b=2")
    assert bildvermittler.marke_pruefen(marke) == "https://absender.example/pixel.gif?a=1&b=2"


def test_eine_gefaelschte_marke_kommt_nicht_durch():
    """⚠️ Sonst wäre nexmail ein offener Vermittler für jede Adresse."""
    marke = bildvermittler.marke_ausstellen("https://absender.example/a.gif")
    koerper, _, _ = marke.rpartition(".")
    with pytest.raises(bildvermittler.Abgelehnt):
        bildvermittler.marke_pruefen(f"{koerper}.{'0' * 32}")


def test_eine_umgeschriebene_adresse_kommt_nicht_durch():
    """Der Körper ist Base64 und sieht harmlos aus — die Unterschrift nicht."""
    import base64

    gefaelscht = (
        base64.urlsafe_b64encode(b'{"u":"http://127.0.0.1:8010/api/konten","ab":9999999999}')
        .decode()
        .rstrip("=")
    )
    echt = bildvermittler.marke_ausstellen("https://absender.example/a.gif")
    _, _, unterschrift = echt.rpartition(".")
    with pytest.raises(bildvermittler.Abgelehnt):
        bildvermittler.marke_pruefen(f"{gefaelscht}.{unterschrift}")


def test_eine_alte_marke_gilt_nicht_mehr():
    alt = time.time() - bildvermittler.GUELTIG_SEKUNDEN - 1
    marke = bildvermittler.marke_ausstellen("https://absender.example/a.gif", jetzt=alt)
    with pytest.raises(bildvermittler.Abgelehnt):
        bildvermittler.marke_pruefen(marke)


# --- Wohin nexmail nicht greifen darf ------------------------------------ #


@pytest.mark.parametrize(
    "adresse",
    [
        "http://127.0.0.1/geraet",
        "http://localhost:8010/api/konten",
        "http://172.16.5.4/reboot",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        # ⚠️ **Hier steht mit Absicht keine 192.168-Adresse.**
        # ``test_veroeffentlichung.py`` verbietet sie im Repo, und das zu Recht
        # — sie ginge als Rechner aus dem Heimnetz durch. Geprueft wird
        # ohnehin derselbe Zweig (``is_private``), 172.16 und 10.x tun es
        # genauso.
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        # ⚠️ Die auf IPv4 abgebildete Schreibweise ist derselbe Rechner.
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
    ],
)
def test_das_eigene_netz_bleibt_zu(adresse):
    """⚠️ Sonst wäre der Vermittler eine Fernbedienung fürs Heimnetz.

    Eine Mail mit ``<img src="http://192.168.x.x/…">`` löste beim Klick auf
    „Bilder anzeigen" einen Abruf dorthin aus — nexmail steht im selben Netz,
    der Absender nicht.
    """
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.adresse_pruefen(adresse)
    assert fehler.value.kennung == "bild_adresse_im_eigenen_netz"


@pytest.mark.parametrize("adresse", ["file:///etc/passwd", "gopher://x/", "javascript:1"])
def test_nur_http_und_https(adresse):
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.adresse_pruefen(adresse)
    assert fehler.value.kennung == "bild_adresse_unerlaubt"


def test_ein_name_der_ins_eigene_netz_zeigt_wird_abgewiesen(monkeypatch):
    """⚠️ Ein Name ist keine Adresse — geprüft wird, worauf er zeigt.

    Sonst genügte ein eigener DNS-Eintrag auf ``192.168.x.x``, und die
    Prüfung oben wäre eine Zierde.
    """
    monkeypatch.setattr(
        bildvermittler.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("172.16.5.4", 80))],
    )
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.adresse_pruefen("http://harmlos.example/bild.png")
    assert fehler.value.kennung == "bild_adresse_im_eigenen_netz"


def test_alle_antworten_des_namensdienstes_zaehlen(monkeypatch):
    """⚠️ Nicht nur die erste. Ein Name darf auf mehrere Adressen zeigen."""
    monkeypatch.setattr(
        bildvermittler.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 80)),
            (2, 1, 6, "", ("10.1.2.3", 80)),
        ],
    )
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.adresse_pruefen("http://zweideutig.example/bild.png")
    assert fehler.value.kennung == "bild_adresse_im_eigenen_netz"


# --- Der Abruf ------------------------------------------------------------ #


def _mit_antwort(monkeypatch, antworten):
    """httpx durch eine Attrappe ersetzen, die vorgegebene Antworten liefert.

    ⚠️ **Und ``adresse_pruefen`` bleibt echt.** Wer sie mit wegmockt, prüft
    eine Behauptung statt einer Regel — genau so entsteht ein Test, der grün
    bleibt, während das Loch aufgeht.
    """
    monkeypatch.setattr(
        bildvermittler.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))]
    )
    verlauf: list[str] = []

    class Attrappe:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, methode, url):  # noqa: ARG002
            verlauf.append(url)
            return antworten.pop(0)

    monkeypatch.setattr(bildvermittler.httpx, "Client", Attrappe)
    return verlauf


class Antwort:
    def __init__(self, status=200, typ="image/png", inhalt=b"x", ort=""):
        self.status_code = status
        self.headers = {"content-type": typ}
        if ort:
            self.headers["location"] = ort
        self.is_redirect = 300 <= status < 400
        self._inhalt = inhalt

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        yield self._inhalt


def test_ein_bild_kommt_zurueck(monkeypatch):
    _mit_antwort(monkeypatch, [Antwort(inhalt=b"PNG")])
    inhalt, typ = bildvermittler.holen("https://absender.example/a.png")
    assert inhalt == b"PNG"
    assert typ == "image/png"


def test_was_kein_bild_ist_kommt_nicht_durch(monkeypatch):
    _mit_antwort(monkeypatch, [Antwort(typ="text/html")])
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.holen("https://absender.example/a.png")
    assert fehler.value.kennung == "bild_kein_bild"


def test_svg_bleibt_draussen(monkeypatch):
    _mit_antwort(monkeypatch, [Antwort(typ="image/svg+xml")])
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.holen("https://absender.example/a.svg")
    assert fehler.value.kennung == "bild_kein_bild"


def test_zu_gross_bricht_beim_lesen_ab(monkeypatch):
    """⚠️ Während des Lesens, nicht danach — ``content-length`` ist eine
    Behauptung des fremden Servers."""
    _mit_antwort(monkeypatch, [Antwort(inhalt=b"x" * (bildvermittler.MAX_BYTES + 1))])
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.holen("https://absender.example/riesig.png")
    assert fehler.value.kennung == "bild_zu_gross"


def test_jeder_sprung_wird_neu_geprueft(monkeypatch):
    """⚠️ Sonst wäre die Prüfung des ersten Sprungs eine Zierde.

    Zähl-Adressen leiten fast immer weiter; eine Weiterleitung ins eigene Netz
    wäre der bequemste Weg an der Regel vorbei.
    """
    monkeypatch.setattr(
        bildvermittler.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))]
    )

    class Attrappe:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, methode, url):  # noqa: ARG002
            return Antwort(status=302, ort="http://172.16.5.4/reboot")

    monkeypatch.setattr(bildvermittler.httpx, "Client", Attrappe)
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.holen("https://absender.example/zaehler.gif")
    assert fehler.value.kennung == "bild_adresse_im_eigenen_netz"


def test_ein_netzfehler_ist_kein_absturz(monkeypatch):
    monkeypatch.setattr(
        bildvermittler.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))]
    )

    class Attrappe:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, methode, url):  # noqa: ARG002
            raise httpx.ConnectTimeout("weg")

    monkeypatch.setattr(bildvermittler.httpx, "Client", Attrappe)
    with pytest.raises(bildvermittler.Abgelehnt) as fehler:
        bildvermittler.holen("https://absender.example/a.png")
    assert fehler.value.kennung == "bild_nicht_erreichbar"


# --- Der ganze Weg durch die Anwendung ----------------------------------- #


def test_der_knopf_liefert_keine_fremde_adresse_mehr(klient, ohne_netz):
    """⚠️ **Der Test, den es drei Fassungen lang nicht gab.**

    Vorher stand hier die echte Adresse im ``src`` — und genau die verwirft der
    Browser im abgeschotteten Lesebereich.
    """
    einrichten(klient)
    kennung = _mail_anlegen(
        klient, '<img data-nexmail-src="https://absender.example/pixel.gif">'
    )

    antwort = klient.post(f"/api/nachrichten/{kennung}/bilder", json={})
    assert antwort.status_code == 200, antwort.text
    html = antwort.json()["html"]
    assert "absender.example" not in html
    assert "/api/bilder/" in html
    assert "data-nexmail-src" not in html


def test_die_marke_aus_der_antwort_holt_genau_dieses_bild(klient, ohne_netz):
    """Die Adresse in der Antwort muss wirklich zu diesem Bild führen."""
    einrichten(klient)
    kennung = _mail_anlegen(
        klient, '<img data-nexmail-src="https://absender.example/p.gif?a=1&amp;b=2">'
    )
    html = klient.post(f"/api/nachrichten/{kennung}/bilder", json={}).json()["html"]
    marke = html.split("/api/bilder/")[1].split('"')[0]
    # ⚠️ Das ``&amp;`` aus dem Attribut muss zurückverwandelt sein — sonst
    # holte nexmail eine Adresse, die es nie gab.
    assert bildvermittler.marke_pruefen(marke) == "https://absender.example/p.gif?a=1&b=2"


def test_bilder_anzeigen_verliert_die_eingebetteten_nicht(klient, ohne_netz):
    """⚠️ **Der zweite Fehler, gefunden am 02.09.2026.**

    ``POST /{id}/bilder`` gab den Rohtext zurück, ohne ``cid_einsetzen``. Wer
    den Knopf drückte, verlor damit ausgerechnet Logo und Bildschirmfotos
    derselben Mail — die nie geblockt waren.
    """
    einrichten(klient)
    kennung = _mail_anlegen(
        klient,
        '<img src="cid:logo1"><img data-nexmail-src="https://absender.example/p.gif">',
        cid_anhang="logo1",
    )
    html = klient.post(f"/api/nachrichten/{kennung}/bilder", json={}).json()["html"]
    assert "cid:logo1" not in html
    assert 'src=""' not in html


def test_ein_freigegebener_absender_braucht_keinen_klick(klient, ohne_netz):
    einrichten(klient)
    kennung = _mail_anlegen(klient, '<img data-nexmail-src="https://absender.example/p.gif">')

    klient.post(f"/api/nachrichten/{kennung}/bilder", json={"absender_merken": True})

    voll = klient.get(f"/api/nachrichten/{kennung}").json()
    assert voll["geblockte_bilder"] == 0
    assert voll["absender_freigegeben"] is True
    assert "/api/bilder/" in voll["html"]


def test_ohne_freigabe_bleiben_die_bilder_ausgeklinkt(klient, ohne_netz):
    einrichten(klient)
    kennung = _mail_anlegen(klient, '<img data-nexmail-src="https://absender.example/p.gif">')

    voll = klient.get(f"/api/nachrichten/{kennung}").json()
    assert voll["geblockte_bilder"] == 1
    assert voll["absender_freigegeben"] is False
    assert "/api/bilder/" not in voll["html"]
    # ⚠️ Die Adresse steht noch da — aber ausgeklinkt, nicht in einem ``src``.
    assert "data-nexmail-src" in voll["html"]
    assert " src=" not in voll["html"]


def test_der_globale_schalter_gilt_fuer_alle(klient, ohne_netz):
    einrichten(klient)
    kennung = _mail_anlegen(klient, '<img data-nexmail-src="https://absender.example/p.gif">')

    klient.put("/api/einstellungen/bilder", json={"immer_laden": True})

    voll = klient.get(f"/api/nachrichten/{kennung}").json()
    assert voll["geblockte_bilder"] == 0
    assert "/api/bilder/" in voll["html"]


def test_gross_und_kleinschreibung_trennt_keine_absender(klient, ohne_netz):
    """Wer „Post@…" freigibt und bei „post@…" wieder gefragt wird, hält die
    Einstellung für kaputt."""
    einrichten(klient)
    kennung = _mail_anlegen(
        klient,
        '<img data-nexmail-src="https://absender.example/p.gif">',
        von="Werbung@Beispiel.Example",
    )
    klient.post(f"/api/nachrichten/{kennung}/bilder", json={"absender_merken": True})

    # ⚠️ **Beide Richtungen.** Nur eine zu prüfen ließ die erste
    # Mutationsprobe durchgehen: Wird beim Merken klein geschrieben, trifft
    # eine kleine Adresse auch ohne Angleichung beim Lesen.
    zweite = _mail_anlegen(
        klient,
        '<img data-nexmail-src="https://absender.example/q.gif">',
        von="werbung@beispiel.example",
        postfach="zweites@beispiel.example",
    )
    assert klient.get(f"/api/nachrichten/{zweite}").json()["geblockte_bilder"] == 0

    dritte = _mail_anlegen(
        klient,
        '<img data-nexmail-src="https://absender.example/r.gif">',
        von="WERBUNG@BEISPIEL.EXAMPLE",
        postfach="drittes@beispiel.example",
    )
    assert klient.get(f"/api/nachrichten/{dritte}").json()["geblockte_bilder"] == 0


def test_die_freigabe_laesst_sich_zuruecknehmen(klient, ohne_netz):
    einrichten(klient)
    kennung = _mail_anlegen(klient, '<img data-nexmail-src="https://absender.example/p.gif">')
    klient.post(f"/api/nachrichten/{kennung}/bilder", json={"absender_merken": True})

    stand = klient.get("/api/einstellungen/bilder").json()
    assert stand["absender"] == ["werbung@beispiel.example"]

    danach = klient.post(
        "/api/einstellungen/bilder/absender/entfernen",
        json={"adresse": "werbung@beispiel.example"},
    ).json()
    assert danach["absender"] == []
    assert klient.get(f"/api/nachrichten/{kennung}").json()["geblockte_bilder"] == 1


def test_zweimal_zuruecknehmen_ist_kein_fehler(klient, ohne_netz):
    """Ein Verklicken, kein Irrtum — dieselbe Haltung wie bei „zu Aufgabe
    machen"."""
    einrichten(klient)
    antwort = klient.post(
        "/api/einstellungen/bilder/absender/entfernen", json={"adresse": "gibtsnicht@example.com"}
    )
    assert antwort.status_code == 200


def test_freigaben_sind_personenbezogen(klient, db):
    """⚠️ Die Freigabe des einen darf die Post des anderen nicht öffnen."""
    einrichten(klient)
    einer = db.query(Benutzer).filter(Benutzer.benutzername == "betreiber").one()
    anderer = Benutzer(benutzername="zweiter", passwort_hash="x")
    db.add(anderer)
    db.commit()

    bildfreigaben.merken(db, einer, "werbung@beispiel.example")
    assert bildfreigaben.darf_laden(db, einer, "werbung@beispiel.example") is True
    assert bildfreigaben.darf_laden(db, anderer, "werbung@beispiel.example") is False


def test_die_vermittler_adresse_weist_muell_ab(klient):
    einrichten(klient)
    assert klient.get("/api/bilder/kaputt").status_code == 404


def test_die_vermittler_adresse_braucht_keine_anmeldung(klient, monkeypatch):
    """⚠️ **Sie kann es nicht** — der Abruf kommt aus dem abgeschotteten
    Rahmen und bringt kein Sitzungs-Cookie mit (02.09.2026 im echten Browser
    gemessen). Der Ausweis ist die Unterschrift.

    Geprüft wird deshalb, dass eine **gültige** Marke ohne Anmeldung trägt —
    und nicht etwa an einem 401 hängen bleibt.
    """
    einrichten(klient)
    klient.cookies.clear()
    _mit_antwort(monkeypatch, [Antwort(inhalt=b"PNG")])
    marke = bildvermittler.marke_ausstellen("https://absender.example/a.png")

    antwort = klient.get(f"/api/bilder/{marke}")
    assert antwort.status_code == 200, antwort.text
    assert antwort.content == b"PNG"
    assert antwort.headers["content-type"].startswith("image/png")


def test_die_adresse_aus_der_antwort_liefert_wirklich_ein_bild(klient, ohne_netz, monkeypatch):
    """⚠️ **Die beiden Hälften treffen sich hier — und nur hier.**

    Jede für sich war schon vorher grün: Der Server baute eine Adresse, und die
    Vermittler-Route lieferte Bilder. Ob die gebaute Adresse zu *dieser* Route
    führt, hat nichts geprüft — und genau so eine Lücke war der ursprüngliche
    Fehler.

    Gegenprobe im echten Chromium am 02.09.2026: Ein ``sandbox=""``-Rahmen mit
    ``srcdoc`` ruft eine Adresse der eigenen Herkunft tatsächlich ab, ``'self'``
    greift dort. Was hier fehlt, ist also nur noch das Bild selbst.
    """
    einrichten(klient)
    kennung = _mail_anlegen(klient, '<img data-nexmail-src="https://absender.example/p.gif">')
    html = klient.post(f"/api/nachrichten/{kennung}/bilder", json={}).json()["html"]

    adresse = html.split('src="')[1].split('"')[0]
    # ⚠️ Wurzelbezogen, mit Vorbau — im ``srcdoc``-Rahmen löst sich eine
    # relative Adresse gegen das Elterndokument auf.
    assert adresse.startswith("/api/bilder/")

    _mit_antwort(monkeypatch, [Antwort(inhalt=b"GIF89a")])
    antwort = klient.get(adresse)
    assert antwort.status_code == 200, antwort.text
    assert antwort.content == b"GIF89a"


def test_ein_schlampig_deklariertes_logo_wird_trotzdem_eingebettet(klient, ohne_netz):
    """⚠️ **Geschaeftsmails haengen ihr Logo gern als ``application/octet-stream`` an.**

    Wer nur dem deklarierten Typ glaubt, laesst es weg — und im Lesebereich
    klafft eine Luecke, die nach einem Fehler beim Laden aussieht. Am
    02.09.2026 an zwei echten Mails gemeldet. Geraten wird nur aus der Endung.
    """
    einrichten(klient)
    kennung = _mail_anlegen(
        klient,
        '<img src="cid:logo1" alt="Logo">',
        cid_anhang="logo1",
        anhang_mime="application/octet-stream",
        anhang_name="logo.png",
    )
    html = klient.get(f"/api/nachrichten/{kennung}").json()["html"]
    assert "data:image/png;base64," in html
    assert "cid:logo1" not in html


def test_was_kein_bild_ist_wird_nicht_eingebettet(klient, ohne_netz):
    """Und das Bild verliert sein ``src``, statt als Bruchsymbol dazustehen."""
    einrichten(klient)
    kennung = _mail_anlegen(
        klient,
        '<img src="cid:datei1" alt="Vertrag">',
        cid_anhang="datei1",
        anhang_mime="application/pdf",
        anhang_name="vertrag.pdf",
    )
    html = klient.get(f"/api/nachrichten/{kennung}").json()["html"]
    assert "data:" not in html
    assert 'src=""' not in html
    assert "cid:datei1" not in html
    assert 'alt="Vertrag"' in html

