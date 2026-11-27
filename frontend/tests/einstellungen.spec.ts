/* Die Einstellungen nach dem Bauplan „Einstellungen“ (Bausatz ui 1.1.0, seit 26.11.2026).
 *
 * Navigation links mit dem eigenen Konto oben und den Gruppen „Mein Konto",
 * „Mail", „Server" und „Über nexmail" am Ende; schmal erst die Liste, in einem
 * Bereich der Weg zurück. Jeder Bereich hat seine Adresse `/settings/<slug>`.
 */
import { expect, test, type Locator } from '@playwright/test'
import { anmelden, bereich, jederKnopfHatEinenNamen, keineRohenSchluessel, keinSeitlichesScrollen, zuEinstellungen, zurAnsicht } from './hilfen'

/** Die Teile stehen in dieser Reihenfolge von oben nach unten, alle sichtbar. */
async function untereinander(teile: Locator[], wo: string) {
  let oben = -Infinity
  for (const teil of teile) {
    await expect(teil.first(), `${wo}: ${teil} fehlt.`).toBeVisible({ timeout: 10_000 })
    const y = (await teil.first().boundingBox())!.y
    expect(y, `${wo}: ${teil} steht nicht unter dem Teil davor.`).toBeGreaterThan(oben)
    oben = y
  }
}

test('Die Einstellungen sind gegliedert wie in nexnotes', async ({ page }, info) => {
  await anmelden(page)
  await zuEinstellungen(page, 'Profil')

  /* Das Profil zuerst, seit konten 0.3.6 ganz aus `PAGES.profile`: Bild, Anzeigename, Benutzername, E-Mail,
     Sprache, klein die Rolle, untereinander; danach nexmails „Abmelden“. Der Benutzername wird direkt im Feld
     geändert, ein „Bearbeiten“ gibt es nicht mehr. */
  const inhalt = page.locator('[data-testid^="settings-area-"]')
  const profil = [
    inhalt.getByText('Profilbild hochladen', { exact: true }),
    inhalt.getByLabel('Anzeigename', { exact: true }),
    inhalt.getByLabel('Benutzername', { exact: true }),
    inhalt.getByLabel('E-Mail', { exact: true }),
    inhalt.getByRole('combobox', { name: /^Sprache/ }),
    inhalt.getByText(/^Rolle: /),
    inhalt.getByRole('heading', { name: 'Abmelden' }),
  ]
  await untereinander(profil, 'Profil')
  await expect(inhalt.getByLabel('Benutzername', { exact: true })).toBeEditable()
  // Wie nexnotes: eine Karte „Profil“, die Beschriftungen normal geschrieben, nicht in Großbuchstaben (25.11.2026).
  await expect(inhalt.getByRole('region', { name: 'Profil', exact: true }).getByLabel('Anzeigename', { exact: true })).toBeVisible()
  await expect(inhalt.locator('label', { hasText: /^Anzeigename$/ })).toHaveCSS('text-transform', 'none')
  // konten 0.3.7: ein Knopf „Speichern“ für die drei Felder, nie beim Verlassen; am Benutzernamen auch seine Regeln.
  const profilkarte = inhalt.getByRole('region', { name: 'Profil', exact: true })
  await expect(profilkarte.getByRole('button', { name: 'Speichern', exact: true })).toHaveCount(1)
  await expect(inhalt.getByLabel('Benutzername', { exact: true })).toHaveAccessibleDescription(/2 bis 64 Zeichen/)
  await expect(inhalt.getByRole('button', { name: 'Bearbeiten', exact: true })).toHaveCount(0)
  // `layout: 'stacked'`: Die Felder stehen untereinander, nie nebeneinander, auch breit.
  const links = await Promise.all(profil.slice(1, 4).map(async (feld) => (await feld.boundingBox())!.x))
  expect(new Set(links).size, 'Die Felder des Profils stehen nicht untereinander.').toBe(1)

  /* Sicherheit in der Reihenfolge des Moduls (`PAGES.security`); Passkeys und Codes zeigen sich nur, wenn es sie
     gibt. Wie nexnotes stehen sie als Unterkästen in EINER Karte „Sicherheit“; nexmails eigene Teile (Anmeldeanbieter,
     Google und Microsoft) folgen danach als eigene Karten. */
  await bereich(page, 'Sicherheit')
  await untereinander(
    [
      inhalt.getByRole('heading', { name: 'Passwort', exact: true }),
      inhalt.getByRole('heading', { name: 'Zweiter Faktor', exact: true }),
      inhalt.getByRole('heading', { name: 'Angemeldete Geräte', exact: true }),
      inhalt.getByRole('button', { name: 'Überall sonst abmelden' }),
      inhalt.getByText('Mail bei neuer Anmeldung', { exact: true }),
    ],
    'Sicherheit',
  )
  await expect(inhalt.getByText('Aus', { exact: true }).or(inhalt.getByText('An', { exact: true })).first()).toBeVisible()
  const sicherheit = inhalt.getByRole('region', { name: 'Sicherheit', exact: true })
  for (const kopf of ['Passwort', 'Zweiter Faktor', 'Angemeldete Geräte']) {
    await expect(sicherheit.getByRole('heading', { name: kopf, exact: true }), `${kopf} steht nicht in der Karte „Sicherheit“.`).toBeVisible()
  }
  await expect(sicherheit.getByText('Mail bei neuer Anmeldung', { exact: true })).toBeVisible()
  const geraete = (await inhalt.getByRole('heading', { name: 'Angemeldete Geräte', exact: true }).boundingBox())!.y
  for (const eigen of ['Anmeldeanbieter', 'Google- und Microsoft-Konten']) {
    const kopf = inhalt.getByRole('heading', { name: eigen, exact: true })
    if (await kopf.count()) {
      expect((await kopf.first().boundingBox())!.y, `${eigen} steht vor den Teilen des Moduls.`).toBeGreaterThan(geraete)
      await expect(sicherheit.getByRole('heading', { name: eigen, exact: true }), `${eigen} steckt in der Karte „Sicherheit“.`).toHaveCount(0)
      await expect(inhalt.getByRole('region', { name: eigen, exact: true }), `${eigen} ist keine eigene Karte.`).toBeVisible()
    }
  }

  if (info.project.name !== 'schmal') {
    const navigation = page.getByTestId('settings-nav')
    await expect(navigation.locator('[id^="settings-group-"]')).toHaveText(['Mein Konto', 'Mail', 'Server'])
    // „Über nexmail" steht unter den Gruppen, als letzter Eintrag.
    const eintraege = await navigation.getByRole('link').allTextContents()
    expect(eintraege.at(-1)?.trim()).toBe('Über nexmail')
  }
  await keinSeitlichesScrollen(page)
  await keineRohenSchluessel(page)
})

