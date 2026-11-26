# Anbindung des Kontenmoduls (`nexkonten`) an nexmail

Stand 25.11.2026, Zweig `konten`: **auf den Modulen 1.0.0** (`konten` 1.0.0, `ui` 1.0.0, `post` 1.0.0, `oidc` 1.1.2,
eingefroren; Abschnitt 0g). Gebaut
mit `konten` 0.2.1 und `oidc` 1.1.0 (Abschnitt 0), Teil 2 mit `konten` 0.3.1 und `post` 0.1.1 (Abschnitt 0b), nachgezogen
in 0c bis 0f; die Abschnitte ab 1 sind der Plan der Vorbereitung (gegen `konten` 0.1.0) und bleiben als Begründung stehen. Maßgeblich sind der
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

**Runde 4 (25.11.2026, entschieden):** Ein Passkey zählt als zweiter Faktor: Bei „für alle verlangen“ ist er nach
dem Passwort oder Anbieter der zweite Schritt (`schritt: "passkey"`), eine App muss nicht dazu; ohne den Schalter
genügt das Passwort wie bisher. Nach dem Einrichten beim Anmelden kommen die Wiederherstellungscodes sofort
(`codes` in der Antwort von `/api/auth/code`, `CodesZeigen`). Die Geräteliste zeigt „Browser auf System“
(`describe_browser`), nie den rohen User-Agent. Passkeys gehen auch auf `localhost` (sicherer Kontext; der Passkey
gehört dann zu `localhost`). „Alle anderen Geräte abmelden“ fragt mit dem Satz des Moduls (Browser und gekoppelte
Geräte, Kalender-Programme, API-Schlüssel und Passkeys bleiben). Der Schalter „Mail bei neuer Anmeldung“ bleibt
unter Sicherheit.

**Runde 5 (25.11.2026, `konten` 0.3.2):** Was in Runde 4 lokal gelöst war, kommt jetzt aus dem Modul:
`Store.second_factor` über `factor.state` (ein Konto nur mit Passkey ist ohne Schalter `none`, mit Schalter
`passkey`), der nächste Schritt über `common.next_step` (`sitzung.naechster_schritt`), der Passkey als zweiter Schritt
über `factor.start_waiting`/`finish_waiting_by_passkey` (Cookie `nexmail_wartet` neben der halben Sitzung), die
Geräteliste über `sessions.listing(..., language=)`, `passkeys.party(..., origin=)`, `common.fresh_sign_in`,
`invites.invite_values(..., public_url=)`, die Wortlaute `account.usernameHintProfile` und
`account.factorRequiredSwitchHint`; der Vertragsadapter sagt `blocking`, `required_second_factor`,
`reusable_invites` = False. **Lokal geblieben:** das Einrichten und Prüfen des Authenticators samt
Wiederherstellungscodes (`services/zwei_faktor`, Geheimnis versiegelt in der Datenbank, überlebt einen Neustart;
`factor.begin_totp` hält es nur im Speicher), die Antwort trägt dafür das Wort des Moduls (`weiter: "show_codes"`);
`NEXMAIL_ZWEI_FAKTOR_AUS`; die eigene Sitzungsschicht (Mindestumfang laut `SCHNITTSTELLE.md`); `origin` fällt bei
einem GET ohne Kopfzeile auf die Adresse der Anfrage zurück.

**Wo das Modul nicht passte (Teil 2):**

7. **Hinweis am Benutzernamen** („Du kannst ihn später im Profil ändern“) steht im Profil selbst falsch. nexmail
   nimmt dort einen eigenen Satz (`profil.benutzername_hinweis`: „Damit meldest du dich an.“). Vorschlag: ein
   zweiter Wortlaut `account.usernameHintProfile` im Modul.
8. **`sessions.current` und eigene Sitzungen:** nexmail behält seine Sitzungsschicht (`services/sitzung.py`), weil
   Gerätetoken und Browser in derselben Tabelle liegen und die iPhone-App daran hängt; das Modul liefert Laufzeiten,
   Marken und die Mail. Vorschlag: in `SCHNITTSTELLE.md` sagen, welche Teile eine App mit eigener Sitzungsschicht
   mindestens nehmen muss.

## 0c. `konten` 0.3.3

Nachgezogen am 25.11.2026 auf demselben Zweig.

| Teil | Wo |
|---|---|
| Store | `pending_totp`/`set_pending_totp` über `benutzer.totp_wartend` (versiegelt, Kontext `benutzer:<id>:totp:wartend`) und `totp_wartend_bis`; ohne sie liest der Store nexmails eigenen halben Authenticator (unbestätigtes `totp_geheimnis`, ohne Ablauf). `set_offered_email` über `benutzer.angebotene_adresse` (Vorgabe `''`) |
| Anmeldung | Bremse des Moduls (`brake.BRAKE.claim(..., browser=sessions.known_mark(...))`, `succeeded(..., browser=…)`) statt `anmeldebremse.torwaechter`; die anderen Türen (Code, Adresse, Passwort vergessen …) bleiben bei nexmails Bremse |
| Passkeys | `passkeys.party(..., origin=…, request_url=str(request.url))` statt eigener GET-Rückfall-Lösung |
| Nothammer | `AppConfig(second_factor_off=…)` mit `NEXMAIL_ZWEI_FAKTOR_AUS`, `NEXMAIL_SECOND_FACTOR_OFF` zusätzlich; beim Start `factor.announce_switched_off()`; `GET /api/auth/ich` → `zwei_faktor_aus`, Hinweis `account.secondFactorOff` oben in Profil, Sicherheit und Anmeldung (`components/FaktorAusHinweis.tsx`) |
| Anbieteradresse | `profiles.provider_email`; Profil „Adresse von <Anbieter> übernehmen?“ über `POST`/`DELETE /api/auth/ich/angebotene-adresse` (Name des Anbieters aus der Verknüpfung mit dieser Adresse) |
| Zurücksetzen | `GET /api/benutzer/{id}/zweiter-faktor-ueberblick` (`factor.reset_overview`), Dialog mit Passkey-Liste und Haken „Passkeys auch entfernen“ (nur mit Passkeys) → `passkeys_entfernen` |

