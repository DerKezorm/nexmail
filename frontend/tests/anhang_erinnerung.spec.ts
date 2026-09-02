/* Die Anhang-Erinnerung — „im Anhang" geschrieben, nichts dran?
 *
 * Drei Wege, in der Reihenfolge des Alltags:
 *
 * 1. Text kündigt einen Anhang an, keiner dran → die Nachfrage kommt, und
 *    Abbrechen lässt das Fenster unverändert offen. Nichts geht hinaus.
 * 2. Mit Anhang → keine Nachfrage, die Mail geht wie bisher.
 * 3. **Der wichtigste Fall:** Die Antwort auf genau diese Mail. „im Anhang"
 *    steht im Zitat, nicht im eigenen Text → KEINE Nachfrage. Das prüft die
 *    Schneide-Logik (`lib/anhang.ts`) über das echte Verhalten: Fiele der
 *    Zitat-Schnitt weg, stünde hier eine Nachfrage im Weg.
 *
 * ⚠️ **Der Test sendet wirklich** — an das eigene Testpostfach, damit Fall 3
 * eine echte Mail mit „im Anhang" im Rumpf vorfindet. Die Antwort geht an
 * example.com (RFC 2606), dort liest niemand mit. Aufgeräumt wird am Ende.
 */
import { Buffer } from 'node:buffer'
import { expect, test, type Page } from '@playwright/test'
import { TESTPOSTFACH, anmelden, postfach, rechtsklick, serverabsagen } from './hilfen'

test.describe.configure({ mode: 'serial' })

/* Ein Betreff, den kein liegen gebliebener Rest eines früheren Laufs tragen
 * kann — beide Tests teilen ihn: Der zweite antwortet auf die Mail des ersten. */
const betreff = `ZZ-Anhangprobe ${Date.now()}`

/** Die Überschrift der Nachfrage — genau daran erkennt der Test sie. */
const frage = (page: Page) => page.getByRole('heading', { name: 'Ohne Anhang senden?' })

/** Testpostfach in „Von" wählen und die eigene Adresse aus dem Eintrag lesen.
 *  Nichts wird fest eingetragen: Die Adresse steht im `<option>` als
 *  „Anzeigename — adresse", und nur dort. */
async function vonTestpostfach(fenster: ReturnType<Page['getByRole']>): Promise<string> {
  const von = fenster.locator('select').first()
  const eintrag = von.locator('option').filter({ hasText: TESTPOSTFACH }).first()
  await expect(
    eintrag,
    `Das Testpostfach „${TESTPOSTFACH}" fehlt in der Von-Auswahl.`,
  ).toHaveCount(1)
  await von.selectOption((await eintrag.getAttribute('value')) ?? '')
  const adresse = ((await eintrag.textContent()) ?? '').split('—').pop()?.trim() ?? ''
  expect(adresse, 'Aus dem Von-Eintrag ließ sich keine Adresse lesen.').toContain('@')
  return adresse
}

