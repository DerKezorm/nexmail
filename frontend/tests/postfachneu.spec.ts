/* Der Weg zu einem neuen Postfach: Kachel, Weiche, Formular.
 *
 * ⚠️ **Geprüft wird die Folge, nicht der Klick.** Ein (+), das ein Fenster
 * öffnet, in dem nichts weiterführt, sieht aus wie eines, das tut — deshalb
 * hört kein Test hier an der Kachel auf, sondern erst im Formular.
 */
import { expect, test } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, zuEinstellungen } from './hilfen'

test.beforeEach(async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Postfächer' }).click()
})

test('Die (+)-Kachel steht neben den Postfächern', async ({ page }) => {
  /* ⚠️ **Sie ist der einzige Weg hinein.** Vorher stand darunter ein Knopf;
     mit Kacheln wäre ein Knopf daneben ein zweiter Weg zum selben Ziel. */
  const plus = page.getByRole('button', { name: 'Postfach hinzufügen' })
  await expect(plus).toBeVisible()

  // Die Kacheln selbst: mindestens ein Postfach, und es trägt seine Adresse.
  await expect(page.getByText('@', { exact: false }).first()).toBeVisible()
})

test('Die Weiche führt bis ins Formular', async ({ page }) => {
  await page.getByRole('button', { name: 'Postfach hinzufügen' }).click()

  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  await expect(fenster.getByText('IMAP und SMTP')).toBeVisible()

  /* ⚠️ **Bis zur Wirkung durchtragen.** Ein Fenster, dessen Auswahl nirgends
     ankommt, ist der Fehler, den „ein Test hört nicht am Knopf auf" meint. */
  await fenster.getByText('IMAP und SMTP').click()

  /* ⚠️ **Nicht `fenster` prüfen, sondern seinen Inhalt.** Die Weiche
     schließt und das Formular öffnet — beide sind `role=dialog`, der Locator
     träfe also einfach das nächste und wäre nie verborgen. */
  await expect(page.getByText('Woher kommt das Postfach?')).toBeHidden()
  await expect(page.getByLabel('E-Mail-Adresse')).toBeVisible()
})

test('Jeder Knopf im Fenster hat einen Namen', async ({ page }) => {
  /* ⚠️ Die Wege sind selbstgebaute Kacheln, keine `Button`. Genau dort ist
     schon einmal ein Name verschwunden (das Benutzermenü, 01.09.2026). */
  await page.getByRole('button', { name: 'Postfach hinzufügen' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await jederKnopfHatEinenNamen(page)
})

test('Ohne eingetragene App gibt es keine Auswahl, sondern das Formular', async ({ page }) => {
  /* ⚠️ **Eine Seite mit einem einzigen Knopf ist ein Klick, der nichts
     entscheidet.** Hat der Betreiber weder Google noch Microsoft eingetragen,
     führt die Kachel gleich ins Formular.

     Die Antwort wird hier gefälscht: Die Entwicklungsumgebung HAT eine
     Google-App, und ohne sie ließe sich der andere Fall nie zeigen. */
  await page.route('**/api/mailoauth/moeglich', (weg) =>
    weg.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { art: 'google', name: 'Google', eingerichtet: false },
        { art: 'microsoft', name: 'Microsoft', eingerichtet: false },
      ]),
    }),
  )

  await page.getByRole('button', { name: 'Postfach hinzufügen' }).click()

  // Das Formular steht selbst in einem Fenster — geprüft wird also, dass die
  // Weiche übersprungen wurde, nicht dass gar kein Fenster da ist.
  await expect(page.getByLabel('E-Mail-Adresse')).toBeVisible()
  await expect(page.getByText('Woher kommt das Postfach?')).toBeHidden()
})

test('Ein eingetragener Anbieter steht als eigener Weg da', async ({ page }) => {
  await page.route('**/api/mailoauth/moeglich', (weg) =>
    weg.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { art: 'google', name: 'Google', eingerichtet: true },
        { art: 'microsoft', name: 'Microsoft', eingerichtet: true },
      ]),
    }),
  )

  await page.getByRole('button', { name: 'Postfach hinzufügen' }).click()
  const fenster = page.getByRole('dialog')

  for (const weg of ['IMAP und SMTP', 'Google', 'Microsoft']) {
    await expect(fenster.getByText(weg, { exact: true })).toBeVisible()
  }

  /* ⚠️ **Microsoft kann keinen Kalender**, und der Text sagt es — sonst wartet
     jemand auf Termine, die nie kommen. */
  await fenster.getByText('Microsoft', { exact: true }).click()
  await expect(fenster.getByText(/Zugriff auf das Postfach/)).toBeVisible()
})