Lokal geblieben: das Einrichten des Authenticators in nexmails eigenen Routen (`/zwei-faktor/starten`, `/einrichtung`,
`/code`; Wiederherstellungscodes im alten Format), weil dort der QR-Code ohne Ablauf wieder abrufbar ist, und nexmails
Bremse an den übrigen Türen.

## 0d. `konten` 0.3.4 bis 0.3.6

Nachgezogen am 25.11.2026 auf demselben Zweig, alle drei Fassungen zusammen.

| Teil | Wo |
|---|---|
| Bremse an allen Türen (0.3.4) | Das Modul zählt `confirm:<Konto>` (Adresse, Benutzername, angebotene Adresse, Betreiber-Handlungen, Faktor), `code:<Konto>` (`/api/auth/code`, `/wiederherstellung` über `factor.check_code`), `mail:<Konto>` („Link nochmal schicken“, Passwort vergessen) und `forgot:<Absender>` (`forgot_in_background(..., sender=…)`; ohne `NEXMAIL_CLIENT_IP` je Eingabe, `none:<Konto oder Eingabe>`). nexmails `anmeldebremse.torwaechter` ist an diesen Türen weg. Eigene Routen, die ein Passwort selbst prüfen (Passwort ändern, Betreiber übergeben, Anbieter verknüpfen), zählen mit `anmeldebremse.bestaetigen` an `confirm:<Konto>`. Die Bremse bleibt bei nexmail an den Links mit Schlüssel, Einrichtung, Kopplung, Webhooks |
| Authenticator (0.3.4) | `/zwei-faktor/starten` → `factor.begin_totp` (Felder `geheimnis`, `otpauth`, `qr_svg` wie bisher, neu `gilt_bis`), neu `GET /zwei-faktor/einrichtung` → `pending_setup` (410 `enrolment_expired`, die Seite beginnt dann neu), `/zwei-faktor/bestaetigen` → `confirm_totp` (Code allein wie bisher; mit `passwort` prüft das Modul es), `/einrichtung` und `/code` beim Anmelden → `pending_setup`/`begin_totp` und `confirm_totp(actor_confirmed=True)`, `/code` und `/wiederherstellung` → `check_code`. Bestand: alte Geheimnisse, Codes und eine angefangene Einrichtung der Vorfassung gelten (`pending_totp` des Stores) |
| Angebotene Adresse (0.3.4) | Spalten `benutzer.angebotene_adresse_von` und `abgelehnte_adresse`, Store `set_offered_email(..., provider)` und `set_declined_email`; `touch_link` gibt den Anzeigenamen des Anbieters mit. „Nein, danke“ gilt für genau diese Adresse |
| Zurücksetzen (0.3.4) | Dialog in der Benutzerverwaltung aus `factorResetParts(überblick)` |
| Einladen (0.3.5) | `invite_values(..., request_base=str(request.base_url))`, Link über `invite_link`: ohne öffentliche Adresse die, unter der der Betreiber nexmail geöffnet hat (vorher 400 `oeffentliche_adresse_fehlt`) |
| Sitzung abgelaufen (0.3.5) | `components/SitzungAbgelaufen.tsx`: `api/client.ts` meldet ein 401 `nicht_angemeldet` außerhalb der Anmeldewege, der Dialog zeigt `sessionExpiredParts(next)` (Passwort, Anbieter, Code, Passkey, Einrichten über die Anmeldeseite, Codes); die Seite darunter bleibt |
| Authenticator aus (0.3.5) | `/zwei-faktor/aus` → `factor.disable_totp` (401 `kennwort_falsch` wie bisher, 409 `factor_required`, 429); nimmt auch die wartende Einrichtung mit, die Codes nur ohne Passkey |
| Profil und Sicherheit (0.3.6) | nur aus `PAGES` (`PROFIL_TEILE`, `SICHERHEIT_TEILE` mit `pageOrder`); eigene Teile am Ende: Profil „Abmelden“, Sicherheit Anmeldeanbieter und Google/Microsoft. Benutzername direkt im Feld, „Speichern“ fragt das Passwort; Anzeigename gilt beim Verlassen des Feldes; Zweiter Faktor „An“/„Aus“ aus `GET /api/auth/ich` → `zweiter_faktor` (`factor.state`); neu „Neue Codes erzeugen“ (`POST /api/auth/zwei-faktor/codes`, `factor.new_codes`). Einrichtung mit `SETUP_PAGE`/`setupNotes` |
| Nothammer | `NEXMAIL_SECOND_FACTOR_OFF` ist jetzt auch eine Einstellung (`Settings.second_factor_off`) und steht in `docker-compose.yml` neben `NEXMAIL_ZWEI_FAKTOR_AUS`; einer genügt |

Weggefallene eigene Wortlaute: „Zweiten Faktor ein-/ausschalten“, „Eingerichtet und aktiv“/„Nicht eingerichtet“, der
Satz über einen fehlenden Faktor unter Sicherheit, „Alle anderen Geräte abmelden“, „Bild wählen“/„Anderes Bild“,
„Bearbeiten“ am Benutzernamen, „Rolle: …“ (jetzt `account.role`). Tests: `tests/test_konten_routen.py` (wartende
Einrichtung, Bremse beim Abschalten, Passwort vergessen je Absender, neue Codes), `test_benutzer.py` (Einladen ohne
öffentliche Adresse), `test_anmeldung.py` (410 statt 400 ohne Einrichtung), vitest `src/nexkonten.test.ts`
(`APP_PAGES`, Dialog „Sitzung abgelaufen“).

## 0e. `konten` 0.3.7

Nachgezogen am 25.11.2026 auf demselben Zweig; Server und Store unverändert (nur `__version__`).

