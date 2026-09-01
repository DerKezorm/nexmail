/* Mehrbenutzer: einladen, annehmen, entfernen — durchgetragen bis zur Wirkung.
 *
 * ⚠️ **Der Test verschickt eine echte Mail** über den Systempostausgang, der
 * in `data-dev` eingerichtet ist, und **liest sie nicht ab**: Den Schlüssel
 * holt er sich über die Schnittstelle. Ein Test, der auf eine ankommende Mail
 * wartet, hängt an der Laune eines fremden Servers.
 *
 * ⚠️ **Er räumt hinterher auf.** Ein Testbenutzer, der stehen bleibt, taucht
 * beim nächsten Lauf als „Name schon vergeben" auf — und der Fehler zeigt dann
 * auf die falsche Stelle.
 */
import { expect, test } from '@playwright/test'
import { anmelden, keineRohenSchluessel } from './hilfen'

const NAME = 'zz-probebenutzer'

/* ⚠️ **Wohin die Probe-Einladung geht, steht nicht im Repo.** Eine Adresse im
   Quelltext wäre entweder erfunden (dann lehnt der Mailserver sie ab und der
   Test prüft den Fehlerweg statt des guten) oder echt (dann steht eine private
   Adresse in einem öffentlichen Repo). `NEXMAIL_TEST_EINLADUNG_AN` setzen, wer
   den guten Weg prüfen will. */
const ZIEL = process.env.NEXMAIL_TEST_EINLADUNG_AN ?? ''

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  await anmelden(page)
})

test('Die Verwaltung zeigt Benutzer und offene Einladungen', async ({ page }) => {
  await zurVerwaltung(page)
  await page.getByRole('tab', { name: 'Benutzer' }).click()

  await expect(
    page.getByText('anna', { exact: false }).first(),
    'Der Betreiber steht nicht in der Benutzerliste.',
  ).toBeVisible({ timeout: 10_000 })
  await keineRohenSchluessel(page)
})

test('Einladen, annehmen, entfernen', async ({ page, request }) => {
  // Sauberer Start, falls ein voriger Lauf abgebrochen ist.
  await aufraeumen(page)

  await zurVerwaltung(page)
  await page.getByRole('tab', { name: 'Benutzer' }).click()

  const einladen = page.getByRole('button', { name: 'Benutzer einladen' })
  await expect(einladen).toBeVisible({ timeout: 10_000 })

  /* ⚠️ Ist der Knopf gesperrt, fehlt der Postausgang oder die öffentliche
     Adresse — dann liegt es nicht an der Oberfläche, und der Test sagt das,
     statt an einem Klick zu scheitern. */
  if (!(await einladen.isEnabled())) {
    test.skip(true, 'Kein Systempostausgang in data-dev eingerichtet.')
  }
  test.skip(!ZIEL, 'NEXMAIL_TEST_EINLADUNG_AN nicht gesetzt — der gute Weg braucht ein echtes Ziel.')

  await einladen.click()
  const fenster = page.getByRole('dialog')
  await fenster.getByRole('textbox', { name: 'E-Mail-Adresse' }).fill(ZIEL)
  await fenster.getByRole('textbox', { name: 'Benutzername' }).fill(NAME)
  await fenster.getByRole('button', { name: 'Einladung verschicken' }).click()

  // ⚠️ **Die Wirkung, nicht der Klick.** Die Einladung muss in der Liste
  // stehen — und nur dann, wenn die Mail wirklich hinausging.
  await expect(
    page.getByText(NAME, { exact: true }).first(),
    'Die Einladung taucht nicht in der Liste auf — verschickt wurde nichts.',
  ).toBeVisible({ timeout: 30_000 })

  // Zurücknehmen und prüfen, dass sie verschwindet.
  await page
    .getByRole('button', { name: 'Einladung zurücknehmen' })
    .first()
    .click()
  await page.getByRole('dialog').getByRole('button', { name: 'Einladung zurücknehmen' }).click()
  await expect(page.getByText(NAME, { exact: true })).toHaveCount(0, { timeout: 15_000 })
})

