# Anbindung des Kontenmoduls (`nexkonten`) an nexmail

Stand 24.11.2026, Zweig `konten`. **Gebaut** mit `konten` 0.2.1 und `oidc` 1.1.0 (Abschnitt 0), Teil 2 mit `konten` 0.3.1 und `post` 0.1.1 (Abschnitt 0b); die Abschnitte
ab 1 sind der Plan der Vorbereitung (gegen `konten` 0.1.0) und bleiben als Begründung stehen. Maßgeblich sind der
Entwurf in nexlore (`Development/nexapps/Baupläne/Entwurf Konten, Einrichtung und Anmeldung.md`, Tabelle
„Entscheidungen“) und die Schnittstelle des Moduls (`bauplaene/konten/SCHNITTSTELLE.md`).

## 0. Was gebaut ist

| Teil | Wo |
|---|---|
| Module | `backend/app/vendor/nexkonten` (0.2.1), `backend/app/vendor/nexoidc` (1.1.0), Wortlaute und `konten.ts` unter `frontend/src/vendor/nexkonten`; kopiert mit `bauplaene/{konten,oidc}/tools/sync.py copy` |
| Store | `services/konten_store.py` über `benutzer`, `einladung`, `ruecksetzung`, `adresswechsel`, `frueherer_name`, `einrichtung`, `sitzung`, `api_schluessel` |
| Wanderung | neue Spalten mit Tabellenvorgabe (`kontaktadresse_zaehlt` 1, `kontaktadresse_bewiesen` 0, `kontaktadresse_herkunft`, `profilbild_herkunft`, `sprache`, `neues_passwort` leer, `ruecksetzung.herkunft` `self`, `ruecksetzung.angelegt_von`, `einladung.gemailt` 1), neue Tabellen (Sicherung davor, weil Tabellen fehlen); der Index auf `lower(benutzername)` erst nach dem Zählen (`services/konten_wanderung.py`). Das Einspielen einer Sicherung läuft danach durch dieselbe Schemapflege |
| Mails | `services/kontenpost.py` (Einladung, Link für ein neues Passwort, Adresse bestätigen, neuer Benutzername, Bescheid an die alte Adresse), Deutsch oder Englisch nach der Sprache des Kontos |
| Notfallbefehl | `python -m app.notfall reset-link <name oder e-mail> [--tage 1/7/30]` |
| Routen | gleiche Feldnamen; neu: `GET /api/auth/kennwort-vergessen`, `GET /api/auth/kennwort-neu/{schluessel}`, `GET/POST /api/auth/adresse/{schluessel}`, `PUT /api/auth/ich/benutzername`, `PUT /api/auth/ich/sprache`, `POST /api/auth/ich/kontaktadresse/nochmal`, `DELETE /api/auth/ich/kontaktadresse/wartend`, `GET /api/auth/zugaenge`, `POST /api/auth/zugaenge/trennen` und `/gesehen`, `PUT /api/benutzer/{id}/benutzername` und `/anzeigename`, `POST /api/benutzer/{id}/passwort-link` und `/kontaktadresse-entfernen` |
| Oberfläche | Anmelden, Einrichtung, Einladung, Passwort vergessen und neu, Adresse bestätigen (neu, `pages/AdressePage.tsx`), Profil, Benutzerverwaltung, „Diese Geräte haben noch Zugriff“ nach der Anmeldung (`components/NeuesPasswort.tsx`); „Passwort“ statt „Kennwort“ in allen Texten |
| Tests | Vertrag `tests/nexkonten` (149, 10 übersprungen, s. unten), `tests/nexoidc`, `tests/test_konten_routen.py`, Test „Bestand“ ohne `xfail` |

**Geprüft am 24.11.2026:** Backend voll einmal (`pytest`, ohne xdist: 2935 bestanden, 14 übersprungen, 6 rot, alle
sechs danach behoben und ihre Dateien erneut grün), Vertrag `tests/nexkonten` 149 grün und 10 übersprungen, Test
„Bestand“ 55 grün und gegen vier Mutationen am neuen Code geprüft (Rückgabecode 1, ohne Mutation 0), Frontend
`npx vitest run --maxWorkers=2` 259 grün, `npm run build` grün samt `tools/gewicht-pruefen.mjs`. `npm run lint` läuft in
nexmail nicht: Es gibt weder `eslint` in den Abhängigkeiten noch eine Konfiguration (schon auf `main` so). Kein
Playwright, keine Server; die Oberflächentests unter `frontend/tests` suchen noch alte Beschriftungen.

**Wo das Modul nicht passte** (mit Vorschlag an `bauplaene/konten`):

1. **Vertragstests setzen Dinge voraus, die nexmail nicht hat:** gesperrte Konten (6 Tests), ein verlangter zweiter
   Faktor (2), die Kennung eines bekannten Browsers (1), mehrfach nutzbare Einladungen (1). Der Adapter überspringt
   sie mit Grund (`pytest.skip` in `seed`, `open_session`, `make_invite`). Vorschlag: Fähigkeiten im Adapter
   (`blocking = False`, `required_second_factor = False`, `reusable_invites = False`), die der Vertrag selbst abfragt.
2. **Vitest-Vorlage `nexkonten.test.ts`:** fragt Pluralschlüssel (`account.days_one`) direkt ab und bekommt das rohe
   `{{count}}`. In nexmail angepasst wie in `nexoidc.wording.test.ts` (ohne Endung, mit passender Zahl). Vorschlag:
   so in die Vorlage.
3. **Bremse ohne Absender:** nexmail kennt den Absender nur mit `NEXMAIL_CLIENT_IP`. Ein Topf `sender:` für alle
   würde jeden alle aussperren lassen; der Absendertopf zählt deshalb nur mit bekannter Adresse
   (`anmeldebremse.torwaechter`), der Kontotopf immer. Vorschlag: in `SCHNITTSTELLE.md` sagen, dass ein leerer
   Absender keinen gemeinsamen Topf ergeben darf.
4. **Protokollzensur:** nexmail schwärzt im Protokoll das Wort nach „password“/„token“. Zeilen des Moduls wie
   „Password link made name=…“ oder „give NEXMAIL_SETUP_TOKEN as the setup code“ erscheinen als
   „Password ***** made …“ bzw. „…TOKEN ***** the setup code“. Vorschlag: Wortlaute ohne diese Wörter direkt vor
   einem Wert („Link for a new password made …“, „set NEXMAIL_SETUP_TOKEN, then …“).
