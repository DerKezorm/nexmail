/* Die Beschriftung eines Kontakts in der Liste. */
import { describe, expect, it } from 'vitest'
import { beschriftung, sichtbareKontakte } from './kontaktanzeige'

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

  it('laesst die zweite Zeile leer, wenn nur eines da ist', () => {
    expect(beschriftung(k({ firma: 'Beispiel GmbH' }))).toEqual({
      titel: 'Beispiel GmbH',
      unter: '',
    })
  })
})
