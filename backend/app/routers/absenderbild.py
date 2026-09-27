"""Das Bild vor einer Zeile der Liste — siehe ``services/absenderbild.py``."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from ..deps import AngemeldeterBenutzer, DbSession
from ..services import absenderbild

router = APIRouter(prefix="/api/absenderbild", tags=["absenderbild"])

#: ⚠️ **Die Kopfzeilen sind der halbe Schutz.** Ein Markenlogo ist ein SVG von
#: fremder Hand und wird unter nexmails Adresse ausgeliefert. ``nosniff`` setzt
#: die Middleware fuer alles; diese Inhaltsregel kommt **zusaetzlich** zu ihrer
#: (der Browser setzt beide durch, die engere gewinnt) und nimmt einer direkt
#: geoeffneten Adresse mit ``sandbox`` jede Moeglichkeit, als Seite von nexmail
#: etwas auszufuehren. Die andere Haelfte ist ``svg_pruefen``: SVG Tiny PS,
#: ohne Skript und ohne Verweis nach draussen.
_SCHUTZ = {"content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"}


@router.get("")
def bild(
    person: AngemeldeterBenutzer,
    db: DbSession,
    adresse: str = Query(min_length=3, max_length=320),
    logo: bool = False,
) -> Response:
    """Kontaktfoto oder Markenlogo; 404 heisst: Initialen.

    ``logo`` setzt die Oberflaeche nur an Mails mit bestandener
    Absenderpruefung. ⚠️ **Ein 404 ist hier der Normalfall** und wird deshalb
    auch kurz gemerkt; sonst fragte jede Liste bei jedem Neuzeichnen wieder.
    """
    gefunden = absenderbild.bild(db, person, adresse, mit_logo=logo)
    if gefunden is None:
        return Response(status_code=404, headers={"cache-control": "private, max-age=300", **_SCHUTZ})
    daten, art = gefunden
    return Response(
        content=daten,
        media_type=art,
        headers={"cache-control": "private, max-age=86400", **_SCHUTZ},
    )