5. **`use_reset` gibt `remaining` in der Antwort**, `POST /api/auth/kennwort-neu` antwortet aber seit jeher 204 ohne
   Rumpf (Bestand). nexmail merkt sich darum die Herkunft am Konto (`neues_passwort`) und zeigt die Liste nach der
   nächsten Anmeldung, wo „Alle trennen“ ohnehin eine Anmeldung braucht. Vorschlag: das als den gemeinsamen Weg
   beschreiben.
6. **Frische Anmeldung beim Anbieter** (Konten ohne Passwort ändern ihre Adresse, Betreiber ohne Passwort): Das Modul
   lässt offen, was „frisch“ ist; nexmail nimmt eine Sitzung, die höchstens fünf Minuten alt ist (`auth._frisch`).
   Vorschlag: eine Zahl für alle Apps festlegen.

Grundsatz für nexmail: **Für niemanden, der nexmail heute benutzt, ändert sich etwas, das er nicht selbst anstößt.**
Jede heutige Anmeldung geht weiter (Test „Bestand“), die Schnittstellen behalten ihre Feldnamen, und die Oberfläche
ändert sich nur, wo ein neues Feld dazukommt.

## 0b. Teil 2 (`konten` 0.3.1, `post` 0.1.1)

Gebaut am 24.11.2026 auf demselben Zweig. Maßgeblich ist der Abschnitt „Teil 2“ des Entwurfs in nexlore.

| Teil | Wo |
|---|---|
| Module | `backend/app/vendor/nexkonten` 0.3.1, neu `backend/app/vendor/nexpost` 0.1.1 (Mailmodul), Wortlaute unter `frontend/src/vendor/{nexkonten,nexpost}`; `requirements.txt` um `webauthn` und `cbor2` |
| Store | `services/konten_store.py` jetzt auch `FactorStore`, `PasskeyStore`, `SessionStore`, `PictureStore`; `services/post_store.py` für das Mailmodul über die bisherigen Einstellungen `system_smtp_*` (die Seite und `systempost.schreiben` bleiben, das Modul liest dieselben Werte) und die Tabelle `post_ausgang` |
| Wanderung | `benutzer.passkey_handle`, `geraete_schluessel`, `mail_neue_anmeldung` (1), `fehlversuche`, `gesperrt_bis`; `sitzung.merken` (1: bestehende Sitzungen bleiben gemerkt und gleiten wie bisher), `stufe` (`full`), `anbieter_geprueft`; Tabellen `passkey`, `post_ausgang`. Beim Start fallen halbe Sitzungen (`bestaetigt = 0`) weg (`konten_wanderung.halbe_sitzungen_verwerfen`) |
| Zweiter Faktor | Geheimnis und Wiederherstellungscodes bleiben, wo und wie sie waren (versiegelt, Kontext `benutzer:<id>:totp`); das Modul liest sie über den Store. Die Codeabfrage beim Anmelden bleibt nexmails eigene (`/api/auth/code`, `/wiederherstellung`), `NEXMAIL_ZWEI_FAKTOR_AUS` gilt weiter und schlägt auch „für alle verlangen“ |
| Schalter des Betreibers | Verwaltung → Anmeldung: „Zweiten Faktor für alle verlangen“ (ab Werk aus; wer keinen hat, richtet ihn bei der nächsten Anmeldung ein, auch nach einem Anbieter: Schritt `einrichten`) und „Passkeys erlaubt“ (ab Werk an) über `PUT /api/oidc/admin/anmeldung` |
| Zurücksetzen | `POST /api/benutzer/{id}/zweiter-faktor-zuruecksetzen` (Passwort des Betreibers, `geraete_trennen` ab Werk an), Knopf in der Benutzerverwaltung |
| Passkeys | `routers/passkeys.py`: `GET /api/auth/passkey`, `POST /api/auth/passkey/start`, `POST /api/auth/passkey` (anmelden, ohne Code), `GET/POST /api/auth/passkeys`, `POST /api/auth/passkeys/start`, `POST /api/auth/passkeys/{uid}/entfernen`; nur mit https-Adresse (oder localhost). Oberfläche: Knopf „Mit Passkey anmelden“, Abschnitt Passkeys unter Sicherheit (`lib/passkey.ts` wandelt von Hand, ältere Browser haben `parseCreationOptionsFromJSON` nicht) |
| Sitzungen | „Angemeldet bleiben“ beim Anmelden (ab Werk an: 30 Tage gleitend, Cookie 400 Tage; aus: Sitzungscookie, höchstens 12 Stunden). Die Liste „Angemeldete Geräte“ und „Auf allen Geräten abmelden“ gab es schon; sie beenden Browser und gekoppelte iPhones, API-Schlüssel bleiben |
| Bekannter Browser | Cookie `nexmail_bekannt` mit bis zu fünf signierten Marken über `benutzer.geraete_schluessel` (neues Passwort: neuer Schlüssel). Ein bekannter Browser ist von der Kontosperre ausgenommen und zählt an der Bremse in einem eigenen Topf. `GET /api/auth/ich` gibt einem Browser von vor dem Update still eine Marke |
| Kontosperre | 10 Fehlversuche, 15 Minuten (`konten_store.SPERRE_NACH`, `SPERRE_MINUTEN`), Antwort wie bei einem falschen Passwort; ein neues Passwort hebt sie auf |
| Mails | alle Systemmails über `nexpost` (Logo, Text und HTML, Sprache des Kontos, sonst des Betreibers, sonst Englisch) in die Outbox, erster Versuch sofort, weitere nach 1, 5, 15, 60, 180 Minuten im Takt (`takt._pushschleife`). Einladungen gehen sofort und ohne Outbox (scheitert die Mail, gibt es die Einladung nicht). Neu: „Neue Anmeldung“ für einen unbekannten Browser, im Profil unter Sicherheit abschaltbar (`PUT /api/auth/ich/neue-anmeldung`). Verwaltung → Postausgang zeigt den letzten Versand, den letzten Fehler und was noch wartet. Unverschlüsselt erlaubt, mit Warnung |
| Profilbilder | sehen alle angemeldeten Konten (vorher nur das Konto selbst und der Betreiber), nie Abgemeldete; ohne Bild ein Buchstabe auf einer Farbe aus dem Namen (`avatarPlaceholder`) statt zweier Initialen |
| 429 | `too_many_attempts` des Moduls kommt als nexmails `zu_viele_versuche` mit `Retry-After` |

