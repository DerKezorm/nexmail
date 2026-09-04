/* Der Kalender — bis zur Wirkung durchgetragen.
 *
 * ⚠️ **Jeder Test räumt hinter sich auf.** Die Termine landen in nexmails
 * eigener Datenbank, nicht in einem Postfach; ein Test, der sie liegen lässt,
 * füllt den Kalender des Betreibers mit Prüfzeug — dieselbe Sorte Ärger wie
 * die `ZZ-Anhangprobe`-Mails im Papierkorb.
 */
import { expect, test, type Page } from '@playwright/test'
import { anmelden } from './hilfen'

test.describe.configure({ mode: 'serial' })

/** Ein Name, den kein echter Termin trägt. */
const PROBE = 'ZZ-Kalenderprobe'

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Der Kalender wird breit geprüft.')
  await anmelden(page)
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()
  await aufraeumen(page)
})

test.afterEach(async ({ page }, info) => {
  /* ⚠️ **`test.skip` im `beforeEach` überspringt den Test, nicht das
     Aufräumen.** In der schmalen Breite hat die Seite nie navigiert; ein
     `fetch` mit relativer Adresse läuft dort gegen `about:blank` und
     scheitert mit „Failed to parse URL". Der Lauf war rot, ohne dass am
     Kalender etwas kaputt war. */
  if (info.project.name === 'schmal') return
  await aufraeumen(page)
})

/** Alles wegräumen, was ein Test angelegt hat — über die Adresse, nicht über
 *  die Oberfläche: Eine kaputte Oberfläche soll den Kalender nicht vollmüllen. */
async function aufraeumen(page: Page) {
  /* ⚠️ **Das Aufräumen darf den Lauf nicht umbringen.** Es ist Haushalt, nicht
     das Geprüfte. Am 03.09.2026 scheiterte es zweimal mit „Failed to fetch" —
     der Entwicklungsserver lädt beim Bearbeiten neu, und dann ist die Adresse
     für einen Wimpernschlag weg. Ein zweiter Versuch genügt. */
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

    /* ⚠️ **Und alle Kalender wieder sichtbar machen.** Ein Test blendet einen
       aus; bricht er vorher ab, bleibt er ausgeblendet — und der nächste Lauf
       sucht Termine, die es scheinbar nicht gibt. Am 03.09.2026 genau so
       passiert: Der Kalender stand danach halb leer da. */
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

/** Einen Termin über die Adresse anlegen — der Test der Oberfläche kommt
 *  danach. */
async function anlegen(page: Page, titel: string, rrule = '') {
  return page.evaluate(
    async ({ titel, rrule }) => {
      const ks = await (await fetch('/api/kalender', { credentials: 'include' })).json()
      const beginn = new Date()
      beginn.setHours(10, 0, 0, 0)
      const antwort = await fetch('/api/kalender/termine', {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          kalender_id: ks[0].id,
          titel,
          beginn: beginn.toISOString(),
          rrule,
        }),
      })
      return antwort.json()
    },
    { titel, rrule },
  )
}


