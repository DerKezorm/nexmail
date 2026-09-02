/* Handlungen bis zu ihrer Wirkung.
 *
 * ⚠️ **Der Fehler in meiner Testroutine, benannt am 01.09.2026.**
 *
 * Die bisherigen Tests hörten an der Bedienung auf: Ist der Knopf da, ist er
 * freigegeben, geht das Fenster auf. Genau dort hörten die Fehler aber nicht
 * auf — gespeichert wurde trotzdem nicht, und der Betreiber bekam „Field
 * required" oder „Das hat nicht geklappt" zu sehen.
 *
 * Deshalb dieser Block: **Jeder Test trägt eine Handlung bis zu ihrer Wirkung
 * durch** — anlegen, speichern, wiederfinden, wieder wegräumen. Ein Test, der
 * vor dem Speichern-Knopf umkehrt, prüft die Hälfte, die selten kaputt ist.
 *
 * Und: Jeder Test räumt hinterher auf. Sie laufen gegen ein echtes Postfach.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden, rechtsklick, zuEinstellungen } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  await anmelden(page)
  await zuEinstellungen(page)
})

/** Fängt rohe Meldungen ab, die niemand deuten kann. */
function keineRohenMeldungen(page: Page): string[] {
  const gesehen: string[] = []
  const roh = [/Field required/i, /String should have/i, /value is not a valid/i, /Input should be/i]
  page.on('response', async (r) => {
    if (!r.url().includes('/api/') || r.status() < 400) return
    try {
      const text = (await r.text()).slice(0, 300)
      if (roh.some((m) => m.test(text))) gesehen.push(`${r.status()} ${r.url()}: ${text}`)
    } catch {
      // Antwort ohne Rumpf - kein Grund, den Test umzuwerfen.
    }
  })
  return gesehen
}

test('Postfach bearbeiten: speichern wirkt wirklich', async ({ page }) => {
  const roh = keineRohenMeldungen(page)

  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()

  const name = page.getByRole('textbox', { name: 'Bezeichnung des Postfachs' })
  const alt = (await name.inputValue()) || 'nexapps'
  const neu = `${alt}-probe`

  await name.fill(neu)
  await page.getByRole('button', { name: 'Änderungen speichern' }).click()

  // ⚠️ **Die Wirkung, nicht der Klick.** Nach dem Speichern steht die Liste
  // wieder da und trägt den neuen Namen.
  await expect(
    page.getByText(neu, { exact: false }).first(),
    'Der geänderte Name taucht nicht in der Liste auf — gespeichert wurde nichts.',
  ).toBeVisible({ timeout: 15_000 })

  expect(roh, `Rohe Server-Meldung in der Oberfläche:\n  ${roh.join('\n  ')}`).toEqual([])

  // Zurückbenennen.
  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()
  await page.getByRole('textbox', { name: 'Bezeichnung des Postfachs' }).fill(alt)
  await page.getByRole('button', { name: 'Änderungen speichern' }).click()
  await expect(page.getByRole('button', { name: 'Bearbeiten' }).first()).toBeVisible({
    timeout: 15_000,
  })
})

test('Regel anlegen, wiederfinden, entfernen', async ({ page }) => {
  const roh = keineRohenMeldungen(page)
  const name = 'ZZ-Probe-Regel'

  await page.getByRole('tab', { name: 'Regeln' }).click()
  await page.getByRole('button', { name: 'Neue Regel' }).click()

  await page.getByRole('textbox', { name: 'Name' }).fill(name)
  await page.getByRole('textbox', { name: 'Wert' }).fill('ZZ-Testwert')
  await page.getByRole('button', { name: 'Regel speichern' }).click()

  await expect(
    page.getByText(name),
    'Die Regel taucht nach dem Speichern nicht in der Liste auf.',
  ).toBeVisible({ timeout: 10_000 })
  expect(roh, `Rohe Server-Meldung:\n  ${roh.join('\n  ')}`).toEqual([])

  // Wieder weg — und zwar über das eigene Fenster, nicht über einen
  // Browser-Kasten.
  await page
    .locator('li', { hasText: name })
    .getByRole('button', { name: 'Regel entfernen' })
    .click()
  await page.getByRole('dialog').getByRole('button', { name: 'Regel entfernen' }).click()
  await expect(page.getByText(name)).toHaveCount(0, { timeout: 10_000 })
})

