/* Wisch-Aktionen am Handy — zieht die Zeile, wirkt die Aktion?
 *
 * Nur im Projekt „schmal": Die Geste gibt es ausschließlich in der schmalen
 * Ansicht, breit gehört die Zieh-Bewegung dem Ordnerbaum (HTML-Drag).
 *
 * ⚠️ **Warum die Wische per `dispatchEvent` simuliert werden:** Playwrights
 * Touch-Unterstützung kennt nur `tap` — eine gezogene Berührung (down,
 * mehrere moves, up) lässt sich damit nicht erzeugen, und das schmale
 * Projekt fährt Desktop Chrome ohne `hasTouch`. Die Zeile hört auf
 * Pointer-Events mit `pointerType === 'touch'`; genau die entstehen hier im
 * Seitenkontext. Was damit NICHT geprüft ist: `touch-action` und das echte
 * Rollen unter dem Finger — das bleibt eine Frage an ein echtes Gerät.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { anmelden, rechtsklick, serverabsagen, TESTPOSTFACH, zuEinstellungen } from './hilfen'

test.describe.configure({ mode: 'serial' })

/* Welcher Ordner-Knopf in der Schublade zum Ordner mit Post geführt hat —
   gesetzt vom beforeEach, gebraucht für den Rückweg. Serial + ein Worker,
   deshalb darf das hier oben stehen. */
let quellKnopf = ''

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'schmal', 'Wisch-Gesten gibt es nur in der schmalen Ansicht.')
  await anmelden(page)
  await inTestOrdnerMitPost(page)
})

test('Ein Wisch nach rechts über die Schwelle archiviert', async ({ page }) => {
  const absagen = serverabsagen(page)
  const zeilen = page.locator('button[draggable="true"]')
  const anzahl = await zeilen.count()
  /* Der rohe Ordnername aus der Überschrift — so heißt der Zielordner auch
     im Verschieben-Untermenü (beides `o.name`, nicht die Übersetzung). */
  const quellTitel = await page.locator('h2').first().innerText()
  const betreff = await zeilen.first().locator('div.min-w-0 > div').nth(1).innerText()

  /* ⚠️ Der eigentliche Wächter: Es muss wirklich ein Archivieren-Befehl zum
     Server gehen. Eine rein örtliche Änderung sähe in der Liste genauso aus. */
  const befehl = page.waitForResponse((r) => r.url().includes('/api/nachrichten/archivieren'))

  await ziehen(zeilen.first(), 200)

  const antwort = await befehl
  expect(antwort.status(), 'Das Archivieren kam nicht durch.').toBe(200)
  const ergebnis = (await antwort.json()) as { bewegt: number; rueckweg: unknown }
  expect(ergebnis.bewegt, 'Der Server hat nichts bewegt.').toBe(1)

  // Die Folge in der Oberfläche: Rückgängig-Leiste da, Zeile weg.
  await expect(page.getByRole('status').filter({ hasText: 'Archiviert' })).toBeVisible()
  await expect
    .poll(() => zeilen.count(), { message: 'Die archivierte Zeile steht noch in der Liste.' })
    .toBe(anzahl - 1)
  await absagen.pruefen()

  // Und die Mail liegt wirklich im Archiv — nachgesehen, nicht geglaubt.
  await inOrdner(page, /^Archiv( \d+)?$/)
  const archiviert = zeilen.filter({ hasText: betreff }).first()
  await expect(archiviert, 'Die Mail liegt nicht im Archiv.').toBeVisible({ timeout: 15_000 })

  /* Zurückschieben statt des Rückgängig-Knopfs: `/api/nachrichten/zurueck`
     bewegt nur auf dem IMAP-Server, in die Liste käme die Mail erst mit dem
     nächsten Abgleich — darauf zu warten machte den Test lahm und wacklig.
     „Verschieben" gleicht sofort ab, und der Rückweg ist derselbe. */
  await rechtsklick(page, archiviert)
  await page.getByRole('menuitem', { name: 'Verschieben' }).first().hover()
  const untermenue = page.getByRole('menu').nth(1)
  await expect(untermenue).toBeVisible()
  await untermenue.getByRole('menuitem', { name: quellTitel, exact: true }).click()

  /* ⚠️ Erst warten, bis das Nachladen der Handlung **gelandet** ist, dann
     weiternavigieren. Die Handlung lädt den Ordner neu, aus dem sie kam
     (Archiv); wer vorher schon den Zielordner öffnet, bekommt dessen Liste
     einen Atemzug später von genau diesem Nachladen überschrieben — die
     Liste stand dann leer da, obwohl alles gut gegangen war. Gelandet ist
     es, wenn die Archivliste wieder sichtbar ist UND die Zeile daraus
     verschwunden ist. */
  await expect(page.getByRole('status').filter({ hasText: 'Nachricht verschoben' })).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.getByRole('heading', { name: 'Archiv', exact: true })).toBeVisible()
  await expect(zeilen.filter({ hasText: betreff })).toHaveCount(0, { timeout: 20_000 })

  // Zurück im Ausgangsordner steht der alte Bestand wieder.
  await inOrdner(page, knopfMuster(quellKnopf))
  await expect
    .poll(() => zeilen.count(), { message: 'Die Nachricht kam nicht zurück.', timeout: 15_000 })
    .toBe(anzahl)
  await expect(zeilen.filter({ hasText: betreff }).first()).toBeVisible()
  await absagen.pruefen()
})

