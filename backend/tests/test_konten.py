"""Postfächer anbinden.

⚠️ **Kein Test hier geht ins Netz.** Autoconfig und IMAP werden ersetzt. Ein
Testlauf, der von fremden Servern abhängt, ist irgendwann rot, ohne dass
jemand etwas kaputt gemacht hat — und dann glaubt ihm niemand mehr.
"""

from __future__ import annotations

import socket
import ssl

import pytest

from app.services import anbieter, imap, konten
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

PASSWORT = "sehr-geheim-123"

# Ein echtes Autoconfig-Dokument in der Form, die Thunderbird ausliefert.
# ⚠️ Die beiden verschiedenen Benutzernamen sind der Grund für dieses Beispiel.
ICLOUD_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<clientConfig version="1.1">
  <emailProvider id="icloud.com">
    <domain>icloud.com</domain>
    <displayName>iCloud</displayName>
    <incomingServer type="imap">
      <hostname>imap.mail.me.com</hostname>
      <port>993</port>
      <socketType>SSL</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILLOCALPART%</username>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>smtp.mail.me.com</hostname>
      <port>587</port>
      <socketType>STARTTLS</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </outgoingServer>
  </emailProvider>
</clientConfig>
"""

# Ein Anbieter, von dem nexmail nie gehört hat.
FREMD_XML = b"""<?xml version="1.0"?>
<clientConfig version="1.1">
  <emailProvider id="beispiel.example">
    <displayName>Beispiel Mail</displayName>
    <incomingServer type="pop3">
      <hostname>pop.beispiel.example</hostname><port>995</port>
      <socketType>SSL</socketType><username>%EMAILADDRESS%</username>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>imap.beispiel.example</hostname><port>143</port>
      <socketType>STARTTLS</socketType><username>%EMAILADDRESS%</username>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>smtp.beispiel.example</hostname><port>465</port>
      <socketType>SSL</socketType><username>%EMAILADDRESS%</username>
    </outgoingServer>
  </emailProvider>
