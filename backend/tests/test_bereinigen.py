"""HTML aus fremden Mails entschärfen.

⚠️ **Dieser Block ist nicht optional.** Eine Mail ist fremder Code von einem
Unbekannten. Jeder Test hier steht für einen Weg, auf dem dieser Code sonst
etwas anrichten könnte — und jeder wird in beide Richtungen geprüft: beim
Anzeigen fremder Mails und beim Senden eigener.
"""

from __future__ import annotations

import pytest

from app.services import bereinigen

BOESE = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<a href=\"javascript:alert(1)\">klick</a>",
    "<iframe src=\"https://boese.example\"></iframe>",
    "<object data=\"boese.swf\"></object>",
    "<embed src=\"boese.swf\">",
    "<form action=\"https://boese.example\"><input name=p></form>",
    "<div onmouseover=\"alert(1)\">text</div>",
    "<svg onload=alert(1)>",
    "<a href=\"data:text/html,<script>alert(1)</script>\">klick</a>",
    "<style>body{background:url('https://boese.example/z.png')}</style>",
    "<base href=\"https://boese.example/\">",
    "<meta http-equiv=refresh content=\"0;url=https://boese.example\">",
    "<link rel=stylesheet href=\"https://boese.example/x.css\">",
]


@pytest.mark.parametrize("roh", BOESE)
def test_nichts_davon_bleibt_uebrig(roh):
    sauber = bereinigen.saeubern(roh)
    tief = sauber.lower()

    assert "<script" not in tief
    assert "<iframe" not in tief
    assert "<object" not in tief
    assert "<embed" not in tief
    assert "<form" not in tief
    assert "<style" not in tief
    assert "<base" not in tief
    assert "<meta" not in tief
    assert "<link" not in tief
    assert "onerror" not in tief
    assert "onload" not in tief
    assert "onmouseover" not in tief
    assert "javascript:" not in tief
    assert "data:text/html" not in tief


@pytest.mark.parametrize("roh", BOESE)
def test_dasselbe_gilt_beim_senden(roh):
    """⚠️ In beide Richtungen.

    Ein weitergeleiteter Newsletter trägt fremdes HTML in den eigenen
    Entwurf — dass es aus dem eigenen Fenster kommt, macht es nicht harmlos.
    """
    sauber = bereinigen.fuer_versand(roh).lower()
    assert "<script" not in sauber
    assert "onerror" not in sauber
    assert "javascript:" not in sauber


def test_gewoehnliche_mail_bleibt_lesbar():
    """Entschärfen heißt nicht kaputtmachen."""
    roh = (
        '<p>Guten Tag <b>Frau Beispiel</b>,</p>'
        '<p>wir kündigen die <i>Wartung</i> an. Mehr unter '
        '<a href="https://example.org/info">example.org</a>.</p>'
        '<table><tr><td>Termin</td><td>12. September</td></tr></table>'
        '<ul><li>Eins</li><li>Zwei</li></ul>'
    )
    sauber = bereinigen.saeubern(roh)
    assert "<b>Frau Beispiel</b>" in sauber
    assert "<table>" in sauber
    assert "<li>Eins</li>" in sauber
    assert "https://example.org/info" in sauber


def test_verweise_bekommen_noopener():
    """Ohne rel kann die geöffnete Seite auf das Fenster zurückgreifen."""
    sauber = bereinigen.saeubern('<a href="https://example.org">x</a>')
    assert "noopener" in sauber


# --- Bilder -------------------------------------------------------------- #


def test_zaehlpixel_wird_ausgeklinkt():
    """⚠️ Der eigentliche Zweck.

    Ein Zählpixel meldet dem Absender, dass und wann seine Mail geöffnet
    wurde. Der Browser darf die Adresse nicht einmal sehen.
    """
    roh = (
        '<p>Werbung</p>'
        '<img src="https://absender.example/bild.jpg" alt="Ware">'
        '<img src="https://absender.example/zaehl/8f3a.gif" width="1" height="1" alt="">'
    )
    html, anzahl = bereinigen.fuer_anzeige(roh)

    assert anzahl == 2
    assert "src=" not in html.replace(bereinigen.BILD_MERKMAL + "=", "")
    assert html.count(bereinigen.BILD_MERKMAL) == 2
    # Die Adresse steht noch da - aber als Wert eines Attributs, das der
    # Browser nicht anfasst.
    assert "absender.example" in html


def test_verstecktes_bild_wird_genauso_ausgeklinkt():
    """⚠️ „display:none" hilft nicht — geladen wird es trotzdem."""
    roh = '<img src="https://absender.example/z.gif" style="display:none">'
    html, anzahl = bereinigen.fuer_anzeige(roh)
    assert anzahl == 1
    assert " src=" not in html


def test_bilder_kommen_auf_wunsch_zurueck():
    """Und zwar über den Vermittler, nicht als fremde Adresse.

    ⚠️ **Genau das war der Fehler von 0.1.0 bis 0.3.0.** Die echte Adresse
    wieder einzuhängen sieht richtig aus und ist es nicht: Der Lesebereich
    erbt ``img-src 'self' data: blob:``, und der Browser verwirft ``https``
    stumm.
    """
    roh = '<img src="https://absender.example/bild.jpg">'
    html, _ = bereinigen.fuer_anzeige(roh)
    assert " src=" not in html

    wieder = bereinigen.bilder_vermitteln(html, lambda _: "/api/bilder/MARKE")
    assert 'src="/api/bilder/MARKE"' in wieder
    assert bereinigen.BILD_MERKMAL not in wieder
    # ⚠️ Die fremde Adresse steht danach nirgends mehr im Dokument — sonst
    # hätte der Browser sie wieder in der Hand.
    assert "absender.example" not in wieder


