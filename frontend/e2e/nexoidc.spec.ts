/**
 * Pflichttests 33 und 34 der gemeinsamen Anmeldung (einmal aus bauplaene/oidc kopiert, dann nexmails Datei).
 *
 * Der Anbieter ist der nachgebaute aus `e2e/fake-oidc.mjs` (http://localhost:8497, eine andere Site als nexmail auf
 * 127.0.0.1). Nie ein echter Anbieter, nie das Netz. Die Seite ist der Betreiber `betreiber` aus `global-setup.ts`.
 *
 * ⚠️ **Das Sitzungs-Cookie steht auf `SameSite=strict`.** Beim Verknüpfen schickt der Browser es auf dem Rückweg vom
 * Anbieter nicht mit; die Rückkehr reicht deshalb einmal über nexmails eigene Seite durch. Genau das prüft der erste
 * Teil von 33 in einem echten Chromium, was kein Server-Test kann.
 */
import { expect, test, type Page } from '@playwright/test'

const PROVIDER = 'http://localhost:8497'
const PASSWORT = process.env.NEXMAIL_E2E_PASSWORD ?? ''

type Eintrag = { id: number; slug: string }

async function eintragWeg(page: Page, slug: string): Promise<void> {
  const eintraege = (await (await page.request.get('/api/oidc/admin/providers')).json()) as Eintrag[]
  for (const e of eintraege) {
    if (e.slug === slug) await page.request.delete(`/api/oidc/admin/providers/${e.id}`)
  }
}

function probleme(page: Page): string[] {
  const liste: string[] = []
  page.on('console', (m) => {
    // Vor der Anmeldung fragt die Seite /api/auth/ich und bekommt 401 („niemand angemeldet“); 422 ist der gewollt
    // abgewiesene Aussteller im Formular. Der Browser schreibt beides als Fehler, die Seite sagt es in Worten.
    if (m.type() === 'error' && !/status of (401|422)/.test(m.text())) liste.push(m.text())
  })
  page.on('pageerror', (f) => liste.push(f.message))
  return liste
}

async function naechstePerson(person: object): Promise<void> {
  await fetch(`${PROVIDER}/next`, { method: 'POST', body: JSON.stringify(person) })
}

test('33: sign-in through the provider button ends in a session', async ({ page, browser }) => {
  const fehler = probleme(page)
  await eintragWeg(page, 'standin')
  const angelegt = await page.request.post('/api/oidc/admin/providers', {
    data: { label: 'Stand-in', slug: 'standin', issuer: PROVIDER, client_id: 'e2e-client', client_secret: `e2e-${Date.now()}` },
  })
  expect(angelegt.ok(), await angelegt.text()).toBe(true)
  await naechstePerson({ sub: 'betreiber-33', preferred_username: 'jemand-anderes', email: 'betreiber@example.com' })

  // Verknüpfen unter Einstellungen → Sicherheit: das Kennwort noch einmal, dann zum Anbieter und zurück.
  await page.goto('/konto/sicherheit')
  const zeile = page.getByTestId('anmeldeanbieter-konto').getByRole('listitem').filter({ hasText: 'Stand-in' })
  await expect(zeile).toContainText('Nicht verknüpft')
  await zeile.getByRole('button', { name: 'Verknüpfen' }).click()
  const fenster = page.getByRole('dialog')
  await fenster.getByLabel('Kennwort').fill(PASSWORT)
  await fenster.getByRole('button', { name: 'Verknüpfen' }).click()
  // Zurück, über die Seite, die einmal durchreicht: Die Rückkehr sah die Sitzung trotz SameSite=strict.
  await page.waitForURL((url) => url.port === '8496' && !url.pathname.startsWith('/api/'))
  await expect(page.getByRole('status').filter({ hasText: 'Stand-in' })).toContainText('Verknüpft')
  await expect(zeile).toContainText('Verknüpft')
  await expect(page).not.toHaveURL(/error=/)
  expect(fehler).toEqual([])

  // Ein Browser ohne Sitzung: der Knopf auf der Anmeldeseite, und hinein.
  const frisch = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const besuch = await frisch.newPage()
  const besuchFehler = probleme(besuch)
  await besuch.goto('/')
  await besuch.getByRole('link', { name: 'Mit Stand-in anmelden' }).click()
  await besuch.waitForURL((url) => url.port === '8496' && !url.pathname.startsWith('/api/'))
  await expect(besuch).not.toHaveURL(/error=/)
  const ich = await besuch.request.get('/api/auth/ich')
  expect((await ich.json()).benutzername).toBe('betreiber')
  expect(besuchFehler).toEqual([])
  await frisch.close()

  // Eine fremde Person beim Anbieter, mit derselben Adresse und bestätigt: kein Konto, die Seite sagt es in Worten.
  await naechstePerson({ sub: 'fremd-33', email: 'betreiber@example.com', email_verified: true })
  const fremd = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const fremder = await fremd.newPage()
  await fremder.goto('/')
  await fremder.getByRole('link', { name: 'Mit Stand-in anmelden' }).click()
  await expect(fremder.getByText('Für dich gibt es hier kein Konto.', { exact: false })).toBeVisible()
  expect((await fremder.request.get('/api/auth/ich')).status()).toBe(401)
  await fremd.close()

  // Wieder lösen: Das Kennwort bleibt der Weg.
  await page.goto('/konto/sicherheit')
  await zeile.getByRole('button', { name: 'Lösen' }).click()
  await expect(zeile).toContainText('Nicht verknüpft')
  await eintragWeg(page, 'standin')
})

