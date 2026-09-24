import { describe, expect, it } from 'vitest'
import { ankername, linkart, mailtoLesen, textAlsHtml } from './leselinks'

describe('Links in fremden Mails', () => {
  it('eine Seite draußen geht in einen neuen Reiter, auch tel:', () => {
    expect(linkart('https://example.com/a')).toBe('extern')
    expect(linkart('HTTP://example.com')).toBe('extern')
    expect(linkart(' https://example.com ')).toBe('extern')
    expect(linkart('tel:+49301234')).toBe('extern')
  })

  it('mailto: gehört dem Verfassen-Fenster, eine Sprungmarke der Mail selbst', () => {
    expect(linkart('mailto:jemand@example.com')).toBe('mail')
    expect(linkart('MAILTO:jemand@example.com')).toBe('mail')
    expect(linkart('#unten')).toBe('anker')
  })

  it('alles andere führt nirgends hin, auch keine relative Adresse auf nexmail', () => {
    expect(linkart('seite.html')).toBe('tot')
    expect(linkart('/api/nachrichten')).toBe('tot')
    expect(linkart('cid:logo@example.com')).toBe('tot')
    expect(linkart('')).toBe('tot')
    expect(linkart(null)).toBe('tot')
  })

  it('der Name einer Sprungmarke kommt entschlüsselt', () => {
    expect(ankername('#unten')).toBe('unten')
    expect(ankername('#Gr%C3%BC%C3%9Fe')).toBe('Grüße')
  })
})

describe('mailto: lesen', () => {
  it('eine blanke Adresse', () => {
    expect(mailtoLesen('mailto:jemand@example.com')).toEqual({
      an: ['jemand@example.com'],
      kopie: [],
      blindkopie: [],
      betreff: '',
      text: '',
    })
  })

  it('mehrere Empfänger, dazu to=, cc und bcc, Feldnamen ohne Groß und Klein', () => {
    const v = mailtoLesen('mailto:a@example.com,b@example.com?To=c@example.com&CC=d@example.com&bcc=e@example.com')
    expect(v?.an).toEqual(['a@example.com', 'b@example.com', 'c@example.com'])
    expect(v?.kopie).toEqual(['d@example.com'])
    expect(v?.blindkopie).toEqual(['e@example.com'])
  })

  it('Betreff und Text kommen entschlüsselt, Zeilenumbrüche bleiben', () => {
    const v = mailtoLesen('mailto:a@example.com?subject=Anfrage%20zu%20%C3%84pfeln&body=Hallo%2C%0D%0Azweite%20Zeile')
    expect(v?.betreff).toBe('Anfrage zu Äpfeln')
    expect(v?.text).toBe('Hallo,\r\nzweite Zeile')
  })

  it('ein + bleibt ein +, in der Adresse und im Betreff', () => {
    const v = mailtoLesen('mailto:name+etikett@example.com?subject=a+b')
    expect(v?.an).toEqual(['name+etikett@example.com'])
    expect(v?.betreff).toBe('a+b')
  })

  it('der erste Betreff gilt, fremde Kopfzeilen fallen weg', () => {
    const v = mailtoLesen('mailto:a@example.com?subject=eins&subject=zwei&in-reply-to=%3Cx%40example.com%3E&body=A&body=B')
    expect(v).toEqual({ an: ['a@example.com'], kopie: [], blindkopie: [], betreff: 'eins', text: 'A' })
  })

  it('ein kaputtes % wirft nicht, es bleibt stehen', () => {
    expect(mailtoLesen('mailto:a@example.com?subject=100%')?.betreff).toBe('100%')
  })

  it('ohne Adresse vorne, nur mit to=', () => {
    expect(mailtoLesen('mailto:?to=a@example.com')?.an).toEqual(['a@example.com'])
  })

  it('kein mailto: ist keine Vorbelegung', () => {
    expect(mailtoLesen('https://example.com')).toBeNull()
  })
})

describe('Text aus dem Link als Absätze', () => {
  it('jede Zeile ein Absatz, leere Zeilen bleiben', () => {
    expect(textAlsHtml('eins\r\n\r\nzwei')).toBe('<p>eins</p><p></p><p>zwei</p>')
  })

  it('HTML im Link wird Text, kein Markup', () => {
    expect(textAlsHtml('<img src=x onerror=alert(1)> & "q"')).toBe(
      '<p>&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot;</p>',
    )
  })

  it('leer bleibt leer', () => {
    expect(textAlsHtml('')).toBe('')
  })
})