test('Ohne Anhang kommt die Nachfrage, Abbrechen ändert nichts; mit Anhang kommt keine', async ({
  page,
}, info) => {
  test.skip(
    info.project.name === 'schmal',
    'Der Ausgang wird an der Ordnerspalte geprüft — die liegt hier in der Schublade.',
  )
  test.setTimeout(120_000)

  const absagen = serverabsagen(page)
  // ⚠️ Die stärkste Form von „nichts im Ausgang": Es ging gar keine
  // Sende-Anfrage hinaus. Die Ordnerspalte allein könnte auch nur nachhinken.
  let sendeAnfragen = 0
  page.on('request', (anfrage) => {
    if (anfrage.url().includes('/api/verfassen/senden')) sendeAnfragen++
  })

  await anmelden(page)

  await page.getByRole('button', { name: 'Neue Nachricht' }).first().click()
  const fenster = page.getByRole('dialog', { name: 'Neue Nachricht' })
  await expect(fenster).toBeVisible()

  // ⚠️ Erst kurz warten: Die Signatur des vorausgewählten Postfachs kommt
  // asynchron und **ersetzt** den Editorinhalt — wer sofort tippt, verliert
  // den Text an sie und prüft danach gegen ein leeres Feld.
  await page.waitForTimeout(1000)

  const selbst = await vonTestpostfach(fenster)
  // An das eigene Postfach — der zweite Test antwortet auf genau diese Mail.
  await fenster.getByPlaceholder('Name oder Adresse').first().fill(selbst)
  await fenster.getByPlaceholder('Betreff').fill(betreff)

  const text = 'Die Unterlagen liegen im Anhang.'
  await fenster.locator('[contenteditable="true"]').first().click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type(text)

  /* 1. Senden ohne Anhang → die Nachfrage steht da. */
  await fenster.getByRole('button', { name: 'Senden', exact: true }).click()
  await expect(frage(page), 'Die Anhang-Nachfrage erscheint nicht.').toBeVisible()

  /* Abbrechen: Das Fenster bleibt unverändert offen, nichts ging hinaus.
     ⚠️ `exact` — sonst trifft auch eine Listenzeile, in deren Anriss das Wort
     zufällig vorkommt. */
  await page.getByRole('button', { name: 'Abbrechen', exact: true }).click()
  await expect(frage(page)).toHaveCount(0)
  await expect(fenster, 'Abbrechen hat das Verfassen-Fenster geschlossen.').toBeVisible()
  await expect(fenster.getByPlaceholder('Betreff')).toHaveValue(betreff)
  await expect(fenster.locator('[contenteditable="true"]').first()).toContainText(text)
  expect(sendeAnfragen, 'Trotz Abbrechen ging eine Sende-Anfrage hinaus.').toBe(0)
  await expect(page.getByRole('button', { name: /Postausgang/ })).toHaveCount(0)

  /* 2. Mit Anhang → keine Nachfrage, die Mail geht wie bisher. */
  await fenster
    .locator('input[type="file"]')
    .setInputFiles({ name: 'unterlagen.txt', mimeType: 'text/plain', buffer: Buffer.from('Probeinhalt') })
  await expect(fenster.getByText('unterlagen.txt')).toBeVisible()

  await fenster.getByRole('button', { name: 'Senden', exact: true }).click()
  await expect(frage(page)).toHaveCount(0)
  await expect(fenster, 'Die Mail mit Anhang ging nicht hinaus.').toBeHidden({ timeout: 30_000 })
  await absagen.pruefen()
})