| Teil | Wo |
|---|---|
| Ein Knopf „Speichern“ | `einstellungen/Profil.tsx`: Anzeigename, Benutzername und E-Mail in einem Formular, darunter `PAGES.profile.saveButton`; kein Speichern beim Verlassen eines Felds, keine Knöpfe je Feld. Ist Benutzername oder E-Mail geändert (`confirmOnSave`), fragt er einmal das Passwort; dann erst `PUT /api/auth/ich/benutzername`, danach `PUT /api/auth/ich/profil` (Anzeigename, Adresse nur wenn geändert) |
| Regeln am Benutzernamen | beide Hinweise (`usernameHintProfile`, `rules`) im Hinweis des Felds, per `aria-describedby` |
| Beschriftung und Feld | `ds/Feld.tsx` seit `4fc817f`: `<label for>` mit genau der Beschriftung, Hinweis per `aria-describedby` |
| vitest | `src/nexkonten.test.ts` zeigt die sechs Bildschirme (`APP_RENDER`: Einrichtung, Einladung, Anmeldung, Passwort vergessen, neues Passwort, Profil) mit einem `fetch`-Ersatz und prüft Beschriftungen, Hinweise und den einen Knopf; dafür `@testing-library/dom` als devDependency |

## 0f. `konten` 0.3.9 und 0.3.10, `ui` 0.1.2, `oidc` 1.1.1, `post` 0.1.2

Nachgezogen am 25.11.2026 auf demselben Zweig, kopiert aus `bauplaene` (Zweig `konten`, `4f714a8`) mit
`sync.py copy`, `check` für alle vier sauber. `e2e/nexoidc.spec.ts` bleibt (nexmail hat Playwright).

| Teil | Wo |
|---|---|
| Anmeldung (0.3.10) | `POST /api/auth/anmelden` über `login.sign_in(store, eingabe, passwort, sender=anmeldebremse.adresse_von(request), browser=<bekannte Marke>)`. Wartet nur der Topf des Kontos oder der Eingabe: 401 `anmeldung_falsch`, das Passwort ungeprüft; 429 `zu_viele_versuche` mit `Retry-After` nur bei vollem Topf des Absenders (ohne `NEXMAIL_CLIENT_IP` je Ziel, `sender:none:<ziel>`). Die eigene Klasse `_Bremse` ist weg; `login.succeeded` bleibt nach der ganzen Anmeldung. „Anmeldung mit Passwort“ aus: Antwort immer 401, gezählt wird weiter an der Bremse des Moduls (`auth._gehalten`) |
| Passwort zuletzt geändert (0.3.10) | Spalte `benutzer.passwort_geaendert` (ergänzend, Bestand leer = „unbekannt“), gesetzt von `Store.set_password`, `add_account` mit Passwort, `benutzerdienst.passwort_aendern` und `anlegen`; das Auffrischen des Hashes beim Anmelden zählt nicht. `GET /api/auth/ich` → `passwort_geaendert`; Sicherheit, Kasten Passwort: Zeile aus `passwordChanged(...)` |
| Passwort vergessen (0.3.10) | `kontenpost.sofort_senden` (`nexpost.send.deliver`), nie über die Outbox; scheitert die Mail, nimmt das Modul den Link zurück. Die übrigen Kontomails gehen weiter über die Outbox |
| Fehlerkennungen (0.3.10) | Nach außen bleiben die alten. Steht hinter einer alten Kennung mehr als eine des Moduls (`einladung_abgelaufen`, `ruecksetzung_ungueltig`; `konten_store.MEHRDEUTIG`), trägt die Antwort die des Moduls in `werte.account_code`; `lib/servermeldung.ts` nimmt dann deren Satz („abgelaufen“) über `accountErrorKeyOf` |
| Zugänge (0.3.10) | `list_access` gab schon nur `device` und `api_key` |
| Kontenliste (0.3.9) | `pages/Benutzerverwaltung.tsx` (Reiter „Konten“) aus `ACCOUNT_LIST`, `MANAGE_DIALOG`, `INVITE_DIALOG`, `RESET_LINK_DIALOG`, `OPEN_INVITES` und den Bausteinen von `ui`; nexmails Seite in `pages/kontenliste.ts`: `APP_CAPS` (`rename`, `emailRemove`, `resetLink`, `factorReset`, `unlink`, `remove`; keine Rollen, kein Sperren, kein „Überall abmelden“, kein Zurückholen), eigener Knopf `handOver` „Betreiber übergeben“ in „Ändern“ vor „Adresse entfernen“ mit `notSelf`, Haken „KI erlaubt“ in „Rechte“ (sofort gespeichert, `PUT /api/benutzer/{id}/ki`), Angabe „Postfächer“, beim Löschen die Zahlen Postfächer und Nachrichten und „Auf dem Mailserver bleibt alles unberührt“, dann `account.askRemoveFinal`. Der Hinweis „kein Postausgang“ steht weiter oben. Das eigene Konto steht zuerst; am eigenen Konto fehlen, was `NOT_ON_SELF` sagt (auch Lösen) und „Betreiber übergeben“ |
| Server zur Liste | `GET /api/benutzer` je Konto zusätzlich `kontaktadresse_zaehlt`, `passkeys`, `gesperrt` (Kontosperre), `zuletzt_gesehen` (jüngste bestätigte Sitzung oder gekoppeltes Gerät; ohne: keine Angabe statt „Nie“), `profilbild`; Einladungen mit `expired` neben `abgelaufen`. `POST /api/benutzer/einladungen` mit `senden` (ab Werk an, wie bisher) und in der Antwort immer `link` und `gemailt` („danach immer der Link zum Kopieren“). `DELETE /api/benutzer/{id}` verlangt `{"passwort": …}` (401 `kennwort_falsch`, gezählt an `confirm:<Betreiber>`; ohne Passwort frische Anmeldung beim Anbieter) |
| Bild ohne Foto | `--nexui-avatar-*` in `styles/index.css`, wie nexmails `Profilbild` (45 %, 45 %, weiß) |
| Vertragsadapter | `sign_in_from` über die eigene Anmelderoute vom Absender aus (`NEXMAIL_CLIENT_IP=direct` für diese eine Anfrage), `listed_invites` über `routers.benutzer.liste` |
| Tests | `test_konten_routen.py` (Passwort-Datum, Felder der Liste, Löschen mit Passwort, Passwort vergessen sofort), Bremstests auf „genau 5“ und 401 statt 429 (`test_anmeldung`, `test_konten_routen`, `test_angemeldet_bleiben`, im Test „Bestand“ eine Zeile: zehn falsche, dann richtig = 401), `test_ruecksetzung` (gleiche Kennung, daneben `account_code`), Löschen mit Passwort in `test_benutzer`, `test_betreiber_uebergeben`, `test_apischluessel`; vitest `src/nexkonten.test.ts` mit den Blöcken der Vorlage 0.3.9 und 0.3.10 (`APP_CAPS`, `APP_OWN`, `APP_ACCOUNTS_RENDER`, Namensraum `account`, „Zuletzt geändert“) |
| Playwright (angepasst, nicht ausgeführt) | `tests/mehrbenutzer.spec.ts` (Einladen, „Link senden“, Zurücknehmen, Verwalten am eigenen und an einem anderen Konto, Aufräumen mit Passwort aus `NEXMAIL_TEST_PASS`), `tests/einstellungen.spec.ts` (Merkmal des Bereichs Konten) |