**Test „Bestand“, Teil 2** (`tests/test_bestand.py`, Ende): das Geheimnis von 0.33.0 ist das Geheimnis des Moduls,
Browser-Sitzungen von 0.33.0 sind gemerkt und voll, eine halbe Anmeldung von 0.33.0 fällt beim Start weg, ein
Profilbild von 0.33.0 zeigt sich (jetzt jedem Angemeldeten), die Postausgang-Einstellungen von 0.33.0 sind die des
Mailmoduls, der Betreiber setzt Monas Faktor zurück und ihr gekoppeltes iPhone ist getrennt. Die Zeilen für Bild und
halbe Sitzung schreibt der Test vor dem Start in die Spalten von 0.33.0 (die Vorlage hat keine).

**Geprüft am 25.11.2026:** Backend voll einmal ohne xdist (`pytest -q`: 3022 bestanden, 16 übersprungen, 1 rot:
`test_waechter` kannte die öffentlichen Passkey-Wege noch nicht, eingetragen und mit `test_passkeys` erneut grün; im
Lauf davor fehlten `webauthn` und `cbor2` in `THIRD-PARTY.md`, nachgetragen), Vertrag `tests/nexkonten` 184 grün und
12 übersprungen, `tests/nexpost` grün, Test „Bestand“ 62 grün, Frontend `npx vitest run --maxWorkers=2` 266 grün,
`npx tsc -b`, `npm run lint` und `npm run build` grün. Kein Playwright, keine Server.

**Noch nicht gebaut:** Ein Konto mit Passkey und ohne Authenticator-App muss bei „für alle verlangen“ nach dem
Passwort trotzdem die App einrichten (nexmails Codeabfrage kennt den Passkey als zweiten Schritt nicht; mit dem
Passkey allein meldet es sich ohne Passwort an). Nach dem Einrichten beim Anmelden gibt es keine
Wiederherstellungscodes, bis man sie unter Sicherheit neu macht (wie vor dem Modul).

**Wo das Modul nicht passte (Teil 2):**

7. **Hinweis am Benutzernamen** („Du kannst ihn später im Profil ändern“) steht im Profil selbst falsch. nexmail
   nimmt dort einen eigenen Satz (`profil.benutzername_hinweis`: „Damit meldest du dich an.“). Vorschlag: ein
   zweiter Wortlaut `account.usernameHintProfile` im Modul.
8. **`sessions.current` und eigene Sitzungen:** nexmail behält seine Sitzungsschicht (`services/sitzung.py`), weil
   Gerätetoken und Browser in derselben Tabelle liegen und die iPhone-App daran hängt; das Modul liefert Laufzeiten,
   Marken und die Mail. Vorschlag: in `SCHNITTSTELLE.md` sagen, welche Teile eine App mit eigener Sitzungsschicht
   mindestens nehmen muss.

## 1. Bestand heute (0.33.0)

### Datenmodell

| Tabelle | Was zum Konto gehört |
|---|---|
| `benutzer` | `id` (32 Hex, Primärschlüssel, an ihm hängt alles), `nummer` (ganze Zahl für `nexoidc`), `benutzername` (String 64, `unique=True`, **aber Groß/Klein-empfindlich** in der DB), `anzeigename` (120, beim Anlegen leer → Kopie des Benutzernamens), `passwort_hash` (Argon2id, leer = nur Anbieter), `ist_betreiber` (genau einer), `kontaktadresse` (320, leer = kein Weg zurück, **nicht eindeutig**), `totp_*`, `profilbild`, `profilbild_am` |
| `einladung` | `schluessel_hash`, `benutzername` (vom Betreiber vorgegeben), `anzeigename`, `adresse` (Pflicht), `laeuft_ab` (7 Tage), `eingeloest` |
| `ruecksetzung` | Link „Passwort vergessen“: `schluessel_hash`, `benutzer_id`, `laeuft_ab` (2 Stunden), `eingeloest` |
| `sitzung` | Browser **und** iPhone (`art = geraet`, Token `nxa_…`), am `benutzer_id`; Push-Ticket des Relays an der Sitzung |
| `wiederherstellungscode`, `app_kopplung`, `push_anmeldung`, `api_schluessel` | alle am `benutzer_id` |
| `oidc_anbieter`, `oidc_verknuepfung` | Verknüpfung `(anbieter_id, subject)` → `benutzer_id`; `email` nur Anzeige |

Es gibt **keinen Zustand „gesperrt“**. `oidc_store.account_state` meldet `blocked=False`. Was ein Konto heute aussperrt,
ist nur „Anmeldung mit Passwort aus“ (Verwaltung → Anmeldung, Einstellung `anmeldung_passwort`), und das gilt für
alle Mitglieder außer dem Betreiber.

### Dienste und Router

| Ort | Was |
|---|---|
| `routers/setup.py` | `GET /api/setup/status`, `POST /api/setup/konto` (`benutzername` ≥ 3, `passwort` ≥ 10, `anzeigename`), **ohne Code**; danach 404 |
| `routers/sicherung.py` | `POST /api/sicherung/pruefen-vor-einrichtung`, `/einspielen-vor-einrichtung`: vor der Einrichtung **ohne Anmeldung offen** |
| `routers/auth.py` | `/anmelden` (`benutzername`, `passwort`), `/code`, `/wiederherstellung`, `/kennwort-vergessen` (`benutzername`), `/kennwort-neu` (`schluessel`, `passwort`), `/passwort`, `/zwei-faktor/*`, `/ich`, `/ich/profil` (`anzeigename`, `kontaktadresse`), `/ich/kontaktadresse`, `/ich/profilbild` |
| `routers/einladung.py` | `GET/POST /api/einladung/{schluessel}` (Vorschau mit `benutzername`, Annahme mit `passwort`) |
| `routers/benutzer.py` | Betreiber: `GET /api/benutzer`, `POST /api/benutzer/einladungen` (`benutzername`, `adresse` Pflicht, `anzeigename`), Zurücknehmen, Betreiber übergeben, Entfernen, KI-Riegel |
| `routers/oidc.py` + `vendor/nexoidc` 1.0.14 | Anbieter, Verknüpfen, Einladung über Anbieter; Store `services/oidc_store.py`, Startabgleich `services/oidc_wanderung.py` |
| `services/benutzer.py` | `finden` (ohne Groß/Klein, `scalar_one_or_none`), `anlegen` (Muster `[A-Za-z0-9._-]{3,64}`, `MIN_LAENGE = 10`), `passwort_stimmt`, `entfernen` |
| `services/einladung.py`, `services/ruecksetzung.py`, `services/systempost.py` | Einladung, Rücksetz-Link, Systempostausgang |
| `services/anmeldebremse.py` | Bremse im Arbeitsspeicher, je Tür und **eingetippter** Kennung |

