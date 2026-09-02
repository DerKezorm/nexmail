/* Post hinein und hinaus — die beiden Fenster am Ordner.
 *
 * ⚠️ **Hier wird nichts wirklich eingespielt und nichts heruntergeladen.**
 * Beides fasst ein echtes Postfach an: Der Export holt jede Mail einzeln beim
 * Anbieter (gemessen 20 s für vier Stück, an einem trägen Tag), der Import
 * legt Post in einem Ordner ab. Ein Testlauf, der das bei jedem Durchgang tut,
 * ist nach einer Woche der Grund, warum niemand mehr Tests laufen lässt.
 *
 * Geprüft wird deshalb, was die Oberfläche **vor** dem Klick sagt — und genau
 * das ist der Teil, der schweigen könnte: die Zahl, die Formatwahl, die
 * gesperrte Schaltfläche.
 */
import { expect, test } from '@playwright/test'
import { anmelden, postfach } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Das Ordner-Kontextmenü wird breit geprüft.')
  await anmelden(page)
  await expect
    .poll(() => postfach(page).getByRole('button').count(), { timeout: 15000 })
    .toBeGreaterThan(0)
})

/** Rechtsklick auf einen Ordner des Testpostfachs. */
async function ordnerKontext(page: import('@playwright/test').Page, name = 'Archiv') {
  await postfach(page).getByRole('button', { name }).first().click({ button: 'right' })
  await expect(page.getByRole('menu').first()).toBeVisible()
}

test('Der Ordner bietet beide Wege an', async ({ page }) => {
  await ordnerKontext(page)

  for (const eintrag of [/Post einspielen/, /Ordner herunterladen/]) {
    await expect(page.getByRole('menuitem', { name: eintrag })).toBeVisible()
  }
})

test('Herunterladen nennt die Zahl und beide Formate', async ({ page }) => {
  await ordnerKontext(page)
  await page.getByRole('menuitem', { name: /Ordner herunterladen/ }).click()

  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  /* ⚠️ **Die Zahl ist der Punkt.** Heruntergeladen wird, was nexmail kennt;
     ein nie abgeglichener Ordner gäbe eine fast leere Datei, und das sähe aus
     wie Datenverlust. */
  await expect(fenster.getByText(/\d+ Nachricht/)).toBeVisible()

  const auswahl = fenster.getByRole('combobox')
  await expect(auswahl).toBeVisible()
  const werte = await auswahl.locator('option').evaluateAll((os) =>
    os.map((o) => (o as HTMLOptionElement).value),
  )
  expect(werte).toEqual(['mbox', 'zip'])

  // Nicht herunterladen — siehe Kopf der Datei.
  await fenster.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(fenster).toBeHidden()
})

test('Einspielen sperrt den Knopf, solange keine Datei gewählt ist', async ({ page }) => {
  await ordnerKontext(page)
  await page.getByRole('menuitem', { name: /Post einspielen/ }).click()

  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  /* ⚠️ **Der Satz muss dastehen, bevor jemand klickt.** „Was schon da ist,
     wird übersprungen" ist die ganze Zusage, auf der die Wiederholbarkeit
     beruht — ohne sie traut sich niemand einen zweiten Anlauf. */
  await expect(fenster.getByText(/übersprungen/)).toBeVisible()
  await expect(fenster.getByRole('button', { name: 'Einspielen' })).toBeDisabled()

  await fenster.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(fenster).toBeHidden()
})

test('Beide Fenster kommen ohne Browser-Kasten aus', async ({ page }) => {
  const kaesten: string[] = []
  page.on('dialog', async (d) => {
    kaesten.push(d.type())
    await d.dismiss()
  })

  for (const eintrag of [/Post einspielen/, /Ordner herunterladen/]) {
    await ordnerKontext(page)
    await page.getByRole('menuitem', { name: eintrag }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Abbrechen' }).click()
  }

  expect(kaesten, 'window.confirm/prompt sind keine Oberfläche.').toEqual([])
})