**Geprüft am 25.11.2026:** Backend voll einmal (`pytest -n 2`: 3086 bestanden, 4 übersprungen), darin Vertrag
`tests/nexkonten` (232 gesammelt) und Test „Bestand“ (62); Frontend `npx vitest run --maxWorkers=2` 303 grün in 36
Dateien, `npm run lint` und `npm run build` (mit `tsc -b`) grün. Kein Playwright, keine Server.

## 0g. Auf den Modulen 1.0.0 (`konten` 1.0.0, `ui` 1.0.0, `post` 1.0.0, `oidc` 1.1.2)

Schluss-Durchgang am 25.11.2026, kopiert aus `bauplaene` (Zweig `konten`, `3c55402`), `sync.py check` für alle vier
sauber. Die Module sind ab hier eingefroren.

| Teil | Wo |
|---|---|
| Mail „Neue Anmeldung“ (post 1.0.0) | `kontenpost._brief`: `from_account_mail(..., link=<öffentliche Adresse>/konto/sicherheit, where=<User-Agent>, time_zone=<Zeitzone der Installation>)`; Personen führen in nexmail keine eigene Zone, darum die aus Verwaltung → Allgemein (sonst `NEXMAIL_ZEITZONE`, sonst die des Servers). Nie eine Netzadresse |
| Vertragsadapter | `nexkonten_adapter.py`: `forgot_through_route` (über `POST /api/auth/kennwort-vergessen`, Post gefangen mit `nexpost.testing.catch_mail`), `picture_status` (über `GET /api/auth/profilbild/{id}` mit einer Browser-Sitzung oder ohne); `nexpost_adapter.py`: `new_sign_in_letter` (Anmeldung über die Route aus einem neuen Browser) |
| Unverändert | `account_code` nur bei `MEHRDEUTIG` (so im Modul beschrieben); ohne `NEXMAIL_CLIENT_IP` der Absendertopf je Ziel; der Test „Bestand“ fängt seine Post weiter über `systempost.senden` |
| vitest | `src/nexkonten.test.ts` mit dem Abschnitt „Helpers“ der Vorlage 1.0.0 vor dem ersten Block (dort jetzt auch `said`), der Block „the konten texts“ wie in der Vorlage |
| ui 1.0.0 | Ein langer Titel eines Kastens bricht um, statt abgeschnitten zu werden („Wiederherstellungscodes“ in der schmalen Ansicht, `tests/darstellung.spec.ts`); geprüft im vitest des Bausatzes |

**Geprüft am 25.11.2026:** `pytest -n 2` über alles (darin `tests/nexkonten`, `tests/nexoidc`, `tests/nexpost` im selben
Lauf) 3089 bestanden, 4 übersprungen; vitest 304 grün in 36 Dateien; `npm run lint` und `npm run build` grün. Kein
Playwright.

## 0h. Durchgang „Einstellungen“ (`ui` 1.1.0, `konten` 1.1.0, `oidc` 1.2.0, `post` 1.1.0, `log` 1.0.0, `sicherung` 1.0.1, `schluessel` 1.0.0)

Nach dem Bauplan „Einstellungen“ (nexlore, `Development/nexapps/Baupläne/Bauplan Einstellungen.md`, E1 bis E34) am
25. und 26.11.2026, Zweig `einst-desktop`. Module aus `bauplaene-stand` (zuerst `bef0132`, dann `7685875` mit E33
bis E38, sicherung zuletzt aus `b0d3618`), `sync.py check` für alle sieben `ok`, jede Vorlage im Frontend mit ihrer
Kopfzeile `// Vorlage <Paket> <Fassung der letzten Änderung>` und den Änderungen der Vorlagen seit `bef0132`.

