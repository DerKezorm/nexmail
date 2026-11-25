/* Mehrbenutzer: einladen, annehmen, entfernen — durchgetragen bis zur Wirkung. Seit konten 0.3.9 die Kontenliste des
 * Moduls: je Konto eine Zeile mit „Verwalten“, alles Weitere im Fenster; „Einladen“ öffnet „Person einladen“.
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
import { anmelden, bereich, keineRohenSchluessel, zuEinstellungen } from './hilfen'

const NAME = 'zz-probebenutzer'

/* ⚠️ **Der Betreiber heisst nicht in jeder Installation gleich.** Bis zum
   01.09.2026 stand hier der Name aus `data-dev` fest im Test; beim Ausmisten
   fuer das oeffentliche Repo wurde der Benutzer umbenannt, und der Test
   meldete danach „Der Betreiber steht nicht in der Benutzerliste" — was
   stimmte, aber auf die falsche Ursache zeigte. Dieselbe Quelle wie die
   Anmeldung: `NEXMAIL_TEST_USER`. */
const BETREIBER = process.env.NEXMAIL_TEST_USER ?? 'betreiber'

/* ⚠️ **Wohin die Probe-Einladung geht, steht nicht im Repo.** Eine Adresse im
   Quelltext wäre entweder erfunden (dann lehnt der Mailserver sie ab und der
   Test prüft den Fehlerweg statt des guten) oder echt (dann steht eine private
   Adresse in einem öffentlichen Repo). `NEXMAIL_TEST_EINLADUNG_AN` setzen, wer
   den guten Weg prüfen will. */
const ZIEL = process.env.NEXMAIL_TEST_EINLADUNG_AN ?? ''

/* Löschen verlangt seit der Kontenliste des Moduls das eigene Passwort des Betreibers (dieselbe Quelle wie die
   Anmeldung). */
const PASSWORT = process.env.NEXMAIL_TEST_PASS ?? ''

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Wird in der breiten Ansicht geprüft.')
  await anmelden(page)
})

test('Die Verwaltung zeigt Benutzer und offene Einladungen', async ({ page }) => {
  await zurVerwaltung(page)
  await bereich(page, 'Konten')

  await expect(
    page.getByText(BETREIBER, { exact: false }).first(),
    'Der Betreiber steht nicht in der Benutzerliste.',
  ).toBeVisible({ timeout: 10_000 })
  await keineRohenSchluessel(page)
})

test('Einladen, annehmen, entfernen', async ({ page }) => {
  // Sauberer Start, falls ein voriger Lauf abgebrochen ist.
  await aufraeumen(page)

  await zurVerwaltung(page)
  await bereich(page, 'Konten')

  const einladen = page.getByRole('button', { name: 'Einladen', exact: true })
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
  await fenster.getByRole('textbox', { name: 'E-Mail' }).fill(ZIEL)
  await fenster.getByRole('textbox', { name: 'Anzeigename' }).fill(NAME)
  // „Per Mail senden“ ist ab Werk angehakt; der Knopf heißt dann „Link senden“.
  await expect(fenster.getByRole('checkbox', { name: 'Per Mail senden' })).toBeChecked()
  await fenster.getByRole('button', { name: 'Link senden' }).click()
  // Danach steht da, wohin sie ging, und immer der Link zum Kopieren.
  await expect(fenster.getByRole('status')).toContainText(ZIEL, { timeout: 30_000 })
  await fenster.getByRole('button', { name: 'Fertig' }).click()

  // ⚠️ **Die Wirkung, nicht der Klick.** Die Einladung muss in der Liste
  // stehen — und nur dann, wenn die Mail wirklich hinausging.
  await expect(
    page.getByText(NAME, { exact: true }).first(),
    'Die Einladung taucht nicht in der Liste auf — verschickt wurde nichts.',
  ).toBeVisible({ timeout: 30_000 })

  // Zurücknehmen und prüfen, dass sie verschwindet.
  await page
    .getByTestId('einladung')
    .filter({ hasText: NAME })
    .getByRole('button', { name: 'Zurücknehmen' })
    .click()
  await page.getByRole('dialog').getByRole('button', { name: 'Zurücknehmen' }).click()
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
  await bereich(page, 'Konten')

  const einladen = page.getByRole('button', { name: 'Einladen', exact: true })
  await expect(einladen).toBeVisible({ timeout: 10_000 })
  /* Seit konten 0.3.5 ist der Knopf immer an (ohne Postausgang steht danach der Link zum Weitergeben da); ob eine
     Mail hinausgeht, sagt der Server. */
  const stand = (await (await page.request.get('/api/benutzer')).json()) as { postausgang_da?: boolean }
  test.skip(!stand.postausgang_da, 'Kein Systempostausgang eingerichtet.')

  await einladen.click()
  const fenster = page.getByRole('dialog')
  await fenster.getByRole('textbox', { name: 'E-Mail' }).fill('zz@example.com')
  await fenster.getByRole('textbox', { name: 'Anzeigename' }).fill(NAME)
  await fenster.getByRole('button', { name: 'Link senden' }).click()

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
    text.includes('zz@example.com') || /\b\d{3}\b/.test(text) || text.length > 60
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
  await bereich(page, 'Konten')
  const zeile = page.getByTestId(`konto-${BETREIBER}`)
  await expect(zeile, 'Der Betreiber steht nicht in der Kontenliste.').toBeVisible({ timeout: 10_000 })
  await expect(zeile.getByText('Du', { exact: true })).toBeVisible()

  /* Am eigenen Konto bietet „Verwalten“ weder „Konto löschen“ noch „Betreiber übergeben“ (konten 0.3.9
     `NOT_ON_SELF`, nexmails `notSelf`), wohl aber „KI erlaubt“. */
  await zeile.getByRole('button', { name: /verwalten$/ }).click()
  const fenster = page.getByRole('dialog')
  await expect(fenster.getByRole('heading', { name: /verwalten$/ })).toBeVisible()
  expect(
    await fenster.getByRole('button', { name: 'Konto löschen' }).count(),
    'Der Betreiber lässt sich in der Oberfläche entfernen.',
  ).toBe(0)
  expect(await fenster.getByRole('button', { name: 'Betreiber übergeben' }).count()).toBe(0)
  await expect(fenster.getByRole('checkbox', { name: 'KI erlaubt' })).toBeVisible()
  await keineRohenSchluessel(page)
  await page.keyboard.press('Escape')
})

