/* Links in einer fremden Mail tun, was man erwartet (Issue #5).
 *
 * Bis 0.18.1 tat ein gewöhnlicher Klick nichts: Der Rahmen durfte keine
 * neuen Fenster öffnen, und im Rahmen selbst verbietet die Inhaltsregel jede
 * fremde Seite. Nur Rechtsklick und „In neuem Tab öffnen" kam durch.
 *
 * ⚠️ **Das zeigt nur ein echter Browser.** Die Entscheidung, welcher Link
 * wohin geht, steht in `lib/leselinks.ts` und ist dort ohne Browser geprüft;
 * ob der Browser den Reiter dann auch aufmacht, hängt an der Abschottung des
 * Rahmens und an der Inhaltsregel, und die gibt es nur hier.
 *
 * Der Rumpf einer vorhandenen Nachricht wird im Test ersetzt, dasselbe
 * Verfahren wie „Im Rahmen steht immer die Mail" in `darstellung.spec.ts`.
 * Die fremden Seiten beantwortet der Test selbst; ins Netz geht nichts.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden } from './hilfen'

/* ⚠️ **`name`, nicht `id`, an der Sprungmarke.** Die Bereinigung im Server
   lässt an einem Link nur `href`, `name` und `target` stehen; eine Marke mit
   `id` käme gar nicht an, und der Test prüfte eine Mail, die es nicht gibt. */
const MAIL = `
<p><a href="https://example.com/mit-target" target="_blank">Mit target</a></p>
<p><a href="https://example.com/ohne-target">Ohne target</a></p>
<p><a href="mailto:jemand@example.com?subject=Hallo%20Welt&amp;cc=kopie@example.com&amp;body=Erste%20Zeile">Schreib mir</a></p>
<p><a href="#ziel">Zum Ende</a></p>
<p><a href="seite.html">Relativ</a></p>
<div style="height:3000px"></div>
<p><a name="ziel">ZIELMARKE</a></p>
`

async function mailMitLinks(page: Page) {
  await page.route(/\/api\/nachrichten\/(\d+)$/, async (route) => {
    const a = await route.fetch()
    const d = await a.json()
    await route.fulfill({ json: { ...d, html: MAIL, geblockte_bilder: 0 } })
  })
  await anmelden(page)
  const zeile = page.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible()
  await zeile.click()
  const rahmen = page.frameLocator('article iframe').first()
  await expect(rahmen.getByText('Mit target')).toBeVisible()
  return rahmen
}

/** Die fremden Seiten, samt der Kopfzeilen, mit denen sie angefragt wurden. */
async function fremdeSeiten(page: Page) {
  const anfragen: Array<{ url: string; referer: string | undefined }> = []
  await page.context().route('https://example.com/**', async (route) => {
    anfragen.push({ url: route.request().url(), referer: route.request().headers()['referer'] })
    /* ⚠️ **Mit Skript.** Erbte der neue Reiter die Abschottung des Rahmens,
       käme die Seite trotzdem an, nur liefe darin nichts. Eine Seite ohne
       Skript sähe in beiden Fällen gleich aus. */
    await route.fulfill({
      contentType: 'text/html',
      body: '<p>FREMDE SEITE</p><script>document.body.dataset.skript = "lief"</script>',
    })
  })
  return anfragen
}

test('Der Rahmen darf Reiter öffnen, aber weiterhin kein Skript ausführen', async ({ page }) => {
  await mailMitLinks(page)
  const sandbox = (await page.locator('article iframe').first().getAttribute('sandbox')) ?? ''
  expect(sandbox.split(/\s+/)).toContain('allow-popups')
  expect(sandbox.split(/\s+/)).toContain('allow-popups-to-escape-sandbox')
  /* ⚠️ **Die eigentliche Zusicherung.** Mit `allow-scripts` neben
     `allow-same-origin` fiele die zweite Verteidigungslinie ganz. */
  expect(sandbox).not.toContain('allow-scripts')
})