test('Unter der Schwelle schnappt die Zeile zurück und nichts passiert', async ({ page }) => {
  const zeilen = page.locator('button[draggable="true"]')
  const anzahl = await zeilen.count()

  const anfragen: string[] = []
  page.on('request', (r) => {
    if (/\/api\/nachrichten\/(archivieren|loeschen|junk)/.test(r.url())) anfragen.push(r.url())
  })

  await ziehen(zeilen.first(), 40)

  /* Erst auf das Zurückschnappen warten (die positive Beobachtung), dann die
     negativen prüfen: Ein fälschlicher Befehl wäre schon beim Loslassen
     hinausgegangen — vor dem Ende der Schnapp-Transition.

     ⚠️ Gemessen wird der **Sollwert** der Zeile (ihr inline-`transform`),
     nicht `getComputedStyle`: Das liefert während der Schnapp-Transition
     Zwischenwerte — im ersten Moment sogar exakt die Ausgangslage. Ein Poll
     darauf hielt eine hängen gebliebene Zeile für zurückgeschnappt, weil er
     genau dieses Fenster erwischte (Mutationsprobe, 02.09.2026). */
  await expect
    .poll(
      () => zeilen.first().evaluate((el) => (el as HTMLElement).style.transform),
      { message: 'Die Zeile schnappt nicht in ihre Lage zurück.' },
    )
    .toBe('translateX(0px)')

  expect(anfragen, 'Unter der Schwelle ging trotzdem ein Befehl hinaus.').toEqual([])
  expect(await zeilen.count()).toBe(anzahl)
  await expect(page.getByRole('status').filter({ hasText: 'Archiviert' })).toHaveCount(0)
})

test('Die Maus löst keinen Wisch aus', async ({ page }) => {
  /* ⚠️ Mit der Maus zieht man Zeilen in den Ordnerbaum. Würde dieselbe
     Bewegung auch als Wisch gedeutet, löschte ein angefangenes Verschieben
     nebenbei eine Mail. */
  const zeilen = page.locator('button[draggable="true"]')
  const anzahl = await zeilen.count()

  const anfragen: string[] = []
  page.on('request', (r) => {
    if (/\/api\/nachrichten\/(archivieren|loeschen|junk)/.test(r.url())) anfragen.push(r.url())
  })

  await ziehen(zeilen.first(), 200, 'mouse')

  // Kurz stehen lassen: Ein fälschlich ausgelöster Befehl bräuchte einen
  // Wimpernschlag, bis er als Anfrage sichtbar wird.
  await page.waitForTimeout(400)
  expect(anfragen, 'Die Maus hat einen Wisch-Befehl ausgelöst.').toEqual([])
  expect(await zeilen.count()).toBe(anzahl)
  await expect(page.getByRole('status').filter({ hasText: 'Archiviert' })).toHaveCount(0)
})

test('Die Einstellung wirkt: steht die Richtung auf „Aus", wischt nichts', async ({ page }) => {
  /* ⚠️ Eine Einstellung, die nichts tut, ist schlimmer als keine — deshalb
     wird hier ihre **Wirkung** gemessen, nicht ihr Speichern: umstellen,
     wischen, nichts darf passieren. */
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('combobox', { name: /Wischen nach rechts/ }).selectOption('aus')
  await page.getByRole('button', { name: 'Mail', exact: true }).click()

  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible()
  const anzahl = await zeilen.count()

  const anfragen: string[] = []
  page.on('request', (r) => {
    if (/\/api\/nachrichten\/(archivieren|loeschen|junk)/.test(r.url())) anfragen.push(r.url())
  })

  await ziehen(zeilen.first(), 200)

  // Die Zeile gibt in einer ausgeschalteten Richtung nicht einmal nach.
  await expect
    .poll(() => zeilen.first().evaluate((el) => (el as HTMLElement).style.transform))
    .toBe('translateX(0px)')
  await page.waitForTimeout(400)
  expect(anfragen, 'Trotz „Aus" ging ein Befehl hinaus.').toEqual([])
  expect(await zeilen.count()).toBe(anzahl)
  await expect(page.getByRole('status').filter({ hasText: 'Archiviert' })).toHaveCount(0)

  // Zurück auf die Vorgabe — `anmelden()` räumt zwar auch auf, aber nur in
  // Tests, die es aufrufen; ein Handgriff hier hält den Stand sauber.
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('combobox', { name: /Wischen nach rechts/ }).selectOption('archivieren')
})

