/* Das Profilbild eines Kontos, sonst ein Buchstabe auf einer Farbe aus dem Namen (Kontenmodul Teil 2: in jeder App
 * und in den iPhone-Apps gleich, `avatarPlaceholder`; vorher zwei Initialen auf der Akzentfarbe).
 *
 * ⚠️ **Die Adresse trägt den Stand** (`?v=`, wann das Bild gesetzt wurde).
 * Der Server liefert es mit langem Zwischenspeichern aus; ein neues Bild ist
 * damit eine neue Adresse, und das alte kommt nicht mehr aus dem Speicher.
 */
import { useState } from 'react'
import { BASIS } from '../lib/basis'
import { avatarPlaceholder } from '../vendor/nexkonten/konten'

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
  // Helligkeit und Sättigung wählt die App (Modul); hell genug für weiße Schrift in beiden Modi.
  const { letter, hue } = avatarPlaceholder(name)
  return (
    <span
      aria-hidden
      style={{
        ...masse,
        fontSize: Math.max(10, Math.round(groesse * 0.42)),
        background: `hsl(${hue} 45% 45%)`,
      }}
      className="flex shrink-0 items-center justify-center rounded-pill font-semibold text-white"
      data-testid="profilbild-platzhalter"
    >
      {letter}
    </span>
  )
}
