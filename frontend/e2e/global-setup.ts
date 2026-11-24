/** Legt den Betreiber an und merkt sich seine Sitzung (das Cookie `nexmail_sitzung`) für die Tests. */
import { request } from '@playwright/test'

export default async function globalSetup(): Promise<void> {
  const context = await request.newContext({ baseURL: 'http://127.0.0.1:8496' })
  const made = await context.post('/api/setup/konto', {
    data: {
      benutzername: 'betreiber',
      anzeigename: 'Betreiber',
      passwort: process.env.NEXMAIL_E2E_PASSWORD,
      // Kontenmodul: das erste Konto braucht den Einrichtungscode (die Instanz bekommt NEXMAIL_SETUP_TOKEN).
      einrichtungscode: process.env.NEXMAIL_SETUP_TOKEN,
    },
  })
  if (!made.ok()) throw new Error(`setup failed: ${made.status()} ${await made.text()}`)
  await context.storageState({ path: process.env.NEXMAIL_E2E_STATE })
  await context.dispose()
}
