"""HTML aus fremden Mails entschärfen.

⚠️ **Eine Mail ist fremder Code, den ein Unbekannter geschickt hat.** Das ist
die gefährlichste Fläche der ganzen Anwendung, und sie wird an drei Stellen
verteidigt — hier ist die erste:

1. **Hier**, im Server: ``nh3`` mit Positivliste. Weg sind ``script``,
   ``style``, ``iframe``, ``object``, ``form``, alle ``on*``-Attribute und
   ``javascript:``-Verweise.
2. **Bilder**: Jedes ``src`` wird zu ``data-nexmail-src``. Der Browser darf die
   Adresse gar nicht erst anfassen — sonst hat der Absender seine Bestätigung
   schon, dass und wann gelesen wurde.
3. **Im Browser**: Anzeige in ``<iframe sandbox>`` ohne ``allow-scripts``.

⚠️ **Bereinigt wird in beide Richtungen.** Beim Anzeigen fremder Mails *und*
beim Senden eigener. Der Editor erzeugt HTML, und was von dort kommt, ist
nicht deshalb harmlos, weil es aus dem eigenen Haus stammt — eine
weitergeleitete Mail trägt fremdes HTML in den eigenen Entwurf.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from html import unescape

import nh3

logger = logging.getLogger("nexmail.bereinigen")

#: Was eine Mail an Struktur haben darf. Bewusst knapp: Alles, was hier fehlt,
#: kann eine Mail nicht kaputt machen, und was fehlt, sieht man sofort.
ERLAUBTE_ELEMENTE = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "col", "colgroup",
    "dd", "div", "dl", "dt", "em", "figcaption", "figure", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "q", "s",
    "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "u", "ul",
}

#: ⚠️ **Keine ``on*``-Attribute, kein ``style`` mit Ausbruch.** ``style`` bleibt
#: erlaubt, weil Mails ohne Inline-Stile unlesbar aussehen - nh3 filtert darin
#: nach eigener Liste und laesst ``expression()`` und ``url()`` nicht durch.
ERLAUBTE_ATTRIBUTE: dict[str, set[str]] = {
    "*": {"style", "title", "dir", "lang"},
    # ⚠️ Kein "rel" hier: nh3 setzt es selbst (siehe link_rel unten) und
    # lehnt es auf der Liste mit einem ValueError ab.
    "a": {"href", "name", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align", "valign"},
    "th": {"colspan", "rowspan", "align", "valign"},
    "table": {"width", "border", "cellpadding", "cellspacing", "align"},
    "col": {"span", "width"},
    "colgroup": {"span", "width"},
    "ol": {"start", "type"},
}

#: Nur diese Schemata. ``javascript:`` und ``data:`` fehlen mit Absicht -
#: ``data:`` waere ein Weg, ein ganzes Dokument in einen Verweis zu packen.
ERLAUBTE_SCHEMATA = {"http", "https", "mailto", "tel", "cid"}

#: Womit ein ausgeklinktes Bild wiederkommt.
BILD_MERKMAL = "data-nexmail-src"

_IMG_SRC = re.compile(r"(<img\b[^>]*?)\ssrc=", re.IGNORECASE)
#: Ein Bild mit ``src="cid:…"``. Die Kennung steht je nach Anführungszeichen
#: in Gruppe 2, 3 oder 4.
_IMG_CID = re.compile(
    r"""(<img\b[^>]*?\ssrc=)(?:"cid:([^"]*)"|'cid:([^']*)'|cid:([^\s>]*))""",
    re.IGNORECASE,
)
#: Ein ausgeklinktes Bild. Die Adresse steht je nach Anführungszeichen in
#: Gruppe 2, 3 oder 4 — dasselbe Muster wie bei ``_IMG_CID``.
_IMG_AUSGEKLINKT = re.compile(
    rf"""(<img\b[^>]*?\s){BILD_MERKMAL}=(?:"([^"]*)"|'([^']*)'|([^\s>]*))""",
    re.IGNORECASE,
)
_TAGS = re.compile(r"<[^>]+>")
_LEERRAUM = re.compile(r"\s+")


