/* API-Schlüssel — der ganze Weg, nicht der Knopf.
 *
 * Anlegen, den einmal gezeigten Schlüssel wirklich gegen `/api/v1` benutzen,
 * widerrufen und sehen, dass er sofort nichts mehr öffnet. Ein Schlüssel, der
 * sich anlegen lässt und danach nichts liest, wäre eine Einstellung, die
 * nichts tut.
 *
 * ⚠️ **Der Riegel wird zurückgestellt, wie er vorgefunden wurde.** Der Test
 * läuft auf der Entwicklungsinstallation; ein Lauf, der API-Schlüssel dort
 * offen stehen lässt, verändert eine Entscheidung des Betreibers.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/apischluessel.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import {
  TESTPOSTFACH,
  anmelden,
  jederKnopfHatEinenNamen,
  keinSeitlichesScrollen,
  keineRohenSchluessel,
  serverabsagen,
  zuEinstellungen,
} from './hilfen'

const NAME = 'ZZ-Probe-Schluessel'

test('Schlüssel anlegen, damit lesen, widerrufen', async ({ page }, info) => {
  const absagen = serverabsagen(page)
  await anmelden(page)

  const vorher = await (await page.request.get('/api/apischluessel/erlaubt')).json()

  try {
    // ⚠️ Aufräumen VOR dem Anlegen: Ein abgebrochener Lauf lässt seinen
    // Schlüssel liegen, und der zählt gegen die Obergrenze.
    const alt = (await (await page.request.get('/api/apischluessel')).json()).schluessel as {
      id: string
      name: string
    }[]
    for (const s of alt.filter((s) => s.name === NAME)) {
      await page.request.delete(`/api/apischluessel/${s.id}`)
    }

    await zuEinstellungen(page)
    await page.getByRole('tab', { name: 'API-Schlüssel' }).click()

    // Der Riegel steht hier, nicht in der Verwaltung.
    const riegel = page.getByRole('switch', { name: 'API-Schlüssel erlauben' })
    await expect(riegel, 'Der Betreiber sieht den Riegel nicht.').toBeVisible()
    if ((await riegel.getAttribute('aria-checked')) !== 'true') {
      await riegel.click()
      await expect(riegel).toHaveAttribute('aria-checked', 'true')
    }

    await page.getByRole('button', { name: 'Neuer Schlüssel' }).click()
    const fenster = page.getByRole('dialog')
    await fenster.getByRole('textbox', { name: 'Name' }).fill(NAME)
    await fenster.getByRole('combobox').selectOption('betreff')
    await expect(fenster.getByText(/Denk daran, wer davorsteht/)).toBeVisible()
    const haken = fenster.getByRole('checkbox', { name: new RegExp(`^${TESTPOSTFACH}\\b`) })
    // Das Feld selbst ist unsichtbar (sr-only); geklickt wird wie von Hand
    // auf seine Beschriftung.
    await fenster.getByText(TESTPOSTFACH, { exact: true }).click()
    await expect(haken).toBeChecked()
    await fenster.getByRole('button', { name: 'Schlüssel anlegen' }).click()

    const feld = fenster.getByRole('textbox', { name: 'API-Schlüssel' })
    await expect(feld, 'Nach dem Anlegen steht kein Schlüssel da.').toBeVisible({ timeout: 10_000 })
    const schluessel = await feld.inputValue()
    expect(schluessel).toMatch(/^nxm_[A-Za-z0-9_-]{40,}$/)

    await page.screenshot({ path: `test-results/apischluessel-neu-${info.project.name}.png` })
    await jederKnopfHatEinenNamen(page)
    await keineRohenSchluessel(page)

    // Die Wirkung: Mit genau diesem Schlüssel liest eine fremde Anwendung.
    const mit = { Authorization: `Bearer ${schluessel}` }
    const stand = await page.request.get('/api/v1/summary', { headers: mit })
    expect(stand.status()).toBe(200)
    const postfaecher = ((await stand.json()).mailboxes as { name: string }[]).map((m) => m.name)
    expect(postfaecher, 'Der Schlüssel sieht nicht das freigegebene Postfach.').toEqual([
      TESTPOSTFACH,
    ])
    expect((await page.request.get('/api/v1/messages/latest', { headers: mit })).status()).toBe(200)

    await fenster.getByRole('button', { name: /Schließen|Close/ }).click()
    await expect(fenster).toHaveCount(0)

    // In der Liste: Name, Stufe, Postfach, „zuletzt benutzt".
    const zeile = page.locator('li', { hasText: NAME })
    await expect(zeile.getByText('Absender und Betreff')).toBeVisible()
    await expect(zeile.getByText(TESTPOSTFACH)).toBeVisible()
    await expect(zeile.getByText(/zuletzt benutzt/)).toBeVisible()
    await keinSeitlichesScrollen(page)
    await page.screenshot({ path: `test-results/apischluessel-liste-${info.project.name}.png` })

    // Widerrufen wirkt sofort.
    await zeile.getByRole('button', { name: `${NAME} widerrufen` }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Widerrufen' }).click()
    await expect(page.locator('li', { hasText: NAME })).toHaveCount(0, { timeout: 10_000 })
    expect((await page.request.get('/api/v1/summary', { headers: mit })).status()).toBe(401)

    await absagen.pruefen()
  } finally {
    await page.request.put('/api/apischluessel/erlaubt', { data: vorher })
  }
})
