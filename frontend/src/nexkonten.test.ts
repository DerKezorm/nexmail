// @vitest-environment jsdom
// nexmail: jsdom because the pages it reads their order from reach `client.ts`, which reads the base from the DOM.
/**
 * Every text of the konten module is in the app, in German and English, through the app's own i18n, and the screens
 * show the module's fields in the module's order. Copied once by the module's `tools/sync.py` to
 * `frontend/src/nexkonten.test.ts`; then the app's file. Fill in the places marked APP.
 *
 * The module's own tests check the wording files word for word against the blueprint; this test checks that the
 * app really loads them (merged into its resources, `{{app}}`, `{{setupTokenEnv}}` and `{{minimum}}` filled in
 * through kontenVariables) and that nothing in the app overrides them. Since 0.3.7 it shows the app's screens
 * (APP_RENDER) and checks that every field is found by exactly its label and that the profile saves with one button;
 * this needs `@testing-library/dom` among the app's devDependencies and vitest's `environment: 'jsdom'`.
 */
import { fireEvent, getAllByRole, getByLabelText, waitFor } from '@testing-library/dom'
import i18next from 'i18next'
import { createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { I18nextProvider } from 'react-i18next'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import { BUTTONS, FIELDS, kontenVariables, PAGES, pageOrder, SCREENS, screenFields, sessionExpiredParts, suggestUsername } from './vendor/nexkonten/konten'
import type { AccountField } from './vendor/nexkonten/konten'
import type { Ich } from './api/client'
import { naechster } from './components/SitzungAbgelaufen'
// nexmail: the order the pages really use (pages/einstellungen/Profil, pages/Sicherheit).
import { Profil, PROFIL_TEILE } from './pages/einstellungen/Profil'
import { Sicherheit, SICHERHEIT_TEILE } from './pages/Sicherheit'
import { EinrichtungPage } from './pages/EinrichtungPage'
import { EinladungPage } from './pages/EinladungPage'
import { AnmeldePage } from './pages/AnmeldePage'
import { KennwortNeuPage, VergessenPage } from './pages/KennwortPage'
import de from './vendor/nexkonten/konten.de.json'
import en from './vendor/nexkonten/konten.en.json'
// nexmail: the resources and settings exactly as `spracheHochfahren` gives them to i18next (`i18n/index.ts` merges the
// module's files and sets kontenVariables('nexmail')); a fresh instance, because the app's own starts with the browser's.
import { GRUNDEINSTELLUNG, ressourcen } from './i18n'

const i18n = i18next.createInstance()

beforeAll(async () => {
  // nexmail: the server of the screens below; every write answers with an empty success.
  globalThis.fetch = server as typeof fetch
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

/** A screen of the app shown in the document: the element that holds it, and how to take it away again. */
type Shown = { root: HTMLElement; unmount: () => void }

/** nexmail: what the screens below ask the server for while they load (the invitation, the sign-in page's
 * providers); everything else answers 404, which the screens take as "nothing there". */
async function server(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const address = String(input instanceof Request ? input.url : input)
  const method = (init?.method ?? 'GET').toUpperCase()
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  if (method !== 'GET') return json({})
  if (address.includes('/api/einladung/')) return json({ anzeigename: 'Kim', benutzername: 'kim', kontaktadresse: 'kim@example.com', passwort: true })
  if (address.includes('/api/oidc/anmeldeseite')) return json({ providers: [], password: true })
  if (address.includes('/api/oidc/providers')) return json([])
  return json({ detail: 'not_found' }, 404)
}

/** nexmail: an account with a password, as the profile gets it from `/api/auth/ich`. */
const KIM = {
  id: 'kim',
  anzeigename: 'Kim',
  benutzername: 'kim',
  kontaktadresse: 'kim@example.com',
  hat_kennwort: true,
  ist_betreiber: false,
} as unknown as Ich

const nichts = () => undefined
const modus = { modus: 'dark' as const, aufModus: nichts }

/** Shows a page with the test's i18n and waits until its first field is there. */
function zeigen(screen: keyof typeof SCREENS, page: ReactNode): () => Promise<Shown> {
  return async () => {
    const root = document.createElement('div')
    document.body.appendChild(root)
    const react = createRoot(root)
    react.render(createElement(I18nextProvider, { i18n }, page))
    const first = screenFields(screen)[0]
    if (first) await waitFor(() => getByLabelText(root, i18n.t(first.label)))
    return {
      root,
      unmount: () => {
        react.unmount()
        root.remove()
      },
    }
  }
}

// nexmail (since 0.3.8): the page "Security" of an account with a password, shown until "Change password" is there.
const APP_PAGE_RENDER: { security?: () => Promise<Shown> } = {
  security: async () => {
    const root = document.createElement('div')
    document.body.appendChild(root)
    const react = createRoot(root)
    react.render(createElement(I18nextProvider, { i18n }, createElement(Sicherheit, { ich: { ...KIM, zwei_faktor_aktiv: false, offene_codes: 0 } as Ich })))
    await waitFor(() => getAllByRole(root, 'button', { name: i18n.t('account.passwordChange') }))
    return {
      root,
      unmount: () => {
        react.unmount()
        root.remove()
      },
    }
  },
}

// nexmail (since 0.3.8): the text keys of the buttons nexmail words itself, by their role in BUTTONS.
const APP_BUTTON_WORDS: Partial<Record<keyof typeof BUTTONS, string>> = {
  signIn: 'anmeldung.weiter',
  setupSubmit: 'einrichtung.weiter',
  inviteSubmit: 'einladung.loslegen',
  resetSubmit: 'kennwort.setzen',
  codeSubmit: 'anmeldung.anmelden',
  signOut: 'anmeldung.abmelden',
}

// nexmail (since 0.3.7): every screen of APP_SCREENS with its own page component; `profile` is the page "Profile" of
// an account with a password.
const APP_RENDER: Partial<Record<keyof typeof SCREENS, () => Promise<Shown>>> = {
  setup: zeigen('setup', createElement(EinrichtungPage, { ...modus, aufFertig: nichts })),
  invite: zeigen('invite', createElement(EinladungPage, { ...modus, schluessel: 'einladung', aufFertig: nichts })),
  login: zeigen('login', createElement(AnmeldePage, { ...modus, aufFertig: nichts, aufVergessen: nichts })),
  forgot: zeigen('forgot', createElement(VergessenPage, { ...modus, aufZurueck: nichts })),
  reset: zeigen('reset', createElement(KennwortNeuPage, { ...modus, schluessel: 'neu', aufFertig: nichts })),
  profile: zeigen('profile', createElement(Profil, { ich: KIM, aufAbmelden: nichts })),
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
        const rules = 'rules' in part ? [part.rules] : []
        for (const key of [part.title, ...part.buttons, ...rules]) expect(i18n.exists(key), key).toBe(true)
      }
    }
    expect(i18n.t(PAGES.profile.saveButton)).toBe('Speichern')
  })
})