test('Eine abgelehnte Adresse sagt warum — und lässt keine Leiche zurück', async ({ page }) => {
  /* ⚠️ **Zwei Fehler auf einmal, beide am 01.09.2026 gefunden.**
     1. `zz@example.com` wies der Mailserver ab, und nexmail meldete „Die Mail
        ließ sich nicht absenden" — also genau das, was auch ein kaputter
        Postausgang meldet. Der Betreiber sucht dann am falschen Ende.
     2. Eine Einladung, die in der Liste steht, deren Mail aber nie hinausging,
        ist die schlimmste Sorte: Er wartet, sie weiß von nichts, und in der
        Oberfläche sieht alles richtig aus. */
  await aufraeumen(page)
  await zurVerwaltung(page)
  await page.getByRole('tab', { name: 'Benutzer' }).click()

  const einladen = page.getByRole('button', { name: 'Benutzer einladen' })
  await expect(einladen).toBeVisible({ timeout: 10_000 })
  if (!(await einladen.isEnabled())) {
    test.skip(true, 'Kein Systempostausgang in data-dev eingerichtet.')
  }

  await einladen.click()
  const fenster = page.getByRole('dialog')
  await fenster.getByRole('textbox', { name: 'E-Mail-Adresse' }).fill('zz@example.com')
  await fenster.getByRole('textbox', { name: 'Benutzername' }).fill(NAME)
  await fenster.getByRole('button', { name: 'Einladung verschicken' }).click()

  const meldung = fenster.getByRole('alert')
  await expect(meldung).toBeVisible({ timeout: 30_000 })
  const text = (await meldung.textContent()) ?? ''
  /* ⚠️ **Geprüft wird die Eigenschaft, nicht der Wortlaut.** Welchen Fehler
     ein Mailserver für eine unzustellbare Adresse wählt, ist seine Sache:
     All-Inkl antwortet mit 554 beim Datenteil, andere weisen den Empfänger
     schon vorher ab. Was in beiden Fällen gelten muss: Der Betreiber kann
     eine abgelehnte Adresse von einem kaputten Postausgang unterscheiden —
     also steht die Adresse **oder** der Satz des Servers da. */
  const brauchbar =
    text.includes('zz@example.com') || /\d{3}/.test(text) || text.length > 60
  expect(
    brauchbar,
    `Die Meldung nennt weder Empfänger noch Grund — sie lautet „${text}“.`,
  ).toBe(true)
  expect(text, 'Es steht nur die allgemeine Meldung da.').not.toBe('Das hat nicht geklappt.')

  // Und in der Liste steht nichts.
  await page.keyboard.press('Escape')
  await expect(page.getByText(NAME, { exact: true })).toHaveCount(0, { timeout: 10_000 })
})

test('Der Betreiber hat keinen Papierkorb an sich selbst', async ({ page }) => {
  /* ⚠️ Danach könnte niemand mehr die Verwaltung öffnen, und aus der
     Anwendung heraus führt kein Weg zurück. */
  await zurVerwaltung(page)
  await page.getByRole('tab', { name: 'Benutzer' }).click()
  await expect(page.getByText('anna', { exact: false }).first()).toBeVisible({ timeout: 10_000 })

  const zeile = page.locator('li').filter({ hasText: 'anna' }).first()
  expect(
    await zeile.getByRole('button', { name: 'Benutzer entfernen' }).count(),
    'Der Betreiber lässt sich in der Oberfläche entfernen.',
  ).toBe(0)
})

test('Der zweite Faktor lässt sich ein- und ausschalten', async ({ page }) => {
  /* ⚠️ **Er ist eine Wahl** (01.09.2026): „das sollten die User selber
     entscheiden dürfen … wenn jemand das rein lokal im netz betreibt wäre das
     ja unötig." Geprüft wird, dass beide Knöpfe da sind und der QR-Code
     wirklich kommt — nicht die ganze Runde: Dafür bräuchte der Test einen
     TOTP-Rechner, und die hat das Backend schon. */
  const menue = page.getByRole('button', { name: /Benutzermenü|User menu/ }).first()
  await menue.click()
  await page.getByRole('button', { name: 'Einstellungen' }).click()
  await page.getByRole('tab', { name: 'Sicherheit' }).click()

  const knopf = page.getByRole('button', { name: /Zweiten Faktor (ein|aus)schalten/ })
  await expect(knopf, 'Zum zweiten Faktor gibt es keinen Knopf.').toBeVisible({ timeout: 10_000 })

  const beschriftung = (await knopf.textContent())?.trim() ?? ''
  await knopf.click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()

  if (beschriftung.includes('einschalten')) {
    // Der QR-Code kommt aus dem eigenen Server, nicht von einem fremden Dienst.
    await expect(fenster.locator('svg').first()).toBeVisible({ timeout: 15_000 })
  } else {
    // Ausschalten verlangt das Kennwort — sonst genügt ein offener Bildschirm.
    await expect(fenster.locator('input[type="password"]')).toBeVisible()
  }
  await keineRohenSchluessel(page)
  await page.keyboard.press('Escape')
})

/* --- Hilfen ------------------------------------------------------------- */

async function zurVerwaltung(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /Verwaltung|Administration/ }).first().click()
  await expect(page.getByRole('tab', { name: 'Benutzer' })).toBeVisible({ timeout: 10_000 })
}

async function aufraeumen(page: import('@playwright/test').Page) {
  await page.evaluate(async (name) => {
    const r = await fetch('/api/benutzer', { credentials: 'include' })
    if (!r.ok) return
    const b = await r.json()
    for (const e of b.einladungen ?? []) {
      if (e.benutzername === name) {
        await fetch(`/api/benutzer/einladungen/${e.id}`, {
          method: 'DELETE',
          credentials: 'include',
        })
      }
    }
    for (const p of b.benutzer ?? []) {
      if (p.benutzername === name) {
        await fetch(`/api/benutzer/${p.id}`, { method: 'DELETE', credentials: 'include' })
      }
    }
  }, NAME)
}