test('Ein Termin lässt sich anlegen und wiederfinden', async ({ page }) => {
  await page.getByRole('button', { name: /Neuer Termin/ }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()

  await fenster.getByLabel('Titel').fill(`${PROBE} Zahnarzt`)
  await fenster.getByRole('button', { name: 'Speichern' }).click()

  // ⚠️ Die **Folge** prüfen, nicht den Klick: Ein Speichern, das nirgends
  // ankommt, sieht aus wie eines, das tut.
  await expect(fenster).toBeHidden()
  await expect(page.getByText(`${PROBE} Zahnarzt`).first()).toBeVisible()
})


test('Ein wiederholter Termin fragt, was gemeint ist', async ({ page }) => {
  await anlegen(page, `${PROBE} Reihe`, 'FREQ=WEEKLY')
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()

  const treffer = page.getByText(`${PROBE} Reihe`)
  await expect(treffer.first()).toBeVisible()
  // Eine Woche steht mehrfach im Monat.
  expect(await treffer.count()).toBeGreaterThan(1)

  await treffer.first().click()
  await page.getByRole('button', { name: 'Löschen', exact: true }).click()

  /* ⚠️ **Ohne die Frage löscht ein Klick fünfzig Termine.** Jedes
     Kalenderprogramm fragt sie, weil das Format keine andere Antwort kennt. */
  const frage = page.getByRole('dialog').filter({ hasText: 'Wiederholter Termin' })
  await expect(frage).toBeVisible()
  for (const wahl of ['Nur dieser Termin', 'Dieser und alle folgenden', 'Alle Termine der Reihe']) {
    await expect(frage.getByRole('button', { name: wahl })).toBeVisible()
  }
})


test('„Nur dieser" nimmt genau einen heraus', async ({ page }) => {
  await anlegen(page, `${PROBE} Reihe`, 'FREQ=WEEKLY')
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()

  const treffer = page.getByText(`${PROBE} Reihe`)
  await expect(treffer.first()).toBeVisible()
  const vorher = await treffer.count()

  await treffer.first().click()
  await page.getByRole('button', { name: 'Löschen', exact: true }).click()
  await page.getByRole('button', { name: 'Nur dieser Termin' }).click()

  await expect.poll(() => treffer.count()).toBe(vorher - 1)
})


test('Ein einzelner Termin wird ohne Rückfrage gelöscht', async ({ page }) => {
  await anlegen(page, `${PROBE} Einmalig`)
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()

  const treffer = page.getByText(`${PROBE} Einmalig`)
  await expect(treffer.first()).toBeVisible()
  await treffer.first().click()
  await page.getByRole('button', { name: 'Löschen', exact: true }).click()

  // ⚠️ Kein „Wiederholter Termin" — die Frage bei etwas, das sich nicht
  // wiederholt, wäre Schikane.
  await expect(page.getByText('Wiederholter Termin')).toBeHidden()
  await expect(treffer).toHaveCount(0)
})


test('Ein ausgeblendeter Kalender versteckt seine Termine', async ({ page }) => {
  await anlegen(page, `${PROBE} Sichtbar`)
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByText(`${PROBE} Sichtbar`).first()).toBeVisible()

  /* ⚠️ **Geklickt wird die Beschriftung, nicht das `<input>`.** Der Haken des
     Design-Systems ist `sr-only` — er hat null Pixel, und Playwright kommt
     nicht an ihn heran. Ein Mensch klickt ohnehin auf den Namen. */
  const haken = page.locator('aside').getByText('Privat', { exact: true })
  await haken.click()

  /* ⚠️ **Eine Einstellung, die nichts tut, ist schlimmer als keine.** Der
     Haken muss die Liste wirklich leeren, nicht nur sich selbst umlegen. */
  await expect(page.getByText(`${PROBE} Sichtbar`)).toHaveCount(0)
  await haken.click()
  await expect(page.getByText(`${PROBE} Sichtbar`).first()).toBeVisible()
})


test('Der Kalender kommt ohne Browser-Kasten aus', async ({ page }) => {
  const kaesten: string[] = []
  page.on('dialog', async (d) => {
    kaesten.push(d.type())
    await d.dismiss()
  })

  await page.locator('aside').getByText('Privat', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Umbenennen' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Abbrechen' }).click()

  expect(kaesten, 'window.confirm/prompt sind keine Oberfläche.').toEqual([])
})


// --- Die Wiederholung in der Maske ---------------------------------------- #


test('Die Liste bietet fertige Muster, nicht nur Häufigkeiten', async ({ page }) => {
  /* ⚠️ **Vier Felder für „jeden Montag" sind drei zu viel.** Erst stand dort
     nur „Wöchentlich" und darunter vier Bausteine; gemeldet am 03.09.2026:
     „müsste da nicht stehen ‚jeden ersten Montag' oder sowas?" — genau so
     macht es Thunderbird, und aus demselben Grund. */
  await page.getByRole('button', { name: /Neuer Termin/ }).click()
  const fenster = page.getByRole('dialog')
  const auswahl = fenster.getByLabel('Wiederholung')

  const texte = await auswahl.locator('option').allTextContents()

  expect(texte[0]).toBe('Keine')
  expect(texte.at(-1)).toContain('Eigene')
  // Die Muster leiten sich vom Beginn ab — der Wochentag muss darin vorkommen.
  const wochentag = new Date().toLocaleDateString('de-DE', { weekday: 'long' })
  expect(
    texte.some((x) => x.includes(wochentag)),
    `Kein Muster nennt den Wochentag des Beginns (${wochentag}): ${texte.join(' · ')}`,
  ).toBe(true)
  expect(texte.some((x) => x.startsWith('Alle zwei Wochen'))).toBe(true)
  expect(texte.some((x) => x.startsWith('Monatlich am'))).toBe(true)
})


