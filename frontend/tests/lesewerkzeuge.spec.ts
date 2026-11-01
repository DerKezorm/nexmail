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

/** Wie `vorspielen`, dazu der KI-Dienst und seine Knöpfe im Editor. */
async function vorspielenMitKi(page: Page, fremdePost: boolean) {
  await page.route('**/api/auth/ich', async (route) => {
    const echt = await route.fetch()
    const ich = await echt.json()
    await route.fulfill({
      response: echt,
      json: { ...ich, ki_aktiv: true, ki_fremde_post: fremdePost },
    })
  })
  await anmelden(page)
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

async function kiWahl(page: Page, eintrag: string) {
  await page.getByRole('button', { name: 'KI-Werkzeuge' }).click()
  await page.getByRole('menuitem', { name: eintrag }).click()
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
  await expect(page.getByRole('button', { name: 'KI-Werkzeuge' })).toHaveCount(0)
})

test('Eine Zusammenfassung steht als Text da, nie als Link', async ({ page }) => {
  await vorspielen(page, null, true)
  const boese = 'Bitte <a href="https://evil.example">hier</a> klicken.'
  await page.route(/\/api\/nachrichten\/\d+\/zusammenfassung$/, (route) =>
    route.fulfill({ json: { text: boese, gekuerzt: true } }),
  )
  await ersteMailOeffnen(page)

  await kiWahl(page, 'Zusammenfassen')

  const kasten = page.getByRole('region', { name: 'KI-Zusammenfassung' })
  await expect(kasten).toContainText(boese)
  await expect(kasten.locator('a')).toHaveCount(0)
  await expect(kasten).toContainText('nur ihr Anfang')
  await expect(kasten).toContainText('kann sich irren')
  await jederKnopfHatEinenNamen(page)

  await kasten.getByRole('button', { name: 'Schließen' }).click()
  await expect(kasten).toHaveCount(0)
})

test('Ein Fehlschlag steht im Kasten, die Mail bleibt lesbar', async ({ page }) => {
  await vorspielen(page, null, true)
  await page.route(/\/api\/nachrichten\/\d+\/zusammenfassung$/, (route) =>
    route.fulfill({ status: 400, json: { detail: 'ki_nicht_erreichbar' } }),
  )
  await ersteMailOeffnen(page)

  await kiWahl(page, 'Zusammenfassen')

  const kasten = page.getByRole('region', { name: 'KI-Zusammenfassung' })
  await expect(kasten.getByRole('alert')).toBeVisible()
  await expect(page.locator('article iframe')).toBeVisible()
})

test('Beim Wechsel der Mail fällt die ganze Karte weg', async ({ page }) => {
  await vorspielen(page, null, true)
  await page.route(/\/api\/nachrichten\/\d+\/zusammenfassung$/, (route) =>
    route.fulfill({ json: { text: 'Das gehört zur ersten Mail.', gekuerzt: false } }),
  )
  await ersteMailOeffnen(page)
  await kiWahl(page, 'Zusammenfassen')
  await expect(page.getByText('Das gehört zur ersten Mail.')).toBeVisible()

  await page.locator('button[draggable="true"]').nth(1).click()

  await expect(page.getByText('Das gehört zur ersten Mail.')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'KI-Zusammenfassung' })).toHaveCount(0)
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

test('Eine Übersetzung steht als Text da und sagt, wenn sie abreißt', async ({ page }) => {
  await vorspielen(page, null, true)
  const boese = 'Please <a href="https://evil.example">click</a>.'
  let sprache = ''
  await page.route(/\/api\/nachrichten\/\d+\/uebersetzung$/, async (route) => {
    sprache = route.request().postDataJSON().sprache
    await route.fulfill({ json: { text: boese, gekuerzt: true } })
  })
  await ersteMailOeffnen(page)

  await kiWahl(page, 'Übersetzen')

  const kasten = page.getByRole('region', { name: 'KI-Übersetzung' })
  await expect(kasten).toContainText(boese)
  await expect(kasten.locator('a')).toHaveCount(0)
  await expect(kasten).toContainText('nur ihr Anfang')
  expect(sprache).toBe('de')
})

test('Eine Frage geht mit ihrem Wortlaut hinaus, und die nächste auch', async ({ page }) => {
  await vorspielen(page, null, true)
  const fragen: string[] = []
  await page.route(/\/api\/nachrichten\/\d+\/frage$/, async (route) => {
    fragen.push(route.request().postDataJSON().frage)
    await route.fulfill({ json: { text: `Antwort ${fragen.length}`, gekuerzt: false } })
  })
  await ersteMailOeffnen(page)

  await kiWahl(page, 'Frage zur Mail stellen')
  const kasten = page.getByRole('region', { name: 'Frage zur Mail' })
  expect(fragen).toEqual([])

  const feld = kasten.getByRole('textbox')
  await expect(feld).toBeFocused()
  await expect(kasten.getByRole('button', { name: 'Frage stellen' })).toBeDisabled()
  await feld.fill('   ')
  await feld.press('Enter')
  await page.waitForTimeout(200)
  expect(fragen).toEqual([])
  await feld.fill('Bis wann?')
  await feld.press('Enter')
  await expect(kasten).toContainText('Antwort 1')
  await expect(feld).toHaveValue('Bis wann?')

  await feld.fill('Wie viel?')
  await kasten.getByRole('button', { name: 'Frage stellen' }).click()
  await expect(kasten).toContainText('Antwort 2')
  await expect(kasten).not.toContainText('Antwort 1')
  expect(fragen).toEqual(['Bis wann?', 'Wie viel?'])
})

