import { describe, expect, it } from 'vitest'
import { ordnerName, WIEDERVORLAGE_PFAD } from './ordnername'

const t = (s: string) => `«${s}»`

describe('ordnerName', () => {
  it('übersetzt den Posteingang', () => {
    expect(ordnerName({ rolle: 'posteingang', name: 'INBOX', pfad: 'INBOX' }, t)).toBe(
      '«ordner.posteingang»',
    )
  })

  it('übersetzt den Ordner der Wiedervorlage', () => {
    expect(ordnerName({ rolle: '', name: 'Wiedervorlage', pfad: WIEDERVORLAGE_PFAD }, t)).toBe(
      '«ordner.wiedervorlage»',
    )
  })

  it('lässt einen gleichnamigen Unterordner, wie er ist', () => {
    expect(ordnerName({ rolle: '', name: 'Wiedervorlage', pfad: 'Ablage/Wiedervorlage' }, t)).toBe(
      'Wiedervorlage',
    )
  })

  it('lässt alle anderen Ordner beim Namen des Servers', () => {
    expect(ordnerName({ rolle: 'junk', name: 'Spam', pfad: 'Spam' }, t)).toBe('Spam')
  })
})