test('34: add, edit and remove a provider; the authentik card lists its steps', async ({ page }) => {
  const fehler = probleme(page)
  await eintragWeg(page, 'stand-in')
  await eintragWeg(page, 'standin')
  await page.goto('/')
  await page.getByRole('button', { name: 'Verwaltung' }).click()
  await page.getByRole('tab', { name: 'Anmeldung' }).click()
  await expect(page.getByRole('heading', { name: 'Anmeldung', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Anmeldeanbieter' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'authentik in einem Schritt' })).toBeVisible()
  await expect(page.getByTestId('oidc-anbieter-leer')).toBeVisible()
  await page.getByRole('button', { name: 'Anbieter hinzufügen' }).click()
  const formular = page.getByTestId('provider-form')
  await formular.getByLabel('Name auf dem Knopf').fill('Stand-in')
  // Der Kurzname folgt dem Namen, die Rückleitadresse dem Kurznamen.
  await expect(formular.getByLabel('Kurzname')).toHaveValue('stand-in')
  await expect(formular.getByTestId('provider-redirect')).toHaveText(/\/api\/oidc\/stand-in\/callback$/)
  // Ein Aussteller, der nicht als einer antwortet, wird am Feld abgewiesen, und nichts ist gespeichert.
  await formular.getByLabel('Aussteller (Issuer)').fill(`${PROVIDER}/nothing-here`)
  await formular.getByLabel('Client-ID').fill('e2e-client')
  await formular.getByLabel('Client-Geheimnis').fill(`e2e-${Date.now()}`)
  await formular.getByRole('button', { name: 'Speichern' }).click()
  await expect(formular.getByText(/Anbieter/).filter({ hasText: /erreichbar|verständlich|nennt sich/ })).toBeVisible()
  await formular.getByLabel('Aussteller (Issuer)').fill(PROVIDER)
  await formular.getByRole('button', { name: 'Speichern' }).click()
  const liste = page.getByTestId('provider-list')
  const zeile = liste.getByRole('listitem').filter({ hasText: 'Stand-in' })
  await expect(zeile).toContainText(PROVIDER)
  await expect(zeile).toContainText('aktiv')
  await zeile.getByRole('button', { name: /^Bearbeiten/ }).click()
  await expect(formular.getByText('stand-in', { exact: true })).toBeVisible()
  await formular.getByLabel('Name auf dem Knopf').fill('Stand-in 2')
  await formular.getByRole('button', { name: 'Speichern' }).click()
  const umbenannt = liste.getByRole('listitem').filter({ hasText: 'Stand-in 2' })
  await expect(umbenannt).toBeVisible()
  // Die Anmeldeseite hat jetzt ihren Knopf.
  const knoepfe = await (await page.request.get('/api/oidc/providers')).json()
  expect(knoepfe).toContainEqual({ slug: 'stand-in', label: 'Stand-in 2' })
  await umbenannt.getByRole('button', { name: /^Entfernen/ }).click()
  const frage = page.getByRole('dialog')
  await expect(frage).toContainText('Konten verlieren die Verknüpfung')
  await frage.getByRole('button', { name: 'Entfernen' }).click()
  await expect(page.getByText('Stand-in 2')).toHaveCount(0)
  // Die authentik-Karte: unter einer Adresse, an der niemand antwortet, scheitert der erste Schritt, in Worten.
  await page.getByLabel('Adresse von authentik').fill('http://127.0.0.1:9')
  await page.getByLabel('API-Token').fill(`e2e-${Date.now()}`)
  // Ohne öffentliche Adresse (eine frische App) heißt der Knopf „Übernehmen und einrichten“ (1.0.10).
  await expect(page.getByTestId('authentik-no-address')).toBeVisible()
  await page.getByRole('button', { name: /^(Einrichten|Übernehmen und einrichten)$/ }).click()
  const schritte = page.getByTestId('authentik-steps')
  await expect(schritte).toContainText('Verbindung zu authentik')
  await expect(schritte).toContainText('authentik ist unter dieser Adresse nicht erreichbar.')
  expect(fehler).toEqual([])
})