### Schema-Wanderung

`db.init_db()` bei jedem Start: fehlende Tabellen (`create_all`, davor Sicherung nach `data/sicherungen/` – **nur wenn
eine Tabelle fehlt**), fehlende Spalten per `ALTER TABLE … ADD COLUMN` mit der Vorgabe des Modells
(`_fehlende_spalten`, nur hinzufügen), fehlende Indizes (`_fehlende_indizes`, ohne Prüfung, ob sie anlegbar sind),
FTS, Änderungsauslöser, dann `oidc_wanderung.laufen`. Es gibt kein Alembic und keine Versionsnummer im Schema.

### Tests

`cd backend && .venv/Scripts/python.exe -m pytest` (pytest-xdist ist nicht installiert; bei wenig Rechenleistung
einzelne Dateien laufen lassen). Konten: `test_anmeldung.py`, `test_benutzer.py`, `test_ruecksetzung.py`, `test_profil.py`,
`test_betreiber_uebergeben.py`, `test_oidc_app.py`, `test_oidc_unterpfad.py`, Vertrag `tests/nexoidc/`, Wächter
`test_veroeffentlichung.py`. Frontend `cd frontend && npx vitest run --maxWorkers=2`, Oberfläche Playwright.

### iPhone-App und Push-Relay

`nexmail-ios` hat **kein eigenes Anmeldeformular** (geprüft): Sie koppelt per QR-Code, kurzem Code oder
`POST /api/app/1/devices` und spricht danach nur mit dem Geräteschlüssel. Sie speichert beim Koppeln
`account = anzeigename or benutzername` zur Anzeige (`APIClient.swift:8`, `Pairing.swift:55`) und frischt ihn nie
auf; erkannt wird die Verbindung über Adresse und Konto-ID (`SharedConnection.swift:29`). `benutzername` kommt im
Swift-Code nicht vor. Das Push-Relay bekommt nur Ticket und verschlüsselten Inhalt (`services/push.py:449`), keinen
Namen.

## 2. Wo der Benutzername mehr ist als Anzeige

Bewertung: **bricht** = Umbenennen oder Umbau würde etwas kaputt machen; **lösen** = vor dem Ändern-Knopf anfassen;
**harmlos** = nur Anzeige oder Protokoll.

| Stelle | Rolle des Namens | Bewertung |
|---|---|---|
| `models.py:107` `benutzer.benutzername unique=True` | eindeutig nur mit gleicher Schreibweise | **lösen**: `Anna` und `anna` könnten bei einem Wettlauf beide entstehen; dann wirft `finden` (`scalar_one_or_none`, `services/benutzer.py:118`) bei jeder Anmeldung einen 500. Eindeutiger Index auf `lower(benutzername)` (s. Wanderung) |
| `services/benutzer.py:44` Muster `[A-Za-z0-9._-]{3,64}`; `oidc_store.py:41` `NAME_MIN = 1` | Bestandsnamen mit Großbuchstaben, mit Punkt/Strich am Anfang, mit einem Zeichen (vom Anbieter) | **lösen**: gelten weiter (Regel 1), nur neue Namen nach `check_username`. Nie beim Start „bereinigen“ |
| `services/anmeldebremse.py` `torwaechter(..., kennung)` mit eingetippter Kennung: `auth.py:120` (anmelden), `auth.py:240` (vergessen) | Zähler je eingetipptem Text | **lösen**: Mit Benutzername **oder** E-Mail hätte jedes Konto zwei Zähler, also doppelt so viele Versuche. Nach dem Auflösen zusätzlich am Konto zählen (`konto:<id>`), ungelöste Eingaben weiter am Text |
| `auth.py:174, 199, 329, 427, 460`, `benutzer.py:247`, `oidc.py:312`, `ki.py:128, 177`, `nachrichten.py:711, 744`, `aufgabenziele.py:206, 302`, `nextime.py:171` | Bremse am `person.benutzername` | harmlos (Arbeitsspeicher; ein Umbenennen setzt nur den Zähler zurück). Beim Umbau auf die ID umstellen, dann ist auch das weg |
| `einladung.benutzername` (`models.py:1277`), `services/einladung.py:73-84, 125-130` | Name wird bei der Einladung reserviert, offene Einladung gleichen Namens ersetzt | **lösen**: neue Einladungen ohne Namen (Spalte bleibt, leer); offene alte behalten ihn (Regel 7). „Ersetzen“ künftig über die Adresse, wenn eine da ist |
| `oidc_store.py:329-339` `create_account(name, …)` | Name aus `preferred_username`, **nicht** aus der Einladung (Modul 1.0.14); Anzeigename aus der Einladung, leer → **Benutzername der Einladung** | harmlos, aber bekannt: Ein über den Anbieter Eingeladener heißt anders als eingeladen (Fixture: Einladung `robin` → Konto `Robin.SSO`; Einladung `jay` ohne Anzeigename → Konto `j` mit Anzeigename `jay`) |
| `oidc_store.py:310` `account_state.name`, `oidc.py:374` | Name fürs Modul, Logzeile | harmlos |
| `zwei_faktor.py:62` `provisioning_uri(name=benutzername)` | Beschriftung im Authenticator | harmlos: alte Einträge zeigen den alten Namen, Codes gelten weiter (Geheimnis am Konto, Kontext `benutzer:<id>:totp`) |
| `services/ruecksetzung.py:70` | Suche nach eingetipptem Namen | **lösen**: geht künftig über `nexkonten.forgot` (Name oder bestätigte, eindeutige Adresse) |
| `ruecksetzung.py:162, 176`, `einladung.py:115-130` | „Dein Benutzername: …“ in der Mail | harmlos (Zeitpunkt der Mail) |
| Sitzungen, Geräte (`sitzung.benutzer_id`), API-Schlüssel, Kopplung, Push, Profilbild-Adresse (`/api/auth/profilbild/{id}`), Verschlüsselungskontexte (`benutzer:<id>:…`), OIDC-Verknüpfung, Sicherung | alle an der ID | harmlos: **nichts** in nexmail hängt einen Pfad, eine Datei oder einen Schlüssel an den Namen. Es gibt kein CalDAV/CardDAV-Server-Pfad mit Namen (nexmail ist dort nur Client) |
| `api_v1.py:129` `username`, `app1.py:162-163`, `app_kopplung.py:196`, `/api/auth/ich`, `/api/benutzer` | Antwortfelder | harmlos, Feldnamen bleiben. Skripte, die `username` aus `/api/v1/me` lesen, sehen nach einer Änderung den neuen |
| iPhone `Connection.account` (`APIClient.swift:8`) | Anzeigename zum Zeitpunkt der Kopplung | harmlos; zeigt nach einer Änderung den alten Namen. Später in der App aus `/api/app/1/me` (`konto.name`) auffrischen |
| Protokoll: `oidc.py:120, 375, 478`, `suche.py:79`, `push.py:560`, `aufraeumen.py:138` | Name in Logzeilen | harmlos; alte Zeilen behalten den alten Namen. Neue Logzeile „Benutzername geändert“ nennt die ID, nicht beide Namen |
| `frontend/src/components/ZweiterFaktor.tsx:80, 86` | Dateiname der Wiederherstellungscodes | harmlos |
| `frontend/src/pages/Benutzerverwaltung.tsx:179, 313`, `EinladungPage.tsx:157` | Einladungszeile und Einladungsseite zeigen den vorgegebenen Namen | **lösen**: neue Einladungen haben keinen; Zeile zeigt Anzeigename, sonst Adresse, sonst „Einladungslink“ |

