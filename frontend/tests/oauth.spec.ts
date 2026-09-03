/* Google und Microsoft — die Einrichtung.
 *
 * ⚠️ **Hier wird nichts wirklich verbunden.** Das ginge nur mit einer echten
 * App-Registrierung und einer echten Zustimmung im Browser des Betreibers.
 * Geprüft wird, was die Oberfläche **vorher** sagt — und genau das ist der
 * Teil, der schweigen könnte.
 */
import { expect, test } from '@playwright/test'
import { anmelden, zuEinstellungen } from './hilfen'

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Die Verwaltung wird breit geprüft.')
  await anmelden(page)
  await page.getByRole('button', { name: 'Verwaltung' }).click()
  await page.getByRole('tab', { name: /Google und Microsoft/ }).click()
})

test('Beide Anbieter stehen da, mit Rückkehr-Adresse zum Kopieren', async ({ page }) => {
  for (const name of ['Google', 'Microsoft']) {
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  }

  /* ⚠️ **Ein Zeichen daneben, und Google antwortet mit
     `redirect_uri_mismatch`** — eine Meldung, die niemand mit dieser Zeile in
     Verbindung bringt. Deshalb steht sie wörtlich da. */
  const adressen = page.getByText(/\/api\/mailoauth\/(google|microsoft)\/zurueck/)
  expect(await adressen.count()).toBeGreaterThanOrEqual(2)
})

test('Der Satz zu „In production" steht da, bevor jemand anfängt', async ({ page }) => {
  /* ⚠️ **Der Satz, der eine Woche später Ärger spart.** Im Testbetrieb
     verfallen Googles Auffrischungs-Token nach sieben Tagen; wer das nicht
     weiß, richtet alles ein, freut sich eine Woche und sucht dann den Fehler
     im Mailserver. */
  await expect(page.getByText(/In production/)).toBeVisible()
  await expect(page.getByText(/sieben Tagen/)).toBeVisible()
})

test('Ohne Client-ID lässt sich nichts speichern', async ({ page }) => {
  const google = page.locator('section').filter({ hasText: 'Google' }).first()
  await google.getByLabel('Client-ID').fill('')
  await expect(google.getByRole('button', { name: 'Speichern' })).toBeDisabled()
})

test('Die Zustimmungen stehen bei den Konten, nicht beim Postfach', async ({ page }) => {
  /* ⚠️ **Eine Zustimmung gilt für Postfach UND Kalender.** Sie an einem der
     beiden aufzuhängen hieße, sie beim anderen zu verstecken. */
  await zuEinstellungen(page)
  await page.getByRole('tab', { name: 'Sicherheit' }).click()

  await expect(page.getByRole('heading', { name: /Google- und Microsoft-Konten/ })).toBeVisible()

  /* ⚠️ **Ohne eingetragene App kein Knopf, sondern der Grund.** Ein Knopf, der
     nur in eine Fehlermeldung führt, ist eine Sackgasse mit Beschriftung —
     dieselbe Regel wie beim gesperrten Google-Eintrag im Kalender. */
  const knopf = page.getByRole('button', { name: /Google-Konto verbinden/ })
  const hinweis = page.getByText(/Google- oder Microsoft-Konto möglich|Verwaltung → Google und Microsoft/)

  /* ⚠️ **Auf die Antwort warten, nicht auf die Uhr — und nicht auf keine.**
     Welche Anbieter offenstehen, holt die Seite erst beim Server; wer sofort
     `count()` abfragt, bekommt null und prüft dann den falschen Zweig. Genau
     so ist der Test am 03.09.2026 rot geworden, ohne dass etwas kaputt war.
     `or` wartet, bis eines von beiden da ist. */
  await expect(knopf.or(hinweis).first()).toBeVisible()
})

test('Die Anleitung ist da, aber zugeklappt', async ({ page }) => {
  /* ⚠️ **Sieben Schritte offen erschlagen jeden**, der nur die Client-ID
     nachtragen will — aber wer zum ersten Mal in der Cloud Console steht,
     kommt ohne sie nicht durch. Also zugeklappt, nicht weggelassen. */
  const auf = page.getByRole('button', { name: /Schritt für Schritt/ })
  await expect(auf).toBeVisible()
  await expect(page.getByText(/Projekt anlegen/)).toBeHidden()

  await auf.click()

  for (const schritt of [/Projekt anlegen/, /Gmail API/, /Data Access/, /In production/]) {
    await expect(page.getByText(schritt).first()).toBeVisible()
  }

  /* ⚠️ **Die CalDAV API ist eine EIGENE Schnittstelle.** Wer nur die Google
     Calendar API einschaltet, bekommt bei jedem Kalenderabruf ein 403, das wie
     eine fehlende Zustimmung aussieht — am 03.09.2026 an einem echten Konto
     genau so passiert. Der Schritt darf aus der Anleitung nicht wieder
     verschwinden. */
  await expect(page.getByText(/CalDAV API/).first()).toBeVisible()

  /* ⚠️ **Der Satz, der einen Denkfehler ausräumt.** „Google findet meinen
     localhost nicht" klingt zwingend und ist falsch. */
  await expect(page.getByText(/schickt nur deinen Browser dorthin/)).toBeVisible()
})
