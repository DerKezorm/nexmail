/* Dateien ins Verfassen-Fenster ziehen.
 *
 * ⚠️ **Das Ablegen wird als Ereignis nachgestellt.** Einen echten Griff aus dem
 * Dateisystem kann Playwright nicht; das `DataTransfer` trägt aber echte Dateien.
 * Es wird nichts gesendet: Das Fenster geht am Ende über „Verwerfen" zu.
 *
 * Einzeln ausführbar:
 *   npx playwright test tests/verfassen_ablegen.spec.ts --reporter=line
 */
import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import { anmelden } from './hilfen'

test.beforeEach(({ page: _page }, info) => {
  test.skip(info.project.name === 'schmal', 'Dateien zieht man am Schreibtisch.')
})

interface Datei {
  name: string
  typ: string
  inhalt?: string
}

/** Ein `DataTransfer` mit echten Dateien, im Browser gebaut. */
async function korb(page: Page, dateien: Datei[]) {
  return page.evaluateHandle((liste) => {
    const dt = new DataTransfer()
    for (const d of liste) dt.items.add(new File([d.inhalt ?? 'Probeinhalt'], d.name, { type: d.typ }))
    return dt
  }, dateien)
}

/** Mitte des Ziels, damit der Editor eine Stelle im Text findet. */
async function mitte(ziel: Locator) {
  const kasten = await ziel.boundingBox()
  if (!kasten) throw new Error('Das Ziel steht nicht im Bild.')
  return { clientX: kasten.x + kasten.width / 2, clientY: kasten.y + 40 }
}

async function ablegen(page: Page, ziel: Locator, dateien: Datei[]) {
  const dataTransfer = await korb(page, dateien)
  const stelle = await mitte(ziel)
  await ziel.dispatchEvent('dragenter', { dataTransfer, ...stelle })
  await ziel.dispatchEvent('dragover', { dataTransfer, ...stelle })
  await ziel.dispatchEvent('drop', { dataTransfer, ...stelle })
}

async function fensterOeffnen(page: Page) {
  await anmelden(page)
  await page.getByRole('button', { name: 'Neue Nachricht' }).first().click()
  const fenster = page.getByRole('dialog', { name: 'Neue Nachricht' })
  await expect(fenster).toBeVisible()
  await expect(fenster.locator('[contenteditable="true"]')).toBeVisible()
  return fenster
}

const textfeld = (fenster: Locator) => fenster.locator('[contenteditable="true"]')
/* ⚠️ Nicht jedes `img`: ProseMirror setzt hinter ein Bild am Zeilenende ein eigenes. */
const bilder = (fenster: Locator) => textfeld(fenster).locator('img[src^="blob:"]')
const PDF = { name: 'angebot.pdf', typ: 'application/pdf' }
const BILD = { name: 'foto.png', typ: 'image/png' }

test.afterEach(async ({ page }) => {
  await page.getByRole('button', { name: 'Verwerfen' }).click({ timeout: 1500 }).catch(() => undefined)
})

test('Beim Ziehen sagt das Fenster, was geschieht, und vergisst es danach', async ({ page }) => {
  const fenster = await fensterOeffnen(page)
  const dataTransfer = await korb(page, [PDF])

  await fenster.dispatchEvent('dragover', { dataTransfer })
  await expect(fenster.getByText('Zum Anhängen hier ablegen')).toBeVisible()

  await page.locator('.fixed.inset-0').first().dispatchEvent('dragleave', { dataTransfer })
  await expect(fenster.getByText('Zum Anhängen hier ablegen')).toHaveCount(0)
})

test('Text, der gezogen wird, ist kein Anhang', async ({ page }) => {
  const fenster = await fensterOeffnen(page)
  const dataTransfer = await page.evaluateHandle(() => {
    const dt = new DataTransfer()
    dt.setData('text/plain', 'Nur Text')
    return dt
  })

  await fenster.dispatchEvent('dragover', { dataTransfer })

  await expect(fenster.getByText('Zum Anhängen hier ablegen')).toHaveCount(0)
})

test('Eine Datei wird zum Anhang, auch mehrere gleichen Namens', async ({ page }) => {
  const fenster = await fensterOeffnen(page)

  await ablegen(page, fenster.getByPlaceholder('Betreff'), [PDF, { ...PDF, inhalt: 'Zweite Fassung' }])

  await expect(fenster.getByText('angebot.pdf')).toHaveCount(2)
  await expect(fenster.getByText('Zum Anhängen hier ablegen')).toHaveCount(0)
})

