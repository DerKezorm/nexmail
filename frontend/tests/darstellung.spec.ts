/* Darstellung — die Fehlerklasse, die Anna reihenweise gefunden hat.
 *
 * Jeder Test hier steht für einen echten Fehler vom 31.08./01.09.2026:
 * überlaufende Beschriftung, abgeschnittener Auswahlwert, weiße Auswahlliste,
 * kaputtes Bildsymbol, persönlicher Name im Platzhalter.
 */
import { expect, test } from '@playwright/test'
import {
  TESTPOSTFACH,
  anmelden,
  jederKnopfHatEinenNamen,
  keineRohenSchluessel,
  tabuWoerter,
  rechtsklick,
  postfach,
  zuEinstellungen,
  auswahllistenSindGefaerbt,
  keinSeitlichesScrollen,
  keinTextLaeuftUeber,
  keineKaputtenBilder,
  serverabsagen,
} from './hilfen'

test.beforeEach(async ({ page }) => {
  await anmelden(page)
})

test('Mail-Ansicht: nichts läuft über, nichts ist kaputt', async ({ page }) => {
  await keinTextLaeuftUeber(page)
  await keineKaputtenBilder(page)
  await keinSeitlichesScrollen(page)
})

test('Postfach-Formular: deutsche Beschriftungen passen in ihre Spalten', async ({ page }) => {
  await zuEinstellungen(page)
  await page.getByRole('button', { name: 'Postfach hinzufügen' }).first().click()

  // Der Serverblock ist zugeklappt, solange Autoconfig noch nichts gemeldet
  // hat — die langen Beschriftungen stecken darin.
  const aufklappen = page.getByRole('button', { name: /Serverdaten/ })
  if (await aufklappen.count()) await aufklappen.first().click()

  await expect(page.getByText('POSTEINGANG (IMAP)')).toBeVisible()
  await keinTextLaeuftUeber(page)
  await auswahllistenSindGefaerbt(page)

  // ⚠️ Der konkrete Fall: „STARTTLS" wurde zu „STARTTI", weil die Spalte
  // 96 px breit war und der Text 65 px plus Polster und Pfeil braucht.
  const passt = await page.evaluate(() => {
    const feld = [...document.querySelectorAll('select')].find((s) => s.value === 'starttls')
    if (!feld) return { gefunden: false, passt: true, text: '', platz: 0, breite: 0 }
    const stil = getComputedStyle(feld)
    const messer = document.createElement('canvas').getContext('2d')!
    messer.font = `${stil.fontWeight} ${stil.fontSize} ${stil.fontFamily}`
    const text = feld.options[feld.selectedIndex].text
    const breite = messer.measureText(text).width
    const platz =
      feld.clientWidth - parseFloat(stil.paddingLeft) - parseFloat(stil.paddingRight)
    return { gefunden: true, passt: breite <= platz, text, platz, breite }
  })
  expect(passt.gefunden, 'Kein STARTTLS-Auswahlfeld gefunden').toBe(true)
  expect(
    passt.passt,
    `„${passt.text}" braucht ${Math.ceil(passt.breite)}px, hat ${Math.round(passt.platz)}px.`,
  ).toBe(true)
})

test('Platzhalter enthalten keine persönlichen Daten', async ({ page }) => {
  await zuEinstellungen(page)
  await page.getByRole('button', { name: 'Postfach hinzufügen' }).first().click()

  /* ⚠️ **Die verbotenen Wörter stehen nicht hier.**
     Ein Wächter, der die Namen mitliefert, die er verbieten soll, ist in einem
     öffentlichen Repo genau die Leckstelle, die er verhindern will. Sie liegen
     in `.veroeffentlichung-tabu` neben dem Projekt, und die Datei bleibt lokal.
     Fehlt sie, prüft der Test wenigstens die Formen — er schweigt nicht. */
  const verboten = tabuWoerter()
  const gefunden = await page.evaluate(
    (woerter) => {
      const treffer: string[] = []
      for (const feld of Array.from(document.querySelectorAll('input, textarea'))) {
        const platzhalter = (feld.getAttribute('placeholder') ?? '').toLowerCase()
        for (const wort of woerter) {
          if (platzhalter.includes(wort)) treffer.push(`${platzhalter} enthält ${wort}`)
        }
      }
      return treffer
    },
    verboten,
  )
  expect(
    gefunden,
    `Platzhalter mit persönlichen Daten — die sieht jeder Betreiber:\n  ${gefunden.join('\n  ')}`,
  ).toEqual([])
})

