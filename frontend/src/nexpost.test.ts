// Vorlage nexpost 1.1.0
/**
 * Every text of the post module is in the app, in German and English, through the app's own i18n, and the mail
 * server card shows the module's fields in the module's order. Copied once by the module's `tools/sync.py` to
 * `frontend/src/nexpost.test.ts`; then the app's file. Fill in the places marked APP.
 */
import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'

import { MAIL_FIELDS, mailErrorKey, postVariables, warnUnencrypted } from './vendor/nexpost/post'
import de from './vendor/nexpost/post.de.json'
import en from './vendor/nexpost/post.en.json'
// nexmail: the resources and settings exactly as `spracheHochfahren` gives them to i18next; a fresh instance.
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
// nexmail: Verwaltung → Server → Mail shows server, port, encryption, user, password, sender, sender name.
const APP_FIELDS: readonly string[] = MAIL_FIELDS

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([name, value]) => {
    const key = prefix ? `${prefix}.${name}` : name
    return typeof value === 'string' ? [[key, value] as [string, string]] : leaves(value, key)
  })
}

const values = { email: 'kim@example.com', when: 'today', error: 'mail_unreachable', count: 3 }
const fill: Record<string, string | number> = { ...postVariables(APP_NAME), ...values }

describe('the post texts', () => {
  for (const [language, tree] of [['de', de], ['en', en]] as const) {
    it(`are all in the app in ${language}, word for word`, async () => {
      await i18n.changeLanguage(language)
      for (const [key, text] of leaves(tree as Tree)) {
        const expected = text.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(fill[name] ?? ''))
        expect(i18n.t(key, values), key).toBe(expected)
      }
    })
  }
})

describe('the mail server card', () => {
  it('shows the fields of the module in its order', () => {
    expect(APP_FIELDS).toEqual(MAIL_FIELDS)
  })

  it('warns without encryption and names every error', () => {
    expect(warnUnencrypted({ security: 'none', user: 'robot', password: '', passwordSet: false })).toBe(true)
    expect(mailErrorKey('mail_off')).toBe('mail.error.mail_off')
    expect(mailErrorKey('something')).toBe('mail.error.unknown')
  })
})
