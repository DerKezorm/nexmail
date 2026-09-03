/**
 * Die Regeln der Anhang-Erinnerung, ohne Browser.
 *
 * ⚠️ **Der Browser-Test dafür bleibt, und er bleibt der teuerste.**
 * `anhang_erinnerung.spec.ts:111` schickt eine echte Mail an ein echtes
 * Postfach, wartet auf die Zustellung, antwortet darauf und räumt beides
 * wieder weg — mit einem Zeitbudget von 300 Sekunden. Er beweist den ganzen
 * Weg: Editor, Zitat, Nachfrage, Versand. Das kann hier nichts ersetzen.
 *
 * ⚠️ **Was er nicht beweist, sind die Regeln selbst.** Welche Wörter zählen,
 * wo das Zitat abgeschnitten wird, ob „unattached" mitzählt — dafür braucht
 * es kein Postfach und keine fünf Minuten. Genau diese Fälle stehen hier, und
 * sie laufen in Millisekunden bei jedem Speichern.
 */

import { describe, expect, it } from 'vitest'

import { ANHANG_SIGNALWOERTER, eigenerText, erwaehntAnhang } from './anhang'

describe('erwaehntAnhang', () => {
  it('trifft die stehenden Wendungen beider Sprachen', () => {
    for (const wort of ANHANG_SIGNALWOERTER) {
      expect(erwaehntAnhang(`Guten Tag, ${wort} finden Sie alles.`), wort).toBe(true)
    }
  })

  it('achtet nicht auf Groß- und Kleinschreibung', () => {
    expect(erwaehntAnhang('IM ANHANG die Rechnung')).toBe(true)
    expect(erwaehntAnhang('Please find Attached')).toBe(true)
  })

  it('braucht einen Wortanfang', () => {
    // ⚠️ Der Grund für die Bindung nach vorn: „unattached" ist kein Anhang.
    expect(erwaehntAnhang('the file is unattached')).toBe(false)
    expect(erwaehntAnhang('Zwischenanbei steht nichts')).toBe(false)
  })

  it('trifft auch, was ein Signalwort nur anfängt', () => {
    /* ⚠️ **Der Preis des offenen Wortendes, und er ist bewusst bezahlt.**
       Im Quelltext stand bis zum 03.09.2026, aus „anbeißen" werde kein
       „anbei" — das war falsch: Ein Wortende, das für „attachments" offen ist,
       lässt sich für „anbeißen" nicht schließen. Aufgefallen, als dieser Test
       den zugesagten Fall nachprüfte.

       Der Tausch stimmt trotzdem: Ein zu viel gefragter Anhang kostet einen
       Klick, ein vergessener eine zweite Mail. Der Test hält fest, dass es
       eine Entscheidung ist und kein Versehen. */
    expect(erwaehntAnhang('nicht anbeissen')).toBe(true)
  })

  it('lässt das Wortende offen', () => {
    expect(erwaehntAnhang('siehe attachments unten')).toBe(true)
    expect(erwaehntAnhang('die angehängte Rechnung')).toBe(true)
  })

  it('sagt bei einem harmlosen Text Nein', () => {
    expect(erwaehntAnhang('Danke für das Gespräch, bis Montag.')).toBe(false)
  })
})

describe('eigenerText', () => {
  it('schneidet das Zitat ab', () => {
    // ⚠️ Der eigentliche Zweck: Wer auf „die Rechnung liegt im Anhang"
    // antwortet, hat den Anhang nicht selbst erwähnt — der Absender hat es.
    const html = '<p>Danke, ist angekommen.</p><blockquote>Die Rechnung liegt im Anhang</blockquote>'
    expect(erwaehntAnhang(eigenerText(html, ''))).toBe(false)
  })

  it('schneidet die weitergeleitete Nachricht ab', () => {
    const html =
      '<p>Zur Kenntnis.</p>---------- Weitergeleitete Nachricht ----------<p>anbei die Unterlagen</p>'
    expect(erwaehntAnhang(eigenerText(html, ''))).toBe(false)
  })

  it('entfernt die Signatur', () => {
    // Eine Signatur mit „anbei" wäre sonst eine Nachfrage bei jeder Mail.
    const signatur = '<p>Viele Grüße, anbei mein Kalender</p>'
    expect(erwaehntAnhang(eigenerText(`<p>Kurze Frage.</p>${signatur}`, signatur))).toBe(false)
  })

  it('lässt den eigenen Text stehen', () => {
    const html = '<p>Die Zahlen sind im Anhang.</p><blockquote>Alte Mail</blockquote>'
    expect(erwaehntAnhang(eigenerText(html, ''))).toBe(true)
  })

  it('macht aus Auszeichnung und Entitäten lesbaren Text', () => {
    expect(eigenerText('<p>A&nbsp;&amp;&nbsp;B</p>', '')).toBe('A & B')
  })
})