/* ⚠️ **Jedes Muster einzeln.** Die Regel wird zerlegt, gebaut und wieder
   zerlegt; passt eines der drei nicht zusammen, steht beim zweiten Öffnen ein
   anderes Muster — und ein Speichern nähme die Wiederholung mit.

   Geprüft werden die beiden, an denen etwas verloren gehen kann: das
   Intervall („alle zwei Wochen") und der Wievielte („am ersten Donnerstag").
   Ohne den zweiten fällt niemandem auf, wenn aus `BYDAY=1TH` ein `BYDAY=TH`
   wird — die Reihe läuft weiter, nur eben jede Woche. */
for (const anfang of ['Alle zwei Wochen', 'Monatlich am '] as const) {
  test(`Muster „${anfang}…" steht beim Wiederöffnen wieder da`, async ({ page }) => {
    await page.getByRole('button', { name: /Neuer Termin/ }).click()
    const fenster = page.getByRole('dialog')
    const titel = `${PROBE} ${anfang.trim()}`
    await fenster.getByLabel('Titel').fill(titel)

    const auswahl = fenster.getByLabel('Wiederholung')
    const texte = await auswahl.locator('option').allTextContents()
    // Bei „Monatlich am " gibt es zwei — der mit dem Wochentag ist der zweite.
    const treffer = texte.filter((x) => x.startsWith(anfang))
    const gewuenscht = treffer.at(-1)!
    expect(gewuenscht, `Kein Muster beginnt mit „${anfang}": ${texte.join(' · ')}`).toBeTruthy()

    await auswahl.selectOption({ label: gewuenscht })
    await fenster.getByRole('button', { name: 'Speichern' }).click()
    await expect(fenster).toBeHidden()

    await page.getByText(titel).first().click()
    const wieder = page.getByRole('dialog')
    await expect(wieder).toBeVisible()

    await expect(
      wieder.getByLabel('Wiederholung'),
      `Beim Wiederöffnen steht ein anderes Muster da als beim Speichern („${gewuenscht}").`,
    ).toHaveValue(await optionWert(wieder, gewuenscht))
  })
}


test('Eine fremde Regel wird benannt, nicht zerlegt', async ({ page }) => {
  /* ⚠️ **Der teuerste Fall.** „Am 15. jedes Monats" (`BYMONTHDAY`) bildet die
     Maske nicht ab. Sie trotzdem in Bausteine zu zwingen hiesse: Aus der Regel
     würde beim Speichern „monatlich", und der Tag wäre weg. */
  await anlegen(page, `${PROBE} Fremd`, 'FREQ=MONTHLY;BYMONTHDAY=15')
  // ⚠️ Nach dem Neuladen steht die Mail-Ansicht da, nicht der Kalender —
  // der Reiter steckt nicht in der Adresse.
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()

  await page.getByText(`${PROBE} Fremd`).first().click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()

  // Keine Bausteine — sondern der Satz, der sagt, warum.
  await expect(fenster.getByText(/lässt sich hier nicht bearbeiten/)).toBeVisible()
  await expect(fenster.getByLabel('Wiederholung')).toHaveCount(0)
})


/** Der `value` einer Option zu ihrem sichtbaren Text. */
async function optionWert(fenster: ReturnType<Page['getByRole']>, text: string) {
  return fenster
    .getByLabel('Wiederholung')
    .locator('option')
    .filter({ hasText: text })
    .first()
    .getAttribute('value')
    .then((v) => v ?? '')
}


test('Ohne Teilnehmer steht kein leerer Abschnitt da', async ({ page }) => {
  await page.getByRole('button', { name: /Neuer Termin/ }).click()
  const neu = page.getByRole('dialog')
  await neu.getByLabel('Titel').fill(`${PROBE} Allein`)
  await neu.getByRole('button', { name: 'Speichern' }).click()
  await expect(neu).toBeHidden()

  await page.getByText(`${PROBE} Allein`).first().click()
  await expect(page.getByRole('dialog').getByText(/Teilnehmer/)).toHaveCount(0)
})


