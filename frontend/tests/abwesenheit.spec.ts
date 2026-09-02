/* Die Abwesenheitsnotiz in der Oberfläche.
 *
 * ⚠️ **Ein Test hört nicht am Knopf auf.** Geprüft wird die Wirkung: Was
 * eingeschaltet wurde, muss ein Neuladen überstehen — eine Einstellung, die
 * nur so aussieht, als sei sie gespeichert, ist die schlimmste Sorte.
 */
import { expect, test } from '@playwright/test'
import { anmelden, zuEinstellungen, jederKnopfHatEinenNamen, keinTextLaeuftUeber } from './hilfen'

async function zurAbwesenheit(page) {
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Abwesenheit' }).click()
  await expect(page.getByText(/beantwortet Post nur, solange/)).toBeVisible()
}

test.afterEach(async ({ page }) => {
  /* Hinterher wieder ausschalten. Ein Testlauf, der eine Abwesenheitsnotiz
     angeschaltet zurücklässt, verschickt echte Post an echte Leute. */
  try {
    await zurAbwesenheit(page)
    const schalter = page.getByRole('switch').first()
    if ((await schalter.getAttribute('aria-checked')) === 'true') {
      await schalter.click()
      await page.getByRole('button', { name: 'Speichern' }).first().click()
    }
  } catch {
    // Der Test ist vorbei; ein Aufräumfehler soll ihn nicht rot machen.
  }
})

test('Der Warnbalken steht da, bevor man etwas einschaltet', async ({ page }) => {
  /* ⚠️ nexmail antwortet nur, solange nexmail läuft. Wer es stoppt, soll es
     vorher wissen — nicht dann, wenn niemand eine Antwort bekam.

     ⚠️ **„Der Rechner" stand hier bis zum 02.09.2026 und war mehrdeutig:** Bei
     einem Server im Haus denkt man an den Laptop, von dem aus man ihn bedient,
     und lässt den an. Am 02.09.2026 aus dem Betrieb gemeldet. */
  await anmelden(page)
  await zurAbwesenheit(page)
  await expect(page.getByText(/nicht dein Rechner, sondern nexmail/)).toBeVisible()
  await keinTextLaeuftUeber(page)
  await jederKnopfHatEinenNamen(page)
})

test('Ohne Text lässt sie sich nicht einschalten', async ({ page }) => {
  /* Eine leere Abwesenheitsnotiz ist schlimmer als keine: Der Empfänger
     denkt, er habe etwas kaputtgemacht. Die Kennung des Servers wird
     übersetzt, nicht roh gezeigt. */
  await anmelden(page)
  await zurAbwesenheit(page)

  /* ⚠️ **Den Zustand herstellen, nicht vorfinden.** Ein voriger Lauf kann
     einen Text hinterlassen haben; dann ginge das Einschalten durch und der
     Test prüfte nichts. */
  const schalter = page.getByRole('switch').first()
  if ((await schalter.getAttribute('aria-checked')) !== 'true') await schalter.click()
  await page.getByLabel('Text').fill('')
  await page.getByRole('button', { name: 'Speichern' }).first().click()

  await expect(page.getByText(/Ohne Text keine Notiz/)).toBeVisible()
  await expect(page.getByText('abwesenheit_ohne_text')).toHaveCount(0)
  // Und eingeschaltet ist danach nichts.
  await expect(page.getByRole('switch').first()).toHaveAttribute('aria-checked', 'false')
})

test('Einschalten, Text setzen, Neuladen überstehen', async ({ page }) => {
  await anmelden(page)
  await zurAbwesenheit(page)

  await page.getByRole('switch').first().click()
  await page.getByLabel('Betreff').fill('Bin bis Montag weg')
  await page.getByLabel('Text').fill('Ich bin ab Montag wieder da.')
  await page.getByRole('button', { name: 'Speichern' }).first().click()

  // Die Folge: Der Zustand kommt vom Server zurück, das Abzeichen erscheint.
  await expect(page.getByText(/^(Läuft|Aktiv bis|Außerhalb des Zeitraums)/).first()).toBeVisible()

  await page.reload()
  await zurAbwesenheit(page)
  await expect(page.getByRole('switch').first()).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByLabel('Betreff')).toHaveValue('Bin bis Montag weg')
  await expect(page.getByLabel('Text')).toHaveValue('Ich bin ab Montag wieder da.')
})

test('Ein verdrehter Zeitraum wird abgewiesen', async ({ page }) => {
  await anmelden(page)
  await zurAbwesenheit(page)

  await page.getByRole('switch').first().click()
  await page.getByLabel('Text').fill('Bin weg.')
  await page.getByLabel('Von').fill('2026-09-14')
  await page.getByLabel('Bis einschließlich').fill('2026-09-05')
  await page.getByRole('button', { name: 'Speichern' }).first().click()

  await expect(page.getByText(/Das Ende liegt vor dem Anfang/)).toBeVisible()
})
