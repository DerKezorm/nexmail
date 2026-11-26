/* API-Schlüssel (Modul schluessel 1.0.0): der ganze Weg, nicht der Knopf.
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
import { anmelden, bereich, jederKnopfHatEinenNamen, keineRohenSchluessel, keinSeitlichesScrollen, serverabsagen, TESTPOSTFACH, zuEinstellungen } from './hilfen'

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

    // Der Riegel steht seit dem Bauplan „Einstellungen“ unter Server › Allgemein › Schnittstellen (Modul schluessel).
    await zuEinstellungen(page, 'Allgemein')
    const riegel = page.getByTestId('interfaces-api')
    await expect(riegel, 'Der Betreiber sieht den Riegel nicht.').toBeVisible()
    if (!(await riegel.isChecked())) {
      await riegel.click()
      await expect(riegel).toBeChecked()
    }

    await bereich(page, 'Verbindungen')
    await page.getByTestId('api-keys-new').click()
    const fenster = page.getByTestId('key-dialog')
    await fenster.getByTestId('key-name').fill(NAME)
    await fenster.getByTestId('key-right-headers').click()
    const haken = fenster.getByTestId('key-areas').getByRole('checkbox', { name: new RegExp(`^${TESTPOSTFACH}\\b`) })
    await haken.check()
    await expect(haken).toBeChecked()
    // Das Recht für Schlagworte steht eigens da, neben dem für Aufgaben (#17).
    const marken = fenster.getByTestId('key-option-tags')
    await expect(marken).not.toBeChecked()
    await marken.check()
    await expect(marken).toBeChecked()
    await fenster.getByTestId('key-submit').click()

    const feld = page.getByTestId('key-secret').locator('input')
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
    const ich = await (await page.request.get('/api/v1/me', { headers: mit })).json()
    expect(ich.key, 'Das Häkchen kam nicht beim Schlüssel an.').toMatchObject({ tags: true, tasks: false })
    expect((await page.request.get('/api/v1/tags', { headers: mit })).status()).toBe(200)

    await page.getByTestId('key-done').click()
    await expect(page.getByTestId('key-secret')).toHaveCount(0)

    // In der Liste: der Name; widerrufen wirkt sofort.
    // Die Tabelle des Bausatzes hat Tisch- und Handyansicht zugleich im DOM, eine davon versteckt: die sichtbare Zeile.
    const zeile = page.getByTestId('key-row').filter({ hasText: NAME }).filter({ visible: true })
    await expect(zeile).toBeVisible()
    await keinSeitlichesScrollen(page)
    await page.screenshot({ path: `test-results/apischluessel-liste-${info.project.name}.png` })
    await zeile.getByTestId('key-revoke').click()
    await page.getByTestId('key-revoke-dialog').getByRole('button', { name: 'Widerrufen' }).click()
    await expect(page.getByTestId('key-row').filter({ hasText: NAME })).toHaveCount(0, { timeout: 10_000 })
    expect((await page.request.get('/api/v1/summary', { headers: mit })).status()).toBe(401)

    await absagen.pruefen()
  } finally {
    await page.request.put('/api/apischluessel/erlaubt', { data: vorher })
  }
})
