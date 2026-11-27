/* Verweise auf Orte in nexmail und in den anderen nex-Apps (Bauplan „Einstellungen“, E39): Was nexmail über einen Ort
 * sagt, nennt ihn so, wie die Navigation heute heißt; was es über nextasks und nextime sagt, passt zu deren Stand
 * (Mein Konto → Verbindungen → API-Schlüssel, Server → Verbindungen → Schnittstellen). Todoist behält sein eigenes Wort
 * „API-Token“, weil Todoist es so nennt. */
import { describe, expect, it } from 'vitest'

import de from './de.json'
import en from './en.json'

type Baum = { [k: string]: string | Baum }

function blaetter(baum: Baum, vor = ''): [string, string][] {
  return Object.entries(baum).flatMap(([k, v]) => (typeof v === 'string' ? [[vor + k, v] as [string, string]] : blaetter(v, `${vor}${k}.`)))
}

const ALT: Record<'de' | 'en', RegExp[]> = {
  de: [/Schlüssel für Programme/, /Server → API\b/, /Einstellungen → Signaturen/, /siehe Protokoll/, /Rücksetzpunkt/, /in den Einstellungen unter Aufgaben/, /Token erneuern/, /Allgemein › (Schnittstellen|Andere nex-Apps)/],
  en: [/Keys for programs/, /Server → API\b/, /Settings → Signatures/, /restore point/i, /Settings, Tasks/, /Renew token/, /General › (Interfaces|Other nex apps)/],
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
    expect(de.serverfehler.nextasks_api_aus).toContain('Server › Verbindungen › Schnittstellen')
    expect(de.serverfehler.nextasks_zugang_ungueltig).toContain('Mein Konto › Verbindungen › API-Schlüssel')
    expect(de.nextime.hinweis).toContain('Mein Konto › Verbindungen › API-Schlüssel')
    expect(de.serverfehler.api_schluessel_abgeschaltet).toContain('Server › Verbindungen › Schnittstellen')
    expect(de.serverfehler.app_adresse_fehlt).toContain('Server › Anmeldung')
    expect(de.regeln.schlagwort_keins).toContain('Mail › Schlagworte')
    expect(en.serverfehler.nextime_api_aus).toContain('Server › Connections › Interfaces')
    expect(en.todoapps.nextasks_hinweis).toContain('My account › Connections › API keys')
    expect(en.verfassen.vorlagen_leer).toContain('Mail › Signatures')
  })
})

/* E46: Ortsangaben mit „›“, vorn die Gruppe; nie Pfeile oder Kommas als Trenner. Die Schritte in fremden Programmen
 * (Google Cloud Console, Entra) behalten deren Schreibweise. */
const FREMD = new Set([
  'oauth.anleitung_google',
  'oauth.anleitung_microsoft',
  'oauth.g2_text',
  'oauth.g3_titel',
  'oauth.g4_titel',
  'oauth.g5_titel',
  'oauth.g6_titel',
  'kalender.fehler_caldav_google_api_aus',
  'kontakte.buch_fehler_carddav_google_api_aus',
])
const BEREICHE: Record<'de' | 'en', string> = {
  de: '(?:Einstellungen|Mein Konto|Server|Mail|Profil|Sicherheit|Darstellung|Benachrichtigungen|Verbindungen|Allgemein|Anmeldung|Konten|Log)',
  en: '(?:Settings|My account|Server|Mail|Profile|Security|Appearance|Notifications|Connections|General|Sign-in|Accounts|Log)',
}

describe('Ortsangaben (E46)', () => {
  for (const [sprache, baum] of [['de', de], ['en', en]] as const) {
    it(`${sprache}: Trenner „›“, kein Pfeil und kein Komma`, () => {
      const pfeil = new RegExp(`${BEREICHE[sprache]}\\s*(?:→|->|>|,)\\s*${BEREICHE[sprache]}`)
      const treffer = blaetter(baum as Baum).filter(([schluessel, text]) => !FREMD.has(schluessel) && (text.includes('→') || pfeil.test(text)))
      expect(treffer).toEqual([])
    })

    it(`${sprache}: eine Ortsangabe beginnt mit der Gruppe, nicht mit „${sprache === 'de' ? 'Einstellungen' : 'Settings'} ›“`, () => {
      const vorn = sprache === 'de' ? /Einstellungen ›/ : /Settings ›/
      expect(blaetter(baum as Baum).filter(([, text]) => vorn.test(text))).toEqual([])
    })
  }
})

/* E49: In „Was ist neu“ zeigt jedes „wo“ auf den heutigen Ort, mit „›“; die Texte älterer Einträge bleiben. Die Texte
   liegen seit dem Modul wasneu 0.1.0 beim Server (`backend/app/wasneu/`) und werden hier gelesen, nicht gebaut. */
type Fs = { readFileSync: (file: string, encoding: string) => string }
// Zur Laufzeit beim Namen geladen: das TypeScript der Oberfläche kennt keine Node-Typen. vitest läuft in frontend/.
const fsName = 'node:fs'
const fs = (await import(/* @vite-ignore */ fsName)) as Fs
const wasneu = (sprache: string): unknown => JSON.parse(fs.readFileSync(`../backend/app/wasneu/${sprache}.json`, 'utf-8'))
const wasneuDe = wasneu('de')
const wasneuEn = wasneu('en')

describe('Was ist neu: wo (E49)', () => {
  for (const [sprache, eintraege] of [['de', wasneuDe], ['en', wasneuEn]] as const) {
    it(`${sprache}: kein „wo“ mit Pfeil, Reiter oder altem Ort`, () => {
      const alt = sprache === 'de' ? /→|Reiter|Verwaltung|Benutzermenü|Zahnrad|^Einstellungen ›/ : /→|the “[^”]*” tab|Administration|user menu|gear|^Settings ›/
      const wo = Object.values(eintraege as Record<string, { sections?: { where?: string }[] }>).flatMap((e) => (e.sections ?? []).map((s) => s.where ?? ''))
      expect(wo.length).toBeGreaterThan(20)
      expect(wo.filter((w) => alt.test(w))).toEqual([])
    })
  }
})
