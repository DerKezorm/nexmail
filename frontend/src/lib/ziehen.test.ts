/* Die Rechnung hinter dem Ziehen.
 *
 * ⚠️ **Diese Datei braucht eine feste Zeitzone.** Der teuerste Fall hier ist
 * die Zeitumstellung, und in UTC gibt es sie nicht: Im Fließband liefe die
 * Probe durch, ohne etwas zu messen — ein hohler Test, der aussieht wie ein
 * grüner. Gesetzt wird sie in `vite.config.ts` (`test.env.TZ`); der erste
 * Test hier weist nach, dass sie wirklich gilt. Ohne diesen Nachweis wäre die
 * Zeile in der Konfiguration nur Zierde, und niemand merkte ihr Verschwinden.
 */
import { describe, expect, it } from 'vitest'
import {
  MIN_MINUTEN,
  RASTER_MINUTEN,
  endeGezogen,
  minutenAusPixeln,
  tageDazwischen,
  verschobenUmMinuten,
  verschobenUmTage,
} from './ziehen'

/** 24.10.2026, 09:00 Berlin — der Tag VOR der Umstellung (Sommerzeit, +02:00). */
const VOR_UMSTELLUNG = { beginn: '2026-10-24T07:00:00.000Z', ende: '2026-10-24T08:00:00.000Z' }
const stunden = (iso: string) => new Date(iso).getHours()
const dauer = (z: { beginn: string; ende: string }) =>
  (new Date(z.ende).getTime() - new Date(z.beginn).getTime()) / 60_000

describe('die Zeitzone dieses Laufs', () => {
  it('steht wirklich auf Europe/Berlin', () => {
    /* ⚠️ **Bodenschwelle.** Ohne wirksame Zone messen die Sommerzeit-Tests
       unten nichts, und zwar lautlos. Lieber hier laut scheitern. */
    expect(stunden('2026-10-24T07:00:00Z')).toBe(9)
  })
})

describe('verschobenUmMinuten', () => {
  it('behaelt die Dauer', () => {
    /* ⚠️ Der Server laesst ein nicht mitgeschicktes Feld unveraendert. Wer nur
       den Beginn verschiebt, macht aus einer Stunde eine halbe. */
    const z = verschobenUmMinuten(VOR_UMSTELLUNG, 30)
    expect(dauer(z)).toBe(60)
    expect(z.beginn).toBe('2026-10-24T07:30:00.000Z')
  })

  it('geht auch rueckwaerts', () => {
    expect(verschobenUmMinuten(VOR_UMSTELLUNG, -60).beginn).toBe('2026-10-24T06:00:00.000Z')
  })
})

describe('verschobenUmTage', () => {
  it('haelt die Uhrzeit ueber die Zeitumstellung fest', () => {
    /* ⚠️ **Der teuerste Fehler dieses Bauteils.** 25.10.2026 ist der Tag der
       Rueckstellung; er hat 25 Stunden. Wer 86.400.000 ms addiert, zieht einen
       Termin von 9 Uhr auf 8 Uhr — und niemand bringt das mit der Sommerzeit
       in Verbindung. */
    const z = verschobenUmTage(VOR_UMSTELLUNG, 1, false)
    expect(stunden(z.beginn)).toBe(9)
    expect(stunden(z.ende)).toBe(10)
    // Und in UTC ist es wirklich eine andere Stunde als vorher.
    expect(z.beginn).toBe('2026-10-25T08:00:00.000Z')
  })

  it('haelt sie auch im Fruehjahr fest', () => {
    // 29.03.2026 ist die Vorstellung; der Tag hat 23 Stunden.
    const vor = { beginn: '2026-03-28T08:00:00.000Z', ende: '2026-03-28T09:00:00.000Z' }
    expect(stunden(vor.beginn)).toBe(9)
    const z = verschobenUmTage(vor, 1, false)
    expect(stunden(z.beginn)).toBe(9)
    expect(z.beginn).toBe('2026-03-29T07:00:00.000Z')
  })

  it('behaelt die Dauer auch ueber die Umstellung', () => {
    expect(dauer(verschobenUmTage(VOR_UMSTELLUNG, 1, false))).toBe(60)
  })

  it('laesst einen ganztaegigen Termin auf UTC-Mitternacht stehen', () => {
    /* ⚠️ Ein Kalendertag ist kein Zeitpunkt. Ueber die Ortszeit gerechnet
       landet er westlich von Greenwich auf dem Vortag. */
    const ganz = { beginn: '2026-09-14T00:00:00Z', ende: '2026-09-15T00:00:00Z' }
    const z = verschobenUmTage(ganz, 3, true)
    expect(z.beginn).toBe('2026-09-17T00:00:00Z')
    expect(z.ende).toBe('2026-09-18T00:00:00Z')
  })

  it('aendert bei null Tagen nichts', () => {
    expect(verschobenUmTage(VOR_UMSTELLUNG, 0, false)).toEqual(VOR_UMSTELLUNG)
  })
})

describe('endeGezogen', () => {
  it('bewegt nur das Ende', () => {
    const z = endeGezogen(VOR_UMSTELLUNG, 30)
    expect(z.beginn).toBe(VOR_UMSTELLUNG.beginn)
    expect(dauer(z)).toBe(90)
  })

  it('laesst den Termin nicht kuerzer als die Mindestdauer werden', () => {
    /* ⚠️ Ein Termin von null Minuten waere im Raster unsichtbar — man haette
       ihn verloren, ohne ihn geloescht zu haben. */
    expect(dauer(endeGezogen(VOR_UMSTELLUNG, -60))).toBe(MIN_MINUTEN)
    expect(dauer(endeGezogen(VOR_UMSTELLUNG, -600))).toBe(MIN_MINUTEN)
  })
})

describe('minutenAusPixeln', () => {
  it('rastert auf das Vielfache, und zwar rundend', () => {
    /* ⚠️ Abschneiden machte jeden kleinen Zug wirkungslos: 14 Minuten wuerden
       zu 0, und der Termin bliebe scheinbar stehen. */
    expect(minutenAusPixeln(48, 48)).toBe(60)
    expect(minutenAusPixeln(24, 48)).toBe(30)
    expect(minutenAusPixeln(8, 48)).toBe(RASTER_MINUTEN) // 10 Minuten -> 15
    expect(minutenAusPixeln(-24, 48)).toBe(-30)
  })

  it('macht aus einem Zittern keine Verschiebung', () => {
    expect(minutenAusPixeln(2, 48)).toBe(0)
  })
})

describe('tageDazwischen', () => {
  it('zaehlt ueber die Zeitumstellung hinweg ganze Tage', () => {
    /* ⚠️ Ueber die Differenz in Millisekunden waere der 25.10. „nicht ganz
       ein Tag", und ein Zug ueber das Wochenende landete daneben. */
    expect(tageDazwischen(new Date(2026, 9, 24), new Date(2026, 9, 26))).toBe(2)
    expect(tageDazwischen(new Date(2026, 2, 28), new Date(2026, 2, 30))).toBe(2)
  })

  it('zaehlt rueckwaerts negativ und gleiche Tage als null', () => {
    expect(tageDazwischen(new Date(2026, 9, 26), new Date(2026, 9, 24))).toBe(-2)
    expect(tageDazwischen(new Date(2026, 9, 24, 23), new Date(2026, 9, 24, 1))).toBe(0)
  })
})
