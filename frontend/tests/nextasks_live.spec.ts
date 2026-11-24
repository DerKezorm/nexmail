/* nextasks ausbauen (MAIL-2): Listen und Aufgaben live in der Aufgabenansicht,
 * nur Geändertes beim Speichern, neue Aufgabe mit Zuständigen, Listenauswahl
 * und eigene Liste abschalten in den Einstellungen.
 *
 * ⚠️ **nextasks wird vorgespielt**, an nexmails eigenen Adressen unter
 * `/api/nextasks` und `/api/aufgabenziele`. Was der Server mit nextasks tut,
 * prüft `test_nextasks_ansicht.py`.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/nextasks_live.spec.ts --project=desktop --reporter=line
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, bereich, keineRohenSchluessel, zuEinstellungen, zurAnsicht } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die nextasks-Ansichten werden breit geprüft.')
})

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

const BEREICHE = [
  {
    id: 's1', name: 'Familie', symbol: 'house', ausgeblendet: false, beschreibbar: true, geteilt: true,
    listen: [
      { id: 'l1', name: 'Einkauf', farbe: 'green', symbol: 'cart', beschreibbar: true, offen: 1, gewaehlt: true,
        abschnitte: [{ id: 'x1', name: 'Markt' }] },
      { id: 'l2', name: 'Haushalt', farbe: '#aa3377', symbol: 'home', beschreibbar: true, offen: 0, gewaehlt: true,
        abschnitte: [] },
    ],
  },
]

const BROT = {
  id: 't1', liste_id: 'l1', liste_name: 'Einkauf', bereich_id: 's1', bereich_name: 'Familie',
  abschnitt_id: null, abschnitt_name: '', eltern_id: null, titel: 'Brot', notiz: '', notiz_text: '', url: null,
  faellig_tag: '2026-11-25', faellig_zeit: null, wiederholung: null, markiert: false, prioritaet: 2,
  schlagworte: [], zustaendige: [{ id: 12, name: 'Mara' }], erledigt: false, erledigt_am: null, papierkorb: false,
  teilaufgaben: { offen: 0, gesamt: 0 }, link: 'https://tasks.example.com/lists/l1?task=t1', beschreibbar: true,
  mail: { aufgabe_id: 5, nachricht_id: 812, konto_id: 'k1', betreff: 'Einkauf', von_name: 'Robin',
          von_adresse: 'robin@example.com', verwaist: false },
}

const STAND = {
  standard: 'v3:l1',
  verbindungen: [{ id: 'v3', art: 'nextasks', name: '', fehler: '', angelegt: '2026-11-07T10:00:00Z',
                   zuletzt_abgeglichen: null }],
  eigene: true,
  eigene_offen: 2,
}

/** Spielt nextasks und die Aufgabenziele vor; gibt zurück, was hinausging. */
async function vorspielen(page: Page) {
  const gesendet: Array<{ methode: string; pfad: string; rumpf: unknown }> = []
  await page.route('**/api/nextasks/**', async (route) => {
    const anfrage = route.request()
    const url = new URL(anfrage.url())
    const pfad = url.pathname.replace(/^.*\/api\/nextasks/, '')
    const methode = anfrage.method()
    if (methode !== 'GET') gesendet.push({ methode, pfad, rumpf: anfrage.postDataJSON() })
    if (pfad === '/lage') {
      return route.fulfill({ json: { verbunden: true, verbindung_id: 'v3', name: '', mitglieder: true, fehler: '',
                                     zeitzone: 'Europe/Berlin', weitere: [] } })
    }
    if (pfad === '/listen') return route.fulfill({ json: { bereiche: BEREICHE } })
    if (pfad.startsWith('/listen/')) return route.fulfill({ status: 204, body: '' })
    if (pfad === '/aufgaben' && methode === 'GET') return route.fulfill({ json: { aufgaben: [BROT], weiter: null } })
    if (pfad === '/aufgaben' && methode === 'POST') {
      return route.fulfill({ status: 201, json: { ...BROT, id: 't9', titel: 'Milch', mail: null } })
    }
    if (pfad === '/aufgaben/t1') {
      if (methode === 'DELETE') return route.fulfill({ status: 204, body: '' })
      return route.fulfill({ json: { ...BROT, teilaufgaben_liste: [] } })
    }
    if (pfad === '/bereiche/s1/mitglieder') {
      return route.fulfill({ json: [{ id: 12, name: 'Mara' }, { id: 14, name: 'Robin' }] })
    }
    return route.fulfill({ status: 404, json: { detail: 'nicht_gefunden' } })
  })
  await page.route('**/api/aufgaben', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/aufgaben/abgleichen', (route) => route.fulfill({ status: 204, body: '' }))
  await page.route('**/api/aufgabenziele', (route) => route.fulfill({ json: STAND }))
  return gesendet
}

test('Listen und Aufgaben aus nextasks, Abhaken und Ändern schicken nur Geändertes (AC-1 bis AC-4, AC-8)', async ({ page }) => {
  const gesendet = await vorspielen(page)
  await anmelden(page)
  await zurAnsicht(page, 'Aufgaben')

  const leiste = page.getByRole('navigation', { name: /Filter|Aufgaben/ }).first()
  await expect(page.getByRole('button', { name: /^Einkauf/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Haushalt/ })).toBeVisible()
  await expect(leiste.getByRole('button', { name: 'Mir zugewiesen' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Neue Aufgabe' })).toBeVisible()

  const zeile = page.locator('li[data-nextasks="t1"]')
  await expect(zeile.getByRole('button', { name: 'Brot' })).toBeVisible()
  await expect(zeile.getByText('Mara')).toBeVisible()
  // Die Aufgabe kam aus einer Mail: Zeichen und Absender (AC-8).
  await expect(zeile.getByRole('button', { name: /Robin/ })).toBeVisible()

  await page.screenshot({ path: 'test-results/mail2-aufgaben.png' })
  await zeile.getByRole('checkbox', { name: 'Als erledigt abhaken' }).click()
  await expect.poll(() => gesendet.filter((g) => g.methode === 'PATCH').length).toBe(1)
  expect(gesendet[0]).toEqual({ methode: 'PATCH', pfad: '/aufgaben/t1', rumpf: { erledigt: true } })

  await zeile.getByRole('button', { name: 'Brot' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster.getByLabel('Titel')).toHaveValue('Brot')
  await page.screenshot({ path: 'test-results/mail2-fenster.png' })
  await fenster.getByLabel('Titel').fill('Brötchen')
  await fenster.getByRole('button', { name: 'Speichern' }).click()
  await expect.poll(() => gesendet.filter((g) => g.methode === 'PATCH').length).toBe(2)
  expect(gesendet.filter((g) => g.methode === 'PATCH')[1].rumpf).toEqual({ titel: 'Brötchen' })
  await keineRohenSchluessel(page)
})

test('Neue Aufgabe ohne Mail, mit Zuständigen, in der gewählten Liste (AC-6)', async ({ page }) => {
  const gesendet = await vorspielen(page)
  await anmelden(page)
  await zurAnsicht(page, 'Aufgaben')

  await page.getByRole('button', { name: /^Haushalt/ }).click()
  await page.getByRole('button', { name: 'Neue Aufgabe' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster.getByRole('combobox', { name: /Liste/ })).toHaveValue('l2|')
  await fenster.getByLabel('Titel').fill('Milch')
  await fenster.getByText('Mara', { exact: true }).click()
  await fenster.getByRole('button', { name: 'Anlegen' }).click()

  await expect.poll(() => gesendet.filter((g) => g.methode === 'POST').length).toBe(1)
  expect(gesendet.find((g) => g.methode === 'POST')!.rumpf).toMatchObject({
    liste_id: 'l2', titel: 'Milch', zustaendige: [12], abschnitt_id: null,
  })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('Listenauswahl in der Karte und eigene Liste abschalten mit Umzug (AC-9, AC-16, AC-17)', async ({ page }) => {
  const gesendet = await vorspielen(page)
  const eigene: unknown[] = []
  await page.route('**/api/aufgabenziele/listen', (route) =>
    route.fulfill({ json: [{ verbindung_id: 'v3', art: 'nextasks', name: '', fehler: '',
                             listen: [{ ziel: 'v3:l1', name: 'Familie › Einkauf' }] }] }),
  )
  await page.route('**/api/aufgabenziele/v3/nextasks', (route) =>
    route.fulfill({ json: { url: 'https://tasks.example.com' } }),
  )
  await page.route('**/api/aufgabenziele/eigene', async (route) => {
    eigene.push(route.request().postDataJSON())
    await route.fulfill({ json: { stand: { ...STAND, eigene: false, eigene_offen: 0 }, umgezogen: 2, fehlgeschlagen: 0 } })
  })
  await anmelden(page)
  await zuEinstellungen(page)
  await bereich(page, 'Verbindungen')

  const karte = page.getByRole('region', { name: 'nextasks' })
  await karte.getByRole('button', { name: /nextasks/ }).first().click()
  await expect(karte.getByText('Diese Listen nimmt nexmail')).toBeVisible()
  await expect(karte.getByText('Weiteres nextasks verbinden')).toHaveCount(0)
  await karte.getByText('Einkauf', { exact: true }).click()
  await expect.poll(() => gesendet.filter((g) => g.pfad === '/listen/l1').length).toBe(1)
  expect(gesendet.find((g) => g.pfad === '/listen/l1')!.rumpf).toEqual({ gewaehlt: false })

  await page.getByText('Eigene Aufgabenliste in nexmail', { exact: true }).click()
  const frage = page.getByRole('dialog')
  await expect(frage.getByRole('checkbox', { name: /2 offenen Aufgaben nach nextasks › Familie › Einkauf/ })).toBeChecked()
  await frage.getByRole('button', { name: 'Abschalten' }).click()
  await expect.poll(() => eigene.length).toBe(1)
  expect(eigene[0]).toEqual({ an: false, umziehen: true })
  await expect(page.getByText('2 Aufgaben verschoben.')).toBeVisible()
  await keineRohenSchluessel(page)
})

test('Ohne nextasks bleibt die Aufgabenansicht wie bisher (AC-13)', async ({ page }) => {
  await page.route('**/api/nextasks/lage', (route) =>
    route.fulfill({ json: { verbunden: false, verbindung_id: '', name: '', mitglieder: false, fehler: '',
                            zeitzone: '', weitere: [] } }),
  )
  await anmelden(page)
  await zurAnsicht(page, 'Aufgaben')
  await expect(page.getByRole('heading', { name: 'Offen' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Neue Aufgabe' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Mir zugewiesen' })).toHaveCount(0)
})