test('Verwaltung, KI und „Über" sind Bereiche, keine Punkte der Leiste', async ({ page }) => {
  await anmelden(page)
  for (const weg of ['Verwaltung', 'KI', 'Über nexmail']) {
    await expect(page.getByRole('button', { name: weg, exact: true })).toHaveCount(0)
  }
  // Die Profilzeile unten in der Ordnerspalte führt für jeden in die
  // Einstellungen, beim Profil (seit 23.11.2026, vorher ein Zahnrad links).
  await zuEinstellungen(page, 'Profil')
  for (const titel of ['Allgemein', 'KI', 'KI-Anbieter', 'Über nexmail']) await bereich(page, titel)
})

test('Hell/Dunkel und Sprache stehen nicht mehr oben, sondern in den Einstellungen', async ({ page }) => {
  await anmelden(page)
  await expect(page.getByRole('button', { name: /Dunkler Modus|Heller Modus/ })).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Sprache' })).toHaveCount(0)
  await zuEinstellungen(page, 'Darstellung')
  await expect(page.getByRole('radio', { name: 'Dunkel', exact: true })).toBeVisible()
  await bereich(page, 'Profil')
  await expect(page.getByRole('combobox', { name: /^Sprache/ })).toBeVisible()
})

test('iPhone oder iPad verbinden zeigt QR-Code, kurzen Code und Stand', async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page, 'Verbindungen')

  // Bauplan „Einstellungen", Verbindungen 1: die Karte „Geräte" (Modul geraete 0.1.0), der Code in einem Fenster.
  // Wie der QR-Code gezeichnet ist (Ruhezone, viewBox), prüfen die Tests des Moduls; hier: er steht da.
  await page.getByTestId('devices-connect').click()
  const fenster = page.getByTestId('pair-body')

  const code = fenster.getByTestId('pair-qr')
  await expect(code).toBeVisible()
  await expect(fenster.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeVisible()
  await expect(fenster.getByTestId('pair-valid')).toBeVisible()
  await keineRohenSchluessel(page)
  await jederKnopfHatEinenNamen(page)

  // Abbrechen zieht den Code zurück; der Knopf steht wieder da.
  await page.getByTestId('pair-cancel').click()
  await expect(fenster).toHaveCount(0)
  await expect(page.getByTestId('devices-connect')).toBeVisible()
})

