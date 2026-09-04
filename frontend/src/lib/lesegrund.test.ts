/* Der Grund, auf dem eine fremde Mail steht.
 *
 * ⚠️ **Hier wird eine Mail unlesbar, nicht hässlich.** Der Fehler, der hier
 * lauert, ist Dunkelgrau auf Fast-Schwarz — am 02.09.2026 an einer echten Mail
 * gemessen: Kontrast 1,53:1. Man sieht dann nichts, und es sieht nicht nach
 * einem Fehler aus, sondern nach einer leeren Mail.
 */
import { describe, expect, it } from 'vitest'
import { lesegrund } from './lesegrund'
import type { Umstaende } from './lesegrund'

/** Der Normalfall: Newsletter mit eigenen Farben, App dunkel, Eindunkeln an. */
const NEWSLETTER: Umstaende = {
  faerbtSichSelbst: true,
  umgeschaltet: false,
  dunkelmodus: true,
  eindunkeln: true,
}

const mit = (teil: Partial<Umstaende>): Umstaende => ({ ...NEWSLETTER, ...teil })

describe('lesegrund', () => {
  it('kehrt einen Newsletter um, statt ein weißes Blatt zu zeigen', () => {
    expect(lesegrund(NEWSLETTER)).toBe('umgekehrt')
  })

  it('zeigt ohne die Einstellung weiter das weiße Blatt', () => {
    // Der Zustand vor dem 04.09.2026 — und die Vorgabe.
    expect(lesegrund(mit({ eindunkeln: false }))).toBe('hell')
  })

  it('kehrt im hellen Modus nie um', () => {
    /* ⚠️ Dort ist das weiße Blatt richtig; eine Umkehr machte eine dunkle
       Insel mitten in einer hellen Anwendung. */
    expect(lesegrund(mit({ dunkelmodus: false }))).toBe('hell')
    expect(lesegrund(mit({ dunkelmodus: false, umgeschaltet: true }))).toBe('hell')
  })

  it('faerbt eine Mail ohne eigene Farben nicht um, sondern nutzt die der App', () => {
    /* ⚠️ **Der teure Fehler waere hier.** Diese Mail traegt die Farben der
       Anwendung und ist schon dunkel; sie zusaetzlich umzukehren machte sie
       hell — und den Text unlesbar. */
    expect(lesegrund(mit({ faerbtSichSelbst: false }))).toBe('anwendung')
    expect(lesegrund(mit({ faerbtSichSelbst: false, eindunkeln: false }))).toBe('anwendung')
  })

  it('laesst den Umschalter je Mail immer das letzte Wort haben', () => {
    // Umgekehrt -> hell, wenn die Umkehr bei dieser Mail danebengeht.
    expect(lesegrund(mit({ umgeschaltet: true }))).toBe('hell')
    // Hell -> Anwendungsfarben, wenn die Mail damit besser aussieht.
    expect(lesegrund(mit({ eindunkeln: false, umgeschaltet: true }))).toBe('anwendung')
    // Und bei einer Mail ohne eigene Farben zurueck aufs weisse Blatt.
    expect(lesegrund(mit({ faerbtSichSelbst: false, umgeschaltet: true }))).toBe('hell')
  })

  it('bietet in jedem Zustand einen Weg zum jeweils anderen Grund', () => {
    /* ⚠️ **Ein Umschalter, der nichts aendert, ist ein kaputter Knopf.** In
       jeder Lage muss er auf etwas anderes fuehren als den aktuellen Grund —
       ausser im hellen Modus, wo es nichts umzuschalten gibt. */
    for (const faerbt of [true, false]) {
      for (const ein of [true, false]) {
        const aus = lesegrund(mit({ faerbtSichSelbst: faerbt, eindunkeln: ein }))
        const an = lesegrund(
          mit({ faerbtSichSelbst: faerbt, eindunkeln: ein, umgeschaltet: true }),
        )
        expect(an).not.toBe(aus)
      }
    }
  })
})
