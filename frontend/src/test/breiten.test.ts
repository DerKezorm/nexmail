/**
 * Die Breiten-Ausnahmen stehen an zwei Stellen und müssen dasselbe sagen.
 *
 * ⚠️ **Warum es zwei Stellen sind.** Eine Datei, die ihre Tests im
 * `beforeEach` für ein Projekt überspringt, hat trotzdem für jeden dieser
 * Tests einen Browser aufgemacht, eine Ablaufaufzeichnung begonnen und alles
 * wieder abgeräumt. Gemessen am 03.09.2026: rund 2,2 Sekunden je Test, der
 * nichts tut, bei 55 solchen Tests also gut zwei Minuten je Lauf. Deshalb
 * stehen die Dateien zusätzlich in `testIgnore` des jeweiligen Projekts —
 * dann kommt Playwright gar nicht erst so weit.
 *
 * ⚠️ **Das `test.skip` bleibt trotzdem stehen**, und zwar mit Absicht: Es
 * trägt den Grund dort, wo man ihn sucht, und es fängt den Fall ab, dass
 * jemand `testIgnore` vergisst. Zwei Listen, die auseinanderlaufen können,
 * brauchen aber einen Wächter — und das ist dieser Test.
 *
 * ⚠️ **Es fällt sonst nicht auf.** Eine vergessene `testIgnore`-Zeile macht
 * den Lauf nur langsamer, nicht rot. Eine zu viel dagegen nimmt eine echte
 * Prüfung weg, und auch das meldet niemand.
 */

import { describe, expect, it } from 'vitest'

const SPECS = import.meta.glob('../../tests/*.spec.ts', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>

const KONFIG = Object.values(
  import.meta.glob('../../playwright.config.ts', {
    query: '?raw',
    eager: true,
    import: 'default',
  }) as Record<string, string>,
)[0]

/** Aus `const NUR_BREIT = ['a.spec.ts', …]` die Dateinamen holen. */
function liste(name: string): string[] {
  const treffer = new RegExp(`const ${name}[^=]*=\\s*\\[([^\\]]*)\\]`, 's').exec(KONFIG ?? '')
  if (!treffer) return []
  return [...treffer[1].matchAll(/'([^']+)'/g)].map((m) => m[1]).sort()
}

/** Dateien, deren `beforeEach` alle Tests für ein Projekt überspringt. */
function ausnahmen(): { nurBreit: string[]; nurSchmal: string[] } {
  const nurBreit: string[] = []
  const nurSchmal: string[] = []
  for (const [pfad, inhalt] of Object.entries(SPECS)) {
    const name = pfad.split('/').pop() as string
    const block = /test\.beforeEach\([\s\S]*?\n\}\)/.exec(inhalt)?.[0] ?? ''
    if (/project\.name === 'schmal'/.test(block)) nurBreit.push(name)
    else if (/project\.name !== 'schmal'/.test(block)) nurSchmal.push(name)
  }
  return { nurBreit: nurBreit.sort(), nurSchmal: nurSchmal.sort() }
}

describe('Breiten-Ausnahmen', () => {
  it('findet die Dateien überhaupt', () => {
    // Bodenschwelle: Greift das Muster ins Leere, wären alle Vergleiche
    // darunter der Vergleich zweier leerer Listen.
    expect(Object.keys(SPECS).length).toBeGreaterThan(15)
    expect(KONFIG, 'playwright.config.ts nicht gefunden').toBeTruthy()
    expect(ausnahmen().nurBreit.length).toBeGreaterThan(5)
  })

  it('stehen für die breite Ansicht in beiden Listen', () => {
    expect(
      ausnahmen().nurBreit,
      'Diese Dateien überspringen sich im schmalen Lauf. Sie gehören in ' +
        'NUR_BREIT, sonst startet Playwright für jeden Test einen Browser, ' +
        'nur um ihn zu überspringen.',
    ).toEqual(liste('NUR_BREIT'))
  })

  it('stehen für die schmale Ansicht in beiden Listen', () => {
    expect(ausnahmen().nurSchmal).toEqual(liste('NUR_SCHMAL'))
  })
})