for (const name of ['Mit target', 'Ohne target']) {
  test(`Ein Link „${name}" öffnet die Seite in einem neuen Reiter, ohne Opener und Referrer`, async ({
    page,
  }) => {
    const anfragen = await fremdeSeiten(page)
    const rahmen = await mailMitLinks(page)

    const reiter = page.context().waitForEvent('page')
    await rahmen.getByText(name).click()
    const neu = await reiter
    await expect(neu.getByText('FREMDE SEITE')).toBeVisible()
    expect(neu.url()).toMatch(/^https:\/\/example\.com\//)
    await expect(neu.locator('body'), 'Der neue Reiter erbte die Abschottung; die Seite läuft ohne Skripte.').toHaveAttribute('data-skript', 'lief')
    expect(await neu.evaluate(() => window.opener === null), 'Die fremde Seite erreicht nexmail über window.opener.').toBe(true)
    expect(anfragen.at(-1)?.referer, 'Die fremde Seite erfährt die Adresse dieser Installation.').toBeUndefined()

    // Die Mail steht weiter da, statt einer Fehlerseite im Rahmen.
    await expect(rahmen.getByText('Mit target')).toBeVisible()
    await neu.close()
  })
}

test('Ein mailto:-Link öffnet nexmails Verfassen-Fenster, vorbelegt', async ({ page }) => {
  const rahmen = await mailMitLinks(page)
  const reiter: Page[] = []
  page.context().on('page', (p) => reiter.push(p))

  await rahmen.getByText('Schreib mir').click()
  const fenster = page.getByRole('dialog', { name: 'Neue Nachricht' })
  await expect(fenster).toBeVisible()
  await expect(fenster.getByRole('button', { name: 'jemand@example.com entfernen' })).toBeVisible()
  await expect(fenster.getByRole('button', { name: 'kopie@example.com entfernen' })).toBeVisible()
  await expect(fenster.getByPlaceholder('Betreff', { exact: true })).toHaveValue('Hallo Welt')
  await expect(fenster.getByText('Erste Zeile')).toBeVisible()
  expect(reiter, 'Neben dem Fenster ging ein Reiter auf.').toHaveLength(0)

  // Verwerfen, nicht schließen: Das Kreuz legte einen Entwurf im Postfach ab.
  await fenster.getByRole('button', { name: 'Verwerfen' }).click()
  await expect(fenster).toBeHidden()
  await expect(rahmen.getByText('Mit target')).toBeVisible()
})

test('Eine Sprungmarke scrollt innerhalb der Mail, statt nexmail in den Rahmen zu laden', async ({
  page,
}) => {
  const rahmen = await mailMitLinks(page)
  const lage = () =>
    page.evaluate(() => {
      const r = document.querySelector('article iframe') as HTMLIFrameElement
      const ziel = r.contentDocument!.querySelector('a[name="ziel"]')!
      return {
        oben: r.getBoundingClientRect().top + ziel.getBoundingClientRect().top,
        hoehe: window.innerHeight,
        adresse: r.contentWindow!.location.href,
      }
    })
  const vorher = await lage()
  expect(vorher.oben, 'Die Marke steht schon vor dem Klick im Bild; der Test prüfte nichts.').toBeGreaterThan(vorher.hoehe)

  await rahmen.getByText('Zum Ende').click()
  await expect.poll(async () => (await lage()).oben, { message: 'Die Marke kam nicht ins Bild.' }).toBeLessThan(vorher.hoehe)
  const nachher = await lage()
  expect(nachher.oben).toBeGreaterThanOrEqual(0)
  expect(nachher.adresse).toBe('about:srcdoc')
  await expect(rahmen.getByText('ZIELMARKE')).toBeVisible()
})

test('Eine relative Adresse führt nirgends hin, auch nicht zu nexmail selbst', async ({ page }) => {
  const rahmen = await mailMitLinks(page)
  const reiter: Page[] = []
  page.context().on('page', (p) => reiter.push(p))

  await rahmen.getByText('Relativ').click()
  await page.waitForTimeout(500)
  expect(reiter).toHaveLength(0)
  expect(await page.evaluate(() => (document.querySelector('article iframe') as HTMLIFrameElement).contentWindow!.location.href)).toBe('about:srcdoc')
  await expect(rahmen.getByText('Mit target')).toBeVisible()
})