Ergebnis: **Ein Umbenennen bricht in nexmail nichts**, sobald der eindeutige Index ohne Groß/Klein steht und die
Bremse am Konto zählt. Es gibt keinen Fall wie den CalDAV-Pfad in nextime.

## 3. Zuordnung nexmail ↔ Modul

| Modul (`Account`, `NewAccount`) | nexmail |
|---|---|
| `id` (`AccountId`, hier `str`) | `benutzer.id` |
| `username` | `benutzername` (wie gespeichert, auch Bestandsnamen gegen die Regeln) |
| `display_name` | `anzeigename` |
| `email` | `kontaktadresse` |
| `email_confirmed` | neu `kontaktadresse_bestaetigt` |
| `email_source` | neu `kontaktadresse_herkunft` |
| `pending_email` | neue Tabelle `adresswechsel` (s. unten) |
| `has_password` | `passwort_hash != ''` |
| `blocked` | immer `False` (nexmail kennt keine Sperre; gelöscht ist gelöscht) |
| `operator` | `ist_betreiber` |
| `picture` | `profilbild` leer → `""`, sonst `profilbild_herkunft or "own"` |
| Einladung `Invite` | `einladung` (Rechte: keine, jeder ist Mitglied; `rights` leer) |
| Reset | `ruecksetzung` |

Der Store (`services/konten_store.py`, neu) bekommt eine Instanz je Anfrage wie `oidc_store.SqlStore`.
`check_password` nimmt `services/benutzer.passwort_stimmt` und rechnet bei `None` oder Konto ohne Passwort einen
Blindhash (heute antwortet `/anmelden` für einen unbekannten Namen schneller als für einen bekannten; mit E-Mail
würde das zur Adressliste). `set_password` nimmt `benutzer.hashen`; `end_sessions` nimmt `sitzung.alle_beenden`
(trifft Browser **und** Geräte, wie heute beim Zurücksetzen). Mails baut nexmail aus `Mail` selbst und schickt sie
über `systempost` (Texte wie heute in `services/einladung.py`/`ruecksetzung.py`, mit Link aus der öffentlichen
Adresse).

`nexoidc` 1.1.0 kommt im selben Zug: `SqlStore.clean_name` → `nexkonten.clean_username`, `name_taken` →
`nexkonten.username_taken`, `create_account(…, display_name, picture)` setzt den Anzeigenamen aus dem Claim, sonst aus
der Einladung, sonst **leer** (nicht mehr den Benutzernamen), `provider_picture` im Hintergrund.

## 4. Wanderung (nur ergänzend)

Alles in einem eigenen Schritt `services/konten_wanderung.py`, aufgerufen aus `init_db` nach den Spalten und vor
`oidc_wanderung`. **Davor eine Sicherung**, auch wenn keine Tabelle fehlt: `_sichern()` läuft heute nur bei fehlenden
Tabellen; die Wanderung ruft es selbst, wenn sie etwas zu tun hat (zweiter Start: still, keine Kopie).

| Neu | Typ, Vorgabe | Bedeutung der Vorgabe |
|---|---|---|
| `benutzer.kontaktadresse_bestaetigt` | Boolean, `server_default '1'` | Bestandsadressen gelten als bestätigt (Regel 2). Leere Adresse: Wert egal |
| `benutzer.kontaktadresse_herkunft` | String(16), `server_default ''` | alle heutigen Adressen sind eigene (aus Einladung oder Profil; nexmail übernimmt nie eine Adresse vom Anbieter) |
| `benutzer.profilbild_herkunft` | String(16), `server_default ''` | vorhandene Bilder gelten als eigene, werden nie vom Anbieter überschrieben |
| `ruecksetzung.angelegt_von` | String(32), nullable | `NULL` = selbst angefordert (alle heutigen) |
| Tabelle `adresswechsel` | `benutzer_id` (eindeutig), `adresse`, `schluessel_hash`, `laeuft_ab` | wartende Adresse mit Bestätigungslink; leer im Bestand |
| Index `uq_benutzer_name_klein` auf `lower(benutzername)`, eindeutig | | **nicht** über `_fehlende_indizes` (das legt ohne Prüfung an und risse den Start bei einem Doppel um): die Wanderung zählt erst `GROUP BY lower(benutzername) HAVING count(*) > 1`. Kein Doppel → Index anlegen. Doppel → Index weglassen, Warnung ins Log und ein Hinweis in der Kontenliste, Start geht weiter; beide melden sich weiter an, sobald `finden` bei mehreren Treffern den exakt geschriebenen nimmt |
| Index auf `lower(kontaktadresse)` | **nicht eindeutig** | Doppelte Adressen gibt es im Bestand (nexmail prüft heute nicht). Eindeutigkeit prüft das Modul (`email_taken`); ein eindeutiger Teilindex `WHERE kontaktadresse <> ''` ginge erst, wenn kein Doppel mehr da ist (offene Frage 4) |

