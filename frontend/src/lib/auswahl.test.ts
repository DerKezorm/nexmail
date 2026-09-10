/* Die Regeln des Auswahlmodus der schmalen Ansicht. */
import { describe, expect, it } from 'vitest'
import {
  alleUmschalten,
  fuersMehrBlatt,
  gelesenZiel,
  LANGDRUCK_MS,
  LANGDRUCK_TOLERANZ_PX,
  sindAlleGewaehlt,
  zuWeitGewandert,
} from './auswahl'

describe('langer Druck', () => {
  it('liegt bei rund einer halben Sekunde', () => {
    /* ⚠️ Ein Band, keine Zahl: Deutlich kürzer feuert der Druck beim Rollen,
       deutlich länger fühlt er sich kaputt an. */
    expect(LANGDRUCK_MS).toBeGreaterThanOrEqual(350)
    expect(LANGDRUCK_MS).toBeLessThanOrEqual(600)
  })

  it('bricht ab, sobald der Finger über die Toleranz wandert', () => {
    expect(zuWeitGewandert(100, 100, 100 + LANGDRUCK_TOLERANZ_PX, 100)).toBe(false)
    expect(zuWeitGewandert(100, 100, 100 + LANGDRUCK_TOLERANZ_PX + 1, 100)).toBe(true)
    /* Beide Richtungen und beide Achsen — Rollen ist senkrecht, Wischen
       waagerecht, und ein Vorzeichen darf keinen Unterschied machen. */
    expect(zuWeitGewandert(100, 100, 100 - LANGDRUCK_TOLERANZ_PX - 1, 100)).toBe(true)
    expect(zuWeitGewandert(100, 100, 100, 100 + LANGDRUCK_TOLERANZ_PX + 1)).toBe(true)
    expect(zuWeitGewandert(100, 100, 100, 100 - LANGDRUCK_TOLERANZ_PX - 1)).toBe(true)
  })
})

describe('gelesenZiel', () => {
  it('macht eine ganz gelesene Auswahl ungelesen', () => {
    expect(gelesenZiel([{ gelesen: true }, { gelesen: true }])).toBe('ungelesen')
  })

  it('macht eine gemischte und eine ungelesene Auswahl gelesen', () => {
    /* ⚠️ Gemischt heißt gelesen, nicht ungelesen — Outlooks Entscheidung. */
    expect(gelesenZiel([{ gelesen: true }, { gelesen: false }])).toBe('gelesen')
    expect(gelesenZiel([{ gelesen: false }])).toBe('gelesen')
  })

  it('sagt bei leerer Auswahl gelesen, damit der Knopf nicht springt', () => {
    expect(gelesenZiel([])).toBe('gelesen')
  })
})

describe('Alle', () => {
  const sichtbare = ['1', '2', '3']

  it('nimmt alle hinein, solange eine fehlt', () => {
    expect(sindAlleGewaehlt(sichtbare, ['1', '3'])).toBe(false)
    expect(alleUmschalten(sichtbare, ['1', '3'])).toEqual(['1', '2', '3'])
    expect(alleUmschalten(sichtbare, [])).toEqual(['1', '2', '3'])
  })

  it('nimmt alle heraus, wenn schon alle drin sind', () => {
    expect(sindAlleGewaehlt(sichtbare, ['3', '2', '1'])).toBe(true)
    expect(alleUmschalten(sichtbare, ['3', '2', '1'])).toEqual([])
  })

  it('kennt bei leerer Liste kein Alle', () => {
    /* Sonst hieße der Knopf „Keine", obwohl es nichts zu nehmen gibt. */
    expect(sindAlleGewaehlt([], [])).toBe(false)
    expect(alleUmschalten([], [])).toEqual([])
  })

  it('zählt nur die sichtbaren, nicht alte Kennungen in der Auswahl', () => {
    expect(sindAlleGewaehlt(sichtbare, ['1', '2', '3', 'weg'])).toBe(true)
  })
})

describe('fuersMehrBlatt', () => {
  const menue = [
    { id: 'antworten' },
    { id: 'allen' },
    { id: 'weiter' },
    { id: 'anhang' },
    { id: 'drucken' },
    { id: 'gelesen' },
    { id: 'markieren' },
    { id: 'schlagwort' },
    { id: 'aufgabe' },
    { id: 'wiedervorlage' },
    { id: 'verschieben' },
    { id: 'archivieren' },
    { id: 'junk' },
    { id: 'regel', deaktiviert: true },
    { id: 'loeschen' },
  ]

  it('lässt weg, was die Leiste trägt, was nur einzeln geht und den Regel-Platzhalter', () => {
    expect(fuersMehrBlatt(menue).map((e) => e.id)).toEqual([
      'markieren',
      'schlagwort',
      'aufgabe',
      'wiedervorlage',
      'junk',
    ])
  })
})
