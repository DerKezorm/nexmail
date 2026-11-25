/**
 * Every text of the konten module is in the app, in German and English, through the app's own i18n, and the screens
 * show the module's fields in the module's order. Copied once by the module's `tools/sync.py` to
 * `frontend/src/nexkonten.test.ts`; then the app's file. Fill in the places marked APP.
 *
 * The module's own tests check the wording files word for word against the blueprint; this test checks that the
 * app really loads them (merged into its resources, `{{app}}`, `{{setupTokenEnv}}` and `{{minimum}}` filled in
 * through kontenVariables) and that nothing in the app overrides them.
 */
import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'

import { kontenVariables, SCREENS, screenFields, suggestUsername } from './vendor/nexkonten/konten'
import de from './vendor/nexkonten/konten.de.json'
import en from './vendor/nexkonten/konten.en.json'
// nexmail: the resources and settings exactly as `spracheHochfahren` gives them to i18next (`i18n/index.ts` merges the
// module's files and sets kontenVariables('nexmail')); a fresh instance, because the app's own starts with the browser's.
import { GRUNDEINSTELLUNG, ressourcen } from './i18n'

const i18n = i18next.createInstance()

beforeAll(async () => {
  await i18n.init({
    resources: { de: { translation: await ressourcen('de') }, en: { translation: await ressourcen('en') } },
    lng: 'de',
    ...GRUNDEINSTELLUNG,
  })
})

// nexmail: the app's name as its container is called.
const APP_NAME = 'nexmail'
// nexmail: the fields each screen shows, top to bottom (pages/EinrichtungPage, EinladungPage, AnmeldePage,
// KennwortPage, einstellungen/Profil); every screen as the module orders it.
const APP_SCREENS: Partial<Record<keyof typeof SCREENS, readonly string[]>> = {
  setup: SCREENS.setup,
  invite: SCREENS.invite,
  login: SCREENS.login,
  forgot: SCREENS.forgot,
  reset: SCREENS.reset,
  profile: SCREENS.profile,
}

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([name, value]) => {
    const key = prefix ? `${prefix}.${name}` : name
    return typeof value === 'string' ? [[key, value] as [string, string]] : leaves(value, key)
  })
}

const values = { username: 'kim', email: 'kim@example.com', provider: 'Pocket ID' }
const fill: Record<string, string | number> = { ...kontenVariables(APP_NAME), ...values }

describe('the konten texts', () => {
  for (const [language, tree] of [['de', de], ['en', en]] as const) {
    it(`are all in the app in ${language}, word for word`, async () => {
      await i18n.changeLanguage(language)
      for (const [key, text] of leaves(tree as Tree)) {
        // nexmail: plural forms are asked for without their suffix, with a count that picks them (as in
        // nexoidc.wording.test.ts); the module's template asked `days_one` directly and got the raw `{{count}}`.
        const plural = /_(one|other)$/.exec(key)
        const given = plural ? { ...values, count: plural[1] === 'one' ? 1 : 2 } : values
        const asked = plural ? key.slice(0, plural.index) : key
        const filled: Record<string, string | number> = { ...fill, ...given }
        const expected = text.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(filled[name] ?? ''))
        expect(i18n.t(asked, given), key).toBe(expected)
      }
    })
  }
})

describe('the konten screens', () => {
  it('show the fields of the module in its order', () => {
    for (const [screen, fields] of Object.entries(APP_SCREENS)) {
      expect(fields, screen).toEqual(screenFields(screen as keyof typeof SCREENS).map((entry) => entry.field))
    }
  })

  it('suggest the username the server would', () => {
    expect(suggestUsername('Max Müller')).toBe('max-mueller')
  })
})