def saeubern(roh: str) -> str:
    """Fremdes HTML auf das Erlaubte zurückschneiden."""
    if not roh:
        return ""
    return nh3.clean(
        roh,
        tags=ERLAUBTE_ELEMENTE,
        attributes={schluessel: set(werte) for schluessel, werte in ERLAUBTE_ATTRIBUTE.items()},
        url_schemes=ERLAUBTE_SCHEMATA,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )


def bilder_ausklinken(html: str) -> tuple[str, int]:
    """Jedes ``src`` durch ``data-nexmail-src`` ersetzen.

    ⚠️ **Nicht verstecken, ausklinken.** Ein Bild mit ``display:none`` wird
    trotzdem geladen - und genau darum geht es: Ein Zählpixel meldet dem
    Absender, dass und wann seine Mail geöffnet wurde. Der Browser darf die
    Adresse nicht sehen.

    ⚠️ **``cid:`` bleibt hängen.** Ein solches Bild zeigt auf einen Teil
    **derselben Mail** - es kann niemanden anfunken, weil es gar nicht ins
    Netz geht. Wer es trotzdem ausklinkt, lässt jede Mail mit eingebettetem
    Logo oder Bildschirmfoto kaputt aussehen, bis jemand „Bilder anzeigen"
    drückt - und danach immer noch, weil ein Browser ``cid:`` nicht auflöst.
    Genau so war es bis zum 31.08.2026.

    Rückgabe: bereinigtes HTML und die Anzahl der ausgeklinkten Bilder.
    """
    anzahl = 0

    def tauschen(treffer: re.Match[str]) -> str:
        nonlocal anzahl
        # Steht direkt hinter dem src ein cid:, bleibt alles, wie es ist.
        rest = html[treffer.end() : treffer.end() + 12].lstrip("\"' ")
        if rest[:4].lower() == "cid:":
            return treffer.group(0)
        anzahl += 1
        return f"{treffer.group(1)} {BILD_MERKMAL}="

    return _IMG_SRC.sub(tauschen, html), anzahl


def cid_einsetzen(html: str, quellen: dict[str, str]) -> str:
    """``cid:xyz`` durch eine anzeigbare Adresse ersetzen.

    ⚠️ **Das muss ohne Netzzugriff gehen.** Der Lesebereich läuft in einem
    ``<iframe sandbox>`` ohne ``allow-same-origin`` - der Rahmen hat also eine
    fremde Herkunft, und eine Adresse wie ``/api/…`` bekäme von dort weder
    Sitzungskeks noch Antwort. Deshalb wird der Inhalt direkt beigelegt.

    ``quellen`` bildet die Kennung (ohne ``cid:``) auf die fertige Adresse ab.
    Was nicht darin steht, wird entfernt statt stehengelassen: Ein ``cid:``,
    das im Browser ankommt, ist ein kaputtes Bildsymbol.

    ⚠️ **Die Adresse wird maskiert, obwohl sie aus dem eigenen Haus kommt.**
    Dieser Tausch läuft **nach** der nh3-Bereinigung — was hier ins Attribut
    gelangt, prüft niemand mehr. Ein ``"`` in der Adresse bräche sonst aus dem
    ``src`` aus, und die zweite Verteidigungslinie wäre genau an der Stelle
    umgangen, für die sie gedacht ist.
    """

    def tauschen(treffer: re.Match[str]) -> str:
        kennung = treffer.group(2) or treffer.group(3) or treffer.group(4) or ""
        adresse = quellen.get(kennung.strip())
        if adresse is None:
            return f'{treffer.group(1)}""'
        sicher = (
            adresse.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        )
        return f'{treffer.group(1)}"{sicher}"'

    return _IMG_CID.sub(tauschen, html)