test('Jeder Bereich geht auf, mit Inhalt und ohne Fehler', async ({ page }, info) => {
  /* ⚠️ **Der Umbau vom 22.11.2026 hat Reiter, Verwaltung, KI und Über in eine
     Seite gezogen.** Dieser Test öffnet jeden Bereich und verlangt, dass dort
     das steht, was vorher im alten Reiter stand: ein Merkmal je Bereich. Fehlt
     eines, ist beim Umbau etwas verloren gegangen. */
  test.skip(info.project.name === 'schmal', 'Die Navigation wird breit geprüft.')
  const fehler: string[] = []
  page.on('pageerror', (e) => fehler.push(e.message))
  await anmelden(page)
  await zuEinstellungen(page, 'Profil')

  // ⚠️ Je Bereich, was der INHALT zeigen muss (nicht Titel oder Satz im Kopf):
  // die Teile, die vorher in den Reitern von Einstellungen und Verwaltung,
  // auf der KI-Seite und der Über-Seite standen.
  const merkmal: Array<[string, RegExp[]]> = [
    // Seit konten 0.3.6 aus `PAGES.profile`; die Sprache gilt am Konto (vorher „Gilt in diesem Browser“).
    ['Profil', [/Profilbild hochladen/, /^Damit meldest du dich an\.$/, /^Rolle: /, /^Abmelden$/]],
    ['Sicherheit', [/Angemeldete Geräte/, /Überall sonst abmelden/, /Zweiter Faktor/]],
    ['Darstellung', [/Dichte der Nachrichtenliste/i, /Wie das System/]],
    ['Benachrichtigungen', [/Je Abgleich eine Meldung/]],
    ['Verbindungen', [/^Geräte$/, /iPhone oder iPad verbinden/, /Verbinde deine Todo-App/, /^API-Schlüssel$/]],
    // Seit 23.11.2026 ein eigener Bereich (vorher nur in Kalender und Kontakten).
    ['Kalender und Adressbücher', [/^Kalender hinzufügen$/, /^Adressbuch verbinden$/]],
    ['Postfächer', [/Postfach hinzufügen/]],
    ['Regeln', [/Neue Regel/]],
    ['Signaturen', [/Neue Signatur/, /Neue Vorlage/]],
    ['Abwesenheit', [/beantwortet Post nur, solange/]],
    ['Schlagworte', [/Noch keine Schlagworte|Mails mit dieser Marke/]],
    // Der persönliche Teil bleibt unter Mein Konto, der Server-Teil heißt „KI-Anbieter“ (nur Betreiber).
    // Seit dem Modul ki 0.1.0 (E61): beide Bereiche aus dessen Karten, dazu nexmails Karte „Eingegangene Post“.
    ['KI', [/^Was ging hinaus$/, /Meine eingegangenen Mails/]],
    ['KI-Anbieter', [/^Wer KI nutzen darf$/, /KI auf diesem Server erlaubt/, /Eingegangene Mails für alle Benutzer/]],
    // Die öffentliche Adresse steht nur noch unter Anmeldung; die Zeitzone des Servers ist nexmails eigene Karte.
    ['Allgemein', [/Server im eigenen Netz/, /Text der Mail an Webhooks/, /Zeitzone des Servers/]],
    ['Anmeldung', [/authentik/i, /Öffentliche Adresse/]],
    ['Mail', [/Testmail an/, /Client-ID/]],
    ['Speicher und Sicherung', [/Jetzt sichern/]],
    ['Konten', [/^Einladen$/, /^Verwalten$/]],
    ['Log', [/Ausführlichkeit/]],
    ['Über nexmail', [/AGPL-3\.0/]],
  ]
  for (const [titel, texte] of merkmal) {
    await bereich(page, titel)
    const inhalt = page.locator('[data-testid^="settings-area-"]')
    for (const text of texte) {
      await expect(inhalt.getByText(text).first(), `Im Bereich „${titel}" fehlt ${text}.`).toBeVisible({
        timeout: 10_000,
      })
    }
    // Die Über-Seite nennt die Projektseite „nexmail.nexapps.dev", und die
    // sieht für den Wächter aus wie ein Schlüssel; sie ist keiner.
    if (titel !== 'Über nexmail') await keineRohenSchluessel(page)
    if (titel === 'Allgemein') {
      await expect(inhalt.getByText('Öffentliche Adresse', { exact: true }), 'Die öffentliche Adresse steht nur unter Anmeldung.').toHaveCount(0)
    }
  }
  expect(fehler, 'Fehler beim Öffnen der Bereiche').toEqual([])
})

/* ⚠️ **Woher man kommt, bleibt links stehen** (gemeldet am 23.11.2026): Aus
   dem Kalender heraus sprang die Spalte neben den Einstellungen auf die Ordner
   der Mail. */
test('Aus dem Kalender geöffnet, steht links weiter die Kalenderliste', async ({ page }, info) => {
  test.skip(info.project.name === 'schmal', 'Schmal stehen die Einstellungen allein.')
  await anmelden(page)
  await zurAnsicht(page, 'Kalender')
  const spalte = page.getByTestId('seitenspalte')
  await expect(spalte.getByRole('heading', { name: 'Kalender' })).toBeVisible()
  await spalte.getByRole('button', { name: /· (Einstellungen|Settings)$/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Profil' })).toBeVisible()
  await expect(spalte.getByRole('heading', { name: 'Kalender' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Ordner (ein|aus)klappen/ })).toHaveCount(0)
})

/* Alte Lesezeichen gelten weiter: deutsche Namen und `/einstellungen/…` landen beim englischen Bereich, und die
   Adresse wird ersetzt, nicht als zweiter Eintrag in den Verlauf gelegt. */
test('Alte Adressen der Einstellungen führen zum neuen Bereich', async ({ page }) => {
  await anmelden(page)
  for (const [alt, neu, titel] of [
    ['/settings/postfaecher', 'settings/mailboxes', 'Postfächer'],
    ['/einstellungen/speicher', 'settings/storage', 'Speicher und Sicherung'],
    ['/settings/ueber', 'settings/about', 'Über nexmail'],
  ] as const) {
    await page.goto(alt)
    await expect(page.getByRole('heading', { level: 1, name: titel, exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`/${neu}$`))
  }
})
