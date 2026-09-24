/* Was ein Klick auf einen Link in einer fremden Mail tut.
 *
 * ⚠️ **Bis 0.18.1 tat er nichts** (Issue #5). Der Rahmen im Lesebereich durfte
 * keine neuen Fenster öffnen; ein Link mit `target="_blank"` wurde deshalb
 * stumm verworfen, einer ohne `target` sollte im Rahmen selbst aufgehen und
 * scheiterte an der Inhaltsregel (`frame-src` ist `'self'`). Statt der Mail
 * stand eine Fehlerseite da. Nur Rechtsklick und „In neuem Tab öffnen" kam
 * durch. Am 24.09.2026 im echten Chromium nachgestellt, mit derselben
 * Abschottung und derselben Regel wie nexmail.
 *
 * Dabei zwei Fälle, die niemand gemeldet hatte und die genauso kaputt waren:
 * `mailto:` ersetzte die Mail ebenfalls durch eine Fehlerseite, und eine
 * Sprungmarke (`#abschnitt`, das Inhaltsverzeichnis eines Newsletters) lud
 * nexmail selbst in den Rahmen, weil ein `srcdoc` Adressen gegen das
 * Elterndokument auflöst.
 *
 * ⚠️ **Ohne Browser, und der Grund ist der Testlauf**, dasselbe Muster wie
 * `lib/leserahmen.ts`. Die Verdrahtung am Rahmen steht im Lesebereich.
 */

/** Wohin ein Link führt, und damit, wer sich um ihn kümmert. */
export type Linkart =
  /** Eine Seite draußen: neuer Reiter, ohne Opener und ohne Referrer. */
  | 'extern'
  /** Eine Adresse: nexmails eigenes Verfassen-Fenster. */
  | 'mail'
  /** Eine Stelle in derselben Mail: dorthin scrollen. */
  | 'anker'
  /** Alles andere. Eine relative Adresse zeigte auf nexmail selbst. */
  | 'tot'

export function linkart(href: string | null | undefined): Linkart {
  const h = (href ?? '').trim()
  if (h.startsWith('#')) return 'anker'
  if (/^mailto:/i.test(h)) return 'mail'
  /* ⚠️ **`tel:` geht wie eine Seite hinaus.** Der Browser reicht es an das
     Telefon oder das Programm, das der Rechner dafür hat; nexmail hat dafür
     nichts Eigenes. */
  if (/^(https?|tel):/i.test(h)) return 'extern'
  return 'tot'
}

/** Die Stelle, auf die eine Sprungmarke zeigt, ohne das `#`. */
export function ankername(href: string): string {
  return entschluesseln(href.trim().slice(1))
}

/** Was ein `mailto:`-Link im Verfassen-Fenster vorbelegt. */
export interface Vorbelegung {
  an: string[]
  kopie: string[]
  blindkopie: string[]
  betreff: string
  /** Nackter Text, wie er im Link stand. HTML wird daraus erst im Fenster. */
  text: string
}

/** Einen `mailto:`-Link lesen (RFC 6068).
 *
 * ⚠️ **`+` ist hier kein Leerzeichen.** Anders als in einem Formular steht es
 * in `mailto:` für sich selbst: `name+etikett@example.com` ist eine
 * gewöhnliche Adresse, und wer es umschreibt, schickt an jemand anderen.
 *
 * ⚠️ **Nur fünf Felder, der Rest fällt weg.** Die Norm erlaubt beliebige
 * Kopfzeilen im Link, darunter `In-Reply-To`. Eine fremde Mail soll nicht
 * bestimmen, in welchen Strang die eigene Antwort einsortiert wird.
 */
export function mailtoLesen(href: string): Vorbelegung | null {
  const h = href.trim()
  if (!/^mailto:/i.test(h)) return null
  const rest = h.slice('mailto:'.length)
  const frage = rest.indexOf('?')
  const vorne = frage < 0 ? rest : rest.slice(0, frage)
  const hinten = frage < 0 ? '' : rest.slice(frage + 1)

  const v: Vorbelegung = { an: adressen(vorne), kopie: [], blindkopie: [], betreff: '', text: '' }
  let betreffGesetzt = false
  let textGesetzt = false
  for (const teil of hinten.split('&')) {
    if (!teil) continue
    const gleich = teil.indexOf('=')
    const name = entschluesseln(gleich < 0 ? teil : teil.slice(0, gleich)).toLowerCase()
    const wert = gleich < 0 ? '' : teil.slice(gleich + 1)
    if (name === 'to') v.an.push(...adressen(wert))
    else if (name === 'cc') v.kopie.push(...adressen(wert))
    else if (name === 'bcc') v.blindkopie.push(...adressen(wert))
    // ⚠️ Das erste gilt. Zwei Betreffzeilen ergeben keinen Sinn, und eine
    // zweite, die die erste still überschreibt, sieht man im Link nicht.
    else if (name === 'subject' && !betreffGesetzt) {
      v.betreff = entschluesseln(wert)
      betreffGesetzt = true
    } else if (name === 'body' && !textGesetzt) {
      v.text = entschluesseln(wert)
      textGesetzt = true
    }
  }
  return v
}

/** Nackten Text aus einem Link als Absätze für den Editor. */
export function textAlsHtml(text: string): string {
  if (!text) return ''
  return text
    .split(/\r\n|\r|\n/)
    .map((zeile) => `<p>${maskieren(zeile)}</p>`)
    .join('')
}

function adressen(roh: string): string[] {
  return entschluesseln(roh)
    .split(',')
    .map((a) => a.trim())
    .filter(Boolean)
}

/** Prozentkodierung auflösen. ⚠️ **Ein kaputtes `%` wirft nicht.** Der Link
 *  kommt aus einer fremden Mail; er soll dann so dastehen, wie er kam, statt
 *  den Klick in eine Ausnahme laufen zu lassen, die niemand sieht. */
function entschluesseln(s: string): string {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

function maskieren(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
