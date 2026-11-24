"""Profilbilder, wie in den anderen nex-Apps (Vorbild nexnotes, ``services/avatars.py``).

Herein kommt ein Bild jeder Sorte, die ein Telefon oder eine Kamera macht;
behalten wird ein quadratisches WebP von ``GROESSE`` Pixeln, neu gezeichnet.
⚠️ **Von der Datei überlebt nur ihr Bild:** kein Ort, kein Gerät, kein
verstecktes zweites Bild, kein Skript in einem SVG (ein SVG wird gar nicht
genommen). Die Sorte entscheiden die ersten Bytes, nie der Name.

Sehen dürfen es das Konto selbst und der Betreiber (seine Benutzerliste).
"""

from __future__ import annotations

import io
import logging
import struct

from ..meldung import Meldung
from ..models import Benutzer

logger = logging.getLogger("nexmail.profilbild")


class ProfilbildFehler(Meldung):
    """Ein Bild, das nicht genommen wird; die Kennung übersetzt die Oberfläche."""


GROESSE = 256
#: Größer als jedes Foto eines Telefons; darüber wird die Datei nicht einmal geöffnet.
MAX_BYTES = 20 * 1024 * 1024
#: Pixel des gekommenen Bildes (ein 1-Bit-PNG ist auf der Platte winzig und im Speicher riesig).
MAX_PIXEL = 50_000_000
#: Was Telefone und Kameras machen. Der Decoder öffnet mehr (TIFF, PSD, EPS mit Ghostscript): hier nicht.
SORTEN = {"jpeg", "png", "webp", "gif", "bmp", "heic", "avif"}
_AVIF = {b"avif", b"avis"}
_HEIF = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


def sorte(kopf: bytes) -> str | None:
    """Die Sorte einer Datei an ihren ersten Bytes."""
    if kopf.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if kopf.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if kopf[:4] == b"RIFF" and kopf[8:12] == b"WEBP":
        return "webp"
    if kopf.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if kopf.startswith(b"BM") and len(kopf) > 14:
        return "bmp"
    if len(kopf) >= 12 and kopf[4:8] == b"ftyp":
        laenge = struct.unpack(">I", kopf[:4])[0]
        marken = {kopf[8:12]} | {kopf[i : i + 4] for i in range(16, min(laenge, len(kopf)) - 3, 4)}
        if marken & _AVIF:
            return "avif"
        if marken & _HEIF:
            return "heic"
    return None


def zeichnen(daten: bytes) -> bytes:
    """Das quadratische WebP eines Bildes, aufrecht und auf seine Mitte zugeschnitten.

    Wirft ``ProfilbildFehler`` mit ``profilbild_zu_gross`` oder ``profilbild_kein_bild``.
    """
    if len(daten) > MAX_BYTES:
        raise ProfilbildFehler("profilbild_zu_gross", max_mb=MAX_BYTES // (1024 * 1024))
    if sorte(daten[:64]) not in SORTEN:
        raise ProfilbildFehler("profilbild_kein_bild")
    try:
        import pillow_heif
        from PIL import Image, ImageOps

        pillow_heif.register_heif_opener()
        with Image.open(io.BytesIO(daten)) as bild:
            if bild.width * bild.height > MAX_PIXEL:
                raise ProfilbildFehler("profilbild_zu_gross", max_mb=MAX_BYTES // (1024 * 1024))
            aufrecht = ImageOps.exif_transpose(bild)
            quadrat = ImageOps.fit(
                aufrecht.convert("RGBA"), (GROESSE, GROESSE), Image.Resampling.LANCZOS
            )
            raus = io.BytesIO()
            quadrat.save(raus, "WEBP", quality=85, method=4, exif=b"", xmp=b"")
            return raus.getvalue()
    except ProfilbildFehler:
        raise
    except Exception as fehler:  # noqa: BLE001 - ein kaputtes Bild scheitert auf seine eigene Weise
        logger.info("A profile picture could not be read: %s", type(fehler).__name__)
        raise ProfilbildFehler("profilbild_kein_bild") from fehler


def darf_sehen(betrachter: Benutzer, besitzer_id: str) -> bool:
    """Jedes angemeldete Konto des Servers (Entwurf, Teil 2: „Profilbilder sehen alle angemeldeten Konten“, in jeder
    App gleich; vorher nur das Konto selbst und der Betreiber). Abgemeldete nie: Die Route verlangt eine Anmeldung.
    nexmail sperrt keine Konten, also gibt es keine gesperrten, die nur der Betreiber sehen duerfte."""
    return betrachter is not None and bool(besitzer_id)