test('Gleichnamige Dateien behalten ihren Inhalt, auch gleichzeitig abgelegt', async ({ page }) => {
  /* ⚠️ Gefunden wurde die Zeile früher über den Namen: Die langsame erste Datei
     hätte den Inhalt der schnellen zweiten bekommen. */
  const fenster = await fensterOeffnen(page)
  await page.evaluate(() => {
    const echt = File.prototype.arrayBuffer
    File.prototype.arrayBuffer = async function () {
      if ((await this.text()) === 'langsam') {
        await new Promise((fertig) => {
          ;(window as unknown as { weiter: () => void }).weiter = () => fertig(null)
        })
      }
      return echt.call(this)
    }
  })
  const entwuerfe: Array<{ anlagen: Array<{ inhalt_b64: string }> }> = []
  await page.route('**/api/verfassen/entwurf', async (route) => {
    entwuerfe.push(route.request().postDataJSON())
    await route.fulfill({ json: { uid: 1 } })
  })

  await ablegen(page, fenster.getByPlaceholder('Betreff'), [{ ...PDF, inhalt: 'langsam' }])
  await expect(fenster.getByText('angebot.pdf')).toHaveCount(1)
  await ablegen(page, fenster.getByPlaceholder('Betreff'), [{ ...PDF, inhalt: 'schnell' }])
  await expect(fenster.getByText('angebot.pdf')).toHaveCount(2)
  await page.waitForTimeout(200)
  await page.evaluate(() => (window as unknown as { weiter: () => void }).weiter())
  await expect(fenster.getByRole('button', { name: 'Später senden' })).toBeDisabled()

  await fenster.getByPlaceholder('Betreff').fill('Probe')
  await fenster.getByRole('button', { name: 'Schließen (der Entwurf bleibt erhalten)' }).click()

  await expect(fenster).toBeHidden()
  const inhalte = entwuerfe[0].anlagen.map((a) => Buffer.from(a.inhalt_b64, 'base64').toString())
  expect(inhalte).toEqual(['langsam', 'schnell'])
})

test('Auch der Rand neben dem Fenster nimmt die Datei an', async ({ page }) => {
  /* ⚠️ Ohne das öffnet der Browser die Datei, und der Entwurf ist weg. */
  const fenster = await fensterOeffnen(page)
  await ablegen(page, page.locator('.fixed.inset-0').first(), [PDF])
  await expect(fenster.getByText('angebot.pdf')).toBeVisible()
})

test('Ein Bild im Text steht im Text, nicht in der Anhangleiste', async ({ page }) => {
  const fenster = await fensterOeffnen(page)

  await ablegen(page, textfeld(fenster), [BILD])

  await expect(bilder(fenster)).toHaveCount(1)
  await expect(fenster.getByText('foto.png')).toHaveCount(0)
})

test('Bild und PDF zusammen im Text werden beide zu Anhängen', async ({ page }) => {
  const fenster = await fensterOeffnen(page)

  await ablegen(page, textfeld(fenster), [BILD, PDF])

  await expect(fenster.getByText('foto.png')).toBeVisible()
  await expect(fenster.getByText('angebot.pdf')).toBeVisible()
  await expect(bilder(fenster)).toHaveCount(0)
})

test('Eine zu große Datei wird gar nicht erst gelesen', async ({ page }) => {
  const fenster = await fensterOeffnen(page)
  const dataTransfer = await page.evaluateHandle(() => {
    const dt = new DataTransfer()
    dt.items.add(new File([new Uint8Array(26 * 1024 * 1024)], 'film.mp4', { type: 'video/mp4' }))
    return dt
  })

  await fenster.dispatchEvent('drop', { dataTransfer })

  await expect(fenster.getByRole('alert')).toContainText('film.mp4')
  await expect(fenster.getByRole('alert')).toContainText('25 MB')
  await expect(fenster.getByRole('listitem').filter({ hasText: 'film.mp4' })).toHaveCount(0)
})

test('Entfernt wird der gewählte Anhang, auch neben einem Bild im Text', async ({ page }) => {
  /* ⚠️ Das Kreuz nahm die Stelle in der gefilterten Liste und traf damit die
     falsche Zeile, sobald ein eingefügtes Bild davor stand. */
  const fenster = await fensterOeffnen(page)
  await ablegen(page, textfeld(fenster), [BILD])
  await expect(bilder(fenster)).toHaveCount(1)
  await ablegen(page, fenster.getByPlaceholder('Betreff'), [
    { name: 'eins.txt', typ: 'text/plain' },
    { name: 'zwei.txt', typ: 'text/plain' },
  ])

  await fenster
    .getByRole('listitem')
    .filter({ hasText: 'eins.txt' })
    .getByRole('button', { name: 'Löschen' })
    .click()

  await expect(fenster.getByText('eins.txt')).toHaveCount(0)
  await expect(fenster.getByText('zwei.txt')).toBeVisible()
  await expect(bilder(fenster)).toHaveCount(1)
})

test('Escape bewahrt, was gerade getippt wurde', async ({ page }) => {
  /* ⚠️ Der Zuhörer sah den Stand beim letzten Zeichnen von `App`, also ein leeres
     Fenster, und schloss ohne Entwurf. */
  const fenster = await fensterOeffnen(page)
  await page.waitForTimeout(800)
  const entwuerfe: string[] = []
  await page.route('**/api/verfassen/entwurf', async (route) => {
    entwuerfe.push(route.request().postDataJSON().html)
    await route.fulfill({ json: { uid: 1 } })
  })

  await textfeld(fenster).click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('Das darf nicht verloren gehen.')
  await expect(textfeld(fenster)).toContainText('Das darf nicht verloren gehen.')
  await page.keyboard.press('Escape')

  await expect(fenster).toBeHidden()
  expect(entwuerfe).toHaveLength(1)
  expect(entwuerfe[0]).toContain('Das darf nicht verloren gehen.')
})

