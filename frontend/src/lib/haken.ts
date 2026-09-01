/* Kleine Haken, die mehrere Ansichten brauchen. */
import { useCallback, useEffect, useState } from 'react'

/** Ab hier faellt die Vier-Spalten-Ansicht auf zwei Ebenen zusammen.
 *  900 px, nicht 768: Bei 800 px waere die Nachrichtenliste noch da, aber der
 *  Lesebereich schon so schmal, dass jede zweite Zeile umbricht. */
export const SCHMAL_AB = 900

export function useSchmal(): boolean {
  const [schmal, setSchmal] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < SCHMAL_AB,
  )
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${SCHMAL_AB - 1}px)`)
    const merke = (e: MediaQueryListEvent | MediaQueryList) => setSchmal(e.matches)
    merke(mq)
    mq.addEventListener('change', merke)
    return () => mq.removeEventListener('change', merke)
  }, [])
  return schmal
}

/** Wert, der einen Neustart des Browsers ueberlebt. */
/** Wird gemeldet, wenn irgendwo ein gemerkter Wert wechselt. */
const GEMERKT_EREIGNIS = 'nexmail:gemerkt'

export function useGemerkt<T>(schluessel: string, vorgabe: T): [T, (wert: T) => void] {
  const lesen = useCallback((): T => {
    try {
      const roh = localStorage.getItem(schluessel)
      return roh === null ? vorgabe : (JSON.parse(roh) as T)
    } catch {
      // Kaputter Eintrag ist kein Grund, die App nicht zu starten.
      return vorgabe
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schluessel])

  const [wert, setWert] = useState<T>(lesen)

  /* ⚠️ **Zwei Stellen mit demselben Schlüssel müssen dasselbe sehen.**
   *
   * Vorher hielt jeder Aufruf seinen eigenen Zustand: Der Reiter
   * „Darstellung" schrieb die Dichte in den Speicher, aber `App` las sie nur
   * beim Aufbau — die Liste blieb, wie sie war. Eine Einstellung, die nichts
   * tut, ist schlimmer als keine: Der Betreiber stellt sie und sucht danach
   * den Fehler bei sich.
   *
   * `storage` allein genügt nicht — das Ereignis feuert nur in **anderen**
   * Reitern, nie im eigenen. Deshalb zusätzlich ein eigenes Ereignis.
   */
  useEffect(() => {
    function auffrischen(e: Event) {
      if (e instanceof CustomEvent && e.detail !== schluessel) return
      setWert(lesen())
    }
    window.addEventListener(GEMERKT_EREIGNIS, auffrischen)
    window.addEventListener('storage', auffrischen)
    return () => {
      window.removeEventListener(GEMERKT_EREIGNIS, auffrischen)
      window.removeEventListener('storage', auffrischen)
    }
  }, [schluessel, lesen])

  const setzen = useCallback(
    (neu: T) => {
      setWert(neu)
      try {
        localStorage.setItem(schluessel, JSON.stringify(neu))
      } catch {
        // Privater Modus, voller Speicher - beides darf nichts kaputtmachen.
      }
      window.dispatchEvent(new CustomEvent(GEMERKT_EREIGNIS, { detail: schluessel }))
    },
    [schluessel],
  )
  return [wert, setzen]
}

