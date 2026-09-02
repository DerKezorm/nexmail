/* „Senden rückholen" — der Aufschub mit Rückgängig.
 *
 * Der ganze Weg, nicht nur der Knopf: Aufschub in den Einstellungen
 * einschalten, senden, die Leiste mit der ablaufenden Zeit sehen, Rückgängig
 * klicken — und dann die Folge prüfen: Das Verfassen-Fenster steht wieder
 * offen, mit demselben Inhalt, und der Ausgang ist leer.
 *
 * ⚠️ **Der Test sendet wirklich — deshalb an example.com.** Geht das
 * Rückholen schief, landet die Mail bei niemandem; RFC 2606 reserviert die
 * Domain genau dafür. Und gesendet wird aus dem Testpostfach, nie aus einem
 * echten — siehe `postfach()` in den Hilfen.
 */
import { expect, test } from '@playwright/test'
import {
  TESTPOSTFACH,
  anmelden,
  postfach,
  serverabsagen,
  zuEinstellungen,
} from './hilfen'

test('Rückgängig holt die Nachricht zurück ins Fenster, der Ausgang ist leer', async ({
  page,
}, info) => {
  test.skip(
    info.project.name === 'schmal',
    'Der Ausgang wird an der Ordnerspalte geprüft — die liegt hier in der Schublade.',
  )

  const absagen = serverabsagen(page)
  await anmelden(page)

  /* 1. Aufschub einschalten — über die Einstellungen, nicht am Speicher
     vorbei. So ist mitgeprüft, dass die Einstellung existiert und wirkt;
     eine Einstellung, die nichts tut, ist schlimmer als keine. */
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Darstellung' }).click()
  await page.getByRole('combobox', { name: /Senden rückholen/ }).selectOption('30')
  await page.getByRole('button', { name: 'Mail', exact: true }).click()

  /* 2. Verfassen — mit einem Betreff, den kein liegen gebliebener Rest eines
     früheren Laufs tragen kann. */
  const betreff = `ZZ-Rückholprobe ${Date.now()}`
  const text = 'Dieser Text muss nach dem Rückholen wieder im Fenster stehen.'

  await page.getByRole('button', { name: 'Neue Nachricht' }).first().click()
  const fenster = page.getByRole('dialog', { name: 'Neue Nachricht' })
  await expect(fenster).toBeVisible()

  // ⚠️ Erst kurz warten: Die Signatur des vorausgewählten Postfachs kommt
  // asynchron und **ersetzt** den Editorinhalt — wer sofort tippt, verliert
  // den Text an sie und prüft danach gegen ein leeres Feld.
  await page.waitForTimeout(1000)

  const von = fenster.locator('select').first()
  const eintrag = von.locator('option').filter({ hasText: TESTPOSTFACH }).first()
  await expect(
    eintrag,
    `Das Testpostfach „${TESTPOSTFACH}" fehlt in der Von-Auswahl.`,
  ).toHaveCount(1)
  await von.selectOption((await eintrag.getAttribute('value')) ?? '')

  await fenster.getByPlaceholder('Name oder Adresse').first().fill('rueckholprobe@example.com')
  await fenster.getByPlaceholder('Betreff').fill(betreff)
  await fenster.locator('[contenteditable="true"]').first().click()
  await page.keyboard.type(text)

  await fenster.getByRole('button', { name: 'Senden', exact: true }).click()

  /* 3. Die Leiste steht da, die Zeit läuft ab, die Nachricht liegt im
     Ausgang — sichtbar an der Zeile in der Ordnerspalte. */
  const leiste = page.getByRole('status').filter({ hasText: /Wird in \d+ s gesendet/ })
  await expect(leiste, 'Die Rückhol-Leiste erscheint nicht.').toBeVisible({ timeout: 10_000 })
  await expect(fenster).toBeHidden()
  await expect(page.getByRole('button', { name: /Postausgang/ })).toBeVisible({
    timeout: 10_000,
  })

  // Ablaufend heißt: Die Zahl ändert sich — eine stehende Uhr verspricht
  // Zeit, die es nicht gibt.
  const stand = await leiste.locator('span').innerText()
  await page.waitForTimeout(2000)
  const danach = await leiste.locator('span').innerText()
  expect(danach, `Die Zeit in der Leiste läuft nicht ab — sie steht auf „${stand}".`).not.toBe(
    stand,
  )

  /* 4. Rückgängig. Der Abbruch legt den Inhalt übers echte Postfach als
     Entwurf ab, das dauert — großzügig warten, und zuerst die Ursache
     prüfen: Hat der Server abgesagt, ist das fehlende Fenster nur die Folge. */
  await leiste.getByRole('button', { name: 'Rückgängig' }).click()

  const wieder = page.getByRole('dialog', { name: 'Neue Nachricht' })
  await expect(wieder, 'Das Verfassen-Fenster kommt nicht wieder.').toBeVisible({
    timeout: 30_000,
  })
  await absagen.pruefen()

  // ⚠️ Die Folge, nicht der Klick: Der Inhalt steht wieder drin …
  await expect(wieder.getByPlaceholder('Betreff')).toHaveValue(betreff)
  await expect(wieder.locator('[contenteditable="true"]').first()).toContainText(text)
  // ⚠️ Seit den Adress-Blasen (02.09.2026) steht ein fertiger Empfänger
  // nicht mehr IM Eingabefeld, sondern als Blase davor - geprüft wird
  // die Blase, nicht der Feldwert.
  await expect(
    wieder.getByRole('button', { name: /rueckholprobe@example\.com entfernen|Remove rueckholprobe/ }),
  ).toBeVisible()

  // … und der Ausgang ist leer: Die Zeile verschwindet, wenn nichts wartet.
  await expect(page.getByRole('button', { name: /Postausgang/ })).toHaveCount(0, {
    timeout: 20_000,
  })

  /* 5. Das wieder geöffnete Fenster hängt an der UID des Sicherheits-Entwurfs,
     den der Abbruch abgelegt hat — „Verwerfen" räumt ihn deshalb **selbst**
     ab. Vorher kannte der Client die UID nicht, und jedes „Rückgängig"
     hinterließ für immer eine Fassung im Entwurfsordner; dieser Schritt war
     das Aufräumen von Hand, jetzt ist er die Probe. */
  await wieder.getByRole('button', { name: 'Verwerfen' }).click()
  await expect(wieder).toBeHidden()

  const baum = postfach(page)
  const entwuerfe = baum.getByRole('button', { name: /Entwürfe|Drafts/ }).first()
  await entwuerfe.click()
  // Erst sicherstellen, dass der Ordner wirklich geladen wurde — ein „nichts
  // da" wegen eines nie geladenen Ordners sähe genauso aus wie der Erfolg.
  await expect(entwuerfe).toHaveAttribute('aria-current', 'true')
  const zeile = page.locator('button[draggable="true"]').filter({ hasText: betreff })
  await expect(
    zeile,
    'Der Sicherheits-Entwurf liegt noch im Entwurfsordner — die UID aus dem Abbruch kam nicht im Fenster an.',
  ).toHaveCount(0, { timeout: 20_000 })

  await absagen.pruefen()
})
