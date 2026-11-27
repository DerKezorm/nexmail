// @vitest-environment jsdom
/** E67: Server › Verbindungen (`/settings/server-connections`) hält „Andere nex-Apps“, dann „Schnittstellen“, mit allen
 * Schaltern wie vorher unter Allgemein; Allgemein hat beide Karten nicht mehr, und `/settings/general#nex-apps` (und
 * `#interfaces`) führt mit dem Anker dorthin. Derselbe Weg wie in `App`: Bereich aus der Adresse (`bereichDerAdresse`),
 * Adresse aus dem Bereich (`useEinstellungsAdresse`), dazu die echte Einstellungsseite. */
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Ich } from '../../api/client'
import { NEXUI_TEXTS, areaText } from '../../vendor/nexui'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'de' } }),
}))

/** Was der Server auf die Fragen der Karten antwortet. */
const ANTWORTEN: Record<string, unknown> = {
  '/api/konten': [],
  '/api/einstellungen': { oeffentliche_adresse: '', zeitzone: 'Europe/Berlin' },
  '/api/einstellungen/eigenes-netz': { erlaubt: false },
  '/api/einstellungen/webhook-mailtext': { erlaubt: false },
  '/api/connect/admin': { connections: true, partners: ['nextasks', 'nextime', 'nexpaper'], addresses: {}, local: false },
  '/api/connections/interfaces': { api: false, mcp: true, app: true, pairing: false },
  '/api/connections/mcp/admin': { programs: false, levels: ['read', 'write'], max_level: 'write', blocked_tools: [], tools: [] },
}

async function antwort(pfad: string): Promise<unknown> {
  const ohneSuche = pfad.split('?')[0]
  if (ohneSuche in ANTWORTEN) return ANTWORTEN[ohneSuche]
  throw new Error(`keine Antwort für ${pfad}`)
}

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  api: { holen: antwort, aendern: antwort },
  modulAnfrage: antwort,
}))

import { EinstellungenPage } from '../EinstellungenPage'
import { bereichDerAdresse, useEinstellungsAdresse } from './adresse'
import type { Bereich } from './bereiche'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const BETREIBER = {
  id: 'x',
  benutzername: 'x',
  anzeigename: 'X',
  ist_betreiber: true,
  zwei_faktor_aktiv: false,
  offene_codes: 0,
  kontaktadresse: '',
  ki_aktiv: false,
  ki_erlaubt: false,
  ki_fremde_post: false,
  absenderlogos: false,
  version: '0',
  wasneu_gesehen: '0',
} as Ich

/** Wie `App`: der Bereich einmal aus der Adresse, die Adresse folgt dem Bereich. */
function Seite() {
  const [bereich] = useState<Bereich | null>(() => {
    const dort = bereichDerAdresse()
    return dort && 'bereich' in dort ? dort.bereich : null
  })
  useEinstellungsAdresse(true, bereich)
  const nichts = () => undefined
  return (
    <EinstellungenPage
      bereich={bereich}
      aufBereich={nichts}
      formularOffen={false}
      aufFormular={nichts}
      wahlOffen={false}
      aufWahl={nichts}
      ich={BETREIBER}
      aufAbmelden={nichts}
      modus="light"
      aufModus={nichts}
    />
  )
}

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
  window.history.replaceState(null, '', '/')
})

async function oeffnen(adresse: string): Promise<void> {
  window.history.replaceState(null, '', adresse)
  await act(async () => root.render(<Seite />))
  for (let i = 0; i < 3; i++) await act(async () => await new Promise((fertig) => setTimeout(fertig, 0)))
}

const wo = () => window.location.pathname + window.location.search + window.location.hash
const bereichsteil = (slug: string) => box.querySelector<HTMLElement>(`[data-testid="settings-area-${slug}"]`)
const karten = (slug: string) =>
  [...(bereichsteil(slug)?.querySelectorAll('[data-part="settings-cards"] > section[data-card], [data-part="settings-cards"] > * > section[data-card]') ?? [])].map(
    (karte) => karte.getAttribute('data-card'),
  )

describe('Server › Verbindungen (E67)', () => {
  it('zeigt „Andere nex-Apps“, dann „Schnittstellen“, mit der Überschrift aus dem Bausatz und allen Schaltern', async () => {
    await oeffnen('/settings/server-connections')
    expect(wo()).toBe('/settings/server-connections')
    const teil = bereichsteil('server-connections')!
    expect(teil).not.toBeNull()
    expect(karten('server-connections')).toEqual(['nex-apps', 'interfaces'])
    const worte = areaText(NEXUI_TEXTS.de, 'server-connections', { app: 'nexmail' })!
    expect(worte.title).toBe('Verbindungen')
    expect(teil.querySelector('h1')!.textContent).toBe(worte.title)
    expect(teil.textContent).toContain(worte.text)
    expect(box.querySelector('[data-testid="settings-nav-server-connections"]')!.getAttribute('aria-current')).toBe('page')
    for (const schalter of [
      'Verbindungen mit anderen nex-Apps',
      'Verbindungen ins eigene Netz',
      'Programmschnittstelle (API) für Mitglieder',
      'MCP-Zugang',
      'iPhone-App erlauben',
      'Neue Geräte verbinden',
    ]) {
      expect(teil.textContent, schalter).toContain(schalter)
    }
    for (const name of ['api', 'mcp', 'app', 'pairing']) {
      expect(teil.querySelector(`[data-testid="interfaces-${name}"] input[type="checkbox"], input[type="checkbox"][data-testid="interfaces-${name}"]`), name).not.toBeNull()
    }
    expect(teil.querySelectorAll('input[type="checkbox"]').length).toBeGreaterThanOrEqual(6)
  })

  it.each(['#nex-apps', '#interfaces'])('/settings/general%s führt mit dem Anker nach Server › Verbindungen', async (anker) => {
    await oeffnen(`/settings/general${anker}`)
    expect(wo()).toBe(`/settings/server-connections${anker}`)
    expect(bereichsteil('general')).toBeNull()
    expect(karten('server-connections')).toEqual(['nex-apps', 'interfaces'])
  })

  it('Allgemein hat die beiden Karten nicht mehr, ein anderer Anker bleibt dort', async () => {
    await oeffnen('/settings/general#features')
    expect(wo()).toBe('/settings/general#features')
    const da = karten('general')
    expect(da).toContain('features')
    expect(da).not.toContain('nex-apps')
    expect(da).not.toContain('interfaces')
    const zeile = bereichsteil('general')!.textContent ?? ''
    expect(zeile).not.toContain(NEXUI_TEXTS.de.generalParts.interfaces)
    expect(zeile).not.toContain(NEXUI_TEXTS.de.generalParts.nexApps)
  })
})
