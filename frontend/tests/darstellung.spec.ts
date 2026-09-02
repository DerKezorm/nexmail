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

  // ⚠️ Der Knopf heißt je Reiter anders — und im Reiter Signaturen stehen
  // seit den Textvorlagen ZWEI „Neue …"-Knöpfe. Ein /Neue/-Muster träfe beide.
  for (const [reiter, knopf] of [
    ['Regeln', 'Neue Regel'],
    ['Signaturen', 'Neue Signatur'],
  ] as const) {
    await page.getByRole('tab', { name: reiter }).click()
    await expect(page.getByRole('button', { name: knopf })).toBeVisible()
    await page.getByRole('button', { name: knopf }).click()

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

test('Der Pfeil einer Auswahl gehört zum Klickziel', async ({ page }) => {
  /* ⚠️ Der Chevron ist ein Geschwister des <select>. Ohne pointer-events-none
     fing ER den Klick — die Liste klappte nur auf, wenn man den TEXT traf.
     An jeder Auswahl der Anwendung, denn alle nutzen denselben Baustein.
     Aufgefallen am 02.09.2026 an der Protokoll-Ausführlichkeit. */
  await anmelden(page)
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()

  const treffer = await page.evaluate(() => {
    const schlecht: string[] = []
    for (const sel of Array.from(document.querySelectorAll('select'))) {
      // Erst ins Bild holen: elementFromPoint sieht nur den sichtbaren
      // Ausschnitt. Ohne das meldete der Test die zwei Auswahlfelder
      // unterhalb der Falz als kaputt - mit undefined als Treffer.
      sel.scrollIntoView({ block: 'center' })
      const r = sel.getBoundingClientRect()
      if (r.width === 0) continue
      const oben = document.elementFromPoint(r.right - 10, r.top + r.height / 2)
      if (oben !== sel) {
        schlecht.push(`${sel.closest('label')?.textContent?.slice(0, 30) ?? '?'} → ${oben?.tagName}`)
      }
    }
    return schlecht
  })
  expect(treffer, 'Unter dem Pfeil liegt nicht die Auswahl: ' + treffer.join(', ')).toEqual([])
})

test('Der Kopf über der Liste schneidet nichts ab', async ({ page }) => {
  /* ⚠️ **Der eigentliche Fehler stand in einer Zeile.** Ordnername, Zahlen und
     drei Bedienelemente nebeneinander: Sobald die Spalte schmaler wurde, blieb
     „Alle Pos…" und „Alle S…" übrig. Am 02.09.2026 gemeldet.

     ⚠️ **`keinTextLaeuftUeber` hätte es nie gefunden** — es überspringt alles
     mit `text-overflow: ellipsis`, und genau das war der Ordnername. Ein
     `<select>` beschneidet seinen Text ohnehin lautlos. Gemessen wird deshalb
     hier von Hand: die Breite, die der Text wirklich braucht. */
  await anmelden(page)

  const zu_eng = await page.evaluate(() => {
    function breite(el: HTMLElement, text: string) {
      const stil = getComputedStyle(el)
      const flaeche = document.createElement('canvas').getContext('2d')
      if (!flaeche) return 0
      flaeche.font = `${stil.fontWeight} ${stil.fontSize} ${stil.fontFamily}`
      return flaeche.measureText(text).width
    }

    const schlecht: string[] = []

    const titel = document.querySelector<HTMLElement>('h2.truncate')
    if (titel && titel.scrollWidth > titel.clientWidth + 1) {
      schlecht.push(`Ordnername „${titel.textContent}" braucht ${titel.scrollWidth}px, hat ${titel.clientWidth}px`)
    }

    for (const sel of Array.from(document.querySelectorAll('select'))) {
      const gewaehlt = sel.options[sel.selectedIndex]?.text ?? ''
      const stil = getComputedStyle(sel)
      const platz =
        sel.clientWidth - parseFloat(stil.paddingLeft) - parseFloat(stil.paddingRight)
      const noetig = breite(sel, gewaehlt)
      if (noetig > platz + 1) {
        schlecht.push(`Auswahl „${gewaehlt}" braucht ${Math.round(noetig)}px, hat ${Math.round(platz)}px`)
      }
    }
    return schlecht
  })

  expect(zu_eng, 'Im Kopf über der Liste wird abgeschnitten:\n  ' + zu_eng.join('\n  ')).toEqual([])
})

test('Schlagworte sind Rechtecke, Postfächer sind Punkte', async ({ page }) => {
  /* ⚠️ **Zwei gleiche Formen für zwei verschiedene Dinge liest man falsch.**
     Am 02.09.2026 gemeldet: „Der Kreis für die Schlagworte ist doof. Mach
     daraus Rechtecke. Sonst verwechselt man es mit den Kreis, die für ein
     Postfach stehen." In einer Listenzeile stehen beide nebeneinander. */
  await anmelden(page)

  /* Eine Marke ist ein leerer Kasten mit Farbe. Das „!" für Wichtigkeit ist
     ebenfalls `role="img"`, trägt aber Text — sonst prüfte der Test dessen
     Form. ⚠️ Und die Liste kommt nachgeladen: erst warten, dann messen, nie
     eine feste Wartezeit. */
  const messen = () =>
    page.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="img"]'))
        .filter((el) => {
          if ((el.textContent ?? '').trim() !== '' || el.querySelector('svg')) return false
          const grund = getComputedStyle(el).backgroundColor
          return el.clientWidth > 0 && grund !== 'rgba(0, 0, 0, 0)' && grund !== 'transparent'
        })
        .map((el) => ({
          name: el.getAttribute('aria-label') ?? '',
          breit: el.clientWidth,
          hoch: el.clientHeight,
          radius: getComputedStyle(el).borderTopLeftRadius,
        })),
    )

  await expect
    .poll(async () => (await messen()).length, {
      message: 'Keine Schlagwortmarke in der Liste gefunden',
    })
    .toBeGreaterThan(0)
  const marken = await messen()
  for (const m of marken) {
    expect(m.breit, `„${m.name}" ist nicht breiter als hoch`).toBeGreaterThan(m.hoch)
    // Ein Kreis hätte hier den halben Kasten oder 9999px stehen.
    expect(parseFloat(m.radius), `„${m.name}" ist rund statt eckig`).toBeLessThan(m.hoch / 2)
  }
})

