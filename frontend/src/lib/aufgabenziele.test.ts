import { describe, expect, it } from 'vitest'
import { gruppenname, schnellwahl, tagText, zielname } from './aufgabenziele'

describe('Schnellwahl im Fenster', () => {
  it('nimmt Ortszeit, nicht UTC', () => {
    // 23:30 am 4. November in Ortszeit ist noch der 4., auch wenn UTC schon weiter ist.
    expect(tagText(new Date(2026, 10, 4, 23, 30))).toBe('2026-11-04')
  })

  it('nächste Woche heißt der kommende Montag', () => {
    // Mittwoch, 4. November 2026
    const w = schnellwahl(new Date(2026, 10, 4, 9))
    expect(w).toEqual({ heute: '2026-11-04', morgen: '2026-11-05', woche: '2026-11-09' })
  })

  it('am Montag selbst ist es der Montag in sieben Tagen', () => {
    expect(schnellwahl(new Date(2026, 10, 9, 9)).woche).toBe('2026-11-16')
  })

  it('am Sonntag ist es der Tag danach', () => {
    expect(schnellwahl(new Date(2026, 10, 8, 9)).woche).toBe('2026-11-09')
  })

  it('morgen geht über das Monatsende', () => {
    expect(schnellwahl(new Date(2026, 10, 30, 9)).morgen).toBe('2026-12-01')
  })
})

describe('Namen', () => {
  const gruppen = [
    { verbindung_id: 'v1', art: 'todoist', name: '', fehler: '', listen: [{ ziel: 'v1:p', name: 'Arbeit' }] },
    { verbindung_id: 'v2', art: 'todoist', name: 'Privat', fehler: '', listen: [{ ziel: 'v2:p', name: 'Inbox' }] },
  ]

  it('zeigt die App vor der Liste, und den Namen der Verbindung, wenn es einen gibt', () => {
    expect(zielname(gruppen, 'v1:p')).toBe('Todoist › Arbeit')
    expect(zielname(gruppen, 'v2:p')).toBe('Todoist · Privat › Inbox')
    expect(zielname(gruppen, 'v3:p')).toBe('')
  })

  it('wiederholt den App-Namen nicht, wenn die Verbindung so heißt', () => {
    expect(gruppenname({ art: 'todoist', name: 'todoist' })).toBe('Todoist')
    expect(gruppenname({ art: 'todoist', name: ' Todoist ' })).toBe('Todoist')
  })

  it('kennt eine unbekannte Art nur mit ihrem Kürzel', () => {
    expect(gruppenname({ art: 'anders', name: '' })).toBe('anders')
  })
})
