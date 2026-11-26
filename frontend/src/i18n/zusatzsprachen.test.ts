/* Eigene Sprachen des Betreibers (Server › Allgemein › Sprachen, E48): was einer Datei fehlt, steht englisch da, und
 * die Auswahl nennt sie zwischen den eingebauten, nach Namen. */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { sprachauswahl, verschmelzen, zusatzsprachenVergessen } from './index'

afterEach(() => {
  vi.unstubAllGlobals()
  zusatzsprachenVergessen()
})

describe('verschmelzen', () => {
  it('nimmt die Texte der Datei und füllt, was ihr fehlt, aus dem Englischen', () => {
    const englisch = { aktion: { schliessen: 'Close', abbrechen: 'Cancel' }, nav: { post: 'Mail' } }
    const datei = { aktion: { schliessen: 'Sluiten' } }
    expect(verschmelzen(englisch, datei)).toEqual({ aktion: { schliessen: 'Sluiten', abbrechen: 'Cancel' }, nav: { post: 'Mail' } })
    expect(englisch.aktion.schliessen).toBe('Close')
  })
})

describe('sprachauswahl', () => {
  it('nennt Deutsch, Englisch und die des Betreibers nach Namen, ohne Doppel und ohne falsche Codes', async () => {
    const liste = [
      { code: 'nl', name: 'Nederlands', keys: 3 },
      { code: 'de', name: 'Deutsch (eigen)', keys: 1 },
      { code: '../x', name: 'Böse', keys: 1 },
      { code: 'es', name: 'Español', keys: 2 },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(liste), { status: 200 })))
    expect((await sprachauswahl()).map((s) => s.code)).toEqual(['de', 'en', 'es', 'nl'])
  })

  it('ohne Server bleiben die eingebauten', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('weg') }))
    expect((await sprachauswahl()).map((s) => s.code)).toEqual(['de', 'en'])
  })
})
