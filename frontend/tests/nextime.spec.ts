/* nextime verbinden (MAIL-1): Karte unter „Verbindungen", Gruppen und Farben im
 * Kalender, nur Geändertes beim Speichern.
 *
 * ⚠️ **nextime wird vorgespielt**, an nexmails eigenen Adressen unter
 * `/api/nextime`. Was der Server mit nextime tut, prüft `test_nextime.py`;
 * hier geht es darum, was der Mensch sieht und was die Oberfläche schickt.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/nextime.spec.ts --project=desktop --reporter=line
 */
import { expect, test } from '@playwright/test'
import { anmelden, bereich, keineRohenSchluessel, zuEinstellungen, zurAnsicht } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die nextime-Ansichten werden breit geprüft.')
})

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

const KALENDER = [
  { id: 'nt:1', name: 'Persönlich', farbe: 1, sichtbar: true, art: 'nextime', herkunft: 'nextime', nur_lesen: false,
    letzter_fehler: '', gruppe: 'own', farbe_nextime: 'red', standard: true, nur_belegt: false, hintergrund: false },
  { id: 'nt:2', name: 'D&M', farbe: 1, sichtbar: true, art: 'nextime', herkunft: 'iCloud', nur_lesen: false,
    letzter_fehler: '', gruppe: 'icloud', farbe_nextime: 'blue', standard: false, nur_belegt: false, hintergrund: false },
  { id: 'nt:4', name: 'Kollegin', farbe: 1, sichtbar: true, art: 'nextime', herkunft: 'nextime', nur_lesen: true,
    letzter_fehler: '', gruppe: 'shared', farbe_nextime: 'teal', standard: false, nur_belegt: true, hintergrund: false },
]

function termin(heute: Date, mehr: Record<string, unknown>) {
  const beginn = new Date(heute)
  beginn.setHours(10, 0, 0, 0)
  const ende = new Date(beginn.getTime() + 60 * 60 * 1000)
  return {
    id: -101, kalender_id: 'nt:2', titel: 'Elternabend', beginn: beginn.toISOString(), ende: ende.toISOString(),
    ganztaegig: false, ort: '', beschreibung: '', aus_reihe: false, wiederholung: '', wiederholung_tage: [],
    wiederholung_intervall: 1, regel_freq: '', regel_intervall: 1, regel_tage: [], regel_monatsart: 'tag',
    regel_ordinal: 1, regel_ende: 'nie', regel_anzahl: 0, regel_bis: '', regel_fremd: false, organisator: null,
    teilnehmer: [], rrule: '', aus_einladung: false, eingeladen: false, fremde_antworten: [], erinnerung: -1,
    fern: { id: 55, vorkommen: null, etag: 'e1', link: 'https://zeit.example.com/day?event=55', beschreibbar: true,
            nur_belegt: false, hintergrund: false, uid: 'u55', einladung: '', herkunft: '', zeitzone: 'Europe/Berlin' },
    ...mehr,
  }
}

test('Die Karte verbindet nextime mit Adresse und Schlüssel (AC-1, AC-2)', async ({ page }) => {
  let verbunden = false
  const geschickt: unknown[] = []
  await page.route('**/api/nextime/verbindung', async (route) => {
    if (route.request().method() === 'POST') {
      geschickt.push(route.request().postDataJSON())
      verbunden = true
      await route.fulfill({ json: { verbunden: true, adresse: 'https://zeit.example.com', name: 'Robin',
                                    version: '0.2.0', letzter_fehler: '', kalender: 3 } })
      return
    }
    await route.fulfill({ json: verbunden
      ? { verbunden: true, adresse: 'https://zeit.example.com', name: 'Robin', version: '0.2.0', letzter_fehler: '' }
      : { verbunden: false, adresse: '', name: '', version: '', letzter_fehler: '' } })
  })
  await anmelden(page)
  await zuEinstellungen(page)
  await bereich(page, 'Verbindungen')

  const karte = page.getByRole('region', { name: 'nextime' })
  await expect(karte.getByText('nicht verbunden')).toBeVisible()
  await karte.getByRole('button', { name: /nextime/ }).first().click()
  await karte.getByRole('textbox', { name: /^Adresse/ }).fill('https://zeit.example.com')
  // Seit dem Bauplan „Einstellungen“ (E3) heißt das Feld „API-Schlüssel“.
  await karte.getByLabel('API-Schlüssel', { exact: true }).fill('probe-sch-1')
  await karte.getByRole('button', { name: 'Verbinden' }).click()

  await expect.poll(() => geschickt.length).toBe(1)
  expect(geschickt[0]).toEqual({ adresse: 'https://zeit.example.com', schluessel: 'probe-sch-1' })
  await expect(karte.getByText('Verbunden, 3 Kalender.')).toBeVisible()
  await expect(karte.getByText('zeit.example.com', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'nextasks' })).toBeVisible()
  // Aufbau wie in nextime (gemeldet am 24.11.2026): das Formular ist weg, unten
  // stehen „Schlüssel ändern" und „Trennen" nebeneinander.
  await expect(karte.getByRole('textbox', { name: /^Adresse/ })).toBeHidden()
  const aendern = karte.getByRole('button', { name: 'Schlüssel ändern' })
  const trennen = karte.getByRole('button', { name: 'Trennen', exact: true })
  const [a, b] = await Promise.all([aendern.boundingBox(), trennen.boundingBox()])
  expect(Math.abs(a!.y - b!.y)).toBeLessThan(2)
  // „Schlüssel ändern" öffnet das Formular mit „Abbrechen" links vom Hauptknopf.
  await aendern.click()
  await expect(karte.getByRole('textbox', { name: /^Adresse/ })).toHaveValue('https://zeit.example.com')
  const abbrechen = karte.getByRole('button', { name: 'Abbrechen' })
  expect((await karte.getByRole('button', { name: 'Verbinden' }).boundingBox())!.x).toBeGreaterThan(
    (await abbrechen.boundingBox())!.x,
  )
  await abbrechen.click()
  await expect(aendern).toBeVisible()
  await keineRohenSchluessel(page)
})

