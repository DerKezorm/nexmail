/* Die Anhang-Erinnerung: Wer „im Anhang" schreibt und nichts anhängt, wird
 * vor dem Senden gefragt — einmal, im eigenen Fenster, mit Senden/Abbrechen.
 *
 * ⚠️ **Geprüft wird nur der selbst geschriebene Text.** Das Verfassen-Fenster
 * baut den Editorinhalt als „eigener Text · Signatur · Zitat" auf; Signatur
 * und Zitat werden hier vor der Prüfung abgeschnitten. Ohne das fragte jede
 * Antwort auf „die Rechnung liegt im Anhang" nach einem Anhang — dabei hat
 * ihn der **Absender** der ersten Mail erwähnt, nicht man selbst.
 */

/** Wörter, die einen Anhang ankündigen — klein geschrieben, verglichen wird
 *  ohne Rücksicht auf Groß/Klein.
 *
 *  Warum genau diese: die stehenden Wendungen deutscher und englischer
 *  Geschäftspost („im Anhang", „anbei", „please find attached", „enclosed").
 *  Beide Sprachen werden **immer** geprüft — wer die Oberfläche auf Deutsch
 *  bedient, schreibt trotzdem englische Mails. Die ae/ue-Schreibweisen stehen
 *  mit drin, weil sie auf einer Tastatur ohne Umlaute genau so getippt werden.
 */
export const ANHANG_SIGNALWOERTER: readonly string[] = [
  'im anhang',
  'angehängt',
  'angehaengt',
  'anbei',
  'beigefügt',
  'beigefuegt',
  'attached',
  'attachment',
  'enclosed',
]

/* Woran Zitat und Weiterleitung im Editor-HTML zu erkennen sind. Beide baut
 * der Server (services/verfassen.py): das Zitat als ``<blockquote>`` hinter
 * seiner „Am … schrieb …"-Zeile, die Weiterleitung mit dieser Trennzeile.
 * Der eigene Text steht immer **davor** — abgeschnitten wird ab der ersten
 * Marke, alles danach ist fremder Text. */
const ZITAT_MARKEN = ['<blockquote', '---------- Weitergeleitete Nachricht ----------']

/** HTML zu schlichtem Text: Auszeichnung raus, die üblichen Entitäten zurück,
 *  Weißraum zusammengezogen. Mehr braucht der Wortvergleich nicht. */
function alsText(html: string): string {
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\s+/g, ' ')
    .trim()
}

/** Der selbst geschriebene Teil des Editorinhalts, als schlichter Text.
 *
 *  ⚠️ **Die Signatur wird über ihren Text entfernt, nicht über ihr HTML.**
 *  Der Editor normalisiert die Auszeichnung beim Laden — das HTML der
 *  Signatur steht also nie mehr wörtlich im Inhalt, ihr Text schon. Wer die
 *  Signatur von Hand umgeschrieben hat, dessen Fassung bleibt stehen und wird
 *  mitgeprüft; das ist dann eben selbst geschriebener Text.
 */
export function eigenerText(html: string, signaturHtml: string): string {
  let schnitt = html.length
  for (const marke of ZITAT_MARKEN) {
    const stelle = html.indexOf(marke)
    if (stelle !== -1 && stelle < schnitt) schnitt = stelle
  }
  let text = alsText(html.slice(0, schnitt))

  const signatur = alsText(signaturHtml)
  if (signatur) {
    const stelle = text.toLowerCase().indexOf(signatur.toLowerCase())
    if (stelle !== -1) text = text.slice(0, stelle) + text.slice(stelle + signatur.length)
  }
  return text
}

/** Kündigt dieser Text einen Anhang an?
 *
 *  ⚠️ **Wortanfang gebunden, Wortende offen.** „die angehängte Rechnung" und
 *  „attachments" sollen treffen, also darf hinter dem Wort weitergeschrieben
 *  sein. Davor muss ein Nicht-Buchstabe stehen: „unattached" ist ausdrücklich
 *  **kein** Anhang.
 *
 *  ⚠️ **Was ein Wort ANFÄNGT, trifft dagegen — auch „anbeißen".** Hier stand
 *  bis zum 03.09.2026 das Gegenteil, und der Satz war schlicht falsch: Das
 *  offene Wortende lässt sich nicht gleichzeitig schließen. Aufgefallen ist es
 *  erst, als die schnelle Prüfebene den zugesagten Fall nachprüfte.
 *
 *  Der Tausch ist bewusst so herum: Ein zu viel gefragter Anhang kostet einen
 *  Klick, ein vergessener kostet eine zweite Mail. „anbeißen" in einer
 *  Geschäftsmail ist selten genug dafür.
 */
export function erwaehntAnhang(text: string): boolean {
  return ANHANG_SIGNALWOERTER.some((wort) => new RegExp(`(^|\\P{L})${wort}`, 'iu').test(text))
}
