"""Die oeffentliche Adresse und der Vorbau (``NEXMAIL_URL_BASE``).

Seit dem Anmeldemodul gilt die gespeicherte Adresse samt Vorbau, so wie man nexmail im Browser erreicht
(``https://mail.example.org/nexmail``). 0.21 speicherte sie ohne und haengte den Vorbau beim Bauen von Rueckleitadressen
an. Wer heute eine Adresse baut und den Vorbau noch einmal anhaengt, darf ihn nicht doppelt schreiben.
"""

from __future__ import annotations


def mit_vorbau(adresse: str, vorbau: str) -> str:
    """Die Adresse samt Vorbau, ohne Schraegstrich am Ende; endet sie schon darauf, bleibt sie, wie sie ist."""
    adresse = (adresse or "").rstrip("/")
    if not vorbau or adresse.endswith(vorbau):
        return adresse
    return adresse + vorbau
