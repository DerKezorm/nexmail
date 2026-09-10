/* Der Auswahlmodus am Telefon: langer Druck oder „Auswählen", Kreise links,
 * die Leiste unten — und wirkt sie wirklich auf den Server?
 *
 * Nur im Projekt „schmal": Am Schreibtisch gibt es weder Knopf noch Geste;
 * dort sammelt man mit Strg und Umschalt (handeln.spec.ts).
 *
 * ⚠️ **Der lange Druck ist ein echter Mauszug**, nicht `dispatchEvent`:
 * `mouse.down`, warten, `mouse.up`. Der Browser erzeugt daraus dieselben
 * Pointer-Events wie ein Finger, samt dem `click`, der nach dem Loslassen
 * noch kommt — und genau der darf die Nachricht nicht öffnen. Was damit NICHT
 * geprüft ist: die Sprechblase und die Textmarkierung des iPhones beim langen
 * Druck (`-webkit-touch-callout`). Das bleibt eine Frage an ein echtes Gerät.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { anmelden, serverabsagen, TESTPOSTFACH } from './hilfen'

test.describe.configure({ mode: 'serial' })

/* Welcher Ordner-Knopf in der Schublade zum Ordner mit Post geführt hat —
   gesetzt vom beforeEach, gebraucht für den Rückweg. */
let quellKnopf = ''

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'schmal', 'Den Auswahlmodus gibt es nur in der schmalen Ansicht.')
  await anmelden(page)
  await inTestOrdnerMitPost(page)
})

test('„Auswählen" schaltet den Modus ein, Tipps markieren, „Fertig" schaltet aus', async ({ page }) => {
  const zeilen = page.locator('button[draggable="true"]')
  test.skip((await zeilen.count()) < 2, 'Zwei Nachrichten braucht es, um zwei zu wählen.')

  await page.getByRole('button', { name: 'Auswählen' }).click()
  await expect(page.getByText('0 ausgewählt')).toBeVisible()

  await zeilen.nth(0).click()
  await zeilen.nth(1).click()
  await expect(page.getByText('2 ausgewählt')).toBeVisible()
  await expect(zeilen.nth(0)).toHaveAttribute('aria-pressed', 'true')
  await expect(zeilen.nth(1)).toHaveAttribute('aria-pressed', 'true')
  /* ⚠️ Im Modus öffnet ein Tipp nichts — sonst wäre er kein Modus. Die
     schmale Leseansicht hätte einen Zurück-Knopf; der darf nicht da sein. */
  await expect(page.getByRole('button', { name: 'Zurück' })).toHaveCount(0)

  // Noch einmal tippen nimmt heraus.
  await zeilen.nth(1).click()
  await expect(page.getByText('1 ausgewählt')).toBeVisible()
  await expect(zeilen.nth(1)).toHaveAttribute('aria-pressed', 'false')

  // „Alle" nimmt alle sichtbaren, danach heißt der Knopf „Keine".
  await page.getByRole('button', { name: 'Alle', exact: true }).click()
  await expect(page.getByText(`${await zeilen.count()} ausgewählt`)).toBeVisible()
  await page.getByRole('button', { name: 'Keine', exact: true }).click()
  await expect(page.getByText('0 ausgewählt')).toBeVisible()

  await page.getByRole('button', { name: 'Fertig' }).click()
  await expect(page.getByRole('button', { name: 'Auswählen' })).toBeVisible()
  await expect(zeilen.nth(0)).not.toHaveAttribute('aria-pressed', 'true')
})

