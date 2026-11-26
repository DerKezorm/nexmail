// @vitest-environment jsdom
/** Modul mcp 1.1.0 in nexmail: welche Adresse welche Seite meint (Zustimmung, Rückfrage), dass die Seite der Zustimmung
 * die Postfächer und das Extra „Mailtext lesen“ nennt, und dass jedes Werkzeug des Servers ein Wort in DE und EN hat. */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import de from '../i18n/de.json'
import en from '../i18n/en.json'

const deMcp = de.mcp as Record<string, string>
const enMcp = en.mcp as Record<string, string>

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => deMcp[k.replace(/^mcp\./, '')] ?? k, i18n: { language: 'de' } }),
}))

import { WERKZEUGE } from '../lib/mcpWorte'
import { McpSeite, mcpSeiteVon } from './McpSeite'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let box: HTMLDivElement
let root: Root

beforeEach(() => {
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
})

describe('Seiten des Moduls mcp', () => {
  it('erkennt Zustimmung und Rückfrage, sonst nichts', () => {
    expect(mcpSeiteVon('/oauth/authorize')).toEqual({ art: 'zustimmung' })
    expect(mcpSeiteVon('/mcp/requests/12')).toEqual({ art: 'rueckfrage', nummer: '12' })
    expect(mcpSeiteVon('/settings/connections')).toBeNull()
    expect(mcpSeiteVon('/mcp/requests/12/approve')).toBeNull()
    expect(mcpSeiteVon('/oauth/authorize/x')).toBeNull()
  })

  it('die Zustimmung nennt Postfächer und „Mailtext lesen“, ab Werk aus', async () => {
    const info = {
      client: { id: 'c1', name: 'Probe' },
      redirect_uri: 'http://127.0.0.1:33418/callback',
      levels: ['read', 'draft', 'write'],
      level: 'read',
      max_level: 'write',
      areas: [{ id: 'k1', name: 'Post' }],
      extras: ['mailtext'],
      ai_allowed: true,
      account: 'owner',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(info), { status: 200, headers: { 'content-type': 'application/json' } })),
    )
    window.history.replaceState(null, '', '/oauth/authorize?client_id=c1&redirect_uri=http%3A%2F%2F127.0.0.1%3A33418%2Fcallback&code_challenge=x&code_challenge_method=S256')
    await act(async () => root.render(<McpSeite seite={{ art: 'zustimmung' }} />))
    await act(async () => await new Promise((fertig) => setTimeout(fertig, 0)))
    const text = box.textContent ?? ''
    expect(text).toContain('Mailtext lesen')
    expect(text).toContain('Lesen und Entwürfe')
    const extra = box.querySelector<HTMLInputElement>('[data-testid="consent-extra-mailtext"] input') ?? box.querySelector<HTMLInputElement>('input[data-testid="consent-extra-mailtext"]')
    expect(extra?.checked ?? false).toBe(false)
    window.history.replaceState(null, '', '/')
  })

  it('jedes Werkzeug und jede Stufe hat ein Wort in DE und EN', () => {
    for (const name of WERKZEUGE) {
      expect(deMcp[`w_${name}`], name).toBeTruthy()
      expect(enMcp[`w_${name}`], name).toBeTruthy()
    }
    for (const stufe of ['read', 'draft', 'write']) {
      expect(deMcp[`stufe_${stufe}`]).toBeTruthy()
      expect(enMcp[`stufe_${stufe}_hinweis`]).toBeTruthy()
    }
  })
})
