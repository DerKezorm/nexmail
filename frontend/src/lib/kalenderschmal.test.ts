/* Die Rechnung der schmalen Kalenderansicht. */
import { describe, expect, it } from 'vitest'
import { farbpunkte, monatsraster, nachTagen, tagesliste } from './kalenderschmal'
import { alsDatum } from './kalendertage'

/** Ein zeitgebundenes Vorkommen an einem Tag, Ortszeit. */
function um(tag: string, von: string, bis: string, kalenderId = 'a') {
  return {
    beginn: new Date(`${tag}T${von}:00`).toISOString(),
    ende: new Date(`${tag}T${bis}:00`).toISOString(),
    ganztaegig: false,
    kalenderId,
  }
}

/** Ein ganztägiges Vorkommen — als Datum, das Ende ausschließend. */
function ganz(von: string, bisAusschl: string, kalenderId = 'a') {
  return { beginn: `${von}T00:00:00Z`, ende: `${bisAusschl}T00:00:00Z`, ganztaegig: true, kalenderId }
}

describe('monatsraster', () => {
  it('beginnt am Montag vor dem Ersten und endet am Sonntag nach dem Letzten', () => {
    /* September 2026: der 1. ist ein Dienstag, der 30. ein Mittwoch. */
    const tage = monatsraster(new Date(2026, 8, 10))
    expect(alsDatum(tage[0])).toBe('2026-08-31')
    expect(alsDatum(tage[tage.length - 1])).toBe('2026-10-04')
    expect(tage.length).toBe(35)
  })

  it('hat vier, fünf oder sechs Zeilen, nie eine feste sechste', () => {
    /* Februar 2027: der 1. ist ein Montag, der 28. ein Sonntag — vier Zeilen. */
    expect(monatsraster(new Date(2027, 1, 1)).length).toBe(28)
    /* August 2026: der 1. ist ein Samstag, der 31. ein Montag — sechs Zeilen. */
    expect(monatsraster(new Date(2026, 7, 15)).length).toBe(42)
  })

  it('zählt ganze Wochen, auch über die Zeitumstellung', () => {
    /* Oktober 2026 enthält die Umstellung am 25. — jeder Tag muss genau
       einmal vorkommen, keiner doppelt, keiner übersprungen. */
    const tage = monatsraster(new Date(2026, 9, 1))
    const namen = tage.map(alsDatum)
    expect(new Set(namen).size).toBe(namen.length)
    expect(namen.length % 7).toBe(0)
    expect(namen).toContain('2026-10-25')
    expect(namen).toContain('2026-10-26')
  })
})

describe('tagesliste', () => {
  it('stellt ganztägige vor die zeitgebundenen, den Rest nach Beginn', () => {
    const termine = [
      um('2026-09-10', '14:00', '15:00'),
      um('2026-09-10', '09:00', '09:30'),
      ganz('2026-09-10', '2026-09-11'),
    ]
    const liste = tagesliste(termine, new Date(2026, 8, 10))
    expect(liste.map((e) => (e.ganztaegig ? 'ganz' : e.beginn))).toEqual([
      'ganz',
      termine[1].beginn,
      termine[0].beginn,
    ])
  })

  it('lässt weg, was an einem anderen Tag liegt', () => {
    const termine = [um('2026-09-09', '10:00', '11:00'), um('2026-09-11', '10:00', '11:00')]
    expect(tagesliste(termine, new Date(2026, 8, 10))).toEqual([])
  })

  it('zeigt einen mehrtägigen ganztägigen an jedem seiner Tage, nicht am Tag danach', () => {
    const termine = [ganz('2026-09-10', '2026-09-12')]
    expect(tagesliste(termine, new Date(2026, 8, 10)).length).toBe(1)
    expect(tagesliste(termine, new Date(2026, 8, 11)).length).toBe(1)
    expect(tagesliste(termine, new Date(2026, 8, 12)).length).toBe(0)
  })
})

describe('farbpunkte', () => {
  it('nennt jeden Kalender einmal, in der Reihenfolge des ersten Vorkommens', () => {
    const termine = [
      um('2026-09-10', '10:00', '11:00', 'b'),
      um('2026-09-10', '12:00', '13:00', 'a'),
      um('2026-09-10', '14:00', '15:00', 'b'),
    ]
    expect(farbpunkte(termine, new Date(2026, 8, 10))).toEqual(['b', 'a'])
  })

  it('hört bei drei auf', () => {
    const termine = ['a', 'b', 'c', 'd'].map((k, i) =>
      um('2026-09-10', `1${i}:00`, `1${i}:30`, k),
    )
    expect(farbpunkte(termine, new Date(2026, 8, 10))).toEqual(['a', 'b', 'c'])
  })

  it('ist an einem leeren Tag leer', () => {
    expect(farbpunkte([um('2026-09-09', '10:00', '11:00')], new Date(2026, 8, 10))).toEqual([])
  })
})

describe('nachTagen', () => {
  const termine = [
    um('2026-09-10', '10:00', '11:00'),
    um('2026-09-12', '10:00', '11:00'),
    um('2026-09-12', '08:00', '09:00'),
    um('2026-09-15', '10:00', '11:00'),
  ]

  it('lässt Tage ohne Termin weg und sortiert je Tag', () => {
    const tage = nachTagen(termine, new Date(2026, 8, 10), new Date(2026, 8, 15))
    expect(tage.map((t) => alsDatum(t.tag))).toEqual(['2026-09-10', '2026-09-12'])
    expect(tage[1].termine.map((e) => e.beginn)).toEqual([termine[2].beginn, termine[1].beginn])
  })

  it('nimmt das Ende ausschließend', () => {
    /* ⚠️ Der 15. liegt genau auf `bis` und darf nicht mehr erscheinen —
       sonst stünde der erste Tag des nächsten Monats unter diesem Monat. */
    const tage = nachTagen(termine, new Date(2026, 8, 1), new Date(2026, 8, 15))
    expect(tage.map((t) => alsDatum(t.tag))).not.toContain('2026-09-15')
    const mit = nachTagen(termine, new Date(2026, 8, 1), new Date(2026, 8, 16))
    expect(mit.map((t) => alsDatum(t.tag))).toContain('2026-09-15')
  })

  it('verträgt Uhrzeiten in den Grenzen', () => {
    const tage = nachTagen(termine, new Date(2026, 8, 10, 15, 30), new Date(2026, 8, 13, 2))
    expect(tage.map((t) => alsDatum(t.tag))).toEqual(['2026-09-10', '2026-09-12'])
  })
})
