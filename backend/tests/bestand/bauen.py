"""Builds the "Bestand" test database with the code that is checked out right now.

The test ``tests/test_bestand.py`` loads what this script wrote and checks that every sign-in that worked in that
version still works in the running one. That only means something if the database comes from the OLD code. So:

    git worktree add ../nexmail-0.33.0 v0.33.0
    cd ../nexmail-0.33.0/backend
    <venv>/python tests/bestand/bauen.py --ziel <this repo>/backend/tests/bestand

⚠️ **Never rebuild it with a newer version and commit the result.** It would then describe the new schema, and the
test would prove nothing about installations that run 0.33.0 today. The script refuses to run when ``__version__`` is
not ``FASSUNG``; a fixture for a later version gets its own file name.

Only invented people and ``example.*`` addresses. Every random value that the test needs to know (session cookies,
device and API keys, the invitation key, recovery codes) is made predictable here by replacing ``secrets`` in the few
modules that draw them; the code paths themselves are the ones of the version. Ids and password hashes stay random, so
two runs give the same accounts, not the same bytes.

⚠️ **Stored as gzip'ed SQL, not as ``.db``.** ``test_veroeffentlichung`` refuses ``*.db`` in the repo (operating
data), and the push guard refuses 32+ hex characters in a text diff, which every id and token hash in a plain dump
is. The full-text index is left out; every version builds it at start.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

HIER = Path(__file__).resolve().parent
FASSUNG = "0.33.0"
#: Same as ``tests/conftest.py``. The fixture's data key is wrapped with it, so the test can open TOTP secrets.
TESTSCHLUESSEL = "nur-fuer-tests-nicht-geheim"
ISSUER = "https://sso.example.com"
CLIENT_ID = "nexmail-bestand"
CLIENT_GEHEIMNIS = "bestand-client"
KUERZEL = "sso"
OEFFENTLICHE_ADRESSE = "https://mail.example.com"


def dump_datei(ordner: Path = HIER) -> Path:
    return ordner / f"bestand-{FASSUNG}.sql.gz"


def manifest_datei(ordner: Path = HIER) -> Path:
    return ordner / f"bestand-{FASSUNG}.json"


def totp_geheimnis(etikett: str) -> str:
    """The TOTP secret of an account in the fixture, derived instead of stored (no secret-looking value in Git)."""
    return base64.b32encode(hashlib.sha256(f"bestand-totp-{etikett}".encode()).digest()[:20]).decode()


class FesterZufall:
    """Stands in for ``secrets`` in the modules that hand out values the test must know.

    ``token_urlsafe`` returns ``bestand-<etikett>``; the script sets ``etikett`` before each call that draws one, so
    each value is unique and readable. ``choice`` walks the alphabet (recovery codes). Everything else is the real
    module, ``compare_digest`` included.
    """

    def __init__(self) -> None:
        self.etikett = "unbenannt"
        self._schritt = 0

    def token_urlsafe(self, nbytes: int | None = None) -> str:  # noqa: ARG002
        return f"bestand-{self.etikett}"

    def choice(self, folge):
        self._schritt += 1
        return folge[(self._schritt * 7) % len(folge)]

    def __getattr__(self, name: str):
        return getattr(secrets, name)


def _umgebung(daten: Path) -> None:
    os.environ["NEXMAIL_DATA_DIR"] = str(daten)
    os.environ["NEXMAIL_SECRET_KEY"] = TESTSCHLUESSEL
    os.environ["NEXMAIL_ZWEI_FAKTOR_AUS"] = "false"
    os.environ["NEXMAIL_URL_BASE"] = ""
    os.environ["NEXMAIL_CLIENT_IP"] = ""
    os.environ["NEXMAIL_TAKT_SEKUNDEN"] = "0"


def bauen(ziel: Path) -> None:
    daten = Path(tempfile.mkdtemp(prefix="nexmail-bestand-"))
    _umgebung(daten)
    backend = HIER.parent.parent
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend / "tests" / "nexoidc"))

    import pyotp
    from fastapi.testclient import TestClient

    import oidc_fakes as fakes
    from app import __version__
    from app.config import get_settings
    from app.db import SessionLocal, engine, einstellung_schreiben, init_db
    from app.main import app
    from app.models import Benutzer
    from app.services import anbieter, apischluessel, app_kopplung, einladung, imap, konten, sitzung, zwei_faktor
    from app.vendor import nexoidc
    from app.vendor.nexoidc import attempt, protocol

    if __version__ != FASSUNG:
        sys.exit(f"This is nexmail {__version__}; the fixture describes {FASSUNG}. Check out v{FASSUNG} first.")

    zufall = FesterZufall()
    for modul in (sitzung, einladung, apischluessel, zwei_faktor):
        modul.secrets = zufall  # type: ignore[attr-defined]
    zwei_faktor.geheimnis_erzeugen = lambda: totp_geheimnis(zufall.etikett)

    # No mail server and no network: the mailbox check answers itself, like in tests/test_konten.py.
    anbieter._holen = lambda url: None
    konten.pruefen = lambda daten, wo="", token="": konten.Befund(
        imap=konten.Teilbefund(ok=True),
        smtp=konten.Teilbefund(ok=True),
        ordner=[imap.Ordnerangabe("INBOX", "INBOX", "posteingang", True, ["abonniert"])],
        faehigkeiten=["IMAP4REV1"],
    )

    netz = fakes.Network()
    nexoidc.use_transport(netz.transport())
    protocol.clear_caches()
    attempt.forget_used_states()
    anbieter_fake = netz.add(fakes.FakeProvider(ISSUER, client_id=CLIENT_ID, client_secret=CLIENT_GEHEIMNIS))

    init_db()
    konten_liste: list[dict] = []

    def browser() -> TestClient:
        return TestClient(app, base_url=OEFFENTLICHE_ADRESSE, follow_redirects=False)

    def ok(antwort, *codes: int):
        assert antwort.status_code in (codes or (200,)), (antwort.status_code, antwort.text[:300])
        return antwort

    def cookie(klient: TestClient) -> str:
        return klient.cookies.get(sitzung.COOKIE_NAME) or ""

    def zwei_faktor_an(klient: TestClient, etikett: str) -> list[str]:
        zufall.etikett = etikett
        geheimnis = ok(klient.post("/api/auth/zwei-faktor/starten")).json()["geheimnis"]
        assert geheimnis == totp_geheimnis(etikett)
        code = pyotp.TOTP(geheimnis).now()
        return ok(klient.post("/api/auth/zwei-faktor/bestaetigen", json={"code": code})).json()["codes"]

    def einladen(name: str, adresse: str, anzeigename: str) -> str:
        zufall.etikett = f"einladung-{name.lower()}"
        with SessionLocal() as db:
            _, schluessel = einladung.aussprechen(db, benutzername=name, adresse=adresse, anzeigename=anzeigename)
        return schluessel

    def annehmen(schluessel: str, passwort: str, etikett: str) -> TestClient:
        klient = browser()
        zufall.etikett = f"sitzung-{etikett}"
        ok(klient.post(f"/api/einladung/{schluessel}", json={"passwort": passwort}), 201)
        return klient

    def ueber_anbieter(klient: TestClient, person: dict, etikett: str, *, einladung_schluessel: str | None = None):
        anbieter_fake.person = person
        zufall.etikett = f"sitzung-{etikett}"
        start = klient.get(f"/api/oidc/{KUERZEL}/start", params={"invite": einladung_schluessel} if einladung_schluessel else {})
        beim_anbieter = start.headers["location"]
        pfad = urlsplit(parse_qs(urlsplit(beim_anbieter).query)["redirect_uri"][0]).path
        zurueck = klient.get(f"{pfad}?{urlencode(anbieter_fake.authorize(beim_anbieter))}")
        assert zurueck.status_code in (302, 303) and "error" not in zurueck.headers["location"], zurueck.headers

    def wer(klient: TestClient) -> dict:
        return ok(klient.get("/api/auth/ich")).json()

    # --- The operator: password, address, second factor ------------------------------------------------------------
    betreiber = browser()
    zufall.etikett = "sitzung-betreiber"
    ok(
        betreiber.post(
            "/api/setup/konto",
            json={"benutzername": "betreiber", "passwort": "Bestand-betreiber-2026", "anzeigename": "Betrieb Beispiel"},
        ),
        201,
    )
    ok(betreiber.put("/api/auth/ich/kontaktadresse", json={"adresse": "betrieb@example.com"}))
    codes_betreiber = zwei_faktor_an(betreiber, "betreiber")
    konten_liste.append(
        {
            "benutzername": "betreiber",
            "passwort": "Bestand-betreiber-2026",
            "adresse": "betrieb@example.com",
            "betreiber": True,
            "zweiter_faktor": "betreiber",
            "wiederherstellungscodes": codes_betreiber,
            "fall": "operator, password, address, second factor",
        }
    )

    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", OEFFENTLICHE_ADRESSE)
        app_kopplung.erlauben(db, True)
    ok(betreiber.put("/api/apischluessel/erlaubt", json={"erlaubt": True}))
    ok(
        betreiber.post(
            "/api/oidc/admin/providers",
            json={
                "label": "SSO",
                "slug": KUERZEL,
                "issuer": ISSUER,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_GEHEIMNIS,
            },
        ),
        201,
    )

    # --- Capital letters, no address (removed after accepting) ----------------------------------------------------
    erika = annehmen(einladen("Erika.Muster", "erika@example.org", "Erika Muster"), "Bestand-erika-2026", "erika")
    ok(erika.put("/api/auth/ich/kontaktadresse", json={"adresse": ""}))
    assert wer(erika)["benutzername"] == "Erika.Muster"
    konten_liste.append(
        {
            "benutzername": "Erika.Muster",
            "passwort": "Bestand-erika-2026",
            "adresse": "",
            "sitzung": cookie(erika),
            "fall": "capital letters in the username, password, no address, open browser session",
        }
    )

    # --- Address, mailbox and an API key ---------------------------------------------------------------------------
    jonas = annehmen(einladen("jonas", "jonas@example.net", "Jonas Beispiel"), "Bestand-jonas-2026", "jonas")
    postfach = ok(
        jonas.post(
            "/api/konten",
            json={
                "anzeigename": "Privat",
                "adresse": "jonas.post@example.net",
                "imap_server": "imap.example.net",
                "imap_port": 993,
                "imap_sicherheit": "ssl",
                "imap_benutzer": "jonas.post",
                "imap_passwort": "postfach-kennwort-1",
                "smtp_server": "smtp.example.net",
                "smtp_port": 587,
                "smtp_sicherheit": "starttls",
                "smtp_benutzer": "jonas.post@example.net",
                "smtp_passwort": "postfach-kennwort-1",
            },
        ),
        201,
    ).json()["id"]
    zufall.etikett = "api-jonas"
    api_schluessel = ok(
        jonas.post("/api/apischluessel", json={"name": "Dashboard", "stufe": "anzahl", "konten": [postfach]}), 201
    ).json()["schluessel"]
    konten_liste.append(
        {
            "benutzername": "jonas",
            "passwort": "Bestand-jonas-2026",
            "adresse": "jonas@example.net",
            "api_schluessel": api_schluessel,
            "fall": "password, address, mailbox, API key",
        }
    )

    # --- Two accounts, one address (case differs), passwords of 10 and 11 characters ------------------------------
    annehmen(einladen("kim", "familie@example.net", "Kim Beispiel"), "kim-123456", "kim")
    annehmen(einladen("lou", "Familie@Example.net", ""), "lou-1234567", "lou")
    konten_liste += [
        {
            "benutzername": "kim",
            "passwort": "kim-123456",
            "adresse": "familie@example.net",
            "doppelte_adresse": True,
            "fall": "address shared with lou, password of 10 characters",
        },
        {
            "benutzername": "lou",
            "passwort": "lou-1234567",
            "adresse": "Familie@Example.net",
            "doppelte_adresse": True,
            "fall": "address shared with kim, empty display name in the invitation, password of 11 characters",
        },
    ]

    # --- Second factor and a paired iPhone -------------------------------------------------------------------------
    mona = annehmen(einladen("mona", "mona@example.com", "Mona Beispiel"), "Bestand-mona-2026", "mona")
    codes_mona = zwei_faktor_an(mona, "mona")
    zufall.etikett = "geraet-mona"
    with SessionLocal() as db:
        person = db.query(Benutzer).filter(Benutzer.benutzername == "mona").one()
        geraet = sitzung.geraet_anlegen(db, person, "iPhone (Bestand)", "")
    konten_liste.append(
        {
            "benutzername": "mona",
            "passwort": "Bestand-mona-2026",
            "adresse": "mona@example.com",
            "zweiter_faktor": "mona",
            "wiederherstellungscodes": codes_mona,
            "geraet": geraet,
            "fall": "password, second factor, paired iPhone",
        }
    )

    # --- Password and a provider -----------------------------------------------------------------------------------
    sam = annehmen(einladen("sam", "sam@example.com", "Sam Beispiel"), "Bestand-sam-2026", "sam")
    verknuepfung = ok(sam.post(f"/api/oidc/{KUERZEL}/link", json={"password": "Bestand-sam-2026"})).json()["url"]
    anbieter_fake.person = {"sub": "bestand-sam", "preferred_username": "sam", "name": "Sam Beispiel", "email": "sam@example.com"}
    pfad = urlsplit(parse_qs(urlsplit(verknuepfung).query)["redirect_uri"][0]).path
    zurueck = sam.get(f"{pfad}?{urlencode(anbieter_fake.authorize(verknuepfung))}")
    assert zurueck.status_code in (302, 303) and "error" not in zurueck.headers["location"], zurueck.headers
    konten_liste.append(
        {
            "benutzername": "sam",
            "passwort": "Bestand-sam-2026",
            "adresse": "sam@example.com",
            "anbieter": {"sub": "bestand-sam", "preferred_username": "sam", "name": "Sam Beispiel", "email": "sam@example.com"},
            "fall": "password and a linked provider",
        }
    )

    # --- Only a provider: the name comes from the provider, not from the invitation (module 1.0.14) ----------------
    robin_person = {
        "sub": "bestand-robin",
        "preferred_username": "Robin.SSO",
        "name": "Robin Beispiel",
        "email": "robin@sso.example.com",
    }
    robin = browser()
    ueber_anbieter(robin, robin_person, "robin", einladung_schluessel=einladen("robin", "robin@example.com", "Robin Beispiel"))
    robin_ich = wer(robin)
    assert robin_ich["benutzername"] == "Robin.SSO" and not robin_ich["hat_kennwort"], robin_ich
    konten_liste.append(
        {
            "benutzername": "Robin.SSO",
            "adresse": "robin@example.com",
            "anbieter": robin_person,
            "fall": "provider only, invited as 'robin', named after preferred_username, address from the invitation",
        }
    )

    j_person = {"sub": "bestand-j", "preferred_username": "j", "name": "", "email": "j@sso.example.com"}
    j = browser()
    ueber_anbieter(j, j_person, "j", einladung_schluessel=einladen("jay", "jay@example.org", ""))
    assert wer(j)["benutzername"] == "j"
    konten_liste.append(
        {
            "benutzername": "j",
            "adresse": "jay@example.org",
            "anbieter": j_person,
            "fall": "provider only, one-character name (the module allows it, the new rules do not)",
        }
    )

    # --- An open invitation with a username set by the operator ----------------------------------------------------
    offen = einladen("neu.gast", "gast@example.org", "Gast Beispiel")

    for klient in (betreiber, erika, jonas, mona, sam, robin, j):
        klient.close()
    nexoidc.use_transport(None)
    engine.dispose()

    ziel.mkdir(parents=True, exist_ok=True)
    _sql_schreiben(get_settings().db_path, dump_datei(ziel))
    manifest = {
        "fassung": FASSUNG,
        "testschluessel": "tests/conftest.py (NEXMAIL_SECRET_KEY)",
        "anbieter": {"kuerzel": KUERZEL, "issuer": ISSUER, "client_id": CLIENT_ID, "client_geheimnis": CLIENT_GEHEIMNIS},
        "oeffentliche_adresse": OEFFENTLICHE_ADRESSE,
        "konten": konten_liste,
        "offene_einladung": {
            "schluessel": offen,
            "benutzername": "neu.gast",
            "adresse": "gast@example.org",
            "anzeigename": "Gast Beispiel",
        },
    }
    manifest_datei(ziel).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(daten, ignore_errors=True)
    print(f"Wrote {dump_datei(ziel)} and {manifest_datei(ziel)}.")


def _sql_schreiben(db_pfad: Path, ziel: Path) -> None:
    """The database as SQL, without the full-text index (a virtual table plus shadow tables and triggers)."""
    verbindung = sqlite3.connect(str(db_pfad))
    try:
        zeilen = [
            z
            for z in verbindung.iterdump()
            if "nachricht_fts" not in z and not z.startswith("PRAGMA writable_schema")
        ]
    finally:
        verbindung.close()
    roh = ("\n".join(zeilen) + "\n").encode("utf-8")
    puffer = io.BytesIO()
    # mtime 0: the same SQL gives the same file.
    with gzip.GzipFile(fileobj=puffer, mode="wb", mtime=0) as gepackt:
        gepackt.write(roh)
    ziel.write_bytes(puffer.getvalue())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ziel", type=Path, default=HIER, help="where the .sql.gz and .json go (default: here)")
    bauen(parser.parse_args().ziel)
