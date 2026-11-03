/* Todo-Apps: Reiter, Fenster beim Umwandeln, Liste, Link zurück zur Mail.
 *
 * ⚠️ **Todoist wird vorgespielt**, an nexmails eigenen Adressen. Kein Lauf soll
 * ein echtes Todoist anfassen oder in `data-dev` Aufgaben hinterlassen. Was
 * der Server mit Todoist tut, prüft `test_todoist.py`; hier geht es darum, was
 * der Mensch sieht und was die Oberfläche dabei schickt.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/todoapps.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import type { Page, Request } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keineRohenSchluessel, postfach, zuEinstellungen } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Todo-Apps werden breit geprüft.')
})

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

const VERBINDUNG = {
  id: 'v1',
  art: 'todoist',
  name: '',
  fehler: '',
  angelegt: '2026-11-02T10:00:00Z',
  zuletzt_abgeglichen: null,
}
const LISTEN = [
  {
    verbindung_id: 'v1',
    art: 'todoist',
    name: '',
    fehler: '',
    listen: [
      { ziel: 'v1:p-eingang', name: 'Inbox' },
      { ziel: 'v1:p-arbeit', name: 'Arbeit' },
    ],
  },
]

function zeile(mehr: Record<string, unknown> = {}) {
  return {
    id: 901,
    nachricht_id: null,
    konto_id: '',
    betreff: 'Angebot schicken',
    von_name: 'Wer Auch Immer',
    von_adresse: 'wer@example.com',
    mail_datum: null,
    erledigt: null,
    faellig: '2026-11-05T00:00:00Z',
    verwaist: false,
    fern_art: 'todoist',
    fern_url: 'https://app.todoist.com/app/task/t1',
    fern_liste: 'Todoist › Arbeit',
    fern_geloescht: false,
    fern_verbunden: true,
    ...mehr,
  }
}

interface Spiel {
  angelegt: Array<Record<string, unknown>>
  einfach: number
}

async function vorspielen(
  page: Page,
  { verbunden = true, schonDa = false }: { verbunden?: boolean; schonDa?: boolean } = {},
): Promise<Spiel> {
  const spiel: Spiel = { angelegt: [], einfach: 0 }
  await page.route('**/api/aufgabenziele', (route) =>
    route.fulfill({
      json: { standard: verbunden ? 'v1:p-arbeit' : '', verbindungen: verbunden ? [VERBINDUNG] : [] },
    }),
  )
  await page.route('**/api/aufgabenziele/listen', (route) =>
    route.fulfill({ json: verbunden ? LISTEN : [] }),
  )
  await page.route('**/api/aufgaben/mit-ziel', async (route) => {
    const rumpf = route.request().postDataJSON() as Record<string, unknown>
    spiel.angelegt.push(rumpf)
    await route.fulfill({ json: { aufgabe: zeile({ betreff: rumpf.titel }), neu: !schonDa } })
  })
  await page.route(/\/api\/aufgaben$/, async (route) => {
    if (route.request().method() === 'POST') {
      spiel.einfach += 1
      await route.fulfill({ status: 201, json: zeile({ fern_art: '', fern_url: '', fern_liste: '' }) })
      return
    }
    await route.fallback()
  })
  await anmelden(page)
  return spiel
}

async function mailMenue(page: Page) {
  const baum = postfach(page)
  await expect.poll(() => baum.getByRole('button').count(), { timeout: 15000 }).toBeGreaterThan(0)
  await baum.getByRole('button', { name: 'Posteingang' }).first().click()
  const erste = page.locator('button[draggable="true"]').first()
  await expect(erste).toBeVisible()
  await erste.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Zu Aufgabe machen' }).click()
}

test('Ohne verbundene App bleibt es ein Klick ohne Fenster', async ({ page }) => {
  const spiel = await vorspielen(page, { verbunden: false })
  await mailMenue(page)
  await expect.poll(() => spiel.einfach).toBe(1)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(spiel.angelegt).toEqual([])
})

