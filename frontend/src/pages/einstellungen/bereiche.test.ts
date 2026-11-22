/* Wer welche Bereiche der Einstellungen sieht — dieselben Grenzen wie vor dem
 * Umbau vom 22.11.2026: Die Verwaltung (jetzt „Server") nur der Betreiber,
 * die KI der Betreiber immer und sonst nur mit `ki_erlaubt`. Neu ist nur
 * „Über nexmail" für jeden (wie nexnotes). */
import { describe, expect, it } from 'vitest'
import type { Ich } from '../../api/client'
import { BEREICHE, bereicheFuer, erlaubterBereich, ueberSichtbar } from './bereiche'

function ich(teil: Partial<Ich>): Ich {
  return {
    id: 'x',
    benutzername: 'x',
    anzeigename: 'X',
    ist_betreiber: false,
    zwei_faktor_aktiv: false,
    offene_codes: 0,
    kontaktadresse: '',
    ki_aktiv: false,
    ki_erlaubt: false,
    ki_fremde_post: false,
    absenderlogos: false,
    version: '0',
    wasneu_gesehen: '0',
    ...teil,
  }
}

const ids = (i: Ich) => bereicheFuer(i).map((b) => b.id)
const SERVER = ['allgemein', 'anmeldung', 'mailversand', 'speicher', 'konten', 'log']

describe('Sichtbarkeit der Bereiche', () => {
  it('der Betreiber sieht alles', () => {
    expect(ids(ich({ ist_betreiber: true }))).toEqual(BEREICHE.map((b) => b.id))
    expect(ueberSichtbar(ich({ ist_betreiber: true }))).toBe(true)
  })

  it('ein Benutzer sieht keinen Bereich der Gruppe Server', () => {
    const sieht = ids(ich({}))
    for (const s of SERVER) expect(sieht).not.toContain(s)
    // Alles, was vorher in seinen eigenen Einstellungen stand, bleibt.
    for (const b of ['profil', 'sicherheit', 'darstellung', 'benachrichtigungen', 'verbindungen',
      'postfaecher', 'regeln', 'signaturen', 'abwesenheit', 'schlagworte'] as const) {
      expect(sieht).toContain(b)
    }
  })

  it('KI nur mit Erlaubnis, wie vorher der Punkt in der Leiste', () => {
    expect(ids(ich({}))).not.toContain('ki')
    expect(ids(ich({ ki_erlaubt: true }))).toContain('ki')
  })

  it('„Über nexmail" sieht jeder Angemeldete', () => {
    expect(ueberSichtbar(ich({}))).toBe(true)
    expect(ueberSichtbar(null)).toBe(false)
  })

  it('ein gesperrter Bereich führt zum Profil, auch nach einer Betreiber-Übergabe', () => {
    for (const s of SERVER) expect(erlaubterBereich(s as never, ich({}))).toBe('profil')
    expect(erlaubterBereich('ki', ich({}))).toBe('profil')
    expect(erlaubterBereich('allgemein', ich({ ist_betreiber: true }))).toBe('allgemein')
  })
})
