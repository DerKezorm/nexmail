/* Die Lage eines Browsers — die Entscheidung, nicht die Browser-Anbindung.
 *
 * ⚠️ **Hier stand ein Fehler, der aus dem Betrieb gemeldet wurde.** Am
 * 03.09.2026 auf einem iPhone: „Erlaubt auf diesem Gerät", obwohl der Server
 * kein Gerät kannte. Die Erlaubnis lebt im Browser und überlebt alles; die
 * Anmeldung lebt im Server und ist nach einem Umzug, einem gelöschten
 * Browserzustand oder einer frischen Installation weg. Wer aus dem einen auf
 * das andere schließt, zeigt einen Probeknopf, der mit 400 antwortet.
 *
 * ⚠️ **Deshalb ist die Entscheidung eine reine Funktion in einem eigenen
 * Modul.** `push.ts` zieht ueber `lib/basis` das Dokument herein und laesst
 * sich in `environment: 'node'` gar nicht erst importieren. Ein Test dafür
 * braucht keinen Browser und läuft in Millisekunden — die Anbindung daneben
 * (`navigator`, `PushManager`) prüft weiterhin nur der echte Browser.
 */
import { describe, expect, it } from 'vitest'
import { lageAus } from './pushlage'
import type { Umstaende } from './pushlage'

/** Ein Rechner, auf dem alles stimmt. Jeder Test dreht genau eine Sache um. */
const GUT: Umstaende = {
  kannPush: true,
  istApple: false,
  alsApp: false,
  erlaubnis: 'granted',
  angemeldet: true,
}

const mit = (teil: Partial<Umstaende>): Umstaende => ({ ...GUT, ...teil })

describe('lageAus', () => {
  it('meldet bereit, wenn Erlaubnis UND Anmeldung stehen', () => {
    expect(lageAus(GUT)).toBe('bereit')
  })

  it('meldet NICHT bereit, wenn die Erlaubnis steht und die Anmeldung fehlt', () => {
    // Genau der gemeldete Fehler.
    expect(lageAus(mit({ angemeldet: false }))).toBe('erlaubt_ohne_anmeldung')
  })

  it('meldet offen, solange der Browser nicht gefragt wurde', () => {
    expect(lageAus(mit({ erlaubnis: 'default', angemeldet: false }))).toBe('offen')
  })

  it('meldet abgelehnt, wenn der Browser Nein gesagt hat', () => {
    expect(lageAus(mit({ erlaubnis: 'denied', angemeldet: false }))).toBe('abgelehnt')
  })

  it('meldet unmoeglich, wenn dem Browser die Schnittstellen fehlen', () => {
    expect(lageAus(mit({ kannPush: false }))).toBe('unmoeglich')
  })

  it('unmoeglich schlaegt alles andere, auch den Home-Bildschirm', () => {
    /* ⚠️ **Der Fall, den die erste Fassung dieses Tests verfehlt hat.** Sie
       prüfte `kannPush: false` auf einem Nicht-Apple-Gerät — dort kollidieren
       die beiden Gründe gar nicht, und ein Vertauschen der Reihenfolge lief
       durch die Mutationsprobe.

       Der erreichbare Grenzfall ist ein iPhone mit zu altem iOS in einem
       gewöhnlichen Reiter: Beide Gründe treffen zu. „Leg es auf den
       Home-Bildschirm" schickt dort jemanden auf eine Fährte, die nie
       ankommt, denn das Gerät kann Push überhaupt nicht. */
    expect(
      lageAus(mit({ kannPush: false, istApple: true, alsApp: false, erlaubnis: 'granted' })),
    ).toBe('unmoeglich')
  })

  it('verlangt auf Apple den Home-Bildschirm, auch bei erteilter Erlaubnis', () => {
    // ⚠️ iOS liefert an einen gewoehnlichen Reiter nichts aus, auch wenn die
    // Erlaubnis dort steht. „Bereit" waere dort eine Falschaussage.
    expect(lageAus(mit({ istApple: true, alsApp: false }))).toBe('kein_home')
  })

  it('ist auf Apple vom Home-Bildschirm aus ganz normal', () => {
    expect(lageAus(mit({ istApple: true, alsApp: true }))).toBe('bereit')
  })

  it('verlangt den Home-Bildschirm NUR auf Apple', () => {
    // Ein Android-Browser in einem gewoehnlichen Reiter kann sehr wohl Push.
    expect(lageAus(mit({ istApple: false, alsApp: false }))).toBe('bereit')
  })
})