/* --- Hilfen ------------------------------------------------------------- */

/** Der Ordnerbaum des Testpostfachs in der geöffneten Schublade.
 *
 * ⚠️ Nicht `postfach()` aus den Hilfen: Das sucht in **allen** `section`s,
 * und schmal stehen die Datumsgruppen der Liste im DOM vor der Schublade.
 * `.last()`, nicht `.first()`: Die Favoriten-Sektion schreibt den
 * Postfachnamen in Klammern hinter jeden Eintrag („Posteingang (Test1)")
 * und träfe den Filter zuerst — geklickt wäre dann irgendein fremder
 * Ordner. Genau so ist der erste Anlauf gescheitert.
 */
async function schubladeAuf(page: Page) {
  await page.getByRole('button', { name: 'Ordner ausklappen' }).click()
  const bereich = page.locator('aside section').filter({ hasText: TESTPOSTFACH }).last()
  await expect(bereich).toBeVisible()
  // Zugeklappt aus einem früheren Lauf? Der Kopf ist der erste Knopf.
  const kopf = bereich.getByRole('button').first()
  if ((await kopf.getAttribute('aria-expanded')) === 'false') await kopf.click()
  return bereich
}

/** Der Name eines Ordner-Knopfs, mit oder ohne Ungelesen-Zahl dahinter.
 *  ⚠️ Die Zahl steht **im** vorlesbaren Namen („Papierkorb 3") — ein
 *  `exact`-Vergleich auf den bloßen Namen findet den Ordner dann nicht.
 *  Verankert, damit „Posteingang (…)" aus den Favoriten nicht trifft. */
function knopfMuster(name: string): RegExp {
  return new RegExp(`^${name}( \\d+)?$`)
}

/** Einen Ordner des Testpostfachs öffnen — über die Schublade. */
async function inOrdner(page: Page, muster: RegExp) {
  const bereich = await schubladeAuf(page)
  await bereich.getByRole('button', { name: muster }).first().click()
  // Die Schublade schließt sich beim Klick; erst dann steht die Liste.
  await expect(page.locator('aside[aria-hidden="true"]')).toHaveCount(1)
}

/** In den ersten Ordner des Testpostfachs, in dem etwas liegt.
 *
 * Der Posteingang ist oft leer (die Läufe räumen hinter sich auf);
 * Papierkorb und Gesendet taugen genauso — archiviert wird aus jedem
 * Ordner. „Archiv" selbst bewusst nicht: von dort ins Archiv zu wischen
 * wäre ein Fehlerfall.
 */
async function inTestOrdnerMitPost(page: Page) {
  const zeilen = page.locator('button[draggable="true"]')
  for (const name of ['Posteingang', 'Papierkorb', 'Gesendet']) {
    await inOrdner(page, knopfMuster(name))
    // Auf den Bestand warten, nicht auf die Uhr — die Liste kommt nach.
    await expect
      .poll(() => zeilen.count(), { timeout: 4000 })
      .toBeGreaterThan(0)
      .catch(() => {})
    if (await zeilen.count()) {
      quellKnopf = name
      return
    }
  }
  test.skip(true, 'Keine Nachricht im Testpostfach — nichts zu wischen.')
}

/** Einen Wisch als Folge von Pointer-Events erzeugen — Begründung oben. */
async function ziehen(zeile: Locator, dx: number, art: 'touch' | 'mouse' = 'touch') {
  await zeile.evaluate(
    (el, lage) => {
      const kasten = el.getBoundingClientRect()
      const x0 = kasten.left + kasten.width / 2
      const y = kasten.top + kasten.height / 2
      const schicken = (typ: string, x: number, gedrueckt: number) =>
        el.dispatchEvent(
          new PointerEvent(typ, {
            bubbles: true,
            cancelable: true,
            pointerId: 7,
            pointerType: lage.art,
            isPrimary: true,
            clientX: x,
            clientY: y,
            buttons: gedrueckt,
          }),
        )
      schicken('pointerdown', x0, 1)
      // Mehrere Schritte, wie ein echter Finger: Die Zeile entscheidet beim
      // ersten deutlichen Versatz, wem die Geste gehört.
      for (let i = 1; i <= 6; i++) schicken('pointermove', x0 + (lage.dx * i) / 6, 1)
      schicken('pointerup', x0 + lage.dx, 0)
    },
    { dx, art },
  )
}
