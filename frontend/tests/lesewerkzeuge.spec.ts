/* Abmelden und Zusammenfassen im Lesebereich.
 *
 * ⚠️ **Server-Antworten werden vorgespielt.** Weder soll ein Lauf eine echte
 * Liste abbestellen noch Text an einen KI-Dienst schicken. Was der Server dabei
 * tut, prüfen `test_abbestellen.py` und `test_zusammenfassung.py`; hier geht es
 * darum, dass die Rückfrage vor der Handlung steht und dass die Antwort eines
 * Modells als Text dasteht und nicht als Link.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/lesewerkzeuge.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { anmelden, jederKnopfHatEinenNamen, keineRohenSchluessel, postfach, TESTPOSTFACH } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Der Lesebereich wird breit geprüft.')
})

/* ⚠️ Die Anwendung öffnet nebenbei Mails. Endet ein Test, während eine davon
   unterwegs ist, wäre das sonst sein Fehler. */
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

type Weg = { art: string; ziel: string; stelle: string; erledigt: boolean } | null

async function vorspielen(page: Page, abbestellen: Weg, kiFremdePost = false) {
  const abmeldungen = { zahl: 0 }
  await page.route('**/api/auth/ich', async (route) => {
    const echt = await route.fetch()
    const ich = await echt.json()
    await route.fulfill({ response: echt, json: { ...ich, ki_fremde_post: kiFremdePost } })
  })
  await page.route(/\/api\/nachrichten\/\d+$/, async (route) => {
    const echt = await route.fetch()
    const mail = await echt.json()
    await route.fulfill({ response: echt, json: { ...mail, abbestellen } })
  })
  await page.route(/\/api\/nachrichten\/\d+\/abbestellen$/, async (route) => {
    abmeldungen.zahl += 1
    await route.fulfill({ json: { ...abbestellen, ziel: '', erledigt: true } })
  })
  await anmelden(page)
  return abmeldungen
}

async function ersteMailOeffnen(page: Page) {
  const baum = postfach(page)
  await expect.poll(() => baum.getByRole('button').count(), { timeout: 15000 }).toBeGreaterThan(0)
  await baum.getByRole('button', { name: 'Posteingang' }).first().click()
  const zeile = page.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible()
  await zeile.click()
  await expect(page.locator('article iframe')).toBeVisible()
}

const EINKLICK: Weg = { art: 'einklick', ziel: '', stelle: 'liste.example.org', erledigt: false }

test('Ein Klick fragt erst und schickt danach genau einmal', async ({ page }) => {
  const abmeldungen = await vorspielen(page, EINKLICK)
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Abmelden' }).click()
  const frage = page.getByRole('dialog')
  await expect(frage).toContainText('liste.example.org')
  expect(abmeldungen.zahl, 'Vor der Antwort geht nichts hinaus.').toBe(0)
  await keineRohenSchluessel(page)

  await frage.getByRole('button', { name: 'Abmelden' }).click()

  await expect(page.getByText(/Abmeldung an liste\.example\.org geschickt/)).toBeVisible()
  expect(abmeldungen.zahl).toBe(1)
  await expect(page.getByRole('button', { name: 'Abmelden' })).toHaveCount(0)
})

test('Abbrechen schickt nichts', async ({ page }) => {
  const abmeldungen = await vorspielen(page, EINKLICK)
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Abmelden' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Abbrechen' }).click()

  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(abmeldungen.zahl).toBe(0)
  await expect(page.getByRole('button', { name: 'Abmelden' })).toBeVisible()
})

test('Eine Abmeldung per Mail geht vorbelegt ins Verfassen-Fenster', async ({ page }) => {
  await vorspielen(page, {
    art: 'mail',
    ziel: 'mailto:ab@liste.example.org?subject=weg',
    stelle: 'ab@liste.example.org',
    erledigt: false,
  })
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Abmelden' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Abmelden' }).click()

  const fenster = page.getByRole('dialog', { name: 'Neue Nachricht' })
  await expect(fenster.getByText('ab@liste.example.org').first()).toBeVisible()
  await expect(fenster.getByRole('textbox', { name: 'Betreff' })).toHaveValue('weg')
})

