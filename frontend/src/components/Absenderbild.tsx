/* Der Kreis vor einem Absender: Kontaktfoto oder Logo, sonst Initialen.
 *
 * Gewünscht in der Diskussion #4. Woher das Bild kommt, entscheidet der
 * Server (`services/absenderbild.py`); hier steht nur, wie es aussieht.
 *
 * ⚠️ **Die Initialen liegen immer darunter.** Das Bild legt sich erst
 * darüber, wenn es geladen ist, und ein 404 („kein Bild") lässt sie stehen.
 * So springt die Zeile nicht, und ein fehlendes Bild sieht nicht aus wie ein
 * kaputtes.
 *
 * ⚠️ **Das Bild steht auf Weiß (`--gray-000`), auch im Dunkeln.** Favicons
 * sind für weißen Grund gezeichnet; auf dunklem verschwindet ein schwarzes
 * Logo. Gmail macht es genauso.
 */
import { useEffect, useState } from 'react'
import { initialen } from '../lib/format'
import type { Person } from '../daten/typen'

interface Props {
  person: Person
  /** Die Bildadresse. Leer heißt: nur Initialen. */
  quelle?: string
  groesse: 'klein' | 'gross'
}

export function Absenderbild({ person, quelle, groesse }: Props) {
  const [geladen, setGeladen] = useState(false)
  const [kaputt, setKaputt] = useState(false)
  useEffect(() => {
    setGeladen(false)
    setKaputt(false)
  }, [quelle])

  return (
    <span
      aria-hidden
      data-absenderbild={geladen ? 'bild' : 'initialen'}
      // Für die Tests: Nach einem 404 ist das `img` weg, die Adresse bleibt.
      data-quelle={quelle || undefined}
      className={
        'relative flex shrink-0 items-center justify-center overflow-hidden rounded-pill ' +
        'bg-surface-3 font-semibold text-fg-2 ' +
        (groesse === 'gross' ? 'size-9 text-[12px]' : 'size-8 text-[11px]')
      }
    >
      {initialen(person)}
      {quelle && !kaputt && (
        <img
          src={quelle}
          alt=""
          loading="lazy"
          decoding="async"
          onLoad={() => setGeladen(true)}
          onError={() => setKaputt(true)}
          className={
            'absolute inset-0 size-full rounded-pill bg-[var(--gray-000)] object-contain ' +
            (geladen ? '' : 'invisible')
          }
        />
      )}
    </span>
  )
}