| Bereich (`/settings/<slug>`) | Woher | Was gewandert ist |
|---|---|---|
| Mein Konto › Profil (`profile`) | konten 1.1.0 `PAGES.profile`, `SignOutCard`, `UnconfirmedEmailBox` | unverändert die Felder; „Adresse noch nicht bestätigt“ neu als Kasten, beim ersten Start gelten zählende Adressen einmal als bewiesen (E23) |
| Sicherheit (`security`) | konten `PAGES.security`, oidc `SignInProviders` | dazu nexmails Karte „Google- und Microsoft-Konten“ (app-eigen); Passwortfelder mit dem Wortlaut des Moduls, Mindestlänge 12 wie der Server |
| Darstellung (`appearance`) | konten `AppearanceCard` (Theme am Konto, `benutzer.theme`) | nexmails Dichte, Lesebereich, Bilder, Logos als eigene Karten danach; das Theme des Browsers wird beim ersten Laden übernommen (`/api/auth/ich/theme/browser`) |
| Kalender und Adressbücher (`calendars`), KI (`ai`) | nexmail | KI: nur der persönliche Zugang; „KI-Anbieter“ unter Server |
| Benachrichtigungen (`notifications`) | ui `NotifyWays` | „Worüber“ und „Ruhezeit“ als nexmails Karten; keine Server-Karte für Web Push (nichts einzustellen, E33) |
| Verbindungen (`connections`) | schluessel `ApiKeysCard`, ui `Collapsible` | Karte „Geräte“ statt „iPhone verbinden“ (`GET /api/app-kopplung/geraete`, Koppeln im Fenster), „Auf diesem Gerät installieren“, nextime und nextasks, „Aufgaben“ (Todoist, Webhook) als app-eigene Karten; keine MCP-Karte (E27) |
| Mail › Postfächer, Regeln, Signaturen, Abwesenheit, Schlagworte | nexmail | nur Karten; Knöpfe, Felder, Auswahl, Haken aus dem Bausatz; „Postfach bearbeiten“ im Fenster des Bausatzes |
| Server › Allgemein (`general`) | schluessel `InterfacesCard` | „Funktionen für alle Konten“, „Zeitzone des Servers“ (app-eigen); die öffentliche Adresse steht nur noch unter Anmeldung |
| Server › Anmeldung (`sign-in`) | konten `SignInPage` (`GET/PUT /api/server/sign-in`, `…/readiness`), oidc `SignInProviders` | Reihenfolge des Bauplans; die Schalter `anmeldung_passwort`, `zwei_faktor_fuer_alle`, `passkeys_erlaubt` unter ihren Namen |
| Server › Mail (`mail`) | post `MailCard` unter `/api/server/mail` | zweite Karte „Google und Microsoft“; `systempost.senden` ist leer (nur noch die Testbrücke des Tests „Bestand“), die Post der Postfächer bleibt, wie sie war |
| Server › Speicher und Sicherung (`storage`) | sicherung 1.0.1 `StorageArea` unter `/api/server/storage` | alte `.db`-Rücksetzpunkte und neue ZIPs in einer Liste, Uhrzeit (`sicherung_uhrzeit`, 03:00), monatlich, schlankes verschlüsseltes Herunterladen (E22); die alten Wege `/api/sicherung/*` über das Modul |
| Server › KI-Anbieter (`ai-provider`) | nexmail | was vorher „KI für alle“ in der Verwaltung war |
| Server › Konten (`accounts`) | konten 1.1.0 Kontenliste, `WhatYouSeeCard`, schluessel `AllKeysCard` | Rollen (mehrere Betreiber), Sperren, Löschen mit 30 Tagen Zurückholen (`manage.purge_due` im Takt), „KI erlaubt“; „Betreiber übergeben“ entfällt, `POST /api/benutzer/{id}/betreiber` bleibt als alter Weg |
| Server › Log (`log`) | log 1.0.0 `LogCard` unter `/api/logs` | „Wie lange“ wird Ausführlichkeit (gespeicherte deutsche Stufen gelten weiter), nexmails Schwärzungen bleiben, Herunterladen als Text (E21); `/api/protokoll` bleibt |
| Über nexmail (`about`) | ui `AboutPage` | „Fassung“ heißt „Version“ |

Die alten Adressen (`/einstellungen/…`, deutsche Namen wie `/settings/postfaecher`) ersetzen sich per
`replaceState` durch die neuen (`bereiche.ts` `ALTE_NAMEN`, Test `bereiche.test.ts`, Spec „Alte Adressen“).

**Alte Wege, die bleiben:** `/api/apischluessel` (ruft `keys.make/change/revoke`, `switches.change`), `/api/v1`
(`keys.authenticate` in `deps.api_zugriff`, alte Kennungen, ruhende Schlüssel 401 `second_factor_required`),
`/api/protokoll`, `/api/sicherung/*`, `/api/benutzer/{id}/betreiber`, `/postausgang` und `/postausgang/probe`,
`/api/app/1` unverändert. Kein Schlüssel wird neu gehasht; neu ist nur die Spalte `api_schluessel.gesperrt`
(eine ältere Fassung liest sie nicht, Rückweg im README von schluessel).

**Mit 7685875 dazu:** `things`/`thingsDative` (Mails/Mails, englisch mail/mail); Sicherung mit `when` in der unter
Darstellung eingestellten Zone und `restore_options = ("address",)`: das Fenster „Wiederherstellen“ fragt, ob die
öffentliche Adresse aus der Sicherung gilt (ab Werk die jetzige, wie der alte Weg), der Befund nennt je Anbieter die
Rückkehradresse mit beiden Adressen; „Postfach hinzufügen“ und das Webhook-Geheimnis im `Dialog` des Bausatzes mit
`dismissable`; `Store.on_shut_out`/`on_back`: solange ein Konto gesperrt oder gelöscht ist, kein Web Push
(`push.draussen`) und kein Abgleich von Postfächern, Kalendern, Adressbüchern und Todo-Apps (`models.konto_drin`), die
Abos und Verbindungen bleiben; `push_ready` im Vertragsadapter.

**Umwege mit TODO:** keine mehr. Die zwei `TODO ui 1.1.0` und das `exclude` in `frontend/tsconfig.json`
(`TODO sicherung 1.0.1`) sind mit 7685875 und b0d3618 wieder heraus.

**Nach Stufe 1:** `Kalenderfenster`, `Buchfenster` und `Nachfrage` bleiben auf `ds/Dialog`, weil die App sie auch
außerhalb der Einstellungen nutzt (E33).

**Mit a374e3c dazu:** post `catch_mail` mit Wächter gegen echtes SMTP (kein App-Test war betroffen), log lässt nach
„Bearer“ die Vorsilbe stehen (`Bearer nxm_…`, neuer Test), konten sagt „Gespeichert.“ erst nach dem Speichern (Vorlage
`nexkonten.cards.test.tsx` von Hand nachgezogen).

**Verweise (E39)**, alt → neu (DE; EN entsprechend):
- nextasks: „API-Token … unter Mein Konto → Verbindungen“ → „API-Schlüssel … unter Einstellungen → Mein Konto →
  Verbindungen → API-Schlüssel“; „Server → API“ → „Server → Allgemein → Schnittstellen“; „Token“ → „Schlüssel“;
  Feld „API-Token“ → „API-Schlüssel“; „Token erneuern“ → „Schlüssel ändern“.
- nextime: „Einstellungen → Verbindungen → Schlüssel für Programme“ → „Einstellungen → Mein Konto → Verbindungen →
  API-Schlüssel“; „Server → Allgemein“ → „Server → Allgemein → Schnittstellen“; Feld „Schlüssel“ → „API-Schlüssel“.
