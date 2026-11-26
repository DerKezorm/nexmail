/** E65 (ui 1.1.2): nexmails Zeitpunkte in den Einstellungen in der Form aller Apps, aber in der eingestellten Zone
 * des Kontos („heute, 14:05“, „gestern, 14:05“, sonst „24.02.2027, 14:05“; ein Tag „24.02.2027“). */
import { afterEach, describe, expect, it } from 'vitest'

import { tag, zeitpunkt, zeitzoneSetzen } from './format'

afterEach(() => zeitzoneSetzen(''))

describe('zeitpunkt und tag', () => {
  const jetzt = new Date('2027-02-24T20:00:00Z')

  it('heute, gestern, sonst der Tag mit zwei Ziffern, in der Zone des Kontos', () => {
    zeitzoneSetzen('Europe/Berlin')
    expect(zeitpunkt('2027-02-24T13:05:00Z', 'de', jetzt)).toBe('heute, 14:05')
    expect(zeitpunkt('2027-02-23T13:05:00Z', 'de', jetzt)).toBe('gestern, 14:05')
    expect(zeitpunkt('2027-02-02T08:05:00Z', 'de', jetzt)).toBe('02.02.2027, 09:05')
    expect(zeitpunkt('2027-02-24T13:05:00Z', 'en', jetzt)).toBe('today, 14:05')
    expect(tag('2027-02-02T08:05:00Z', 'de')).toBe('02.02.2027')
    expect(tag('2027-02-02T08:05:00Z', 'en')).toBe('02/02/2027')
  })

  it('der Tag wechselt um Mitternacht der Zone, nicht des Browsers', () => {
    zeitzoneSetzen('Pacific/Auckland')
    // 20:00 UTC am 24. ist in Auckland schon der 25. um 09:00; 23:30 UTC am 23. dort der 24. um 12:30, also gestern.
    expect(zeitpunkt('2027-02-23T23:30:00Z', 'de', jetzt)).toBe('gestern, 12:30')
  })

  it('was kein Datum ist, bleibt, wie es kam', () => {
    expect(zeitpunkt('kein Datum', 'de', jetzt)).toBe('kein Datum')
  })
})