Rückweg auf 0.33.0 eine Fassung lang: alle neuen Spalten haben eine Tabellenvorgabe, 0.33.0 legt also weiter Konten
an; die neue Tabelle stört sie nicht. Einschränkungen nach einem Rückweg: Einladungen der neuen Fassung (ohne Namen)
lassen sich mit 0.33.0 nicht annehmen (`benutzername_ungueltig`), Anmelden mit E-Mail geht dort nicht, wartende
Adressänderungen bleiben liegen. Geänderte Benutzernamen gelten auch in 0.33.0 (gleiche Spalte), solange sie ≥ 3
Zeichen haben; ein neuer Name mit 2 Zeichen wäre in 0.33.0 anmeldbar, aber nicht neu vergebbar.

## 5. Routen

**Feldnamen bleiben.** Neue Felder heißen nexmail-üblich deutsch. Antworten bekommen höchstens Felder dazu.

| Route | Heute | Künftig |
|---|---|---|
| `GET /api/setup/status` | `eingerichtet`, `zwei_faktor_aus` | dazu `code_noetig: true` (ohne Konto immer), `min_passwort: 12` |
| `POST /api/setup/konto` | `benutzername`, `passwort`, `anzeigename` | dazu `einrichtungscode` (Pflicht), `kontaktadresse` (frei), `anzeigename` Pflicht (Entwurf); `nexkonten.setup`. Beim Start ohne Konto `announce_setup` ins Log, Variable `NEXMAIL_SETUP_TOKEN` |
| `POST /api/sicherung/*-vor-einrichtung` | offen ohne Konto | **verlangt denselben Einrichtungscode** (Kopfzeile oder Formularfeld). Sonst wäre der Code wertlos: Wer eine fremde Sicherung einspielt, ist danach Betreiber |
| `POST /api/auth/anmelden` | `benutzername` | Feldname bleibt, Inhalt „Benutzername oder E-Mail“ → `nexkonten.authenticate`; Fehlertext `anmeldung_falsch` bleibt die Kennung, Wortlaut „Benutzername, E-Mail oder Passwort stimmt nicht.“. Die Sperre „Anmeldung mit Passwort aus“ bleibt **vor** der Passwortprüfung, gleiche Antwort |
| `POST /api/auth/kennwort-vergessen` | `benutzername` | Feldname bleibt, `nexkonten.forgot`; nur mit Systempostausgang, öffentlicher Adresse und Passwort-Anmeldung, sonst kommt nichts (Antwort immer 202). Link **eine Stunde** (heute zwei) |
| `POST /api/auth/kennwort-neu` | `schluessel`, `passwort` | bleibt, `nexkonten.use_reset`; neu gesetzte Passwörter ≥ 12. Offene Links der Vorfassung gelten (gleiche Tabelle, gleicher Hash) |
| `GET /api/auth/ich` | … `benutzername`, `anzeigename`, `kontaktadresse` | dazu `kontaktadresse_bestaetigt`, `kontaktadresse_wartet` |
| `PUT /api/auth/ich/profil` | `anzeigename`, `kontaktadresse` | bleibt; leerer Anzeigename bleibt **leer** (heute wird er zum Benutzernamen), Adresse über `change_email` (mit Postausgang: wartet auf den Link) |
| `PUT /api/auth/ich/kontaktadresse` | `adresse` | bleibt (ältere Oberflächen), gleiche Regeln |
| neu `PUT /api/auth/ich/benutzername` | – | `benutzername`, `passwort` (wenn das Konto eins hat) → `change_username` |
| neu `GET/POST /api/auth/adresse/{schluessel}` | – | Bestätigungslink für eine neue Adresse |
| `GET /api/einladung/{schluessel}` | `benutzername`, `anzeigename`, `passwort` | dazu `kontaktadresse`; `benutzername` = Vorschlag oder der Name der alten Einladung |
| `POST /api/einladung/{schluessel}` | `passwort` | dazu `anzeigename`, `benutzername`, `kontaktadresse` (alle frei; fehlt `benutzername`, gilt der Vorschlag bzw. der alte Name). Alte Oberfläche, die nur `passwort` schickt, geht weiter |
| `POST /api/benutzer/einladungen` | `benutzername`, `adresse` Pflicht, `anzeigename` | `benutzername` frei und **ignoriert** für neue Einladungen (Feld bleibt erlaubt, damit alte Skripte nicht mit 422 scheitern), `adresse` frei; ohne Adresse oder ohne Postausgang kommt der Link einmal in der Antwort (`link`) zum Kopieren |
| neu `PUT /api/benutzer/{id}/benutzername`, `PUT /api/benutzer/{id}/anzeigename` | – | Betreiber, mit eigenem Passwort |
| neu `POST /api/benutzer/{id}/passwort-link` | – | Betreiber, mit eigenem Passwort → `reset_link`; mit Postausgang und Adresse per Mail, sonst `link` einmal in der Antwort |
| neu `DELETE /api/benutzer/{id}/kontaktadresse` | – | Betreiber, nur entfernen |
| `GET /api/benutzer` | Zeilen mit `benutzername`, `anzeigename` | dazu `kontaktadresse`, `adresse_doppelt` (Hinweis), `hat_kennwort` |

## 6. Oberfläche

Vorgabe (24.11.2026): **Optisch ändert sich so wenig wie möglich.** Wo etwas dazukommt, sieht es in allen
Apps gleich aus, Vorbild nexnotes (`nexnotes/frontend/src/pages/AuthPages.tsx`, `pages/settings/AccountTab.tsx`):
Reihenfolge der Felder, Wortlaute, Hinweis unter dem Feld, Fehlerkasten über dem Formular. Gebaut wird **nur aus
vorhandenen nexmail-Bausteinen**: `Torbogen` (Rahmen der Anmeldeseiten), `Input` mit `label`/`hint`, `Button`,
`Meldung` (aus `EinrichtungPage.tsx`), `Select`, `Karte`, `Profilbild`, `Dialog`, `Badge`, `IconButton`,
`useNachfrage`. Kein neuer Baustein mit eigenem Aussehen.

