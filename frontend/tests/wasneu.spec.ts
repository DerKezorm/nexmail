/* „Was ist neu“: der Banner nach dem Update, das Fenster und das Wegklicken.
 *
 * ⚠️ **Die Version wird vorgespielt, nicht hochgezählt.** Der Text gilt der
 * nächsten Version mit Neuem; der Server hier läuft auf der vorigen. Die
 * Antwort von `/api/auth/ich` bekommt deshalb die Version des Eintrags und
 * einen älteren Stand „gesehen“. Die Meldung „gesehen“ wird abgefangen und
 * gezählt, damit der Entwicklungsbenutzer nichts davon behält.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/wasneu.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { anmelden, jederKnopfHatEinenNamen } from './hilfen'

/* Gelesen statt importiert: Playwrights Lader will bei JSON ein
   Import-Attribut, das Vite und tsc nicht kennen. */
type Eintrag = { lead: string; sections: { where: string }[]; small: string[] }
const de = JSON.parse(
  readFileSync(new URL('../src/i18n/wasneu/de.json', import.meta.url), 'utf-8'),
) as Record<string, Eintrag>
/* ⚠️ Numerisch, nicht alphabetisch: Als Text käme 0.9.0 nach 0.10.0. */
const VERSION = Object.keys(de).sort((a, b) =>
  a.localeCompare(b, undefined, { numeric: true }),
).at(-1) as string

async function vorspielen(page: Page, gesehen: string | null) {
  const meldungen = { zahl: 0 }
  await page.route('**/api/auth/ich', async (route) => {
    const echt = await route.fetch()
    const ich = await echt.json()
    await route.fulfill({
      response: echt,
      json: { ...ich, version: VERSION, wasneu_gesehen: gesehen ?? VERSION },
    })
  })
  await page.route('**/api/auth/ich/wasneu-gesehen', async (route) => {
    meldungen.zahl += 1
    const ich = await (await page.request.get('/api/auth/ich')).json()
    await route.fulfill({ json: ich })
  })
  await anmelden(page)
  return meldungen
}

test('nach dem Update: Banner, Fenster, und weg ist er', async ({ page }) => {
  const meldungen = await vorspielen(page, '0.23.4')

  const banner = page.getByTestId('wasneu-banner')
  await expect(banner).toContainText(VERSION)
  await banner.getByRole('button', { name: 'Was ist neu?' }).click()

  const fenster = page.getByTestId('wasneu-fenster')
  await expect(fenster).toContainText(de[VERSION].lead)
  await expect(fenster).toContainText(de[VERSION].sections[0].where)
  await expect(fenster).toContainText(de[VERSION].small[0])
  await jederKnopfHatEinenNamen(page)
  await page.getByRole('button', { name: 'Verstanden' }).click()

  await expect(fenster).toHaveCount(0)
  await expect(banner).toHaveCount(0)
  expect(meldungen.zahl).toBe(1)
})

test('das Kreuz räumt den Banner weg, ohne das Fenster', async ({ page }) => {
  const meldungen = await vorspielen(page, '0.23.4')

  await page.getByTestId('wasneu-banner').getByRole('button', { name: 'Wegklicken' }).click()

  await expect(page.getByTestId('wasneu-banner')).toHaveCount(0)
  await expect(page.getByTestId('wasneu-fenster')).toHaveCount(0)
  await expect.poll(() => meldungen.zahl).toBe(1)
})

test('schon gesehen: kein Banner, aber im Benutzermenü wieder zu öffnen', async ({ page }) => {
  const meldungen = await vorspielen(page, null)

  await expect(page.getByRole('button', { name: 'Mail', exact: true })).toBeVisible()
  await expect(page.getByTestId('wasneu-banner')).toHaveCount(0)
  await page.getByRole('button', { name: /Benutzermenü|User menu/ }).first().click()
  await page.getByRole('button', { name: 'Was ist neu' }).click()

  await expect(page.getByTestId('wasneu-fenster')).toContainText(de[VERSION].lead)
  await page.getByRole('button', { name: 'Verstanden' }).click()
  expect(meldungen.zahl).toBe(0)
})

test('eine Version ohne Text: kein Banner, kein Menüpunkt', async ({ page }) => {
  await page.route('**/api/auth/ich', async (route) => {
    const echt = await route.fetch()
    await route.fulfill({
      response: echt,
      json: { ...(await echt.json()), version: '0.0.1', wasneu_gesehen: '0.0.0' },
    })
  })
  await anmelden(page)

  await expect(page.getByRole('button', { name: 'Mail', exact: true })).toBeVisible()
  await expect(page.getByTestId('wasneu-banner')).toHaveCount(0)
  await page.getByRole('button', { name: /Benutzermenü|User menu/ }).first().click()
  await expect(page.getByRole('button', { name: 'Einstellungen' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Was ist neu' })).toHaveCount(0)
})
