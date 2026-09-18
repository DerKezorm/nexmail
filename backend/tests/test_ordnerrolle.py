"""Die Rolle eines Ordners: erkannt, oder von Hand zugewiesen.

⚠️ **Gemeldet am 18.09.2026:** „Archive" und „Delete" taten bei mehreren
IMAP-Postfächern nichts. Der Server führte kein SPECIAL-USE, seine Ordner
standen nicht auf der Namensliste, und zuweisen ließ sich die Rolle nirgends.

⚠️ **Der teuerste Fehler hier ist der stille Rückfall.** Eine Zuweisung, die
das nächste Ordnerlesen nicht übersteht, sieht einen Tag lang richtig aus:
bis jemand einen Ordner anlegt, und „Löschen" wieder ins Leere geht.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from conftest import anmelden, zweiten_benutzer_anlegen

from app.models import Ordner
from app.services import imap as imapdienst
from app.services import konten as kontendienst
from app.services import ordner as ordnerdienst
from test_abgleich import konto  # noqa: F401 - Fixture


def _angabe(pfad: str, rolle: str = "eigen", waehlbar: bool = True) -> imapdienst.Ordnerangabe:
    return imapdienst.Ordnerangabe(
        pfad=pfad, name=pfad.split("/")[-1], rolle=rolle, waehlbar=waehlbar,
        kennzeichen=["abonniert"],
    )


#: Ein Server ohne SPECIAL-USE, mit Namen, die keine Liste kennt.
KARG = [
    _angabe("INBOX", "posteingang"),
    _angabe("Ablage"),
    _angabe("Weg damit"),
    _angabe("Rechnungen"),
]


def _lesen(db, konto, angaben):  # noqa: F811
    kontendienst.ordner_uebernehmen(db, konto, angaben)
    db.refresh(konto)
    return {o.pfad: o for o in konto.ordner}


def _rollen(konto) -> dict[str, str]:  # noqa: F811
    return {o.pfad: o.rolle for o in konto.ordner}


# --- Die Erkennung -------------------------------------------------------- #


@pytest.mark.parametrize(
    "pfad,rolle",
    [
        ("Deleted", "papierkorb"),
        ("Gelöschte Elemente", "papierkorb"),
        ("INBOX.Gelöscht", "papierkorb"),
        ("Spamverdacht", "junk"),
        ("Gesendete Elemente", "gesendet"),
        # ⚠️ Was sich ein Mensch für seine Ablage ausdenkt, bleibt draußen:
        # Die Liste entscheidet, was das Aufräumen endgültig leert.
        ("Bin", "eigen"),
        ("Alt", "eigen"),
        ("Archiv 2024", "eigen"),
        # Und weiterhin nur auf oberster Ebene. ⚠️ Beide Richtungen: Mit nur
        # der ersten lief die Mutation „gilt in jeder Tiefe" durch, denn sie
        # liest dann das ERSTE Segment, und „Ablage" steht auf keiner Liste.
        ("Ablage/Deleted", "eigen"),
        ("Deleted/Ablage", "eigen"),
    ],
)
def test_die_namensliste(pfad, rolle):
    assert imapdienst._rolle_bestimmen(pfad, []) == rolle


# --- Zuweisen ------------------------------------------------------------- #


def test_eine_zuweisung_gilt_sofort(db, konto):  # noqa: F811
    ordner = _lesen(db, konto, KARG)
    assert "papierkorb" not in _rollen(konto).values()

    ordnerdienst.rolle_zuweisen(db, konto, ordner["Weg damit"], "papierkorb")

    assert _rollen(konto)["Weg damit"] == "papierkorb"
    assert ordner["Weg damit"].rolle_von_hand == "papierkorb"


def test_die_zuweisung_uebersteht_das_ordnerlesen(db, konto):  # noqa: F811
    """⚠️ Der stille Rückfall. ``ordner_uebernehmen`` läuft nach jedem
    Anlegen, Umbenennen und Entfernen eines Ordners, und bis zum 18.09.2026
    schrieb es die erkannte Rolle wörtlich über die geltende."""
    ordner = _lesen(db, konto, KARG)
    ordnerdienst.rolle_zuweisen(db, konto, ordner["Weg damit"], "papierkorb")

    _lesen(db, konto, [*KARG, _angabe("Neu angelegt")])

    assert _rollen(konto)["Weg damit"] == "papierkorb"
    assert _rollen(konto)["Neu angelegt"] == "eigen"


def test_von_hand_schlaegt_erkannt_im_ganzen_postfach(db, konto):  # noqa: F811
    """⚠️ Sonst gäbe es zwei Papierkörbe, und welcher gilt, entschiede die
    Reihenfolge in der Datenbank. Das Aufräumen leerte beide."""
    ordner = _lesen(db, konto, [*KARG, _angabe("Trash", "papierkorb")])
    assert _rollen(konto)["Trash"] == "papierkorb"

    ordnerdienst.rolle_zuweisen(db, konto, ordner["Weg damit"], "papierkorb")

    rollen = _rollen(konto)
    assert rollen["Weg damit"] == "papierkorb"
    assert rollen["Trash"] == "eigen"
    assert [p for p, r in rollen.items() if r == "papierkorb"] == ["Weg damit"]

    # Und das bleibt so, wenn die Ordnerliste neu gelesen wird.
    _lesen(db, konto, [*KARG, _angabe("Trash", "papierkorb")])
    assert _rollen(konto)["Trash"] == "eigen"


def test_faellt_die_zuweisung_kommt_der_erkannte_zurueck(db, konto):  # noqa: F811
    """Ohne Abruf beim Server: Was er gesagt hat, steht in ``rolle_erkannt``."""
    ordner = _lesen(db, konto, [*KARG, _angabe("Trash", "papierkorb")])
    ordnerdienst.rolle_zuweisen(db, konto, ordner["Weg damit"], "papierkorb")

    ordnerdienst.rolle_zuweisen(db, konto, ordner["Weg damit"], "")

    rollen = _rollen(konto)
    assert rollen["Weg damit"] == "eigen"
    assert rollen["Trash"] == "papierkorb"
    assert ordner["Weg damit"].rolle_von_hand == ""


def test_je_rolle_nur_eine_zuweisung_von_hand(db, konto):  # noqa: F811
    """Wer einen zweiten Ordner zum Archiv macht, meint „der statt dem"."""
    ordner = _lesen(db, konto, KARG)
    ordnerdienst.rolle_zuweisen(db, konto, ordner["Ablage"], "archiv")
    ordnerdienst.rolle_zuweisen(db, konto, ordner["Rechnungen"], "archiv")

    rollen = _rollen(konto)
    assert rollen["Rechnungen"] == "archiv"
    assert rollen["Ablage"] == "eigen"
    assert ordner["Ablage"].rolle_von_hand == ""


