/**
 * Beide Sprachen müssen dieselben Einträge kennen — jeden einzelnen.
 *
 * ⚠️ **Der Rückfall verdeckt es nur zur Hälfte.** `fallbackLng: 'de'` in
 * `i18n/index.ts` fängt einen fehlenden **englischen** Text ab: Es erscheint
 * dann der deutsche, und in einer englischen Oberfläche steht plötzlich
 * Deutsch. Fehlt der Eintrag auf der **deutschen** Seite, gibt es gar keinen
 * Rückfall, und der Schlüssel selbst steht auf dem Bildschirm.
 *
 * Den Fall „fehlt in beiden" findet dieser Test nicht — dafür gibt es
 * `schluessel-vorhanden.test.ts` daneben.
 */

import { describe, expect, it } from 'vitest'

import de from './de.json'
import en from './en.json'

/** Alle Blattpfade eines verschachtelten Objekts, z. B. `konto.server`. */
function pfade(wert: unknown, praefix = ''): string[] {
  if (typeof wert !== 'object' || wert === null || Array.isArray(wert)) {
    return praefix ? [praefix] : []
  }
  return Object.entries(wert as Record<string, unknown>).flatMap(([k, v]) =>
    pfade(v, praefix ? `${praefix}.${k}` : k),
  )
}

const deutsch = new Set(pfade(de))
const englisch = new Set(pfade(en))

describe('Sprachdateien', () => {
  it('kennen beide dieselben Einträge', () => {
    const nurDeutsch = [...deutsch].filter((p) => !englisch.has(p)).sort()
    const nurEnglisch = [...englisch].filter((p) => !deutsch.has(p)).sort()

    expect(nurDeutsch, 'Nur in de.json — auf Englisch erschiene der deutsche Satz').toEqual([])
    expect(nurEnglisch, 'Nur in en.json — auf Deutsch erschiene der Schlüssel').toEqual([])
  })

  it('sind nicht versehentlich leer', () => {
    // ⚠️ Ohne diese Bodenschwelle wäre der Vergleich oben auch dann grün, wenn
    // beide Dateien kaputt geladen würden — zwei leere Mengen sind gleich.
    expect(deutsch.size).toBeGreaterThan(900)
  })

  it('haben keine leeren Texte', () => {
    // Ein leerer Text ist so unbrauchbar wie ein fehlender, fällt aber dem
    // Vergleich oben nicht auf.
    const leer = (daten: unknown, sprache: string) =>
      pfade(daten)
        .filter((pfad) => {
          const wert = pfad
            .split('.')
            .reduce<unknown>((o, k) => (o as Record<string, unknown>)?.[k], daten)
          return typeof wert === 'string' && wert.trim() === ''
        })
        .map((pfad) => `${sprache}: ${pfad}`)

    expect([...leer(de, 'de'), ...leer(en, 'en')]).toEqual([])
  })
})
