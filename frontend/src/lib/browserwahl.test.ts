import { describe, expect, it } from 'vitest'

import { gespeicherteBrowserwahl } from './browserwahl'

const speicher = (werte: Record<string, string>) => ({ getItem: (k: string) => werte[k] ?? null })

describe('gespeicherteBrowserwahl (E45)', () => {
  it('gibt den gespeicherten Wert roh weiter', () => {
    expect(gespeicherteBrowserwahl(speicher({ 'nexmail.modus': '"light"' }))).toBe('"light"')
  })

  it('ohne gespeicherten Wert leer, nie die Vorgabe der Seite', () => {
    expect(gespeicherteBrowserwahl(speicher({}))).toBe('')
  })

  it('ein gesperrter Speicher ist kein Fehler', () => {
    expect(gespeicherteBrowserwahl({ getItem: () => { throw new Error('gesperrt') } })).toBe('')
  })
})
