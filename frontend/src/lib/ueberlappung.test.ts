/* Wie sich gleichzeitige Termine die Breite teilen. */
import { describe, expect, it } from 'vitest'
import { nebeneinander } from './ueberlappung'

/** Kurzschreibweise: `u(9, 10)` ist 09:00 bis 10:00 am selben Tag. */
const u = (vonStd: number, bisStd: number, vonMin = 0, bisMin = 0) => ({
  beginn: `2026-09-04T${String(vonStd).padStart(2, '0')}:${String(vonMin).padStart(2, '0')}:00Z`,
  ende: `2026-09-04T${String(bisStd).padStart(2, '0')}:${String(bisMin).padStart(2, '0')}:00Z`,
})

describe('nebeneinander', () => {
  it('laesst einen einzelnen Termin die ganze Breite haben', () => {
    expect(nebeneinander([u(9, 10)])).toEqual([{ spalte: 0, spalten: 1 }])
  })

  it('teilt zwei gleichzeitige Termine in zwei Spalten', () => {
    /* ⚠️ **Der ganze Anlass.** Vorher lagen sie exakt uebereinander, und der
       obere verbarg den unteren restlos — das sieht aus wie verloren. */
    const lagen = nebeneinander([u(9, 10), u(9, 10)])
    expect(lagen.map((l) => l.spalten)).toEqual([2, 2])
    expect(lagen.map((l) => l.spalte).sort()).toEqual([0, 1])
  })

  it('laesst zwei Termine, die sich nur beruehren, nebeneinander in Ruhe', () => {
    /* ⚠️ **`<=`, nicht `<`.** Ein Termin, der genau dann beginnt, wenn der
       vorige endet, ueberschneidet sich nicht. Sonst rutschte eine
       lueckenlose Tagesplanung in immer neue Spalten und waere am Ende
       fingerbreit. */
    const lagen = nebeneinander([u(9, 10), u(10, 11)])
    expect(lagen).toEqual([
      { spalte: 0, spalten: 1 },
      { spalte: 0, spalten: 1 },
    ])
  })

  it('haelt eine Kette zusammen, auch wo sich die Enden nicht beruehren', () => {
    /* ⚠️ **Die Gruppe ist transitiv.** A ueberschneidet B, B ueberschneidet C,
       A und C nicht — trotzdem gehoeren alle drei zusammen. Rechnete C mit
       einer anderen Breite als A, laegen die Bloecke wieder uebereinander. */
    const lagen = nebeneinander([u(9, 10), u(9, 10, 30, 30), u(10, 11)])
    expect(lagen.map((l) => l.spalten)).toEqual([2, 2, 2])
    expect(lagen.map((l) => l.spalte)).toEqual([0, 1, 0])
  })

  it('macht aus drei gleichzeitigen drei Spalten', () => {
    const lagen = nebeneinander([u(9, 12), u(9, 12), u(9, 12)])
    expect(lagen.map((l) => l.spalten)).toEqual([3, 3, 3])
    expect(lagen.map((l) => l.spalte).sort()).toEqual([0, 1, 2])
  })

  it('stellt bei gleichem Beginn den laengeren nach links', () => {
    /* ⚠️ **Sonst haengt es an der Reihenfolge des Servers**, welcher Termin
       links steht — und die kann sich zwischen zwei Abrufen aendern. Der
       Kalender saehe dann bei jedem Neuladen anders aus. */
    const kurz = u(9, 10)
    const lang = u(9, 12)
    expect(nebeneinander([kurz, lang]).map((l) => l.spalte)).toEqual([1, 0])
    expect(nebeneinander([lang, kurz]).map((l) => l.spalte)).toEqual([0, 1])
  })

  it('gibt die Lagen in der Reihenfolge der Eingabe zurueck', () => {
    /* ⚠️ Gerechnet wird auf einer sortierten Kopie. Wer die sortierte Liste
       zurueckgaebe, brächte die Ansicht durcheinander. */
    const spaet = u(14, 15)
    const frueh = u(9, 10)
    const lagen = nebeneinander([spaet, frueh])
    expect(lagen).toHaveLength(2)
    expect(lagen[0]).toEqual({ spalte: 0, spalten: 1 })
    expect(lagen[1]).toEqual({ spalte: 0, spalten: 1 })
  })

  it('faengt eine leere Liste ab', () => {
    expect(nebeneinander([])).toEqual([])
  })

  it('trennt zwei Gruppen, die nichts miteinander zu tun haben', () => {
    // Vormittags zwei, nachmittags zwei — die Breite gilt je Gruppe.
    const lagen = nebeneinander([u(9, 10), u(9, 10), u(14, 15)])
    expect(lagen.map((l) => l.spalten)).toEqual([2, 2, 1])
  })
})
