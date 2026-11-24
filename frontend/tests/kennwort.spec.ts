/* Passwort ändern unter Einstellungen → Sicherheit.
 *
 * ⚠️ Die Schnittstelle gab es seit Stufe 0, einen Dialog erst seit 0.23.0.
 *
 * ⚠️ **Geprüft wird nur der Weg, der nichts ändert.** Ein echter Wechsel
 * änderte das Passwort des Entwicklungsbenutzers, und jeder spätere Lauf
 * scheiterte an der Anmeldung. Der gute Weg steht im Server
 * (`test_anmeldung.py`); hier zählt, dass der Dialog die Eingaben bis zum
 * Server trägt und dessen Absage benannt zeigt.
 */
import { expect, test } from '@playwright/test'
import { anmelden, bereich, jederKnopfHatEinenNamen, keineRohenSchluessel, zuEinstellungen } from './hilfen'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Einstellungen werden breit geprüft.')
  await anmelden(page)
  await zuEinstellungen(page)
  await bereich(page, 'Sicherheit')
})

test('Ein falsches bisheriges Passwort wird benannt abgewiesen', async ({ page }) => {
  await page.getByRole('button', { name: 'Passwort ändern' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  await jederKnopfHatEinenNamen(page)

  const knopf = fenster.getByRole('button', { name: 'Passwort ändern' })
  await fenster.getByLabel('Bisheriges Passwort').fill('sicher-nicht-das-kennwort-1')
  await fenster.getByLabel('Neues Passwort').fill('ein-neues-kennwort-42')
  await fenster.getByLabel('Passwort wiederholen').fill('ein-anderes-kennwort-42')

  // Zwei verschiedene neue Passwörter: Der Knopf bleibt zu, und der Grund steht da.
  await expect(knopf).toBeDisabled()
  await expect(fenster.getByRole('alert')).toContainText('stimmen nicht überein')

  await fenster.getByLabel('Passwort wiederholen').fill('ein-neues-kennwort-42')
  await expect(knopf).toBeEnabled()

  const antwort = page.waitForResponse(
    (r) => r.url().includes('/api/auth/passwort') && r.request().method() === 'PUT',
  )
  await knopf.click()
  expect((await antwort).status()).toBe(400)
  await expect(fenster.getByRole('alert')).toHaveText('Das bisherige Passwort stimmt nicht.')
  await keineRohenSchluessel(page)

  await fenster.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(fenster).toBeHidden()
})