test('Mit verbundener App: Standardliste vorbelegt, Enter legt an', async ({ page }) => {
  const spiel = await vorspielen(page)
  await mailMenue(page)

  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()
  const titel = fenster.getByLabel('Titel')
  await expect(titel).toBeFocused()
  const betreff = await titel.inputValue()
  expect(betreff.length).toBeGreaterThan(0)
  await expect(fenster.getByLabel('Liste')).toHaveValue('v1:p-arbeit')
  await jederKnopfHatEinenNamen(page)
  await keineRohenSchluessel(page)
  await page.screenshot({ path: 'test-results/todoapps-fenster.png' })

  await titel.press('Enter')
  await expect(fenster).toHaveCount(0)
  expect(spiel.angelegt).toHaveLength(1)
  const rumpf = spiel.angelegt[0]
  expect(rumpf.ziel).toBe('v1:p-arbeit')
  expect(rumpf.titel).toBe(betreff)
  expect(rumpf.faellig).toBeNull()
  expect(rumpf.liste_name).toBe('Todoist › Arbeit')
  expect(String(rumpf.adresse)).toMatch(/^http:\/\/(localhost|127\.0\.0\.1):5175/)
})

test('Die Schnellwahl setzt das Datum, die eigene Liste ist wählbar', async ({ page }) => {
  const spiel = await vorspielen(page)
  await mailMenue(page)
  const fenster = page.getByRole('dialog')
  await fenster.getByRole('button', { name: 'Morgen' }).click()
  await expect(fenster.getByRole('button', { name: 'Morgen' })).toHaveAttribute('aria-pressed', 'true')
  await fenster.getByLabel('Liste').selectOption('')
  await fenster.getByRole('button', { name: 'Anlegen' }).click()
  await expect(fenster).toHaveCount(0)

  const morgen = new Date()
  morgen.setDate(morgen.getDate() + 1)
  const erwartet = `${morgen.getFullYear()}-${String(morgen.getMonth() + 1).padStart(2, '0')}-${String(morgen.getDate()).padStart(2, '0')}`
  expect(spiel.angelegt[0].faellig).toBe(erwartet)
  expect(spiel.angelegt[0].ziel).toBe('')
})

test('Gibt es die Aufgabe schon, sagt das Fenster wo, mit Link', async ({ page }) => {
  await vorspielen(page, { schonDa: true })
  await mailMenue(page)
  await page.getByRole('dialog').getByRole('button', { name: 'Anlegen' }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster.getByText('Gibt es schon')).toBeVisible()
  await expect(fenster.getByRole('link', { name: 'In der Todo-App öffnen' })).toHaveAttribute(
    'href',
    'https://app.todoist.com/app/task/t1',
  )
  await page.screenshot({ path: 'test-results/todoapps-schon-da.png' })
})

test('Die Liste zeigt Todoist-Aufgaben mit Link und ohne Datumsfeld', async ({ page }) => {
  const abgleiche: Request[] = []
  page.on('request', (r) => {
    if (r.url().endsWith('/api/aufgaben/abgleichen')) abgleiche.push(r)
  })
  await page.route(/\/api\/aufgaben$/, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({
          json: [
            zeile(),
            zeile({ id: 902, fern_art: '', fern_url: '', fern_liste: '', betreff: 'Selbst', faellig: null }),
            zeile({ id: 903, betreff: 'Dort geloescht', fern_geloescht: true }),
          ],
        })
      : route.fallback(),
  )
  await page.route('**/api/aufgaben/abgleichen', (route) => route.fulfill({ status: 204 }))
  await anmelden(page)
  await page.getByRole('button', { name: 'Aufgaben' }).first().click()

  const app = page.locator('li').filter({ hasText: 'Angebot schicken' })
  await expect(app.getByText('Todoist › Arbeit')).toBeVisible()
  await expect(app.getByRole('link', { name: 'In der Todo-App öffnen' })).toBeVisible()
  await expect(app.getByLabel('Fällig am')).toHaveCount(0)
  await expect(app.getByRole('button', { name: /in der Todo-App bleibt sie/ })).toBeVisible()

  const weg = page.locator('li').filter({ hasText: 'Dort geloescht' })
  await expect(weg.getByText('In der Todo-App gelöscht')).toBeVisible()
  await expect(weg.getByRole('link')).toHaveCount(0)

  const eigene = page.locator('li').filter({ hasText: 'Selbst' })
  await expect(eigene.getByLabel('Fällig am')).toBeVisible()
  await expect.poll(() => abgleiche.length).toBeGreaterThan(0)
  await keineRohenSchluessel(page)
  await page.screenshot({ path: 'test-results/todoapps-liste.png' })
})

