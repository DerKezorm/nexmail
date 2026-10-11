/* Kennwort ändern unter Einstellungen → Sicherheit.
 *
 * ⚠️ Die Schnittstelle gab es seit Stufe 0, einen Dialog erst seit 0.23.0.
 *
 * ⚠️ **Geprüft wird nur der Weg, der nichts ändert.** Ein echter Wechsel
 * änderte das Kennwort des Entwicklungsbenutzers, und jeder spätere Lauf
 * scheiterte an der Anmeldung. Der gute Weg steht im Server
 * (`test_anmeldung.py`); hier zählt, dass der Dialog die Eingaben bis zum
 * Server trägt und dessen Absage benannt zeigt.
 */
import { expect, test } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keineRohenSchluessel, zuEinstellungen } from './hilfen'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Einstellungen werden breit geprüft.')
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Sicherheit' }).click()
})

test('Ein falsches bisheriges Kennwort wird benannt abgewiesen', async ({ page }) => {
  await page.getByRole('button', { name: 'Kennwort ändern' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  await jederKnopfHatEinenNamen(page)

  const knopf = fenster.getByRole('button', { name: 'Kennwort ändern' })
  await fenster.getByLabel('Bisheriges Kennwort').fill('sicher-nicht-das-kennwort-1')
  await fenster.getByLabel('Neues Kennwort').fill('ein-neues-kennwort-42')
  await fenster.getByLabel('Kennwort wiederholen').fill('ein-anderes-kennwort-42')

  // Zwei verschiedene neue Kennwörter: Der Knopf bleibt zu, und der Grund steht da.
  await expect(knopf).toBeDisabled()
  await expect(fenster.getByRole('alert')).toContainText('stimmen nicht überein')

  await fenster.getByLabel('Kennwort wiederholen').fill('ein-neues-kennwort-42')
  await expect(knopf).toBeEnabled()

  const antwort = page.waitForResponse(
    (r) => r.url().includes('/api/auth/passwort') && r.request().method() === 'PUT',
  )
  await knopf.click()
  expect((await antwort).status()).toBe(400)
  await expect(fenster.getByRole('alert')).toHaveText('Das bisherige Kennwort stimmt nicht.')
  await keineRohenSchluessel(page)

  await fenster.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(fenster).toBeHidden()
})
