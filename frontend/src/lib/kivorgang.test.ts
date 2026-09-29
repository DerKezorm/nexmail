import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'
import de from '../i18n/de.json'
import { vorgangFehler } from './kivorgang'

const i18n = i18next.createInstance()

beforeAll(async () => {
  await i18n.init({
    lng: 'de',
    resources: { de: { translation: de } },
    interpolation: { escapeValue: false },
  })
})

describe('Der Fehlersatz in der Liste „Was hinausging"', () => {
  it('setzt die gespeicherten Werte ein', () => {
    expect(vorgangFehler(i18n, 'ki_dienst_sagt', { code: 400, gesagt: 'temperature is deprecated' })).toBe(
      'Der Dienst hat mit einem Fehler geantwortet (400: temperature is deprecated).',
    )
    expect(vorgangFehler(i18n, 'ki_zeitueberschreitung', { sekunden: 120 })).toContain('120 Sekunden')
  })

  it('zeigt nie einen rohen Platzhalter, auch ohne Werte', () => {
    for (const kennung of ['ki_dienst_antwortet_nicht', 'ki_dienst_sagt', 'ki_zeitueberschreitung']) {
      const satz = vorgangFehler(i18n, kennung, {})
      expect(satz).not.toContain('{{')
      expect(satz).toBe(de.ki.fehlgeschlagen)
    }
    // Ein Teil der Werte reicht nicht.
    expect(vorgangFehler(i18n, 'ki_dienst_sagt', { code: 400 })).toBe(de.ki.fehlgeschlagen)
  })

  it('ein Fehler ohne Werte bleibt sein eigener Satz', () => {
    expect(vorgangFehler(i18n, 'ki_nicht_erreichbar')).toBe(de.serverfehler.ki_nicht_erreichbar)
  })

  it('eine unbekannte Kennung erscheint nicht roh', () => {
    expect(vorgangFehler(i18n, 'gibt_es_nicht')).toBe(de.ki.fehlgeschlagen)
  })
})