def test_gewoehnlicher_ordner_ist_eine_echte_zuweisung(db, konto):  # noqa: F811
    """⚠️ „Das ist KEIN Junk", auch wenn der Ordner so heißt. Ohne das leerte
    das Aufräumen eine Ablage, die zufällig „Spam" heißt, und niemand könnte es
    abstellen."""
    ordner = _lesen(db, konto, [*KARG, _angabe("Spam", "junk")])
    ordnerdienst.rolle_zuweisen(db, konto, ordner["Spam"], "eigen")
    assert _rollen(konto)["Spam"] == "eigen"

    _lesen(db, konto, [*KARG, _angabe("Spam", "junk")])
    assert _rollen(konto)["Spam"] == "eigen"


def test_der_bestand_von_vor_der_spalte_behaelt_seine_rollen(db, konto):  # noqa: F811
    """Nach dem Update steht ``rolle_erkannt`` überall leer. Eine Zuweisung
    darf dann nicht alle anderen Rollen des Postfachs mitnehmen."""
    for pfad, rolle in (("Archive", "archiv"), ("Trash", "papierkorb"), ("Ablage", "eigen")):
        db.add(Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle=rolle))
    db.commit()
    db.refresh(konto)
    ordner = {o.pfad: o for o in konto.ordner}
    assert all(o.rolle_erkannt == "" for o in ordner.values())

    ordnerdienst.rolle_zuweisen(db, konto, ordner["Ablage"], "papierkorb")
    ordnerdienst.rolle_zuweisen(db, konto, ordner["Ablage"], "")

    assert _rollen(konto) == {
        "INBOX": "posteingang", "Archive": "archiv", "Trash": "papierkorb", "Ablage": "eigen",
    }


# --- Was nicht geht ------------------------------------------------------- #


def test_der_posteingang_bleibt_der_posteingang(db, konto):  # noqa: F811
    ordner = _lesen(db, konto, KARG)
    with pytest.raises(ordnerdienst.OrdnerFehler, match="ordner_rolle_posteingang"):
        ordnerdienst.rolle_zuweisen(db, konto, ordner["INBOX"], "papierkorb")
    with pytest.raises(ordnerdienst.OrdnerFehler, match="ordner_rolle_unbekannt"):
        ordnerdienst.rolle_zuweisen(db, konto, ordner["Ablage"], "posteingang")
    assert _rollen(konto)["INBOX"] == "posteingang"


