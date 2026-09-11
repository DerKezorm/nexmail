/* Der Kalender am Telefon: Monat mit Punkten und Tagesliste, die Liste, die
 * Schublade mit den Kalendern, der runde Knopf.
 *
 * Nur im Projekt „schmal": Breit gibt es diese Ansicht nicht; dort prüft
 * kalender.spec.ts das Raster.
 *
 * ⚠️ **Jeder Test räumt hinter sich auf**, über die Adresse, wie in
 * kalender.spec.ts: Die Termine landen in nexmails eigener Datenbank.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden } from './hilfen'

test.describe.configure({ mode: 'serial' })

/** Ein Name, den kein echter Termin trägt. */
const PROBE = 'ZZ-Telefonprobe'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'schmal', 'Die Telefonansicht des Kalenders gibt es nur schmal.')
  await anmelden(page)
  await aufraeumen(page)
  await zumKalender(page)
})

test.afterEach(async ({ page }, info) => {
  if (info.project.name !== 'schmal') return
  await aufraeumen(page)
})

test('Der Monat zeigt den Termin als Punkt und in der Tagesliste, ein Tipp öffnet ihn', async ({ page }) => {
  await anlegen(page, `${PROBE} Zahnarzt`)
  await zumKalender(page)

  /* Heute ist beim Öffnen gewählt; die Zelle trägt den ganzen Tag als Namen
     und einen Punkt in der Farbe des Kalenders. */
  const heute = page.getByRole('button', { name: langesDatum(new Date()), exact: true })
  await expect(heute).toHaveAttribute('aria-pressed', 'true')
  /* ⚠️ Mindestens ein Punkt, nicht genau einer: Das Entwicklungspostfach hat
     verbundene Kalender, und die können heute selbst etwas haben. */
  await expect
    .poll(() => heute.locator('span[aria-hidden]').count(), {
      message: 'Die Tageszelle trägt keinen Punkt für den Termin.',
    })
    .toBeGreaterThan(0)

  const eintrag = page.getByRole('button', { name: new RegExp(`${PROBE} Zahnarzt`) })
  await expect(eintrag).toBeVisible()
  await eintrag.click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  await expect(fenster.getByLabel('Titel')).toHaveValue(`${PROBE} Zahnarzt`)
  await page.keyboard.press('Escape')
  await expect(fenster).toHaveCount(0)
})