test('Kalender aus nextime stehen in ihren Gruppen, und Speichern schickt nur Geändertes (AC-3, AC-6)', async ({ page }) => {
  const heute = new Date()
  const geaendert: unknown[] = []
  await page.route('**/api/nextime/kalender', (route) => route.fulfill({ json: KALENDER }))
  await page.route('**/api/nextime/stand', (route) => route.fulfill({ json: { version: 'v1' } }))
  await page.route('**/api/nextime/termine?*', (route) => route.fulfill({ json: [termin(heute, {})] }))
  await page.route('**/api/nextime/termine/55*', async (route) => {
    if (route.request().method() === 'PATCH') {
      geaendert.push(route.request().postDataJSON())
      await route.fulfill({ json: termin(heute, { titel: 'Elternabend 4b', beschreibung: 'Raum 12' }) })
      return
    }
    await route.fulfill({ json: termin(heute, { beschreibung: 'Raum 12' }) })
  })
  await anmelden(page)
  await zurAnsicht(page, 'Kalender')

  const spalte = page.locator('main, body')
  await expect(spalte.getByRole('heading', { name: 'iCloud' })).toBeVisible()
  await expect(spalte.getByRole('heading', { name: 'Geteilt' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'D&M' })).toBeChecked()

  await page.getByRole('button', { name: /Elternabend/ }).first().click()
  const fenster = page.getByRole('dialog')
  // Die Notiz kommt aus dem Einzelabruf, nicht aus dem Fenster der Woche.
  await expect(fenster.getByLabel('Notiz')).toHaveValue('Raum 12')
  await expect(fenster.getByRole('link', { name: 'In nextime öffnen' })).toHaveAttribute(
    'href', 'https://zeit.example.com/day?event=55')
  await expect(fenster.getByText('Erinnerungen an diesen Termin kommen aus nextime.')).toBeVisible()
  await fenster.getByLabel('Titel').fill('Elternabend 4b')
  await fenster.getByRole('button', { name: 'Speichern' }).click()

  await expect.poll(() => geaendert.length).toBe(1)
  expect(geaendert[0]).toEqual({ titel: 'Elternabend 4b', umfang: 'alle', vorkommen: null, etag: 'e1' })
  await keineRohenSchluessel(page)
})

test('„Kalender hinzufügen" führt zu nextime, Karte aufgeklappt (Befund 2 vom 24.11.2026)', async ({ page }) => {
  await page.route('**/api/nextime/verbindung', (route) =>
    route.fulfill({ json: { verbunden: false, adresse: '', name: '', version: '', letzter_fehler: '' } }),
  )
  await anmelden(page)
  await zurAnsicht(page, 'Kalender')
  await page.getByRole('button', { name: 'Kalender hinzufügen' }).first().click()
  const fenster = page.getByRole('dialog')
  await expect(fenster.getByText('Alle deine Kalender aus nextime auf einmal', { exact: false })).toBeVisible()
  await fenster.getByRole('button', { name: /^nextime/ }).click()

  const karte = page.getByRole('region', { name: 'nextime' })
  await expect(karte.getByRole('button', { name: 'Verbinden' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await keineRohenSchluessel(page)
})
