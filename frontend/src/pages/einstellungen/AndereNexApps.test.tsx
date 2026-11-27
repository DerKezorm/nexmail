// @vitest-environment jsdom
/** verbinden 0.1.8 in nexmail (B3, V42, V46): „Einrichten“ und „Von Hand verbinden“ für eine neue Verbindung nur für
 * den Betreiber; ein Mitglied sieht nur, dass die App hier nicht eingerichtet ist, und kein Formular von Hand. */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PartnerView } from '../../vendor/nexverbinden'

let antworten: Record<string, unknown> = {}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'de' } }),
}))
vi.mock('../../api/client', () => ({
  modulAnfrage: async (pfad: string) => {
    if (!(pfad.split('?')[0] in antworten)) throw new Error(`keine Antwort für ${pfad}`)
    return antworten[pfad.split('?')[0]]
  },
}))
vi.mock('./NexApps', () => ({
  NexApps: ({ nur, teil }: { nur: string; teil: string }) => <p data-testid={`nexapps-${nur}-${teil}`}>{nur}</p>,
}))

import { AndereNexApps } from './AndereNexApps'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function ansicht(partner: string, mehr: Partial<PartnerView> = {}): PartnerView {
  return {
    partner,
    state: 'none',
    address: '',
    address_from_operator: false,
    set_up: true,
    host: '',
    uses: ['tasks.read'],
    grants: [],
    uses_levels: { 'tasks.read': 'read' },
    grants_levels: {},
    account: null,
    since: null,
    ok_at: null,
    used_at: null,
    stale_since: null,
    problem: null,
    areas_used: null,
    areas_granted: null,
    legacy: null,
    version: null,
    areas_choice: [],
    ...mehr,
  } as PartnerView
}

let box: HTMLDivElement
let root: Root

beforeEach(() => {
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
  window.sessionStorage.clear()
  antworten = {
    '/api/connect/partners': [
      ansicht('nextasks', { address: 'https://tasks.example.com', address_from_operator: true, host: 'tasks.example.com' }),
      ansicht('nextime', { set_up: false }),
    ],
  }
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

async function zeigen(betreiber: boolean) {
  await act(async () => root.render(<AndereNexApps betreiber={betreiber} />))
  await act(async () => await new Promise((fertig) => setTimeout(fertig, 0)))
  // Die Karten stehen zu; aufklappen wie mit der Hand.
  for (const kopf of Array.from(box.querySelectorAll<HTMLElement>('[aria-expanded="false"]'))) {
    await act(async () => kopf.click())
  }
}

const alle = (id: string) => box.querySelectorAll(`[data-testid="${id}"]`).length

describe('Andere nex-Apps', () => {
  it('der Betreiber bekommt „Einrichten“ und „Von Hand verbinden“', async () => {
    await zeigen(true)
    expect(alle('connection-not-set-up')).toBe(1)
    expect(alle('connection-set-up')).toBe(1)
    expect(alle('connection-manual')).toBe(2)
  })

  it('ein Mitglied sieht nur, dass nextime nicht eingerichtet ist, ohne Weg dorthin und ohne Formular von Hand', async () => {
    await zeigen(false)
    expect(alle('connection-not-set-up')).toBe(1)
    expect(alle('connection-set-up')).toBe(0)
    expect(alle('connection-manual')).toBe(0)
    expect(alle('connection-connect')).toBe(1)
    expect(box.querySelector('input[type="url"]')).toBeNull()
  })
})
