// @vitest-environment jsdom
// ⚠️ jsdom nur hier: `laden.ts` holt über `client.ts` den Vorbau aus dem DOM.
/* MAIL-1: Was beim Ändern eines nextime-Termins hinausgeht, und welche Farbe ein
 * Kalender aus nextime trägt.
 *
 * ⚠️ **Der teuerste Fehler hier wäre still**: Die Kalenderseite schickt alle
 * Felder des Formulars; ginge davon alles an nextime, löschte ein leeres
 * Notizfeld dort die Notiz, und eine Zeitangabe ohne Zone verschöbe eine Reihe.
 */
import { describe, expect, it } from 'vitest'
import { fernAenderung, istNextimeKalender, type TerminZeile } from './laden'
import { kalenderPunkt } from '../lib/farben'

const alt: TerminZeile = {
  id: -42,
  kalenderId: 'nt:2',
  titel: 'Jour fixe',
  erinnerung: -1,
  beginn: '2026-12-01T09:00:00Z',
  ende: '2026-12-01T10:00:00Z',
  ganztaegig: false,
  ort: 'Raum 3',
  beschreibung: 'Agenda im Wiki',
  ausReihe: true,
  wiederholung: 'woechentlich',
  wiederholungTage: ['MO'],
  wiederholungIntervall: 1,
  regel: { freq: 'woechentlich', intervall: 1, tage: ['MO'], monatsart: 'tag', ordinal: 1, endeArt: 'nie', anzahl: 10, bis: '' },
  regelFremd: false,
  organisator: null,
  teilnehmer: [],
  rrule: 'FREQ=WEEKLY;BYDAY=MO',
  ausEinladung: false,
  eingeladen: false,
  fremdeAntworten: [],
  fern: {
    id: 7,
    vorkommen: '20261201T090000Z',
    etag: 'e1',
    link: 'https://zeit.example.com/day?event=7',
    beschreibbar: true,
    nurBelegt: false,
    hintergrund: false,
    uid: 'u7',
    einladung: '',
    herkunft: '',
    zeitzone: 'Europe/Berlin',
  },
}

describe('fernAenderung', () => {
  it('schickt nichts, wenn das Formular unverändert gespeichert wird', () => {
    expect(
      fernAenderung(alt, {
        titel: alt.titel,
        ort: alt.ort,
        beschreibung: alt.beschreibung,
        beginn: '2026-12-01T09:00:00.000Z',
        ende: '2026-12-01T10:00:00.000Z',
        ganztaegig: false,
        rrule: alt.rrule,
      }),
    ).toEqual({})
  })

  it('schickt nur das geänderte Feld', () => {
    expect(fernAenderung(alt, { titel: 'Neu', beschreibung: alt.beschreibung })).toEqual({ titel: 'Neu' })
  })

  it('schickt Zeiten zusammen und mit der Zone des Termins', () => {
    expect(
      fernAenderung(alt, { beginn: '2026-12-01T11:00:00Z', ende: '2026-12-01T12:00:00Z' }),
    ).toEqual({
      beginn: '2026-12-01T11:00:00Z',
      ende: '2026-12-01T12:00:00Z',
      ganztaegig: false,
      zeitzone: 'Europe/Berlin',
    })
  })

  it('schickt die Regel nur, wenn sie anders lautet', () => {
    expect(fernAenderung(alt, { rrule: 'FREQ=WEEKLY;BYDAY=MO' })).toEqual({})
    expect(fernAenderung(alt, { rrule: '' })).toEqual({ rrule: '' })
  })
})

describe('Kalender aus nextime', () => {
  it('erkennt sie an der Vorsilbe', () => {
    expect(istNextimeKalender('nt:2')).toBe(true)
    expect(istNextimeKalender('3f2a')).toBe(false)
  })

  it('tragen nextimes Farbe, eigene die eigene', () => {
    expect(kalenderPunkt({ farbe: 1, farbeNextime: 'blue' })).toBe('nt-farbe-blue')
    expect(kalenderPunkt({ farbe: 1, farbeNextime: 'lila-gibt-es-nicht' })).toBe('nt-farbe-slate')
    expect(kalenderPunkt({ farbe: 3 })).toBe('bg-data-3')
    expect(kalenderPunkt(undefined)).toBe('bg-data-1')
  })
})
