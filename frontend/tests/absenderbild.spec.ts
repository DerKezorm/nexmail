/* Das Bild vor jedem Absender (Diskussion #4).
 *
 * ⚠️ **Die Logos schaltet hier kein Test ein.** Dann holte der Server bei
 * jedem Lauf Symbole von den Websites der Testpost, und der Lauf hinge am
 * Internet. Was das Holen tut, prüft `tests/test_absenderbild.py` im Server
 * ohne Netz; hier geht es darum, dass der Kreis dasteht, der Schalter ankommt
 * und der Browser selbst nirgends hingreift.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, postfach, zuEinstellungen } from './hilfen'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Liste wird breit geprüft.')
  await anmelden(page)
})

const zeilen = (page: Page) => page.locator('button[draggable="true"]')
const kreise = (page: Page) => zeilen(page).locator('[data-absenderbild]')

async function posteingang(page: Page) {
  const baum = postfach(page)
  await expect.poll(() => baum.getByRole('button').count(), { timeout: 15000 }).toBeGreaterThan(0)
  await baum.getByRole('button', { name: 'Posteingang' }).first().click()
  await expect
    .poll(() => zeilen(page).count(), { timeout: 8000, message: 'Im Posteingang liegt nichts.' })
    .toBeGreaterThan(0)
}

test('Vor jeder Zeile steht ein Kreis, und der Browser fragt nur nexmail', async ({ page }) => {
  const fremd: string[] = []
  const eigene: string[] = []
  page.on('request', (r) => {
    if (r.resourceType() !== 'image') return
    if (new URL(r.url()).origin !== new URL(page.url()).origin) fremd.push(r.url())
    else if (r.url().includes('/api/absenderbild?')) eigene.push(r.url())
  })
  await posteingang(page)

  await expect(kreise(page).first()).toBeVisible()
  expect(await kreise(page).count()).toBe(await zeilen(page).count())
  // ⚠️ **Gezählt, nicht durchlaufen.** Ohne Bild antwortet der Server mit 404,
  // und das `img` fällt weg; eine Schleife über die Bilder wäre dann leer
  // und immer grün.
  await expect.poll(() => eigene.length, { message: 'Keine Zeile hat nach ihrem Bild gefragt.' }).toBeGreaterThan(0)
  // ⚠️ Der Kern der ganzen Sache: Ein Logo holt der Server, nie der Browser.
  expect(fremd, 'Der Browser hat ein Bild von einer fremden Adresse geholt.').toEqual([])

  // Im Lesebereich derselbe Kreis, groß.
  await zeilen(page).first().click()
  await expect(page.locator('article [data-absenderbild]').first()).toBeVisible()
})

test('Unter Darstellung lässt sich der Kreis abschalten, ohne F5', async ({ page }) => {
  await posteingang(page)
  await expect(kreise(page).first()).toBeVisible()

  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('switch', { name: 'Bilder vor den Absendern' }).click()
  await page.getByRole('button', { name: 'Mail', exact: true }).click()

  await expect(zeilen(page).first()).toBeVisible()
  await expect(kreise(page)).toHaveCount(0)
})

test('Der Logo-Schalter kommt beim Server an, und eine ungeprüfte Mail fragt trotzdem nie', async ({
  page,
}) => {
  /* ⚠️ Stand beim Server lesen und am Ende dorthin zurückstellen, nicht am
     Schalter: Ein Test, der den angezeigten Stand zurückdreht, lässt bei einer
     Mutation den echten Stand verstellt liegen. */
  const vorher = (await (await page.request.get('/api/einstellungen/bilder')).json()) as { logos: boolean }
  try {
    await page.request.put('/api/einstellungen/bilder', { data: { logos: false } })
    await page.reload()
    await zuEinstellungen(page)
    await page.getByRole('tab', { name: 'Darstellung' }).click()
    const schalter = page.getByRole('switch', { name: 'Firmenlogos laden' })
    await expect(schalter).toHaveAttribute('aria-checked', 'false')
    const antwort = page.waitForResponse(
      (r) => r.url().includes('/api/einstellungen/bilder') && r.request().method() === 'PUT',
    )
    await schalter.click()
    expect((await antwort).status()).toBe(200)
    const beimServer = (await (await page.request.get('/api/einstellungen/bilder')).json()) as {
      logos: boolean
    }
    expect(beimServer.logos).toBe(true)

    // ⚠️ **Der Kern:** Die Mails im Testpostfach tragen keine bestandene
    // Absenderprüfung, also fragt keine Zeile nach einem Logo, auch jetzt nicht.
    await page.getByRole('button', { name: 'Mail', exact: true }).click()
    await posteingang(page)
    const quellen = await kreise(page).evaluateAll((k) => k.map((e) => e.getAttribute('data-quelle') ?? ''))
    expect(quellen.length).toBeGreaterThan(0)
    for (const q of quellen) expect(q, 'Eine ungeprüfte Mail fragt nach dem Logo.').not.toContain('logo=')
  } finally {
    await page.request.put('/api/einstellungen/bilder', { data: { logos: vorher.logos } })
  }
})

test('Eine geprüfte Mail zeigt ihr Logo, wenn der Schalter an ist', async ({ page }) => {
  /* Die echte Prüfung läuft im Server und hat dort ihre Tests; hier wird die
     Antwort der Liste so verändert, dass die erste Zeile als geprüft gilt,
     und das Logo kommt aus einer Attrappe. Gemessen wird, dass die Zeile es
     anfordert und zeichnet. */
  const vorher = (await (await page.request.get('/api/einstellungen/bilder')).json()) as { logos: boolean }
  try {
    await page.request.put('/api/einstellungen/bilder', { data: { logos: true } })
    await page.route('**/api/nachrichten?**', async (route) => {
      const antwort = await route.fetch()
      const zeilen = (await antwort.json()) as Array<Record<string, unknown>>
      if (zeilen[0]) zeilen[0].absender_geprueft = true
      await route.fulfill({ response: antwort, json: zeilen })
    })
    await page.route('**/api/absenderbild?**', (route) =>
      route.request().url().includes('logo=1')
        ? route.fulfill({
            contentType: 'image/svg+xml',
            body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="#123456"/></svg>',
          })
        : route.fulfill({ status: 404 }),
    )
    await page.reload()
    await posteingang(page)

    await expect(kreise(page).first()).toHaveAttribute('data-quelle', /logo=1$/)
    await expect(kreise(page).first()).toHaveAttribute('data-absenderbild', 'bild')
    // Die zweite Zeile ist ungeprüft und bleibt bei den Initialen.
    if ((await kreise(page).count()) > 1) {
      await expect(kreise(page).nth(1)).not.toHaveAttribute('data-quelle', /logo=/)
    }
  } finally {
    await page.request.put('/api/einstellungen/bilder', { data: { logos: vorher.logos } })
  }
})