test('Beim Wechsel der Mail fällt die offene Frage samt Text weg', async ({ page }) => {
  await vorspielen(page, null, true)
  await ersteMailOeffnen(page)
  await kiWahl(page, 'Frage zur Mail stellen')
  await page.getByRole('region', { name: 'Frage zur Mail' }).getByRole('textbox').fill('Bis wann?')

  await page.locator('button[draggable="true"]').nth(1).click()

  await expect(page.getByRole('region', { name: 'Frage zur Mail' })).toHaveCount(0)
})

test('Ohne Freigabe bietet das Antworten keinen Entwurf an', async ({ page }) => {
  await vorspielenMitKi(page, false)
  await ersteMailOeffnen(page)
  await page.getByRole('button', { name: 'Antworten', exact: true }).click()
  const fenster = page.getByRole('dialog').first()
  await expect(fenster.locator('[contenteditable="true"]')).toBeVisible()

  await fenster.getByRole('button', { name: 'KI', exact: true }).click()

  await expect(page.getByText('Antwort entwerfen')).toHaveCount(0)
})

test('Escape schließt nur das KI-Fenster, nicht die Antwort darunter', async ({ page }) => {
  await vorspielenMitKi(page, true)
  await ersteMailOeffnen(page)
  await page.getByRole('button', { name: 'Antworten', exact: true }).click()
  const fenster = page.getByRole('dialog').first()
  await expect(fenster.locator('blockquote').first()).toBeVisible()
  await fenster.getByRole('button', { name: 'KI', exact: true }).click()
  const hinweis = page.getByLabel('Was soll drinstehen? (optional)')
  await expect(hinweis).toBeVisible()

  await page.keyboard.press('Escape')

  await expect(hinweis).toHaveCount(0)
  await expect(fenster.locator('[contenteditable="true"]')).toBeVisible()
  await page.getByRole('button', { name: 'Verwerfen' }).click()
})

test('Beim Weiterleiten gibt es keinen Antwortentwurf', async ({ page }) => {
  await vorspielenMitKi(page, true)
  await ersteMailOeffnen(page)
  await page.getByRole('button', { name: 'Weiterleiten', exact: true }).click()
  const fenster = page.getByRole('dialog').first()
  await expect(fenster.locator('[contenteditable="true"]')).toBeVisible()

  await fenster.getByRole('button', { name: 'KI', exact: true }).click()

  await expect(page.getByText('Antwort entwerfen')).toHaveCount(0)
})

test('Ein eigener Text bleibt sichtbar, bis der Entwurf ihn ersetzt', async ({ page }) => {
  await vorspielenMitKi(page, true)
  await page.route(/\/api\/nachrichten\/\d+\/antwortentwurf$/, (route) =>
    route.fulfill({ json: { text: 'Neuer Vorschlag.', gekuerzt: false } }),
  )
  await ersteMailOeffnen(page)
  await page.getByRole('button', { name: 'Antworten', exact: true }).click()
  const fenster = page.getByRole('dialog').first()
  const text = fenster.locator('[contenteditable="true"]')
  await expect(text.locator('blockquote').first()).toBeVisible()
  await text.click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('Mein eigener erster Satz.')
  await expect(text).toContainText('Mein eigener erster Satz.')

  await fenster.getByRole('button', { name: 'KI', exact: true }).click()
  await page.getByRole('button', { name: /Antwort entwerfen/ }).click()
  await page.getByRole('button', { name: 'Bearbeiten', exact: true }).click()

  const vorschlag = page.getByRole('dialog').filter({ hasText: 'Vorschlag für deine Antwort' })
  await expect(vorschlag).toContainText('Mein eigener erster Satz.')
  await expect(vorschlag).toContainText('Neuer Vorschlag.')

  await vorschlag.getByRole('button', { name: 'Übernehmen' }).click()
  await expect(text).toContainText('Neuer Vorschlag.')
  await expect(text).not.toContainText('Mein eigener')
  await expect(text.locator('blockquote').first()).toBeVisible()
  await page.getByRole('button', { name: 'Verwerfen' }).click()
})