test('Ohne Weg steht kein Knopf da', async ({ page }) => {
  await vorspielen(page, null)
  await ersteMailOeffnen(page)

  await expect(page.getByRole('button', { name: 'Abmelden' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Zusammenfassen' })).toHaveCount(0)
})

test('Eine Zusammenfassung steht als Text da, nie als Link', async ({ page }) => {
  await vorspielen(page, null, true)
  const boese = 'Bitte <a href="https://evil.example">hier</a> klicken.'
  await page.route(/\/api\/nachrichten\/\d+\/zusammenfassung$/, (route) =>
    route.fulfill({ json: { text: boese, gekuerzt: true } }),
  )
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Zusammenfassen' }).click()

  const kasten = page.getByRole('region', { name: 'KI-Zusammenfassung' })
  await expect(kasten).toContainText(boese)
  await expect(kasten.locator('a')).toHaveCount(0)
  await expect(kasten).toContainText('nur ihr Anfang')
  await expect(kasten).toContainText('kann sich irren')
  await jederKnopfHatEinenNamen(page)

  await kasten.getByRole('button', { name: 'Zusammenfassung schließen' }).click()
  await expect(kasten).toHaveCount(0)
})

test('Ein Fehlschlag steht im Kasten, die Mail bleibt lesbar', async ({ page }) => {
  await vorspielen(page, null, true)
  await page.route(/\/api\/nachrichten\/\d+\/zusammenfassung$/, (route) =>
    route.fulfill({ status: 400, json: { detail: 'ki_nicht_erreichbar' } }),
  )
  await ersteMailOeffnen(page)

  await page.getByRole('button', { name: 'Zusammenfassen' }).click()

  const kasten = page.getByRole('region', { name: 'KI-Zusammenfassung' })
  await expect(kasten.getByRole('alert')).toBeVisible()
  await expect(page.locator('article iframe')).toBeVisible()
})

test('Beim Wechsel der Mail fällt die Zusammenfassung weg', async ({ page }) => {
  await vorspielen(page, null, true)
  await page.route(/\/api\/nachrichten\/\d+\/zusammenfassung$/, (route) =>
    route.fulfill({ json: { text: 'Das gehört zur ersten Mail.', gekuerzt: false } }),
  )
  await ersteMailOeffnen(page)
  await page.getByRole('button', { name: 'Zusammenfassen' }).click()
  await expect(page.getByText('Das gehört zur ersten Mail.')).toBeVisible()

  await page.locator('button[draggable="true"]').nth(1).click()

  await expect(page.getByText('Das gehört zur ersten Mail.')).toHaveCount(0)
})

/* ⚠️ Gemessen an der Farbe, nicht am Klassennamen: Mit 10 bis 14 % Deckkraft
   stand die Liste mitten in der Meldung und ließ sich kaum lesen. */
test('Eine Absage steht auf deckendem Grund', async ({ page }) => {
  await vorspielen(page, null)
  await page.route('**/api/nachrichten/loeschen', (route) =>
    route.fulfill({ status: 400, json: { detail: 'liegt_schon_dort' } }),
  )
  await ersteMailOeffnen(page)

  await page.keyboard.press('Delete')

  const meldung = page.getByRole('alert').filter({ hasText: 'liegt' })
  await expect(meldung).toBeVisible()
  const grund = await meldung.evaluate((e) => getComputedStyle(e).backgroundColor)
  expect(grund, `Hintergrund ${grund}`).toMatch(/^rgb\(/)
})

test('Eine Mail lässt sich auf den Ordner eines anderen Postfachs ziehen', async ({ page }) => {
  /* ⚠️ Bis 0.24.7 wies die Ordnerspalte das ab, obwohl der Server es längst
     konnte. Vorgespielt: Der Test soll keine echte Mail umziehen. */
  await vorspielen(page, null)
  const gesendet: { ids: string[]; ordner_id: string }[] = []
  await page.route('**/api/nachrichten/verschieben', async (route) => {
    gesendet.push(route.request().postDataJSON())
    await route.fulfill({ json: { bewegt: 1, nicht_bewegt: 0, rueckweg: null } })
  })
  await ersteMailOeffnen(page)
  const fremde = page
    .locator('section')
    .filter({ hasNotText: TESTPOSTFACH })
    .getByRole('button', { name: 'Posteingang' })
  test.skip((await fremde.count()) === 0, 'Braucht ein zweites Postfach.')

  await page.locator('button[draggable="true"]').first().dragTo(fremde.last())

  await expect.poll(() => gesendet.length).toBe(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('Was liegenblieb, steht neben dem Rückgängig', async ({ page }) => {
  await vorspielen(page, null)
  await page.route('**/api/nachrichten/loeschen', (route) =>
    route.fulfill({
      json: {
        bewegt: 1,
        nicht_bewegt: 2,
        rueckweg: { konto_id: '', quelle_pfad: '', ziel_pfad: '', message_ids: ['<a@example.org>'], text: '', teile: [] },
      },
    }),
  )
  await ersteMailOeffnen(page)

  await page.keyboard.press('Delete')

  await expect(page.getByRole('alert').filter({ hasText: 'Nicht verschoben: 2' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Rückgängig' })).toBeVisible()
})

test('Eine Änderung beim Server kommt ohne Handlung in die Liste', async ({ page }) => {
  /* ⚠️ **Das war bis 0.24.7 nicht so.** Der Takt holte die Post in die
     Datenbank, und ein offenes Fenster erfuhr nichts davon. */
  let stand = 100
  let listenabrufe = 0
  await page.route(/\/api\/nachrichten\/ereignisse/, async (route) => {
    const seit = Number(new URL(route.request().url()).searchParams.get('seit'))
    if (seit === stand) await new Promise((fertig) => setTimeout(fertig, 200))
    await route.fulfill({ json: { stand } })
  })
  await page.route(/\/api\/nachrichten\?/, async (route) => {
    listenabrufe += 1
    await route.fallback()
  })
  await vorspielen(page, null)
  await expect(page.locator('button[draggable="true"]').first()).toBeVisible()
  await expect.poll(() => listenabrufe).toBeGreaterThan(0)

  const vorher = listenabrufe
  await page.waitForTimeout(800)
  expect(listenabrufe, 'Ohne Änderung lädt nichts neu.').toBe(vorher)

  stand = 101
  await expect.poll(() => listenabrufe, { timeout: 4000 }).toBeGreaterThan(vorher)
})
