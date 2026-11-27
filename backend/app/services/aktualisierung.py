"""Nachsehen, ob es eine neuere Version von nexmail gibt: das gemeinsame Modul updates 0.1.3 (``vendor/nexupdates``).

Bis zum Durchgang „Module“ (26.11.2026) stand hier nexmails eigene, ältere Fassung. Das Modul behebt ihre drei
Schwächen: Ein Fehlschlag überschreibt den letzten guten Stand nicht mehr (und wird nach einer Stunde wiederholt, nicht
erst nach 24), die Antwort ist auf 256 KB begrenzt und nur ein Tag der Form ``v1.2.3`` zählt, und es geht weder über
einen Proxy aus der Umgebung noch einer Weiterleitung nach. Neu ist ``NEXMAIL_UPDATE_URL``.

nexmail bleibt bei seinem Schalter ``update_pruefen`` (``"0"`` aus, ``"1"`` an, leer oder fehlend: nie gespeichert,
also an) und bei seinen alten Wegen ``/api/ueber`` (dünne Hülle in ``routers/ueber.py``). Die Wege des Moduls liegen
unter ``/api/about``.

⚠️ **Keine Glocke, aber Geräte** (U19, U24; geraete G56): nexmail hat keine Glocke (``on_newer`` fehlt). Ein Gerät
eines Betreibers, das „Neue Version“ versteht und will, zählt wie eine Glocke (``devices_want`` =
``geraete_store.update_gewollt``): nur dann, und nur solange „Einmal am Tag nachsehen“ an ist, sieht der Aufräumfaden
höchstens einmal am Tag nach (``im_hintergrund``) und sagt es einmal je Version diesen Geräten (``on_devices`` =
``geraete_store.neue_version``). Die veröffentlichte iPhone-App nennt ``update`` nicht, ohne ein solches Gerät fragt
der Hintergrund also nie. Gefragt wird außerdem, wenn ein Betreiber „Über nexmail“ öffnet oder „Jetzt nachsehen“
klickt. Ein Mitglied löst nie eine Frage aus und erfährt nichts über den Stand (U2, U15).

⚠️ **Die Prüfung ist Beiwerk.** Fällt GitHub aus, fehlt das Netz oder antwortet die Schnittstelle mit einem Fehler,
geht davon nichts in der Oberfläche kaputt; dann steht dort einfach kein Stand.
"""

from __future__ import annotations

from .. import __version__
from ..config import get_settings
from ..vendor import nexupdates

#: Der Schalter, wo er immer lag (Tabelle ``einstellung``).
SCHLUESSEL_UPDATE_PRUEFEN = "update_pruefen"
#: Die Version, von der die Geräte der Betreiber zuletzt hörten (G18): niemand hört zweimal von derselben.
SCHLUESSEL_UPDATE_GEMELDET = "update_gemeldet"

REPO = "DerKezorm/nexmail"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
#: Leer, solange die Projektseiten abgeschaltet sind (seit 17.10.2026, U18): die Zeile „Projektseite“ fällt weg.
PROJEKTSEITE = ""


def _lesen() -> bool | None:
    """Der Schalter, wie er gespeichert ist; None, solange ihn nie jemand angefasst hat (leer oder fehlend)."""
    from ..db import SessionLocal, einstellung_lesen

    with SessionLocal() as db:
        wert = einstellung_lesen(db, SCHLUESSEL_UPDATE_PRUEFEN)
    return None if wert == "" else wert != "0"


def _schreiben(an: bool) -> None:
    """In der Form von vorher: ``"1"`` an, ``"0"`` aus (eine ältere Fassung liest ihn genauso)."""
    from ..db import SessionLocal, einstellung_schreiben

    with SessionLocal() as db:
        einstellung_schreiben(db, SCHLUESSEL_UPDATE_PRUEFEN, "1" if an else "0")


def _gemeldet_lesen() -> str | None:
    from ..db import SessionLocal, einstellung_lesen

    with SessionLocal() as db:
        return einstellung_lesen(db, SCHLUESSEL_UPDATE_GEMELDET) or None


def _gemeldet_schreiben(fassung: str) -> None:
    from ..db import SessionLocal, einstellung_schreiben

    with SessionLocal() as db:
        einstellung_schreiben(db, SCHLUESSEL_UPDATE_GEMELDET, fassung)


def _geraete_wollen() -> bool:
    """``devices_want`` (U24): ob ein Gerät eines Betreibers „Neue Version“ will."""
    from . import geraete_store

    return geraete_store.update_gewollt()


def _neue_version(fassung: str) -> None:
    """``on_devices`` (U24): die Version ohne das ``v`` des Tags an die Geräte der Betreiber."""
    from . import geraete_store

    geraete_store.neue_version(fassung.removeprefix("v"))


def im_hintergrund() -> str | None:
    """Ein Blick im Hintergrund (``look_once``): fragt das Netz höchstens einmal am Tag, nur bei „an“ und nur, solange
    ein Gerät eines Betreibers es will; findet er eine neuere Version, geht sie einmal an diese Geräte."""
    return nexupdates.check.look_once()


def konfigurieren() -> None:
    """Beim Laden der App (``main``), vor der ersten Anfrage; der Vertragsadapter startet so neu."""
    nexupdates.configure(
        nexupdates.AppConfig(
            app_name="nexmail",
            version=lambda: __version__,
            repo=REPO,
            project_url=PROJEKTSEITE,
            update_url=lambda: get_settings().update_url,
            read_switch=_lesen,
            write_switch=_schreiben,
            # Keine Glocke (U19); die Geräte der Betreiber über den Modulweg (U24, geraete G56), einmal je Version.
            on_newer=None,
            devices_want=_geraete_wollen,
            on_devices=_neue_version,
            read_told=_gemeldet_lesen,
            write_told=_gemeldet_schreiben,
        )
    )


#: Die Namen von vorher, für alles, was sie noch ruft.
ist_neuer = nexupdates.is_newer
zuruecksetzen = nexupdates.forget
