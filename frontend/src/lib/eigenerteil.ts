/* Wo der selbst geschriebene Teil eines Entwurfs aufhört.
 *
 * Zwei Stellen brauchen diese Antwort, und sie brauchen sie in verschiedenen
 * Formen: die Anhang-Erinnerung als schlichten Text (`lib/anhang.ts`), der
 * KI-Knopf als HTML (`components/KiFenster.tsx`). Die **Marken** dürfen
 * deshalb nur einmal dastehen — zwei Listen, die auseinanderlaufen, hiessen:
 * Die Erinnerung liest ein Zitat mit, das die KI nicht sieht, oder umgekehrt.
 *
 * ⚠️ **Ohne Browser.** Die schnelle Prüfebene läuft mit `environment: 'node'`;
 * `document.createElement` wäre dort nicht da. Dieselbe Trennung wie bei
 * `lib/lesegrund.ts`, `lib/pushlage.ts` und `lib/ziehen.ts`.
 */

/** Woran Zitat und Weiterleitung im Editor-HTML zu erkennen sind.
 *
 *  Beide baut der Server (`services/verfassen.py`): das Zitat als
 *  ``<blockquote>`` hinter seiner „Am … schrieb …"-Zeile, die Weiterleitung
 *  mit dieser Trennzeile. Der eigene Text steht immer **davor**. */
export const ZITAT_MARKEN = ['<blockquote', '---------- Weitergeleitete Nachricht ----------']

/** Wo im HTML das Zitat beginnt — oder die Länge, wenn keines da ist. */
export function zitatBeginn(html: string): number {
  let schnitt = html.length
  for (const marke of ZITAT_MARKEN) {
    const stelle = html.indexOf(marke)
    if (stelle !== -1 && stelle < schnitt) schnitt = stelle
  }
  return schnitt
}

/** Der Text ohne Auszeichnung, dazu die Stelle jedes Zeichens im HTML.
 *
 *  ⚠️ **Entitäten werden NICHT aufgelöst.** Sie bleiben als `&nbsp;` stehen,
 *  denn jedes aufgelöste Zeichen verschöbe die Karte gegen das HTML — und die
 *  Karte ist der ganze Zweck. Verglichen wird ohnehin mit einem Text, der
 *  durch dieselbe Funktion ging. */
function textMitKarte(html: string): { text: string; karte: number[] } {
  let text = ''
  const karte: number[] = []
  let imTag = false
  for (let i = 0; i < html.length; i += 1) {
    const zeichen = html[i]
    if (zeichen === '<') {
      imTag = true
      /* ⚠️ **Ein Tag ist eine Wortgrenze.** Ohne dieses Leerzeichen wird aus
         ``Grüße<br>Alex`` das Wort „GrüßeAlex" — und die Signatur ist dann nur
         noch zu finden, wenn ihre Auszeichnung zufällig genauso steht wie
         beim Einsetzen. Genau das tut sie nach dem Editor nicht mehr.
         Die Karte zeigt für das eingefügte Zeichen auf das ``<``, also auf den
         Anfang des Tags — abgeschnitten wird dort ohnehin. */
      if (text && !/\s$/.test(text)) {
        text += ' '
        karte.push(i)
      }
      continue
    }
    if (zeichen === '>') {
      imTag = false
      continue
    }
    if (imTag) continue
    text += zeichen
    karte.push(i)
  }
  return { text, karte }
}

const SONDERZEICHEN = /[.*+?^${}()|[\]\\]/g

/** Wie viele Wörter der Signatur zum Wiedererkennen genügen.
 *
 *  ⚠️ **Nicht die ganze Signatur.** Der Editor normalisiert die Auszeichnung
 *  beim Laden; wer wörtlich sucht, findet nichts. Sechs Wörter treffen eine
 *  Signatur und nicht versehentlich einen Satz darüber. */
const SIGNATUR_WOERTER = 6

/** Der selbst geschriebene Teil, als HTML.
 *
 *  Zitat und Signatur fallen weg. ⚠️ **Beides ist eine Entscheidung, keine
 *  Sparsamkeit:** Das Zitat ist fremde Post, die niemand zu einem KI-Anbieter
 *  geschickt hat; und eine umgeschriebene Signatur trägt einen Namen und eine
 *  Anschrift, die dort nichts verloren haben.
 *
 *  Findet sich die Signatur nicht wieder — weil jemand sie von Hand
 *  umgeschrieben hat —, bleibt sie stehen. Das ist dann selbst geschriebener
 *  Text, und der Mensch sieht ihn im Gegenüber vor dem Übernehmen. */
export function eigenesHtml(html: string, signaturHtml = ''): string {
  const eigen = html.slice(0, zitatBeginn(html))

  const worte = textMitKarte(signaturHtml).text.trim().split(/\s+/).filter(Boolean)
  if (worte.length === 0) return eigen.trim()

  const muster = new RegExp(
    worte
      .slice(0, SIGNATUR_WOERTER)
      .map((w) => w.replace(SONDERZEICHEN, '\\$&'))
      .join('\\s+'),
    'i',
  )
  const { text, karte } = textMitKarte(eigen)
  const treffer = muster.exec(text)
  if (!treffer) return eigen.trim()

  const imHtml = karte[treffer.index] ?? eigen.length
  /* Zurück bis zum Anfang des Blocks, in dem die Signatur steht — sonst bliebe
     ein angebrochenes ``<p>`` ohne Inhalt stehen. */
  const blockAnfang = eigen.lastIndexOf('<', imHtml)
  return eigen.slice(0, blockAnfang === -1 ? imHtml : blockAnfang).trim()
}
