/* Ende-zu-Ende für die Anmeldung über Anbieter, kopflos.
 *
 * ⚠️ **Nicht die Reihe aus `tests/`.** Die braucht `data-dev` und ein echtes Postfach; diese hier nicht. Die gebaute
 * Oberfläche kommt vom echten Server wie im Container (`NEXMAIL_STATIC_DIR` auf `dist`), mit eigenem Datenordner und
 * eigenem Port, daneben ein nachgebauter Anbieter (`e2e/fake-oidc.mjs`) unter `localhost`: eine andere Site als
 * nexmail unter `127.0.0.1`, wie ein echter. Nie ein echter Anbieter, nie das Netz, nie `data/` oder `data-dev/`.
 *
 *   npm run build
 *   npx playwright test -c playwright.nexoidc.config.ts
 */
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { defineConfig } from '@playwright/test'

export const PORT = 8496
export const PROVIDER_PORT = 8497

function datenordner(): string {
  if (process.env.NEXMAIL_E2E_DATA) return process.env.NEXMAIL_E2E_DATA
  const ordner = fs.mkdtempSync(path.join(process.env.NEXMAIL_E2E_TMP || os.tmpdir(), 'nexmail-e2e-'))
  process.env.NEXMAIL_E2E_DATA = ordner
  // Das Kennwort des Betreibers, je Lauf neu; die Tests lesen es aus der Umgebung.
  process.env.NEXMAIL_E2E_PASSWORD = randomBytes(12).toString('base64url')
  return ordner
}

const DATEN = datenordner()
const ANGEMELDET = path.join(DATEN, 'e2e-betreiber.json')
process.env.NEXMAIL_E2E_STATE = ANGEMELDET
const python = path.join('.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    headless: true,
    locale: 'de-DE',
    storageState: ANGEMELDET,
    // Ein schon vorhandener Chromium, wenn der zur Playwright-Fassung fehlt (nie ein Download im Lauf).
    launchOptions: process.env.NEXMAIL_E2E_CHROMIUM ? { executablePath: process.env.NEXMAIL_E2E_CHROMIUM } : {},
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
      cwd: path.join('..', 'backend'),
      url: `http://127.0.0.1:${PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXMAIL_DATA_DIR: path.join(DATEN, 'data'),
        NEXMAIL_STATIC_DIR: path.resolve('dist'),
        NEXMAIL_SECRET_KEY: randomBytes(24).toString('base64url'),
        NEXMAIL_TAKT_SEKUNDEN: '0',
        NEXMAIL_URL_BASE: '',
        NEXMAIL_CLIENT_IP: '',
      },
    },
    {
      command: 'node e2e/fake-oidc.mjs',
      url: `http://localhost:${PROVIDER_PORT}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
      env: { FAKE_OIDC_PORT: String(PROVIDER_PORT) },
    },
  ],
})