| Bildschirm | Heute | Künftig | Bausteine | Sichtbar anders |
|---|---|---|---|---|
| **Anmelden** (`AnmeldePage.tsx`) | `Torbogen`, Feld „Benutzername“, „Passwort“, Knopf, „Passwort vergessen?“, Anbieterknöpfe | gleich | `Input` (`autoComplete="username"` bleibt) | nur die Beschriftung: „Benutzername oder E-Mail“; Fehlertext „Benutzername, E-Mail oder Passwort stimmt nicht.“ |
| **Einrichtung** (`EinrichtungPage.tsx`) | Benutzername, Angezeigter Name (frei), Passwort, Passwort wiederholen | Einrichtungscode (mit Hinweis auf `docker logs nexmail` / `NEXMAIL_SETUP_TOKEN`), Anzeigename, Benutzername (Vorschlag folgt dem Anzeigenamen, bis man ihn anfasst), E-Mail (frei), Passwort, Passwort wiederholen; Sprache wie heute aus dem Browser | dieselben `Input` und `Meldung` im selben `Torbogen`; der Vorschlag ist nur ein vorbelegter Wert, kein eigener Baustein | zwei Felder mehr (Code oben, E-Mail), Reihenfolge wie nexnotes, Hinweise in Entwurfs-Wortlaut, Mindestlänge 12 |
| **Einladung** (`EinladungPage.tsx`) | „Willkommen, {Name}“, „Vergib ein Passwort für den Benutzernamen {Name}“, Passwort zweimal, darunter Anbieter | Anzeigename (vorbelegt), Benutzername (Vorschlag oder der Name der alten Einladung), E-Mail (vorbelegt), Passwort zweimal, darunter „oder“ und die Anbieter wie heute | dieselben `Input`, `Button`, `Meldung` | drei Felder mehr; Untertitel ohne festen Namen. Alte Einladungen zeigen ihren Namen im Feld, nicht mehr im Satz |
| **Passwort vergessen** (`KennwortPage.tsx`) | Feld „Benutzername“, „Link anfordern“, Bestätigung „…zwei Stunden“ | Feld „Benutzername oder E-Mail“; ohne Postausgang statt des Formulars der Satz „Der Betreiber kann dir unter Konten einen Link erstellen …“; Seite zum Setzen unverändert | `Input`, `Button`, `Torbogen` | Beschriftung, Bestätigungssatz aus dem Entwurf („eine Stunde“ entfällt dort), Hinweis ohne Postausgang |
| **Profil** (`einstellungen/Profil.tsx`) | Karte „Profil“: Bild, Name, E-Mail (Hinweis „Adresse für Kontosachen“, Warnkasten ohne Adresse), Sprache (nur dieser Browser), Rolle | gleiche Karte: Bild, Anzeigename, **Benutzername** (Feld mit „Ändern“; Kennwortabfrage über `Dialog`, wie bei „Betreiber übergeben“), E-Mail (mit Postausgang: „wartet auf Bestätigung“ als `Badge` daneben, Knopf „Zurücknehmen“), Sprache, Rolle | `Karte`, `Profilbild`, `Input`, `Select`, `Badge`, `Dialog`, `Button` | Benutzername sichtbar und änderbar; Beschriftung „Anzeigename“ statt „Name“; Warnkasten bleibt |
| **Benutzerverwaltung** (`Benutzerverwaltung.tsx`) | Zeile: Anzeigename, darunter klein Benutzername; Einladen-Dialog mit Adresse (Pflicht), Benutzername (Pflicht), Angezeigter Name; Einladungszeile zeigt den Namen | Zeile: Anzeigename, darunter klein Benutzername · E-Mail, `Badge` „Adresse doppelt“ wo nötig; Menü der Zeile um „Benutzername ändern“, „Anzeigename ändern“, „Passwort-Link erstellen“, „Adresse entfernen“ (je `IconButton` + `Dialog` mit eigenem Passwort); Einladen-Dialog: E-Mail (frei), Anzeigename (frei), **kein** Benutzername; ohne Postausgang zeigt der Dialog danach den Link zum Kopieren; Einladungszeile zeigt Anzeigename oder Adresse, alte zeigen weiter ihren Namen | `Dialog`, `Input`, `IconButton`, `Badge`, `useNachfrage` | Benutzername-Feld im Einladen-Dialog fällt weg; neue Knöpfe in der Zeile; Link zum Kopieren |

Wortlaute: die Schlüssel `account.*` aus dem Entwurf kommen als eigener Namensraum in `de.json`/`en.json` (aus
`vendor/nexkonten`), die alten nexmail-Schlüssel (`anmeldung.benutzername`, `einrichtung.anzeigename`,
`sicherheit.kontaktadresse*`, `verwaltung.einladung_benutzername*`) fallen weg, sobald nichts mehr sie liest
(`schluessel-vorhanden.test.ts`). „Passwort“ oder „Passwort“: offene Frage 1.

Vor dem Festschreiben wird jede geänderte Ansicht gezeigt und abgenommen.

## 7. Passwort vergessen: beide Wege

- **Selbst per Mail** wie heute, aber mit Benutzername oder bestätigter, eindeutiger Adresse; Link eine Stunde, einmal,
  beendet alle Sitzungen und Geräte.
- **Betreiber-Link**: Benutzerverwaltung → Zeile → „Passwort-Link erstellen“, mit eigenem Passwort; mit Postausgang
  und Adresse per Mail, sonst einmal angezeigt zum Weitergeben, 24 Stunden. Der Betreiber setzt nie selbst ein
  Passwort. Für ein Konto nur über Anbieter (kein Passwort) erstellt der Link ein erstes Passwort; ob das gewollt ist:
  offene Frage 5.

## 8. Einrichtungscode

Nur auf einem Server ohne Konto (Regel 8): Beim Start steht der Code im Log (`announce_setup`), oder er kommt aus
`NEXMAIL_SETUP_TOKEN`. Eine laufende Installation fragt nie danach. README, `docker-compose.yml` (Kommentar zur
Variable) und die Hinweise der Einrichtungsseite werden nachgezogen. Der Code schützt auch das Einspielen einer
Sicherung vor der Einrichtung (Abschnitt 5).

