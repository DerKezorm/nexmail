/* Die Einstellungen, aufgebaut wie in nexnotes (22.11.2026).
 *
 * Navigation links mit dem eigenen Konto oben und den Gruppen „Mein Konto",
 * „Mail", „Server" und „Über nexmail" am Ende; schmal eine Auswahl darüber.
 * Verwaltung, KI und „Über" sind Bereiche darin, keine Punkte der Leiste mehr.
 */
import { expect, test } from '@playwright/test'
import { anmelden, bereich, jederKnopfHatEinenNamen, keineRohenSchluessel, keinSeitlichesScrollen, zuEinstellungen, zurAnsicht } from './hilfen'

test('Die Einstellungen sind gegliedert wie in nexnotes', async ({ page }, info) => {
  await anmelden(page)
  await zuEinstellungen(page, 'Profil')

  // Das Profil zuerst, mit Name, Mailadresse, Sprache und Abmelden.
  await expect(page.getByLabel('Name', { exact: true })).toBeVisible()
  await expect(page.getByLabel('E-Mail', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Abmelden' })).toBeVisible()

  if (info.project.name !== 'schmal') {
    const navigation = page.getByTestId('einstellungen-navigation')
    await expect(navigation.locator('[id^="einstellungen-gruppe-"]')).toHaveText(['Mein Konto', 'Mail', 'Server'])
    // „Über nexmail" steht unter den Gruppen, als letzter Eintrag.
    const knoepfe = await navigation.getByRole('button').allTextContents()
    expect(knoepfe.at(-1)?.trim()).toBe('Über nexmail')
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
  for (const titel of ['Allgemein', 'KI', 'Über nexmail']) await bereich(page, titel)
})

test('Hell/Dunkel und Sprache stehen nicht mehr oben, sondern in den Einstellungen', async ({ page }) => {
  await anmelden(page)
  await expect(page.getByRole('button', { name: /Dunkler Modus|Heller Modus/ })).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Sprache' })).toHaveCount(0)
  await zuEinstellungen(page, 'Darstellung')
  await expect(page.getByRole('tab', { name: 'Dunkel', exact: true })).toBeVisible()
  await bereich(page, 'Profil')
  await expect(page.getByRole('combobox', { name: /^Sprache/ })).toBeVisible()
})

test('iPhone verbinden zeigt QR-Code, kurzen Code und Stand', async ({ page }) => {
  await anmelden(page)
  await zuEinstellungen(page, 'Verbindungen')

  await page.getByRole('button', { name: 'Code anzeigen' }).click()

  /* ⚠️ Gemessen, nicht nur gesucht: Ohne `viewBox` schnitt die Fläche den Code
     rechts und unten ab. Er war sichtbar, und kein Telefon konnte ihn lesen. */
  const code = page.getByRole('img', { name: 'iPhone verbinden' })
  await expect(code).toBeVisible()
  const m = await code.evaluate((rahmen) => {
    const flaeche = rahmen.getBoundingClientRect()
    const muster = rahmen.querySelector('svg path.qrline')!.getBoundingClientRect()
    return {
      breite: flaeche.width,
      links: muster.left - flaeche.left,
      rechts: flaeche.right - muster.right,
      oben: muster.top - flaeche.top,
      unten: flaeche.bottom - muster.bottom,
    }
  })
  expect(m.breite).toBe(200)
  // Vier Module Ruhezone auf jeder Seite, also etwas Weiß ringsum.
  for (const seite of [m.links, m.rechts, m.oben, m.unten]) expect(seite).toBeGreaterThan(5)
  await expect(page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeVisible()
  await expect(page.getByText(/Wartet auf die App/)).toBeVisible()
  await keineRohenSchluessel(page)
  await jederKnopfHatEinenNamen(page)

  await page.getByRole('button', { name: 'Zurückziehen' }).click()
  await expect(page.getByRole('button', { name: 'Code anzeigen' })).toBeVisible()
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
    ['Profil', [/Profilbild hochladen/, /Gilt in diesem Browser/, /^Abmelden$/]],
    ['Sicherheit', [/Angemeldete Geräte/, /Überall sonst abmelden/, /Zweiter Faktor/]],
    ['Darstellung', [/Dichte der Nachrichtenliste/i, /Wie das System/]],
    ['Benachrichtigungen', [/Je Abgleich eine Meldung/]],
    ['Verbindungen', [/Verbinde deine Todo-App/, /Code anzeigen/, /Adresse für das Dashboard/]],
    // Seit 23.11.2026 ein eigener Bereich (vorher nur in Kalender und Kontakten).
    ['Kalender und Adressbücher', [/^Kalender hinzufügen$/, /^Adressbuch verbinden$/]],
    ['Postfächer', [/Postfach hinzufügen/]],
    ['Regeln', [/Neue Regel/]],
    ['Signaturen', [/Neue Signatur/, /Neue Vorlage/]],
    ['Abwesenheit', [/beantwortet Post nur, solange/]],
    ['Schlagworte', [/Noch keine Schlagworte|Mails mit dieser Marke/]],
    ['KI', [/KI-Dienste für alle Benutzer/, /Eingegangene Mails für alle Benutzer/]],
    ['Allgemein', [/Öffentliche Adresse/, /Eigenes Netz erlauben/, /Text der Mail an Webhooks/]],
    ['Anmeldung', [/authentik/i]],
    ['Mail', [/Probemail schicken/, /Client-ID/]],
    ['Speicher und Sicherung', [/Rücksetzpunkte/]],
    ['Konten', [/Benutzer einladen/]],
    ['Log', [/Ausführlichkeit/]],
    ['Über nexmail', [/AGPL-3\.0/]],
  ]
  for (const [titel, texte] of merkmal) {
    await bereich(page, titel)
    const inhalt = page.getByTestId('einstellungen-inhalt')
    for (const text of texte) {
      await expect(inhalt.getByText(text).first(), `Im Bereich „${titel}" fehlt ${text}.`).toBeVisible({
        timeout: 10_000,
      })
    }
    // Die Über-Seite nennt die Projektseite „nexmail.nexapps.dev", und die
    // sieht für den Wächter aus wie ein Schlüssel; sie ist keiner.
    if (titel !== 'Über nexmail') await keineRohenSchluessel(page)
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
