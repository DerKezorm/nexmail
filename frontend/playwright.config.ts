/* Oberflächen-Tests im echten Browser.
 *
 * ⚠️ **jsdom hätte keinen einzigen der bisherigen Fehler gefunden.** Eine
 * abgeschnittene Beschriftung, eine weiße Auswahlliste auf schwarzem Grund,
 * ein Bild mit kaputter Quelle, ein Knopf ohne Wirkung — das sind alles
 * Fragen an ein echtes Layout und eine echte Zeichnung. Deshalb Playwright
 * und kein Attrappen-DOM.
 *
 * Vorbedingung: Der Entwicklungsserver läuft (Port 5175) und das Backend
 * (Port 8010) zeigt auf ein eingerichtetes `data-dev`. Die Zugangsdaten
 * stehen in `NEXMAIL_TEST_USER` / `NEXMAIL_TEST_PASS` oder in
 * `tests/.zugang` — beides **nie** im Repo.
 * `npm run test:ui` startet den Frontend-Server bei Bedarf selbst.
 */
import { existsSync, readFileSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

/* ⚠️ **Die Zugangsdaten stehen in einer Datei, die nie mitgeht.**
 * `tests/.zugang` liegt in `.gitignore`, und der Benutzername der eigenen
 * Entwicklungsumgebung steht auf der Tabu-Liste des
 * Veroeffentlichungs-Waechters — wanderte die Datei je in den Index, schlaegt
 * `test_veroeffentlichung.py` an. Nachgeprueft am 01.09.2026, indem sie
 * absichtlich einmal hineingelegt wurde.
 *
 * Ohne die Datei gelten die neutralen Vorgaben aus `anmeldung.setup.ts`. Auf
 * einer fremden Installation ist das richtig; hier waere es falsch, und man
 * merkt es an einer Anmeldung, die nicht durchgeht.
 */
const zugang = new URL('./tests/.zugang', import.meta.url)
if (existsSync(zugang)) {
  for (const zeile of readFileSync(zugang, 'utf-8').split(/\r?\n/)) {
    const treffer = /^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/.exec(zeile)
    if (treffer && !process.env[treffer[1]]) process.env[treffer[1]] = treffer[2]
  }
}

/* ⚠️ **Welche Datei zu welcher Breite gehört, und warum das hier steht.**
 *
 * Acht Dateien überspringen ihre Tests im `beforeEach`, wenn das Projekt
 * `schmal` heißt; `wischen.spec.ts` macht es umgekehrt. Das ist richtig und
 * bleibt auch stehen — der Grund gehört an den Test. Nur: Playwright kommt
 * dabei trotzdem so weit, für jeden dieser Tests einen Browser aufzumachen,
 * eine Ablaufaufzeichnung zu beginnen und alles wieder abzuräumen. Gemessen
 * am 03.09.2026: rund 2,2 Sekunden je Test, der nichts tut. Bei 55 solchen
 * Tests sind das gut zwei Minuten je Lauf, in denen nichts geprüft wird.
 *
 * ⚠️ **Es fällt weder etwas weg noch etwas hinzu.** Dieselben Tests laufen in
 * denselben Breiten wie vorher; sie werden nur nicht mehr eingesammelt, um
 * gleich darauf übersprungen zu werden.
 *
 * ⚠️ **Zwei Listen, die auseinanderlaufen können.** Eine vergessene Zeile
 * macht den Lauf nur wieder langsamer, eine zu viel nimmt eine echte Prüfung
 * weg — und beides meldet niemand. `src/test/breiten.test.ts` hält die Liste
 * hier gegen die `test.skip`-Zeilen in den Dateien.
 */
const NUR_BREIT = [
  'adressfeld.spec.ts',
  'durchtragen.spec.ts',
  'handeln.spec.ts',
  'kalender.spec.ts',
  'mehrbenutzer.spec.ts',
  'oauth.spec.ts',
  'sicherungen.spec.ts',
  'umzug.spec.ts',
]
const NUR_SCHMAL = ['wischen.spec.ts']

export default defineConfig({
  testDir: './tests',
  // Ein Lauf soll unter einer Minute bleiben - sonst wird er nicht benutzt.
  timeout: 30_000,
  expect: { timeout: 7_000 },
  // ⚠️ Keine Parallelität: Die Tests arbeiten auf **einem** echten Postfach.
  // Zwei gleichzeitige Läufe würden sich gegenseitig die Ordner umräumen.
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5175',
    locale: 'de-DE',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    // ⚠️ **Einmal anmelden, dann weiterreichen.** Je Test neu anzumelden
    // laeuft in nexmails eigene Anmeldebremse - der Testlauf meldet dann
    // einen Fehler, den es nicht gibt.
    { name: 'anmeldung', testMatch: /anmeldung\.setup\.ts/ },
    {
      name: 'desktop',
      dependencies: ['anmeldung'],
      testIgnore: NUR_SCHMAL,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: 'tests/.sitzung.json',
      },
    },
    {
      name: 'schmal',
      dependencies: ['anmeldung'],
      testIgnore: NUR_BREIT,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 420, height: 860 },
        storageState: 'tests/.sitzung.json',
      },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5175',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
