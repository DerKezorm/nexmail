// @vitest-environment jsdom
// nexmail: jsdom because the pages it reads their order from reach `client.ts`, which reads the base from the DOM.
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

import { kontenVariables, PAGES, pageOrder, SCREENS, screenFields, sessionExpiredParts, suggestUsername } from './vendor/nexkonten/konten'
import { naechster } from './components/SitzungAbgelaufen'
// nexmail: the order the pages really use (pages/einstellungen/Profil, pages/Sicherheit).
import { PROFIL_TEILE } from './pages/einstellungen/Profil'
import { SICHERHEIT_TEILE } from './pages/Sicherheit'
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

// nexmail (since 0.3.6): the parts of the pages "Profile" and "Security", top to bottom, by the module's part names
// (PAGES), then nexmail's own: 'signOut' in the profile, 'providers' (linking sign-in providers) and 'googleMicrosoft'
// in security, always after the module's.
const APP_PAGES: Record<keyof typeof PAGES, readonly string[]> = {
  profile: PROFIL_TEILE,
  security: SICHERHEIT_TEILE,
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

describe('the konten pages (since 0.3.6)', () => {
  it("show the module's parts first, in its order, and the app's own after them", () => {
    expect(APP_PAGES.profile).toEqual(pageOrder('profile', ['signOut']))
    expect(APP_PAGES.security).toEqual(pageOrder('security', ['providers', 'googleMicrosoft']))
    for (const page of Object.keys(PAGES) as (keyof typeof PAGES)[]) {
      const module = pageOrder(page)
      const shown = APP_PAGES[page]
      expect(shown.slice(0, module.length), page).toEqual(module)
      for (const own of shown.slice(module.length)) expect(module, `${page}: ${own}`).not.toContain(own)
    }
  })

  it("title every part with the module's texts", async () => {
    await i18n.changeLanguage('de')
    expect(i18n.t('account.sessions')).toBe('Angemeldete Geräte')
    expect(i18n.t('account.signOutEverywhere')).toBe('Überall sonst abmelden')
    expect(i18n.t('account.stateOff')).toBe('Aus')
    expect(i18n.t('account.pictureUpload')).toBe('Profilbild hochladen')
    for (const page of Object.values(PAGES)) {
      for (const part of page.parts) {
        for (const key of [part.title, ...part.buttons]) expect(i18n.exists(key), key).toBe(true)
      }
    }
  })
})

describe('the dialog "Session expired" (since 0.3.5)', () => {
  it("names nexmail's steps as the module does and offers the passkey where it is the second step", () => {
    expect(naechster({ schritt: 'fertig' })).toBe('session')
    expect(naechster({ schritt: 'fertig', weiter: 'show_codes', codes: ['A'] })).toBe('show_codes')
    expect(naechster({ schritt: 'code' })).toBe('second_factor')
    expect(naechster({ schritt: 'einrichten' })).toBe('second_factor_setup')
    expect(naechster({ schritt: 'passkey' })).toBe('passkey')
    expect(sessionExpiredParts(naechster({ schritt: 'passkey' }))).toContain('passkeySignIn')
    expect(sessionExpiredParts('sign_in')).toEqual(['sessionExpiredHint', 'password', 'signInAgain', 'or'])
  })
})
