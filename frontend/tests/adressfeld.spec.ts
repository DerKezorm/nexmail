/* Adress-Blasen im Verfassen-Fenster.
 *
 * ⚠️ **Entstanden aus einer Erwartung, nicht aus einem Absturz** (02.09.2026):
 * „wenn ich hier jetzt enter drücke müsste daraus eine bubble werden". Vorher
 * war das Feld eine Komma-Textzeile; Enter tat nichts, und
 * „test@web.de blablabla" ging als EINE kaputte Adresse durch, sichtbar erst
 * beim Senden.
 */
import { expect, test } from '@playwright/test'
import { anmelden } from './hilfen'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  await anmelden(page)
})

test('Enter macht eine Blase, Unsinn wird rot, Rückschritt öffnet wieder', async ({ page }) => {
  await page.getByRole('button', { name: 'Neue Nachricht' }).click()
  const feld = page.getByLabel('Name oder Adresse').first()

  await feld.fill('erste@example.com')
  await feld.press('Enter')
  // Die Folge: eine Blase mit Entfernen-Knopf, das Tippfeld ist wieder leer.
  await expect(
    page.getByRole('button', { name: 'erste@example.com entfernen' }),
  ).toBeVisible()
  await expect(feld).toHaveValue('')

  // Unsinn wird eine ROTE Blase - sichtbar, nicht erst beim Senden.
  await feld.fill('kein-adresse-nur-text')
  await feld.press('Enter')
  const kaputt = page
    .locator('span', { hasText: 'kein-adresse-nur-text' })
    .locator('xpath=ancestor-or-self::span[contains(@class, "danger")]')
    .first()
  await expect(kaputt).toBeVisible()

  // Rückschritt im leeren Feld öffnet die letzte Blase wieder zum Bearbeiten.
  await feld.press('Backspace')
  await expect(feld).toHaveValue('kein-adresse-nur-text')
  await expect(
    page.getByRole('button', { name: 'kein-adresse-nur-text entfernen' }),
  ).toHaveCount(0)

  // Und das Entfernen-Kreuz entfernt genau seine Blase.
  await feld.fill('zweite@example.com')
  await feld.press('Enter')
  await page.getByRole('button', { name: 'zweite@example.com entfernen' }).click()
  await expect(
    page.getByRole('button', { name: 'zweite@example.com entfernen' }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'erste@example.com entfernen' }),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Verwerfen' }).click()
})
