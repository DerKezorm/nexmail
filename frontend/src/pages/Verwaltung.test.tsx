// @vitest-environment jsdom
/** Befundsuche 28.11.2026: die Karte „Zeitzone des Servers“ schickte die beim Öffnen gemerkte öffentliche Adresse mit.
 * War sie nicht geladen (Ladefehler, Speichern vor dem Laden) oder inzwischen unter Server › Anmeldung geändert, leerte
 * oder überschrieb das Speichern der Zeitzone sie still. Jetzt geht nur die Zeitzone hinaus, ein Ladefehler steht in
 * der Karte, und vor dem Laden ist Speichern gesperrt. */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'de' } }),
}))

const holen = vi.fn()
const aendern = vi.fn()

vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  api: { holen: (...a: unknown[]) => holen(...a), aendern: (...a: unknown[]) => aendern(...a) },
}))

import { ZeitzoneDesServers } from './Verwaltung'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let wurzel: Root
let behaelter: HTMLDivElement

beforeEach(() => {
  holen.mockReset()
  aendern.mockReset()
  behaelter = document.createElement('div')
  document.body.appendChild(behaelter)
  wurzel = createRoot(behaelter)
})

afterEach(() => {
  act(() => wurzel.unmount())
  behaelter.remove()
})

async function zeigen() {
  await act(async () => {
    wurzel.render(<ZeitzoneDesServers />)
  })
  await act(async () => {
    await Promise.resolve()
  })
}

function knopf(): HTMLButtonElement {
  const gefunden = [...behaelter.querySelectorAll('button')].find((b) => b.textContent?.includes('aktion.speichern'))
  if (!gefunden) throw new Error('kein Speichern-Knopf')
  return gefunden
}

describe('Zeitzone des Servers', () => {
  it('schickt nur die Zeitzone, nie die öffentliche Adresse', async () => {
    holen.mockResolvedValue({ oeffentliche_adresse: 'https://mail.example.org', zeitzone: 'Europe/Berlin' })
    aendern.mockResolvedValue({ oeffentliche_adresse: 'https://mail.example.org', zeitzone: 'Europe/Berlin' })
    await zeigen()
    await act(async () => {
      knopf().click()
    })
    expect(aendern).toHaveBeenCalledTimes(1)
    expect(aendern).toHaveBeenCalledWith('/api/einstellungen', { zeitzone: 'Europe/Berlin' })
  })

  it('zeigt einen Ladefehler und speichert vor dem Laden nichts', async () => {
    holen.mockRejectedValue(new Error('weg'))
    await zeigen()
    expect(behaelter.textContent).toContain('anmeldung.fehler_allgemein')
    expect(knopf().disabled).toBe(true)
    await act(async () => {
      knopf().click()
    })
    expect(aendern).not.toHaveBeenCalled()
  })
})
