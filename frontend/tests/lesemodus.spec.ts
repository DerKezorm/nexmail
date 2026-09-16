/* Der Lesebereich lässt sich ausblenden.
 *
 * Ein Knopf neben der Suche geht reihum durch drei Modi: Lesebereich rechts,
 * aus mit Öffnen über der Liste, aus mit Öffnen im Fenster. Ohne Lesebereich
 * markiert ein Klick nur, erst ein Doppelklick oder die Eingabetaste öffnet.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen } from './hilfen'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Schmal gibt es keinen Lesebereich neben der Liste.')
  await anmelden(page)
})

const knopf = (page: Page) => page.getByRole('button', { name: /^Lesebereich:/ })
const zeilen = (page: Page) => page.locator('button[draggable="true"]')
const offeneMail = (page: Page) => page.locator('article h1').first()

async function modusWaehlen(page: Page, name: RegExp) {
  for (let i = 0; i < 3; i++) {
    if (name.test((await knopf(page).getAttribute('aria-label')) ?? '')) return
    await knopf(page).click()
  }
  await expect(knopf(page)).toHaveAttribute('aria-label', name)
}

/** Zählt, wie oft eine einzelne Nachricht geholt wird. */
function nachrichtenAbrufe(page: Page) {
  let zahl = 0
  page.on('request', (r) => {
    if (/\/api\/nachrichten\/\d+$/.test(new URL(r.url()).pathname)) zahl++
  })
  return () => zahl
}

test('Der Knopf geht reihum durch drei Modi und merkt sich die Wahl', async ({ page }) => {
  await expect(knopf(page)).toHaveAttribute('aria-label', /^Lesebereich: rechts/)
  await jederKnopfHatEinenNamen(page)

  await knopf(page).click()
  await expect(knopf(page)).toHaveAttribute('aria-label', /^Lesebereich: aus, Doppelklick öffnet ganzseitig/)
  await knopf(page).click()
  await expect(knopf(page)).toHaveAttribute('aria-label', /^Lesebereich: aus, Doppelklick öffnet ein Fenster/)

  // ⚠️ Übersteht das Neuladen — sonst wäre es eine Einstellung für eine Sitzung.
  await page.reload()
  await expect(knopf(page)).toHaveAttribute('aria-label', /^Lesebereich: aus, Doppelklick öffnet ein Fenster/)

  await knopf(page).click()
  await expect(knopf(page)).toHaveAttribute('aria-label', /^Lesebereich: rechts/)
})

test('Ganzseitig: ein Klick markiert nur, ein Doppelklick öffnet über der Liste', async ({ page }) => {
  await expect(zeilen(page).first()).toBeVisible()
  await modusWaehlen(page, /ganzseitig\./)
  const abrufe = nachrichtenAbrufe(page)

  const erste = zeilen(page).first()
  await erste.click()
  await expect(erste).toHaveAttribute('aria-current', 'true')
  // ⚠️ Nicht nur nicht zu sehen, sondern nicht geholt: Eine bloß markierte
  // Mail darf die „nach zwei Sekunden gelesen"-Uhr nicht anwerfen.
  await page.waitForTimeout(400)
  expect(abrufe(), 'Ein Klick hat die Mail geholt, obwohl er nur markieren soll.').toBe(0)
  await expect(offeneMail(page)).toHaveCount(0)

  await erste.dblclick()
  await expect(offeneMail(page)).toBeVisible()
  await expect(zeilen(page)).toHaveCount(0)

  await page.getByRole('button', { name: 'Zurück', exact: true }).click()
  await expect(offeneMail(page)).toHaveCount(0)
  await expect(zeilen(page).first()).toHaveAttribute('aria-current', 'true')

  // Die Tastatur kommt ohne Maus hinein und mit Escape wieder heraus.
  await zeilen(page).first().focus()
  await page.keyboard.press('Enter')
  await expect(offeneMail(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(offeneMail(page)).toHaveCount(0)
  await expect(zeilen(page).first()).toBeVisible()
})

test('Im Fenster: ein Doppelklick öffnet die Mail über der stehenden Liste', async ({ page }) => {
  await expect(zeilen(page).first()).toBeVisible()
  await modusWaehlen(page, /ein Fenster\./)

  const erste = zeilen(page).first()
  await erste.click()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await erste.dblclick()
  const fenster = page.getByRole('dialog')
  await expect(fenster.locator('article h1').first()).toBeVisible()
  // Die Liste bleibt dahinter stehen.
  await expect(erste).toBeAttached()

  await page.keyboard.press('Escape')
  await expect(fenster).toHaveCount(0)
  await expect(erste).toHaveAttribute('aria-current', 'true')

  // Und wieder hinein, diesmal über das Kreuz hinaus.
  await erste.dblclick()
  await expect(fenster.locator('article h1').first()).toBeVisible()
  await fenster.getByRole('button', { name: 'Schließen', exact: true }).click()
  await expect(fenster).toHaveCount(0)
})

test('Mit Lesebereich öffnet weiterhin schon der Klick', async ({ page }) => {
  await expect(knopf(page)).toHaveAttribute('aria-label', /^Lesebereich: rechts/)
  await zeilen(page).first().click()
  await expect(offeneMail(page)).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
