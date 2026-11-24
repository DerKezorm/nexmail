// @vitest-environment jsdom
// ⚠️ jsdom nur hier: `nextasks.ts` holt über `client.ts` den Vorbau aus dem DOM.
/* MAIL-2 AC-4: Beim Ändern einer nextasks-Aufgabe geht nur hinaus, was sich
 * geändert hat. */
import { describe, expect, it } from 'vitest'
import { aenderungen, schlagworteAus, type Fernaufgabe } from './nextasks'

const VORHER: Fernaufgabe = {
  id: 't1', liste_id: 'l1', liste_name: 'Einkauf', bereich_id: 's1', bereich_name: 'Familie',
  abschnitt_id: null, abschnitt_name: '', eltern_id: null, titel: 'Brot', notiz: '**Vollkorn**',
  notiz_text: 'Vollkorn', url: null, faellig_tag: '2026-11-25', faellig_zeit: '09:00', wiederholung: null,
  markiert: false, prioritaet: 0, schlagworte: ['einkauf', 'mail'], zustaendige: [{ id: 12, name: 'Mara' }],
  erledigt: false, erledigt_am: null, papierkorb: false, teilaufgaben: { offen: 0, gesamt: 0 },
  link: null, beschreibbar: true, mail: null,
}

const GLEICH = {
  titel: 'Brot', notiz: '**Vollkorn**', faellig_tag: '2026-11-25', faellig_zeit: '09:00', prioritaet: 0,
  markiert: false, schlagworte: ['mail', 'einkauf'], zustaendige: [12], liste_id: 'l1', abschnitt_id: null,
}

describe('aenderungen', () => {
  it('schickt nichts, wenn nichts geändert ist (auch nicht bei anderer Reihenfolge)', () => {
    expect(aenderungen(VORHER, GLEICH)).toEqual({})
  })

  it('schickt nur den geänderten Titel', () => {
    expect(aenderungen(VORHER, { ...GLEICH, titel: 'Brötchen' })).toEqual({ titel: 'Brötchen' })
  })

  it('leert Datum mit null; die Uhrzeit geht dann nicht eigens hinaus', () => {
    expect(aenderungen(VORHER, { ...GLEICH, faellig_tag: null, faellig_zeit: null })).toEqual({ faellig_tag: null })
  })

  it('nimmt beim Verschieben den Abschnitt mit', () => {
    expect(aenderungen(VORHER, { ...GLEICH, liste_id: 'l2', abschnitt_id: 'x1' })).toEqual({
      liste_id: 'l2',
      abschnitt_id: 'x1',
    })
  })

  it('erkennt geänderte Zuständige', () => {
    expect(aenderungen(VORHER, { ...GLEICH, zustaendige: [12, 14] })).toEqual({ zustaendige: [12, 14] })
  })
})

describe('schlagworteAus', () => {
  it('trennt an Kommas, ohne Leeres und Doppeltes', () => {
    expect(schlagworteAus(' einkauf, mail ,, einkauf ')).toEqual(['einkauf', 'mail'])
  })
})
