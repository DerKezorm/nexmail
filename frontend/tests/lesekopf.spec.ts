/* Der Kopf der geöffneten Mail am Telefon.
 *
 * ⚠️ Bis 0.22.2 stand das lange Datum („Samstag, 10. Oktober 2026 um 14:32")
 * neben dem Absender und schrumpfte nicht. Bei 390 px blieben der Spalte mit
 * Name und Adresse 82 px, und die Adresse lief 76 px aus ihr heraus in die
 * Spalte des Datums. Jetzt rutscht das Datum in eine eigene Zeile.
 *
 * Gemessen wird an den Kästen, nicht am Bild: Kein Text der Absenderspalte
 * darf über ihren Rand hinaus und keiner in den Kasten des Datums.
 */
import { expect, test } from '@playwright/test'
import { anmelden } from './hilfen'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'schmal', 'Der Kopf wird in der schmalen Ansicht geprüft.')
  await page.setViewportSize({ width: 390, height: 844 })
  await anmelden(page)
})

test('Absender und Datum kommen sich bei 390 px nicht in die Quere', async ({ page }) => {
  const zeile = page.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible({ timeout: 15_000 })
  await zeile.click()

  const kopf = page.locator('header').filter({ has: page.locator('time') }).first()
  await expect(kopf.locator('time')).toBeVisible({ timeout: 15_000 })

  const m = await kopf.evaluate((el) => {
    const zeitEl = el.querySelector('time')!
    const zeit = zeitEl.getBoundingClientRect()
    // Die Spalte mit Name, Adresse und Empfängern steht direkt vor dem Datum.
    const spalte = zeitEl.previousElementSibling as HTMLElement
    const sp = spalte.getBoundingClientRect()
    const texte = [...spalte.querySelectorAll('span')]
      .map((s) => s.getBoundingClientRect())
      .filter((r) => r.width > 0)
    return {
      spalte: Math.round(sp.width),
      raus: Math.round(Math.max(...texte.map((r) => r.right)) - sp.right),
      ueberDatum: texte.some(
        (r) =>
          r.right > zeit.left + 0.5 &&
          r.left < zeit.right - 0.5 &&
          r.bottom > zeit.top + 0.5 &&
          r.top < zeit.bottom - 0.5,
      ),
    }
  })

  expect(m.raus, `Ein Text läuft ${m.raus} px aus der Absenderspalte.`).toBeLessThanOrEqual(0)
  expect(m.ueberDatum, 'Ein Text liegt im Kasten des Datums.').toBe(false)
  expect(m.spalte, 'Die Absenderspalte ist zu schmal zum Lesen.').toBeGreaterThanOrEqual(190)
})
