import { describe, expect, it } from 'vitest'
import {
  artSetzen,
  auswahlWert,
  beschriftungText,
  etwasDrin,
  felderAusKontakt,
  leereFelder,
  neueNummer,
  sternSetzen,
  zeileEntfernen,
  zeileHinzufuegen,
} from './kontaktfelder'

const n = (nummer: string, bevorzugt = false, art = 'home', beschriftung = '') => ({
  nummer,
  art,
  beschriftung,
  bevorzugt,
})

describe('der Stern', () => {
  it('sitzt auf genau einer Zeile', () => {
    const liste = sternSetzen([n('1', true), n('2'), n('3')], 2)
    expect(liste.map((e) => e.bevorzugt)).toEqual([false, false, true])
  })

  it('wandert auf die erste Zeile, wenn seine Zeile faellt', () => {
    const liste = zeileEntfernen([n('1', true), n('2'), n('3')], 0)
    expect(liste.map((e) => e.nummer)).toEqual(['2', '3'])
    expect(liste.map((e) => e.bevorzugt)).toEqual([true, false])
  })

  it('bleibt, wo er ist, wenn eine andere Zeile faellt', () => {
    const liste = zeileEntfernen([n('1'), n('2', true), n('3')], 0)
    expect(liste.map((e) => e.bevorzugt)).toEqual([true, false])
  })

  it('kommt auf die erste Zeile einer leeren Liste, nicht auf jede weitere', () => {
    const eine = zeileHinzufuegen([], n('1'))
    expect(eine[0].bevorzugt).toBe(true)
    const zwei = zeileHinzufuegen(eine, n('2', true))
    expect(zwei.map((e) => e.bevorzugt)).toEqual([true, false])
  })
})

describe('die Auswahl der Art', () => {
  it('zeigt „Eigene …“, sobald eine Beschriftung da ist', () => {
    expect(auswahlWert(n('1', false, 'cell'))).toBe('cell')
    expect(auswahlWert(n('1', false, '', 'Zweitbüro'))).toBe('eigen')
    expect(auswahlWert(n('1', false, ''))).toBe('other')
  })

  it('merkt sich „Eigene …“, bis ein Text dasteht, und leert die Beschriftung bei einer Art', () => {
    const eigen = artSetzen(n('1', false, 'cell'), 'eigen')
    expect(auswahlWert(eigen)).toBe('eigen')
    expect(eigen.beschriftung).toBe('')
    const zurueck = artSetzen({ ...eigen, beschriftung: 'Zweitbüro' }, 'work')
    expect([zurueck.art, zurueck.beschriftung]).toEqual(['work', ''])
  })

  it('die erste Nummer ist ein Handy, jede weitere Festnetz', () => {
    expect(neueNummer([]).art).toBe('cell')
    expect(neueNummer([n('1')]).art).toBe('home')
  })
})

describe('die Beschriftung einer Zeile', () => {
  const t = (s: string) => `[${s}]`
  const kennt = (s: string) => s === 'kontakte.art_cell' || s === 'kontakte.apple_mother'

  it('nimmt die eigene, uebersetzt Apples Woerter und sonst die Art', () => {
    expect(beschriftungText(n('1', false, '', 'Zweitbüro'), t, kennt)).toBe('Zweitbüro')
    expect(beschriftungText(n('1', false, '', 'Mother'), t, kennt)).toBe('[kontakte.apple_mother]')
    expect(beschriftungText(n('1', false, 'cell'), t, kennt)).toBe('[kontakte.art_cell]')
    expect(beschriftungText(n('1', false, ''), t, kennt)).toBe('')
  })
})

describe('die Felder', () => {
  it('kommen als eigene Kopie aus der Zeile', () => {
    const zeile = { ...leereFelder(), vorname: 'Anna', nummern: [n('1', true)] }
    const felder = felderAusKontakt(zeile)
    felder.nummern[0].nummer = '2'
    expect(zeile.nummern[0].nummer).toBe('1')
    expect(felder.vorname).toBe('Anna')
  })

  it('wissen, ob etwas drin ist', () => {
    expect(etwasDrin(leereFelder())).toBe(false)
    expect(etwasDrin({ ...leereFelder(), nummern: [n(' ')] })).toBe(false)
    expect(etwasDrin({ ...leereFelder(), firma: 'Beispiel GmbH' })).toBe(true)
  })
})