test('Regeln und Signaturen: Auswahllisten sind gefärbt, nichts läuft über', async ({ page }) => {
  await zuEinstellungen(page)

  for (const reiter of ['Regeln', 'Signaturen']) {
    await page.getByRole('tab', { name: reiter }).click()
    await expect(page.getByRole('button', { name: /Neue/ })).toBeVisible()
    await page.getByRole('button', { name: /Neue/ }).click()

    await auswahllistenSindGefaerbt(page)
    await keinTextLaeuftUeber(page)
    await keinSeitlichesScrollen(page)

    await page.getByRole('button', { name: 'Abbrechen' }).click()
  }
})

test('Keine Browser-Popups: Rückfragen laufen im eigenen Fenster', async ({ page }, info) => {
  // In der schmalen Ansicht steckt die Ordnerspalte in einer Schublade — der
  // Rechtsklick darauf wird dort eigens geprüft.
  test.skip(info.project.name === 'schmal', 'Ordnerspalte liegt hier in der Schublade.')
  // ⚠️ Ein `dialog`-Ereignis heißt: window.confirm/prompt/alert. Playwright
  // würde es sonst still wegklicken und der Test bestünde hohl.
  const browserkasten: string[] = []
  page.on('dialog', async (d) => {
    browserkasten.push(`${d.type()}: ${d.message().slice(0, 60)}`)
    await d.dismiss()
  })

  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Signaturen' }).click()
  await page.getByRole('button', { name: 'Neue Signatur' }).click()
  await page.getByRole('button', { name: 'Abbrechen' }).click()

  // Ordner anlegen — der frühere `window.prompt`.
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  const ordner = page.getByRole('button', { name: 'Posteingang' }).first()
  await rechtsklick(page, ordner)
  await page.getByRole('menuitem', { name: /Neuer Ordner/ }).click()

  await expect(
    page.getByRole('dialog'),
    'Es sollte ein eigenes Fenster erscheinen, kein Browser-Kasten.',
  ).toBeVisible()
  // Im Fenster suchen: „Abbrechen" steht auch im Betreff mancher echten Mail.
  await page.getByRole('dialog').getByRole('button', { name: 'Abbrechen' }).click()

  expect(browserkasten, `Browser-Popups aufgetreten:\n  ${browserkasten.join('\n  ')}`).toEqual([])
})

