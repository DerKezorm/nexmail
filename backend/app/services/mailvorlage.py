"""Wie eine Mail aussieht, die nexmail selbst verschickt.

⚠️ **HTML-Mail ist nicht HTML.** Was hier steht, sieht aus wie 1998 und ist es
auch: Tabellen statt Flexbox, Stile in jedem Element statt im Kopf, feste
Hex-Werte statt Token. Gmail wirft `<style>` teilweise weg, Outlook rendert mit
Word, und `flex`, `grid`, `gap`, CSS-Variablen und `border-radius` fallen der
Reihe nach aus. Wer hier die Oberflaechen-Bausteine benutzt, baut etwas, das im
Browser gut aussieht und im Postfach zerfaellt.

⚠️ **Immer beide Teile.** ``multipart/alternative`` mit Text **und** HTML: Wer
seinen Client auf Nur-Text stellt — und in dieser Zielgruppe tun das einige —
bekaeme sonst eine leere Mail mit einem Anhang.

⚠️ **Das Logo haengt an, es wird nicht geholt.** Ein ``<img src="https://…">``
wuerde von jedem ordentlichen Client blockiert, und wenn nicht, meldete es dem
Absender die Oeffnung. nexmail klinkt in fremden Mails genau solche Bilder aus
— es waere lachhaft, selbst welche zu verschicken. Deshalb ``cid:``: Das Bild
liegt in der Mail und faellt unter keinen Bildblocker.

Die Farben stammen aus ``frontend/src/styles/tokens/colors.css`` und dem Logo.
Sie stehen hier ausgeschrieben, weil eine Mail keine Token kennt.
"""

from __future__ import annotations

from email.message import EmailMessage
from html import escape
from pathlib import Path

#: Aus den nexapps-Tokens. Nicht erfinden — nachschlagen.
NEX_400 = "#23d19e"  # --accent
NEX_300 = "#5fe4bb"  # --accent-hover
#: ⚠️ Fuer Schrift auf **weissem** Grund. ``--accent`` (#23d19e) ist dafuer
#: zu hell, ``--nex-900`` liest sich schwarz — die Wortmarke waere dann
#: einfarbig, und das Zeichen daneben stimmt nicht mehr mit ihr ueberein.
NEX_700 = "#007a58"
NEX_900 = "#043226"
GRAU_1000 = "#060909"  # --text-on-accent
LOGO_PLATTE = "#0d1614"  # der Grund des Zeichens

#: ⚠️ **Heller Grund, nicht dunkler.** Die Oberflaeche ist dunkel; eine Mail
#: ist es nicht. Viele Clients hinterlegen fremdes HTML mit Weiss, und dann
#: steht helle Schrift auf hellem Grund. Wer es dunkel will, hat den
#: Dunkelmodus seines Clients — der dreht diese Mail sauber mit.
GRUND = "#f2f5f4"
KARTE = "#ffffff"
TEXT = "#121817"
TEXT_LEISE = "#5b6b68"
LINIE = "#dde3e3"

LOGO = Path(__file__).resolve().parent.parent / "vorlagen" / "logo.png"
LOGO_KENNUNG = "nexmail-logo"


def _knopf(text: str, ziel: str) -> str:
    """Ein Knopf aus einer Tabellenzelle.

    ⚠️ **Kein ``<a>`` mit Polsterung.** Outlook ignoriert ``padding`` an einem
    Verweis, und der Knopf wird zu unterstrichenem Text. Eine Zelle mit
    Hintergrund halten alle.
    """
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="center" bgcolor="{NEX_400}" style="border-radius:8px;">
            <a href="{escape(ziel, quote=True)}"
               style="display:inline-block;padding:12px 26px;font-family:
               -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
               font-size:15px;font-weight:600;color:{GRAU_1000};
               text-decoration:none;border-radius:8px;">{escape(text)}</a>
          </td>
        </tr>
      </table>"""


def rahmen(*, ueberschrift: str, absaetze: list[str], knopf: tuple[str, str] | None,
           fusszeile: str) -> str:
    """Das Geruest jeder Systemmail. Inhalt kommt als fertige Absaetze."""
    schrift = "-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"

    inhalt = "".join(
        f'<p style="margin:0 0 14px;font-family:{schrift};font-size:15px;'
        f'line-height:1.55;color:{TEXT};">{a}</p>'
        for a in absaetze
    )

    knopfteil = (
        f'<div style="margin:22px 0 8px;">{_knopf(*knopf)}</div>' if knopf else ""
    )

    return f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(ueberschrift)}</title></head>
<body style="margin:0;padding:0;background:{GRUND};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:{GRUND};padding:28px 12px;">
    <tr><td align="center">

      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="max-width:520px;background:{KARTE};border:1px solid {LINIE};
             border-radius:14px;overflow:hidden;">

        <!-- Kopf: Zeichen und Wortmarke. Das Zeichen haengt als cid an. -->
        <tr>
          <td style="padding:26px 28px 0;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="padding-right:10px;" valign="middle">
                  <img src="cid:{LOGO_KENNUNG}" width="34" height="34" alt="nexmail"
                       style="display:block;border:0;border-radius:9px;">
                </td>
                <td valign="middle" style="font-family:{schrift};font-size:17px;
                    font-weight:700;letter-spacing:-0.01em;color:{TEXT};">
                  NEX<span style="color:{NEX_700};">MAIL</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:20px 28px 0;">
            <h1 style="margin:0 0 14px;font-family:{schrift};font-size:21px;
                line-height:1.3;font-weight:600;color:{TEXT};">
              {escape(ueberschrift)}
            </h1>
            {inhalt}
            {knopfteil}
          </td>
        </tr>

        <tr>
          <td style="padding:22px 28px 26px;">
            <hr style="border:0;border-top:1px solid {LINIE};margin:0 0 14px;">
            <p style="margin:0;font-family:{schrift};font-size:12px;
               line-height:1.5;color:{TEXT_LEISE};">{fusszeile}</p>
          </td>
        </tr>
      </table>

    </td></tr>
  </table>
</body>
</html>"""


def anhaengen(mail: EmailMessage, html: str) -> None:
    """Den HTML-Teil und das Logo an eine Mail mit Textteil haengen.

    ⚠️ **Reihenfolge zaehlt.** In ``multipart/alternative`` gilt der
    **letzte** Teil als der beste; der Textteil muss also zuerst gesetzt sein
    (``mail.set_content(...)``), das HTML danach. Andersherum zeigen Clients
    den rohen Text, und die ganze Gestaltung war umsonst.
    """
    mail.add_alternative(html, subtype="html")

    # Das Bild gehoert **in den HTML-Teil**, nicht neben ihn: Sonst haengt es
    # als Anhang an der Mail und der Empfaenger sieht eine Bueroklammer.
    html_teil = mail.get_payload()[-1]
    try:
        daten = LOGO.read_bytes()
    except OSError:
        # ⚠️ Ohne Logo lieber eine Mail ohne Bild als gar keine. Eine
        # Einladung, die an einer fehlenden Datei scheitert, waere das
        # schlechteste Ergebnis von allen.
        return
    html_teil.add_related(
        daten, maintype="image", subtype="png", cid=f"<{LOGO_KENNUNG}>", filename="nexmail.png"
    )
