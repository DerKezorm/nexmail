"""Technische Konfiguration von nexmail.

Hier stehen nur Betriebs-Einstellungen: Pfade, Laufzeiten, das Verhalten
hinter einem Reverse Proxy. Alles, was der Betreiber in der Oberflaeche
pflegt - oeffentliche Adresse, Postfaecher, Regeln -, liegt in der Datenbank.

⚠️ **Nichts wird geraten.** Jede Einstellung, die von der Umgebung abhaengt
(Proxy davor? HTTPS?), hat eine Vorgabe, die im Zweifel *nicht* schaerfer ist
als noetig. Der Grund steht jeweils daneben; siehe FALLSTRICKE.md §3.
"""

from __future__ import annotations

import logging
import re
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("nexmail.config")

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXMAIL_",
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ablage -------------------------------------------------------------

    data_dir: Path = PROJECT_ROOT / "data"
    static_dir: str = ""

    # --- Verschluesselung ---------------------------------------------------
    #
    # Der Schluessel-Schluessel (KEK). Leer lassen ist in Ordnung: nexmail legt
    # beim ersten Start einen an und speichert ihn unter ``data/secret.key``.
    #
    # ⚠️ Wer ihn hier setzt, zieht ihn aus dem Datenverzeichnis heraus - dann
    # ist eine gestohlene Sicherung allein wertlos. Das ist der einzige
    # wirksame Hebel; siehe FALLSTRICKE.md §6.
    secret_key: str = ""

    # --- Sitzungen ----------------------------------------------------------

    #: Wie lange eine Anmeldung ohne Nutzung gilt.
    sitzung_tage: int = 30
    #: Wie lange der Zwischenschritt zwischen Passwort und Code gilt.
    zwei_faktor_minuten: int = 5

    # --- Notausgang ---------------------------------------------------------
    #
    # ⚠️ Schaltet den zweiten Faktor ab. Gedacht fuer genau einen Fall: Das
    # Telefon mit der Authenticator-App ist weg und die Wiederherstellungscodes
    # sind es auch. Wer an die compose-Datei kommt, kommt ohnehin an /data -
    # der Hammer macht also kein neues Loch auf, er macht ein vorhandenes
    # benutzbar. Beim Start wird er laut protokolliert.
    zwei_faktor_aus: bool = False

    # --- Der Takt -----------------------------------------------------------

    # Wie oft nexmail von selbst nach neuer Post sieht (Sekunden).
    # ⚠️ **0 schaltet ihn ab** - dann kommt neue Post erst auf Klick. Zwei
    # Minuten sind der Kompromiss: haeufig genug, dass es sich lebendig
    # anfuehlt, selten genug, dass ein Anbieter es nicht als Dauerlast sieht.
    # Weniger als 30 Sekunden waere unhoeflich gegenueber dem Server, deshalb
    # die Untergrenze.
    takt_sekunden: int = 120

    # --- Protokoll -----------------------------------------------------------

    # Stufe: leise | normal | ausfuehrlich | alles.
    # ⚠️ **Der Notausgang.** Gesetzt uebersteuert sie die gespeicherte Stufe
    # und laesst sich in der Oberflaeche nicht mehr umstellen - gebraucht,
    # wenn die Anwendung gar nicht erst startet und man an keine Oberflaeche
    # kommt. Leer heisst: Die Oberflaeche entscheidet.
    log_stufe: str = ""

    # Zeitzone fuer die Anzeige, z. B. ``Europe/Berlin``.
    # ⚠️ **Ein Container laeuft fast immer in UTC**, der Betreiber nicht. Ohne
    # diese Angabe zeigt die Oberflaeche die Zone des Browsers - was auf einem
    # Telefon im Urlaub die falsche ist. Leer heisst: die des Browsers.
    zeitzone: str = ""

    # --- Hinter einem Reverse Proxy ----------------------------------------

    # Unterpfad, unter dem nexmail laeuft - z. B. ``/nexmail`` fuer
    # ``https://example.com/nexmail/``.
    #
    # Leer heisst: nexmail wohnt an der Wurzel. Ist der Pfad gesetzt,
    # beantwortet nexmail jede Adresse **doppelt** - mit und ohne Vorbau.
    # Beides ist noetig, weil Proxys auf zwei Arten eingestellt sind: Die einen
    # reichen den Pfad mitsamt Vorbau durch, die anderen schneiden ihn vorher
    # ab. Und der Docker-Healthcheck ruft ohnehin an der Wurzel an.
    #
    # ``/api`` ist verboten - er fiele mit der Schnittstelle zusammen.
    url_base: str = ""

    # Ob das Sitzungs-Cookie nur ueber HTTPS mitfahren darf (Secure).
    #
    #   auto   Secure, wenn die Anfrage ueber https kam (Vorgabe)
    #   on     immer - fuer einen Proxy, der HTTPS abschliesst und intern
    #          schlichtes http weiterreicht
    #   off    nie
    #
    # ⚠️ Nicht auf "on" stellen, wenn nexmail ueber http:// erreichbar sein
    # soll: Der Browser wirft ein Secure-Cookie ueber http weg, und dann kommt
    # niemand mehr hinein.
    cookie_secure: str = "auto"

    # Woher die Adresse des Anfragenden kommt - gebraucht von der Anmeldebremse.
    #
    #   leer      nur nach Konto zaehlen (Vorgabe, immer sicher)
    #   direct    nexmail haengt direkt am Netz
    #   proxy     genau ein Reverse Proxy davor
    #   proxy:2   zwei davor, z. B. Cloudflare und dahinter ein eigener
    #
    # ⚠️ Leer lassen, wenn unklar. Steht hier "direct", obwohl ein Proxy
    # davorsteht, sehen alle Anfragen aus wie dieselbe Adresse - dann sperrt
    # ein einziger Vertipper den ganzen Haushalt aus.
    client_ip: str = ""

    # --- Entwicklung --------------------------------------------------------

    cors_origins: list[str] = [
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ]

    # ------------------------------------------------------------------ #

    @field_validator("url_base", mode="before")
    @classmethod
    def _url_base_aufraeumen(cls, wert: object) -> object:
        """Fuehrenden Schraegstrich ergaenzen, abschliessenden entfernen.

        Wer versehentlich eine ganze Adresse eintraegt, bekommt deren Pfad.
        Das ist keine Bequemlichkeit: Ein ``url_base`` mit Schema haette
        Adressen wie ``/https://example.com/nexmail/api/health`` erzeugt, und
        der Fehler waere erst im Browser aufgefallen.
        """
        if not isinstance(wert, str) or not wert.strip():
            return ""
        roh = wert.strip()
        if "://" in roh:
            roh = urlsplit(roh).path
        roh = "/" + roh.strip("/")
        if roh == "/":
            return ""
        if not re.fullmatch(r"(/[A-Za-z0-9._~-]+)+", roh):
            raise ValueError(
                "NEXMAIL_URL_BASE darf nur Buchstaben, Ziffern, Punkt, "
                "Unterstrich, Tilde und Bindestrich enthalten."
            )
        if roh == "/api" or roh.startswith("/api/"):
            raise ValueError("NEXMAIL_URL_BASE darf nicht mit /api beginnen.")
        return roh

    @field_validator("takt_sekunden", mode="after")
    @classmethod
    def _takt_untergrenze(cls, wert: int) -> int:
        if wert <= 0:
            return 0
        return max(30, wert)

    @field_validator("zwei_faktor_aus", mode="before")
    @classmethod
    def _leer_heisst_nein(cls, wert: object) -> object:
        """Eine leere Umgebungsvariable heisst "nicht gesetzt", nicht "kaputt".

        ⚠️ **Sonst startet der Container gar nicht.** In der compose-Datei
        steht ``NEXMAIL_ZWEI_FAKTOR_AUS: ${NEXMAIL_ZWEI_FAKTOR_AUS:-}`` - der
        Normalfall ist also eine gesetzte, leere Variable. pydantic kann ""
        nicht als Ja/Nein lesen und wirft einen Validierungsfehler, und der
        Betreiber sieht einen Container, der sofort wieder stirbt, mit einer
        Meldung ueber "bool_parsing". Genau das ist beim Schreiben der
        compose-Datei passiert.
        """
        if isinstance(wert, str) and not wert.strip():
            return False
        return wert

    @field_validator("cookie_secure", mode="before")
    @classmethod
    def _cookie_secure_pruefen(cls, wert: object) -> object:
        text = str(wert or "auto").strip().lower()
        if text not in {"auto", "on", "off"}:
            raise ValueError("NEXMAIL_COOKIE_SECURE muss auto, on oder off sein.")
        return text

    @field_validator("client_ip", mode="before")
    @classmethod
    def _client_ip_pruefen(cls, wert: object) -> object:
        text = str(wert or "").strip().lower()
        if text and text != "direct" and not re.fullmatch(r"proxy(:[1-9]\d?)?", text):
            raise ValueError("NEXMAIL_CLIENT_IP muss leer, direct, proxy oder proxy:<Zahl> sein.")
        return text

    # ------------------------------------------------------------------ #

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nexmail.db"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    def resolved_secret_key(self) -> str:
        """Der Schluessel-Schluessel - aus der Umgebung oder von der Platte.

        Liegt keiner vor, wird einer erzeugt und abgelegt. Die Rechte werden
        auf 0600 gesetzt; unter Windows verpufft das folgenlos, unter Linux
        ist es der Unterschied zwischen "nur der Dienst" und "jeder Benutzer
        auf dem Server".
        """
        if self.secret_key.strip():
            return self.secret_key.strip()

        pfad = self.key_path
        if pfad.exists():
            vorhanden = pfad.read_text(encoding="utf-8").strip()
            if vorhanden:
                return vorhanden

        pfad.parent.mkdir(parents=True, exist_ok=True)
        neu = secrets.token_urlsafe(48)
        pfad.write_text(neu + "\n", encoding="utf-8")
        try:
            pfad.chmod(0o600)
        except OSError:  # pragma: no cover - Windows, Netzlaufwerke
            logger.debug("Rechte an %s liessen sich nicht setzen.", pfad)
        logger.info("A new encryption key was generated at %s.", pfad)
        return neu

    def anzahl_proxys(self) -> int:
        """Wie viele Proxys laut Einstellung davorstehen. 0 = keiner/unbekannt."""
        if self.client_ip.startswith("proxy"):
            _, _, zahl = self.client_ip.partition(":")
            return int(zahl) if zahl else 1
        return 0


@lru_cache
def get_settings() -> Settings:
    einstellungen = Settings()
    einstellungen.data_dir.mkdir(parents=True, exist_ok=True)
    return einstellungen
