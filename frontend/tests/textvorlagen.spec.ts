/* Textvorlagen — der ganze Weg, nicht der Knopf.
 *
 * Eine Vorlage, die sich anlegen lässt und im Verfassen-Fenster nicht
 * ankommt, ist eine Einstellung, die nichts tut — und das ist schlimmer als
 * keine. Der Test trägt sie durch: anlegen, im Fenster einfügen, den Text im
 * Editor wiederfinden, wieder wegräumen.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/textvorlagen.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import { anmelden, serverabsagen, zuEinstellungen } from './hilfen'

test('Vorlage anlegen, im Verfassen-Fenster einfügen, wieder entfernen', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  const absagen = serverabsagen(page)
  const name = 'ZZ-Probe-Vorlage'
  const inhalt = 'ZZ-Vorlagentext für die Probe'

  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Signaturen' }).click()

  // Der eigene Abschnitt unter den Signaturen.
  await expect(
    page.getByRole('heading', { name: 'Textvorlagen' }),
    'Der Abschnitt „Textvorlagen" fehlt im Reiter Signaturen.',
  ).toBeVisible()

  // Erst wenn die Liste geladen ist, lässt sich zählen — der Knopf erscheint
  // genau dann.
  await expect(page.getByRole('button', { name: 'Neue Vorlage' })).toBeVisible()

  // ⚠️ Aufräumen VOR dem Anlegen: Ein abgebrochener früherer Lauf lässt die
  // Probe-Vorlage liegen, und der Server weist den doppelten Namen dann mit
  // „gibt es schon" ab — der Test scheiterte an seinem eigenen Rest.
  const altlast = page.locator('li', { hasText: name })
  if ((await altlast.count()) > 0) {
    await altlast.getByRole('button', { name: 'Vorlage entfernen' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Vorlage entfernen' }).click()
    await expect(page.getByText(name)).toHaveCount(0, { timeout: 10_000 })
  }

  await page.getByRole('button', { name: 'Neue Vorlage' }).click()
  await page.getByRole('textbox', { name: 'Name' }).fill(name)
  await page.locator('.ProseMirror').first().click()
  await page.keyboard.type(inhalt)
  await page.getByRole('button', { name: 'Vorlage speichern' }).click()

  // ⚠️ Die Wirkung, nicht der Klick: Sie steht in der Liste.
  await expect(
    page.getByText(name).first(),
    'Die Vorlage taucht nach dem Speichern nicht in der Liste auf.',
  ).toBeVisible({ timeout: 10_000 })

  // Ins Verfassen-Fenster — dort sitzt das Menü „Vorlage" neben „Anhang".
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: 'Neue Nachricht' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()

  const menueKnopf = fenster.getByRole('button', { name: 'Vorlage', exact: true })
  await expect(menueKnopf, 'Der Menü-Knopf „Vorlage" fehlt im Verfassen-Fenster.').toBeVisible()
  await expect(menueKnopf).toHaveAttribute('aria-haspopup', 'menu')
  await menueKnopf.click()

  await fenster.getByRole('menuitem', { name }).click()

  // ⚠️ Bis in den Editor: Der Text steht wirklich drin.
  await expect(
    fenster.locator('.ProseMirror'),
    'Der Vorlagentext kommt nicht im Editor an — eingefügt wurde nichts.',
  ).toContainText(inhalt, { timeout: 10_000 })

  // Aufräumen 1: Den angefangenen Entwurf verwerfen, nicht aufbewahren.
  await fenster.getByRole('button', { name: 'Verwerfen' }).click()
  await expect(fenster).toHaveCount(0)

  // Aufräumen 2: Die Vorlage wieder weg — über die eigene Rückfrage.
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Signaturen' }).click()
  await page
    .locator('li', { hasText: name })
    .getByRole('button', { name: 'Vorlage entfernen' })
    .click()
  await page.getByRole('dialog').getByRole('button', { name: 'Vorlage entfernen' }).click()
  await expect(page.getByText(name)).toHaveCount(0, { timeout: 10_000 })

  await absagen.pruefen()
})

test('Ein gescheiterter Abruf sieht nicht wie Leere aus', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  // Der Abruf scheitert — als wäre der Server gerade nicht da. Kein
  // serverabsagen-Wächter hier: Der Fehler ist der Gegenstand des Tests.
  await page.route('**/api/textvorlagen', (route) => route.abort())

  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Signaturen' }).click()

  // ⚠️ Kein „Noch keine Textvorlagen" — das sähe wie Datenverlust aus.
  // Stattdessen: der Fehlerbalken mit dem Nachhol-Knopf.
  await expect(
    page.getByRole('alert').filter({ hasText: 'Textvorlagen ließen sich nicht laden' }),
  ).toBeVisible()
  await expect(page.getByText('Noch keine Textvorlagen')).toHaveCount(0)

  // Der Knopf holt nach, sobald der Server wieder antwortet.
  await page.unroute('**/api/textvorlagen')
  await page.getByRole('button', { name: 'Noch einmal versuchen' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0, { timeout: 10_000 })

  // Dasselbe im Verfassen-Fenster: Das Menü „Vorlage" darf einen Fehler
  // nicht als „Noch keine Vorlagen" ausgeben.
  await page.route('**/api/textvorlagen', (route) => route.abort())
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: 'Neue Nachricht' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  await fenster.getByRole('button', { name: 'Vorlage', exact: true }).click()

  await expect(fenster.getByRole('menuitem', { name: /ließen sich nicht laden/ })).toBeVisible()
  await expect(fenster.getByText('Noch keine Vorlagen')).toHaveCount(0)

  // Ein Klick auf den Eintrag holt nach.
  await page.unroute('**/api/textvorlagen')
  await fenster.getByRole('menuitem', { name: /ließen sich nicht laden/ }).click()
  await expect(fenster.getByRole('menuitem', { name: /ließen sich nicht laden/ })).toHaveCount(0, {
    timeout: 10_000,
  })

  await fenster.getByRole('button', { name: 'Verwerfen' }).click()
  await expect(fenster).toHaveCount(0)
})