test('Unterordner stehen eingerückt unter ihrem Ordner', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Ordnerspalte liegt hier in der Schublade.')

  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** Die Spalte war flach: sortiert
     nach Rolle, dann nach Namen. Ein `INBOX/Rechnungen` bekam die Rolle
     „eigen" und landete damit ganz unten — weit weg von dem Ordner, in dem er
     liegt. Das sah aus wie ein Darstellungsfehler und war eine fehlende
     Funktion. */
  const absagen = serverabsagen(page)

  /* ⚠️ **Erst warten, bis der Baum steht.** Die Ordner kommen je Postfach
     einzeln nach; mit vier Postfächern, davon einem unerreichbaren, dauert
     das. Ohne dieses Warten scheiterte der Test im vollen Lauf gelegentlich
     und im einzelnen nie — die Sorte Flackern, die man zweimal wegerklärt
     und beim dritten Mal für einen echten Fehler hält. */
  await expect
    .poll(() => page.locator('section').filter({ hasText: 'Posteingang' }).count(), {
      message: 'Der Ordnerbaum steht nicht — läuft das Backend auf 8010 mit data-dev?',
      timeout: 25_000,
    })
    .toBeGreaterThan(1)

  // ⚠️ **Im Testpostfach anlegen, nicht im erstbesten** — siehe `postfach()`.
  const baum = postfach(page)
  const ordner = baum.getByRole('button', { name: 'Posteingang' }).first()
  await expect(ordner, `Das Postfach „${TESTPOSTFACH}" steht nicht im Baum.`).toBeVisible()
  await rechtsklick(page, ordner)
  await page.getByRole('menuitem', { name: /Neuer Unterordner/ }).click()

  const name = 'ZZ-Testordner'
  await page.getByRole('dialog').getByRole('textbox').fill(name)
  await page.getByRole('dialog').getByRole('button', { name: 'Anlegen' }).click()

  const neuer = baum.getByRole('button', { name, exact: true })
  // ⚠️ Zuerst die Ursache: Hat der Server den Ordner abgelehnt, ist „taucht
  // nicht auf" nur die Folge.
  await page.waitForTimeout(2500)
  await absagen.pruefen()
  await expect(neuer.first(), 'Der Unterordner taucht nicht auf.').toBeVisible({ timeout: 20_000 })

  const lage = await page.evaluate((n) => {
    // Nur die Ordnerzeilen des Baums, in ihrer echten Reihenfolge.
    const zeilen = Array.from(
      document.querySelectorAll<HTMLElement>('nav ~ * button, aside button, button'),
    ).filter((b) => b.textContent?.trim() && getComputedStyle(b).paddingLeft)
    const kind = zeilen.find((b) => b.textContent?.trim() === n)
    // Der Posteingang **desselben** Postfachs: der letzte vor dem Kind.
    const eltern = zeilen
      .slice(0, zeilen.indexOf(kind))
      .reverse()
      .find((b) => b.textContent?.trim().startsWith('Posteingang'))
    if (!kind || !eltern) return null
    return {
      einzugKind: parseFloat(getComputedStyle(kind).paddingLeft),
      einzugEltern: parseFloat(getComputedStyle(eltern).paddingLeft),
      // ⚠️ **Die Reihenfolge, nicht der Abstand in Pixeln.** „Direkt darunter"
      // heißt: kein anderer Ordner dazwischen — eine Pixelgrenze wäre eine
      // Wette auf die Zeilenhöhe.
      // Zwischen Eltern und Kind dürfen nur **Geschwister** stehen — also
      // Zeilen, die mindestens genauso tief eingerückt sind. Ein Ordner der
      // obersten Ebene dazwischen hieße: Das Kind hängt nicht am Elternteil.
      dazwischen: zeilen
        .slice(zeilen.indexOf(eltern) + 1, zeilen.indexOf(kind))
        .filter(
          (b) =>
            parseFloat(getComputedStyle(b).paddingLeft) <=
            parseFloat(getComputedStyle(eltern).paddingLeft),
        )
        .map((b) => b.textContent?.trim() ?? ''),
    }
  }, name)

  expect(lage, 'Ordner nicht gefunden').not.toBeNull()
  expect(
    lage!.einzugKind,
    'Der Unterordner ist nicht eingerückt — er steht auf derselben Ebene wie sein Ordner.',
  ).toBeGreaterThan(lage!.einzugEltern)
  expect(
    lage!.dazwischen,
    'Zwischen dem Posteingang und seinem Unterordner stehen Ordner einer höheren Ebene — das Kind hängt nicht am Elternteil.',
  ).toEqual([])

  // Aufräumen: Der Testordner darf nicht im echten Postfach zurückbleiben.
  await rechtsklick(page, neuer)
  await page.getByRole('menuitem', { name: 'Ordner entfernen' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Ordner entfernen' }).click()
  await expect(neuer).toHaveCount(0, { timeout: 20_000 })
})

test('Ein Postfach lässt sich bearbeiten, ohne das Passwort neu zu tippen', async ({ page }) => {
  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** Postfächer ließen sich nur
     anlegen und löschen. Und beim Bearbeiten ist die Falle das Passwortfeld:
     nexmail kann ein gespeichertes Passwort nicht anzeigen — leer muss also
     „unverändert" heißen, sonst verliert jeder seinen Zugang, der nur den
     Anzeigenamen ändert. */
  await zuEinstellungen(page)

  const bearbeiten = page.getByRole('button', { name: 'Bearbeiten' }).first()
  await expect(bearbeiten, 'Kein Weg zum Bearbeiten eines Postfachs.').toBeVisible()
  await bearbeiten.click()

  // Die Serverdaten stehen vorgeblendet da.
  const adresse = page.getByRole('textbox', { name: 'E-Mail-Adresse' })
  await expect(adresse).not.toHaveValue('')

  /* ⚠️ **Das Passwortfeld sieht belegt aus — und leert sich beim Anfassen.**
     Ein leeres Feld sah aus, als wäre nichts gespeichert; Anna hat es
     deshalb jedes Mal neu getippt. nexmail kann das Passwort nicht anzeigen
     (es liegt verschlüsselt), also stehen Punkte darin, bis jemand
     hineinklickt. */
  const passwort = page.locator('input[type="password"]').first()
  await expect(passwort, 'Das Feld sieht leer aus — als wäre nichts gespeichert.').not.toHaveValue(
    '',
  )
  await expect(page.getByText(/nexmail kann es nicht anzeigen/)).toBeVisible()

  await passwort.click()
  await expect(
    passwort,
    'Beim Hineinklicken muss das Feld leer werden — sonst tippt man in die Punkte hinein.',
  ).toHaveValue('')

  // Und der Knopf ist trotzdem freigegeben — ohne das könnte man nichts ändern.
  await expect(
    page.getByRole('button', { name: 'Änderungen speichern' }),
    'Der Speichern-Knopf ist gesperrt, obwohl nur das Passwortfeld leer ist.',
  ).toBeEnabled()

  await page.getByRole('button', { name: 'Abbrechen' }).click()
})

test('Reiter Sicherheit zeigt Geräte und Wiederherstellungscodes', async ({ page }) => {
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Sicherheit' }).click()

  await expect(page.getByText('Angemeldete Geräte')).toBeVisible()
  await expect(page.getByText(/Wiederherstellungscode/)).toBeVisible()
  // Die eigene Sitzung ist als solche gekennzeichnet und nicht kündbar —
  // sonst meldet man sich hier versehentlich selbst ab.
  await expect(page.getByText('dieses Gerät')).toBeVisible()

  await keinTextLaeuftUeber(page)
})

test('Reiter Darstellung wirkt wirklich auf die Liste', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Liste wird breit gemessen.')

  /* ⚠️ Eine Einstellung, die nichts tut, ist schlimmer als keine — der
     Betreiber stellt sie und sucht danach den Fehler bei sich. */
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  for (const name of ['Papierkorb', 'Archiv', 'Posteingang']) {
    const knopf = page.getByRole('button', { name }).first()
    if (await knopf.count()) {
      await knopf.click()
      await page.waitForTimeout(600)
      if (await page.locator('button[draggable="true"]').count()) break
    }
  }
  test.skip(!(await page.locator('button[draggable="true"]').count()), 'Keine Nachricht da.')

  const hoehe = async () =>
    (await page.locator('button[draggable="true"]').first().boundingBox())?.height ?? 0
  const normal = await hoehe()

  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('combobox', { name: /Dichte/ }).selectOption('kompakt')
  await page.getByRole('button', { name: 'Mail', exact: true }).click()
  await page.waitForTimeout(600)

  const kompakt = await hoehe()
  expect(kompakt, `Kompakt (${kompakt}px) ist nicht flacher als normal (${normal}px).`).toBeLessThan(
    normal,
  )

  // Zurückstellen, damit der nächste Lauf denselben Stand vorfindet.
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('combobox', { name: /Dichte/ }).selectOption('normal')
})

