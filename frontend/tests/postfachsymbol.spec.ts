/* Farbe und Symbol am Postfach wie in nextasks (24.11.2026). Der Wähler im
 * Postfach-Fenster schickt Farbe und Symbol mit; ohne Symbol bleibt der Punkt.
 *
 * ⚠️ Das Speichern wird abgefangen: Die Postfächer der Testdaten bleiben, wie
 * sie sind.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/postfachsymbol.spec.ts --project=desktop --reporter=line
 */
import { expect, test } from '@playwright/test'
import { anmelden, zuEinstellungen } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Das Postfach-Fenster wird breit geprüft.')
})

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('Symbol und Farbe wählen, „Kein Symbol“ ist die Vorgabe', async ({ page }) => {
  const gesendet: Array<Record<string, unknown>> = []
  await page.route('**/api/konten/*', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const rumpf = route.request().postDataJSON() as Record<string, unknown>
    gesendet.push(rumpf)
    const vorher = await (await route.fetch({ method: 'GET', url: route.request().url().replace(/\/[^/]+$/, '') })).json()
    const konto = (vorher as Array<Record<string, unknown>>)[0]
    await route.fulfill({ json: { ...konto, farbton: rumpf.farbton, symbol: rumpf.symbol } })
  })
  await anmelden(page)
  await zuEinstellungen(page)

  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()
  const fenster = page.getByRole('dialog')
  await expect(fenster.getByRole('button', { name: 'Kein Symbol' })).toHaveAttribute('aria-pressed', 'true')
  await expect(fenster.getByRole('button', { name: /Automatisch/ })).toHaveAttribute('aria-pressed', 'true')

  await fenster.getByRole('textbox', { name: 'Symbol suchen' }).fill('aktentasche')
  await fenster.getByRole('button', { name: 'briefcase' }).click()
  await fenster.getByRole('button', { name: 'Türkis' }).click()
  await fenster.getByRole('button', { name: 'Änderungen speichern' }).click()

  await expect.poll(() => gesendet.length).toBe(1)
  expect(gesendet[0]).toMatchObject({ farbton: 'teal', symbol: 'briefcase' })
})
