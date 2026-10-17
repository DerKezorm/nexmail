import { describe, expect, it } from 'vitest'
import { elternVon, namensraumWurzel, ordnerName, WIEDERVORLAGE_PFAD } from './ordnername'

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

describe('Wiedervorlage mit Namensraum', () => {
  it('übersetzt sie auch unter INBOX., wenn der Server es sagt', () => {
    expect(
      ordnerName(
        { rolle: '', name: 'Wiedervorlage', pfad: 'INBOX.Wiedervorlage', wiedervorlage: true },
        t,
      ),
    ).toBe('«ordner.wiedervorlage»')
  })

  it('glaubt dem Server auch im Nein', () => {
    expect(
      ordnerName(
        { rolle: '', name: 'Wiedervorlage', pfad: WIEDERVORLAGE_PFAD, wiedervorlage: false },
        t,
      ),
    ).toBe('Wiedervorlage')
  })
})

/* Issue #12: Dovecot bei Hetzner meldet den Namensraum `INBOX.`, jeder eigene
   Ordner heißt `INBOX.Name`. */
describe('elternVon', () => {
  const ordner = (pfad: string, namensraum = '') => ({ pfad, namensraum })

  it('kennt die Wurzel des Namensraums', () => {
    expect(namensraumWurzel('INBOX.')).toBe('INBOX')
    expect(namensraumWurzel('INBOX/')).toBe('INBOX')
    expect(namensraumWurzel('')).toBeNull()
    expect(namensraumWurzel(undefined)).toBeNull()
  })

  it('stellt INBOX.Name bei Namensraum INBOX. nach oben, wie Thunderbird', () => {
    const liste = [ordner('INBOX', 'INBOX.'), ordner('INBOX.Rechnungen', 'INBOX.')]
    expect(elternVon(liste[1], liste)).toBeUndefined()
  })

  it('lässt tiefere Ebenen unter ihrem Ordner', () => {
    const liste = [
      ordner('INBOX', 'INBOX.'),
      ordner('INBOX.Haus', 'INBOX.'),
      ordner('INBOX.Haus.Rechnungen', 'INBOX.'),
    ]
    expect(elternVon(liste[2], liste)?.pfad).toBe('INBOX.Haus')
  })

  it('lässt ohne Namensraum einen Unterordner des Posteingangs, wo er ist', () => {
    const liste = [ordner('INBOX'), ordner('INBOX/Rechnungen')]
    expect(elternVon(liste[1], liste)?.pfad).toBe('INBOX')
  })

  it('hält einen gleichen Wortanfang nicht für einen Vorfahren', () => {
    const liste = [ordner('Archiv'), ordner('Archivalien')]
    expect(elternVon(liste[1], liste)).toBeUndefined()
  })
})