</clientConfig>
"""


# --- Autoconfig ---------------------------------------------------------- #


def test_icloud_bekommt_zwei_verschiedene_benutzernamen(monkeypatch):
    """⚠️ Die Falle, die sonst einen Abend kostet.

    Apple will beim Posteingang nur den Namensteil und beim Postausgang die
    vollständige Adresse. Wer beides gleich einträgt, kann lesen aber nicht
    senden — und iCloud meldet in beiden Fällen dasselbe wie bei einem
    Tippfehler.
    """
    monkeypatch.setattr(anbieter, "_holen", lambda url: ICLOUD_XML)

    gefunden = anbieter.vorschlagen("anna@icloud.com")
    assert gefunden is not None
    assert gefunden.imap.benutzerform == "nur_name"
    assert gefunden.smtp.benutzerform == "volle_adresse"

    assert anbieter.benutzer_bilden("anna@icloud.com", gefunden.imap.benutzerform) == (
        "anna"
    )
    assert anbieter.benutzer_bilden("anna@icloud.com", gefunden.smtp.benutzerform) == (
        "anna@icloud.com"
    )


def test_unbekannter_anbieter_geht_ueber_autoconfig(monkeypatch):
    """Der eigentliche Sinn: ein Postfach, von dem nexmail nichts weiß."""
    monkeypatch.setattr(anbieter, "_holen", lambda url: FREMD_XML)

    gefunden = anbieter.vorschlagen("wer@beispiel.example")
    assert gefunden is not None
    assert gefunden.imap.server == "imap.beispiel.example"
    assert gefunden.imap.port == 143
    assert gefunden.imap.sicherheit == "starttls"
    assert gefunden.smtp.sicherheit == "ssl"
    assert gefunden.quelle == "autoconfig"


def test_pop3_wird_nicht_genommen(monkeypatch):
    """Im Beispiel steht POP3 vor IMAP. nexmail nimmt IMAP."""
    monkeypatch.setattr(anbieter, "_holen", lambda url: FREMD_XML)
    gefunden = anbieter.vorschlagen("wer@beispiel.example")
    assert gefunden.imap.server.startswith("imap.")


def test_reihenfolge_der_quellen(monkeypatch):
    """Der Anbieter selbst zuerst, Mozilla zuletzt."""
    gefragt: list[str] = []

    def merken(url: str):
        gefragt.append(url)
        return ICLOUD_XML if "thunderbird.net" in url else None

    monkeypatch.setattr(anbieter, "_holen", merken)
    assert anbieter.autoconfig("wer@icloud.com") is not None

    assert gefragt[0].startswith("https://autoconfig.icloud.com/")
    assert ".well-known" in gefragt[1]
    assert "thunderbird.net" in gefragt[2]


def test_ohne_autoconfig_greift_die_tabelle(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    gefunden = anbieter.vorschlagen("wer@icloud.com")
    assert gefunden is not None
    assert gefunden.imap.server == "imap.mail.me.com"
    assert gefunden.quelle.startswith("eingebaut")
    assert gefunden.app_passwort_noetig is True


def test_voellig_unbekannt_gibt_nichts_zurueck(monkeypatch):
    """Kein Fehler — von Hand eintragen ist der Hauptweg."""
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    assert anbieter.vorschlagen("wer@gibtesnicht.example") is None


def test_app_passwort_hinweis_ueberlebt_autoconfig(monkeypatch):
    """⚠️ In keinem Autoconfig-Dokument steht, dass iCloud ein
    app-spezifisches Passwort verlangt. Der Hinweis kommt aus der Tabelle und
    muss auch dann mitfahren, wenn die Serverdaten von woanders stammen."""
    monkeypatch.setattr(anbieter, "_holen", lambda url: ICLOUD_XML)
    gefunden = anbieter.vorschlagen("wer@icloud.com")
    assert gefunden.quelle == "autoconfig"
    assert gefunden.app_passwort_noetig is True
    assert "apple.com" in gefunden.app_passwort_wo


def test_unverschluesselt_wird_abgelehnt(monkeypatch):
    """Ein Postfach ohne Verschlüsselung schickt das Passwort im Klartext."""
    nur_plain = ICLOUD_XML.replace(b"<socketType>SSL</socketType>", b"<socketType>plain</socketType>")
    monkeypatch.setattr(anbieter, "_holen", lambda url: nur_plain)
    # Der IMAP-Teil fällt weg, damit ist das Dokument unbrauchbar.
    assert anbieter._aus_xml(nur_plain) is None


# --- Ordnerrollen -------------------------------------------------------- #


@pytest.mark.parametrize(
    "pfad,kennzeichen,erwartet",
    [
        ("INBOX", [], "posteingang"),
        ("Sent", [rb"\Sent"], "gesendet"),
        # ⚠️ iCloud: die Namen sind anders als überall sonst.
        ("Sent Messages", [], "gesendet"),
        ("Deleted Messages", [], "papierkorb"),
        ("Junk", [], "junk"),
        ("Archive", [], "archiv"),
        # Deutsche Server.
        ("Entwürfe", [], "entwuerfe"),
        ("Gelöschte Objekte", [], "papierkorb"),
        # Kennzeichen schlägt Namen.
        ("Irgendwas", [rb"\Trash"], "papierkorb"),
        # Unterordner behalten ihre Rolle nicht vom Elternteil.
        ("Haus/Rechnungen", [], "eigen"),
        ("INBOX.Sent", [], "gesendet"),
    ],
)
def test_ordnerrollen(pfad, kennzeichen, erwartet):
    assert imap._rolle_bestimmen(pfad, kennzeichen) == erwartet


# --- Fehlerdeutung ------------------------------------------------------- #


@pytest.mark.parametrize(
    "fehler,art",
    [
        (socket.gaierror("nicht gefunden"), imap.Fehlerart.NICHT_ERREICHBAR),
        (ssl.SSLError("falsches protokoll"), imap.Fehlerart.VERSCHLUESSELUNG),
        (TimeoutError("zu lange"), imap.Fehlerart.KEINE_ANTWORT),
        (ConnectionRefusedError("nein"), imap.Fehlerart.KEINE_ANTWORT),
    ],
)
def test_fehler_werden_unterschieden(fehler, art):
    """⚠️ „Fehler" hilft bei keinem dieser Fälle weiter."""
    gedeutet = imap._deuten(fehler, "imap.beispiel.example", 993)
    assert gedeutet.art == art
    assert len(gedeutet.text) > 20
    assert "imap.beispiel.example" in gedeutet.text or "993" in gedeutet.text