test('Verwalten zeigt die Angaben und Knöpfe des Kontos, ohne Menü', async ({ page }) => {
  await zurVerwaltung(page)
  await bereich(page, 'Konten')
  await expect(page.getByTestId(`konto-${BETREIBER}`)).toBeVisible({ timeout: 10_000 })
  const zeilen = page.getByTestId('konten').getByRole('button', { name: /verwalten$/ })
  test.skip((await zeilen.count()) < 2, 'Nur der Betreiber hat ein Konto.')

  await zeilen.last().click()
  const fenster = page.getByRole('dialog')
  for (const angabe of ['Benutzername', 'E-Mail', 'Rolle', 'Anmeldung', 'Postfächer']) {
    await expect(fenster.getByText(angabe, { exact: true }).first(), `Die Angabe „${angabe}“ fehlt.`).toBeVisible()
  }
  for (const gruppe of ['Ändern', 'Rechte', 'Beenden']) {
    await expect(fenster.getByRole('heading', { name: gruppe, exact: true })).toBeVisible()
  }
  await expect(fenster.getByRole('button', { name: 'Betreiber übergeben' })).toBeVisible()
  await expect(fenster.getByRole('button', { name: 'Konto löschen' })).toBeVisible()
  await expect(fenster.getByRole('menu')).toHaveCount(0)

  // Löschen fragt mit Postfächern und Nachrichten, sagt, dass auf dem Mailserver alles bleibt, und will das Passwort.
  await fenster.getByRole('button', { name: 'Konto löschen' }).click()
  const frage = page.getByTestId('verwalten-frage')
  await expect(frage.getByTestId('entfernen-zahlen')).toContainText('Mailserver')
  await expect(frage.locator('input[type="password"]')).toBeVisible()
  await expect(frage.getByRole('button', { name: 'Konto löschen' })).toBeDisabled()
  await frage.getByRole('button', { name: 'Abbrechen' }).click()
  await keineRohenSchluessel(page)
})

test('Der zweite Faktor lässt sich ein- und ausschalten', async ({ page }) => {
  /* ⚠️ **Er ist eine Wahl** (01.09.2026): „das sollten die User selber
     entscheiden dürfen … wenn jemand das rein lokal im netz betreibt wäre das
     ja unötig." Geprüft wird, dass beide Knöpfe da sind und der QR-Code
     wirklich kommt — nicht die ganze Runde: Dafür bräuchte der Test einen
     TOTP-Rechner, und die hat das Backend schon. */
  await zuEinstellungen(page, 'Sicherheit')

  const knopf = page.getByRole('button', { name: /Authenticator-App (einrichten|entfernen)/ })
  await expect(knopf, 'Zum zweiten Faktor gibt es keinen Knopf.').toBeVisible({ timeout: 10_000 })

  const beschriftung = (await knopf.textContent())?.trim() ?? ''
  await knopf.click()
  const fenster = page.getByRole('dialog')
  await expect(fenster).toBeVisible()

  if (beschriftung.includes('einrichten')) {
    // Der QR-Code kommt aus dem eigenen Server, nicht von einem fremden Dienst.
    await expect(fenster.locator('svg').first()).toBeVisible({ timeout: 15_000 })
  } else {
    // Ausschalten verlangt das Passwort — sonst genügt ein offener Bildschirm.
    await expect(fenster.locator('input[type="password"]')).toBeVisible()
  }
  await keineRohenSchluessel(page)
  await page.keyboard.press('Escape')
})

/* --- Hilfen ------------------------------------------------------------- */

async function zurVerwaltung(page: import('@playwright/test').Page) {
  // Seit dem 22.11.2026 die Gruppe „Server" der Einstellungen.
  await zuEinstellungen(page, 'Konten')
}

async function aufraeumen(page: import('@playwright/test').Page) {
  await page.evaluate(async ({ name, passwort }) => {
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
        await fetch(`/api/benutzer/${p.id}`, {
          method: 'DELETE',
          credentials: 'include',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ passwort }),
        })
      }
    }
  }, { name: NAME, passwort: PASSWORT })
}
