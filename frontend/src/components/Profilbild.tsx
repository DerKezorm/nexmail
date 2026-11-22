/* Das Profilbild eines Kontos, sonst seine Initialen.
 *
 * ⚠️ **Die Adresse trägt den Stand** (`?v=`, wann das Bild gesetzt wurde).
 * Der Server liefert es mit langem Zwischenspeichern aus; ein neues Bild ist
 * damit eine neue Adresse, und das alte kommt nicht mehr aus dem Speicher.
 */
import { useState } from 'react'
import { BASIS } from '../lib/basis'

export function profilbildAdresse(id: string, stand: string): string {
  return `${BASIS}/api/auth/profilbild/${encodeURIComponent(id)}?v=${encodeURIComponent(stand)}`
}

export function Profilbild({
  id,
  name,
  stand,
  groesse = 28,
}: {
  id: string
  name: string
  stand: string | null | undefined
  groesse?: number
}) {
  // Scheitert das Laden (gelöscht in einem anderen Reiter), stehen die Initialen da.
  const [kaputt, setKaputt] = useState<string | null>(null)
  const zeigen = stand && kaputt !== stand
  const masse = { width: groesse, height: groesse }
  if (zeigen) {
    return (
      <img
        src={profilbildAdresse(id, stand)}
        alt=""
        aria-hidden
        style={masse}
        onError={() => setKaputt(stand)}
        className="shrink-0 rounded-pill object-cover"
        data-testid="profilbild"
      />
    )
  }
  return (
    <span
      aria-hidden
      style={{ ...masse, fontSize: Math.max(10, Math.round(groesse * 0.38)) }}
      className="flex shrink-0 items-center justify-center rounded-pill bg-accent-soft font-semibold text-accent-text"
    >
      {name.slice(0, 2).toUpperCase()}
    </span>
  )
}
