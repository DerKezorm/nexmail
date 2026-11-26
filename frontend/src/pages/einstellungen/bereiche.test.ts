/* Wer welche Bereiche der Einstellungen sieht, in welcher Reihenfolge, und welche Adressen wohin führen.
 *
 * Dieselben Grenzen wie vor dem Bauplan „Einstellungen": Server nur der Betreiber, die KI (persönlich) der Betreiber
 * immer und sonst nur mit `ki_erlaubt`, „Über nexmail" jeder. Neu: englische Slugs, die deutschen Namen von vorher
 * führen dauerhaft auf sie, der Riegel der KI steht unter Server › KI-Anbieter. */
import { describe, expect, it } from 'vitest'
import type { Ich } from '../../api/client'
import { ALTE_NAMEN, BEREICHE, bereichAusPfad, bereicheFuer, bereichVon, erlaubterBereich, pfadVon, ueberSichtbar } from './bereiche'

function ich(teil: Partial<Ich>): Ich {
  return {
    id: 'x',
    benutzername: 'x',
    anzeigename: 'X',
    ist_betreiber: false,
    zwei_faktor_aktiv: false,
    offene_codes: 0,
    kontaktadresse: '',
    ki_aktiv: false,
    ki_erlaubt: false,
    ki_fremde_post: false,
    absenderlogos: false,
    version: '0',
    wasneu_gesehen: '0',
    ...teil,
  }
}

const ids = (i: Ich) => bereicheFuer(i).map((b) => b.id)
const SERVER = ['general', 'sign-in', 'mail', 'storage', 'ai-provider', 'accounts', 'log']

describe('Sichtbarkeit der Bereiche', () => {
  it('der Betreiber sieht alles', () => {
    expect(ids(ich({ ist_betreiber: true }))).toEqual(BEREICHE.map((b) => b.id))
    expect(ueberSichtbar(ich({ ist_betreiber: true }))).toBe(true)
  })

  it('ein Benutzer sieht keinen Bereich der Gruppe Server', () => {
    const sieht = ids(ich({}))
    for (const s of SERVER) expect(sieht).not.toContain(s)
    // Alles, was vorher in seinen eigenen Einstellungen stand, bleibt.
    for (const b of ['profile', 'security', 'appearance', 'notifications', 'connections', 'calendars',
      'mailboxes', 'rules', 'signatures', 'out-of-office', 'tags'] as const) {
      expect(sieht).toContain(b)
    }
  })

  it('KI nur mit Erlaubnis, wie vorher der Punkt in der Leiste', () => {
    expect(ids(ich({}))).not.toContain('ai')
    expect(ids(ich({ ki_erlaubt: true }))).toContain('ai')
    expect(ids(ich({ ki_erlaubt: true }))).not.toContain('ai-provider')
  })

  it('„Über nexmail" sieht jeder Angemeldete', () => {
    expect(ueberSichtbar(ich({}))).toBe(true)
    expect(ueberSichtbar(null)).toBe(false)
  })

  it('ein gesperrter Bereich führt zum Profil, auch wenn das Konto kein Betreiber mehr ist', () => {
    for (const s of SERVER) expect(erlaubterBereich(s as never, ich({}))).toBe('profile')
    expect(erlaubterBereich('ai', ich({}))).toBe('profile')
    expect(erlaubterBereich('general', ich({ ist_betreiber: true }))).toBe('general')
  })
})

describe('Reihenfolge nach dem Bauplan', () => {
  it('Mein Konto: Profil, Sicherheit, Darstellung, eigene Bereiche, Benachrichtigungen, Verbindungen', () => {
    expect(BEREICHE.filter((b) => b.gruppe === 'account').map((b) => b.id)).toEqual([
      'profile', 'security', 'appearance', 'calendars', 'ai', 'notifications', 'connections',
    ])
  })

  it('Mail: Postfächer, Regeln, Signaturen, Abwesenheit, Schlagworte', () => {
    expect(BEREICHE.filter((b) => b.gruppe === 'mail').map((b) => b.id)).toEqual([
      'mailboxes', 'rules', 'signatures', 'out-of-office', 'tags',
    ])
  })

  it('Server: Allgemein, Anmeldung, Mail, Speicher, eigene (KI-Anbieter), Konten, Log', () => {
    expect(BEREICHE.filter((b) => b.gruppe === 'server').map((b) => b.id)).toEqual(SERVER)
  })
})

describe('Adressen', () => {
  it('jeder Bereich unter /settings/<slug>, /settings allein ist die Liste', () => {
    for (const b of BEREICHE) expect(bereichAusPfad(pfadVon(b.id))).toEqual({ bereich: b.id, ersetzen: false })
    expect(bereichAusPfad('/settings')).toEqual({ liste: true })
    expect(bereichAusPfad('/settings/about')).toEqual({ bereich: 'about', ersetzen: false })
  })

  it('jeder alte deutsche Name führt dauerhaft auf seinen Bereich', () => {
    expect(Object.keys(ALTE_NAMEN).sort()).toEqual([
      'abwesenheit', 'allgemein', 'anmeldung', 'benachrichtigungen', 'darstellung', 'kalender', 'ki', 'konten',
      'mailversand', 'postfaecher', 'profil', 'regeln', 'schlagworte', 'sicherheit', 'signaturen', 'speicher',
      'ueber', 'verbindungen',
    ])
    for (const [alt, neu] of Object.entries(ALTE_NAMEN)) {
      expect(bereichVon(alt)).toBe(neu)
      expect(bereichAusPfad(`/settings/${alt}`)).toEqual({ bereich: neu, ersetzen: true })
      expect(bereichAusPfad(`/einstellungen/${alt}`)).toEqual({ bereich: neu, ersetzen: true })
    }
    expect(bereichAusPfad('/einstellungen')).toEqual({ bereich: 'profile', ersetzen: true })
  })

  it('andere Adressen gehören nicht zu den Einstellungen; ein unbekannter Bereich wird das Profil', () => {
    expect(bereichAusPfad('/')).toBeNull()
    expect(bereichAusPfad('/konto/sicherheit')).toBeNull()
    expect(bereichAusPfad('/settingsfoo')).toBeNull()
    expect(bereichAusPfad('/settings/gibt-es-nicht')).toEqual({ bereich: 'profile', ersetzen: true })
  })
})

describe('Server › Allgemein (ui 1.1.3, U-3)', () => {
  it('der Untertitel nennt nur die Karten, die nexmail dort hat, in ihrer Reihenfolge', async () => {
    const { NEXUI_TEXTS, areaText } = await import('../../vendor/nexui')
    const { ALLGEMEIN_TEILE } = await import('./bereiche')
    const de = areaText(NEXUI_TEXTS.de, 'general', { app: 'nexmail', parts: ALLGEMEIN_TEILE })?.text ?? ''
    const teile = NEXUI_TEXTS.de.generalParts
    let davor = -1
    for (const teil of ALLGEMEIN_TEILE) {
      const stelle = de.indexOf(teile[teil])
      expect(stelle, teil).toBeGreaterThan(davor)
      davor = stelle
    }
    expect(de).not.toContain(teile.limits)
    expect(de).not.toContain(teile.webPush)
    const en = areaText(NEXUI_TEXTS.en, 'general', { app: 'nexmail', parts: ALLGEMEIN_TEILE })?.text ?? ''
    expect(en).not.toContain(NEXUI_TEXTS.en.generalParts.limits)
  })
})