def bilder_vermitteln(html: str, adresse: Callable[[str], str]) -> str:
    """Die Umkehrung — erst wenn jemand „Bilder anzeigen" gedrückt hat.

    ⚠️ **Die fremde Adresse kommt nicht zurück ins ``src``.** Bis zum
    02.09.2026 stand hier ein schlichtes Zurücktauschen, und genau das war der
    Grund, warum der Knopf sichtbar nichts tat: Der Lesebereich läuft in einem
    ``<iframe sandbox>``, der die Inhaltsregel der Anwendung erbt, und dort
    steht ``img-src 'self' data: blob:``. Der Browser verwarf jede
    ``https``-Adresse — stumm, weil aus einem abgeschotteten Rahmen keine
    Verstossmeldung herauskommt.

    Stattdessen steht dort jetzt eine Adresse **dieser** Anwendung, hinter der
    der Bild-Vermittler sitzt. ``adresse`` baut sie aus der echten Adresse.

    ⚠️ **Die gespeicherte Adresse ist HTML-maskiert.** nh3 macht aus einem
    ``&`` im Attribut ein ``&amp;`` — wer das nicht zurücknimmt, signiert und
    holt eine Adresse, die es so nie gab. Bei Zähl-Adressen mit einem halben
    Dutzend Parametern ist das der Normalfall, nicht die Ausnahme.
    """

    def tauschen(treffer: re.Match[str]) -> str:
        roh = unescape(treffer.group(2) or treffer.group(3) or treffer.group(4) or "")
        if not roh.strip():
            return f'{treffer.group(1)}src=""'
        sicher = (
            adresse(roh.strip()).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        )
        return f'{treffer.group(1)}src="{sicher}"'

    return _IMG_AUSGEKLINKT.sub(tauschen, html)


def fuer_anzeige(roh_html: str) -> tuple[str, int]:
    """Der ganze Weg für den Lesebereich: säubern, dann Bilder ausklinken."""
    sauber = saeubern(roh_html)
    return bilder_ausklinken(sauber)


def fuer_druck(roh_html: str) -> str:
    """Für die Druckseite: säubern, Bilder ausklinken — und die ausgeklinkten
    Adressen ganz entfernen.

    ⚠️ **Anders als im Lesebereich gibt es hier kein „Bilder anzeigen".** Die
    ausgeklinkte Adresse hätte im Dokument keinen Zweck mehr, würde aber mit
    jeder abgelegten oder weitergereichten Kopie mitwandern. ``cid:``-Bilder
    bleiben — sie zeigen auf Teile derselben Mail und funken niemanden an.

    ⚠️ **Und es wird gesäubert, obwohl der Bestand bereinigt gespeichert
    ist.** Die Druckseite rendert unter nexmails eigener Herkunft, nicht im
    abgeschotteten Rahmen: Ein vergifteter Bestand — ältere Fassung, fremde
    Sicherung — darf hier nicht zu ausführbarem Code werden.
    """
    sauber, _ = fuer_anzeige(roh_html)
    # nh3 setzt Attribute stets in doppelte Anführungszeichen — der Rohfall
    # ohne Anführungszeichen kann nach dem Säubern nicht mehr vorkommen.
    return re.sub(rf'\s{BILD_MERKMAL}="[^"]*"', "", sauber)


def fuer_versand(roh_html: str) -> str:
    """Was der Editor erzeugt hat, bevor es hinausgeht.

    ⚠️ Dieselbe Bereinigung. Ein weitergeleiteter Newsletter trägt fremdes
    HTML in den eigenen Entwurf - dass es aus dem eigenen Fenster kommt, macht
    es nicht harmlos.
    """
    return saeubern(roh_html)


def text_aus_html(html: str, laenge: int = 200) -> str:
    """Ein Anreißer für die Liste, aus HTML wenn nichts anderes da ist."""
    ohne = _TAGS.sub(" ", html)
    ohne = (
        ohne.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    knapp = _LEERRAUM.sub(" ", ohne).strip()
    return knapp[:laenge]


def anreisser(text: str, laenge: int = 200) -> str:
    """Aus reinem Text. Zitatzeilen fliegen raus — sie sagen nichts Neues."""
    zeilen = [z for z in text.splitlines() if not z.lstrip().startswith(">")]
    return _LEERRAUM.sub(" ", " ".join(zeilen)).strip()[:laenge]