test('Der Lesebereich hat keinen toten Raum unter der Mail', async ({ page }) => {
  /* ⚠️ **Am 02.09.2026 gemeldet und gemessen:** Der Rahmen war 420 px hoch,
     die Mail darin brauchte 1432 px, und der Bereich aussen rollte gar nicht.
     Jede Mail steckte damit in einem Fenster mit eigenem Rollbalken, darunter
     standen 336 px Nichts. Ein `<iframe>` waechst nie von selbst mit seinem
     Inhalt — die Hoehe muss gemessen und gesetzt werden.

     Die Nachricht kommt gestellt, damit der Test nicht davon abhaengt, was
     gerade im Postfach liegt. */
  const HOCH = '<div style="height:1200px">lang</div>'
  const KURZ = '<p>kurz</p>'
  await page.route(/\/api\/nachrichten\/\d+$/, async (route) => {
    const a = await route.fetch()
    const d = await a.json()
    await route.fulfill({ json: { ...d, html: page.url().includes('#kurz') ? KURZ : HOCH } })
  })

  await anmelden(page)
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible()
  await zeilen.first().click()
  await expect(page.locator('article h1').first()).toBeVisible()

  const passt = async () =>
    page.evaluate(() => {
      const r = document.querySelector('iframe') as HTMLIFrameElement
      const d = r.contentDocument
      if (!d?.body) return null
      return { rahmen: Math.round(r.getBoundingClientRect().height), inhalt: d.body.scrollHeight }
    })

  await expect
    .poll(async () => {
      const m = await passt()
      return m ? Math.abs(m.rahmen - m.inhalt) : 9999
    }, { message: 'Der Rahmen ist nicht so hoch wie die Mail.' })
    .toBeLessThanOrEqual(2)

  const m = await passt()
  expect(m!.inhalt, 'Die gestellte Mail sollte lang sein').toBeGreaterThan(1000)
})

