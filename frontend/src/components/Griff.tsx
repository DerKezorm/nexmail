/* Der Griff zwischen zwei Spalten.
 *
 * Zieht man daran, aendert sich die Breite links davon. Der Wert wird
 * gemerkt - eine Spaltenaufteilung, die man bei jedem Start neu einstellt,
 * stellt man nach dem dritten Mal nicht mehr ein.
 *
 * Bedienbar ist er auch mit der Tastatur: Pfeiltasten schieben in 16er
 * Schritten. Ein Griff, den man nur mit der Maus trifft, ist fuer alle
 * unerreichbar, die keine fuehren.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface Props {
  breite: number
  aufBreite: (b: number) => void
  min: number
  max: number
  label: string
}

export function Griff({ breite, aufBreite, min, max, label }: Props) {
  const [zieht, setZieht] = useState(false)
  const start = useRef({ x: 0, breite: 0 })

  const begrenzen = useCallback((b: number) => Math.min(max, Math.max(min, b)), [min, max])

  useEffect(() => {
    if (!zieht) return

    function beiBewegung(e: PointerEvent) {
      aufBreite(begrenzen(start.current.breite + (e.clientX - start.current.x)))
    }
    function beiLoslassen() {
      setZieht(false)
    }

    document.body.dataset.zieht = 'true'
    window.addEventListener('pointermove', beiBewegung)
    window.addEventListener('pointerup', beiLoslassen)
    return () => {
      delete document.body.dataset.zieht
      window.removeEventListener('pointermove', beiBewegung)
      window.removeEventListener('pointerup', beiLoslassen)
    }
  }, [zieht, aufBreite, begrenzen])

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={breite}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      data-aktiv={zieht}
      className="griff"
      onPointerDown={(e) => {
        start.current = { x: e.clientX, breite }
        setZieht(true)
      }}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') {
          e.preventDefault()
          aufBreite(begrenzen(breite - 16))
        }
        if (e.key === 'ArrowRight') {
          e.preventDefault()
          aufBreite(begrenzen(breite + 16))
        }
      }}
    />
  )
}