- nexmail selbst: API-Schalter „Einstellungen → Verbindungen“ → „Server → Allgemein → Schnittstellen“; Adresse für
  den QR-Code „Server → Allgemein“ → „Server → Anmeldung“; Vorlagen „Einstellungen → Signaturen“ → „Einstellungen →
  Mail → Signaturen“; Todoist „in den Einstellungen unter Aufgaben“ → „Einstellungen → Verbindungen → Aufgaben“;
  „siehe Protokoll“ → „siehe Log“; „Rücksetzpunkt“ → „Sicherung“.
- README: nextasks-Schlüssel, „Change key“, „Settings → Mail → Mailboxes“, Schalter unter „Settings → Server →
  General → Interfaces“, der Abschnitt „Backup and restore“ nach dem Modul (eine Liste, Adressfrage im Fenster).
- Test `src/i18n/verweise.test.ts` hält die neuen Orte fest (gegen eine Mutation geprüft).

**Gemeinsame Runde (86a0cce, E45 bis E48):** neue Konten beginnen mit „Wie das System“, Konten von vorher ohne Wahl
behalten nexmails Dunkel, außer ihr Browser hielt wirklich einen Wert (`theme_default_before="dark"`,
`lib/browserwahl.ts`); Kasten „Passkeys“ immer, wenn der Betreiber sie erlaubt; Server › Allgemein in der Reihenfolge
des Bauplans: „Funktionen für alle Konten“ (`features`), „Schnittstellen“, neu „Sprachen“ (wie nexnotes, `/api/locales`,
`services/sprachen.py`), „Zeitzone des Servers“; „Postfach hinzufügen“ als Bausatz-Knopf; Abwesenheit aus Karten;
Ortsangaben nach E46 (Mein Konto › Verbindungen › API-Schlüssel, Server › Allgemein › Schnittstellen), Test
`src/i18n/verweise.test.ts` mit der Regel; E49: jedes „wo“ in „Was ist neu“ zeigt auf den heutigen Ort.

**Nacharbeit (1ce1a8f, c0b07ab):** Kasten „Passkeys“ mit `PasskeyAddition` aus konten: `GET /api/auth/passkeys` trägt
`passkeys_can_add` (`passkeys.can_add`, die öffentliche Adresse so, wie sie gesetzt ist); ohne öffentliche
https-Adresse (und nicht auf localhost) steht statt „Passkey hinzufügen“ der Satz des Moduls, für den Betreiber mit
Link „Server › Anmeldung“.

**Sprachen (E51/2):** die eigenen Sprachen des Zwischenstands sind zurückgenommen (`901d213`, Revert von `5ff7fb3`);
an ihrer Stelle das gemeinsame Modul `sprachen` 1.0.0 (zuletzt e18169e) unter `/api/locales` (Ordner
`<data>/locales`, Ablehnungen in der Form des Moduls, `tidy_at_start` beim Start), Karte `LanguagesCard` unter
Server › Allgemein, eigene Sprachen in Profil und Anmeldeseite über `ownLanguages`/`useLanguageOptions`; die
Profilsprache nimmt an, was sie vorher annahm (E52), `nexsprachen.known` nur für die Auswahl. Die Vertragstests zu
`/openapi.json` lesen nexmails Beschreibung über `description()` des Adapters; veröffentlicht wird keine. Vertragstests
`tests/nexsprachen` (63 grün). Dazu schluessel aus 4f3e75e („Neuer MCP-Schlüssel“ md secondary).

**E53 (0e372f1):** sicherung und sprachen neu gezogen; der Vertragsadapter von sicherung liest nexmails Beschreibung
über `description()` (`app.openapi()`, veröffentlicht wird keine). `tests/test_openapi_namen.py` hält `operationId`
und `summary` aller 394 Wege des Stands `konten` fest (`openapi_namen_konten.json`); der Vergleich mit `konten`
(`openapi-namen/vergleichen.py`) zeigt nur Zusätze. Das Schema `Gefunden` (zwei gleichnamige Klassen in
`routers/kalender.py` und `routers/adressbuecher.py`) heißt auf beiden Ständen `app__routers__adressbuecher__Gefunden`.

**Galerie-Funde Endlauf:** `AccountButton` gibt die Größe aus konten-`BUTTONS` weiter (`buttonSize`, wie nexnotes;
„Verwalten“ und die anderen kleinen Knöpfe `sm`, Test `components/AccountButton.test.tsx`); zwischen den Karten von
Profil und Sicherheit 24 px wie überall (`gap-6`).

**Playwright auf dem Surface (8b820d2), Nacharbeit:** keine Funktion fehlte; Specs umgestellt, ohne abzuschwächen
(sichtbare Zeile der Bausatz-`Table`, Zahl allein im Umzugsfenster, Feld „API-Schlüssel“ bei nextime, „Neu in nexmail …“
auf der Über-Seite, Rückkehr-Adressen in ihren `CopyRow`-Feldern, Knopf `notify-browser-on` samt Lage „Erlaubt, aber
nicht angemeldet“, der nächste Abschnitt um eine Überschrift in der Karte „Aufgaben“).

**Zweiter Surface-Lauf (7f944dd):** „unterlagen.txt“ war kein roher Schlüssel, sondern der Dateiname des Anhangs der
Probe-Mail aus `anhang_erinnerung.spec.ts` im Lesebereich; Dateinamen tragen jetzt `data-dateiname` (wie Rechnernamen
`data-adresse`), der Wächter übergeht genau diese. nextime: der Rechnername steht im Zustand der Karte („verbunden ·
zeit.example.com“), nichts fehlte. oauth: je Anbieter ein Feld „Client-ID“, der Spec nimmt den Kasten „Google“. Der
Antwort-Test schickt seine eigene Probe-Mail und läuft damit auch allein.

**E57 (dcbd5d1):** sprachen 1.0.1 (Entfernen einer Sprache fragt erst), konten 1.1.1, schluessel 1.0.1 (danach 1.0.2, 35ed594); die drei
Vorlagen von Hand nachgezogen (nur die Werte der App weichen ab). nexmail nutzt die neuen Plätze `newSignInMailHint`,
`offAction`, `made` nicht.

