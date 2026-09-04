/* Auf welchem Grund eine fremde Mail gezeigt wird.
 *
 * ⚠️ **Drei Zustände, nicht zwei.** Bis zum 04.09.2026 gab es nur „hell" und
 * „die Farben der Anwendung". Eine Mail, die eigene Farben setzt, bekam
 * zwingend ein weißes Blatt — richtig, denn halb umzufärben ist schlimmer:
 * Am 02.09.2026 gemessen stand eine Mail mit `color:#333` und ohne eigenen
 * Grund als Dunkelgrau auf Fast-Schwarz da, Kontrast 1,53:1 statt 12,63:1.
 *
 * Der Preis war eine weiße Platte mitten im dunklen Fenster, bei fast jedem
 * Newsletter. Der dritte Zustand ist der Ausweg: **umkehren statt umfärben.**
 *
 * ⚠️ **Warum Umkehren und nicht Farben ersetzen.** Wer die Farben einer
 * fremden Mail einzeln umschreibt, muss jede Regel verstehen — Verläufe,
 * Rahmen, Tabellenzellen, `!important`, Farben in Attributen. Was er übersieht,
 * wird unlesbar, und das fällt erst beim Empfänger auf. Eine Umkehr über das
 * ganze Dokument kann das nicht: Sie trifft alles gleich, und der Abstand
 * zwischen Vorder- und Hintergrund bleibt genau erhalten.
 *
 * ⚠️ **Bilder werden zurückgedreht.** Ohne das stünde jedes Logo als Negativ
 * da, und Fotos sähen aus wie Röntgenbilder.
 */

export type Lesegrund =
  /** Weißes Blatt — die Mail rechnet damit und bekommt es. */
  | 'hell'
  /** Die Farben der Anwendung. Nur für Mails, die selbst keine setzen. */
  | 'anwendung'
  /** Umgekehrt: dunkel, aber mit den Abständen der Mail. */
  | 'umgekehrt'

export interface Umstaende {
  /** Setzt die Mail selbst Farben? Entscheidet der Server beim Bereinigen. */
  faerbtSichSelbst: boolean
  /** Hat jemand für **diese eine** Mail umgeschaltet? */
  umgeschaltet: boolean
  /** Steht die Anwendung dunkel? */
  dunkelmodus: boolean
  /** Ist „fremde Mails eindunkeln" eingeschaltet? */
  eindunkeln: boolean
}

/** Der Grund für diese Mail — ohne Browser, damit er prüfbar bleibt.
 *
 * ⚠️ **Der Umschalter je Mail hat immer das letzte Wort.** Er ist der Ausweg,
 * wenn die Umkehr bei einer bestimmten Mail danebengeht — und das wird
 * vorkommen, weil niemand die Gestaltung fremder Post kennt. Ohne ihn wäre die
 * Umkehr eine Einstellung, die man erst sucht, während man etwas lesen will.
 */
export function lesegrund(u: Umstaende): Lesegrund {
  /* Eine Mail ohne eigene Farben trägt die der Anwendung — sie passt sich von
     selbst an, da gibt es nichts umzukehren. */
  if (!u.faerbtSichSelbst) return u.umgeschaltet ? 'hell' : 'anwendung'

  /* ⚠️ **Im hellen Modus wird nie umgekehrt.** Dort ist das weiße Blatt der
     Mail genau richtig, und eine Umkehr machte eine dunkle Insel daraus. */
  if (!u.dunkelmodus) return 'hell'

  if (!u.eindunkeln) return u.umgeschaltet ? 'anwendung' : 'hell'
  return u.umgeschaltet ? 'hell' : 'umgekehrt'
}
