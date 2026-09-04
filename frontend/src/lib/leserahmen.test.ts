/* Was im Rahmen der fremden Mail wirklich ankommt.
 *
 * ⚠️ **`lesegrund.test.ts` prüft die Entscheidung, hier steht ihre Umsetzung.**
 * Am 04.09.2026 war die Entscheidung richtig und das Ergebnis trotzdem
 * unlesbar: Der Rahmen baute „umgekehrt" mit den Farben der Anwendung und
 * drehte dann alles um — heraus kam dunkelgrau auf fast schwarz. Sechs grüne
 * Tests der Entscheidung haben davon nichts gemerkt.
 */
import { describe, expect, it } from 'vitest'
import { leseseite } from './leserahmen'
import type { Rahmenfarben } from './leserahmen'

/** Erfundene Werte — geprüft wird der Bau, nicht die Palette. */
const FARBEN: Rahmenfarben = {
  sans: 'TestSans',
  mono: 'TestMono',
  text: 'rgb(155, 166, 165)',
  stark: 'rgb(230, 240, 240)',
  akzent: 'rgb(0, 200, 140)',
}

const seite = (grund: 'hell' | 'anwendung' | 'umgekehrt') =>
  leseseite('<p>Text ohne eigene Farbe</p>', grund, FARBEN)

const UMKEHRFILTER = 'invert(1) hue-rotate(180deg)'

describe('leseseite', () => {
  it('dreht nur den umgekehrten Grund um', () => {
    expect(seite('umgekehrt')).toContain(UMKEHRFILTER)
    expect(seite('hell')).not.toContain(UMKEHRFILTER)
    expect(seite('anwendung')).not.toContain(UMKEHRFILTER)
  })

  it('baut den umgekehrten Grund ZUERST hell', () => {
    /* ⚠️ **Der teuerste Fehler dieses Bauteils.** Die Umkehr ist ein Filter
       über dem fertigen Bild: Liegt darunter der helle Text der Anwendung,
       wird er dunkel — auf einem Grund, der auch dunkel ist. Genau so stand es
       am 04.09.2026 im Browser. */
    const s = seite('umgekehrt')
    expect(s).toContain('color: CanvasText')
    expect(s).toContain('background: Canvas')
    expect(s).not.toContain('color: var(--nm-text)')
    expect(s).not.toContain('background: transparent')
  })

  it('haelt Canvas auf hell fest, auch beim umgekehrten Grund', () => {
    /* ⚠️ `Canvas` folgt sonst dem Browser des Lesers. Steht der dunkel, wird
       daraus rgb(18,18,18) — und die Umkehr macht einen fast weißen Rand um
       die Mail. Auf einem hell eingestellten Browser sieht man davon nichts,
       und deshalb steht der Wächter hier und nicht im Auge. */
    expect(seite('umgekehrt')).toContain('color-scheme: light;')
    expect(seite('hell')).toContain('color-scheme: light;')
    expect(seite('anwendung')).toContain('color-scheme: light dark;')
  })

  it('dreht Bilder wieder zurueck', () => {
    // Ohne das stünde jedes Logo als Negativ da.
    const s = seite('umgekehrt')
    const bilderregel = s.slice(s.indexOf('img, video, svg'))
    expect(bilderregel).toContain(UMKEHRFILTER)
  })

  it('gibt der Mail auf dem Anwendungsgrund die Farben der Anwendung', () => {
    const s = seite('anwendung')
    expect(s).toContain('color: var(--nm-text)')
    expect(s).toContain('a { color: var(--nm-accent); }')
  })

  it('reicht die Variablen des Elternfensters hinein', () => {
    // Der Rahmen sieht sie nicht von selbst; ohne sie fiele die Schrift zurueck.
    const s = seite('hell')
    for (const wert of Object.values(FARBEN)) expect(s).toContain(wert)
  })

  it('laesst den Koerper unangetastet', () => {
    expect(seite('hell')).toContain('<p>Text ohne eigene Farbe</p>')
  })
})