test('Jeder sichtbare Knopf hat einen Namen, den man vorlesen kann', async ({ page }) => {
  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** Das Benutzermenü oben rechts
     bestand schmal nur noch aus zwei `aria-hidden`-Symbolen — die Beschriftung
     ist ab `sm:` sichtbar. Für eine Vorlesehilfe war der einzige Weg zu den
     Einstellungen damit eine namenlose Schaltfläche. Aufgefallen ist es, weil
     der Test ihn nicht mehr fand; gefunden hätte es sonst niemand. */
  await jederKnopfHatEinenNamen(page)
})

test('Nirgends steht ein roher Übersetzungsschlüssel', async ({ page }) => {
  /* ⚠️ **Aus Schaden entstanden, 01.09.2026.** Auf der Einladungsseite stand
     „einrichtung.grund_passwort" als Satz da. i18next gibt bei einem
     unbekannten Schlüssel still den Schlüssel zurück — nichts schlägt fehl,
     und in einer Sprache, die man selbst nicht liest, fällt es nie auf. */
  await keineRohenSchluessel(page)

  await zuEinstellungen(page)
  for (const reiter of ['Postfächer', 'Regeln', 'Signaturen', 'Sicherheit', 'Darstellung']) {
    await page.getByRole('tab', { name: reiter }).click()
    await page.waitForTimeout(300)
    await keineRohenSchluessel(page)
  }
})
