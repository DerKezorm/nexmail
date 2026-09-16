import { describe, expect, it } from 'vitest'
import { lesemodusAus, naechsterLesemodus } from './lesemodus'

describe('Lesemodus', () => {
  it('der Knopf geht reihum durch alle drei und wieder zum Anfang', () => {
    expect(naechsterLesemodus('rechts')).toBe('ganz')
    expect(naechsterLesemodus('ganz')).toBe('fenster')
    expect(naechsterLesemodus('fenster')).toBe('rechts')
  })

  it('ein unbekannter gemerkter Wert ist der Lesebereich rechts', () => {
    expect(lesemodusAus('fenster')).toBe('fenster')
    expect(lesemodusAus('ganz')).toBe('ganz')
    expect(lesemodusAus('unten')).toBe('rechts')
    expect(lesemodusAus(null)).toBe('rechts')
    expect(lesemodusAus(3)).toBe('rechts')
  })
})