/** The texts of the elements ``aria-describedby`` names, one after the other. */
function description(field: HTMLElement): string {
  const ids = (field.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean)
  return ids.map((id) => field.ownerDocument.getElementById(id)?.textContent ?? '').join(' ')
}

/** The field of a screen, found by exactly its label (getByLabelText fails on none and on more than one). */
function labelled(root: HTMLElement, field: AccountField): HTMLElement {
  return getByLabelText(root, i18n.t(FIELDS[field].label))
}

async function shown(screen: keyof typeof SCREENS): Promise<Shown> {
  await i18n.changeLanguage('de')
  const render = APP_RENDER[screen]
  if (!render) throw new Error(`APP_RENDER.${screen} is missing`)
  return render()
}

describe('the konten fields (since 0.3.7)', () => {
  for (const screen of Object.keys(APP_SCREENS) as (keyof typeof SCREENS)[]) {
    it(`${screen}: every field is found by exactly its label, its hints by aria-describedby`, async () => {
      const { root, unmount } = await shown(screen)
      try {
        for (const spec of screenFields(screen)) {
          const label = i18n.t(spec.label)
          const field = getByLabelText(root, label)
          const own = field.getAttribute('aria-label')
          expect(own === null || own === label, `${screen}.${spec.field}: aria-label`).toBe(true)
          const said = description(field)
          for (const hint of spec.hints) expect(said, `${screen}.${spec.field}: ${hint}`).toContain(i18n.t(hint))
        }
      } finally {
        unmount()
      }
    })
  }
})

