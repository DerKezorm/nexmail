/* Darstellung „Wie das System“ (24.11.2026, wie nexnotes und nextasks): nexmail
 * folgt hell/dunkel des Systems, auch wenn es während der Sitzung umschaltet.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/systemmodus.spec.ts --project=desktop --reporter=line
 */
import { expect, test } from '@playwright/test'
import { anmelden, bereich, zuEinstellungen } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird breit geprüft.')
})

test('„Wie das System“ folgt dem System, auch beim Umschalten', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await anmelden(page)
  await zuEinstellungen(page, 'Darstellung')
  await bereich(page, 'Darstellung')

  const html = page.locator('html')
  await page.getByRole('radio', { name: 'Dunkel' }).click()
  await expect(html).not.toHaveAttribute('data-theme', 'light')

  await page.getByRole('radio', { name: 'Wie das System' }).click()
  await expect(html).toHaveAttribute('data-theme', 'light')
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(html).not.toHaveAttribute('data-theme', 'light')

  // Die Wahl bleibt nach dem Neuladen.
  await page.reload()
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(html).toHaveAttribute('data-theme', 'light')

  // Zurück auf die Vorgabe der Testdaten.
  await zuEinstellungen(page, 'Darstellung')
  await bereich(page, 'Darstellung')
  await page.getByRole('radio', { name: 'Dunkel' }).click()
  await expect(html).not.toHaveAttribute('data-theme', 'light')
})