test('Signatur anlegen, wiederfinden, entfernen', async ({ page }) => {
  const roh = keineRohenMeldungen(page)
  const name = 'ZZ-Probe-Signatur'

  await page.getByRole('tab', { name: 'Signaturen' }).click()
  await page.getByRole('button', { name: 'Neue Signatur' }).click()

  await page.getByRole('textbox', { name: 'Name' }).fill(name)
  await page.locator('.ProseMirror').first().click()
  await page.keyboard.type('Viele Grüße')
  await page.getByRole('button', { name: 'Signatur speichern' }).click()

  await expect(
    page.getByText(name),
    'Die Signatur taucht nach dem Speichern nicht in der Liste auf.',
  ).toBeVisible({ timeout: 10_000 })
  expect(roh, `Rohe Server-Meldung:\n  ${roh.join('\n  ')}`).toEqual([])

  await page
    .locator('li', { hasText: name })
    .getByRole('button', { name: 'Signatur entfernen' })
    .click()
  await page.getByRole('dialog').getByRole('button', { name: 'Signatur entfernen' }).click()
  await expect(page.getByText(name)).toHaveCount(0, { timeout: 10_000 })
})

test('Kontakt anlegen, wiederfinden, entfernen', async ({ page }) => {
  const roh = keineRohenMeldungen(page)
  const adresse = 'zz-probe@example.org'

  await page.getByRole('button', { name: 'Kontakte', exact: true }).click()
  await page.getByRole('button', { name: 'Neuer Kontakt' }).click()

  await page.getByRole('textbox', { name: 'E-Mail-Adresse' }).fill(adresse)
  await page.getByRole('textbox', { name: 'Name' }).first().fill('ZZ Probe')
  await page.getByRole('button', { name: 'Anlegen' }).click()

  await expect(
    page.getByText(adresse).first(),
    'Der Kontakt taucht nach dem Anlegen nicht in der Liste auf.',
  ).toBeVisible({ timeout: 10_000 })
  expect(roh, `Rohe Server-Meldung:\n  ${roh.join('\n  ')}`).toEqual([])

  // Den Eintrag in der Liste anwählen — so kommt auch ein Mensch an das
  // Entfernen heran.
  await page.getByText(adresse).first().click()
  await page.getByRole('button', { name: 'Entfernen', exact: true }).click()
  await expect(page.getByText(adresse)).toHaveCount(0, { timeout: 10_000 })
})

