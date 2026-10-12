/* „Was ist neu“: Kein Eintrag verschwindet lautlos.
 *
 * ⚠️ **Warum es diese Datei gibt.** Ein Eintrag, dem eines der vier Felder
 * fehlt, wird weggelassen, und zwar ohne Meldung. In Nexview stand so zweimal
 * nach dem Update kein Banner da, und das Fenster zeigte den Text der Version
 * davor. Hier fällt das vor dem Release auf. Dass eine Version auf `.0` einen
 * Text braucht, prüft `backend/tests/test_wasneu.py`: Die Version kennt nur
 * der Server.
 */
import { describe, expect, it } from 'vitest'
import de from '../i18n/wasneu/de.json'
import en from '../i18n/wasneu/en.json'
import { dateiFuer, gueltige, istEintrag } from './wasneu'

const vollstaendig = {
  lead: 'Ein Satz.',
  sections: [{ title: 'Neu', where: 'Oben', body: 'Was es tut.' }],
  smallTitle: 'Außerdem',
  small: ['Eine Kleinigkeit.'],
}

describe('jeder Eintrag in beiden Sprachen', () => {
  it.each([
    ['de', de],
    ['en', en],
  ] as const)('%s: alle vier Felder, sonst fiele er lautlos weg', (_sprache, datei) => {
    const alle = Object.keys(datei)
    expect(alle.length, 'Die Datei ist leer').toBeGreaterThan(0)
    expect(Object.keys(gueltige(datei))).toEqual(alle)
  })

  it('beide Sprachen kennen dieselben Versionen, gleich gegliedert', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(de).sort())
    for (const version of Object.keys(de) as (keyof typeof de)[]) {
      const d = de[version]
      const e = en[version as keyof typeof en]
      expect(e.sections.length, version).toBe(d.sections.length)
      expect(e.small.length, version).toBe(d.small.length)
    }
  })

  it('die Schlüssel sind Versionen', () => {
    for (const version of Object.keys(de)) expect(version).toMatch(/^\d+\.\d+\.\d+$/)
  })
})

describe('die Prüfung selbst', () => {
  it('nimmt einen vollständigen Eintrag', () => {
    expect(istEintrag(vollstaendig)).toBe(true)
  })

  it.each([
    ['ohne lead', { ...vollstaendig, lead: '' }],
    ['ohne Abschnitte', { ...vollstaendig, sections: [] }],
    ['Abschnitt ohne where', { ...vollstaendig, sections: [{ title: 'a', body: 'b' }] }],
    ['Abschnitt mit leerem body', { ...vollstaendig, sections: [{ title: 'a', where: 'b', body: ' ' }] }],
    ['ohne smallTitle', { ...vollstaendig, smallTitle: undefined }],
    ['small keine Liste', { ...vollstaendig, small: 'x' }],
    ['small mit Leerem', { ...vollstaendig, small: ['a', ''] }],
    ['gar kein Objekt', 'Text'],
  ])('verwirft einen Eintrag %s', (_fall, eintrag) => {
    expect(istEintrag(eintrag)).toBe(false)
  })

  it('Deutsch für Deutsch, Englisch für alles andere', () => {
    expect(dateiFuer('de')).toBe('de')
    expect(dateiFuer('de-AT')).toBe('de')
    expect(dateiFuer('en')).toBe('en')
    expect(dateiFuer('fr')).toBe('en')
  })
})