def test_anmeldefehler_nennt_das_app_passwort():
    """Der teuerste Fall bekommt eine Wegbeschreibung."""
    ohne = imap._anmeldefehler("")
    mit = imap._anmeldefehler("account.apple.com")

    assert ohne.art == imap.Fehlerart.ANMELDUNG
    assert "account.apple.com" in mit.text
    assert "app-spezifischen" in mit.text
    assert len(mit.text) > len(ohne.text)


# --- Anlegen ------------------------------------------------------------- #


def _guter_befund():
    return konten.Befund(
        imap=konten.Teilbefund(ok=True),
        smtp=konten.Teilbefund(ok=True),
        ordner=[
            imap.Ordnerangabe("INBOX", "INBOX", "posteingang", True, ["abonniert"]),
            imap.Ordnerangabe("Sent Messages", "Sent Messages", "gesendet", True, ["abonniert"]),
            imap.Ordnerangabe("Deleted Messages", "Deleted Messages", "papierkorb", True, ["abonniert"]),
            imap.Ordnerangabe("Haus", "Haus", "eigen", True, ["nicht_abonniert"]),
        ],
        faehigkeiten=["IMAP4REV1", "MOVE", "IDLE"],
    )


def _eingabe(adresse="anna@icloud.example"):
    return {
        "anzeigename": "Privat",
        "adresse": adresse,
        "imap_server": "imap.mail.me.com",
        "imap_port": 993,
        "imap_sicherheit": "ssl",
        "imap_benutzer": adresse.split("@")[0],
        "imap_passwort": "app-spezifisch-1234",
        "smtp_server": "smtp.mail.me.com",
        "smtp_port": 587,
        "smtp_sicherheit": "starttls",
        "smtp_benutzer": adresse,
        "smtp_passwort": "app-spezifisch-1234",
    }


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="", token="": _guter_befund())
    yield


def test_postfach_anlegen(klient, ohne_netz):
    einrichten(klient)
    antwort = klient.post("/api/konten", json=_eingabe())
    assert antwort.status_code == 201, antwort.text

    daten = antwort.json()
    assert daten["adresse"] == "anna@icloud.example"
    assert daten["farbe"] == 1
    assert daten["anzahl_ordner"] == 4


def test_ordner_werden_uebernommen(klient, ohne_netz):
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]

    ordner = klient.get(f"/api/konten/{konto_id}/ordner").json()
    rollen = {o["pfad"]: o["rolle"] for o in ordner}

    assert rollen["INBOX"] == "posteingang"
    assert rollen["Sent Messages"] == "gesendet"
    assert rollen["Deleted Messages"] == "papierkorb"
    assert rollen["Haus"] == "eigen"
    # Der Posteingang steht oben.
    assert ordner[0]["pfad"] == "INBOX"
    # Und das Abonnement wandert mit.
    assert {o["pfad"]: o["abonniert"] for o in ordner}["Haus"] is False