test('Ein langer Druck markiert die Zeile, ein kurzer öffnet sie, ein Zug tut nichts', async ({ page }) => {
  const zeilen = page.locator('button[draggable="true"]')

  await langDruecken(zeilen.first(), 700)
  await expect(page.getByText('1 ausgewählt')).toBeVisible()
  await expect(zeilen.first()).toHaveAttribute('aria-pressed', 'true')
  // Der Klick nach dem Loslassen hat nichts geöffnet.
  await expect(page.getByRole('button', { name: 'Zurück' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Fertig' }).click()

  /* Ein Druck mit Bewegung ist Rollen oder Wischen, kein langer Druck —
     sonst markierte jedes Rollen mit ruhendem Daumen eine Zeile. */
  await ziehenUndHalten(zeilen.first(), 700)
  await expect(page.getByText(/ausgewählt/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Auswählen' })).toBeVisible()

  // Ein kurzer Druck ist ein Tipp und öffnet die Nachricht.
  await zeilen.first().click()
  await expect(page.getByRole('button', { name: 'Zurück' })).toBeVisible()
  await page.getByRole('button', { name: 'Zurück' }).click()
  await expect(page.getByRole('button', { name: 'Auswählen' })).toBeVisible()
})

test('„Gelesen" in der Leiste setzt das Flag beim Server und lässt sich zurückdrehen', async ({ page }) => {
  const absagen = serverabsagen(page)
  const zeilen = page.locator('button[draggable="true"]')
  const leiste = page.getByRole('navigation', { name: 'Aktionen für die Auswahl' })
  const knopf = leiste.getByRole('button', { name: /^(Gelesen|Ungelesen)$/ })

  await langDruecken(zeilen.first(), 700)
  await expect(page.getByText('1 ausgewählt')).toBeVisible()
  const vorher = await knopf.innerText()

  /* ⚠️ Der eigentliche Wächter: Das Flag muss den Server erreichen. Eine rein
     örtliche Änderung sähe in der Liste genauso aus. */
  const hin = page.waitForResponse((r) => r.url().includes('/flags') && r.request().method() !== 'GET')
  await knopf.click()
  expect((await hin).status(), 'Das Flag kam nicht durch.').toBe(200)
  // Danach ist der Modus aus.
  await expect(page.getByRole('button', { name: 'Auswählen' })).toBeVisible()

  // Dieselbe Zeile noch einmal: Der Knopf muss jetzt das Gegenteil anbieten.
  await langDruecken(zeilen.first(), 700)
  await expect(page.getByText('1 ausgewählt')).toBeVisible()
  expect(await knopf.innerText(), 'Der Knopf hat den neuen Stand nicht erkannt.').not.toBe(vorher)

  // Und zurück, damit das Postfach so dasteht wie vorher.
  const zurueck = page.waitForResponse((r) => r.url().includes('/flags') && r.request().method() !== 'GET')
  await knopf.click()
  expect((await zurueck).status()).toBe(200)
  await absagen.pruefen()
})

test('Die Leiste archiviert beim Server; das Blatt „Verschieben" holt die Mail zurück', async ({ page }) => {
  const absagen = serverabsagen(page)
  const zeilen = page.locator('button[draggable="true"]')
  /* Der rohe Ordnername aus der Überschrift — so heißt der Zielordner auch
     im Blatt (beides `o.name`, nicht die Übersetzung). */
  const quellTitel = await page.locator('h2').first().innerText()
  const betreff = await zeilen.first().locator('div.min-w-0 > div').nth(1).innerText()
  /* ⚠️ Der Betreff benennt nicht immer genau eine Mail (die Anhang-Tests
     legen Prüfnachrichten paarweise an). Gezählt wird, wie viele Treffer es
     vorher gab — hinterher muss es einer weniger sein. */
  const inQuelle = zeilen.filter({ hasText: betreff })
  const vorherInQuelle = await inQuelle.count()

  await langDruecken(zeilen.first(), 700)
  await expect(page.getByText('1 ausgewählt')).toBeVisible()

  const befehl = page.waitForResponse((r) => r.url().includes('/api/nachrichten/archivieren'))
  await page
    .getByRole('navigation', { name: 'Aktionen für die Auswahl' })
    .getByRole('button', { name: 'Archivieren' })
    .click()
  const antwort = await befehl
  expect(antwort.status(), 'Das Archivieren kam nicht durch.').toBe(200)
  expect(((await antwort.json()) as { bewegt: number }).bewegt, 'Der Server hat nichts bewegt.').toBe(1)

  await expect(page.getByRole('status').filter({ hasText: 'Archiviert' })).toBeVisible()
  await expect
    .poll(() => inQuelle.count(), { message: 'Die archivierte Zeile steht noch in der Liste.' })
    .toBe(vorherInQuelle - 1)
  await expect(page.getByRole('button', { name: 'Auswählen' })).toBeVisible()
  await absagen.pruefen()

  // Ins Archiv, dort per Blatt „Verschieben" zurück in den Ausgangsordner.
  await inOrdner(page, /^Archiv( \d+)?$/)
  const imArchiv = zeilen.filter({ hasText: betreff })
  await expect(imArchiv.first(), 'Die Mail liegt nicht im Archiv.').toBeVisible({ timeout: 15_000 })
  const vorher = await imArchiv.count()

  await langDruecken(imArchiv.first(), 700)
  await expect(page.getByText('1 ausgewählt')).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Aktionen für die Auswahl' })
    .getByRole('button', { name: 'Verschieben' })
    .click()
  const blatt = page.getByRole('dialog', { name: 'Verschieben' })
  await expect(blatt).toBeVisible()
  await blatt.getByRole('menuitem', { name: quellTitel, exact: true }).click()

  await expect(page.getByRole('status').filter({ hasText: 'Nachricht verschoben' })).toBeVisible({
    timeout: 20_000,
  })
  await expect(imArchiv, 'Die Mail ist nicht aus dem Archiv verschwunden.').toHaveCount(vorher - 1, {
    timeout: 20_000,
  })
  await expect(page.getByRole('button', { name: 'Auswählen' })).toBeVisible()

  await inOrdner(page, knopfMuster(quellKnopf))
  await expect(zeilen.filter({ hasText: betreff }).first(), 'Die Nachricht kam nicht zurück.').toBeVisible({
    timeout: 15_000,
  })
  await absagen.pruefen()
})

/* --- Hilfen ------------------------------------------------------------- */

/** Ein langer Druck als echter Mauszug: drücken, halten, loslassen. */
async function langDruecken(zeile: Locator, ms: number) {
  const kasten = await zeile.boundingBox()
  if (!kasten) throw new Error('Die Zeile hat keinen Kasten.')
  const maus = zeile.page().mouse
  await maus.move(kasten.x + kasten.width / 2, kasten.y + kasten.height / 2)
  await maus.down()
  await zeile.page().waitForTimeout(ms)
  await maus.up()
}

/** Drücken, dabei deutlich wandern, halten, loslassen — ein Rollen. */
async function ziehenUndHalten(zeile: Locator, ms: number) {
  const kasten = await zeile.boundingBox()
  if (!kasten) throw new Error('Die Zeile hat keinen Kasten.')
  const maus = zeile.page().mouse
  const x = kasten.x + kasten.width / 2
  const y = kasten.y + kasten.height / 2
  await maus.move(x, y)
  await maus.down()
  await maus.move(x, y + 30, { steps: 4 })
  await zeile.page().waitForTimeout(ms)
  await maus.up()
}

/** Der Ordnerbaum des Testpostfachs in der geöffneten Schublade —
 *  dieselbe Hilfe wie in wischen.spec.ts, aus denselben Gründen. */
async function schubladeAuf(page: Page) {
  await page.getByRole('button', { name: 'Ordner ausklappen' }).click()
  const bereich = page.locator('aside section').filter({ hasText: TESTPOSTFACH }).last()
  await expect(bereich).toBeVisible()
  const kopf = bereich.getByRole('button').first()
  if ((await kopf.getAttribute('aria-expanded')) === 'false') await kopf.click()
  return bereich
}

function knopfMuster(name: string): RegExp {
  return new RegExp(`^${name}( \\d+)?$`)
}

async function inOrdner(page: Page, muster: RegExp) {
  const bereich = await schubladeAuf(page)
  await bereich.getByRole('button', { name: muster }).first().click()
  await expect(page.locator('aside[aria-hidden="true"]')).toHaveCount(1)
}

async function inTestOrdnerMitPost(page: Page) {
  const zeilen = page.locator('button[draggable="true"]')
  for (const name of ['Posteingang', 'Papierkorb', 'Gesendet']) {
    await inOrdner(page, knopfMuster(name))
    await expect
      .poll(() => zeilen.count(), { timeout: 4000 })
      .toBeGreaterThan(0)
      .catch(() => {})
    if (await zeilen.count()) {
      quellKnopf = name
      return
    }
  }
  test.skip(true, 'Keine Nachricht im Testpostfach — nichts auszuwählen.')
}
