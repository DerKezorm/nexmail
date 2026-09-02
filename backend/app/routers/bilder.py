"""Der Bild-Vermittler.

Eine Adresse, an der die Bilder fremder Mails liegen — geholt vom Server, nicht
vom Browser. Warum es diesen Umweg gibt und was daran gemessen wurde, steht in
``services/bildvermittler.py``.

⚠️ **Diese Adresse verlangt keine Anmeldung, und sie kann es nicht.** Der
Abruf kommt aus dem abgeschotteten Lesebereich; der hat eine fremde Herkunft,
und das Sitzungs-Cookie steht auf ``SameSite=Strict`` — es faehrt nicht mit.
Am 02.09.2026 im echten Chromium nachgemessen, nicht angenommen. Der Ausweis
ist deshalb die **Unterschrift in der Adresse**: Sie oeffnet genau ein Bild,
gilt eine Stunde und wird nur ausgestellt, wenn jemand angemeldet ist und die
Mail lesen darf.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from ..services import bildvermittler

logger = logging.getLogger("nexmail.bilder")

router = APIRouter(prefix="/api/bilder", tags=["bilder"])


@router.get("/{marke}")
def bild(marke: str) -> Response:
    """Ein Bild aus einer Mail — geholt, nicht durchgereicht."""
    try:
        adresse = bildvermittler.marke_pruefen(marke)
        inhalt, typ = bildvermittler.holen(adresse)
    except bildvermittler.Abgelehnt as grund:
        # ⚠️ **Ein Bild aus dem eigenen Netz ist einen Satz im Protokoll
        # wert.** Es heisst entweder, dass hier eine Mail aus dem Homelab
        # liegt (harmlos, und die Bilder fehlen), oder dass jemand versucht
        # hat, nexmail als Fernbedienung zu benutzen. Beides will man sehen.
        if grund.kennung == "bild_adresse_im_eigenen_netz":
            logger.warning("An image in a message pointed into a private network; refused.")
        else:
            logger.debug("An image could not be fetched (%s).", grund.kennung)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=grund.kennung
        ) from None

    return Response(
        content=inhalt,
        media_type=typ,
        headers={
            # ⚠️ **Genauso lange wie die Marke gilt.** Ein laenger
            # zwischengespeichertes Bild haenge an einer Adresse, die schon
            # abgelaufen ist — dann faende der Browser sie beim naechsten Mal
            # kaputt vor. ``private``, weil ein Proxy dazwischen die Post
            # anderer Leute nicht sammeln soll.
            "cache-control": f"private, max-age={bildvermittler.GUELTIG_SEKUNDEN}",
        },
    )
