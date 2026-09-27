/* Was nach Archivieren, Löschen oder Verschieben aufgeht (Issue #6).
 *
 * Eingestellt unter Darstellung, ab Werk nichts. Geprüft wird mit
 * Archivieren im Posteingang des Testpostfachs und danach „Rückgängig":
 * Löschen könnte im Papierkorb endgültig sein, und Archivieren geht durch
 * denselben Rückruf.
 *
 * ⚠️ **Die Rechnung selbst steht in `lib/danach.test.ts`** (Mehrfachauswahl,
 * Ende der Liste, neue Post oben). Hier geht es darum, dass die Einstellung
 * ankommt und die Mail wirklich aufgeht.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, postfach, serverabsagen, zuEinstellungen } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Handlungen werden in der breiten Ansicht geprüft.')
  await anmelden(page)
})

const zeilen = (page: Page) => page.locator('button[draggable="true"]')
const offeneMail = (page: Page) => page.locator('article h1').first()
const lesebereich = (page: Page) => page.getByRole('button', { name: /^Lesebereich:/ })

async function einstellen(page: Page, text: string) {
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('combobox', { name: 'Nach Löschen oder Verschieben' }).selectOption({ label: text })
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
}

/** Posteingang des Testpostfachs, und die Betreffe der ersten beiden Zeilen.
 *
 *  ⚠️ **Kein `test.skip`, wenn Post fehlt.** Ein übersprungener Test sieht
 *  im Bericht aus wie ein grüner. */
async function posteingang(page: Page) {
  const baum = postfach(page)
  await expect.poll(() => baum.getByRole('button').count(), { timeout: 15000 }).toBeGreaterThan(0)
  await baum.getByRole('button', { name: 'Posteingang' }).first().click()
  await expect
    .poll(() => zeilen(page).count(), {
      timeout: 8000,
      message: 'Im Posteingang des Testpostfachs liegen keine zwei Nachrichten.',
    })
    .toBeGreaterThan(1)

  const betreffe: string[] = []
  for (const i of [1, 0]) {
    await zeilen(page).nth(i).click()
    await expect(offeneMail(page)).toBeVisible()
    betreffe[i] = (await offeneMail(page).innerText()).trim()
  }
  // Mit gleichem Betreff ließe sich nicht unterscheiden, welche aufging.
  expect(betreffe[0], 'Die ersten beiden Nachrichten tragen denselben Betreff.').not.toBe(betreffe[1])
  return betreffe
}

async function archivieren(page: Page) {
  const antwort = page.waitForResponse((r) => r.url().includes('/api/nachrichten/archivieren'))
  await page.keyboard.press('e')
  expect((await antwort).status(), 'Das Archivieren kam nicht durch.').toBe(200)
}

/** Zurückholen, damit der nächste Lauf denselben Posteingang vorfindet.
 *
 *  ⚠️ **Auch wenn der Test rot wird**, deshalb im `finally`: Sonst bliebe die
 *  Mail im Archiv, und der nächste Lauf fände einen anderen Posteingang.
 *  Die Leiste steht 8 Sekunden, länger als jede Zusicherung wartet. */
async function zurueckholen(page: Page) {
  const rueck = page.waitForResponse(
    (r) => r.url().includes('/api/nachrichten/') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Rückgängig' }).click()
  expect((await rueck).status(), 'Das Zurückholen kam nicht durch.').toBe(200)
}

test('Ab Werk geht nach dem Archivieren nichts auf', async ({ page }) => {
  const absagen = serverabsagen(page)
  await posteingang(page)

  await archivieren(page)
  try {
    await expect(page.getByRole('status').filter({ hasText: 'Archiviert' })).toBeVisible()
    await expect(offeneMail(page)).toHaveCount(0)
    await expect(page.locator('button[draggable="true"][aria-current="true"]')).toHaveCount(0)
  } finally {
    await zurueckholen(page)
  }
  await absagen.pruefen()
})

test('„Nächste" öffnet die Nachricht, die darunter stand', async ({ page }) => {
  const absagen = serverabsagen(page)
  await einstellen(page, 'Nächste Nachricht öffnen')
  const [, zweite] = await posteingang(page)

  await archivieren(page)
  try {
    await expect(offeneMail(page), 'Die nächste Nachricht ging nicht auf.').toHaveText(zweite)
    await expect(zeilen(page).first()).toHaveAttribute('aria-current', 'true')
  } finally {
    await zurueckholen(page)
  }
  await absagen.pruefen()
})

test('„Vorige" ganzseitig: die Nachricht darüber geht über der Liste auf', async ({ page }) => {
  const absagen = serverabsagen(page)
  await einstellen(page, 'Vorige Nachricht öffnen')
  const [erste] = await posteingang(page)

  // Ganzseitig, und die zweite Zeile per Doppelklick geöffnet.
  for (let i = 0; i < 3 && !/ganzseitig\./.test((await lesebereich(page).getAttribute('aria-label')) ?? ''); i++) {
    await lesebereich(page).click()
  }
  await zeilen(page).nth(1).dblclick()
  await expect(offeneMail(page)).toBeVisible()
  await expect(zeilen(page)).toHaveCount(0)

  await archivieren(page)
  try {
    // ⚠️ Nicht nur gewählt, sondern offen: Wer die alte über der Liste las,
    // soll die neue genauso vor sich haben.
    await expect(offeneMail(page), 'Die vorige Nachricht ging nicht auf.').toHaveText(erste)
    await expect(zeilen(page)).toHaveCount(0)
  } finally {
    await zurueckholen(page)
  }
  await absagen.pruefen()
})