def test_farben_werden_zugeteilt(klient, ohne_netz):
    """Nicht gewählt — zwei kaum unterscheidbare Töne fallen erst auf, wenn
    man aus dem falschen Postfach geantwortet hat."""
    einrichten(klient)
    farben = []
    for n in range(3):
        antwort = klient.post("/api/konten", json=_eingabe(f"konto{n}@beispiel.example"))
        farben.append(antwort.json()["farbe"])
    assert farben == [1, 2, 3]


def test_dasselbe_postfach_nicht_zweimal(klient, ohne_netz):
    einrichten(klient)
    assert klient.post("/api/konten", json=_eingabe()).status_code == 201
    zweiter = klient.post("/api/konten", json=_eingabe())
    assert zweiter.status_code == 400
    assert "postfach_schon_da" == zweiter.json()["detail"]


def test_kaputtes_postfach_wird_nicht_angelegt(klient, monkeypatch):
    """⚠️ Geprüft wird **vor** dem Anlegen.

    Ein Postfach, das in der Liste steht und nicht funktioniert, sieht aus wie
    ein Fehler von nexmail.
    """
    einrichten(klient)
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(
        konten,
        "pruefen",
        lambda daten, wo="", token="": konten.Befund(
            imap=konten.Teilbefund(ok=False, art="anmeldung", text="Passwort abgewiesen."),
            smtp=konten.Teilbefund(ok=True),
            ordner=[],
            faehigkeiten=[],
        ),
    )

    antwort = klient.post("/api/konten", json=_eingabe())
    assert antwort.status_code == 400
    assert "Passwort" in antwort.json()["detail"]
    assert klient.get("/api/konten").json() == []


def test_passwoerter_liegen_verschluesselt(klient, db, ohne_netz):
    einrichten(klient)
    klient.post("/api/konten", json=_eingabe())

    from sqlalchemy import text

    roh = db.execute(text("select imap_passwort, smtp_passwort from konto")).one()
    assert all(w.startswith("v1:") for w in roh)
    assert not any("app-spezifisch" in w for w in roh)


def test_passwort_kommt_wieder_heraus(klient, db, ohne_netz):
    """⚠️ **Der Test, der gefehlt hat.**

    Alle bisherigen prüften, dass das Passwort verschlüsselt *aussieht* und
    dass falsche Kontexte scheitern. Keiner prüfte das Selbstverständliche:
    dass es sich überhaupt wieder lesen lässt.

    Es ließ sich nicht — ``konto.id`` war beim Verschlüsseln noch ``None``,
    weil SQLAlchemy den Vorgabewert erst beim Einfügen vergibt. Aufgefallen
    ist es erst dem Abgleich, der das Passwort tatsächlich brauchte.
    """
    einrichten(klient)
    klient.post("/api/konten", json=_eingabe())

    from app.models import Konto

    konto = db.query(Konto).one()
    imap_pw, smtp_pw = konten.passwoerter_lesen(konto)
    assert imap_pw == "app-spezifisch-1234"
    assert smtp_pw == "app-spezifisch-1234"


def test_passwort_laesst_sich_nicht_umhaengen(klient, db, ohne_netz):
    """⚠️ **Der eigentliche Nachweis**, und der ist schärfer, als er aussieht.

    Nicht „mit falschem Kontext scheitert es" — das gilt auch dann noch, wenn
    der Kontext gar keine Kontokennung enthält. Geprüft wird die Eigenschaft,
    auf die es ankommt: **Ein verschlüsseltes Passwort aus Postfach A lässt
    sich nicht in Postfach B legen und dort lesen.**

    Dieser Test entstand, weil die Mutationsprobe die schwächere Fassung
    durchgewunken hat: Man konnte die Kontokennung aus dem Kontext streichen,
    ohne dass ein Test rot wurde — und genau dann wäre das Umhängen möglich.
    """
    einrichten(klient)

    eins = klient.post("/api/konten", json=_eingabe("eins@beispiel.example")).json()["id"]
    zwei = klient.post("/api/konten", json=_eingabe("zwei@beispiel.example")).json()["id"]

    from app import crypto
    from app.models import Konto

    a = db.get(Konto, eins)
    b = db.get(Konto, zwei)
    assert a.imap_passwort != b.imap_passwort, "Zwei Postfächer, zweimal derselbe Geheimtext."

    # Der Angriff: A's Geheimtext in B's Zeile schieben.
    b.imap_passwort = a.imap_passwort
    db.commit()

    with pytest.raises(crypto.SchluesselFehler):
        konten.passwoerter_lesen(b)


