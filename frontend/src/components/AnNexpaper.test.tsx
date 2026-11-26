// @vitest-environment jsdom
/** V38: „Als Dokument an nexpaper“ fragt nach dem Tresor, wenn die Verbindung in mehr als einen ablegen darf
 * (vorgewählt der zuletzt genutzte); bei einem geht der Anhang direkt. Ohne Verbindung steht kein Knopf. */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'de' } }),
}))

import { AnNexpaper, nexpaperVergessen } from './AnNexpaper'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let box: HTMLDivElement
let root: Root
let gesendet: { pfad: string; methode: string; rumpf: unknown }[]

function server(tresore: { id: number; name: string }[], zuletzt: number | null, verbunden = true) {
  gesendet = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (eingabe: RequestInfo | URL, init?: RequestInit) => {
      const pfad = String(eingabe)
      const methode = init?.method ?? 'GET'
      gesendet.push({ pfad, methode, rumpf: init?.body ? JSON.parse(String(init.body)) : null })
      const json = (daten: unknown) => new Response(JSON.stringify(daten), { status: 200, headers: { 'content-type': 'application/json' } })
      if (pfad.endsWith('/api/connect/partners')) return json([{ partner: 'nexpaper', state: verbunden ? 'connected' : 'none' }])
      if (pfad.endsWith('/api/nexpaper/tresore')) return json({ tresore, zuletzt })
      return json({ status: 'created' })
    }),
  )
}

async function zeigen() {
  await act(async () => root.render(<AnNexpaper nachrichtId={5} anhangId={8} />))
  await act(async () => await new Promise((fertig) => setTimeout(fertig, 0)))
}

async function klicken(el: Element | null) {
  await act(async () => {
    ;(el as HTMLElement).click()
    await new Promise((fertig) => setTimeout(fertig, 0))
  })
}

const posts = () => gesendet.filter((g) => g.methode === 'POST')

beforeEach(() => {
  nexpaperVergessen()
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('Als Dokument an nexpaper (V38)', () => {
  it('mehrere Tresore: das Fenster fragt, der zuletzt genutzte ist vorgewählt', async () => {
    server([{ id: 3, name: 'Zuhause' }, { id: 7, name: 'Verein' }], 7)
    await zeigen()
    await klicken(box.querySelector('[data-testid="an-nexpaper"]'))
    expect(posts()).toEqual([])
    const wahl = document.querySelector<HTMLSelectElement>('select')
    expect(wahl?.value).toBe('7')
    expect([...(wahl?.options ?? [])].map((o) => o.textContent)).toEqual(['Zuhause', 'Verein'])
    await act(async () => {
      wahl!.value = '3'
      wahl!.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await act(async () => {
      document.querySelector<HTMLFormElement>('form#an-nexpaper-8')!.requestSubmit()
      await new Promise((fertig) => setTimeout(fertig, 0))
    })
    expect(posts()).toEqual([{ pfad: '/api/nachrichten/5/anhang/8/nexpaper', methode: 'POST', rumpf: { tresor: 3 } }])
  })

  it('ein Tresor: der Anhang geht direkt, ohne Fenster', async () => {
    server([{ id: 3, name: 'Zuhause' }], null)
    await zeigen()
    await klicken(box.querySelector('[data-testid="an-nexpaper"]'))
    expect(document.querySelector('select')).toBeNull()
    expect(posts()).toEqual([{ pfad: '/api/nachrichten/5/anhang/8/nexpaper', methode: 'POST', rumpf: { tresor: 3 } }])
  })

  it('ohne Verbindung steht kein Knopf', async () => {
    server([], null, false)
    await zeigen()
    expect(box.querySelector('[data-testid="an-nexpaper"]')).toBeNull()
  })
})