test('Ein Entwurf steht erst nach dem Übernehmen im Text, über Zitat und Signatur', async ({ page }) => {
  await vorspielenMitKi(page, true)
  const auftraege: Array<{ hinweis: string; sprache: string }> = []
  const boese = 'Hallo,\nbitte <a href="https://evil.example">hier</a> klicken.'
  await page.route(/\/api\/nachrichten\/\d+\/antwortentwurf$/, async (route) => {
    auftraege.push(route.request().postDataJSON())
    await route.fulfill({ json: { text: boese, gekuerzt: true } })
  })
  await ersteMailOeffnen(page)
  await page.getByRole('button', { name: 'Antworten', exact: true }).click()
  const fenster = page.getByRole('dialog').first()
  const text = fenster.locator('[contenteditable="true"]')
  await expect(text).toBeVisible()
  await expect(text.locator('blockquote').first()).toBeVisible()

  await fenster.getByRole('button', { name: 'KI', exact: true }).click()
  /* Bei leerer Antwort ist es die einzige Wahl, und das Feld steht schon da. */
  await page.getByLabel('Was soll drinstehen? (optional)').fill('Zusagen')
  await page.getByRole('button', { name: 'Bearbeiten', exact: true }).click()

  const vorschlag = page.getByRole('dialog').filter({ hasText: 'Vorschlag für deine Antwort' })
  await expect(vorschlag).toContainText('bitte <a href')
  await expect(vorschlag).toContainText('nur ihr Anfang')
  await expect(text).not.toContainText('bitte')
  expect(auftraege).toEqual([{ hinweis: 'Zusagen', sprache: 'de' }])

  await vorschlag.getByRole('button', { name: 'Übernehmen' }).click()

  await expect(text).toContainText('bitte <a href')
  await expect(text.locator('a[href*="evil"]')).toHaveCount(0)
  await expect(text.locator('p').first()).toHaveText('Hallo,')
  await expect(text.locator('blockquote').first()).toBeVisible()
  await page.getByRole('button', { name: 'Verwerfen' }).click()
})

test('Strg K findet Handgriffe und Ordner, Enter führt aus', async ({ page }) => {
  await vorspielen(page, null, false)
  await ersteMailOeffnen(page)

  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Befehle' })
  await expect(palette).toBeVisible()
  const feld = palette.getByRole('combobox')
  await expect(feld).toBeFocused()

  await expect(palette.getByRole('option', { name: 'Neue Nachricht' })).toBeVisible()
  await expect(palette.getByRole('option', { name: 'Antworten', exact: true })).toBeVisible()
  await expect(palette.getByRole('option', { name: /Posteingang/ })).toHaveCount(0)
  await expect(palette.getByRole('option', { name: /›/ })).toHaveCount(0)

  await feld.fill('kalender')
  await expect(palette.getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Enter')
  await expect(palette).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Kalender', exact: true })).toHaveAttribute('aria-current', 'page')
})

test('In der Palette bewegen die Pfeile die Wahl, der Fokus bleibt im Feld', async ({ page }) => {
  await vorspielen(page, null, false)
  await ersteMailOeffnen(page)
  const liste = page.locator('button[draggable="true"]')
  const vorher = await liste.count()

  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Befehle' })
  const feld = palette.getByRole('combobox')
  const zeilen = palette.getByRole('option')
  await expect(zeilen.first()).toHaveAttribute('aria-selected', 'true')

  await page.keyboard.press('ArrowDown')
  await expect(zeilen.nth(1)).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowUp')
  await page.keyboard.press('ArrowUp')
  await expect(zeilen.last()).toHaveAttribute('aria-selected', 'true')
  await expect(feld).toBeFocused()

  /* ⚠️ Ein `e` im Feld ist ein Buchstabe, nicht „Archivieren". */
  await page.keyboard.type('e')
  await expect(feld).toHaveValue('e')
  await page.keyboard.press('Escape')
  await expect(palette).toHaveCount(0)
  await expect(liste).toHaveCount(vorher)
})

test('Strg K schließt die Palette wieder und öffnet nichts über einem Fenster', async ({ page }) => {
  await vorspielen(page, null, false)
  await ersteMailOeffnen(page)
  const palette = page.getByRole('dialog', { name: 'Befehle' })

  await page.keyboard.press('Control+k')
  await expect(palette).toBeVisible()
  await page.keyboard.press('Control+k')
  await expect(palette).toHaveCount(0)

  await page.getByRole('button', { name: 'Neue Nachricht' }).first().click()
  await expect(page.getByRole('dialog', { name: 'Neue Nachricht' })).toBeVisible()
  await page.keyboard.press('Control+k')
  await expect(palette).toHaveCount(0)
  await page.getByRole('button', { name: 'Verwerfen' }).click()
})

test('Ein Ordner aus der Palette öffnet sich, ein Nichts sagt es', async ({ page }) => {
  await vorspielen(page, null, false)
  await ersteMailOeffnen(page)

  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Befehle' })
  await palette.getByRole('combobox').fill('zzzqqq')
  await expect(palette.getByRole('status')).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(palette).toBeVisible()

  await palette.getByRole('combobox').fill('markierte')
  await palette.getByRole('option', { name: /Markierte/ }).first().click()
  await expect(palette).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Markierte' })).toBeVisible()
})