def test_passwort_kommt_nie_in_einer_antwort_zurueck(klient, ohne_netz):
    einrichten(klient)
    antwort = klient.post("/api/konten", json=_eingabe())
    assert "passwort" not in antwort.text.lower()
    assert "app-spezifisch" not in antwort.text

    liste = klient.get("/api/konten")
    assert "passwort" not in liste.text.lower()


def test_fremdes_postfach_ist_unsichtbar(klient, zweiter_klient, db, ohne_netz):
    """⚠️ Die Trennung, geprüft statt behauptet."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]

    _, geheimnis2 = zweiten_benutzer_anlegen(db)
    from conftest import anmelden

    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis2)

    assert zweiter_klient.get("/api/konten").json() == []
    assert zweiter_klient.get(f"/api/konten/{konto_id}/ordner").status_code == 404
    assert zweiter_klient.delete(f"/api/konten/{konto_id}").status_code == 404

    # Und beim Ersten steht es noch.
    assert len(klient.get("/api/konten").json()) == 1


def test_entfernen_nimmt_die_ordner_mit(klient, db, ohne_netz):
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]

    from app.models import Ordner

    assert db.query(Ordner).count() == 4
    assert klient.delete(f"/api/konten/{konto_id}").status_code == 204
    db.expire_all()
    assert db.query(Ordner).count() == 0


def test_vorschlag_ohne_treffer_ist_kein_fehler(klient, monkeypatch):
    einrichten(klient)
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    antwort = klient.post("/api/konten/vorschlag", json={"adresse": "wer@gibtesnicht.example"})
    assert antwort.status_code == 200
    assert antwort.json()["gefunden"] is False


def test_vorschlag_fuellt_beide_benutzernamen(klient, monkeypatch):
    einrichten(klient)
    monkeypatch.setattr(anbieter, "_holen", lambda url: ICLOUD_XML)

    daten = klient.post(
        "/api/konten/vorschlag", json={"adresse": "anna@icloud.com"}
    ).json()

    assert daten["gefunden"] is True
    assert daten["imap"]["benutzer"] == "anna"
    assert daten["smtp"]["benutzer"] == "anna@icloud.com"
    assert daten["app_passwort_noetig"] is True


def test_posteingang_gilt_immer_als_abonniert():
    """Ein Server ohne INBOX in LSUB darf den Posteingang nicht verlieren.

    ⚠️ **Aus Schaden entstanden.** All-Inkl fuehrt ``INBOX`` nicht in der
    Abonnementliste - er ist immer da und laesst sich nicht abonnieren. Die
    Ordnerspalte zeigte daraufhin Gesendet, Entwuerfe, Archiv, Spam und
    Papierkorb, aber keinen Posteingang.
    """

    class ServerOhneInboxImLsub:
        def list_folders(self):
            return [
                ((rb"\HasNoChildren",), b".", "INBOX"),
                ((rb"\HasNoChildren", rb"\Sent"), b".", "Gesendet"),
                ((rb"\HasNoChildren", rb"\Trash"), b".", "Papierkorb"),
            ]

        def list_sub_folders(self):
            # Genau wie beim echten Server: alles ausser INBOX.
            return [
                ((rb"\HasNoChildren",), b".", "Gesendet"),
                ((rb"\HasNoChildren",), b".", "Papierkorb"),
            ]

    ordner = imap.ordner_lesen(ServerOhneInboxImLsub())
    nach_pfad = {o.pfad: o for o in ordner}

    assert "abonniert" in nach_pfad["INBOX"].kennzeichen, (
        "Der Posteingang wurde als nicht abonniert eingestuft - die "
        "Ordnerspalte wuerde ihn ausblenden."
    )
    assert nach_pfad["INBOX"].rolle == "posteingang"
    # Die Regel darf nicht auf alles ausgeweitet werden: Was wirklich nicht
    # abonniert ist, bleibt es auch.
    assert "abonniert" in nach_pfad["Gesendet"].kennzeichen


# --- Schlagworte zum Gruppieren ------------------------------------------ #


def test_schlagworte_werden_gespeichert_und_zurueckgegeben(klient, ohne_netz):
    einrichten(klient)
    antwort = klient.post("/api/konten", json={**_eingabe(), "tags": ["privat", "verein"]})
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["tags"] == ["privat", "verein"]

    # Und beim Auflisten stehen sie auch da — sonst hilft das Speichern nichts.
    assert klient.get("/api/konten").json()[0]["tags"] == ["privat", "verein"]


def test_zweimal_dasselbe_wort_gibt_eine_pille(klient, ohne_netz):
    """⚠️ Groß/klein trennt keine Gruppen.

    Wer „Privat" und „privat" tippt, bekaeme sonst zwei Pillen nebeneinander,
    die gleich aussehen und Verschiedenes filtern. Behalten wird die erste
    Schreibweise — die hat er sich ausgesucht.
    """
    einrichten(klient)
    antwort = klient.post("/api/konten", json={**_eingabe(), "tags": ["Privat", "privat", " PRIVAT "]})
    assert antwort.json()["tags"] == ["Privat"]


def test_ein_komma_im_schlagwort_zerreisst_die_spalte_nicht(klient, ohne_netz):
    """Gespeichert wird kommagetrennt — ein Komma im Wort waere ein zweites."""
    einrichten(klient)
    antwort = klient.post("/api/konten", json={**_eingabe(), "tags": ["privat,arbeit"]})
    assert antwort.json()["tags"] == ["privat arbeit"]


def test_leere_und_zu_lange_schlagworte(klient, ohne_netz):
    einrichten(klient)
    antwort = klient.post(
        "/api/konten",
        json={**_eingabe(), "tags": ["  ", "", "x" * 60, *[f"t{n}" for n in range(20)]]},
    )
    tags = antwort.json()["tags"]
    assert "" not in tags
    assert all(len(t) <= 24 for t in tags)
    assert len(tags) <= 8


def test_beim_aendern_heisst_nichts_geschickt_unveraendert(klient, ohne_netz):
    """⚠️ Wie beim Passwort: Ein Feld, das nicht mitkommt, bleibt stehen.

    Sonst verloere jeder, der nur den Anzeigenamen aendert, seine Gruppierung.
    """
    einrichten(klient)
    konto_id = klient.post("/api/konten", json={**_eingabe(), "tags": ["privat"]}).json()["id"]

    ohne_tags = {k: v for k, v in _eingabe().items()}
    ohne_tags["imap_passwort"] = ""
    ohne_tags["smtp_passwort"] = ""
    ohne_tags["anzeigename"] = "Neuer Name"
    geaendert = klient.put(f"/api/konten/{konto_id}", json=ohne_tags)
    assert geaendert.status_code == 200, geaendert.text
    assert geaendert.json()["anzeigename"] == "Neuer Name"
    assert geaendert.json()["tags"] == ["privat"]

    # Eine leere Liste heisst dagegen ausdruecklich „alle weg".
    geleert = klient.put(f"/api/konten/{konto_id}", json={**ohne_tags, "tags": []})
    assert geleert.json()["tags"] == []


def test_schlagworte_eines_fremden_postfachs_bleiben_fremd(klient, zweiter_klient, ohne_netz, db):
    """Der Waechter ueber die Trennung gilt auch hier."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json={**_eingabe(), "tags": ["privat"]}).json()["id"]

    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get("/api/konten").json() == []

    # ⚠️ **Auf die Wirkung prüfen, nicht auf die Zahl.** Diese Route meldet ein
    # fremdes Postfach als 400 statt 404 — unschön, aber nichts wird verraten
    # und nichts geändert. Ein Test auf den Zahlencode hätte hier nur die
    # Nachlässigkeit festgeschrieben statt die Trennung zu prüfen.
    versuch = zweiter_klient.put(
        f"/api/konten/{konto_id}", json={**_eingabe(), "tags": ["geklaut"]}
    )
    assert versuch.status_code >= 400
    assert klient.get("/api/konten").json()[0]["tags"] == ["privat"]