test('Der Reiter Aufgaben verbindet Todoist und nennt einen abgelehnten Token', async ({ page }) => {
  const gesendet: Array<Record<string, unknown>> = []
  let verbunden = false
  await page.route('**/api/aufgabenziele', async (route) => {
    if (route.request().method() === 'POST') {
      gesendet.push(route.request().postDataJSON())
      verbunden = true
      await route.fulfill({ status: 201, json: VERBINDUNG })
      return
    }
    await route.fulfill({
      json: {
        standard: '',
        verbindungen: verbunden ? [{ ...VERBINDUNG, fehler: 'todoist_zugang_ungueltig' }] : [],
      },
    })
  })
  await page.route('**/api/aufgabenziele/listen', (route) => route.fulfill({ json: LISTEN }))
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Aufgaben' }).click()

  const token = page.getByLabel('API-Token')
  await expect(token).toHaveAttribute('type', 'password')
  await token.fill('nur-ein-probetoken')
  // Todoist steht über dem Webhook; beide Formulare haben „Verbinden“.
  await page.getByRole('button', { name: 'Verbinden' }).first().click()
  await expect(page.getByText('Todoist nimmt den Token nicht mehr an', { exact: false })).toBeVisible()
  expect(gesendet[0]).toMatchObject({ art: 'todoist', zugang: 'nur-ein-probetoken' })
  // Der Token steht nach dem Verbinden nirgends mehr auf der Seite.
  await expect(token).toHaveValue('')
  await expect(page.getByLabel('Standardliste')).toBeVisible()
  await keineRohenSchluessel(page)
  await page.screenshot({ path: 'test-results/todoapps-reiter.png', fullPage: true })
})

const WEBHOOK = {
  id: 'v2',
  art: 'webhook',
  name: 'Praxis',
  fehler: '',
  angelegt: '2026-11-03T10:00:00Z',
  zuletzt_abgeglichen: null,
}

test('Ein Webhook wird verbunden, sein Geheimnis steht genau einmal da', async ({ page }) => {
  const gesendet: Array<Record<string, unknown>> = []
  let verbunden = false
  await page.route('**/api/aufgabenziele', (route) =>
    route.fulfill({ json: { standard: '', verbindungen: verbunden ? [WEBHOOK] : [] } }),
  )
  await page.route('**/api/aufgabenziele/listen', (route) =>
    route.fulfill({
      json: verbunden
        ? [{ verbindung_id: 'v2', art: 'webhook', name: 'Praxis', fehler: '', listen: [{ ziel: 'v2:webhook', name: 'praxis.example.com' }] }]
        : [],
    }),
  )
  await page.route('**/api/aufgabenziele/webhook', async (route) => {
    gesendet.push(route.request().postDataJSON())
    verbunden = true
    await route.fulfill({ status: 201, json: { verbindung: WEBHOOK, geheimnis: 'whsec_nur_ein_probegeheimnis' } })
  })
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Aufgaben' }).click()

  // Die Beschriftung trägt den Hinweis mit, deshalb nach dem Anfang.
  await page.getByRole('textbox', { name: /^Adresse/ }).fill('https://praxis.example.com/hook')
  await page.getByRole('textbox', { name: /^Name \(optional\) Zum Wiedererkennen/ }).fill('Praxis')
  await page.getByText('Nur senden', { exact: true }).click()
  await page.getByRole('button', { name: 'Verbinden' }).last().click()

  const fenster = page.getByRole('dialog')
  await expect(fenster.getByText('Webhook verbunden')).toBeVisible()
  await expect(fenster.getByRole('textbox')).toHaveValue('whsec_nur_ein_probegeheimnis')
  expect(gesendet).toEqual([
    {
      url: 'https://praxis.example.com/hook',
      name: 'Praxis',
      geheimnis: '',
      nur_senden: true,
      mit_text: false,
    },
  ])
  await jederKnopfHatEinenNamen(page)
  await keineRohenSchluessel(page)
  await page.screenshot({ path: 'test-results/todoapps-webhook-geheimnis.png' })

  await fenster.getByRole('button', { name: 'Schließen' }).last().click()
  await expect(fenster).toHaveCount(0)
  await expect(page.getByText('whsec_nur_ein_probegeheimnis')).toHaveCount(0)
  await expect(page.getByText('Webhook · Praxis').first()).toBeVisible()
  await expect(page.getByLabel('Standardliste')).toContainText('Webhook · Praxis › praxis.example.com')
})