def test_ein_zwischenknoten_wird_kein_papierkorb(db, konto):  # noqa: F811
    ordner = _lesen(db, konto, [*KARG, _angabe("Nur Huelle", waehlbar=False)])
    with pytest.raises(ordnerdienst.OrdnerFehler, match="ordner_rolle_nicht_waehlbar"):
        ordnerdienst.rolle_zuweisen(db, konto, ordner["Nur Huelle"], "papierkorb")


def test_die_wiedervorlage_wird_kein_papierkorb(db, konto):  # noqa: F811
    """⚠️ Was dort liegt, hat ein Mensch bewusst weggelegt; das Aufräumen
    leerte es endgültig."""
    from app.services.wiedervorlage import ORDNER_NAME

    ordner = _lesen(db, konto, [*KARG, _angabe(ORDNER_NAME)])
    for rolle in ("papierkorb", "junk"):
        with pytest.raises(ordnerdienst.OrdnerFehler, match="ordner_rolle_wiedervorlage"):
            ordnerdienst.rolle_zuweisen(db, konto, ordner[ORDNER_NAME], rolle)


# --- Über die Adresse ------------------------------------------------------ #


def test_die_adresse_gibt_den_ganzen_baum_zurueck(klient, db, konto):  # noqa: F811
    """⚠️ Eine Zuweisung ändert bis zu drei Zeilen. Wer nur eine zurückgibt,
    lässt die Oberfläche zwei Papierkörbe zeigen."""
    ordner = _lesen(db, konto, [*KARG, _angabe("Trash", "papierkorb")])

    antwort = klient.put(
        f"/api/konten/{konto.id}/ordner/{ordner['Weg damit'].id}/rolle",
        json={"rolle": "papierkorb"},
    )
    assert antwort.status_code == 200, antwort.text
    baum = {o["pfad"]: o for o in antwort.json()}
    assert baum["Weg damit"]["rolle"] == "papierkorb"
    assert baum["Weg damit"]["rolle_von_hand"] == "papierkorb"
    assert baum["Trash"]["rolle"] == "eigen"
    assert baum["Trash"]["rolle_von_hand"] == ""

    # ⚠️ **Noch einmal, in einer eigenen Anfrage.** Die Antwort oben entsteht
    # in derselben Sitzung wie die Zuweisung und sieht sie auch dann, wenn sie
    # nie festgeschrieben wurde; genau diese Mutation lief zuerst durch.
    spaeter = {o["pfad"]: o for o in klient.get(f"/api/konten/{konto.id}/ordner").json()}
    assert spaeter["Weg damit"]["rolle"] == "papierkorb"
    assert spaeter["Trash"]["rolle"] == "eigen"

    antwort = klient.put(
        f"/api/konten/{konto.id}/ordner/{ordner['INBOX'].id}/rolle", json={"rolle": "archiv"}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "ordner_rolle_posteingang"


def test_ein_fremder_weist_nichts_zu(klient, zweiter_klient, db, konto):  # noqa: F811
    ordner = _lesen(db, konto, KARG)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.put(
        f"/api/konten/{konto.id}/ordner/{ordner['Ablage'].id}/rolle", json={"rolle": "papierkorb"}
    )
    assert antwort.status_code == 404
    db.refresh(ordner["Ablage"])
    assert ordner["Ablage"].rolle == "eigen"


# --- Der Vertrag mit der Oberfläche ---------------------------------------- #


def test_das_menue_bietet_an_was_der_server_annimmt():
    """Laufen die Listen auseinander, führt ein Menüpunkt in eine Absage, oder
    eine Rolle lässt sich nirgends wählen."""
    datei = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "lib" / "ordnerrollen.ts"
    )
    block = re.search(r"ZUWEISBARE_ROLLEN = \[(.*?)\]", datei.read_text(encoding="utf-8"), re.S)
    assert block, "Die Liste in ordnerrollen.ts wurde nicht gefunden."
    oberflaeche = re.findall(r"'([a-z]+)'", block.group(1))
    assert len(oberflaeche) >= 5, "Die Liste ist verdächtig kurz; liest der Test noch richtig?"
    assert sorted(oberflaeche) == sorted(kontendienst.ZUWEISBARE_ROLLEN)