def test_der_ordnerzaehler_wird_gezaehlt_nicht_abgelesen(klient, ohne_netz):
    """⚠️ **Am 02.09.2026 gemeldet: der Baum zeigte 16, der Ordner 11.**

    Die Zahl kam aus einer Spalte am Ordner, und die kann veralten — eine
    veraltete Zahl im Baum ist schlimmer als gar keine, weil man ihr glaubt.
    Gezählt wird jetzt beim Abrufen. Der Test schreibt die Spalte absichtlich
    falsch: Steht danach die Spalte in der Antwort, ist der Wächter hohl.
    """
    from datetime import datetime, timezone

    from app.db import SessionLocal
    from app.models import Nachricht, Ordner

    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe("zaehler@beispiel.example")).json()["id"]
    with SessionLocal() as db:
        posteingang = (
            db.query(Ordner)
            .filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang")
            .one()
        )
        for uid, gelesen in ((1, False), (2, False), (3, True)):
            db.add(
                Nachricht(
                    benutzer_id=posteingang.konto.benutzer_id,
                    konto_id=konto_id,
                    ordner_id=posteingang.id,
                    uid=uid,
                    betreff=f"Nummer {uid}",
                    von_adresse="wer@example.com",
                    datum=datetime(2026, 9, 2, 10, uid, tzinfo=timezone.utc),
                    gelesen=gelesen,
                )
            )
        # Die veraltete Spalte, genau wie im gemeldeten Fall.
        posteingang.ungelesen = 16
        posteingang.anzahl = 16
        db.commit()
        ordner_id = posteingang.id

    ordner = klient.get(f"/api/konten/{konto_id}/ordner").json()
    eingang = next(o for o in ordner if o["id"] == ordner_id)
    assert eingang["ungelesen"] == 2, "Die Antwort trägt die veraltete Spalte"
    assert eingang["anzahl"] == 3



