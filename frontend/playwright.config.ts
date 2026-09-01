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
 * stehen in `NEXMAIL_TEST_USER` / `NEXMAIL_TEST_PASS` (Vorgabe:
 * `betreiber`/`betreiber`) — nicht im Repo.
 * `npm run test:ui` startet den Frontend-Server bei Bedarf selbst.
 */
import { defineConfig, devices } from '@playwright/test'

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
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: 'tests/.sitzung.json',
      },
    },
    {
      name: 'schmal',
      dependencies: ['anmeldung'],
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
