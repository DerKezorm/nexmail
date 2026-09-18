/* Das Ordnermenü am Telefon.
 *
 * ⚠️ **Bis 0.17.0 hatte ein Ordner am Telefon gar kein Menü.** Die Spalte
 * kannte nur den Rechtsklick, und den gibt es dort nicht: Weder „Neuer Ordner"
 * noch Favorit noch „Verwenden als" waren erreichbar. Aufgefallen beim Bau
 * von „Verwenden als" am 18.09.2026, nicht durch eine Meldung: Wer es nicht
 * findet, meldet es nicht als „fehlt", sondern benutzt es nicht.
 *
 * Der Weg ist ein sichtbares „…" je Ordner in der Schublade, dahinter dasselbe
 * Blatt wie bei der Post und beim Kalender, mit **denselben Einträgen** wie im
 * Kontextmenü am Schreibtisch.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  TESTPOSTFACH,
  anmelden,
  jederKnopfHatEinenNamen,
  keinSeitlichesScrollen,
  serverabsagen,
  zuweisungenWeg,
} from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'schmal', 'Das Blatt am Ordner gibt es nur in der schmalen Ansicht.')
  await anmelden(page)
  await zuweisungenWeg(page)
})

test.afterEach(async ({ page }, info) => {
  if (info.project.name !== 'schmal') return
  await zuweisungenWeg(page)
})

async function schubladeAuf(page: Page) {
  await page.getByRole('button', { name: 'Ordner ausklappen' }).click()
  const bereich = page.locator('aside section').filter({ hasText: TESTPOSTFACH }).last()
  await expect(bereich).toBeVisible()
  const kopf = bereich.getByRole('button').first()
  if ((await kopf.getAttribute('aria-expanded')) === 'false') await kopf.click()
  return bereich
}

/** Das Blatt des Ordners öffnen. Ist die Schublade schon offen, bleibt sie es. */
async function blattAuf(page: Page, ordner: string) {
  const offen = await page.locator('aside[aria-hidden="false"]').count()
  const bereich = offen
    ? page.locator('aside section').filter({ hasText: TESTPOSTFACH }).last()
    : await schubladeAuf(page)
  await bereich.getByRole('button', { name: `Mehr zu „${ordner}“` }).click()
  const blatt = page.getByRole('dialog')
  await expect(blatt).toBeVisible()
  return blatt
}

test('Jeder Ordner trägt ein sichtbares „…", und dahinter steht das ganze Menü', async ({ page }) => {
  const bereich = await schubladeAuf(page)

  /* Sichtbar, nicht hinter einem langen Druck: je Ordner genau einer. */
  const ordner = await bereich.getByRole('button', { name: /^(Posteingang|Archiv|Papierkorb)( \d+)?$/ }).count()
  expect(ordner).toBeGreaterThanOrEqual(3)
  for (const name of ['Posteingang', 'Archiv', 'Papierkorb']) {
    await expect(bereich.getByRole('button', { name: `Mehr zu „${name}“` })).toBeVisible()
  }
  await jederKnopfHatEinenNamen(page)
  /* ⚠️ Das „…" kostet Breite in einer Schublade von 280 px. Geprüft wird,
     dass dabei nichts seitlich überläuft. */
  await keinSeitlichesScrollen(page)

  const blatt = await blattAuf(page, 'Archiv')
  /* Dieselben Einträge wie am Schreibtisch, nicht eine Auswahl davon. */
  for (const eintrag of [
    /^Zu Favoriten hinzufügen$/,
    /^Neuer Ordner/,
    /^Verwenden als$/,
    /^Ordner herunterladen/,
    /^Ordner umbenennen$/,
  ]) {
    await expect(blatt.getByRole('menuitem', { name: eintrag })).toBeVisible()
  }
  await keinSeitlichesScrollen(page)

  /* Ein Fenster hat einen sichtbaren Ausgang, und er ändert nichts. */
  await blatt.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(blatt).toBeHidden()
})

test('„Verwenden als" ist eine zweite Seite, und die Zuweisung kommt beim Server an', async ({ page }) => {
  const absagen = serverabsagen(page)
  let blatt = await blattAuf(page, 'Archiv')
  await blatt.getByRole('menuitem', { name: 'Verwenden als', exact: true }).click()

  /* Der Haken steht an dem, was der Ordner ist. */
  await expect(blatt.getByRole('menuitemcheckbox', { name: 'Archiv' })).toHaveAttribute(
    'aria-checked',
    'true',
  )

  const geschrieben = page.waitForResponse(
    (a) => a.request().method() === 'PUT' && /\/ordner\/\d+\/rolle$/.test(a.url()),
  )
  await blatt.getByRole('menuitemcheckbox', { name: 'Gewöhnlicher Ordner' }).click()
  expect((await geschrieben).status()).toBe(200)
  await expect(blatt).toBeHidden()
  await absagen.pruefen()

  /* ⚠️ Bis es stimmt, nicht einmal: Das Blatt entsteht aus dem Baum, wie er
     beim Antippen dasteht, und der lädt nach der Zuweisung erst neu. */
  await expect(async () => {
    await page.keyboard.press('Escape')
    blatt = await blattAuf(page, 'Archiv')
    await blatt.getByRole('menuitem', { name: 'Verwenden als', exact: true }).click()
    await expect(blatt.getByRole('menuitemcheckbox', { name: 'Gewöhnlicher Ordner' })).toHaveAttribute(
      'aria-checked',
      'true',
      { timeout: 1000 },
    )
  }).toPass({ timeout: 15000 })
})

test('Der Posteingang bietet „Verwenden als" nicht an', async ({ page }) => {
  const blatt = await blattAuf(page, 'Posteingang')
  await expect(blatt.getByRole('menuitem', { name: 'Verwenden als', exact: true })).toBeDisabled()
})
