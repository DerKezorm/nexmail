/* „Was ist neu“ (Modul wasneu 0.1.0): der Banner nach dem Update, das Fenster und das Wegklicken, die Zeile auf
 * „Über nexmail“.
 *
 * ⚠️ **Der Stand des Kontos wird vorgespielt, nicht hochgezählt.** Die Oberfläche fragt `GET /api/whats-new`; die
 * Antwort bekommt hier die neueste Version der Texte als laufende und einen älteren Stand „gesehen“, mit dem echten
 * Eintrag. Die Meldung „gesehen“ (`POST /api/whats-new/seen`) wird abgefangen und gezählt, damit der
 * Entwicklungsbenutzer nichts davon behält.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/wasneu.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { anmelden, jederKnopfHatEinenNamen, mailKnopf, zuEinstellungen } from './hilfen'

/* Gelesen statt importiert: Playwrights Lader will bei JSON ein
   Import-Attribut, das Vite und tsc nicht kennen. Die Texte liegen seit dem
   Modul wasneu beim Server. */
type Abschnitt = { title: string; where: string; body: string }
type Eintrag = { lead: string; sections: Abschnitt[]; smallTitle: string; small: string[] }
const de = JSON.parse(
  readFileSync(new URL('../../backend/app/wasneu/de.json', import.meta.url), 'utf-8'),
) as Record<string, Eintrag>
/* ⚠️ Numerisch, nicht alphabetisch: Als Text käme 0.9.0 nach 0.10.0. */
const VERSION = Object.keys(de).sort((a, b) =>
  a.localeCompare(b, undefined, { numeric: true }),
).at(-1) as string

function posten(version: string) {
  const e = de[version]
  return {
    version,
    language: 'de',
    lead: e.lead,
    sections: e.sections.map((a) => ({ ...a, link: null, operator: false })),
    smallTitle: e.smallTitle,
    small: e.small,
  }
}

async function vorspielen(page: Page, gesehen: string | null, version = VERSION) {
  const meldungen = { zahl: 0 }
  const eintrag = de[version] ? posten(version) : null
  await page.route(/\/api\/whats-new(\?.*)?$/, async (route) => {
    await route.fulfill({
      json: {
        version,
        seen: gesehen ?? version,
        unread: gesehen && eintrag ? [eintrag] : [],
        more: false,
        current: eintrag,
        earlier: false,
      },
    })
  })
  await page.route('**/api/whats-new/seen', async (route) => {
    await route.fulfill({ json: { seen: version } })
    meldungen.zahl += 1
  })
  await anmelden(page)
  return meldungen
}

/* ⚠️ Nach dem Wegklicken lädt die Oberfläche `ich` nach; endet der Test, während
   der Abfang darauf noch liest, wirft Playwright „Response has been disposed“.
   Die Abfänge gehen deshalb am Ende jedes Falls weg, laufende Lesevorgänge
   werden dabei verworfen. */
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('nach dem Update: Banner, Fenster, und weg ist er', async ({ page }) => {
  const meldungen = await vorspielen(page, '0.23.4')

  const banner = page.getByTestId('whats-new-banner')
  await expect(banner).toContainText(VERSION)
  await banner.getByRole('button', { name: 'Was ist neu?' }).click()

  const fenster = page.getByTestId('whats-new-window')
  await expect(fenster).toContainText(de[VERSION].lead)
  await expect(fenster).toContainText(de[VERSION].sections[0].where)
  await expect(fenster).toContainText(de[VERSION].small[0])
  await jederKnopfHatEinenNamen(page)
  await fenster.getByRole('button', { name: 'Verstanden' }).click()

  await expect(fenster).toHaveCount(0)
  await expect(banner).toHaveCount(0)
  await expect.poll(() => meldungen.zahl).toBe(1)
})

test('das Kreuz räumt den Banner weg, ohne das Fenster', async ({ page }) => {
  const meldungen = await vorspielen(page, '0.23.4')

  await page.getByTestId('whats-new-banner').getByRole('button', { name: 'Ausblenden' }).click()

  await expect(page.getByTestId('whats-new-banner')).toHaveCount(0)
  await expect(page.getByTestId('whats-new-window')).toHaveCount(0)
  await expect.poll(() => meldungen.zahl).toBe(1)
})

/* ⚠️ **Seit dem 23.11.2026 unter „Über nexmail"**, nicht mehr im Benutzermenü
   oben rechts (das gibt es nicht mehr). „Über" sehen alle Konten. */
test('schon gesehen: kein Banner, aber unter „Über nexmail" wieder zu öffnen', async ({ page }) => {
  const meldungen = await vorspielen(page, null)

  await expect(mailKnopf(page)).toBeVisible()
  await expect(page.getByTestId('whats-new-banner')).toHaveCount(0)
  await zuEinstellungen(page, 'Über nexmail')
  // Über-Seite des Bausatzes (AboutPage): „Neu in nexmail <Version>“, das Fenster `whats-new-window`.
  await page.getByRole('button', { name: /^Neu in nexmail / }).click()

  const fenster = page.getByTestId('whats-new-window')
  await expect(fenster).toContainText(de[VERSION].lead)
  await fenster.getByRole('button', { name: 'Schließen' }).first().click()
  await expect(fenster).toHaveCount(0)
  expect(meldungen.zahl).toBe(0)
})

test('eine Version ohne Text: kein Banner, kein Knopf auf „Über“', async ({ page }) => {
  await vorspielen(page, '0.0.0', '0.0.1')

  await expect(mailKnopf(page)).toBeVisible()
  await expect(page.getByTestId('whats-new-banner')).toHaveCount(0)
  await zuEinstellungen(page, 'Über nexmail')
  // Erst warten, bis die Auskunft steht: Vorher fehlt der Knopf ohnehin.
  await expect(page.getByText('github.com/DerKezorm/nexmail')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Neu in nexmail / })).toHaveCount(0)
})
