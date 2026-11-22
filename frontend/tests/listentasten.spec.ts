/* Strg+A in der Mailliste und die Postfachgruppen als Reiter (22.11.2026). */
import { expect, test } from '@playwright/test'
import { anmelden } from './hilfen'

test.beforeEach(({}, info) => {
  test.skip(info.project.name === 'schmal', 'Tastatur und Reiterleiste werden breit geprüft.')
})

test('Strg+A markiert alle geladenen Mails, im Suchfeld bleibt es Text markieren', async ({ page }) => {
  await anmelden(page)
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible({ timeout: 15_000 })
  const anzahl = await zeilen.count()

  // Im Suchfeld gehört Strg+A dem Text: Es wird nichts ausgewählt.
  const suche = page.getByPlaceholder(/Suchen|Search/).first()
  await suche.fill('abc')
  await suche.press('Control+a')
  await expect(page.getByText(/\d+ ausgewählt/)).toHaveCount(0)
  await suche.fill('')

  await zeilen.first().click()
  await page.keyboard.press('Control+a')
  await expect(page.getByText(`${anzahl} ausgewählt`)).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(page.getByText(/\d+ ausgewählt/)).toHaveCount(0)
})

test('Die Postfachgruppen stehen als Reiter über der Ansicht, nicht als Pillen im Baum', async ({ page }) => {
  await anmelden(page)
  const reiter = page.getByTestId('postfachgruppen')
  // ⚠️ Erst zählen, wenn die Postfächer geladen sind: Vorher steht nie ein Reiter da.
  await expect(page.getByRole('button', { name: /Postfach hinzufügen/ }).first()).toBeVisible({ timeout: 15_000 })
  // Erst ab zwei Schlagworten an Postfächern; ohne gibt es nichts zu prüfen.
  test.skip((await reiter.count()) === 0, 'Diese Daten haben keine zwei Postfachgruppen.')

  await expect(reiter.getByRole('tab').first()).toHaveText(/^Alle/)
  await expect(reiter.getByRole('tab', { selected: true })).toHaveText(/^Alle/)
  // In der Ordnerspalte steht der Umschalter nicht mehr.
  await expect(page.getByRole('group', { name: /Schlagwort|tag/i })).toHaveCount(0)

  const zweiter = reiter.getByRole('tab').nth(1)
  await zweiter.click()
  await expect(zweiter).toHaveAttribute('aria-selected', 'true')
  // Zurück auf „Alle", damit der nächste Test nicht gefiltert anfängt.
  await reiter.getByRole('tab').first().click()
  await expect(reiter.getByRole('tab').first()).toHaveAttribute('aria-selected', 'true')
})
