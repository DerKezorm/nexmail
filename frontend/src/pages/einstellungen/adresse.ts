/* Die Adresse der Einstellungen in der Adresszeile (Bauplan „Einstellungen"): was sie beim Laden und nach „Zurück"
 * meint, und wie sie dem gezeigten Bereich folgt. In `App` benutzt, hier für sich, damit ein Test genau diesen Weg geht.
 *
 * ⚠️ **Der Anker zählt mit.** Seit E67 ist `/settings/general#nex-apps` (und `#interfaces`) Server › Verbindungen:
 * Die Adresse wird ersetzt und behält Suche und Anker, die Karte kommt so in Sicht.
 */
import { useEffect } from 'react'

import { appPfad, ohneBasis } from '../../lib/basis'
import { bereichAusPfad, pfadVon, type Bereich } from './bereiche'

/** Was die Adresse gerade über die Einstellungen sagt (`bereichAusPfad` samt Vorbau und Anker). */
export function bereichDerAdresse(): ReturnType<typeof bereichAusPfad> {
  return bereichAusPfad(ohneBasis(window.location.pathname) ?? '', window.location.hash)
}

/**
 * ⚠️ **Jeder Bereich hat seine Adresse** (`/settings/<slug>`): Lesezeichen, Neuladen und der Zurück-Knopf des Browsers
 * führen dorthin. Ein alter Name in der Adresse wird ersetzt, nicht angehängt; Suche und Anker bleiben dabei. Wer die
 * Einstellungen verlässt, bekommt wieder die Adresse der App.
 */
export function useEinstellungsAdresse(offen: boolean, reiter: Bereich | null): void {
  useEffect(() => {
    const jetzt = ohneBasis(window.location.pathname) ?? ''
    const dort = bereichAusPfad(jetzt, window.location.hash)
    if (offen) {
      const soll = pfadVon(reiter)
      if (jetzt === soll) return
      if (dort && 'ersetzen' in dort && dort.ersetzen)
        window.history.replaceState(null, '', appPfad(soll) + window.location.search + window.location.hash)
      else window.history.pushState(null, '', appPfad(soll))
    } else if (dort) {
      window.history.pushState(null, '', appPfad('/'))
    }
  }, [offen, reiter])
}
