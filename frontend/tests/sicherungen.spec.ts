/* Speicher und Sicherung (Modul sicherung 1.0.1, Bereich `storage`) und die Über-Seite, durchgetragen bis zur Wirkung.
 *
 * ⚠️ **Der Test hört nicht am Knopf auf.** Er macht eine Sicherung, findet sie in der Liste wieder und löscht sie:
 * angelegt und gespeichert sind hier zwei verschiedene Dinge, und kaputt ist erfahrungsgemäß das zweite.
 *
 * ⚠️ **Er räumt hinterher auf.** Eine Sicherung, die stehen bleibt, ist eine Datei je Lauf; nach einer Woche fragt
 * sich jemand, wohin die Platte verschwindet.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keinTextLaeuftUeber, serverabsagen, zuEinstellungen } from './hilfen'

const KENNWORT = process.env.NEXMAIL_TEST_PASS ?? 'betreiber'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  await anmelden(page)
})

async function zurSicherung(page: Page) {
  await zuEinstellungen(page, 'Speicher und Sicherung')
  await expect(page.getByTestId('backup-now')).toBeVisible({ timeout: 10_000 })
}

/** Die Namen der Sicherungen in der Liste, sobald sie geladen ist. */
async function namen(page: Page): Promise<string[]> {
  await expect(page.getByTestId('backup-last')).toBeVisible({ timeout: 10_000 })
  const ids = await page.locator('[data-testid^="backup-nexmail-"]').evaluateAll((zeilen) =>
    zeilen.map((z) => z.getAttribute('data-testid') ?? ''),
  )
  return ids.map((id) => id.replace(/^backup-/, ''))
}

/** sicherung 1.0.3 (E63): „Jetzt sichern" öffnet ein Fenster mit optionaler Notiz; erst „Sichern" legt an. */
async function sichernBestaetigen(page: Page): Promise<void> {
  const fenster = page.getByTestId('backup-confirm-make')
  await expect(fenster.getByTestId('backup-note')).toBeVisible()
  await fenster.getByRole('button', { name: 'Sichern', exact: true }).click()
}

test('Sicherung machen, wiederfinden, löschen', async ({ page }) => {
  const absagen = serverabsagen(page)
  await zurSicherung(page)
  const vorher = await namen(page)

  await page.getByTestId('backup-now').click()
  await sichernBestaetigen(page)
  await expect(page.getByText('Sicherung erstellt.')).toBeVisible({ timeout: 20_000 })
  await absagen.pruefen()

  // Die Wirkung: genau eine neue Zeile, als „von Hand“ gemacht.
  await expect.poll(async () => (await namen(page)).filter((n) => !vorher.includes(n)).length, { timeout: 10_000 }).toBe(1)
  const neu = (await namen(page)).find((n) => !vorher.includes(n))!
  const zeile = page.getByTestId(`backup-${neu}`)
  await expect(zeile).toContainText('von Hand')

  // --- Aufräumen, und das ist zugleich der Test des Löschens ------------ //
  await zeile.getByRole('button', { name: 'Löschen', exact: false }).click()
  const frage = page.getByTestId('backup-confirm-delete')
  await expect(frage).toContainText('Sie lässt sich nicht zurückholen.')
  await frage.getByLabel('Dein Passwort').fill(KENNWORT)
  await frage.getByRole('button', { name: 'Löschen', exact: true }).click()
  await expect(page.getByTestId(`backup-${neu}`)).toHaveCount(0, { timeout: 10_000 })
  expect(await namen(page)).toEqual(vorher)
})

test('Wiederherstellen fragt erst und fasst beim Abbrechen nichts an', async ({ page }) => {
  await zurSicherung(page)
  if (!(await namen(page)).length) {
    await page.getByTestId('backup-now').click()
    await sichernBestaetigen(page)
    await expect(page.getByText('Sicherung erstellt.')).toBeVisible({ timeout: 20_000 })
  }
  const vorher = await namen(page)
  const zeile = page.getByTestId(`backup-${vorher[0]}`)
  await zeile.getByRole('button', { name: /^Wiederherstellen/ }).click()

  // ⚠️ Erst die Probe (was kommt, was sich ändert), dann die Frage; ohne Bestätigen geschieht nichts.
  const frage = page.getByTestId('backup-confirm-restore')
  await expect(frage).toContainText('Erst wird der jetzige Stand gesichert')
  await frage.getByRole('button', { name: 'Abbrechen', exact: true }).click()
  await expect(frage).toHaveCount(0)
  expect(await namen(page)).toEqual(vorher)
})

test('Die Über-Seite nennt Version, Lizenz und was hinausgeht', async ({ page }) => {
  await zuEinstellungen(page, 'Über nexmail')

  await expect(page.getByText(/AGPL-3\.0/)).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('link', { name: /github\.com\/DerKezorm\/nexmail/ })).toBeVisible()
  // Bauplan „Einstellungen", Über: „Version“, nie mehr „Fassung“.
  await expect(page.getByText('Fassung', { exact: true })).toHaveCount(0)

  // ⚠️ **Der Satz über die Nachfrage muss dastehen.** nexmail liefert die
  // Schriften mit, damit es beim Öffnen niemanden anfunkt; die Frage bei
  // GitHub ist die einzige Verbindung, die zu nichts Eingerichtetem gehört,
  // und eine verschwiegene Ausnahme ist ein gebrochenes Versprechen.
  await expect(page.getByText(/einzige Verbindung nach draußen|only connection to the outside/)).toBeVisible()

  await keinTextLaeuftUeber(page)
  await jederKnopfHatEinenNamen(page)
})