**E59 (3f8605c):** sprachen 1.0.2 (2a565f5): die Vorlage trägt nur Texte (`texts_only`, `textsOnly`). Der
Adapter gibt mit `offered_template()` dieselben englischen Texte wie die Seite (en.json, Anmeldung, Kontenmodul,
Mailmodul); der neue Vertragstest `test_nexsprachen_template.py` ist grün. In `nexsprachen.test.tsx` ist `ENGLISH`
genau `englischeTexte()`, also das, was `Sprachen()` in `Verwaltung.tsx` an `LanguagesCard template` gibt. Einen
Cast an `template` gab es in nexmail nicht.

**E59 A6 (da4f220):** konten 1.1.2 (6e13836). Wo ein Passwort ein altes ersetzt, heißt das Feld jetzt „Neues Passwort“:
im Fenster „Passwort ändern“ (`Sicherheit.tsx`, `fieldLabel('change', 'newPassword')`) und nach „Passwort vergessen?“
(`KennwortPage.tsx`, `fieldLabel('reset', 'newPassword')`). Einrichtung und Einladung bleiben bei „Passwort“. Der
neue Vertragstest zur Anmeldung (eine Passwortprüfung je Weg, Zeit paarweise) ist ohne Änderung grün; nexmails Speicher
rechnet schon für unbekannte Namen. `change` steht nicht in `APP_SCREENS`: Der Knopf im Fenster heißt wie der Knopf
auf der Seite („Passwort ändern“), das Wortverzeichnis des Knopfblocks hielte ihn für `secondary`. Deshalb prüft ein
eigener Block in `nexkonten.test.ts` das offene Fenster. `kennwort.spec.ts` sucht jetzt „Neues Passwort“ (nur mit
`tsc` geprüft).

**Geprüft am 26.11.2026** mit `einst-werkzeug/reihe.sh nexmail ende` nach 86a0cce, E45 bis E49 (ohne ruff, nexmail
hat keins; pytest ohne xdist; zuletzt nach E59 A6): pytest 3308 bestanden, 0 rot, 6 übersprungen (2 im Schlüssel-Vertrag: nexmails
Schlüssel haben kein Ablaufdatum; 3 im oidc-Vertrag: Einladungen tragen keine Rechte; 1 in nexmails eigenen Tests,
schon vorher). Der Vertragstest von sicherung zum Herunterladen ist jetzt grün. `tsc --noEmit` sauber, vitest 455
grün in 47 Dateien, `npm run build` grün. Neue Tests je gegen eine Mutation geprüft (Rückgabecode 1): ruhender
Schlüssel über den alten Weg, gesperrter Schlüssel über `/api/v1`, gelöschtes Konto ohne Post, fremder Browser nicht
entfernbar, die Adressfrage beim Wiederherstellen (verschlüsselt und eigene Sicherung), die Rückkehradressen der
Anbieter, kein Push und kein Abgleich für ein Konto, das draußen ist. Test „Bestand“ unverändert. **Playwright nicht
gelaufen** (hier kein Browser); die Specs unter `frontend/tests` sind auf den Bausatz umgestellt und nur mit `tsc`
geprüft.

## 0i. Durchgang „Module“ (`sicherung` 1.0.4, `ui` 1.1.1, `schluessel` 1.1.1, `updates` 0.1.2, `mcp` 1.1.2, `ki` 0.1.1, `verbinden` 0.1.4)

Am 26.11.2026 auf dem Zweig `einst-module` (Worktree `nexmail-module`), Module aus `bauplaene-module` (`einst-module`,
zuletzt `de70ac2`), je Modul `sync.py check` ok. Grundlage: Bauplan Einstellungen E61 bis E64, Entwurf Update-Prüfung
U1 bis U21, Entwurf MCP-Modul samt Entscheidungen 1 bis 16, Entwurf KI-Anbieter K1 bis K18, Entwurf Apps verbinden V1
bis V23. Fragen und Modulfehler: `einst-fragen/nexmail-module.md`.

