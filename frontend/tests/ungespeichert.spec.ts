/* Postfach-Fenster: Wer etwas geändert hat, wird vor dem Schließen gefragt
 * (gemeldet am 22.11.2026). Und die Gruppen-Reiter lassen sich ziehen. */
import { expect, test } from '@playwright/test'
import { anmelden, zuEinstellungen } from './hilfen'

test.beforeEach(({}, info) => {
  test.skip(info.project.name === 'schmal', 'Fenster und Ziehen werden breit geprüft.')
})

test('Ungespeicherte Änderungen im Postfach-Fenster: erst fragen, dann schließen', async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page, 'Postfächer')
  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()
  const fenster = page.getByRole('dialog').filter({ hasText: 'Postfach bearbeiten' })
  await expect(fenster).toBeVisible()

  // Nichts geändert: Escape schließt ohne Rückfrage.
  await page.keyboard.press('Escape')
  await expect(fenster).toHaveCount(0)

  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()
  await expect(fenster).toBeVisible()
  const name = fenster.getByLabel(/Bezeichnung des Postfachs/)
  await name.fill((await name.inputValue()) + ' geändert')

  // Geändert: Escape fragt, „Abbrechen" lässt das Fenster mit der Änderung stehen.
  await page.keyboard.press('Escape')
  const frage = page.getByRole('dialog').filter({ hasText: 'Änderungen verwerfen?' })
  await expect(frage).toBeVisible()
  await frage.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(frage).toHaveCount(0)
  await expect(fenster).toBeVisible()
  await expect(name).toHaveValue(/ geändert$/)

  // Das Kreuz fragt genauso; „Verwerfen" schließt, gespeichert wird nichts.
  await fenster.getByRole('button', { name: 'Schließen' }).click()
  await expect(frage).toBeVisible()
  await frage.getByRole('button', { name: 'Verwerfen' }).click()
  await expect(fenster).toHaveCount(0)
  await expect(page.getByText(/ geändert/)).toHaveCount(0)
})

test('Gruppen-Reiter lassen sich ziehen, und die Reihenfolge bleibt', async ({ page }) => {
  await anmelden(page)
  await expect(page.getByRole('button', { name: /Postfach hinzufügen/ }).first()).toBeVisible({ timeout: 15_000 })
  const leiste = page.getByTestId('postfachgruppen')
  test.skip((await leiste.count()) === 0, 'Diese Daten haben keine zwei Postfachgruppen.')
  const reiter = leiste.locator('[data-gruppe]')
  const vorher = await reiter.evaluateAll((r) => r.map((e) => e.getAttribute('data-gruppe')))
  test.skip(vorher.length < 2, 'Zum Ziehen braucht es zwei Gruppen.')

  try {
    const gespeichert = page.waitForResponse((r) => r.url().includes('/api/auth/ich/gruppen'))
    await reiter.nth(vorher.length - 1).dragTo(reiter.nth(0))
    expect((await gespeichert).status()).toBe(200)
    const erwartet = [vorher[vorher.length - 1], ...vorher.slice(0, -1)]
    await expect.poll(() => reiter.evaluateAll((r) => r.map((e) => e.getAttribute('data-gruppe')))).toEqual(erwartet)

    // Nach dem Neuladen kommt sie vom Server, nicht aus dem Browser.
    await page.reload()
    await expect.poll(() => reiter.evaluateAll((r) => r.map((e) => e.getAttribute('data-gruppe'))), {
      timeout: 15_000,
    }).toEqual(erwartet)
    // „Alle" bleibt vorn und lässt sich nicht ziehen.
    await expect(leiste.getByRole('tab').first()).toHaveText(/^Alle/)
    await expect(leiste.locator('[draggable="true"]').first()).toHaveAttribute('data-gruppe', erwartet[0] ?? '')
  } finally {
    await page.evaluate(() =>
      fetch('/api/auth/ich/gruppen', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ reihenfolge: [] }),
      }),
    )
  }
})