test('Die Einstellungen eines Webhooks: Test senden nennt den Status, gesperrter Text sagt warum', async ({ page }) => {
  const geaendert: Array<Record<string, unknown>> = []
  await page.route('**/api/aufgabenziele', (route) =>
    route.fulfill({ json: { standard: '', verbindungen: [WEBHOOK] } }),
  )
  await page.route('**/api/aufgabenziele/listen', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/aufgabenziele/v2/webhook', async (route) => {
    const stand = { url: 'https://praxis.example.com/hook', nur_senden: false, mit_text: false, mailtext_erlaubt: false }
    if (route.request().method() === 'PUT') {
      const rumpf = route.request().postDataJSON() as Record<string, unknown>
      geaendert.push(rumpf)
      await route.fulfill({ json: { ...stand, ...rumpf } })
      return
    }
    await route.fulfill({ json: stand })
  })
  await page.route('**/api/aufgabenziele/v2/test', (route) =>
    route.fulfill({ status: 502, json: { detail: 'webhook_fehler', werte: { status: 401 } } }),
  )
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Aufgaben' }).click()
  await page.getByRole('button', { name: 'Einstellungen' }).last().click()

  await expect(page.getByText('nicht freigegeben', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Test senden' }).click()
  await expect(page.getByRole('alert')).toContainText('HTTP 401')

  // Ein Schalter speichert sofort, mit der gespeicherten Adresse, nicht mit
  // einer halb getippten.
  await page.getByRole('textbox', { name: /^Adresse/ }).first().fill('https://halb')
  await page.getByText('Nur senden', { exact: true }).first().click()
  await expect.poll(() => geaendert.length).toBe(1)
  expect(geaendert[0]).toEqual({ url: 'https://praxis.example.com/hook', nur_senden: true, mit_text: false })
  await keineRohenSchluessel(page)
  await page.screenshot({ path: 'test-results/todoapps-webhook-einstellungen.png', fullPage: true })
})

test('Der Link aus Todoist öffnet die Mail über ihre Message-ID', async ({ page }) => {
  const gefragt: string[] = []
  await anmelden(page)
  // Eine echte Mail aus dem Testpostfach, über die Liste des Posteingangs.
  const baum = postfach(page)
  await expect.poll(() => baum.getByRole('button').count(), { timeout: 15000 }).toBeGreaterThan(0)
  await baum.getByRole('button', { name: 'Posteingang' }).first().click()
  const erste = page.locator('button[draggable="true"]').first()
  await expect(erste).toBeVisible()
  const antwort = page.waitForResponse(/\/api\/nachrichten\/\d+$/)
  await erste.click()
  const mail = (await (await antwort).json()) as { id: number; betreff: string }

  await page.route('**/api/aufgaben/mail?**', (route) => {
    gefragt.push(new URL(route.request().url()).searchParams.get('message_id') ?? '')
    return route.fulfill({ json: { nachricht_id: mail.id } })
  })
  await page.goto('/?mail=%3Cprobe%40example.com%3E')
  await expect(page.locator('article iframe')).toBeVisible()
  // ⚠️ Im Entwicklungsmodus läuft der Effekt zweimal (StrictMode); gefragt
  // wird also mindestens einmal, und immer nach genau dieser Kennung.
  expect(gefragt.length).toBeGreaterThan(0)
  expect(new Set(gefragt)).toEqual(new Set(['<probe@example.com>']))
  // Die Mail selbst steht da, nicht die Startseite mit Ordnern.
  await expect(page.locator('article').getByText(mail.betreff, { exact: true }).first()).toBeVisible()
  await expect(postfach(page)).toHaveCount(0)
  await page.screenshot({ path: 'test-results/todoapps-link.png' })
})
