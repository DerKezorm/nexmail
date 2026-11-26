/* Web Push: Wenn der Browser selbst ablehnt, steht da, woran (Issue #10).
 *
 * Gemeldet am 12.10.2026 von einem Mac: Erlaubnis erteilt, „Register this
 * device" geklickt, „That did not work." und keine einzige Anfrage an den
 * Server. Der Browser hatte abgelehnt, und `servermeldung` kannte nur
 * Absagen des Servers.
 *
 * ⚠️ **Der Browser wird hier zum Scheitern gebracht, nicht gemessen.** Ein
 * kopfloses Chromium hat keinen Push-Dienst; ob `subscribe` dort scheitert,
 * hängt am Bau. Die Absage wird deshalb vor dem Laden der Seite eingesetzt,
 * mit Name und Satz wie bei einem echten Browser.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/pushfehler.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { anmelden, bereich, zuEinstellungen } from './hilfen'

async function zumReiter(page: Page) {
  /* ⚠️ **Kopflos meldet Chromium „denied“, auch nach `grantPermissions`.**
     Die Seite zeigte dann „abgelehnt“ statt des Knopfs aus dem Issue. Die
     Erlaubnis steht deshalb wie beim Melder: längst erteilt. */
  await page.addInitScript(() => {
    Object.defineProperty(Notification, 'permission', { get: () => 'granted' })
    Notification.requestPermission = () => Promise.resolve('granted')
  })
  await anmelden(page)
  await zuEinstellungen(page)
  await bereich(page, 'Benachrichtigungen')
}

function anmeldungenZaehlen(page: Page): { zahl: number } {
  const stand = { zahl: 0 }
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().includes('/api/push/anmelden')) stand.zahl += 1
  })
  return stand
}

test('ein abgelehnter Service Worker nennt seinen Grund', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.serviceWorker.register = () =>
      Promise.reject(new DOMException('The script has an unsupported MIME type', 'SecurityError'))
  })
  const anmeldungen = anmeldungenZaehlen(page)
  await zumReiter(page)

  // Seit „Auf welchem Weg“ (Bausatz NotifyWays): die Lage steht im Satz, der Knopf heißt wie überall; bei erteilter
  // Erlaubnis ohne Anmeldung holt er die Anmeldung nach (`nachholen`).
  await expect(page.getByText(/Erlaubt, aber nicht angemeldet/)).toBeVisible()
  await page.getByTestId('notify-browser-on').click()

  const kasten = page.getByText(/Service Worker von nexmail nicht starten/)
  await expect(kasten).toBeVisible()
  await expect(kasten).toContainText('SecurityError: The script has an unsupported MIME type')
  await expect(page.getByText('Das hat nicht geklappt.')).toHaveCount(0)
  expect(anmeldungen.zahl).toBe(0)
})

test('ein abgelehnter Push-Dienst nennt seinen Grund', async ({ page }) => {
  await page.addInitScript(() => {
    PushManager.prototype.getSubscription = () => Promise.resolve(null)
    PushManager.prototype.subscribe = () =>
      Promise.reject(new DOMException('Registration failed - push service error', 'AbortError'))
  })
  const anmeldungen = anmeldungenZaehlen(page)
  await zumReiter(page)

  // Seit „Auf welchem Weg“ (Bausatz NotifyWays): die Lage steht im Satz, der Knopf heißt wie überall; bei erteilter
  // Erlaubnis ohne Anmeldung holt er die Anmeldung nach (`nachholen`).
  await expect(page.getByText(/Erlaubt, aber nicht angemeldet/)).toBeVisible()
  await page.getByTestId('notify-browser-on').click()

  const kasten = page.getByText(/Push-Dienst des Browsers hat dieses Gerät nicht angenommen/)
  await expect(kasten).toBeVisible()
  await expect(kasten).toContainText('AbortError: Registration failed - push service error')
  expect(anmeldungen.zahl).toBe(0)
})
