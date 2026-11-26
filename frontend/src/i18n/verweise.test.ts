/* Verweise auf Orte in nexmail und in den anderen nex-Apps (Bauplan „Einstellungen“, E39): Was nexmail über einen Ort
 * sagt, nennt ihn so, wie die Navigation heute heißt; was es über nextasks und nextime sagt, passt zu deren Stand
 * (Mein Konto → Verbindungen → API-Schlüssel, Server → Allgemein → Schnittstellen). Todoist behält sein eigenes Wort
 * „API-Token“, weil Todoist es so nennt. */
import { describe, expect, it } from 'vitest'

import de from './de.json'
import en from './en.json'

type Baum = { [k: string]: string | Baum }

function blaetter(baum: Baum, vor = ''): [string, string][] {
  return Object.entries(baum).flatMap(([k, v]) => (typeof v === 'string' ? [[vor + k, v] as [string, string]] : blaetter(v, `${vor}${k}.`)))
}

const ALT: Record<'de' | 'en', RegExp[]> = {
  de: [/Schlüssel für Programme/, /Server → API\b/, /Einstellungen → Signaturen/, /siehe Protokoll/, /Rücksetzpunkt/, /in den Einstellungen unter Aufgaben/, /Token erneuern/],
  en: [/Keys for programs/, /Server → API\b/, /Settings → Signatures/, /restore point/i, /Settings, Tasks/, /Renew token/],
}

describe('Verweise auf Orte (E39)', () => {
  for (const [sprache, baum] of [['de', de], ['en', en]] as const) {
    it(`${sprache}: kein Text nennt einen alten Ort`, () => {
      const treffer = blaetter(baum as Baum).filter(([, text]) => ALT[sprache].some((muster) => muster.test(text)))
      expect(treffer).toEqual([])
    })

    it(`${sprache}: „API-Token“ nur noch für Todoist und authentik`, () => {
      const wort = sprache === 'de' ? /API-Token/ : /API token/
      const treffer = blaetter(baum as Baum).filter(([schluessel, text]) => wort.test(text) && !/todoist/i.test(schluessel + text))
      expect(treffer).toEqual([])
    })
  }

  it('nennt die neuen Orte in nextasks, nextime und nexmail', () => {
    expect(de.serverfehler.nextasks_api_aus).toContain('Einstellungen → Server → Allgemein → Schnittstellen')
    expect(de.serverfehler.nextasks_zugang_ungueltig).toContain('Einstellungen → Mein Konto → Verbindungen → API-Schlüssel')
    expect(de.nextime.hinweis).toContain('Einstellungen → Mein Konto → Verbindungen → API-Schlüssel')
    expect(de.serverfehler.api_schluessel_abgeschaltet).toContain('Einstellungen → Server → Allgemein → Schnittstellen')
    expect(de.serverfehler.app_adresse_fehlt).toContain('Einstellungen → Server → Anmeldung')
    expect(en.serverfehler.nextime_api_aus).toContain('Settings → Server → General → Interfaces')
    expect(en.todoapps.nextasks_hinweis).toContain('Settings → My account → Connections → API keys')
    expect(en.verfassen.vorlagen_leer).toContain('Settings → Mail → Signatures')
  })
})
