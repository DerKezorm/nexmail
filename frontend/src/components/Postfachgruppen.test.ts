/* Die Reihenfolge der Postfachgruppen-Reiter (Ziehen, am Konto gespeichert). */
import { describe, expect, it } from 'vitest'
import { gruppenOrdnen, verschoben } from './Postfachgruppen'

describe('gruppenOrdnen', () => {
  it('ohne eigene Reihenfolge wie die Postfächer', () => {
    expect(gruppenOrdnen(['nexapps', 'privat', 'hello'], [])).toEqual(['nexapps', 'privat', 'hello'])
  })

  it('erst die eigene Reihenfolge, neue Gruppen hinten', () => {
    expect(gruppenOrdnen(['nexapps', 'privat', 'hello', 'neu'], ['hello', 'nexapps'])).toEqual([
      'hello',
      'nexapps',
      'privat',
      'neu',
    ])
  })

  it('Groß/klein zählt nicht, Verschwundenes fällt weg', () => {
    expect(gruppenOrdnen(['Privat', 'Arbeit'], ['weg', 'arbeit', 'PRIVAT'])).toEqual(['Arbeit', 'Privat'])
  })
})

describe('verschoben', () => {
  const reihe = ['a', 'b', 'c', 'd']

  it('nach rechts landet hinter dem Ziel, nach links davor', () => {
    expect(verschoben(reihe, 'a', 'c')).toEqual(['b', 'c', 'a', 'd'])
    expect(verschoben(reihe, 'd', 'b')).toEqual(['a', 'd', 'b', 'c'])
  })

  it('auf sich selbst oder ein unbekanntes Ziel ändert nichts', () => {
    expect(verschoben(reihe, 'b', 'b')).toEqual(reihe)
    expect(verschoben(reihe, 'b', 'x')).toEqual(reihe)
  })
})
