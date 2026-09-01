/* Sicherung und Über-Seite — durchgetragen bis zur Wirkung.
 *
 * ⚠️ **Der Test hört nicht am Knopf auf.** Er legt einen Rücksetzpunkt an,
 * findet ihn in der Tabelle wieder und räumt ihn weg — angelegt und
 * gespeichert sind hier zwei verschiedene Dinge, und kaputt ist erfahrungsgemäß
 * das zweite.
 *
 * ⚠️ **Er räumt hinterher auf.** Ein Rücksetzpunkt, der stehen bleibt, ist eine
 * 2,8-MB-Datei je Lauf — nach einer Woche fragt sich jemand, wohin die Platte
 * verschwindet.
 */
import { expect, test } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keinTextLaeuftUeber, serverabsagen } from './hilfen'

const NOTIZ = 'zz-probe-sicherung'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  await anmelden(page)
})

/** Wartet, bis sich die Zeilenzahl nicht mehr ändert, und gibt sie zurück. */
async function ruhigeZahl(zeilen: import('@playwright/test').Locator): Promise<number> {
  let letzte = -1
  await expect
    .poll(
      async () => {
        const jetzt = await zeilen.count()
        const stabil = jetzt === letzte
        letzte = jetzt
        return stabil
      },
      { timeout: 10_000, message: 'Die Tabelle kam nicht zur Ruhe.' },
    )
    .toBe(true)
  return letzte
}

async function zurSicherung(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /Verwaltung|Administration/ }).first().click()
  await page.getByRole('tab', { name: /Sicherung|Backup/ }).click()
  await expect(page.getByRole('button', { name: /Jetzt anlegen|Create now/ })).toBeVisible({
    timeout: 10_000,
  })
}

/** Reste eines abgebrochenen Laufs wegräumen.
 *
 * ⚠️ **Ohne das zeigt der nächste Lauf auf die falsche Stelle.** Bricht der
 * Test vor dem Aufräumen ab, liegen zwei Zeilen mit derselben Notiz da — und
 * Playwright meldet dann „strict mode violation" statt „das Anlegen geht
 * nicht". Genau so beim ersten Anlauf passiert.
 */
async function aufraeumen(page: import('@playwright/test').Page) {
  await page.evaluate(async (notiz) => {
    const daten = await (await fetch('/api/sicherung/liste')).json()
    for (const e of daten.eintraege as Array<{ name: string; kommentar: string }>) {
      if (e.kommentar === notiz) {
        await fetch(`/api/sicherung/liste/${encodeURIComponent(e.name)}`, { method: 'DELETE' })
      }
    }
  }, NOTIZ)
}

test('Rücksetzpunkt anlegen, wiederfinden, entfernen', async ({ page }) => {
  const absagen = serverabsagen(page)
  await zurSicherung(page)
  await aufraeumen(page)
  await page.reload()
  await zurSicherung(page)

  // ⚠️ **Erst zählen, wenn die Liste wirklich steht.** `zurSicherung` wartet
  // auf den Knopf — und der ist da, bevor die Tabelle geladen ist. Ein
  // sofortiges `count()` las deshalb einen Zwischenstand, und der Test meldete
  // hinterher eine falsche Zeilenzahl. Zweimal derselbe Wert heißt: fertig.
  const zeilen = page.locator('table tbody tr')
  const vorher = await ruhigeZahl(zeilen)

  // ⚠️ **Die Aufbewahrungszahl deckelt die Liste**, auch beim Anlegen von
  // Hand: Liegen schon so viele, wie aufgehoben werden, faellt beim naechsten
  // der aelteste weg. Der erste Anlauf dieses Tests erwartete stur
  // `vorher + 1` und schlug fehl, obwohl alles richtig lief — die Zahl stand
  // auf 5 und fuenf lagen da.
  const behalten = Number(await page.getByRole('spinbutton').inputValue())
  const erwartet = Math.min(vorher + 1, behalten)

  await page.getByRole('button', { name: /Jetzt anlegen|Create now/ }).click()
  const fenster = page.getByRole('dialog')
  await fenster.getByRole('textbox').fill(NOTIZ)
  await fenster.getByRole('button', { name: /^(Anlegen|Create)$/ }).click()

  await absagen.pruefen()

  // Die Wirkung: Der Eintrag steht in der Tabelle, mit seiner Notiz.
  await expect(page.getByRole('cell', { name: NOTIZ })).toBeVisible({ timeout: 10_000 })
  await expect(zeilen).toHaveCount(erwartet)

  // Und die Art steht dabei — sonst ist „von Hand" von „vor Update" nicht zu
  // unterscheiden, und genau das ist die Zeile, die man behalten will.
  const zeile = page.locator('tr', { hasText: NOTIZ })
  await expect(zeile).toContainText(/von Hand|manual/)

  // --- Aufräumen, und das ist zugleich der Test des Entfernens ---------- //
  await zeile.getByRole('button', { name: /Entfernen|Remove/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: /Entfernen|Remove/ }).click()

  await expect(page.getByRole('cell', { name: NOTIZ })).toHaveCount(0, { timeout: 10_000 })
  await expect(zeilen).toHaveCount(erwartet - 1)
})

test('Das Einspiel-Fenster fasst nichts an, bevor es geprüft hat', async ({ page }) => {
  await zurSicherung(page)
  await page.getByRole('button', { name: /^(Einspielen|Restore)$/ }).click()

  const fenster = page.getByRole('dialog')
  // ⚠️ Der Knopf muss gesperrt sein, solange keine Datei da ist. Sonst
  // schickt ein Klick ein leeres Formular, und die Antwort ist eine rohe
  // Pydantic-Meldung statt eines Satzes.
  await expect(fenster.getByRole('button', { name: /Prüfen|Check/ })).toBeDisabled()
  await expect(fenster).toContainText(/wird nichts angefasst|nothing is touched/)
})

test('Die Über-Seite nennt Fassung, Lizenz und was hinausgeht', async ({ page }) => {
  await page.getByRole('button', { name: /Über nexmail|About nexmail/ }).click()

  await expect(page.getByText(/AGPL-3\.0/)).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('link', { name: /github\.com\/DerKezorm\/nexmail/ })).toBeVisible()

  // ⚠️ **Der Satz über die Nachfrage muss dastehen.** nexmail liefert die
  // Schriften mit, damit es beim Öffnen niemanden anfunkt — die tägliche
  // Frage bei GitHub ist die einzige Ausnahme, und eine verschwiegene
  // Ausnahme ist ein gebrochenes Versprechen.
  await expect(page.getByText(/einzige Stelle|only place/)).toBeVisible()

  await keinTextLaeuftUeber(page)
  await jederKnopfHatEinenNamen(page)
})
