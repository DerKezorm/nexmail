/* „Verwenden als" — einem Ordner von Hand sagen, was er ist.
 *
 * ⚠️ **Gemeldet am 18.09.2026:** „Archive" und „Delete" taten bei mehreren
 * IMAP-Postfächern nichts, und zuweisen ließ sich die Rolle nirgends. Der
 * Server hat dafür seine eigenen Tests; hier steht, was nur ein Browser weiß:
 * ob der Menüpunkt da ist, ob der Haken dem Zustand folgt, und ob vor
 * Papierkorb und Junk wirklich gefragt wird.
 *
 * ⚠️ **Nichts davon geht zum Mailserver.** Die Zuweisung lebt in nexmails
 * Datenbank; der Test räumt sie am Ende selbst wieder weg.
 */
import { expect, test } from '@playwright/test'
import { anmelden, postfach, rechtsklick, serverabsagen, zuweisungenWeg } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Das Ordner-Kontextmenü wird breit geprüft.')
  await anmelden(page)
  await zuweisungenWeg(page)
  await expect
    .poll(() => postfach(page).getByRole('button').count(), { timeout: 15000 })
    .toBeGreaterThan(0)
})

test.afterEach(async ({ page }, info) => {
  if (info.project.name === 'schmal') return
  await zuweisungenWeg(page)
})

/** Das Untermenü „Verwenden als" an einem Ordner des Testpostfachs öffnen. */
async function verwendenAls(page: import('@playwright/test').Page, name: string | RegExp) {
  await rechtsklick(page, postfach(page).getByRole('button', { name }).first())
  await page.getByRole('menuitem', { name: 'Verwenden als' }).hover()
  await expect(page.getByRole('menuitemcheckbox', { name: 'Archiv' })).toBeVisible()
}

/** Wartet, bis der Haken im Menü dort steht, wo er hingehört.
 *
 * ⚠️ **Nicht einmal nachsehen, sondern bis es stimmt.** Nach einer Zuweisung
 * lädt die Oberfläche den Ordnerbaum neu, und das Menü entsteht aus dem Baum,
 * wie er beim Rechtsklick gerade dasteht. Beim ersten Lauf ging es auf, bevor
 * der neue Baum da war: Der Test meldete „die Rolle kommt nicht zurück",
 * während sie in der Datenbank längst wieder stand. */
async function hakenSteht(
  page: import('@playwright/test').Page,
  ordner: string,
  eintrag: string,
) {
  await expect(async () => {
    await page.keyboard.press('Escape')
    await verwendenAls(page, ordner)
    await expect(page.getByRole('menuitemcheckbox', { name: eintrag })).toHaveAttribute(
      'aria-checked',
      'true',
      { timeout: 1000 },
    )
  }).toPass({ timeout: 15000 })
}

test('Der Haken steht an dem, was der Ordner ist', async ({ page }) => {
  await verwendenAls(page, 'Archiv')
  await expect(page.getByRole('menuitemcheckbox', { name: 'Archiv' })).toHaveAttribute(
    'aria-checked',
    'true',
  )
  await expect(page.getByRole('menuitemcheckbox', { name: 'Papierkorb' })).toHaveAttribute(
    'aria-checked',
    'false',
  )
  /* Ohne Zuweisung von Hand gibt es nichts zurückzunehmen. */
  await expect(page.getByRole('menuitem', { name: 'Wieder selbst erkennen' })).toBeDisabled()
})

test('Am Schreibtisch steht kein „…" an den Ordnern', async ({ page }) => {
  /* Das „…" ist der Weg am Telefon, wo es keinen Rechtsklick gibt. Am
     Schreibtisch wäre es eine zweite Tür zum selben Menü, in einer Spalte,
     die jeden Pixel für Ordnernamen braucht. */
  await expect(postfach(page).getByRole('button', { name: /^Mehr zu/ })).toHaveCount(0)
})

test('Den Posteingang legt niemand um', async ({ page }) => {
  await rechtsklick(page, postfach(page).getByRole('button', { name: 'Posteingang' }).first())
  await expect(page.getByRole('menuitem', { name: 'Verwenden als' })).toBeDisabled()
})

test('Vor Papierkorb wird gefragt, und Abbrechen ändert nichts', async ({ page }) => {
  const absagen = serverabsagen(page)
  let geschrieben = 0
  page.on('request', (a) => {
    if (a.method() === 'PUT' && /\/ordner\/\d+\/rolle$/.test(a.url())) geschrieben += 1
  })

  await verwendenAls(page, 'Archiv')
  await page.getByRole('menuitemcheckbox', { name: 'Papierkorb' }).click()

  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  /* ⚠️ **Der Satz ist der Punkt.** Das Aufräumen leert jeden Ordner mit
     dieser Rolle endgültig; wer das erst hinterher erfährt, hat es nicht
     entschieden. */
  await expect(fenster.getByText(/endgültig/)).toBeVisible()
  await fenster.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(fenster).toBeHidden()

  expect(geschrieben, 'Abbrechen hat trotzdem geschrieben.').toBe(0)
  await absagen.pruefen()
})

test('Eine Zuweisung gilt sofort und lässt sich zurücknehmen', async ({ page }) => {
  const absagen = serverabsagen(page)

  /* Das Archiv des Testpostfachs wird zum gewöhnlichen Ordner … */
  await verwendenAls(page, 'Archiv')
  const antwort = page.waitForResponse(
    (a) => a.request().method() === 'PUT' && /\/ordner\/\d+\/rolle$/.test(a.url()),
  )
  await page.getByRole('menuitemcheckbox', { name: 'Gewöhnlicher Ordner' }).click()
  expect((await antwort).status()).toBe(200)
  await absagen.pruefen()

  await hakenSteht(page, 'Archiv', 'Gewöhnlicher Ordner')
  await expect(page.getByRole('menuitemcheckbox', { name: 'Archiv' })).toHaveAttribute(
    'aria-checked',
    'false',
  )

  /* … und wieder zurück: Der Server sagt weiterhin „Archiv", und ohne
     Zuweisung gilt das wieder. */
  const zurueck = page.waitForResponse(
    (a) => a.request().method() === 'PUT' && /\/ordner\/\d+\/rolle$/.test(a.url()),
  )
  await page.getByRole('menuitem', { name: 'Wieder selbst erkennen' }).click()
  expect((await zurueck).status()).toBe(200)

  await hakenSteht(page, 'Archiv', 'Archiv')
  await expect(page.getByRole('menuitem', { name: 'Wieder selbst erkennen' })).toBeDisabled()
})