# --- Kalender beim Entfernen ---------------------------------------------- #


def _mit_zustimmung(db, person):
    """Ein Postfach und ein Kalender an derselben Google-Zustimmung."""
    from app.models import Kalender, Konto, OauthZugang

    zugang = OauthZugang(benutzer_id=person.id, art="google", adresse="anja@example.com")
    db.add(zugang)
    db.flush()
    konto = Konto(
        benutzer_id=person.id,
        anzeigename="Anja",
        adresse="anja@example.com",
        imap_server="imap.gmail.com",
        imap_benutzer="anja@example.com",
        smtp_server="smtp.gmail.com",
        smtp_benutzer="anja@example.com",
        oauth_zugang_id=zugang.id,
    )
    kalender = Kalender(
        benutzer_id=person.id, name="Privat", art="caldav",
        url="https://example.com/dav/privat/", oauth_zugang_id=zugang.id,
    )
    db.add_all([konto, kalender])
    db.commit()
    return konto, kalender


def test_ein_postfach_entfernen_laesst_den_kalender_stehen(db, klient):
    """⚠️ **Der Kalender hängt an der Zustimmung, nicht am Postfach.**

    Ihn stillschweigend mitzunehmen wäre ein Datenverlust, den niemand
    angeordnet hat. Die Vorgabe ist deshalb: stehen lassen.
    """
    from app.models import Benutzer, Kalender

    einrichten(klient)
    person = db.query(Benutzer).one()
    konto, _ = _mit_zustimmung(db, person)

    konten.entfernen(db, person, konto.id)

    assert db.query(Kalender).count() == 1


