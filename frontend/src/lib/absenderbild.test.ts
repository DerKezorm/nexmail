import { describe, expect, it } from 'vitest'
import { absenderbildQuelle } from './absenderbild'

const ohne = (p: string) => p
const mitVorbau = (p: string) => `/nexmail${p}`

describe('Adresse des Absenderbilds', () => {
  it('kodiert die Mailadresse, auch ein Plus', () => {
    expect(absenderbildQuelle('a+b@example.com', false, ohne)).toBe(
      '/api/absenderbild?adresse=a%2Bb%40example.com',
    )
  })

  it('nur mit Logo-Wunsch fragt die Adresse nach dem Logo', () => {
    expect(absenderbildQuelle('a@example.com', true, ohne)).toBe('/api/absenderbild?adresse=a%40example.com&logo=1')
    expect(absenderbildQuelle('a@example.com', false, ohne)).not.toContain('logo')
  })

  it('trägt den Vorbau und ist ohne Adresse leer', () => {
    expect(absenderbildQuelle('a@example.com', true, mitVorbau)).toMatch(/^\/nexmail\/api\/absenderbild\?/)
    expect(absenderbildQuelle('', true, mitVorbau)).toBe('')
  })
})