test('Eine Antwort, deren Zitat „im Anhang" enthält, fragt nicht nach', async ({ page }, info) => {
  test.skip(
    info.project.name === 'schmal',
    'Antwort und Aufräumen laufen über Ordnerspalte und Kontextmenü der breiten Ansicht.',
  )
  // Die Mail aus dem ersten Test muss erst beim Anbieter ankommen und vom
  // Abgleich geholt werden — das dauert, und zwar draußen, nicht hier.
  test.setTimeout(300_000)

  const absagen = serverabsagen(page)
  await anmelden(page)

  const baum = postfach(page)
  await baum.getByRole('button', { name: /Posteingang|Inbox/ }).first().click()

  /* Auf die Zustellung warten: nachsehen, von Hand abgleichen, wieder
     nachsehen. ⚠️ Auf den Bestand warten, nie auf die Uhr allein — und der
     Aktualisieren-Knopf ist während eines laufenden Abgleichs gesperrt. */
  const zeile = page.locator('button[draggable="true"]').filter({ hasText: betreff }).first()
  const aktualisieren = page.getByRole('button', { name: 'Aktualisieren' })
  for (let versuch = 0; versuch < 14; versuch++) {
    if (await zeile.isVisible().catch(() => false)) break
    await expect(aktualisieren).toBeEnabled({ timeout: 60_000 })
    await aktualisieren.click()
    await expect(aktualisieren).toBeEnabled({ timeout: 60_000 })
    await page.waitForTimeout(8_000)
  }
  await expect(
    zeile,
    'Die Mail aus dem ersten Test ist nicht angekommen — ohne sie gibt es nichts zu zitieren.',
  ).toBeVisible()

  /* Antworten: Das Zitat trägt „im Anhang", der eigene Text nicht. */
  await rechtsklick(page, zeile)
  await page.getByRole('menuitem', { name: 'Antworten', exact: true }).click()
  const fenster = page.getByRole('dialog', { name: 'Antworten' })
  await expect(fenster).toBeVisible()

  // Erst wenn das Zitat wirklich da ist, beweist „keine Nachfrage" etwas.
  const editor = fenster.locator('[contenteditable="true"]').first()
  await expect(editor, 'Das Zitat mit „im Anhang" steht nicht im Editor.').toContainText(
    'im Anhang',
    { timeout: 15_000 },
  )

  /* ⚠️ Der Empfänger bleibt die eigene Adresse, die die Antwort vorausfüllt.
     example.com wäre sauberer, aber All-Inkl weist es beim **echten** Versand
     mit „554 … spam activity" ab — „Senden rückholen" merkt das nie, weil
     dort der geplante Versand vor dem SMTP wieder abgebrochen wird. Die
     ankommende Antwort räumt das Ende dieses Tests mit weg. */
  await editor.click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('Danke, ist angekommen.')

  await fenster.getByRole('button', { name: 'Senden', exact: true }).click()
  await expect(
    frage(page),
    'Die Nachfrage kam, obwohl „im Anhang" nur im Zitat steht — der Zitat-Schnitt fehlt.',
  ).toHaveCount(0)
  await expect(fenster, 'Die Antwort ging nicht hinaus.').toBeHidden({ timeout: 30_000 })
  await expect(frage(page)).toHaveCount(0)
  await absagen.pruefen()

  /* Aufräumen — die Tests laufen gegen ein echtes Postfach: die zugestellte
     Mail und die eintreffende Antwort aus dem Posteingang, danach beide
     Fassungen aus „Gesendet". */
  await rechtsklick(page, zeile)
  await page.getByRole('menuitem', { name: 'Löschen' }).click()
  await expect(zeile).toHaveCount(0, { timeout: 20_000 })

  /* Auf die Antwort an sich selbst warten und auch sie wegräumen. */
  const antwortZeile = page
    .locator('button[draggable="true"]')
    .filter({ hasText: `AW: ${betreff}` })
    .first()
  for (let versuch = 0; versuch < 14; versuch++) {
    if (await antwortZeile.isVisible().catch(() => false)) break
    await expect(aktualisieren).toBeEnabled({ timeout: 60_000 })
    await aktualisieren.click()
    await expect(aktualisieren).toBeEnabled({ timeout: 60_000 })
    await page.waitForTimeout(8_000)
  }
  await expect(antwortZeile, 'Die Antwort an sich selbst ist nicht angekommen.').toBeVisible()
  await rechtsklick(page, antwortZeile)
  await page.getByRole('menuitem', { name: 'Löschen' }).click()
  await expect(antwortZeile).toHaveCount(0, { timeout: 20_000 })

  await baum.getByRole('button', { name: /Gesendet|Sent/ }).first().click()
  const gesendete = page.locator('button[draggable="true"]').filter({ hasText: betreff })
  await expect(gesendete.first(), 'In „Gesendet" liegt keine Fassung der Probe-Mail.').toBeVisible({
    timeout: 20_000,
  })
  /* ⚠️ Über die Restzahl, nicht über `.first()`: Nach dem Löschen rückt die
     nächste Zeile an die erste Stelle — „die erste ist weg" stimmt dann nie. */
  for (let rest = await gesendete.count(); rest > 0; rest--) {
    await rechtsklick(page, gesendete.first())
    await page.getByRole('menuitem', { name: 'Löschen' }).click()
    await expect(gesendete).toHaveCount(rest - 1, { timeout: 20_000 })
  }
  await absagen.pruefen()
})
