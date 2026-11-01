/* Die Reiterleiste der Einstellungen passt auf die Seite.
 *
 * ⚠️ Gemessen wird die EINZEILIGE Breite. Bis zum 18.09.2026 brachen
 * „KI-Dienst" und „API-Schlüssel" zweizeilig um, und die Leiste lief trotzdem
 * über; ein Test, der nur scrollWidth gegen clientWidth hält, war dabei grün,
 * weil der Umbruch die Breite versteckte. Die Reiter tragen jetzt
 * `whitespace-nowrap`, also zeigt scrollWidth die Wahrheit.
 */
import { expect, test } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keineRohenSchluessel, zuEinstellungen } from './hilfen'

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

test('Die KI hat ihren eigenen Ort, keinen zweiten in den Einstellungen', async ({ page }) => {
  /* ⚠️ Der Reiter daneben lud `ich` nicht nach: Dort geschaltet, standen die
     Knöpfe in Mail und Editor erst nach dem Neuladen da. */
  await anmelden(page)
  await zuEinstellungen(page)

  await expect(page.getByRole('tab', { name: 'Signaturen' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /KI/ })).toHaveCount(0)
})

test('iPhone verbinden zeigt QR-Code, kurzen Code und Stand', async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'iPhone verbinden' }).click()

  await page.getByRole('button', { name: 'Code anzeigen' }).click()

  /* ⚠️ Gemessen, nicht nur gesucht: Ohne `viewBox` schnitt die Fläche den Code
     rechts und unten ab. Er war sichtbar, und kein Telefon konnte ihn lesen. */
  const code = page.getByRole('img', { name: 'iPhone verbinden' })
  await expect(code).toBeVisible()
  const m = await code.evaluate((rahmen) => {
    const flaeche = rahmen.getBoundingClientRect()
    const muster = rahmen.querySelector('svg path.qrline')!.getBoundingClientRect()
    return {
      breite: flaeche.width,
      links: muster.left - flaeche.left,
      rechts: flaeche.right - muster.right,
      oben: muster.top - flaeche.top,
      unten: flaeche.bottom - muster.bottom,
    }
  })
  expect(m.breite).toBe(200)
  // Vier Module Ruhezone auf jeder Seite, also etwas Weiß ringsum.
  for (const seite of [m.links, m.rechts, m.oben, m.unten]) expect(seite).toBeGreaterThan(5)
  await expect(page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeVisible()
  await expect(page.getByText(/Wartet auf die App/)).toBeVisible()
  await keineRohenSchluessel(page)
  await jederKnopfHatEinenNamen(page)

  await page.getByRole('button', { name: 'Zurückziehen' }).click()
  await expect(page.getByRole('button', { name: 'Code anzeigen' })).toBeVisible()
})