## 9. Einladungen ohne Benutzernamen

Der Betreiber gibt keinen Namen mehr vor; der Eingeladene wählt ihn (Vorschlag aus dem Anzeigenamen). Offene alte
Einladungen behalten ihren Namen als Vorbelegung (Regel 7) – der Test „Bestand“ prüft das. Eine Einladung ohne
Adresse kann der Betreiber nur kopieren. Über den Anbieter angenommen entsteht der Name wie heute aus dem Anbieter
(`preferred_username`), nicht aus der Einladung.

## 10. Test „Bestand“

`backend/tests/test_bestand.py` mit der Fixture `backend/tests/bestand/bestand-0.33.0.sql.gz` (gebaut von 0.33.0 mit
`tests/bestand/bauen.py`, Beschreibung der Konten in `bestand-0.33.0.json`). Start:

    cd backend && .venv/Scripts/python.exe -m pytest tests/test_bestand.py -q

Konten: Betreiber mit Adresse und zweitem Faktor; `Erika.Muster` (Großbuchstaben, ohne Adresse, offene
Browsersitzung); `jonas` (Adresse, Postfach, API-Schlüssel); `kim`/`lou` (dieselbe Adresse in anderer Schreibweise,
Passwörter mit 10 und 11 Zeichen); `mona` (zweiter Faktor, gekoppeltes iPhone); `sam` (Passwort und Anbieter);
`Robin.SSO` und `j` (nur Anbieter, `j` mit einem Zeichen); eine offene Einladung `neu.gast`. Geprüft: Start ergänzt
nur (keine Spalte, keine Zeile verloren), Anmelden mit Benutzername in jeder Schreibweise, zweiter Faktor und
Wiederherstellungscode, kurze Passwörter, Anbieter, Sitzung, Gerät, API-Schlüssel, offene Einladung mit ihrem Namen,
Passwort vergessen per Benutzername, „Anmeldung mit Passwort aus“, Bremse. Anmelden und „vergessen“ mit eindeutiger
Adresse stehen als `xfail(strict=True)` da und werden mit der Anbindung grün (der Marker muss dann weg); doppelte
Adressen öffnen nie ein Konto. Gegen Mutationen geprüft (Rückgabecode 1): Vergleich mit Groß/Klein, Start löscht
offene Einladungen, Mindestlänge 12 beim Anmelden, Start löscht Verknüpfungen, Start beendet Sitzungen; eine
Anmeldung mit E-Mail lässt die strikten `xfail` rot werden.

Vor dem Aufspielen dieselbe Probe auf einer **Kopie** der Live-Datenbank (Regel 11): Doppelte Benutzernamen ohne
Groß/Klein und doppelte Adressen zählen, dann die neue Fassung gegen die Kopie starten.

## 11. Risiken

1. **Doppelte Namen ohne Groß/Klein** in einer Live-Datenbank: Der Index ließe sich nicht anlegen; heute würden diese
   Konten schon mit 500 scheitern. Die Wanderung darf deshalb nie am Index sterben (Abschnitt 4).
2. **Doppelte Kontaktadressen** sind erlaubt und wahrscheinlich (Familie mit einer Adresse). Sie öffnen nichts und
   bekommen keinen Link per Adresse; die Betroffenen merken nur, dass „mit E-Mail“ bei ihnen nicht geht.
3. **Bremse**: zählt sie weiter nur am eingetippten Text, verdoppelt das Anmeldefeld die Versuche je Konto.
4. **Zeitunterschied** zwischen bekanntem und unbekanntem Namen bzw. Adresse (heute kein Blindhash).
5. **Einrichtungscode ohne Sicherungsweg**: Lässt man `einspielen-vor-einrichtung` offen, ist der Code Zierde.
6. **Sicherung vor der Wanderung**: `init_db` sichert heute nur bei fehlenden Tabellen; Spalten und Indizes kämen ohne
   Kopie.
7. **Anzeigename = Benutzername** im Bestand (heute beim Anlegen kopiert): Wer seinen Benutzernamen ändert, sieht
   weiter den alten als Anzeigenamen (offene Frage 3).
8. **Rückweg** auf 0.33.0: neue Einladungen ohne Namen gehen dort nicht (Abschnitt 4).
9. **Oberflächentests** (Playwright) suchen Beschriftungen wie „Benutzername“ und „Angezeigter Name“; sie müssen mit
   den Wortlauten wandern, sonst laufen sie ins Leere.
10. **Mailtexte** von Einladung und Rücksetzen nennen heute den Benutzernamen fest; eine Einladung ohne Namen braucht
    einen neuen Text (nexmail-eigene Mailvorlage, deutsch; englische Fassung fehlt heute ganz).

## 12. Offene Fragen

1. **„Passwort“ oder „Passwort“?** nexmail sagt überall „Passwort“, der Entwurf und die anderen Apps „Passwort“. Für
   „alle Apps gleich“ müsste nexmail umstellen (viele Schlüssel, Mailtexte, README).
2. **Sprache bei Einrichtung und im Profil**: In nexmail gilt sie heute nur im Browser („Gilt in diesem Browser“), in
   nexnotes reist sie mit dem Konto. Soll nexmail sie am Konto speichern?
3. **Anzeigename, der nur eine Kopie des Benutzernamens ist**: beim Ändern des Benutzernamens mitziehen, oder bleibt er
   (Regel 4 „bleiben, wie sie sind“)?
4. **Doppelte Adressen**: Bleibt es beim Hinweis in der Kontenliste, oder soll der Betreiber (oder die Wanderung) eine
   der beiden entfernen dürfen, damit ein eindeutiger Index möglich wird? Und schickt „Passwort vergessen“ **per
   Benutzername** an eine doppelte Adresse weiter einen Link (heute ja; Regel 3 liest sich wie nein)?
5. **Passwort-Link für ein Konto nur über Anbieter**: erlaubt (gibt ihm ein erstes Passwort) oder ausgeblendet?
6. **Link-Dauer**: Einladung 7 Tage (nexmail) – bleibt das, oder wie im Modul? Rücksetzen per Mail künftig 1 Stunde
   statt 2.
7. **Einrichtung ohne Anzeigename**: Der Entwurf macht ihn zur Pflicht, nexmail hat ihn frei. Pflicht übernehmen?