describe('the profile saves with one button (since 0.3.7)', () => {
  it('has exactly one "Save" for display name, username and email', async () => {
    const { root, unmount } = await shown('profile')
    try {
      const fields = PAGES.profile.saveFields.map((field) => labelled(root, field))
      // The card: the closest element holding all three fields.
      let card: HTMLElement = fields[0] ?? root
      while (!fields.every((field) => card.contains(field)) && card.parentElement) card = card.parentElement
      expect(getAllByRole(card, 'button', { name: i18n.t(PAGES.profile.saveButton) })).toHaveLength(1)
    } finally {
      unmount()
    }
  })

  it('saves nothing when a field is changed and left', async () => {
    const { root, unmount } = await shown('profile')
    const sent = vi.spyOn(globalThis, 'fetch')
    try {
      for (const field of PAGES.profile.saveFields) {
        const input = labelled(root, field)
        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: field === 'email' ? 'neu@example.com' : 'neu' } })
        fireEvent.focusOut(input)
        fireEvent.blur(input)
      }
      await new Promise((done) => setTimeout(done, 50))
      const writes = sent.mock.calls.filter(([input, init]) => {
        const method = init?.method ?? (input instanceof Request ? input.method : 'GET')
        return method.toUpperCase() !== 'GET'
      })
      expect(writes).toEqual([])
    } finally {
      sent.mockRestore()
      unmount()
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

/** What a button says: its text without the symbol (an `svg` has no text). */
function said(element: Element): string {
  return (element.textContent ?? '').replace(/\s+/g, ' ').trim()
}

describe('every button of the account pages has its kind and symbol (since 0.3.8)', () => {
  const screens: [string, (() => Promise<Shown>) | undefined][] = [
    ...(Object.keys(APP_SCREENS) as (keyof typeof SCREENS)[]).map((screen) => [screen, APP_RENDER[screen]] as [string, (() => Promise<Shown>) | undefined]),
    ['security', APP_PAGE_RENDER.security],
  ]
  for (const [screen, render] of screens) {
    it(`${screen}: kind and symbol as BUTTONS says, no button without them`, async () => {
      if (!render) throw new Error(`no render for ${screen}`)
      await i18n.changeLanguage('de')
      const { root, unmount } = await render()
      try {
        const words = new Map<string, keyof typeof BUTTONS>()
        for (const name of Object.keys(BUTTONS) as (keyof typeof BUTTONS)[]) {
          const own = APP_BUTTON_WORDS[name]
          const text = name.includes('.') ? i18n.t(name, { name: 'Pocket ID' }) : own && i18n.t(own)
          if (text && !words.has(text)) words.set(text, name)
        }
        let found = 0
        for (const element of Array.from(root.querySelectorAll<HTMLElement>('button, [role="button"], [data-kind]'))) {
          const name = words.get(said(element))
          if (!name) continue
          found += 1
          const spec = BUTTONS[name]
          expect(element.getAttribute('data-kind'), `${screen}: ${said(element)}`).toBe(spec.kind)
          expect(element.getAttribute('data-icon'), `${screen}: ${said(element)}`).toBe(spec.icon)
        }
        expect(found, `${screen}: no button of BUTTONS found`).toBeGreaterThan(0)
      } finally {
        unmount()
      }
    })
  }
})
