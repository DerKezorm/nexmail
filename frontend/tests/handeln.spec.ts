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
import { anmelden, postfach, serverabsagen } from './hilfen'

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
  /* ⚠️ **Das Testpostfach, nicht der erstbeste Ordner dieses Namens.**
     `getByRole('button', { name: 'Papierkorb' }).first()` nimmt den des
     Postfachs, das zufaellig oben steht — und der kann leer sein, waehrend
     zwei Postfaecher weiter unten neunzehn Mails liegen. Der Helfer gab dann
     auf, `test.skip` sprang an, und **sechs von acht Tests dieser Datei
     uebersprangen sich stillschweigend**.

     ⚠️ **Ein uebersprungener Test sieht im Bericht aus wie ein gruener.** Am
     02.09.2026 war der neue Waechter fuer die Untermenues deshalb hohl: Beide
     Mutationen liefen auf Rueckgabecode 0, weil der Test gar nicht lief.

     ⚠️ **Und gewartet wird auf die Antwort, nicht auf die Uhr.** Eine feste
     Wartezeit war zu kurz, sobald der Mailserver traege ist. */
  const baum = postfach(page)
  const zeilen = page.locator('button[draggable="true"]')

  /* ⚠️ **Erst muss der Baum ueberhaupt da sein.** Die Ordner kommen je
     Postfach einzeln nach; wer sofort nach ihnen greift, findet keinen und
     haelt das Testpostfach fuer leer. Genau daran uebersprangen sich die
     Tests. */
  await expect
    .poll(() => baum.getByRole('button').count(), { timeout: 15000 })
    .toBeGreaterThan(0)

  for (const name of ['Papierkorb', 'Archiv', 'Posteingang', 'Gesendet']) {
    const knopf = baum.getByRole('button', { name }).first()
    if (!(await knopf.count())) continue
    await knopf.click()
    try {
      await expect.poll(() => zeilen.count(), { timeout: 6000 }).toBeGreaterThan(0)
      return
    } catch {
      // Dieser Ordner ist wirklich leer. Der naechste.
    }
  }
  test.skip(true, 'Im Testpostfach liegt in keinem Ordner Post.')
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

/* ⚠️ **Gemeldet am 02.09.2026: „das ist NEBEN meinem Monitor".**
 *
 * Die Untermenüs von „Schlagwort" und „Wiedervorlage" standen fest auf
 * `left-full`. Am rechten Rand kippt das Menü selbst nach links — das
 * Untermenü ging trotzdem nach rechts weiter und landete außerhalb des
 * Bildschirms. Sichtbar wird das nur ganz rechts, also genau dort, wo man es
 * beim Bauen nicht ausprobiert.
 */
test('Ein Untermenü bleibt im Bild, auch am rechten Rand', async ({ page }) => {
  // Der gemeldete Weg: eine Mail öffnen, „Weitere Aktionen" ganz rechts in der
  // Werkzeugleiste des Lesebereichs. Das Menü kippt dort nach links — das
  // Untermenü ging trotzdem weiter nach rechts.
  await page.locator('button[draggable="true"]').first().click()
  const mehr = page.getByRole('button', { name: 'Weitere Aktionen' })
  await expect(mehr).toBeVisible()

  const sicht = page.viewportSize()!
  const knopf = (await mehr.boundingBox())!
  expect(
    sicht.width - knopf.x,
    'Der Knopf steht nicht am rechten Rand — der Test misst dann nichts.',
  ).toBeLessThan(120)

  await mehr.click()
  await expect(page.getByRole('menu').first()).toBeVisible()

  let geprueft = 0
  for (const name of ['Schlagwort', 'Wiedervorlage']) {
    const punkt = page.getByRole('menuitem', { name: new RegExp(`^${name}`) }).first()
    if (!(await punkt.count())) continue
    await punkt.hover()
    const unter = page.getByRole('menu').nth(1)
    await expect(unter).toBeVisible()
    const kasten = (await unter.boundingBox())!
    geprueft += 1

    expect(
      Math.round(kasten.x + kasten.width),
      `Das Untermenü „${name}" ragt ${Math.round(kasten.x + kasten.width - sicht.width)} px ` +
        'über den rechten Rand hinaus — dort sieht es niemand.',
    ).toBeLessThanOrEqual(sicht.width)
    expect(Math.round(kasten.x), `Das Untermenü „${name}" steht links außerhalb.`).toBeGreaterThanOrEqual(0)
    expect(
      Math.round(kasten.y + kasten.height),
      `Das Untermenü „${name}" ragt unten heraus.`,
    ).toBeLessThanOrEqual(sicht.height)
  }

  // ⚠️ Ohne das ist der Test still grün, wenn es die Untermenüs gar nicht gibt.
  expect(geprueft, 'Kein einziges Untermenü geprüft.').toBeGreaterThan(0)
})

/* Dieselbe Regel nach unten. „Verschieben" trägt die längste Liste — an der
 * unteren Kante ragte sie sonst aus dem Bild, und die letzten Ordner waren
 * unerreichbar. */
test('Ein Untermenü bleibt im Bild, auch am unteren Rand', async ({ page }) => {
  /* ⚠️ **Ein flaches Fenster, sonst misst der Test nichts.** Bei 900 px Höhe
     passt das Untermenü unter die letzte Zeile — die Prüfung wäre grün, ohne
     je die Kante berührt zu haben. Ein Laptop mit 768 px ist ohnehin der
     häufigere Fall als der Entwicklungsbildschirm. */
  await page.setViewportSize({ width: 1440, height: 480 })
  const zeilen = page.locator('button[draggable="true"]')
  const letzte = zeilen.last()
  await expect(letzte).toBeVisible()
  await letzte.scrollIntoViewIfNeeded()

  const sicht = page.viewportSize()!
  const zeile = (await letzte.boundingBox())!
  await letzte.click({ button: 'right', position: { x: 20, y: zeile.height - 4 } })
  await expect(page.getByRole('menu').first()).toBeVisible()

  const punkt = page.getByRole('menuitem', { name: /^Verschieben/ }).first()
  await expect(punkt).toBeVisible()
  await punkt.hover()
  const unter = page.getByRole('menu').nth(1)
  await expect(unter).toBeVisible()

  const kasten = (await unter.boundingBox())!
  // ⚠️ Erst prüfen, dass die Lage überhaupt eng ist — sonst ist der Test
  // still grün, weil unten reichlich Platz war.
  const anker = (await punkt.boundingBox())!
  expect(
    anker.y + kasten.height,
    'Das Untermenü hätte hier ohnehin gepasst — der Test misst nichts.',
  ).toBeGreaterThan(sicht.height)
  expect(
    Math.round(kasten.y + kasten.height),
    `Das Untermenü ragt ${Math.round(kasten.y + kasten.height - sicht.height)} px unten heraus.`,
  ).toBeLessThanOrEqual(sicht.height)
  expect(Math.round(kasten.y), 'Das Untermenü ist oben herausgerutscht.').toBeGreaterThanOrEqual(0)
})