test('Teilnehmer stehen am Termin — mit ihrem Zusagestand', async ({ page }) => {
  /* ⚠️ **Geprüft wird die ANZEIGE, nicht der Weg dorthin.** Ein Termin mit
     Teilnehmern entsteht nur über CalDAV oder eine übernommene Einladung;
     beides in einen Oberflächen-Test zu ziehen hieße, den halben Server
     nachzubauen. Woher die Daten kommen, halten die Backend-Tests fest
     (`test_teilnehmer_kommen_mit`) — hier zählt, dass man sie sieht.

     ⚠️ **Und der Zusagestand gehört dazu.** Ohne ihn ist eine
     Teilnehmerliste eine Namensliste, und man weiß nicht, wer kommt. */
  await page.route('**/api/kalender/termine?*', async (weg) => {
    const echt = await weg.fetch()
    const daten = await echt.json()
    if (Array.isArray(daten) && daten.length) {
      daten[0] = {
        ...daten[0],
        titel: `${PROBE} Runde`,
        organisator: { name: 'Vera Beispiel', adresse: 'vera@example.com', antwort: '', rolle: '' },
        teilnehmer: [
          { name: 'Anja', adresse: 'anja@example.com', antwort: 'ACCEPTED', rolle: '' },
          { name: 'Jan', adresse: 'jan@example.com', antwort: 'DECLINED', rolle: '' },
        ],
      }
    }
    await weg.fulfill({ response: echt, json: daten })
  })

  await anlegen(page, `${PROBE} Traeger`)
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()

  await page.getByText(`${PROBE} Runde`).first().click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()

  await expect(fenster.getByText('2 Teilnehmer')).toBeVisible()
  await expect(fenster.getByText(/Eingeladen von Vera Beispiel/)).toBeVisible()
  await expect(fenster.getByText('Zugesagt')).toBeVisible()
  await expect(fenster.getByText('Abgesagt')).toBeVisible()
})

/* --- Ziehen ------------------------------------------------------------- */

/** Einen Termin über die Adresse nachschlagen — die Oberfläche ist hier der
 *  Weg, nicht die Auskunft. */
async function nachschlagen(page: Page, id: number) {
  return page.evaluate(async (id) => {
    const von = new Date()
    von.setMonth(von.getMonth() - 2)
    const bis = new Date()
    bis.setMonth(bis.getMonth() + 2)
    const frage = new URLSearchParams({ von: von.toISOString(), bis: bis.toISOString() })
    const alle = await (
      await fetch(`/api/kalender/termine?${frage}`, { credentials: 'include' })
    ).json()
    const t = (alle as Array<{ id: number; beginn: string; ende: string }>).find((x) => x.id === id)
    return t ? { beginn: t.beginn, ende: t.ende } : null
  }, id)
}

