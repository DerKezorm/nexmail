/* Wo der eigene Text aufhört — die Grenze, an der der KI-Knopf abschneidet.
 *
 * ⚠️ **Was hier schiefgeht, geht nach draußen.** Schneidet die Funktion zu
 * spät, wandert fremde Post zu einem KI-Anbieter; schneidet sie zu früh,
 * fehlt dem Modell die Hälfte des eigenen Textes. Beide Richtungen haben
 * deshalb ihren Test.
 */
import { describe, expect, it } from 'vitest'
import { eigenesHtml, zitatBeginn } from './eigenerteil'

const SIGNATUR = '<p>Viele Grüße<br>Alex Bergmann<br>Musterfirma GmbH</p>'

describe('zitatBeginn', () => {
  it('findet das blockquote', () => {
    const html = '<p>Meine Antwort</p><blockquote><p>Alte Mail</p></blockquote>'
    expect(zitatBeginn(html)).toBe(html.indexOf('<blockquote'))
  })

  it('findet die Weiterleitungszeile', () => {
    const html = '<p>Schau mal</p><p>---------- Weitergeleitete Nachricht ----------</p>'
    expect(zitatBeginn(html)).toBe(html.indexOf('----------'))
  })

  it('nimmt die FRÜHERE der beiden Marken — in beiden Reihenfolgen', () => {
    /* ⚠️ **Beide Richtungen, und das ist keine Gründlichkeit, sondern Pflicht.**
       Der erste Anlauf prüfte nur den Fall, in dem die Weiterleitungszeile vor
       dem `blockquote` steht. Dort steht sie in der Liste an zweiter Stelle,
       überschreibt also am Ende ohnehin — und die Mutation „nimm die letzte
       statt der frühesten" lief glatt durch. Erst der umgekehrte Fall trennt
       die beiden Fassungen: eine Antwort auf eine weitergeleitete Mail, bei der
       das Zitat vorn steht und die Trennzeile darin.

       Prüffrage, die daraus folgt: Hängt mein Ergebnis an der Reihenfolge der
       Liste oder an der Stelle im Text? */
    const zitatZuerst =
      '<p>Meins</p><blockquote><p>---------- Weitergeleitete Nachricht ----------</p></blockquote>'
    expect(zitatBeginn(zitatZuerst)).toBe(zitatZuerst.indexOf('<blockquote'))

    const trennzeileZuerst =
      '<p>Meins</p><p>---------- Weitergeleitete Nachricht ----------</p><blockquote>fremd</blockquote>'
    expect(zitatBeginn(trennzeileZuerst)).toBe(trennzeileZuerst.indexOf('----------'))
  })

  it('gibt ohne Zitat die volle Länge', () => {
    const html = '<p>Nur ich</p>'
    expect(zitatBeginn(html)).toBe(html.length)
  })
})

describe('eigenesHtml', () => {
  it('schneidet das Zitat weg', () => {
    const html = `<p>Meine Antwort</p>${SIGNATUR}<blockquote><p>Alte Mail</p></blockquote>`
    const raus = eigenesHtml(html, SIGNATUR)
    expect(raus).toBe('<p>Meine Antwort</p>')
    expect(raus).not.toContain('Alte Mail')
  })

  it('schneidet die Signatur weg, auch wenn der Editor sie umgeschrieben hat', () => {
    /* ⚠️ **Der eigentliche Fall.** Tiptap normalisiert die Auszeichnung beim
       Laden — das HTML der Signatur steht danach nie mehr wörtlich im Inhalt.
       Wer wörtlich vergleicht, findet nichts und schickt Name und Firma mit. */
    const imEditor = '<p>Hallo,</p><p>hier die Zahlen.</p><p>Viele Grüße<br />Alex Bergmann<br />Musterfirma GmbH</p>'
    const raus = eigenesHtml(imEditor, SIGNATUR)
    expect(raus).toBe('<p>Hallo,</p><p>hier die Zahlen.</p>')
    expect(raus).not.toContain('Bergmann')
  })

  it('lässt den eigenen Text vollständig stehen', () => {
    const html = `<p>Erster Absatz</p><p>Zweiter Absatz</p>${SIGNATUR}`
    const raus = eigenesHtml(html, SIGNATUR)
    expect(raus).toContain('Erster Absatz')
    expect(raus).toContain('Zweiter Absatz')
  })

  it('behält die Signatur, wenn sie von Hand umgeschrieben wurde', () => {
    /* Dann ist sie selbst geschriebener Text. Der Mensch sieht sie im
       Gegenüber, bevor er übernimmt — schlimmer wäre, den Absatz stumm
       wegzuwerfen. */
    const html = '<p>Hallo</p><p>Beste Grüße aus Hamburg, Alex</p>'
    expect(eigenesHtml(html, SIGNATUR)).toContain('Beste Grüße aus Hamburg')
  })

  it('kommt ohne Signatur zurecht', () => {
    const html = '<p>Nur Text</p>'
    expect(eigenesHtml(html, '')).toBe('<p>Nur Text</p>')
    expect(eigenesHtml(html)).toBe('<p>Nur Text</p>')
  })

  it('lässt kein angebrochenes Element stehen', () => {
    /* ⚠️ Abgeschnitten wird am Anfang des Blocks, nicht mitten im Text: Ein
       offenes ``<p>`` ohne Inhalt käme als leerer Absatz im Vorschlag an. */
    const html = `<p>Text</p>${SIGNATUR}`
    const raus = eigenesHtml(html, SIGNATUR)
    expect(raus).toBe('<p>Text</p>')
    expect(raus.match(/</g)?.length).toBe(raus.match(/>/g)?.length)
  })

  it('erkennt die Signatur auch mit anderem Weißraum', () => {
    /* Der Editor setzt Umbrüche und Einrückungen, wie er mag. Verglichen wird
       deshalb über Wörter mit `\\s+` dazwischen, nicht über Zeichen. */
    const html = '<p>Hallo</p>\n  <p>Viele   Grüße<br>\n Alex Bergmann<br>Musterfirma GmbH</p>'
    expect(eigenesHtml(html, SIGNATUR)).not.toContain('Bergmann')
  })

  it('trifft nicht versehentlich einen Satz über der Signatur', () => {
    const html = '<p>Viele Grüße gehen auch an Ihr Team.</p><p>Das war es von mir.</p>'
    /* „Viele Grüße" allein darf nicht reichen — erst die Wortfolge samt Namen
       ist die Signatur. */
    expect(eigenesHtml(html, SIGNATUR)).toContain('Das war es von mir')
  })
})
