"""Die oeffentliche Adresse und der Vorbau (``NEXMAIL_URL_BASE``).

Gespeichert wird die Adresse so wie in 0.21: ohne Vorbau (``https://mail.example.org``). 0.21 hat den Vorbau beim Bauen
von Rueckleitadressen angehaengt, und ein Rueckweg auf 0.21 muss mit der gespeicherten Adresse weiter arbeiten, ohne
dass er doppelt dasteht. Das Anmeldemodul sieht die Adresse samt Vorbau, so wie man nexmail im Browser erreicht
(``https://mail.example.org/nexmail``); ``fuer_modul`` bildet sie zur Laufzeit, ``ohne_vorbau`` schneidet ihn beim
Speichern ab. Wer eine Adresse baut und den Vorbau noch einmal anhaengt, darf ihn nicht doppelt schreiben.
"""

from __future__ import annotations


def mit_vorbau(adresse: str, vorbau: str) -> str:
    """Die Adresse samt Vorbau, ohne Schraegstrich am Ende; endet sie schon darauf, bleibt sie, wie sie ist."""
    adresse = (adresse or "").rstrip("/")
    if not vorbau or adresse.endswith(vorbau):
        return adresse
    return adresse + vorbau


def ohne_vorbau(adresse: str, vorbau: str) -> str:
    """Die Adresse in der gespeicherten Form (wie 0.21): ohne Schraegstrich am Ende und ohne den Vorbau, wenn sie auf
    ihn endet. Alles andere bleibt, wie es eingegeben wurde."""
    adresse = (adresse or "").strip().rstrip("/")
    if vorbau and adresse.endswith(vorbau):
        adresse = adresse[: -len(vorbau)].rstrip("/")
    return adresse


def fuer_modul(gespeichert: str, vorbau: str) -> str:
    """Die gespeicherte Adresse, so wie das Anmeldemodul sie braucht (samt Vorbau); "" bleibt "" (dann gilt die
    Adresse der Anfrage)."""
    if not (gespeichert or "").strip():
        return ""
    return mit_vorbau(gespeichert.strip(), vorbau)
