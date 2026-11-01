import { describe, expect, it } from 'vitest'
import { ausMenue, befehleFiltern, HOECHSTENS } from './befehle'
import type { Befehl } from './befehle'

const nichts = () => undefined

function befehl(text: string, gruppe = 'allgemein'): Befehl {
  return { id: text, text, gruppe, tun: nichts }
}

describe('ausMenue', () => {
  it('macht ein Untermenü zu Zeilen mit seinem Weg', () => {
    const zeilen = ausMenue(
      [
        { id: 'a', text: 'Antworten', tun: nichts },
        {
          id: 'v',
          text: 'Verschieben',
          unter: [
            { id: 'x', text: 'Archiv', tun: nichts },
            { id: 'k', text: 'Privat', unter: [{ id: 'y', text: 'Rechnungen', tun: nichts }] },
          ],
        },
      ],
      'mail',
    )
    expect(zeilen.map((z) => z.text)).toEqual([
      'Antworten',
      'Verschieben › Archiv',
      'Verschieben › Privat › Rechnungen',
    ])
  })

  it('lässt Gesperrtes und Leeres weg', () => {
    const zeilen = ausMenue(
      [
        { id: 'a', text: 'Antworten', deaktiviert: true, tun: nichts },
        { id: 'b', text: 'Ohne Handlung' },
        { id: 'c', text: 'Geht', tun: nichts },
      ],
      'mail',
    )
    expect(zeilen.map((z) => z.text)).toEqual(['Geht'])
  })

  it('gibt jeder Zeile eine eigene Kennung, auch bei gleichen Ordnern', () => {
    const zeilen = ausMenue(
      [
        { id: 'k1', text: 'Eins', unter: [{ id: 'o', text: 'Archiv', tun: nichts }] },
        { id: 'k2', text: 'Zwei', unter: [{ id: 'o', text: 'Archiv', tun: nichts }] },
      ],
      'mail',
    )
    expect(new Set(zeilen.map((z) => z.id)).size).toBe(2)
  })

  it('reicht die Handlung und die Warnfarbe durch', () => {
    let lief = false
    const [zeile] = ausMenue(
      [{ id: 'l', text: 'Löschen', gefaehrlich: true, tun: () => (lief = true) }],
      'mail',
    )
    zeile.tun()
    expect(lief).toBe(true)
    expect(zeile.gefaehrlich).toBe(true)
  })
})

describe('befehleFiltern', () => {
  const ohne = new Set<string>()

  it('findet ohne Rücksicht auf Groß, klein und Umlaute', () => {
    const zeilen = befehleFiltern([befehl('Löschen'), befehl('Antworten')], 'LOSCH', ohne)
    expect(zeilen.map((z) => z.text)).toEqual(['Löschen'])
  })

  it('verlangt alle Wörter, in beliebiger Reihenfolge', () => {
    const liste = [befehl('Verschieben › Archiv'), befehl('Archivieren'), befehl('Verschieben › Junk')]
    expect(befehleFiltern(liste, 'archiv versch', ohne).map((z) => z.text)).toEqual([
      'Verschieben › Archiv',
    ])
  })

  it('stellt nach vorn, was mit dem Gesuchten beginnt', () => {
    const liste = [befehl('Verschieben › Archiv'), befehl('Archivieren')]
    expect(befehleFiltern(liste, 'archiv', ohne).map((z) => z.text)).toEqual([
      'Archivieren',
      'Verschieben › Archiv',
    ])
  })

  it('zeigt ohne Eingabe die Ordner nicht, findet sie aber', () => {
    const liste = [befehl('Neue Nachricht'), befehl('Rechnungen', 'ordner')]
    const nurGesucht = new Set(['ordner'])
    expect(befehleFiltern(liste, '  ', nurGesucht).map((z) => z.text)).toEqual(['Neue Nachricht'])
    expect(befehleFiltern(liste, 'rech', nurGesucht).map((z) => z.text)).toEqual(['Rechnungen'])
  })

  it('zeigt ohne Eingabe keine Untermenüs, findet sie aber', () => {
    const liste = [befehl('Antworten'), befehl('Verschieben › Archiv')]
    expect(befehleFiltern(liste, '', ohne).map((z) => z.text)).toEqual(['Antworten'])
    expect(befehleFiltern(liste, 'arch', ohne).map((z) => z.text)).toEqual(['Verschieben › Archiv'])
  })

  it('deckelt die Liste', () => {
    const viele = Array.from({ length: HOECHSTENS + 5 }, (_, i) => befehl(`Ordner ${i}`))
    expect(befehleFiltern(viele, 'ordner', ohne)).toHaveLength(HOECHSTENS)
    expect(befehleFiltern(viele, '', ohne)).toHaveLength(HOECHSTENS)
  })
})
