/* Gelöschte Mails verschwinden sofort, nicht erst, wenn der Server fertig ist
 * (22.11.2026). Der Server wird hier abgefangen: Er antwortet absichtlich
 * spät oder mit einer Absage, und nichts wird wirklich gelöscht. */
import { expect, test } from '@playwright/test'
import { anmelden } from './hilfen'

// eslint-disable-next-line no-empty-pattern -- Playwright verlangt die Zerlegung der Fixtures
test.beforeEach(({}, info) => {
  test.skip(info.project.name === 'schmal', 'Tastatur und Liste werden breit geprüft.')
})

test('Entf nimmt die Mail sofort aus der Liste, auch wenn der Server noch arbeitet', async ({ page }) => {
  await anmelden(page)
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible({ timeout: 15_000 })
  const vorher = await zeilen.count()
  const betreff = (await zeilen.first().innerText()).split('\n').slice(0, 2).join(' ')

  // Der Server lässt sich drei Sekunden Zeit und sagt dann „erledigt".
  await page.route('**/api/nachrichten/loeschen', async (route) => {
    await new Promise((r) => setTimeout(r, 3000))
    await route.fulfill({ json: { bewegt: 1, rueckweg: null } })
  })

  await zeilen.first().click()
  const start = Date.now()
  await page.keyboard.press('Delete')
  await expect(zeilen).toHaveCount(vorher - 1, { timeout: 1000 })
  expect(Date.now() - start, 'Die Zeile wartete auf den Server.').toBeLessThan(1000)
  // Die gelöschte Zeile ist weg, nicht irgendeine.
  await expect(zeilen.first()).not.toHaveText(betreff)
})

test('Sagt der Server ab, steht die Mail wieder da, mit dem Grund', async ({ page }) => {
  await anmelden(page)
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible({ timeout: 15_000 })
  const vorher = await zeilen.count()

  await page.route('**/api/nachrichten/loeschen', async (route) => {
    await new Promise((r) => setTimeout(r, 500))
    await route.fulfill({ status: 400, json: { detail: 'rolle_ohne_ordner', werte: { rolle: 'papierkorb' } } })
  })

  await zeilen.first().click()
  await page.keyboard.press('Delete')
  await expect(zeilen).toHaveCount(vorher - 1, { timeout: 1000 })
  // Nach der Absage holt das Nachladen sie zurück, und die Meldung steht da.
  await expect(zeilen).toHaveCount(vorher, { timeout: 10_000 })
  await expect(page.getByRole('alert').or(page.getByText(/Papierkorb/)).first()).toBeVisible()
})

test('Die Rückgängig-Leiste steht sofort da, und ein früher Klick wartet auf den Server', async ({ page }) => {
  await anmelden(page)
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible({ timeout: 15_000 })

  const rueckweg = { konto_id: 'probe', quelle_pfad: 'INBOX', ziel_pfad: 'Trash', message_ids: ['<probe@example.com>'], text: '' }
  await page.route('**/api/nachrichten/loeschen', async (route) => {
    await new Promise((r) => setTimeout(r, 2500))
    await route.fulfill({ json: { bewegt: 1, rueckweg } })
  })
  const zurueck: unknown[] = []
  await page.route('**/api/nachrichten/zurueck', async (route) => {
    zurueck.push(route.request().postDataJSON())
    await route.fulfill({ json: { bewegt: 1, rueckweg: null } })
  })

  await zeilen.first().click()
  await page.keyboard.press('Delete')
  // Die Leiste kommt mit der Zeile, nicht erst mit der Antwort des Servers.
  const leiste = page.getByRole('status').filter({ hasText: 'In den Papierkorb gelegt' })
  await expect(leiste).toBeVisible({ timeout: 700 })

  // Geklickt, bevor der Server fertig ist: Das Zurückholen geht los, sobald
  // der Rückweg da ist, und zwar mit genau diesem Rückweg.
  await leiste.getByRole('button', { name: 'Rückgängig' }).click()
  await expect(leiste).toHaveCount(0)
  expect(zurueck).toHaveLength(0)
  await expect.poll(() => zurueck.length, { timeout: 8000 }).toBe(1)
  expect(zurueck[0]).toMatchObject({ ziel_pfad: 'Trash', message_ids: ['<probe@example.com>'] })
})
