/* Regeln aus einer Mail und „Jetzt anwenden".
 *
 * ⚠️ Bis 0.22.2 stand „Regel erstellen" gesperrt im Kontextmenü („kommt
 * später"), und für `POST /api/regeln/anwenden` gab es keinen Knopf. Beide
 * Tests tragen die Handlung bis zu ihrer Wirkung: das vorbelegte Formular,
 * und die Antwort des Servers samt Zahl.
 *
 * ⚠️ **Die Probe-Regel trifft nichts.** Sie sucht einen Betreff, den es nicht
 * gibt, und markiert nur; so ändert „Jetzt anwenden" am Testpostfach nichts,
 * auch wenn der Test mittendrin abbricht. Weggeräumt wird sie vor und nach
 * dem Fall über die Schnittstelle.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, keineRohenSchluessel, postfach, serverabsagen, TESTPOSTFACH } from './hilfen'

const MARKE = 'nexmail-regelprobe-ohne-treffer'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Kontextmenü und Regelseite werden breit geprüft.')
  await anmelden(page)
  await probeRegelnWeg(page)
})

test.afterEach(async ({ page }) => {
  await probeRegelnWeg(page)
})

async function probeRegelnWeg(page: Page) {
  const regeln = (await (await page.request.get('/api/regeln')).json()) as Array<{
    id: number
    name: string
  }>
  for (const r of regeln.filter((x) => x.name === MARKE)) {
    await page.request.delete(`/api/regeln/${r.id}`)
  }
}

test('„Regel erstellen" öffnet das Formular mit dem Absender', async ({ page }) => {
  const baum = postfach(page)
  await expect.poll(() => baum.getByRole('button').count(), { timeout: 15_000 }).toBeGreaterThan(0)
  await baum.getByRole('button', { name: 'Posteingang' }).first().click()
  const zeile = page.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible({ timeout: 15_000 })

  await zeile.click({ button: 'right' })
  const eintrag = page.getByRole('menuitem', { name: 'Regel erstellen' })
  await expect(eintrag).toBeEnabled()
  await eintrag.click()

  // Die Regelseite mit dem Formular; die Bedingung trägt eine Mailadresse.
  await expect(page.getByRole('tab', { name: 'Regeln', selected: true })).toBeVisible()
  const wert = page.getByLabel('Wert', { exact: true }).first()
  await expect(wert).toHaveValue(/.+@.+/)
  // ⚠️ Auswahllisten über die Rolle: Das Label umschließt die Liste, und
  // `getByLabel` liest dann die Optionen mit.
  await expect(page.getByRole('combobox', { name: 'Aktion', exact: true })).toHaveValue(
    'verschieben',
  )
  await keineRohenSchluessel(page)

  // Abbrechen speichert nichts.
  const vorher = ((await (await page.request.get('/api/regeln')).json()) as unknown[]).length
  await page.getByRole('button', { name: 'Abbrechen' }).click()
  const nachher = ((await (await page.request.get('/api/regeln')).json()) as unknown[]).length
  expect(nachher).toBe(vorher)
})

test('„Jetzt anwenden" läuft über den gewählten Ordner und sagt, was es traf', async ({
  page,
}) => {
  const angelegt = await page.request.post('/api/regeln', {
    data: {
      name: MARKE,
      bedingungen: [{ feld: 'betreff', vergleich: 'enthaelt', wert: MARKE }],
      aktionen: [{ art: 'markieren', wert: '' }],
    },
  })
  expect(angelegt.status()).toBe(201)

  const absagen = serverabsagen(page)
  await page.getByRole('button', { name: /Benutzermenü|User menu/ }).first().click()
  await page.getByRole('button', { name: 'Einstellungen' }).click()
  await page.getByRole('tab', { name: 'Regeln' }).click()

  await page.getByRole('button', { name: /Jetzt anwenden/ }).click()
  const fenster = page.getByRole('dialog')
  const auswahl = fenster.getByRole('combobox', { name: 'Ordner', exact: true })
  await expect(auswahl).toBeVisible()
  /* ⚠️ **Ausdrücklich der Posteingang des Testpostfachs.** Vorgewählt ist der
     erste Posteingang, und der gehört hier einem echten Postfach; „Jetzt
     anwenden" liefe dort mit allen eingeschalteten Regeln des Benutzers. */
  const konten = (await (await page.request.get('/api/konten')).json()) as Array<{
    id: string
    anzeigename: string
  }>
  const test1 = konten.find((k) => k.anzeigename === TESTPOSTFACH)
  expect(test1, 'Das Testpostfach fehlt.').toBeTruthy()
  const ordner = (await (await page.request.get(`/api/konten/${test1!.id}/ordner`)).json()) as Array<{
    id: number
    rolle: string
  }>
  const eingang = ordner.find((o) => o.rolle === 'posteingang')
  expect(eingang, 'Das Testpostfach hat keinen Posteingang.').toBeTruthy()
  await auswahl.selectOption(String(eingang!.id))

  const antwort = page.waitForResponse(
    (r) => r.url().includes('/api/regeln/anwenden') && r.request().method() === 'POST',
  )
  await fenster.getByRole('button', { name: 'Anwenden' }).click()
  const r = await antwort
  await absagen.pruefen()
  expect(r.status()).toBe(200)
  const stand = (await r.json()) as { getroffen: number; geprueft: number }
  expect(stand.getroffen, 'Die Probe-Regel darf nichts treffen.').toBe(0)

  await expect(
    page.getByText(new RegExp(`^0 von ${stand.geprueft} Mails? getroffen`)),
  ).toBeVisible()
})
