/**
 * Jeder Schlüssel, den der Code nachschlägt, muss es auch geben.
 *
 * ⚠️ **Aus Schaden entstanden, 03.09.2026.** Auf der Verwaltungsseite standen
 * vier rohe Schlüssel als Beschriftungen: `konto.smtp_server`,
 * `konto.verschluesselung`, `konto.benutzername` und `konto.keine`. i18next
 * gibt bei einem unbekannten Schlüssel still den Schlüssel zurück; nichts
 * schlägt fehl, nichts wird rot. Nur der Betreiber liest Kauderwelsch.
 *
 * ⚠️ **Den Wächter dafür gibt es längst, und er kam nie dorthin.**
 * `keineRohenSchluessel(page)` in den Oberflächen-Tests hätte sie gefunden —
 * er läuft in `mehrbenutzer.spec.ts` sogar auf der Verwaltungsseite, aber im
 * Reiter *Benutzer*. Der Postausgang steht in einem anderen Reiter und ist
 * dann gar nicht im Dokument. Ein Browser-Test sieht, was er öffnet; dieser
 * Test hier sieht alles, in Millisekunden.
 *
 * ⚠️ **Das ersetzt den Browser-Test nicht.** Er prüft, was wirklich gezeichnet
 * wird, samt zusammengesetzten Schlüsseln, die kein Textvergleich auflöst.
 * Hier steht die zweite Ebene daneben, nicht an seiner Stelle.
 *
 * Geprüft werden nur **wörtliche** Schlüssel. Zusammengesetzte
 * (`t('kalender.antwort_' + stand)`) kann kein Test auflösen; sie fallen
 * bewusst durch, statt eine Ausnahmeliste zu erzwingen, die jemand pflegen
 * müsste.
 */

import { describe, expect, it } from 'vitest'

import de from './de.json'
import en from './en.json'

/** Alle Knoten, nicht nur die Blätter — `t(..., { returnObjects: true })`
 *  holt ganze Teilbäume. */
function knoten(wert: unknown, praefix = ''): string[] {
  if (typeof wert !== 'object' || wert === null || Array.isArray(wert)) {
    return praefix ? [praefix] : []
  }
  return Object.entries(wert as Record<string, unknown>).flatMap(([k, v]) => {
    const pfad = praefix ? `${praefix}.${k}` : k
    return [pfad, ...knoten(v, pfad)]
  })
}

/** i18next hängt bei `{ count }` eine Endung an. Beide Schreibweisen zählen. */
const PLURAL = ['', '_one', '_other', '_zero', '_two', '_few', '_many']

function kennt(menge: Set<string>, schluessel: string): boolean {
  return PLURAL.some((endung) => menge.has(schluessel + endung))
}

const deutsch = new Set(knoten(de))
const englisch = new Set(knoten(en))

const DATEIEN = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>

/** `t('a.b')` oder `t("a.b", …)` — mindestens ein Punkt, sonst ist es keiner. */
const AUFRUF = /\bt\(\s*(['"])([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)\1\s*[,)]/g

/** Diese Datei nennt zwangsläufig Schlüssel, die es nicht gibt. */
const AUSGENOMMEN = /schluessel-vorhanden\.test\.ts$/

function gefundeneSchluessel(): Array<{ schluessel: string; datei: string }> {
  const treffer: Array<{ schluessel: string; datei: string }> = []
  for (const [datei, inhalt] of Object.entries(DATEIEN)) {
    if (AUSGENOMMEN.test(datei)) continue
    for (const m of inhalt.matchAll(AUFRUF)) {
      treffer.push({ schluessel: m[2], datei })
    }
  }
  return treffer
}

describe('Übersetzungsschlüssel', () => {
  /**
   * ⚠️ **Zuerst prüfen, dass überhaupt etwas geprüft wird.** Greift das Muster
   * ins Leere, bestünde die Regel darunter mit einer leeren Liste — ein
   * Wächter, der nichts sieht, meldet lebenslang „alles in Ordnung".
   */
  it('findet die Aufrufe überhaupt', () => {
    expect(Object.keys(DATEIEN).length).toBeGreaterThan(50)
    expect(gefundeneSchluessel().length).toBeGreaterThan(500)
  })

  it('erkennt einen erfundenen Schlüssel', () => {
    // Ohne das wäre nicht bewiesen, dass `kennt` überhaupt Nein sagen kann.
    expect(kennt(deutsch, 'gibt.es.nicht')).toBe(false)
    expect(kennt(deutsch, 'aktion.abbrechen')).toBe(true)
  })

  it('gibt es alle, in beiden Sprachen', () => {
    const fehlend: string[] = []
    for (const { schluessel, datei } of gefundeneSchluessel()) {
      const kurz = datei.replace(/^\.\.\//, 'src/')
      if (!kennt(deutsch, schluessel)) fehlend.push(`de.json: ${schluessel}   (${kurz})`)
      if (!kennt(englisch, schluessel)) fehlend.push(`en.json: ${schluessel}   (${kurz})`)
    }

    expect(
      [...new Set(fehlend)].sort(),
      'Diese Schlüssel schlägt der Code nach, aber es gibt sie nicht. ' +
        'Auf dem Bildschirm steht dann der Schlüssel selbst.',
    ).toEqual([])
  })
})
