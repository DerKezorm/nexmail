"""Sicherung und Wiederherstellung.

Der wichtigste Test hier ist ``test_alles_im_datenverzeichnis_ist_entschieden``.
Er prüft nicht „ist die Datenbank drin", sondern dreht es um: **Alles** im
Datenverzeichnis muss entweder ins Archiv gehen oder begründet auf der
Ausnahmeliste stehen. Genau weil in Nexview nur benannte Bestandteile geprüft
wurden, konnte dort ein ganzer Ordner unbemerkt fehlen.
"""

from __future__ import annotations

import io
import json

import pyzipper
import pytest

from app.config import get_settings
from app.services import sicherung
from conftest import einrichten

PASSWORT = "sehr-geheim-123"
ARCHIVPASSWORT = "archiv-passwort-1"


def _inhalt(daten: bytes) -> list[str]:
    with pyzipper.AESZipFile(io.BytesIO(daten)) as z:
        z.setpassword(ARCHIVPASSWORT.encode())
        return sorted(z.namelist())


def test_archiv_traegt_datenbank_und_manifest(klient):
    einrichten(klient)
    antwort = klient.post("/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT})
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/zip"
    assert "attachment" in antwort.headers["content-disposition"]

    namen = _inhalt(antwort.content)
    assert "nexmail.db" in namen
    assert "manifest.json" in namen


def test_archiv_ohne_passwort_gibt_es_nicht(klient):
    einrichten(klient)
    antwort = klient.post("/api/sicherung/erstellen", json={"passwort": ""})
    assert antwort.status_code == 422


def test_ohne_anmeldung_kein_archiv(klient):
    einrichten(klient)
    klient.cookies.clear()
    antwort = klient.post("/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT})
    assert antwort.status_code == 401


def test_rundlauf(klient, db):
    """Sichern, etwas ändern, einspielen — der Stand von vorher ist wieder da."""
    einrichten(klient)
    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content

    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://danach.example"})
    assert (
        klient.get("/api/einstellungen").json()["oeffentliche_adresse"]
        == "https://danach.example"
    )

    antwort = klient.post(
        "/api/sicherung/einspielen",
        files={"datei": ("sicherung.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
    )
    assert antwort.status_code == 200, antwort.text

    # Die Einstellung von *nach* der Sicherung ist weg - so soll es sein.
    from app.db import SessionLocal, einstellung_lesen

    with SessionLocal() as frisch:
        assert einstellung_lesen(frisch, "oeffentliche_adresse") == ""


def test_falsches_passwort_sagt_das_auch(klient):
    einrichten(klient)
    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content

    antwort = klient.post(
        "/api/sicherung/einspielen",
        files={"datei": ("sicherung.zip", archiv, "application/zip")},
        data={"passwort": "ganz-anderes-passwort"},
    )
    assert antwort.status_code == 400
    assert "archiv_passwort_falsch" == antwort.json()["detail"]


def test_keine_zip_datei(klient):
    einrichten(klient)
    antwort = klient.post(
        "/api/sicherung/einspielen",
        files={"datei": ("nicht.zip", b"das ist kein zip", "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
    )
    assert antwort.status_code == 400


def test_falscher_schluessel_ersetzt_nichts(klient):
    """⚠️ Der Test, der eine laufende Installation rettet.

    Wenn der Schlüssel nicht zur Datenbank im Archiv passt, wären alle
    Postfach-Passwörter danach unlesbar. Also wird **vorher** geprüft und
    nichts angefasst — und die Meldung sagt, was fehlt.
    """
    einrichten(klient)
    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content

    # In den Tests kommt der Schlüssel aus der Umgebung, liegt also nicht im
    # Archiv. Ein anderer Schlüssel schließt den Daten-Schlüssel nicht auf.
    einstellungen = get_settings()
    vorher = einstellungen.secret_key
    einstellungen.secret_key = "ein-ganz-anderer-schluessel"
    try:
        antwort = klient.post(
            "/api/sicherung/einspielen",
            files={"datei": ("sicherung.zip", archiv, "application/zip")},
            data={"passwort": ARCHIVPASSWORT},
        )
    finally:
        einstellungen.secret_key = vorher

    assert antwort.status_code == 400
    assert "schluessel_passt_nicht" == antwort.json()["detail"]

    # Und die laufende Installation steht noch.
    assert klient.get("/api/auth/ich").status_code == 200


def test_einspielen_vor_einrichtung_schliesst_sich(klient):
    """Wie beim ersten Konto: offen, bis es einen Benutzer gibt."""
    antwort = klient.post(
        "/api/sicherung/einspielen-vor-einrichtung",
        files={"datei": ("x.zip", b"kaputt", "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
    )
    # Offen - der Inhalt ist Unsinn, aber der Weg ist da.
    assert antwort.status_code == 400

    einrichten(klient)
    zu = klient.post(
        "/api/sicherung/einspielen-vor-einrichtung",
        files={"datei": ("x.zip", b"kaputt", "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
    )
    assert zu.status_code == 404


def test_alles_im_datenverzeichnis_ist_entschieden(klient):
    """⚠️ **Der Wächter.**

    Wer eine neue Datei ins Datenverzeichnis legt, muss entscheiden, ob sie in
    eine Sicherung gehört. Dieser Test erzwingt die Entscheidung — er ist
    nicht dazu da, hinterher durch einen Eintrag auf der Ausnahmeliste
    beruhigt zu werden.
    """
    einrichten(klient)

    # Ein realistisches Datenverzeichnis herstellen.
    einstellungen = get_settings()
    (einstellungen.data_dir / "blobs").mkdir(exist_ok=True)
    (einstellungen.data_dir / "blobs" / "abc123").write_bytes(b"ein Anhang")
    (einstellungen.data_dir / "sicherungen").mkdir(exist_ok=True)
    (einstellungen.data_dir / "sicherungen" / "alt.db").write_bytes(b"alt")
    (einstellungen.data_dir / "logs").mkdir(exist_ok=True)
    (einstellungen.data_dir / "ausgang").mkdir(exist_ok=True)
    (einstellungen.data_dir / "ausgang" / "wartet.eml").write_bytes(b"From: a@b.example")

    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content
    im_archiv = set(_inhalt(archiv))

    # Was im Archiv unter welchem Namen liegt. Ordner tragen dort ein
    # Praefix - deshalb reicht ein Name-zu-Name-Vergleich nicht.
    abbildung = {
        "nexmail.db": sicherung.DATENBANK_IM_ARCHIV,
        "secret.key": sicherung.SCHLUESSEL_IM_ARCHIV,
    }
    praefixe = {"ausgang": "ausgang/"}

    unentschieden = []
    for name in sicherung.datenverzeichnis_eintraege():
        if abbildung.get(name) in im_archiv:
            continue
        vorbau = praefixe.get(name)
        if vorbau and any(e.startswith(vorbau) for e in im_archiv):
            continue
        if name in sicherung.NICHT_INS_ARCHIV:
            continue
        unentschieden.append(name)

    assert not unentschieden, (
        "Diese Einträge im Datenverzeichnis landen weder im Archiv noch stehen "
        f"sie begründet auf der Ausnahmeliste: {unentschieden}\n\n"
        "Das ist keine Aufforderung, sie einzutragen. Die Frage ist, ob sie in "
        "eine Sicherung gehören - und wenn dir kein Grund einfällt, warum "
        "nicht, gehören sie hinein."
    )


def test_ungesendete_post_ist_im_archiv(klient):
    """⚠️ Was im Ausgang liegt, hat noch niemand bekommen.

    Es ist Zustand, kein Zwischenspeicher — wer es weglässt, verliert bei
    einer Wiederherstellung genau die Mails, die noch niemand hat. Diese
    Entscheidung hat der Wächter erzwungen, als das Verzeichnis entstand.
    """
    einrichten(klient)
    einstellungen = get_settings()
    ausgang = einstellungen.data_dir / "ausgang"
    ausgang.mkdir(exist_ok=True)
    (ausgang / "abc123.eml").write_bytes(
        b"From: a@b.example" + bytes([13, 10, 13, 10]) + b"noch nicht raus"
    )

    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content

    assert "ausgang/abc123.eml" in _inhalt(archiv)


def test_jede_ausnahme_hat_einen_grund():
    ohne = [n for n, grund in sicherung.NICHT_INS_ARCHIV.items() if len(grund.strip()) < 40]
    assert not ohne, f"Ohne brauchbare Begründung ausgenommen: {ohne}"


def test_anhaenge_sind_nicht_im_archiv(klient):
    """Bewusst so entschieden — die Sicherung soll klein genug bleiben."""
    einrichten(klient)
    einstellungen = get_settings()
    (einstellungen.data_dir / "blobs").mkdir(exist_ok=True)
    (einstellungen.data_dir / "blobs" / "grosser-anhang").write_bytes(b"x" * 10_000)

    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content
    assert not any("blobs" in n for n in _inhalt(archiv))


def test_manifest_nennt_was_fehlt(klient):
    """Wer das Archiv öffnet, soll ohne uns verstehen, was er hat."""
    einrichten(klient)
    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content

    with pyzipper.AESZipFile(io.BytesIO(archiv)) as z:
        z.setpassword(ARCHIVPASSWORT.encode())
        manifest = json.loads(z.read(sicherung.MANIFEST_IM_ARCHIV))

    assert manifest["anwendung"] == "nexmail"
    assert "blobs" in manifest["nicht_enthalten"]


def test_schluessel_wandert_ins_archiv(klient):
    """⚠️ Die wichtigste Zusage der ganzen Sicherung.

    Ohne ``secret.key`` im Archiv sind beim Einspielen alle Postfach-Passwörter
    unlesbar. Genau in Nexview ist das der teuer gelernte Punkt.

    Dieser Test entstand, weil die Mutationsprobe ihn vermisst hat: In der
    Testumgebung kommt der Schlüssel aus ``NEXMAIL_SECRET_KEY``, also lief der
    Zweig „Datei danebenlegen" nie - und man konnte das Mitnehmen des
    Schlüssels abschalten, ohne dass ein einziger Test rot wurde.
    """
    einrichten(klient)

    einstellungen = get_settings()
    vorher = einstellungen.secret_key
    einstellungen.key_path.write_text(vorher + chr(10), encoding="utf-8")
    einstellungen.secret_key = ""  # jetzt kommt er von der Platte
    try:
        archiv = klient.post(
            "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
        ).content
        namen = _inhalt(archiv)

        assert sicherung.SCHLUESSEL_IM_ARCHIV in namen, (
            "Der Schlüssel fehlt im Archiv. Beim Einspielen wären damit alle "
            "Postfach-Passwörter unlesbar."
        )
        assert "SCHLUESSEL-FEHLT.txt" not in namen

        with pyzipper.AESZipFile(io.BytesIO(archiv)) as z:
            z.setpassword(ARCHIVPASSWORT.encode())
            assert z.read(sicherung.SCHLUESSEL_IM_ARCHIV).decode().strip() == vorher

        import json as _json

        with pyzipper.AESZipFile(io.BytesIO(archiv)) as z:
            z.setpassword(ARCHIVPASSWORT.encode())
            manifest = _json.loads(z.read(sicherung.MANIFEST_IM_ARCHIV))
        assert manifest["schluessel_dabei"] is True
    finally:
        einstellungen.secret_key = vorher
        einstellungen.key_path.unlink(missing_ok=True)


def test_hinweis_wenn_der_schluessel_aus_der_umgebung_kommt(klient):
    """⚠️ Ohne diesen Hinweis ist das Archiv eine Falle.

    Kommt der Schlüssel aus NEXMAIL_SECRET_KEY, liegt er nicht bei — und wer
    das erst beim Einspielen merkt, hat die Postfächer verloren.
    """
    einrichten(klient)
    archiv = klient.post(
        "/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT}
    ).content

    namen = _inhalt(archiv)
    assert "SCHLUESSEL-FEHLT.txt" in namen

    with pyzipper.AESZipFile(io.BytesIO(archiv)) as z:
        z.setpassword(ARCHIVPASSWORT.encode())
        text = z.read("SCHLUESSEL-FEHLT.txt").decode("utf-8")
    assert "NEXMAIL_SECRET_KEY" in text


@pytest.mark.parametrize("pfad", ["/api/sicherung/erstellen", "/api/sicherung/einspielen"])
def test_beide_wege_wollen_eine_anmeldung(klient, pfad):
    einrichten(klient)
    klient.cookies.clear()
    assert klient.post(pfad, json={"passwort": ARCHIVPASSWORT}).status_code == 401


def test_die_groesse_wird_beim_lesen_gezaehlt_nicht_danach():
    """⚠️ **Sonst liegt die Datei schon im Speicher, wenn die Grenze greift.**

    Bis zum 03.09.2026 stand hier `daten = await datei.read()` und die Prüfung
    eine Zeile später. Bei `MAX_BYTES = 512 MB` heißt das: Der Container nimmt
    sich das halbe Gigabyte, bevor er ablehnt — und dieser Weg ist über
    `/api/sicherung/einspielen-vor-einrichtung` **ohne Anmeldung** erreichbar.
    Der Nachbarrouter (mbox-Upload) macht es seit jeher in Blöcken richtig.

    Gezählt wird, wie viele Bytes wirklich gelesen wurden, nicht die Laufzeit:
    Genau darum geht es.
    """
    import asyncio

    from app.routers import sicherung as router

    class ZaehlendeDatei:
        """Tut so, als wäre sie doppelt so groß wie erlaubt."""

        def __init__(self) -> None:
            self.gelesen = 0
            self.uebrig = router.MAX_BYTES * 2

        async def read(self, groesse: int = -1) -> bytes:
            if groesse < 0:  # der alte Weg: alles auf einmal
                block = b"x" * self.uebrig
                self.uebrig = 0
            else:
                block = b"x" * min(groesse, self.uebrig)
                self.uebrig -= len(block)
            self.gelesen += len(block)
            return block

    datei = ZaehlendeDatei()
    with pytest.raises(Exception) as fehler:
        asyncio.run(router._gelesen(datei))  # noqa: SLF001 - genau das ist der Prüfling

    assert getattr(fehler.value, "status_code", None) == 413
    # ⚠️ Ein Block Toleranz: Der Abbruch kommt, sobald die Grenze überschritten
    # ist, also einen Block danach.
    assert datei.gelesen <= router.MAX_BYTES + router.UPLOAD_BLOCK, (
        f"{datei.gelesen} Bytes gelesen, obwohl bei {router.MAX_BYTES} Schluss ist."
    )


def test_eine_kleine_sicherung_kommt_vollstaendig_an():
    """Die Gegenprobe: Blockweise lesen darf nichts abschneiden."""
    import asyncio

    from app.routers import sicherung as router

    inhalt = bytes(range(256)) * 9000  # gut 2 MB, also mehrere Blöcke

    class Datei:
        def __init__(self) -> None:
            self.rest = inhalt

        async def read(self, groesse: int = -1) -> bytes:
            block = self.rest if groesse < 0 else self.rest[:groesse]
            self.rest = b"" if groesse < 0 else self.rest[groesse:]
            return block

    assert asyncio.run(router._gelesen(Datei())) == inhalt  # noqa: SLF001
