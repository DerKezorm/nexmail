/**
 * Jeder Schritt des authentik-Knopfs (`STEP_KEYS` im Server, `AUTHENTIK_STEPS` hier)
 * und jeder Grund (`REASONS`, `AUTHENTIK_REASONS`) hat einen Namen in beiden Sprachen, und keiner zu viel. Die Karte
 * fragt sie über `authentikStepKey` und `authentikReasonKey`; eine Kennung ohne Text stünde roh da.
 */
import { describe, expect, it } from 'vitest'

import { GRUNDEINSTELLUNG, ressourcen } from './i18n'
import { AUTHENTIK_REASONS, AUTHENTIK_STEPS, authentikReasonKey, authentikStepKey } from './vendor/nexoidc/oidc'
import i18next from 'i18next'

const SERVER = '../../backend/app/vendor/nexoidc/authentik.py'
const quelle = import.meta.glob('../../backend/app/vendor/nexoidc/authentik.py', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>

function tupel(name: string): string[] {
  const text = quelle[SERVER] ?? ''
  const treffer = new RegExp(`^${name} = \(([^)]*)\)`, 'm').exec(text)
  return treffer ? [...treffer[1].matchAll(/"([a-z_A-Z]+)"/g)].map((m) => m[1]) : []
}

describe('the steps of the authentik button', () => {
  it('are the same here and in the server', () => {
    expect(tupel('STEP_KEYS')).toEqual([...AUTHENTIK_STEPS])
    expect(tupel('REASONS').sort()).toEqual([...AUTHENTIK_REASONS].sort())
  })

  for (const sprache of ['de', 'en'] as const) {
    it(`have a name and every reason a sentence in ${sprache}, none too many`, async () => {
      const i18n = i18next.createInstance()
      await i18n.init({ resources: { [sprache]: { translation: await ressourcen(sprache) } }, lng: sprache, ...GRUNDEINSTELLUNG })
      for (const schritt of AUTHENTIK_STEPS) {
        const schluessel = authentikStepKey(schritt)
        expect(schluessel && i18n.exists(schluessel), schritt).toBe(true)
      }
      for (const grund of AUTHENTIK_REASONS) {
        const schluessel = authentikReasonKey(grund)
        const plural = grund === 'issuer_change'
        expect(schluessel && i18n.exists(plural ? `${schluessel}_one` : schluessel), grund).toBe(true)
      }
      const texte = (await ressourcen(sprache)) as { oidc: { authentik: { step: object; why: object } } }
      const schritte = Object.keys(texte.oidc.authentik.step).filter((s) => s !== 'binding')
      expect(schritte.sort()).toEqual([...AUTHENTIK_STEPS].sort())
      const gruende = Object.keys(texte.oidc.authentik.why).map((g) => g.replace(/_(one|other)$/, ''))
      expect([...new Set(gruende)].sort()).toEqual([...AUTHENTIK_REASONS].sort())
    })
  }
})