test('Die Liste führt den Termin unter „Heute"', async ({ page }) => {
  await anlegen(page, `${PROBE} Chor`)
  await zumKalender(page)

  await page.getByRole('button', { name: 'Liste', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Liste', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(page.getByRole('button', { name: new RegExp(`${PROBE} Chor`) })).toBeVisible()
  /* Das erste „Heute" ist der Knopf im Kopf, das letzte die Marke am Tag in
     der Liste — und nur die zweite beweist, dass der Tag als heute gilt. */
  await expect(page.getByText('Heute', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('Heute', { exact: true })).toHaveCount(2)
})

test('Ein Haken in der Schublade blendet den Kalender beim Server aus', async ({ page }) => {
  await anlegen(page, `${PROBE} Kino`)
  await zumKalender(page)
  const eintrag = page.getByRole('button', { name: new RegExp(`${PROBE} Kino`) })
  await expect(eintrag).toBeVisible()

  await page.getByRole('button', { name: 'Kalender wählen' }).click()
  const schublade = page.locator('aside[aria-hidden="false"]')
  await expect(schublade).toBeVisible()

  /* ⚠️ Der eigentliche Wächter: Das Ausblenden muss den Server erreichen —
     eine rein örtliche Änderung sähe in der Liste genauso aus. */
  const befehl = page.waitForResponse(
    (r) => /\/api\/kalender\/[^/]+$/.test(r.url()) && r.request().method() === 'PATCH',
  )
  /* ⚠️ Der Haken selbst ist ein `sr-only`-Eingabefeld; geklickt wird das
     sichtbare Etikett, das dazugehört. */
  const haken = schublade.getByRole('checkbox').first()
  await expect(haken).toBeChecked()
  await schublade.locator('label').first().click()
  expect((await befehl).status(), 'Das Ausblenden kam nicht durch.').toBe(200)
  await expect(haken).not.toBeChecked()

  await schublade.getByRole('button', { name: 'Schließen' }).click()
  await expect(page.locator('aside[aria-hidden="true"]')).toHaveCount(1)
  await expect(eintrag, 'Der ausgeblendete Kalender zeigt noch Termine.').toHaveCount(0)
})

test('Das Menü eines Kalenders kommt als Blatt von unten', async ({ page }) => {
  /* ⚠️ Am Telefon gibt es keinen Rechtsklick; bis 0.14.1 gab es umbenennen,
     Farbe, ICS und trennen dort gar nicht. Die Einträge sind dieselben wie
     im Kontextmenü am Schreibtisch. */
  await page.getByRole('button', { name: 'Kalender wählen' }).click()
  const schublade = page.locator('aside[aria-hidden="false"]')
  await expect(schublade).toBeVisible()

  await schublade.getByRole('button', { name: /^Mehr zu/ }).first().click()
  const blatt = page.getByRole('dialog')
  await expect(blatt).toBeVisible()
  for (const eintrag of ['Umbenennen', 'Farbe ändern', 'Kalender herunterladen …']) {
    await expect(blatt.getByRole('menuitem', { name: eintrag })).toBeVisible()
  }
  /* Der eine sichtbare Ausgang: Abbrechen. Danach steht die Schublade noch. */
  await blatt.getByRole('button', { name: 'Abbrechen' }).click()
  await expect(blatt).toHaveCount(0)
  await expect(schublade).toBeVisible()
})

test('Der runde Knopf öffnet das Terminfenster für den gewählten Tag', async ({ page }) => {
  await page.getByRole('button', { name: 'Neuer Termin' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  await expect(fenster.getByLabel('Titel')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(fenster).toHaveCount(0)
})

/* --- Hilfen ------------------------------------------------------------- */

/** Frisch in den Kalender — über die Post, damit die Seite neu lädt.
 *  ⚠️ Ein Klick auf „Kalender", während der Kalender schon offen ist, tut
 *  nichts; ein über die Adresse angelegter Termin bliebe dann unsichtbar. */
async function zumKalender(page: Page) {
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Monat', exact: true })).toBeVisible()
}

/** Der Name der Tageszelle — so, wie der Browser ihn baut. */
function langesDatum(d: Date): string {
  return d.toLocaleDateString('de', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

/** Einen Termin heute um 10 Uhr anlegen — über die Adresse, wie in
 *  kalender.spec.ts; der Test der Oberfläche kommt danach. */
async function anlegen(page: Page, titel: string) {
  const status = await page.evaluate(async (titel) => {
    const ks = (await (await fetch('/api/kalender', { credentials: 'include' })).json()) as Array<{
      id: string
      nur_lesen?: boolean
    }>
    /* Den ersten Kalender, in den man schreiben darf — ein Abo nähme den
       Termin nicht an, und der Test sähe eine leere Zelle statt der Ursache. */
    const ziel = ks.find((k) => !k.nur_lesen) ?? ks[0]
    const beginn = new Date()
    beginn.setHours(10, 0, 0, 0)
    const ende = new Date(beginn)
    ende.setHours(11)
    const antwort = await fetch('/api/kalender/termine', {
      method: 'POST',
      credentials: 'include',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        kalender_id: ziel.id,
        titel,
        beginn: beginn.toISOString(),
        ende: ende.toISOString(),
      }),
    })
    return antwort.status
  }, titel)
  expect(status, 'Der Probetermin ließ sich nicht anlegen.').toBeLessThan(300)
}

async function aufraeumen(page: Page) {
  for (const versuch of [1, 2]) {
    try {
      await page.waitForLoadState('domcontentloaded')
      await einmalAufraeumen(page)
      return
    } catch (f) {
      if (versuch === 2) throw f
      await page.waitForTimeout(1000)
    }
  }
}

async function einmalAufraeumen(page: Page) {
  await page.evaluate(async (probe) => {
    const von = new Date()
    von.setMonth(von.getMonth() - 2)
    const bis = new Date()
    bis.setMonth(bis.getMonth() + 2)
    const frage = new URLSearchParams({ von: von.toISOString(), bis: bis.toISOString() })
    const alle = await (
      await fetch(`/api/kalender/termine?${frage}`, { credentials: 'include' })
    ).json()
    for (const t of alle as Array<{ id: number; titel: string }>) {
      if (t.titel.startsWith(probe)) {
        await fetch(`/api/kalender/termine/${t.id}?umfang=alle`, {
          method: 'DELETE',
          credentials: 'include',
        })
      }
    }
    const ks = await (await fetch('/api/kalender', { credentials: 'include' })).json()
    for (const k of ks as Array<{ id: string; sichtbar: boolean }>) {
      if (!k.sichtbar) {
        await fetch(`/api/kalender/${k.id}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sichtbar: true }),
        })
      }
    }
  }, PROBE)
}