test('Escape in der Link-Frage lässt das Fenster offen', async ({ page }) => {
  const fenster = await fensterOeffnen(page)
  await fenster.getByRole('button', { name: 'Link einfügen' }).click()
  const frage = page.getByLabel('Adresse', { exact: true })
  await expect(frage).toBeVisible()

  await page.keyboard.press('Escape')

  await expect(frage).toHaveCount(0)
  await expect(fenster).toBeVisible()
})

test('Wer dem Zeichnen vorausschreibt, verliert nichts', async ({ page }) => {
  /* ⚠️ Der Editor hielt seinen eigenen, verspätet zurückkommenden Stand für einen
     neuen Startinhalt und setzte den Text darauf zurück. */
  const fenster = await fensterOeffnen(page)
  await page.waitForTimeout(800)
  await textfeld(fenster).click()

  const zeichen = await page.evaluate(async () => {
    const kasten = document.querySelector('.ProseMirror') as unknown as {
      editor: { commands: { insertContent: (t: string) => void } }
    }
    for (let i = 0; i < 400; i += 1) {
      kasten.editor.commands.insertContent('x')
      await new Promise((weiter) => setTimeout(weiter, 0))
    }
    return (document.querySelector('.ProseMirror')?.textContent ?? '').split('x').length - 1
  })

  expect(zeichen).toBe(400)
  await expect(textfeld(fenster)).toContainText('x'.repeat(400))
})

test('Hervorhebung und Größe gehen mit hinaus', async ({ page }) => {
  /* ⚠️ Beide kamen nie an: `mark` fiel in der Bereinigung weg, und die Größe
     stand gar nicht erst im Text. Hier die Hälfte im Browser, die Bereinigung
     prüft `test_bereinigen.py` mit genau diesem HTML. */
  const fenster = await fensterOeffnen(page)
  await page.waitForTimeout(800)
  const entwuerfe: string[] = []
  await page.route('**/api/verfassen/entwurf', async (route) => {
    entwuerfe.push(route.request().postDataJSON().html)
    await route.fulfill({ json: { uid: 1 } })
  })

  await textfeld(fenster).click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('Wichtig')
  await page.keyboard.press('Control+a')
  await fenster.getByRole('button', { name: 'Hervorheben' }).click()
  await fenster.getByRole('combobox', { name: 'Größe' }).selectOption('14')
  await expect(textfeld(fenster).locator('mark')).toHaveCSS('font-size', /18\.\d+px/)
  await textfeld(fenster).click()
  await page.keyboard.press('Escape')

  await expect(fenster).toBeHidden()
  expect(entwuerfe[0]).toContain('<mark')
  expect(entwuerfe[0]).toContain('font-size: 14pt')
})

test('Solange eine Datei gelesen wird, geht nichts hinaus', async ({ page }) => {
  /* ⚠️ Fertige Anlagen fahren mit, halb gelesene fielen lautlos weg. */
  const fenster = await fensterOeffnen(page)
  await page.evaluate(() => {
    const echt = File.prototype.arrayBuffer
    File.prototype.arrayBuffer = function () {
      return new Promise((fertig) => {
        ;(window as unknown as { weiter: () => void }).weiter = () => fertig(echt.call(this))
      })
    }
  })
  await fenster.getByPlaceholder('Name oder Adresse').first().fill('vera@example.org, ')
  const senden = fenster.getByRole('button', { name: 'Senden', exact: true })
  await expect(senden).toBeEnabled()

  await ablegen(page, fenster.getByPlaceholder('Betreff'), [PDF])
  await expect(fenster.getByText('angebot.pdf')).toBeVisible()
  await expect(senden).toBeDisabled()
  await expect(fenster.getByRole('button', { name: 'Später senden' })).toBeDisabled()

  await page.evaluate(() => (window as unknown as { weiter: () => void }).weiter())
  await expect(senden).toBeEnabled()
})

test('Ein Ordner lässt sich nicht lesen, und das steht da', async ({ page }) => {
  const fenster = await fensterOeffnen(page)
  await page.evaluate(() => {
    const echt = File.prototype.arrayBuffer
    File.prototype.arrayBuffer = function () {
      return this.name === 'bilder' ? Promise.reject(new Error('kein Inhalt')) : echt.call(this)
    }
  })

  await ablegen(page, fenster.getByPlaceholder('Betreff'), [{ name: 'bilder', typ: '' }])

  await expect(fenster.getByRole('alert')).toContainText('bilder')
  await expect(fenster.getByRole('listitem').filter({ hasText: 'bilder' })).toHaveCount(0)
})
