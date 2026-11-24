/* Postfachfarben wie nextasks (24.11.2026): benannte Töne, eigene lesbar gemacht. */
import { describe, expect, it } from 'vitest'
import { FARBTOENE, lesbar, tonVon } from './farbtoene'

describe('tonVon', () => {
  it('leer heißt: die automatische Postfachfarbe (null)', () => {
    expect(tonVon('')).toBeNull()
    expect(tonVon(undefined)).toBeNull()
  })

  it('kennt die elf Namen aus nextasks', () => {
    expect(Object.keys(FARBTOENE)).toHaveLength(11)
    expect(tonVon('teal')).toBe('#22a08a')
    expect(tonVon('lila')).toBeNull()
  })

  it('lässt eine gut lesbare eigene Farbe, wie sie ist', () => {
    expect(tonVon('#3a84d0')).toBe('#3a84d0')
  })

  it('macht fast Schwarz und fast Weiß lesbar, statt sie verschwinden zu lassen', () => {
    expect(lesbar('#050505')).not.toBe('#050505')
    expect(lesbar('#fafafa')).not.toBe('#fafafa')
  })
})