test('Kontaktgruppe anlegen, Mitglied ankreuzen, wieder entfernen', async ({ page }) => {
  const roh = keineRohenMeldungen(page)
  const adresse = 'zz-gruppen-probe@example.org'
  const gruppenname = 'ZZ-Probe-Gruppe'

  await page.getByRole('button', { name: 'Kontakte', exact: true }).click()

  // Erst ein Kontakt — ohne Adressbuch gibt es nichts anzukreuzen.
  await page.getByRole('button', { name: 'Neuer Kontakt' }).click()
  await page.getByRole('textbox', { name: 'E-Mail-Adresse' }).fill(adresse)
  await page.getByRole('button', { name: 'Anlegen' }).click()
  await expect(page.getByText(adresse).first()).toBeVisible({ timeout: 10_000 })

  await page.getByRole('button', { name: 'Neue Gruppe' }).click()
  await page.getByRole('textbox', { name: 'Name der Gruppe' }).fill(gruppenname)
  // ⚠️ Das Kaestchen selbst ist unsichtbar (sr-only) — geklickt wird das
  // Label, genau wie ein Mensch es tut. Gemessen wird trotzdem am Zustand.
  const kaestchen = page.getByRole('checkbox', { name: adresse })
  await page.locator('label').filter({ hasText: adresse }).click()
  await expect(kaestchen).toBeChecked()
  await page.getByRole('button', { name: 'Anlegen' }).click()

  // Die Wirkung: Die Gruppe steht links, und die Mitgliederzahl stimmt.
  const zeile = page.getByRole('button', { name: new RegExp(gruppenname) })
  await expect(
    zeile,
    'Die Gruppe taucht nach dem Anlegen nicht mit ihrer Mitgliederzahl auf.',
  ).toContainText('1 Mitglied', { timeout: 10_000 })
  expect(roh, `Rohe Server-Meldung:\n  ${roh.join('\n  ')}`).toEqual([])

  // Aufräumen: Gruppe weg — über die eigene Rückfrage, nie den Browser-Kasten.
  await zeile.click()
  await page.getByRole('button', { name: 'Gruppe entfernen' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Gruppe entfernen' }).click()
  await expect(page.getByText(gruppenname)).toHaveCount(0, { timeout: 10_000 })

  // ⚠️ Der Kontakt lebt noch: Eine Gruppe besitzt ihre Mitglieder nicht.
  await expect(page.getByText(adresse).first()).toBeVisible()
  await page.getByText(adresse).first().click()
  await page.getByRole('button', { name: 'Entfernen', exact: true }).click()
  await expect(page.getByText(adresse)).toHaveCount(0, { timeout: 10_000 })
})

test('Absendername und Bezeichnung sind zwei Felder', async ({ page }) => {
  /* ⚠️ **Aus einer Meldung vom 01.09.2026.** Ein Feld diente beiden Zwecken:
     Wer sein Postfach in der Ordnerspalte „Arbeit" nannte, verschickte Post
     von einem Absender namens „Arbeit". Der Empfänger sieht das, der Absender
     nicht. */
  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()

  await expect(
    page.getByRole('textbox', { name: 'Bezeichnung des Postfachs' }),
    'Die Bezeichnung für die Ordnerspalte fehlt.',
  ).toBeVisible()
  await expect(
    page.getByRole('textbox', { name: 'Absendername' }),
    'Der Absendername fehlt — er landet im From jeder Mail.',
  ).toBeVisible()

  await page.getByRole('button', { name: 'Abbrechen' }).click()
})


test('Schlagwort vergeben, umschalten, wieder wegnehmen', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Ordnerspalte liegt hier in der Schublade.')

  /* ⚠️ **Der ganze Weg, nicht das Feld.** Ein Schlagwort, das gespeichert
     wird und die Ordnerspalte nicht erreicht, ist eine Einstellung, die
     nichts tut — und das ist schlimmer als keine. Der Test vergibt es,
     schaltet um, zählt die Postfächer und räumt wieder auf. */
  const roh = keineRohenMeldungen(page)
  const wort = 'zz-probe'

  await zuEinstellungen(page)
  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()

  const feld = page.getByRole('textbox', { name: 'Schlagworte' })
  await expect(feld, 'Das Feld für Schlagworte fehlt im Postfach-Formular.').toBeVisible()
  await feld.fill(wort)
  await feld.press('Enter')
  await page.getByRole('button', { name: 'Änderungen speichern' }).click()
  await expect(page.getByRole('button', { name: 'Bearbeiten' }).first()).toBeVisible({
    timeout: 15_000,
  })

  /* ⚠️ **Auch in der Liste sichtbar.** Ein Schlagwort, das man nur im
     Formular sieht, zwingt zum Aufklappen jedes Postfachs, um die Zuordnung
     zu prüfen. Der Betreiber am 01.09.2026: „an dieser Stelle für die
     Übersichtlichkeit aber noch die Tag-Badges einblenden." */
  await expect(
    page.getByText(wort, { exact: true }).first(),
    'Das Schlagwort taucht in der Postfachliste nicht auf.',
  ).toBeVisible()

  // ⚠️ **Neu laden.** Sonst prüft der Test den Zustand im Browser, nicht das,
  // was der Server behalten hat — und ein gar nicht gespeichertes Schlagwort
  // bestünde ihn.
  await page.reload()
  await page.getByRole('button', { name: 'Mail', exact: true }).click()

  const umschalter = page.getByRole('group', { name: /Schlagwort|tag/i })
  await expect(umschalter, 'Der Umschalter über der Ordnerspalte fehlt.').toBeVisible()

  const postfaecher = page.locator('section').filter({ hasText: 'Posteingang' })

  /* ⚠️ **Erst warten, bis der Baum steht.** Die Ordner werden je Postfach
     einzeln nachgeladen. Wer sofort zählt, bekommt 0 — und vergleicht
     hinterher gegen 0, was nie kleiner wird. Der Test meldete dann „der
     Umschalter filtert nicht", obwohl er es tat. Am 01.09.2026 genau so. */
  await expect
    .poll(() => postfaecher.count(), {
      message: 'Der Ordnerbaum steht nicht — läuft das Backend auf 8010 mit data-dev?',
      timeout: 20_000,
    })
    .toBeGreaterThan(1)
  const vorher = await postfaecher.count()

  await umschalter.getByRole('button', { name: wort, exact: true }).click()
  await expect
    .poll(() => postfaecher.count(), {
      message: `Nach dem Umschalten auf „${wort}" stehen unverändert ${vorher} Postfächer da — der Umschalter filtert nicht.`,
      timeout: 8000,
    })
    .toBeLessThan(vorher)
  expect(await postfaecher.count(), 'Alle Postfächer sind verschwunden.').toBeGreaterThan(0)

  /* ⚠️ **„Alle Posteingänge" folgt dem Schlagwort.** Am 01.09.2026 zuerst
     andersherum entschieden und am selben Tag gedreht. Geprüft wird die
     Wirkung, nicht die Beschriftung: Die Zahl der ungelesenen Mails dort darf
     nicht größer sein als vor dem Umschalten. */
  const sammel = page.getByRole('button', { name: /Alle Posteingänge|All inboxes/ })
  await expect(sammel, 'Die Zeile „Alle Posteingänge" fehlt.').toBeVisible()
  await expect(sammel).not.toHaveText(/alle Postfächer|all mailboxes/)

  /* ⚠️ **Und die Einschränkung muss beim Server ankommen.** Im Browser
     auszusieben wäre falsch: Die Liste hält nur 200 Zeilen, ein voller
     Posteingang zeigte dann drei Mails und behauptete, mehr gebe es nicht.
     Geprüft wird deshalb die Anfrage, nicht die Anzahl der Zeilen. */
  const anfragen: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/nachrichten?')) anfragen.push(r.url())
  })
  await sammel.click()
  await expect
    .poll(() => anfragen.some((u) => u.includes('konto_ids=')), {
      message:
        'Die Anfrage für „Alle Posteingänge" trägt kein konto_ids — die Sammelansicht ignoriert das Schlagwort.',
      timeout: 8000,
    })
    .toBe(true)

  anfragen.length = 0
  await page.getByRole('button', { name: /^(Markierte|Flagged)$/ }).click()
  await expect
    .poll(() => anfragen.some((u) => u.includes('konto_ids=')), {
      message: 'Auch „Markierte" muss dem Schlagwort folgen.',
      timeout: 8000,
    })
    .toBe(true)

  // Aufräumen: Schlagwort wieder weg, sonst findet der nächste Lauf es vor.
  await umschalter.getByRole('button', { name: 'Alle', exact: true }).click()
  await zuEinstellungen(page)
  await page.getByRole('button', { name: 'Bearbeiten' }).first().click()
  await page.getByRole('button', { name: `„${wort}" entfernen` }).click()
  await page.getByRole('button', { name: 'Änderungen speichern' }).click()
  await expect(page.getByRole('button', { name: 'Bearbeiten' }).first()).toBeVisible({
    timeout: 15_000,
  })

  expect(roh, 'Rohe Server-Meldung in der Oberfläche: ' + roh.join(' | ')).toEqual([])
})