test('Im Rahmen steht immer die Mail, die oben im Kopf steht', async ({ page }, info) => {
  /* ⚠️ **Nur breit.** In der schmalen Ansicht ersetzt die geöffnete Mail die
     Liste — nach dem ersten Klick gibt es keine zweite Zeile mehr zum
     Weiterklicken. Der Test prüfte dort nicht weniger, sondern lief ins
     Leere. Am 02.09.2026 im Release-Lauf aufgefallen. */
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  /* ⚠️ **Am 02.09.2026 aus dem Betrieb gemeldet:** Oben stand eine Mail, im
     Rahmen darunter eine andere. Die Druckansicht — die der Server aus dem
     gespeicherten Rumpf baut — zeigte die richtige. Die Daten stimmten also,
     die Anzeige nicht.

     Dieser Waechter war vorher gar nicht moeglich: Der Rahmen lief mit
     `sandbox=""`, und in ein Dokument mit fremder Herkunft sieht auch ein
     Test nicht hinein. Seit der Rahmen `allow-same-origin` traegt, geht es.

     ⚠️ **Und er ist KEIN Beweis, dass der gemeldete Fehler behoben ist.**
     Gegen beide Behebungen mutiert (Rahmen ohne `key`, spaete Bilder-Antwort
     ohne Wache) bleibt er gruen — der Fehler liess sich hier nie ausloesen,
     und was man nicht ausloesen kann, faengt kein Test. Er haelt die Regel
     fest, nicht die Behebung: Im Rahmen steht die gewaehlte Mail. Wer ihn
     spaeter gruen sieht, weiss damit nur, dass der Normalfall stimmt.

     Jede Mail bekommt einen eindeutigen Rumpf, und zwischendurch wird
     „Bilder anzeigen" gedrueckt — das war der Weg, auf dem eine zu spaet
     eintreffende Antwort einen fremden Rumpf in den Rahmen setzen konnte. */
  await page.route(/\/api\/nachrichten\/(\d+)$/, async (route) => {
    const id = /\/(\d+)$/.exec(route.request().url())![1]
    const a = await route.fetch()
    const d = await a.json()
    await route.fulfill({
      json: {
        ...d,
        html: `<p>RUMPF-${id}</p>`,
        geblockte_bilder: 1,
        absender_freigegeben: false,
      },
    })
  })
  await page.route(/\/api\/nachrichten\/(\d+)\/bilder$/, async (route) => {
    const id = /\/(\d+)\/bilder$/.exec(route.request().url())![1]
    await route.fulfill({ json: { html: `<p>RUMPF-${id}</p>` } })
  })

  await anmelden(page)
  const zeilen = page.locator('button[draggable="true"]')
  await expect(zeilen.first()).toBeVisible()
  const wieviele = Math.min(await zeilen.count(), 5)
  expect(wieviele, 'Zu wenige Nachrichten zum Durchklicken').toBeGreaterThan(1)

  const rumpf = () => page.frameLocator('iframe').first().locator('body')

  for (let i = 0; i < wieviele; i++) {
    await zeilen.nth(i).click()
    await expect(page.locator('article h1').first()).toBeVisible()

    // Welche Kennung hat der Server fuer diese Zeile geliefert? Genau die muss
    // im Rahmen stehen.
    await expect
      .poll(async () => (await rumpf().innerText().catch(() => '')).trim(), {
        message: 'Der Rahmen zeigt nicht den Rumpf der gewaehlten Mail.',
      })
      .toMatch(/^RUMPF-\d+$/)
    const imRahmen = (await rumpf().innerText()).trim()

    // Zwischendurch die Bilder anfordern und sofort weiterklicken — der Weg,
    // auf dem eine spaete Antwort frueher einen fremden Rumpf gesetzt hat.
    const knopf = page.getByRole('button', { name: 'Bilder anzeigen' })
    if (await knopf.count()) await knopf.click()

    const naechste = i + 1
    if (naechste < wieviele) {
      await zeilen.nth(naechste).click()
      await expect(page.locator('article h1').first()).toBeVisible()
      await expect
        .poll(async () => (await rumpf().innerText().catch(() => '')).trim(), {
          message: 'Nach dem Weiterklicken steht noch der alte Rumpf im Rahmen.',
        })
        .not.toBe(imRahmen)
      await zeilen.nth(i).click()
    }
  }
})


