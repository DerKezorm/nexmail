import { describe, expect, it } from 'vitest'
import { anlegeOptionen, anmeldeOptionen, geraetename, zuBytes, zuText } from './passkey'

describe('passkey', () => {
  it('turns base64url into bytes and back, without padding', () => {
    for (const text of ['', 'AA', 'AAE', 'AAEC', '_-8', 'aGVsbG8gd29ybGQ']) {
      expect(zuText(zuBytes(text))).toBe(text)
    }
    expect(Array.from(new Uint8Array(zuBytes('_-8')))).toEqual([255, 239])
  })

  it('makes the challenge, the user id and the excluded passkeys bytes for the browser', () => {
    const o = anlegeOptionen({
      challenge: 'AAEC',
      rp: { id: 'mail.example', name: 'nexmail' },
      user: { id: 'AQI', name: 'mona', displayName: 'Mona' },
      excludeCredentials: [{ id: 'AwQ', type: 'public-key' }],
    })
    expect(Array.from(new Uint8Array(o.challenge as ArrayBuffer))).toEqual([0, 1, 2])
    expect(Array.from(new Uint8Array(o.user.id as ArrayBuffer))).toEqual([1, 2])
    expect(o.user.name).toBe('mona')
    expect(Array.from(new Uint8Array(o.excludeCredentials![0].id as ArrayBuffer))).toEqual([3, 4])
    const a = anmeldeOptionen({ challenge: 'AAEC', rpId: 'mail.example' })
    expect(a.rpId).toBe('mail.example')
    expect(a.allowCredentials).toBeUndefined()
  })

  it('suggests a name from the system, never the raw header', () => {
    expect(geraetename('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)')).toBe('iPhone')
    expect(geraetename('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('Windows')
    expect(geraetename('please visit https://evil.example')).toBe('Passkey')
  })
})