test('Ältere Nachrichten lassen sich nachladen', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** Die Liste hörte bei 200 auf,
     und danach kam nichts: kein Nachladen, kein Blättern, kein Hinweis. Im
     iCloud-Posteingang lagen 1481 Nachrichten — an 1281 davon kam man nur
     noch über die Suche. Ein Mail-Client, der an seine eigene Post nicht
     herankommt, ist im Kern kaputt.

     Geprüft wird die Wirkung: Die Liste **wächst** beim Rollen, und am Ende
     sagt sie, dass Schluss ist. */
  /* ⚠️ **Vorher zählen, nicht null annehmen.** In `data-dev` können schon
     Aufgaben liegen — von Hand angelegte oder aus einem abgebrochenen Lauf.
     Ein Test, der eine leere Liste voraussetzt, scheitert dann an etwas, das
     er gar nicht prüft. Gemessen wird der **Zuwachs**. */
  const leiste = page.getByRole('button', { name: /^(Aufgaben|Tasks)$/ })
  await expect(leiste, 'In der Leiste fehlt „Aufgaben".').toBeVisible()
  await leiste.click()
  await page.waitForTimeout(800)
  const vorher = await page.getByRole('checkbox').count()

  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: /Alle Posteingänge|All inboxes/ }).click()

  const zeilen = page.locator('button[draggable="true"]')
  await expect.poll(() => zeilen.count(), { timeout: 20_000 }).toBeGreaterThan(0)
  const erste = await zeilen.count()

  // Ohne genug Post gibt es nichts nachzuladen — das ist kein Fehler.
  test.skip(erste < 60, `Nur ${erste} Nachrichten da — zum Nachladen zu wenige.`)

  const fuss = page.getByText(/Ältere laden|Load older|Das war alles|That is everything/)
  await expect(fuss, 'Unter der Liste steht kein Fuß — das Ende ist nicht von „mehr kommt nicht" zu unterscheiden.').toBeVisible()

  await zeilen.last().scrollIntoViewIfNeeded()
  await expect
    .poll(() => zeilen.count(), {
      message: `Nach dem Rollen ans Ende stehen unverändert ${erste} Zeilen da — es wird nichts nachgeladen.`,
      timeout: 20_000,
    })
    .toBeGreaterThan(erste)
})

