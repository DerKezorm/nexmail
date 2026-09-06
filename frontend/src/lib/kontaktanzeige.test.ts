/* Die Beschriftung eines Kontakts in der Liste. */
import { describe, expect, it } from 'vitest'
import { beschriftung, beschriftungFuer, nummerArt, sichtbareKontakte } from './kontaktanzeige'

const uebersetzt = (art: string) =>
  ({ cell: 'Mobil', home: 'Privat', work: 'Arbeit', fax: 'Fax', main: 'Zentrale', pager: 'Pager' })[art] ??
  '?'

describe('beschriftungFuer', () => {
  it('uebersetzt Apples Woerter', () => {
    expect(beschriftungFuer({ typen: 'voice', beschriftung: 'Mobile' }, uebersetzt)).toBe('Mobil')
    expect(beschriftungFuer({ typen: '', beschriftung: 'HomeFAX' }, uebersetzt)).toBe('Fax')
    /* „Other" ist Apples Wort fuer „keine Beschriftung", nicht eine. */
    expect(beschriftungFuer({ typen: 'voice', beschriftung: 'Other' }, uebersetzt)).toBe('')
  })

  it('laesst eine eigene Beschriftung woertlich stehen', () => {
    expect(beschriftungFuer({ typen: 'cell', beschriftung: 'Mutter' }, uebersetzt)).toBe('Mutter')
  })

  it('faellt auf die Typen der Zeile zurueck', () => {
    expect(beschriftungFuer({ typen: 'cell,voice,pref', beschriftung: '' }, uebersetzt)).toBe('Mobil')
    expect(beschriftungFuer({ typen: 'work,fax', beschriftung: '' }, uebersetzt)).toBe('Fax')
    expect(beschriftungFuer({ typen: 'voice', beschriftung: '' }, uebersetzt)).toBe('')
  })

  it('kennt die Typen in jeder Schreibweise', () => {
    expect(nummerArt('CELL,VOICE')).toBe('cell')
    expect(nummerArt('iphone')).toBe('cell')
    expect(nummerArt('home,voice')).toBe('home')
  })
})

describe('sichtbareKontakte', () => {
  const buecher = [
    { id: 'lokal', sichtbar: true },
    { id: 'icloud', sichtbar: false },
  ]

  it('versteckt, was in einem abgehakten Buch liegt', () => {
    const liste = [
      { id: 1, adressbuch_id: 'lokal' },
      { id: 2, adressbuch_id: 'icloud' },
    ]
    expect(sichtbareKontakte(liste, buecher).map((k) => k.id)).toEqual([1])
  })

  it('laesst einen Kontakt ohne bekanntes Buch stehen', () => {
    /* ⚠️ Unsichtbar ohne geloescht zu sein saehe aus wie Datenverlust. */
    const liste = [
      { id: 1, adressbuch_id: null },
      { id: 2, adressbuch_id: 'unbekannt' },
    ]
    expect(sichtbareKontakte(liste, buecher).map((k) => k.id)).toEqual([1, 2])
  })
})

const k = (teil: Partial<Parameters<typeof beschriftung>[0]>) => ({
  name: '',
  adresse: '',
  telefon: '',
  firma: '',
  ...teil,
})

describe('beschriftung', () => {
  it('nimmt den Namen und darunter die Adresse', () => {
    expect(beschriftung(k({ name: 'Anna Beispiel', adresse: 'anna@example.org' }))).toEqual({
      titel: 'Anna Beispiel',
      unter: 'anna@example.org',
    })
  })

  it('faellt ohne Namen auf die Adresse zurueck, ohne sie darunter zu wiederholen', () => {
    expect(beschriftung(k({ adresse: 'anna@example.org', telefon: '030 1' }))).toEqual({
      titel: 'anna@example.org',
      unter: '030 1',
    })
  })

  it('zeigt einen Kontakt ohne Adresse mit Name und Nummer', () => {
    /* ⚠️ **Der ganze Anlass.** Vorher stand hier `name || adresse` und
       darunter die Adresse; die Werkstatt haette eine leere zweite Zeile. */
    expect(beschriftung(k({ name: 'Werkstatt Beispiel', telefon: '030 1234' }))).toEqual({
      titel: 'Werkstatt Beispiel',
      unter: '030 1234',
    })
  })

  it('betitelt einen Firmen-Kontakt mit der Firma, nicht mit der Nummer', () => {
    /* ⚠️ Ein Firmen-Kontakt von Apple traegt seinen Namen in ORG und sonst
       keinen. Als Nummer betitelt findet ihn niemand wieder. */
    expect(beschriftung(k({ firma: 'Polizei Beispielstadt', telefon: '0177 1' }))).toEqual({
      titel: 'Polizei Beispielstadt',
      unter: '0177 1',
    })
  })

  it('laesst die zweite Zeile leer, wenn nur eines da ist', () => {
    expect(beschriftung(k({ firma: 'Beispiel GmbH' }))).toEqual({
      titel: 'Beispiel GmbH',
      unter: '',
    })
  })
})