/** In die Wochenansicht, wo es ein Zeitraster gibt. */
async function inDieWoche(page: Page) {
  await page.getByRole('button', { name: 'Woche', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Woche', exact: true })).toBeVisible()
}

/** Eine echte Mausbewegung — Playwright erzeugt dabei `pointerType: 'mouse'`,
 *  und genau darauf hört das Ziehen (mit dem Finger rollt die Ansicht). */
async function ziehen(page: Page, block: ReturnType<Page['locator']>, dx: number, dy: number) {
  const kasten = await block.boundingBox()
  if (!kasten) throw new Error('Der Block hat keine Ausdehnung')
  const x = kasten.x + kasten.width / 2
  const y = kasten.y + 8
  await page.mouse.move(x, y)
  await page.mouse.down()
  // ⚠️ Zwei Schritte: Der erste bringt den Zeiger über die 4-px-Schwelle,
  // erst danach gilt es als Zug und nicht mehr als Klick.
  await page.mouse.move(x + Math.sign(dx) * 6, y + Math.sign(dy) * 6)
  await page.mouse.move(x + dx, y + dy)
  await page.mouse.up()
}

test('Ein gezogener Termin steht danach eine Stunde später', async ({ page }) => {
  const termin = await anlegen(page, `${PROBE} Zug`)
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()
  await inDieWoche(page)

  const vorher = await nachschlagen(page, termin.id)
  const block = page.getByRole('button', { name: new RegExp(`${PROBE} Zug`) }).first()
  await expect(block).toBeVisible()

  // 48 px sind genau eine Stunde (STUNDE_PX).
  await ziehen(page, block, 0, 48)

  await expect
    .poll(async () => (await nachschlagen(page, termin.id))?.beginn, {
      message: 'Der Zug ist nicht beim Server angekommen',
    })
    .not.toBe(vorher?.beginn)

  const nachher = await nachschlagen(page, termin.id)
  const verschoben =
    (new Date(nachher!.beginn).getTime() - new Date(vorher!.beginn).getTime()) / 60_000
  expect(verschoben).toBe(60)

  /* ⚠️ **Hier stand einmal eine Zusicherung auf die Dauer, und sie war Zierde.**
     Die Mutationsprobe lief auf Rückgabecode 0: `termine.aendern` im Server
     hält die Dauer von sich aus, wenn nur der Beginn ankommt. Der Test konnte
     also gar nicht rot werden. Wo die Zusicherung wirklich hängt:
     `lib/ziehen.test.ts` für die Rechnung der Oberfläche (dort wird die
     Mutation erkannt) und `termine.aendern` für den Server. Zwei Tests, die
     dasselbe behaupten, aber nur einer kann es beweisen. */
})

test('Die Unterkante ändert das Ende und lässt den Beginn stehen', async ({ page }) => {
  const termin = await anlegen(page, `${PROBE} Kante`)
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()
  await inDieWoche(page)

  const vorher = await nachschlagen(page, termin.id)
  const block = page.getByRole('button', { name: new RegExp(`${PROBE} Kante`) }).first()
  const kasten = await block.boundingBox()
  if (!kasten) throw new Error('Der Block hat keine Ausdehnung')

  // Der Griff liegt in den untersten Pixeln des Blocks.
  const x = kasten.x + kasten.width / 2
  const y = kasten.y + kasten.height - 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y + 8)
  await page.mouse.move(x, y + 48)
  await page.mouse.up()

  await expect
    .poll(async () => (await nachschlagen(page, termin.id))?.ende, {
      message: 'Die Kante ist nicht beim Server angekommen',
    })
    .not.toBe(vorher?.ende)

  const nachher = await nachschlagen(page, termin.id)
  expect(nachher!.beginn).toBe(vorher!.beginn)
  expect(new Date(nachher!.ende).getTime()).toBeGreaterThan(new Date(vorher!.ende).getTime())
})

test('Ein Zug an einer Reihe fragt, was gemeint ist', async ({ page }) => {
  /* ⚠️ **Ein Zug ist billiger als ein Formular — genau deshalb muss die Frage
     bleiben.** Ohne sie verschiebt eine Handbewegung fünfzig Termine. */
  await anlegen(page, `${PROBE} Reihe`, 'FREQ=WEEKLY')
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()
  await inDieWoche(page)

  const block = page.getByRole('button', { name: new RegExp(`${PROBE} Reihe`) }).first()
  await expect(block).toBeVisible()
  await ziehen(page, block, 0, 48)

  const frage = page.getByRole('dialog')
  await expect(frage).toBeVisible()
  await expect(frage.getByRole('button', { name: /Nur dieser/ })).toBeVisible()
  await expect(frage.getByRole('button', { name: /folgenden/ })).toBeVisible()
  await expect(frage.getByRole('button', { name: /Alle Termine/ })).toBeVisible()
  // Abbrechen lässt alles, wie es war.
  await frage.getByRole('button', { name: 'Abbrechen' }).click()
})

test('Ein Wackeln beim Klicken oeffnet weiterhin den Termin', async ({ page }) => {
  /* ⚠️ **Ohne Schwelle oeffnet kein Klick mehr einen Termin.** Eine Maus
     wackelt beim Druecken um ein, zwei Pixel; jeder dieser Pixel waere sonst
     ein Zug um null Minuten — und der unterdrueckt den Klick.

     ⚠️ **Playwrights `click()` findet das nicht.** Es setzt den Zeiger und
     drueckt, ohne ihn dazwischen zu bewegen; `pointermove` feuert nie. Die
     Bewegung muss von Hand kommen, sonst prueft der Test die Schwelle nicht. */
  await anlegen(page, `${PROBE} Wackeln`)
  await page.reload()
  await page.getByRole('button', { name: 'Kalender', exact: true }).click()
  await expect(page.getByRole('button', { name: /Neuer Termin/ })).toBeVisible()
  await inDieWoche(page)

  const block = page.getByRole('button', { name: new RegExp(`${PROBE} Wackeln`) }).first()
  const kasten = await block.boundingBox()
  if (!kasten) throw new Error('Der Block hat keine Ausdehnung')
  const x = kasten.x + kasten.width / 2
  const y = kasten.y + 8

  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 2, y + 1) // unter der Schwelle
  await page.mouse.up()

  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog').getByText(`${PROBE} Wackeln`)).toBeVisible()
})