test('Eine Mail mit eigener Schriftfarbe wird nicht unlesbar', async ({ page }) => {
  /* ⚠️ **Am 02.09.2026 gemessen, bevor es das gab:** Eine Mail mit
     `color:#333` und ohne eigenen Grund stand im Dunkelmodus mit Kontrast
     **1,53:1** da. Lesbar waere ab 4,5. Es sind ausgerechnet die schlichten
     Geschaeftsmails, und man sieht der Anzeige den Grund nicht an.

     Die Regel dahinter ist ganz oder gar nicht je Mail: Sagt die Mail
     irgendetwas ueber Farbe, bekommt sie den hellen Grund, mit dem sie
     rechnet. Sagt sie nichts, traegt sie die Farben der Anwendung. */
  const FAELLE = [
    { name: 'nur Schriftfarbe', html: '<div style="color:#333333"><p>Text</p></div>', faerbt: true },
    { name: 'malt sich selbst', html: '<table bgcolor="#ffffff"><tr><td style="color:#222"><p>Text</p></td></tr></table>', faerbt: true },
    { name: 'ohne eigene Farben', html: '<p>Text</p>', faerbt: false },
    /* ⚠️ **Der Fall, den die erste Fassung des Tests nicht hatte.** Die
       Mail setzt einen hellen Grund, aber keine Schriftfarbe — der Text
       erbt sie dann vom Rahmen. Nimmt der Rahmen dort die helle Schrift
       der Anwendung, steht Hellgrau auf Weiss. Die Mutationsprobe hat
       genau das aufgedeckt. */
    { name: 'nur Grund, keine Schrift', html: '<table bgcolor="#ffffff"><tr><td><p>Text</p></td></tr></table>', faerbt: true },
  ]

  await anmelden(page)
  for (const fall of FAELLE) {
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    await page.route(/\/api\/nachrichten\/\d+$/, async (route) => {
      const a = await route.fetch()
      const d = await a.json()
      await route.fulfill({
        json: { ...d, html: fall.html, geblockte_bilder: 0, faerbt_sich_selbst: fall.faerbt },
      })
    })
    await page.reload()
    const zeilen = page.locator('button[draggable="true"]')
    await expect(zeilen.first()).toBeVisible()
    await zeilen.first().click()
    await expect(page.locator('article h1').first()).toBeVisible()

    const kontrast = await page.evaluate(() => {
      const leuchte = (c: string) => {
        const [r, g, b] = c.match(/\d+/g)!.slice(0, 3).map((n) => Number(n) / 255)
        const f = (x: number) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4)
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
      }
      const r = document.querySelector('iframe') as HTMLIFrameElement
      const d = r.contentDocument!
      const p = d.querySelector('p')!
      // Den ersten undurchsichtigen Grund suchen; ist keiner da, gilt der
      // Grund der Anwendung hinter dem Rahmen.
      let el: HTMLElement | null = p
      let grund = ''
      while (el) {
        const g = getComputedStyle(el).backgroundColor
        if (g && g !== 'rgba(0, 0, 0, 0)') { grund = g; break }
        el = el.parentElement
      }
      if (!grund) grund = getComputedStyle(document.body).backgroundColor
      const a = leuchte(getComputedStyle(p).color)
      const b = leuchte(grund)
      const [hoch, tief] = a > b ? [a, b] : [b, a]
      return (hoch + 0.05) / (tief + 0.05)
    })

    expect(kontrast, `„${fall.name}" ist im Dunkelmodus zu blass`).toBeGreaterThan(4.5)
  }
})
