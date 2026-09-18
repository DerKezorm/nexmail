/* Der Riegel fürs eigene Netz — Verwaltung → Server.
 *
 * ⚠️ **Gemeldet am 18.09.2026:** Ein selbst betriebenes Nextcloud ließ sich
 * nicht verbinden, „Adressen im eigenen Netz sind gesperrt". Die Sperre ist
 * Absicht; was fehlte, war der Weg, sie als Betreiber aufzuheben.
 *
 * Geprüft wird, was nur ein Browser weiß: dass der Schalter beim Umlegen
 * wirkt (nicht erst über „Speichern"), dass er ein Neuladen übersteht, und
 * dass der Preis danebensteht. Am Ende steht er wieder, wie er stand.
 */
import { expect, test } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keineRohenSchluessel, serverabsagen } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Verwaltung wird breit geprüft.')
  await anmelden(page)
})

const ADRESSE = '/api/einstellungen/eigenes-netz'

/** Der Stand beim Server, nicht der am Schalter.
 *
 * ⚠️ **Aus Schaden entstanden, am Tag des Baus.** Zuerst merkte sich der Test
 * den Stand, den der Schalter ANZEIGT, und stellte am Ende danach zurück. Die
 * Mutation „der Stand kommt nicht vom Server" zeigt immer „aus": Der Test
 * legte um, wurde wie verlangt rot, verglich dann „aus" mit „aus" und ließ den
 * Riegel beim Server offen stehen. Wer zurückstellt, fragt die Quelle. */
async function standBeimServer(page: import('@playwright/test').Page): Promise<boolean> {
  return ((await (await page.request.get(ADRESSE)).json()) as { erlaubt: boolean }).erlaubt
}

async function zumServer(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /Verwaltung|Administration/ }).first().click()
  await page.getByRole('tab', { name: 'Server' }).click()
  const schalter = page.getByRole('switch', { name: 'Eigenes Netz erlauben' })
  await expect(schalter).toBeEnabled({ timeout: 10_000 })
  return schalter
}

test('Der Schalter wirkt beim Umlegen und übersteht das Neuladen', async ({ page }) => {
  const absagen = serverabsagen(page)
  const vorher = await standBeimServer(page)
  let schalter = await zumServer(page)
  await expect(schalter).toHaveAttribute('aria-checked', String(vorher))

  /* ⚠️ Der Preis steht neben dem Schalter, nicht in einer README. */
  await expect(page.getByText(/jeder Benutzer dieser Installation/)).toBeVisible()
  await jederKnopfHatEinenNamen(page)
  await keineRohenSchluessel(page)

  try {
    const geschrieben = page.waitForResponse(
      (a) => a.request().method() === 'PUT' && a.url().endsWith('/api/einstellungen/eigenes-netz'),
    )
    await schalter.click()
    expect((await geschrieben).status()).toBe(200)
    await expect(schalter).toHaveAttribute('aria-checked', String(!vorher))

    await page.reload()
    schalter = await zumServer(page)
    await expect(schalter).toHaveAttribute('aria-checked', String(!vorher))
  } finally {
    /* Zurück auf den Stand von vorher, auch wenn oben etwas scheitert, und
       über die Schnittstelle statt über den Schalter: Die
       Entwicklungsdatenbank gehört nicht diesem Test. */
    await page.request.put(ADRESSE, { data: { erlaubt: vorher } })
  }
  expect(await standBeimServer(page)).toBe(vorher)
  await absagen.pruefen()
})