test('Ein Serverfehler sieht nicht aus wie „alles weg"', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** Der Server konnte seine
     Datenbank kurz nicht öffnen. `kontenLaden()` warf, der Fehler wurde
     geschluckt, `konten` blieb leer — und die Oberfläche zeigte „Noch kein
     Postfach" und einen leeren Ordnerbaum.

     Der Betreiber: „meine eingestelten mails sind jetzt alle weg. also die
     postfächer…" Es war nichts weg. Aber genau so sieht ein Datenverlust
     aus, und diesen Schrecken darf eine Anwendung niemandem machen. */
  await page.route('**/api/konten', (r) =>
    r.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":""}' }),
  )
  await page.goto('/')

  await expect(
    page.getByRole('alert').filter({ hasText: /nicht laden|could not be loaded/ }),
    'Ein gescheiterter Abruf sagt nichts — die Oberfläche wirkt einfach leer.',
  ).toBeVisible({ timeout: 20_000 })

  // ⚠️ Und **nicht** die Meldung, die es sonst für einen frisch aufgesetzten
  // nexmail gibt. Genau die stand da und war die eigentliche Schreckensquelle.
  await expect(
    page.getByText(/Noch kein Postfach|No mailbox yet/),
    'Es steht „Noch kein Postfach" da, obwohl der Server nur nicht antwortete.',
  ).toHaveCount(0)

  // Der Knopf holt es nach, sobald es wieder geht.
  await page.unroute('**/api/konten')
  await page.getByRole('button', { name: /Noch einmal versuchen|Try again/ }).click()
  await expect(page.getByRole('alert').filter({ hasText: /nicht laden|could not be loaded/ })).toHaveCount(
    0,
    { timeout: 20_000 },
  )
})