def test_der_vermittler_bekommt_die_unmaskierte_adresse():
    """⚠️ nh3 macht aus ``&`` im Attribut ein ``&amp;``.

    Wer das nicht zurücknimmt, signiert und holt eine Adresse, die es nie
    gab — und Zähl-Adressen mit mehreren Parametern sind der Normalfall.
    """
    roh = '<img src="https://absender.example/p.gif?a=1&b=2&c=3">'
    html, _ = bereinigen.fuer_anzeige(roh)
    gesehen: list[str] = []
    bereinigen.bilder_vermitteln(html, lambda u: gesehen.append(u) or "/x")
    assert gesehen == ["https://absender.example/p.gif?a=1&b=2&c=3"]


def test_grossgeschriebenes_img_wird_auch_erwischt():
    """Mail-HTML ist selten sauber geschrieben."""
    html, anzahl = bereinigen.fuer_anzeige('<IMG SRC="https://x.example/z.gif">')
    assert anzahl == 1
    assert " src=" not in html.lower().replace(bereinigen.BILD_MERKMAL.lower() + "=", "")


def test_reihenfolge_saeubern_dann_ausklinken():
    """⚠️ Erst säubern, dann ausklinken.

    Umgekehrt wäre ein ``<img onerror=…>`` schon entschärft worden, aber ein
    ``<script>``, das ein Bild nachlädt, hätte die Umschreibung überlebt.
    """
    html, anzahl = bereinigen.fuer_anzeige(
        '<script>document.write(\'<img src="https://boese.example/z.gif">\')</script>'
        '<img src="https://echt.example/b.jpg">'
    )
    assert "<script" not in html.lower()
    assert anzahl == 1
    assert "boese.example" not in html


# --- Anreißer ------------------------------------------------------------ #


def test_anreisser_ohne_zitat():
    """Zitatzeilen sagen nichts Neues und fressen die Vorschau auf."""
    text = "Passt bei mir.\n\n> Am 1.9. schrieb Anja:\n> Wollen wir um elf?"
    assert bereinigen.anreisser(text).startswith("Passt bei mir.")
    assert "Wollen wir um elf" not in bereinigen.anreisser(text)


def test_anreisser_aus_html():
    roh = "<p>Guten Tag,</p><p>die <b>Rechnung</b> liegt bei.</p>"
    assert bereinigen.text_aus_html(roh) == "Guten Tag, die Rechnung liegt bei."


def test_anreisser_loest_entitaeten_auf():
    assert "&" in bereinigen.text_aus_html("<p>Meier &amp; S&ouml;hne</p>".replace("&ouml;", "ö"))
    assert "&amp;" not in bereinigen.text_aus_html("<p>Meier &amp; Söhne</p>")


def test_leeres_bleibt_leer():
    assert bereinigen.saeubern("") == ""
    assert bereinigen.text_aus_html("") == ""
    assert bereinigen.anreisser("") == ""


# --- Eingebettete Bilder --------------------------------------------------- #


def test_ein_cid_bild_wird_nicht_ausgeklinkt():
    """⚠️ **Aus Schaden entstanden, 31.08.2026.**

    Ein ``cid:``-Bild zeigt auf einen Teil **derselben Mail**. Es kann
    niemanden anfunken, weil es gar nicht ins Netz geht — anders als ein
    Zählpixel. Ausgeklinkt sah jede Mail mit eingebettetem Logo kaputt aus,
    und zwar dauerhaft: Auch nach „Bilder anzeigen" löst kein Browser ``cid:``
    auf.
    """
    html = '<img src="cid:logo123"><img src="https://spion.example/p.gif">'

    aus, anzahl = bereinigen.bilder_ausklinken(html)

    assert anzahl == 1, "Nur das Fremdbild darf ausgeklinkt werden."
    assert 'src="cid:logo123"' in aus
    assert "data-nexmail-src=\"https://spion.example/p.gif\"" in aus


def test_cid_wird_durch_eine_anzeigbare_adresse_ersetzt():
    aus = bereinigen.cid_einsetzen(
        '<img src="cid:logo123">', {"logo123": "data:image/png;base64,AAAA"}
    )
    assert aus == '<img src="data:image/png;base64,AAAA">'


def test_ein_unbekanntes_cid_bleibt_nicht_stehen():
    """Ein ``cid:``, das im Browser ankommt, ist ein kaputtes Bildsymbol."""
    aus = bereinigen.cid_einsetzen('<img src="cid:gibtesnicht">', {})
    assert "cid:" not in aus


def test_einfache_anfuehrungszeichen_und_ohne():
    quellen = {"a": "data:image/png;base64,X"}
    assert "cid:" not in bereinigen.cid_einsetzen("<img src='cid:a'>", quellen)
    assert "cid:" not in bereinigen.cid_einsetzen("<img src=cid:a>", quellen)


def test_ein_zaehlpixel_bleibt_ausgeklinkt_auch_neben_einem_cid_bild():
    """Die Ausnahme für ``cid:`` darf nicht auf den Nachbarn abfärben."""
    html = '<img src="cid:logo"><img src="http://spion.example/1px.gif" width="1">'

    aus, anzahl = bereinigen.bilder_ausklinken(html)

    assert anzahl == 1
    assert 'src="cid:logo"' in aus
    assert 'data-nexmail-src="http://spion.example/1px.gif"' in aus
    # Kein echtes ``src=`` mehr, das ins Netz zeigt. Das führende Leerzeichen
    # ist nötig: ``data-nexmail-src="http…`` endet selbst auf ``src="http``.
    assert ' src="http' not in aus
