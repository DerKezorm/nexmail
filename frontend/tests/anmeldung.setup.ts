/* Einmal anmelden, alle Tests benutzen dieselbe Sitzung.
 *
 * ⚠️ **Nicht je Test neu anmelden.** nexmail hat eine Anmeldebremse — genau
 * dafür ist sie da. Ein Testlauf, der sich zehnmal hintereinander anmeldet,
 * läuft hinein und meldet dann „die Oberfläche geht nicht", obwohl der Server
 * völlig richtig handelt. Der erste Lauf dieser Tests ist genau so
 * gescheitert.
 */
import { expect, test as setup } from '@playwright/test'

const STAND = 'tests/.sitzung.json'

/* ⚠️ **Die Zugangsdaten stehen nicht im Repo.**
 *
 * Sie gehoerten frueher hier hin — der Name des Betreibers und sein Kennwort,
 * fest eingetippt. In einem oeffentlichen Repo ist beides fehl am Platz, und
 * ausserdem heisst der Benutzer nicht in jeder Installation gleich.
 *
 * Vorgabe passt zur mitgelieferten Beschreibung; wer anders heisst, setzt
 * `NEXMAIL_TEST_USER` und `NEXMAIL_TEST_PASS`. */
const NUTZER = process.env.NEXMAIL_TEST_USER ?? 'betreiber'
const KENNWORT = process.env.NEXMAIL_TEST_PASS ?? 'betreiber'

setup('anmelden', async ({ page }) => {
  await page.goto('/')

  const benutzerfeld = page.getByRole('textbox', { name: 'Benutzername' })
  await expect(benutzerfeld).toBeVisible()
  await benutzerfeld.fill(NUTZER)
  await page.getByRole('textbox', { name: 'Kennwort' }).fill(KENNWORT)

  const weiter = page.getByRole('button', { name: 'Weiter' })
  await expect(weiter, 'Der Anmeldeknopf bleibt gesperrt.').toBeEnabled()
  await weiter.click()

  await expect(
    page.getByRole('button', { name: 'Mail', exact: true }),
    'Nach der Anmeldung steht die Mail-Ansicht nicht da. Läuft das Backend auf 8010 mit data-dev?',
  ).toBeVisible({ timeout: 15_000 })

  await page.context().storageState({ path: STAND })
})
