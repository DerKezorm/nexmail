/* Was der Rückweg vom Anbieter in der Adresse hinterlassen hat.
 *
 * ⚠️ **Einmal beim Laden gelesen, nicht in einem Effekt.** Zwei Stellen
 * warten darauf — das Fenster „Postfach hinzufügen" und die Zustimmungsliste
 * unter Sicherheit. Wer zuerst liest, räumt die Adresse ab, und der zweite
 * fände nichts mehr. Ein Modulwert wird beim Import gesetzt, also vor der
 * ersten Zeichnung, und beide sehen dasselbe.
 *
 * ⚠️ **Die Adresse wird sofort bereinigt.** Sonst käme die Meldung bei jedem
 * F5 wieder, und ein Zugang würde zweimal weiterverarbeitet.
 */

function lesen() {
  const frage = new URLSearchParams(window.location.search)
  const stand = frage.get('oauth') ?? ''
  const weiter = frage.get('weiter') ?? ''
  const zugang = frage.get('zugang') ?? ''

  if (stand) {
    for (const feld of ['oauth', 'weiter', 'zugang']) frage.delete(feld)
    const rest = frage.toString()
    // Der Pfad bleibt, wie er ist — er trägt den Vorbau schon.
    window.history.replaceState({}, '', window.location.pathname + (rest ? `?${rest}` : ''))
  }
  return { stand, weiter, zugang }
}

export const RUECKWEG = lesen()