def test_mit_haken_geht_der_kalender_mit(db, klient):
    """Wer beides in einem Zug angelegt hat, hält den Kalender sonst für ein
    Waisenkind — deshalb der Haken, vorbelegt mit aus. Am 03.09.2026 so
    entschieden."""
    from app.models import Benutzer, Kalender

    einrichten(klient)
    person = db.query(Benutzer).one()
    konto, _ = _mit_zustimmung(db, person)

    konten.entfernen(db, person, konto.id, kalender_mit=True)

    assert db.query(Kalender).count() == 0


def test_die_zahl_steht_an_der_kachel(db, klient):
    """⚠️ Ohne sie hakt man „Kalender mit entfernen" an, ohne zu wissen, wie
    viele das sind."""
    from app.models import Benutzer

    einrichten(klient)
    person = db.query(Benutzer).one()
    _mit_zustimmung(db, person)

    zeile = klient.get("/api/konten").json()[0]
    assert zeile["oauth_art"] == "google"
    assert zeile["oauth_kalender"] == 1


# --- Absender-Aliasse ----------------------------------------------------- #


def test_aliasse_kommen_zurueck(klient, ohne_netz):
    einrichten(klient)
    eingabe = _eingabe()
    eingabe["aliase"] = [{"adresse": "Verein@Example.com", "name": "Vorstand"}]
    daten = klient.post("/api/konten", json=eingabe).json()
    assert daten["aliase"] == [{"adresse": "verein@example.com", "name": "Vorstand"}]


def test_ohne_das_feld_bleiben_die_aliasse_stehen(klient, ohne_netz):
    """⚠️ **Nicht mitgeschickt heißt unverändert** — dieselbe Regel wie beim
    Passwort und bei den Schlagworten. Sonst verlöre jeder seine Zweitadressen,
    der nur den Anzeigenamen ändert."""
    einrichten(klient)
    eingabe = _eingabe()
    eingabe["aliase"] = [{"adresse": "verein@example.com", "name": ""}]
    konto_id = klient.post("/api/konten", json=eingabe).json()["id"]

    ohne = _eingabe()
    ohne["anzeigename"] = "Neuer Name"
    daten = klient.put(f"/api/konten/{konto_id}", json=ohne).json()
    assert daten["anzeigename"] == "Neuer Name"
    assert [a["adresse"] for a in daten["aliase"]] == ["verein@example.com"]


def test_eine_leere_liste_raeumt_sie_weg(klient, ohne_netz):
    """Eine leere Liste heißt ausdrücklich „alle weg" — anders als gar keine."""
    einrichten(klient)
    eingabe = _eingabe()
    eingabe["aliase"] = [{"adresse": "verein@example.com", "name": ""}]
    konto_id = klient.post("/api/konten", json=eingabe).json()["id"]

    leer = _eingabe()
    leer["aliase"] = []
    assert klient.put(f"/api/konten/{konto_id}", json=leer).json()["aliase"] == []


def test_eine_kaputte_aliasadresse_wird_benannt(klient, ohne_netz):
    """⚠️ Eine Kennung, kein deutscher Satz — die Oberfläche übersetzt."""
    einrichten(klient)
    eingabe = _eingabe()
    eingabe["aliase"] = [{"adresse": "ohne-at", "name": ""}]
    antwort = klient.post("/api/konten", json=eingabe)
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "alias_adresse_ungueltig"
