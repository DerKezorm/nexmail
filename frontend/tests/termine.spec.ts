/* Termin-Einladungen im Lesebereich.
 *
 * ⚠️ **Die Antworten des Servers sind gestellt.** In den Testpostfächern liegt
 * keine Einladung, und sich eine zu schicken hiesse, für einen Test einen
 * Termin zu erfinden. Geprüft wird das, was der Server nicht prüfen kann: dass
 * die Karte erscheint, das Unsichere benennt und die Antwort sichtbar macht.
 * Was der Server liefert, steht unter Wache in `backend/tests/test_kalender.py`.
 */
import { expect, test } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keinTextLaeuftUeber } from './hilfen'

const EINLADUNG = {
  uid: '30@example.org',
  methode: 'REQUEST',
  titel: 'Quartalsbesprechung mit dem Team',
  beschreibung: '',
  ort: 'Halle 3, Eingang Nord',
  beginn: '2026-09-10T10:00:00+02:00',
  ende: '2026-09-10T11:30:00+02:00',
  ganztaegig: false,
  fremde_zeitzone: '',
  wiederholt_sich: false,
  abgesagt: false,
  organisator: { name: 'Chefin Beispiel', adresse: 'chefin@example.org' },
  teilnehmer: [{ name: '', adresse: 'anna@example.org' }],
  antwort: '',
  antwort_am: null,
}

async function mitEinladung(page, teil = {}) {
  await page.route(/\/api\/termine\/\d+$/, (route) =>
    route.fulfill({ json: { ...EINLADUNG, ...teil } }),
  )
}

async function ersteMailOeffnen(page) {
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible()
  await zeilen.first().click()
  await expect(page.locator('article h1').first()).toBeVisible()
}

test('Die Einladung steht als Karte da, nicht als Anhang', async ({ page }) => {
  await mitEinladung(page)
  await anmelden(page)
  await ersteMailOeffnen(page)

  /* ⚠️ **Auf der Karte suchen, nicht auf der Seite.** Derselbe Ort steht auch
     im Anreißer der Zeile in der Liste; `getByText` traf dann zwei Elemente
     und der Test scheiterte an seiner eigenen Ungenauigkeit, nicht an der
     Oberfläche. Am 03.09.2026 aufgefallen, als eine zweite Einladung im
     Testpostfach lag. */
  const karte = page.locator('section').filter({ hasText: /Eingeladen von/ }).last()

  await expect(karte.getByText('Quartalsbesprechung mit dem Team')).toBeVisible()
  await expect(karte.getByText('Halle 3, Eingang Nord')).toBeVisible()
  await expect(karte.getByText(/Eingeladen von Chefin Beispiel/)).toBeVisible()
  /* ⚠️ **Der Satz, der die Erwartung geradezieht.** Er hieß bis zum Kalender
     „Einen Kalender hat es nicht"; seit es einen gibt, trennt er Zusagen vom
     Übernehmen. Der Test hing an der alten Formulierung und war danach rot,
     ohne dass etwas kaputt war. */
  await expect(page.getByText(/erst, wenn du ihn übernimmst/)).toBeVisible()
  await keinTextLaeuftUeber(page)
  await jederKnopfHatEinenNamen(page)
})

test('Eine Wiederholung wird benannt, nicht ausgerechnet', async ({ page }) => {
  /* Ausrechnen wäre gelogen, verschweigen wäre schlimmer: Man säße beim
     zweiten Termin nicht da, weil man ihn nie gesehen hat. */
  await mitEinladung(page, { wiederholt_sich: true })
  await anmelden(page)
  await ersteMailOeffnen(page)
  await expect(page.getByText(/Wiederholt sich/)).toBeVisible()
})

test('Eine unbekannte Zeitzone wird benannt, nicht verschwiegen', async ({ page }) => {
  /* ⚠️ Die Uhrzeit stillschweigend als Ortszeit auszugeben verschiebt den
     Termin um Stunden, und niemand sieht es der Anzeige an. */
  await mitEinladung(page, { fremde_zeitzone: 'Hausinterne Zeit' })
  await anmelden(page)
  await ersteMailOeffnen(page)
  await expect(page.getByText(/Hausinterne Zeit.*unbekannt/)).toBeVisible()
})

test('Eine Absage zeigt keine Antwortknöpfe', async ({ page }) => {
  await mitEinladung(page, { abgesagt: true, methode: 'CANCEL' })
  await anmelden(page)
  await ersteMailOeffnen(page)
  await expect(page.getByText('Abgesagt')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Zusagen' })).toHaveCount(0)
})

test('Was geantwortet wurde, steht danach da', async ({ page }) => {
  /* ⚠️ Sonst sieht die Karte beim zweiten Öffnen aus wie beim ersten, und man
     antwortet zweimal. */
  await mitEinladung(page)
  await page.route(/\/api\/termine\/\d+\/antwort$/, async (route) => {
    const wunsch = JSON.parse(route.request().postData() ?? '{}')
    await route.fulfill({
      json: { ...EINLADUNG, antwort: wunsch.antwort, antwort_am: '2026-09-03T09:12:00+02:00' },
    })
  })
  await anmelden(page)
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Mit Vorbehalt' }).click()
  await expect(page.getByText(/mit Vorbehalt zugesagt/)).toBeVisible()
})

test('Eine gewöhnliche Mail bekommt keine Karte', async ({ page }) => {
  await page.route(/\/api\/termine\/\d+$/, (route) => route.fulfill({ json: null }))
  await anmelden(page)
  await ersteMailOeffnen(page)
  await expect(page.getByText(/Einen Kalender hat es nicht/)).toHaveCount(0)
})
