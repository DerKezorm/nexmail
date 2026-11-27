"""„Was ist neu“ über das Modul wasneu 0.1.0 (``vendor/nexwasneu``): die Texte, der Banner nach dem Update, das
Fenster und die Zeile auf „Über nexmail“.

Die Texte liegen im Paket (``app/wasneu/<sprache>.json``, dazu ``released.json``), damit das Abbild sie trägt; der
Wächter ``tests/nexwasneu/test_nexwasneu_texts.py`` hält vor jedem Release fest, dass die laufende x.y.0 ihren Text in
beiden Sprachen hat und kein veröffentlichter Text umgeschrieben wird. Gesehen wird am Konto gemerkt
(``benutzer.wasneu_gesehen``), wie vorher; neue Konten starten auf der laufenden Version (``seen_for_new_account``).
Nach jedem Release: ``python bauplaene-konten/wasneu/tools/sync.py freeze nexmail``.
"""

from __future__ import annotations

from pathlib import Path

from .. import __version__
from ..deps import AngemeldeterBenutzer, DbSession
from ..vendor import nexwasneu

#: Die eingebauten Sprachen; Englisch ist der Rückfall.
SPRACHEN = ("de", "en")


def konfigurieren() -> None:
    """Beim Start (``main.py``): Name, laufende Version, Ordner der Texte."""
    nexwasneu.configure(
        nexwasneu.AppConfig(
            app_name="nexmail",
            version=lambda: __version__,
            folder=Path(__file__).resolve().parent.parent / "wasneu",
            languages=SPRACHEN,
        )
    )


def betrachter(person: AngemeldeterBenutzer, db: DbSession) -> nexwasneu.Viewer:
    """Das angemeldete Konto, wie das Modul es braucht. ⚠️ ``mark`` speichert sofort: Wegklicken wartet in der
    Oberfläche nicht auf den Server, und der Banner soll beim nächsten Laden nicht wiederkommen."""

    def merken(version: str) -> None:
        person.wasneu_gesehen = version
        db.commit()

    return nexwasneu.Viewer(
        seen=person.wasneu_gesehen or "",
        operator=bool(person.ist_betreiber),
        mark=merken,
        language=person.sprache or None,
    )
