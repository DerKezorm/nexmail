/* Strg+A in der Mailliste und die Postfachgruppen als Reiter (22.11.2026). */
import { expect, test } from '@playwright/test'
import { anmelden, zurAnsicht } from './hilfen'

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
  await expect(page.getByTestId('profilzeile').first()).toBeVisible({ timeout: 15_000 })
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

/* ⚠️ **Strg K springt in die Suche, wie in nexnotes, nextasks und nextime**
   (seit 23.11.2026), in jeder Ansicht mit Suchfeld; die Befehlspalette liegt
   seitdem auf Strg Umschalt P. Strg F bleibt dazu. */
test('Strg K und Strg F springen in die Suche, die Palette liegt auf Strg Umschalt P', async ({ page }) => {
  await anmelden(page)
  const suche = page.getByPlaceholder(/^(Suchen|Search)$/).first()
  await expect(suche).toBeVisible()
  await expect(page.locator('header kbd').first()).toHaveText(/^(Strg K|Ctrl K|⌘ K)$/)

  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('Control+k')
  await expect(suche).toBeFocused()
  // Die Palette geht dabei NICHT auf.
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('Control+f')
  await expect(suche).toBeFocused()

  await page.keyboard.press('Control+Shift+P')
  await expect(page.getByRole('dialog').getByRole('combobox')).toBeVisible()
  await page.keyboard.press('Control+Shift+P')

  // Auch im Kalender springt Strg K in dessen Suche.
  await zurAnsicht(page, 'Kalender')
  // Der Kalender lädt nach; erst drücken, wenn sein Suchfeld dasteht.
  const kalenderSuche = page.getByPlaceholder(/Termine suchen|Search events/)
  await expect(kalenderSuche).toBeVisible()
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('Control+k')
  await expect(kalenderSuche).toBeFocused()
})
