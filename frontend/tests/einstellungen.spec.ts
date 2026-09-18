/* Die Reiterleiste der Einstellungen passt auf die Seite.
 *
 * ⚠️ Gemessen wird die EINZEILIGE Breite. Bis zum 18.09.2026 brachen
 * „KI-Dienst" und „API-Schlüssel" zweizeilig um, und die Leiste lief trotzdem
 * über; ein Test, der nur scrollWidth gegen clientWidth hält, war dabei grün,
 * weil der Umbruch die Breite versteckte. Die Reiter tragen jetzt
 * `whitespace-nowrap`, also zeigt scrollWidth die Wahrheit.
 */
import { expect, test } from '@playwright/test'
import { anmelden, zuEinstellungen } from './hilfen'

test.beforeEach(({}, info) => {
  test.skip(info.project.name === 'schmal', 'Schmal rollt die Leiste seitlich, das ist gewollt.')
})

test('Alle Reiter passen einzeilig auf die Seite', async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page)
  const m = await page.evaluate(() => {
    const leiste = document.querySelector('[role=tablist]') as HTMLElement
    const reiter = [...leiste.querySelectorAll('[role=tab]')] as HTMLElement[]
    return {
      breite: leiste.clientWidth,
      noetig: leiste.scrollWidth,
      reiter: reiter.length,
    }
  })
  expect(
    m.noetig,
    `Die Reiter brauchen ${m.noetig} px, die Leiste hat ${m.breite}.`,
  ).toBeLessThanOrEqual(m.breite)
})