| Modul | Was nexmail dafür gebaut hat | Alte Wege als Hüllen | Umwege (TODO) |
|---|---|---|---|
| sicherung 1.0.2 bis 1.0.4 | Zeit in Klammern (E62); „Jetzt sichern“ mit Notiz (E63); `archiv()` schreibt Zeitpunkt, Art und Notiz der Sicherung ins verschlüsselte Manifest, `_gesperrt_pruefen` gibt `described` zurück (E64); `test_absenderbild` kopiert die Datenbank über die Sicherungs-API statt `shutil.copy` (WAL) | `/api/sicherung/*` unverändert | keine |
| ui 1.1.1, schluessel 1.1.0 | Vorlage `nexschluessel.test.tsx` nachgezogen; Art `mcp` (s. u.) | `/api/apischluessel` unverändert | keine |
| updates 0.1.1 | `services/aktualisierung.py` konfiguriert das Modul (Schalter `update_pruefen` wie bisher, „“ = nie gespeichert = an), Wege unter `/api/about`, Einrichtung mit „Nach neuen Versionen sehen“ (`update_check` optional, U1), `NEXMAIL_UPDATE_URL`; keine Glocke, also kein Blick im Hintergrund (U19); keine Projektseite (U18); Über-Seite aus `useUpdates` | `GET /api/ueber`, `POST`/`PUT /api/ueber/pruefen` mit deutschen Feldern (`routers/ueber.py`), Mitglieder bekommen die Felder zum Stand leer (U15) | Vertragstests setzen eine Glocke voraus (4 übersprungen, `TODO updates 0.1.1`) |
| mcp 1.1.0 (neu) | zehn Werkzeuge (`services/mcp_werkzeuge.py`) über die Dienste der Oberfläche, Stufen `read`/`draft`/`write`, Bereiche = Postfächer (Pflicht), Extra `mailtext`; Tabellen `mcp_schluessel`, `mcp_programm`, `mcp_code`, `mcp_verbraucht`, `mcp_recht`, `mcp_anfrage`; Vorsilben `nxk_`, `nxkr_`, `nxkc_` (auch im Log geschwärzt); Schalter `mcp_zugang` ab Werk aus; „KI erlaubt“ über `nexki.chain.for_programs`; Programme enden beim Sperren (E42, `konten_store.shut_out`); Rückfragen als Web-Push an die Browser (MCP 14); Karte „KI-Werkzeuge (MCP)“ mit „Rechte je Werkzeug“ und „Wartende Rückfragen“, Seiten `/oauth/authorize` und `/mcp/requests/<nr>`, Betreiber in „Schnittstellen“ | – (nexmail hatte kein MCP) | Test-Clients geben neuen MCP-Schlüsseln die Postfächer mit (`TODO mcp 1.1.0`); Bremse falscher Schlüssel ohne `NEXMAIL_CLIENT_IP` nach Adresse der Verbindung (`TODO mcp 1.1.0`) |
| ki 0.1.0 | `services/ki_store.py` (Store über `einstellung.ki_erlaubt`, `Benutzer.ki_*`, neu `Benutzer.ki_api`, `ki_vorgang.form`/`an`); `kidienst` fragt über `nexki.ask` (Netzregeln, Kette, Bremse, Rahmen mit Zufallsmarke, Was ging hinaus), behält Aufträge, Töne, Prüfungen und Kennungen; `settings.adopt` beim Start; Bereiche Server › KI-Anbieter und Mein Konto › KI aus `AiProviderArea`/`AiAccountArea` mit nexmails Karten „Eingegangene Post“; `KiDienst.tsx`, `KiVorgaenge.tsx` entfallen; eigener Vertragstest `tests/test_ki_netzregeln.py` (K1, je Regel gegen eine Mutation) | `/api/ki`, `/api/ki/modelle`, `/api/ki/text`, `/api/ki/vorgaenge`, `/api/ki/erlaubt`, `/api/ki/fremde-post`, `/api/nachrichten/{id}/…` mit den Kennungen von vorher (`kidienst.ALTE_KENNUNGEN`); neue Fälle mit der Kennung des Moduls | Adapter beantwortet `manual` mit der Absage des Moduls (`KiFehler.modul`), kein automatischer Auftrag (2 übersprungen); unlesbare Antwort schreibt nexmail selbst in die Liste (alle `TODO ki 0.1.0`) |
| verbinden 0.1.2 | `services/verbinden_store.py` (Tabellen `vb_*` als ORM), `in_use` = nextasks, nextime, nexfolk, nexpaper (V20); Gast über die Klick-Verbindung: `Zugang.ueber` in `nextasks.py`/`nextime.py`, jede Anfrage über `nexverbinden.call` (V18), `on_connected` legt dieselbe Zeile an wie das Verbinden von Hand; nexfolk: Bücher mit `adressbuch.ueber`, CardDAV mit dem Token aus `nexverbinden.access`, Ausgang per `reached`; nexpaper (V19): `services/nexpaper.py`, `POST /api/nachrichten/{id}/anhang/{id}/nexpaper` mit `tresor`, `GET /api/nexpaper/tresore` (V38: Fenster bei mehr als einem Tresor, zuletzt genutzter je Konto in `einstellung` `nexpaper_tresor:<konto>`), Knopf am Anhang (`AnNexpaper.tsx`); `retire_key` beendet einen alten `nxm_`-Schlüssel; Karten aus `ConnectionsArea` mit den Zeichen des Moduls, Kalender- und Listenwahl als `children` in jedem Zustand (V23), Form von Hand unter `manual`, `per_klick` an nextime- und Aufgabenverbindung; Betreiberkarte nach „Schnittstellen“ (V22), Seiten `/connect/app`, `/connect/return` | `/api/aufgabenziele/…/nextasks`, `/api/nextime`, CardDAV von Hand unverändert, alte Zeilen bleiben | seit 0.1.4 gelöst über `on_disconnected` |

**Mutationsproben (Rückgabecode 1):** updates: Mitglied-Zweig, `at_setup`, Glocke, Schlüssel des Schalters; mcp:
Bereiche ignoriert, Extra weg, Programme beim Sperren nicht getrennt, „KI erlaubt“ ignoriert, Inhalt im Log, Push bei
Rückfrage; ki (im Modul, Kopie): eigenes Netz ohne Liste, Link-local/Metadaten, Weiterleitung, Proxy aus der Umgebung;
sicherung 1.0.4: `described` weggelassen; verbinden: Klick-Weg in `nextasks._anfrage` übergangen; nexfolk-Token im Abgleich, zweiter Versuch nach 401 bei nexpaper, Besitzprüfung des Anhangs, `reached` bei „nicht erreichbar“.

**Programme ohne Seiten-Köpfe:** nexmail hat keinen Tab- oder CSRF-Wächter; die Adapter schicken Programmen (OAuth,
`/api/connect/token|revoke|retire|hello`) keine Kopfzeile der Seite, die Vertragstests laufen so durch.

Nachzug 9bc9f73: updates 0.1.2 (`has_bell = False`, `UpdateSetupRow bell={false}`), mcp 1.1.1 (Rücksprungadressen,
Prüfsumme bei `approve`, `describe(arguments, caller)` mit Namen in der Sprache des Kontos, Mitteilung nur mit der Art
des Werkzeugs), verbinden 0.1.3 (`people.read`, Hostregel; nexmail nutzt den Zweck nicht), ki 0.1.1 (keine Änderung an
nexmails Wegen; `old_codes` greift nicht, siehe einst-fragen Nr. 14).

Nachzug 80a3dd0: schluessel 1.1.1 (ein Wortlaut für Bereiche), mcp 1.1.2 (`key_defaults` mit den Postfächern im
Vertrag, `sender` ohne `NEXMAIL_CLIENT_IP` leer, falsche Schlüssel dann je Schlüssel), verbinden 0.1.4
(`on_disconnected` löst nextasks-, nextime-Verbindung und nexfolk-Bücher einer beendeten Klick-Verbindung,
`set_local_allowed` für den Haken „Verbindungen ins eigene Netz“).

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
