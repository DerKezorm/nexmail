/* Die Ersteinrichtung — der einzige Bildschirm, den jeder Betreiber sieht.
 *
 * ⚠️ **Er wird von den anderen Tests nie erreicht**: Die laufen gegen eine
 * eingerichtete Installation. Deshalb hier gegen den frischen Container auf
 * 5174, der noch keinen Benutzer hat.
 *
 * ⚠️ **Aus Schaden entstanden, 01.09.2026.** Der Weiter-Knopf war gesperrt,
 * weil das Kennwort ein Zeichen zu kurz war — der Grund stand aber unter dem
 * Formular, nicht am Feld. Anna las ihn und bezog ihn nicht auf das
 * Kennwort: „hier ist Ende".
 */
import { expect, test } from '@playwright/test'

const CONTAINER = 'http://localhost:5174'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }) => {
  const antwort = await page.request.get(`${CONTAINER}/api/setup/status`).catch(() => null)
  test.skip(!antwort?.ok(), 'Der Container auf 5174 läuft nicht.')
  const stand = await antwort!.json()
  test.skip(stand.eingerichtet, 'Der Container ist schon eingerichtet.')
  await page.goto(CONTAINER)
})

test('Ein zu kurzes Kennwort wird am Feld selbst gemeldet', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  await page.getByRole('textbox', { name: 'Benutzername' }).fill('admin')
  const kennwort = page.locator('input[type="password"]').first()
  await kennwort.fill('123456789') // neun Zeichen

  /* Der Grund muss **beim Kennwortfeld** stehen — nicht nur unten. Gemessen
     wird der Abstand: Steht er weiter als eine Feldhöhe entfernt, bezieht ihn
     niemand mehr darauf. */
  const meldung = page.getByText(/Noch 1 Zeichen/).first()
  await expect(meldung, 'Kein Hinweis, warum es nicht weitergeht.').toBeVisible()

  const abstand = await page.evaluate(() => {
    const feld = document.querySelector<HTMLElement>('input[type="password"]')
    const texte = Array.from(document.querySelectorAll<HTMLElement>('span, p'))
    const hinweis = texte.find((e) => /Noch 1 Zeichen/.test(e.textContent ?? ''))
    if (!feld || !hinweis) return null
    return hinweis.getBoundingClientRect().top - feld.getBoundingClientRect().bottom
  })
  expect(abstand, 'Hinweis oder Feld nicht gefunden').not.toBeNull()
  expect(
    abstand!,
    `Der Hinweis steht ${Math.round(abstand!)}px unter dem Kennwortfeld — zu weit weg, um ihn darauf zu beziehen.`,
  ).toBeLessThan(40)
})

test('Mit zehn Zeichen geht es weiter', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  await page.getByRole('textbox', { name: 'Benutzername' }).fill('admin')
  const felder = page.locator('input[type="password"]')
  await felder.nth(0).fill('1234567890')
  await felder.nth(1).fill('1234567890')

  await expect(
    page.getByRole('button', { name: 'Weiter' }),
    'Zehn Zeichen, gleich getippt — der Knopf muss frei sein.',
  ).toBeEnabled()
})
