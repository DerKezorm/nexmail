/* Ein Empfängerfeld mit Vorschlägen aus dem Adressbuch.
 *
 * ⚠️ **Vorgeschlagen wird auf das letzte Bruchstück**, nicht auf den ganzen
 * Feldinhalt. „anna@x.de, ma" soll „ma" vervollständigen und „anna@x.de"
 * stehen lassen — wer den ganzen Inhalt als Suchbegriff nimmt, findet ab dem
 * zweiten Empfänger nie wieder etwas.
 *
 * ⚠️ **Die Tastatur muss reichen.** Wer Adressen tippt, hat die Hand nicht an
 * der Maus: Pfeile wählen, Eingabe und Tab übernehmen, Esc schließt. Ein
 * Vorschlagskasten, den man nur klicken kann, ist im Weg statt eine Hilfe.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Kontakt } from '../pages/KontaktePage'

interface Props {
  wert: string
  aufAendern: (s: string) => void
  platzhalter?: string
  autoFocus?: boolean
}

/** Das Stück hinter dem letzten Trenner — nur das wird vervollständigt. */
function bruchstueck(wert: string): string {
  const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
  return wert.slice(trenner + 1).trim()
}

function einsetzen(wert: string, adresse: string): string {
  const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
  const vorher = trenner === -1 ? '' : wert.slice(0, trenner + 1) + ' '
  return `${vorher}${adresse}, `
}

export function Adressfeld({ wert, aufAendern, platzhalter, autoFocus }: Props) {
  const [vorschlaege, setVorschlaege] = useState<Kontakt[]>([])
  const [offen, setOffen] = useState(false)
  const [aktiv, setAktiv] = useState(0)
  const uhr = useRef<number | undefined>(undefined)
  // Für welches Bruchstück die laufende Abfrage gestartet wurde. Ältere
  // Antworten werden verworfen, sonst überholt eine langsame die schnelle.
  const laeuftFuer = useRef('')

  useEffect(() => {
    window.clearTimeout(uhr.current)
    const kern = bruchstueck(wert)
    if (kern.length < 2) {
      setVorschlaege([])
      setOffen(false)
      return
    }
    uhr.current = window.setTimeout(() => {
      laeuftFuer.current = kern
      api
        .holen<Kontakt[]>(`/api/kontakte/vorschlag?anfang=${encodeURIComponent(kern)}`)
        .then((gefunden) => {
          if (laeuftFuer.current !== kern) return
          setVorschlaege(gefunden)
          setAktiv(0)
          setOffen(gefunden.length > 0)
        })
        .catch(() => {
          // Ein Adressbuch, das gerade nicht antwortet, darf das Tippen nicht
          // stören. Dann gibt es eben keine Vorschläge.
          if (laeuftFuer.current === kern) setOffen(false)
        })
    }, 180)
    return () => window.clearTimeout(uhr.current)
  }, [wert])

  function uebernehmen(k: Kontakt) {
    aufAendern(einsetzen(wert, k.adresse))
    setOffen(false)
    setVorschlaege([])
  }

  return (
    <div className="relative min-w-0 flex-1">
      <input
        value={wert}
        autoFocus={autoFocus}
        autoComplete="off"
        onChange={(e) => aufAendern(e.target.value)}
        onBlur={() => {
          // Erst nach dem Klick schließen - sonst verschwindet der Kasten,
          // bevor der Klick darauf ankommt.
          window.setTimeout(() => setOffen(false), 120)
        }}
        onKeyDown={(e) => {
          if (!offen || vorschlaege.length === 0) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setAktiv((a) => (a + 1) % vorschlaege.length)
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setAktiv((a) => (a - 1 + vorschlaege.length) % vorschlaege.length)
          } else if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault()
            uebernehmen(vorschlaege[aktiv])
          } else if (e.key === 'Escape') {
            // ⚠️ Nur den Kasten schließen, nicht das Fenster. Sonst kostet ein
            // Esc gegen einen Vorschlag die ganze angefangene Mail.
            e.stopPropagation()
            setOffen(false)
          }
        }}
        placeholder={platzhalter}
        className="min-w-0 flex-1 bg-transparent text-sm text-fg-1 outline-none placeholder:text-fg-4"
      />

      {offen && (
        <ul className="absolute top-full left-0 z-10 mt-1 max-h-56 w-[320px] overflow-y-auto rounded-md border border-line bg-surface-1 py-1 shadow-[var(--shadow-2)]">
          {vorschlaege.map((k, i) => (
            <li key={k.id}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => uebernehmen(k)}
                onMouseEnter={() => setAktiv(i)}
                className={
                  'flex w-full flex-col items-start px-3 py-1.5 text-left ' +
                  (i === aktiv ? 'bg-accent-soft' : 'hover:bg-surface-2')
                }
              >
                {k.name && <span className="text-[13px] text-fg-1">{k.name}</span>}
                <span className="text-[12px] text-fg-3">{k.adresse}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
