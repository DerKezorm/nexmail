import { describe, expect, it } from 'vitest'
import { danachAus, danachWaehlen } from './danach'

const ALT = ['a', 'b', 'c', 'd', 'e']

describe('Was nach einer Handlung aufgeht', () => {
  it('ab Werk und bei allem Unbekannten geht nichts auf', () => {
    expect(danachAus(null)).toBe('nichts')
    expect(danachAus('unten')).toBe('nichts')
    expect(danachAus('vorige')).toBe('vorige')
    expect(danachWaehlen('nichts', ALT, ['a', 'b', 'd', 'e'], 'c')).toBeNull()
  })

  it('nächste ist die Zeile darunter, vorige die darüber, neueste die oberste', () => {
    const neu = ['a', 'b', 'd', 'e']
    expect(danachWaehlen('naechste', ALT, neu, 'c')).toBe('d')
    expect(danachWaehlen('vorige', ALT, neu, 'c')).toBe('b')
    expect(danachWaehlen('neueste', ALT, neu, 'c')).toBe('a')
  })

  it('bei einer Mehrfachauswahl zählt der Nachbar, der übrig bleibt', () => {
    // b, c und d sind weg, c war offen.
    const neu = ['a', 'e']
    expect(danachWaehlen('naechste', ALT, neu, 'c')).toBe('e')
    expect(danachWaehlen('vorige', ALT, neu, 'c')).toBe('a')
  })

  it('neue Post oben verschiebt den Nachbarn nicht', () => {
    const neu = ['x', 'y', 'a', 'b', 'd', 'e']
    expect(danachWaehlen('naechste', ALT, neu, 'c')).toBe('d')
    expect(danachWaehlen('vorige', ALT, neu, 'c')).toBe('b')
    expect(danachWaehlen('neueste', ALT, neu, 'c')).toBe('x')
  })

  it('am Ende der Liste geht nichts auf, auch nicht die andere Richtung', () => {
    expect(danachWaehlen('naechste', ALT, ['a', 'b', 'c', 'd'], 'e')).toBeNull()
    expect(danachWaehlen('vorige', ALT, ['b', 'c', 'd', 'e'], 'a')).toBeNull()
  })

  it('die oberste weg: nächste ist die neue oberste', () => {
    expect(danachWaehlen('naechste', ALT, ['b', 'c', 'd', 'e'], 'a')).toBe('b')
  })

  it('steht die offene Mail noch da, bleibt sie offen', () => {
    expect(danachWaehlen('naechste', ALT, ALT, 'c')).toBe('c')
    expect(danachWaehlen('neueste', ALT, ALT, 'c')).toBe('c')
  })

  it('war nichts offen, geht nichts auf', () => {
    expect(danachWaehlen('naechste', ALT, ['a', 'b'], null)).toBeNull()
    expect(danachWaehlen('neueste', ALT, ['a', 'b'], null)).toBeNull()
  })

  it('eine leere Liste danach öffnet nichts', () => {
    expect(danachWaehlen('naechste', ['c'], [], 'c')).toBeNull()
    expect(danachWaehlen('vorige', ['c'], [], 'c')).toBeNull()
    expect(danachWaehlen('neueste', ['c'], [], 'c')).toBeNull()
  })
})