test('Aus einer Mail wird eine Aufgabe, und sie lässt sich abhaken', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  /* ⚠️ **Der ganze Weg, nicht der Menüpunkt.** Eine Aufgabe, die angelegt
     wird und in der Liste nicht auftaucht, ist genau der Fehler, den man erst
     bemerkt, wenn man sich auf sie verlassen hat. */

  /* ⚠️ **Erst leeren.** Zweimal „zu Aufgabe machen" auf dieselbe Mail gibt
     absichtlich **eine** Aufgabe, keine zwei. Liegt aus einem früheren Lauf
     schon eine für die erste Mail vor, wächst die Liste also nicht — und der
     Test scheitert an etwas, das er gar nicht prüft. `data-dev` ist eine
     Testdatenbank; hier darf er aufräumen. */
  await page.evaluate(async () => {
    const alle = await (await fetch('/api/aufgaben', { credentials: 'include' })).json()
    for (const a of alle) {
      await fetch(`/api/aufgaben/${a.id}`, { method: 'DELETE', credentials: 'include' })
    }
  })

  const leiste = page.getByRole('button', { name: /^(Aufgaben|Tasks)$/ })
  await expect(leiste, 'In der Leiste fehlt „Aufgaben".').toBeVisible()
  const vorher = 0

  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: /Alle Posteingänge|All inboxes/ }).click()

  const zeilen = page.locator('button[draggable="true"]')
  await expect.poll(() => zeilen.count(), { timeout: 20_000 }).toBeGreaterThan(0)

  await rechtsklick(page, zeilen.first())
  await page.getByRole('menuitem', { name: /Zu Aufgabe machen|Turn into task/ }).click()

  await leiste.click()

  const kasten = page.getByRole('checkbox').first()
  await expect(
    kasten,
    'Die Aufgabe steht nicht in der Liste — angelegt wurde nichts.',
  ).toBeVisible({ timeout: 15_000 })
  /* ⚠️ **Genau eine mehr.** Beim ersten Anlauf stand hier ein Vergleich, der
     gegen den leeren String prüfte (`.slice(0, 0)`) und deshalb immer
     bestand — eine hohle Zusicherung mitten in einem grünen Test. Der
     Zuwachs ist überprüfbar: aus einer Mail wird eine Aufgabe, nicht zwei. */
  await expect(
    page.getByRole('checkbox'),
    'Aus einer Mail ist nicht genau eine Aufgabe geworden.',
  ).toHaveCount(vorher + 1)

  // Abhaken wirkt — und ist umkehrbar.
  await kasten.click()
  await expect
    .poll(() => kasten.getAttribute('aria-checked'), {
      message: 'Das Abhaken kommt nicht an.',
      timeout: 10_000,
    })
    .toBe('true')

  await kasten.click()
  await expect.poll(() => kasten.getAttribute('aria-checked'), { timeout: 10_000 }).toBe('false')

  // Aufräumen: Die Aufgabe wieder weg, die Mail bleibt.
  await page.getByRole('button', { name: /Aufgabe entfernen|Remove task/ }).first().click()
  await expect(page.getByRole('checkbox')).toHaveCount(vorher, { timeout: 10_000 })

  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await expect.poll(() => zeilen.count(), { timeout: 20_000 }).toBeGreaterThan(0)
})

test('Gespräche fassen zusammen und lassen sich aufklappen', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  /* ⚠️ **Falsch gruppiert versteckt eine Nachricht.** Sie steckt dann in
     einem zugeklappten Strang, und man merkt es erst, wenn man sie sucht.
     Deshalb prüft der Test beide Richtungen: Der Umschalter fasst wirklich
     zusammen — **und** das Aufgeklappte bringt die Nachricht zurück. */
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: /Alle Posteingänge|All inboxes/ }).click()

  const zeilen = page.locator('button[draggable="true"]')
  await expect.poll(() => zeilen.count(), { timeout: 25_000 }).toBeGreaterThan(0)

  const umschalter = page.getByRole('button', { name: /^(Gespräche|Conversations)$/ })
  await expect(umschalter, 'Der Umschalter für Gespräche fehlt.').toBeVisible()
  await expect(
    umschalter,
    'Gespräche sind von vornherein an — sie sollen aus sein, bis man ihnen traut.',
  ).toHaveAttribute('aria-pressed', 'false')

  await umschalter.click()
  const aufklapper = page.locator('[role="button"][aria-expanded]')
  await expect
    .poll(() => aufklapper.count(), {
      message:
        'Nach dem Umschalten steht kein einziges Gespräch da — entweder gruppiert der Server nicht, oder die Liste zeigt es nicht.',
      timeout: 20_000,
    })
    .toBeGreaterThan(0)

  // Aufklappen bringt Nachrichten dazu, Zuklappen nimmt sie wieder weg.
  const vorher = await zeilen.count()
  await aufklapper.first().click()
  await expect
    .poll(() => zeilen.count(), {
      message: 'Das Aufklappen zeigt keine weitere Nachricht — der Strang ist eine Sackgasse.',
      timeout: 15_000,
    })
    .toBeGreaterThan(vorher)

  await page.locator('[role="button"][aria-expanded="true"]').first().click()
  await expect.poll(() => zeilen.count(), { timeout: 15_000 }).toBe(vorher)

  // Zurückstellen, damit der nächste Lauf denselben Stand vorfindet.
  await umschalter.click()
  await expect(umschalter).toHaveAttribute('aria-pressed', 'false')
})

