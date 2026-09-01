/* Das Kontextmenü — tut es wirklich etwas?
 *
 * ⚠️ **Aus Schaden entstanden, 01.09.2026.** Kein einziger Menüpunkt tat
 * etwas, und keiner meldete einen Fehler: Ein Zuhörer am Dokument schloss das
 * Menü in der Erfassungsphase bei jedem `pointerdown` — auch bei einem auf
 * dem Menü selbst. Der Klick landete im Nichts.
 *
 * Deshalb prüft jeder Test hier die **Folge**, nicht den Klick. Und die Folge
 * wird an der Beschriftung des Menüpunkts abgelesen: Sie kommt aus dem
 * Zustand der Anwendung und kippt, wenn die Handlung angekommen ist.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, serverabsagen } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Kontextmenü wird in der breiten Ansicht geprüft.')
  await anmelden(page)
  await inOrdnerMitNachrichten(page)
})

test('Das Kontextmenü öffnet sich und zeigt die Einträge', async ({ page }) => {
  await kontext(page)

  for (const eintrag of ['Antworten', 'Weiterleiten', 'Verschieben', 'Löschen']) {
    await expect(page.getByRole('menuitem', { name: new RegExp(eintrag) }).first()).toBeVisible()
  }
})

test('„Markieren" wirkt und lässt sich zurücknehmen', async ({ page }) => {
  const absagen = serverabsagen(page)
  const muster = /^(Markieren|Markierung entfernen)$/
  const vorher = await klickenUndLesen(page, muster)
  const nachher = await beschriftung(page, muster)

  // ⚠️ **Zuerst die Ursache.** Hat der Server abgesagt, ist die unveränderte
  // Beschriftung nur die Folge — und die Meldung darüber führt in die Irre.
  await absagen.pruefen()
  expect(nachher, `Beschriftung blieb „${vorher}" — die Handlung kam nicht an.`).not.toBe(vorher)

  // Zurückdrehen, damit der nächste Lauf denselben Stand vorfindet.
  await klickenUndLesen(page, muster)
})

test('„Als gelesen/ungelesen markieren" wirkt', async ({ page }) => {
  const absagen = serverabsagen(page)
  const muster = /^Als (gelesen|ungelesen) markieren$/
  const vorher = await klickenUndLesen(page, muster)
  const nachher = await beschriftung(page, muster)

  await absagen.pruefen()
  expect(nachher, `Beschriftung blieb „${vorher}" — die Handlung kam nicht an.`).not.toBe(vorher)

  await klickenUndLesen(page, muster)
})

test('Ein Klick im Menü schickt wirklich etwas zum Server', async ({ page }) => {
  /* ⚠️ Der eigentliche Wächter gegen den Fehler von oben: Damals ging **gar
     keine** Anfrage hinaus. Ein Test, der nur die Anzeige prüft, könnte von
     einer rein örtlichen Änderung getäuscht werden. */
  const anfragen: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/')) anfragen.push(r.url().split('/api/')[1])
  })

  await kontext(page)
  anfragen.length = 0
  await page.getByRole('menuitem', { name: /^(Markieren|Markierung entfernen)$/ }).first().click()

  await expect
    .poll(() => anfragen.length, {
      message: 'Der Klick hat keine einzige Anfrage ausgelöst.',
      timeout: 8000,
    })
    .toBeGreaterThan(0)

  // Wieder zurück.
  await kontext(page)
  await page.getByRole('menuitem', { name: /^(Markieren|Markierung entfernen)$/ }).first().click()
})

test('„Verschieben" bietet Zielordner an', async ({ page }) => {
  await kontext(page)
  await page.getByRole('menuitem', { name: 'Verschieben' }).first().hover()

  // ⚠️ Ein Untermenü ohne Einträge ist ein toter Eintrag.
  const untermenue = page.getByRole('menu').nth(1)
  await expect(untermenue).toBeVisible()
  expect(await untermenue.getByRole('menuitem').count()).toBeGreaterThan(0)
})

test('„Neuer Unterordner" fragt im eigenen Fenster nach', async ({ page }) => {
  const browserkasten: string[] = []
  page.on('dialog', async (d) => {
    browserkasten.push(d.type())
    await d.dismiss()
  })

  const ordner = page.getByRole('button', { name: 'Posteingang' }).first()
  await ordner.click({ button: 'right' })
  await page.getByRole('menuitem', { name: /Neuer Unterordner/ }).click()

  await expect(
    page.getByRole('dialog'),
    'Kein eigenes Fenster — der Menüpunkt tat nichts oder benutzte einen Browser-Kasten.',
  ).toBeVisible()
  await page.getByRole('button', { name: 'Abbrechen' }).click()
  expect(browserkasten).toEqual([])
})

/* --- Hilfen ------------------------------------------------------------- */

async function inOrdnerMitNachrichten(page: Page) {
  for (const name of ['Papierkorb', 'Archiv', 'Posteingang', 'Gesendet']) {
    const knopf = page.getByRole('button', { name }).first()
    if (!(await knopf.count())) continue
    await knopf.click()
    // ⚠️ Warten, bis die Liste **dieses** Ordners steht. Ohne das misst der
    // Test den vorigen Ordner - genau daran ist der erste Anlauf gescheitert.
    await page.waitForTimeout(800)
    if (await page.locator('button[draggable="true"]').count()) return
  }
  test.skip(true, 'Kein Ordner mit Nachrichten gefunden.')
}

async function kontext(page: Page) {
  const zeile = page.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible()
  await zeile.click({ button: 'right' })
  await expect(page.getByRole('menu').first()).toBeVisible()
}

/** Die aktuelle Beschriftung eines Menüpunkts — sie spiegelt den Zustand. */
async function beschriftung(page: Page, muster: RegExp): Promise<string> {
  await kontext(page)
  const text = (await page.getByRole('menuitem', { name: muster }).first().textContent()) ?? ''
  await page.keyboard.press('Escape')
  return text.trim()
}

/** Menü öffnen, Beschriftung merken, klicken. Gibt die alte Beschriftung zurück.
 *
 * ⚠️ **Auf die Antwort warten, nicht auf die Uhr.** Eine feste Wartezeit war
 * zu kurz: Die Anmeldung am Mailserver läuft in eine Zeitgrenze, die Antwort
 * traf erst danach ein — der Wächter für Serverabsagen sah nichts und der
 * Test meldete die Folge statt der Ursache. Am 01.09.2026 genau daran eine
 * halbe Stunde verloren.
 */
async function klickenUndLesen(page: Page, muster: RegExp): Promise<string> {
  await kontext(page)
  const eintrag = page.getByRole('menuitem', { name: muster }).first()
  const alt = ((await eintrag.textContent()) ?? '').trim()

  const antwort = page
    .waitForResponse((r) => r.url().includes('/flags'), { timeout: 20_000 })
    .catch(() => null)
  await eintrag.click()
  await antwort
  // Kurz nachfassen, damit React den neuen Zustand gezeichnet hat.
  await page.waitForTimeout(400)
  return alt
}
