/* Das Bilder-Paket in der Oberfläche.
 *
 * ⚠️ **Warum es diese Datei gibt.** Der Knopf „Bilder anzeigen" hat von 0.1.0
 * bis 0.3.0 sichtbar nichts getan, und kein Test hat es gezeigt: Alle prüften
 * den Server. Was im Browser ankam, hat nie jemand angesehen — und genau dort
 * saß der Fehler (die geerbte Inhaltsregel des abgeschotteten Rahmens).
 *
 * ⚠️ **Die Antworten des Servers sind hier gestellt, und das ist Absicht.**
 * In den Testpostfächern liegt keine Mail mit fremden Bildern; eine dorthin zu
 * schicken hieße, für einen Test Werbung zu verschicken. Geprüft wird deshalb
 * genau das, was der Server nicht prüfen kann: dass die Oberfläche den
 * richtigen Knopf zeigt, die Antwort in den Rahmen einsetzt und die dauerhafte
 * Freigabe sichtbar macht. Was der Server liefert, steht unter Wache in
 * `backend/tests/test_bilder.py`.
 */
import { expect, test } from '@playwright/test'
import { anmelden, zuEinstellungen, serverabsagen } from './hilfen'

const MIT_BILD = '<p>Newsletter</p><img data-nexmail-src="https://absender.example/p.gif">'
const VERMITTELT = '<p>Newsletter</p><img src="/api/bilder/eine-marke">'

/** Die geöffnete Nachricht so tun lassen, als trüge sie ein fremdes Bild. */
async function mitGeblocktemBild(page, gemerkt = { wert: false }) {
  await page.route(/\/api\/nachrichten\/\d+$/, async (route) => {
    const antwort = await route.fetch()
    const daten = await antwort.json()
    await route.fulfill({
      json: { ...daten, html: MIT_BILD, geblockte_bilder: 1, absender_freigegeben: false },
    })
  })
  await page.route(/\/api\/nachrichten\/\d+\/bilder$/, async (route) => {
    gemerkt.wert = JSON.parse(route.request().postData() ?? '{}').absender_merken === true
    await route.fulfill({ json: { html: VERMITTELT } })
  })
}

async function ersteMailOeffnen(page) {
  const zeile = page.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible()
  await zeile.click()
}

test('Der Balken zeigt beide Wege, und „Bilder anzeigen" setzt sie ein', async ({ page }) => {
  await anmelden(page)
  await mitGeblocktemBild(page)
  const absagen = serverabsagen(page)
  /* ⚠️ **Der Beweis, den es drei Fassungen lang nicht gab.** Nicht dass die
     Adresse im HTML steht, sondern dass der Browser sie aus dem
     abgeschotteten Rahmen heraus wirklich abruft. Genau das hat die geerbte
     Inhaltsregel vorher stumm verhindert. */
  const abgerufen: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/bilder/')) abgerufen.push(r.url())
  })
  await ersteMailOeffnen(page)

  await expect(page.getByRole('button', { name: 'Bilder anzeigen' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Immer von diesem Absender' })).toBeVisible()

  await page.getByRole('button', { name: 'Bilder anzeigen' }).click()

  /* ⚠️ **Der Punkt der ganzen Übung:** Im Rahmen steht danach eine Adresse
     dieser Anwendung, keine fremde. Eine fremde verwirft der Browser stumm. */
  const rahmen = page.frameLocator('iframe').first()
  await expect(rahmen.locator('img')).toHaveAttribute('src', /^\/api\/bilder\//)
  await expect(page.getByRole('button', { name: 'Bilder anzeigen' })).toHaveCount(0)

  await expect.poll(() => abgerufen.length).toBeGreaterThan(0)
  await absagen.pruefen()
})

test('„Immer von diesem Absender" sagt, was es getan hat — und nimmt es zurück', async ({
  page,
}) => {
  await anmelden(page)
  const gemerkt = { wert: false }
  await mitGeblocktemBild(page, gemerkt)
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Immer von diesem Absender' }).click()

  expect(gemerkt.wert).toBe(true)
  /* Eine Handlung, die man nicht sieht, gibt es nicht — und ein Fehlklick ist
     im selben Atemzug zurückzunehmen. */
  await expect(page.getByText(/werden ab jetzt immer geladen/)).toBeVisible()
  const zurueck = page.getByRole('button', { name: 'Rückgängig' })
  await expect(zurueck).toBeVisible()
  await zurueck.click()
  await expect(page.getByText(/werden ab jetzt immer geladen/)).toHaveCount(0)
})

test('Der globale Schalter liegt im Server und übersteht das Neuladen', async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()

  const schalter = page.getByRole('switch', { name: 'Bilder immer anzeigen' })
  await expect(schalter).toBeVisible()
  await expect(schalter).toHaveAttribute('aria-checked', 'false')

  await schalter.click()
  await expect(schalter).toHaveAttribute('aria-checked', 'true')

  /* ⚠️ **Neu laden, nicht nur klicken.** Eine Einstellung, die nur im Browser
     steht, sieht bis zum F5 genauso aus wie eine, die wirklich gespeichert
     wurde — und dieser Schalter soll ausdrücklich auf jedem Gerät gelten. */
  await page.reload()
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  const wieder = page.getByRole('switch', { name: 'Bilder immer anzeigen' })
  await expect(wieder).toHaveAttribute('aria-checked', 'true')

  await wieder.click()
  await expect(wieder).toHaveAttribute('aria-checked', 'false')
})