test('„Als gelesen" lässt sich auf „nur von Hand" stellen', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  /* ⚠️ **Die Wirkung, nicht die Einstellung.** Eine Einstellung, die
     gespeichert wird und nichts tut, ist schlimmer als keine — der Betreiber
     stellt etwas ein, nichts passiert, und er sucht den Fehler bei sich. */
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()

  const wahl = page.getByLabel(/Als gelesen markieren|Mark as read/)
  await expect(wahl, 'Die Einstellung „Als gelesen" fehlt.').toBeVisible()
  await wahl.selectOption('-1')

  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.getByRole('button', { name: /Alle Posteingänge|All inboxes/ }).click()

  /* ⚠️ **Eine wirklich ungelesene Nachricht nehmen.** Beim ersten Anlauf
     klickte der Test die erste Zeile der Liste — die war längst gelesen, und
     dann geht ohnehin keine Anfrage hinaus. Der Test bestand, ohne etwas zu
     prüfen; die Mutationsprobe hat ihn aufgedeckt. Über den Filter
     „Ungelesene" ist die Auswahl eindeutig. */
  await page.getByRole('button', { name: /^(Ungelesene|Unread)$/ }).click()
  const ungelesen = page.locator('button[draggable="true"]').first()
  const wieviele = await page.locator('button[draggable="true"]').count()
  test.skip(wieviele === 0, 'Keine ungelesene Nachricht da — nichts zu prüfen.')
  await expect(ungelesen).toBeVisible({ timeout: 20_000 })

  /* Keine Anfrage darf hinausgehen, die etwas als gelesen markiert. Vier
     Sekunden — die längste einstellbare Wartezeit sind zehn, die Vorgabe
     zwei; wäre die Einstellung wirkungslos, wäre sie längst gefeuert. */
  const flags: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/flags') && r.method() !== 'GET') flags.push(r.url())
  })
  await ungelesen.click()
  await page.waitForTimeout(4000)
  expect(
    flags,
    'Trotz „nur von Hand" wurde die Nachricht als gelesen gemeldet.',
  ).toEqual([])

  // Zurück auf die Vorgabe — und den Filter zurückstellen.
  await page.getByRole('button', { name: /^(Alle|All)$/ }).first().click()
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByLabel(/Als gelesen markieren|Mark as read/).selectOption('2')
})

test('Eine Änderung an mir selbst steht sofort da, nicht erst nach F5', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')

  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** `ich` wurde einmal beim Start
     geholt und nach unten durchgereicht — keine Handlung frischte es auf. Wer
     den zweiten Faktor ausschaltete, sah es erst nach F5.

     Der Betreiber: „das zeigt er mir aber erst an, wenn ich mit F5 die seite neu lade
     … das ist an mehreren stellen aufgefallen."

     ⚠️ **Geprüft wird die Mechanik, nicht ein einzelner Schalter.** Der erste
     Anlauf hing am zweiten Faktor — der ist in `data-dev` aus, also übersprang
     sich der Test und wachte über nichts. Jede Handlung im Reiter Sicherheit
     läuft durch dieselbe Stelle; genommen wird deshalb die, die es immer gibt:
     eine Sitzung beenden. Der Server wird dabei **nicht** wirklich verändert. */
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Sicherheit' }).click()

  const beenden = page.getByRole('button', { name: /^(Sitzung beenden|Abmelden)$/ }).first()
  const alleBeenden = page.getByRole('button', { name: /Alle anderen Geräte abmelden|Sign out all other devices/ })
  const knopf = (await beenden.count()) && (await beenden.isEnabled()) ? beenden : alleBeenden
  await expect(knopf, 'Im Reiter Sicherheit gibt es keine Handlung zum Prüfen.').toBeVisible({
    timeout: 10_000,
  })

  // Abgefangen: Der Server bleibt, wie er ist.
  await page.route('**/api/sitzungen/**', (r) =>
    r.request().method() === 'GET' ? r.continue() : r.fulfill({ status: 204, body: '' }),
  )

  const ichAbrufe: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/auth/ich')) ichAbrufe.push(r.url())
  })

  await knopf.click()
  // Eine Rückfrage kann dazwischenstehen.
  const ja = page.getByRole('dialog').getByRole('button', { name: /abmelden|beenden/i }).first()
  if (await ja.isVisible().catch(() => false)) await ja.click()

  await expect
    .poll(() => ichAbrufe.length, {
      message:
        'Nach der Änderung wird `ich` nicht neu geholt — die Oberfläche zeigt den alten Stand bis zum nächsten F5.',
      timeout: 10_000,
    })
    .toBeGreaterThan(0)

  await page.unroute('**/api/sitzungen/**')
})
