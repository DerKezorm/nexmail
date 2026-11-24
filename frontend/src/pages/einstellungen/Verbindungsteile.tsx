/* Die Bausteine im Inneren der Karten unter „Verbindungen" (nextime, nextasks).
 *
 * ⚠️ **Aufbau wie in nextime › Verbindungen** (gemeldet am 24.11.2026: „wir
 * wollten doch einheitlich bleiben"): oben eine Statuszeile (Punkt, „verbunden",
 * Adresse · was die Verbindung tut), darunter Abschnitte mit einer Überschrift in
 * Großbuchstaben, ganz unten die Knöpfe nebeneinander („Schlüssel ändern",
 * „Trennen"); in einem Formular steht der Hauptknopf rechts.
 */
import type { ReactNode } from 'react'

/** Ein Punkt, ein Wort und die Adresse: verbunden, gestört oder nicht verbunden. */
export function Lage({
  art,
  text,
  adresse,
  zusatz,
}: {
  art: 'ok' | 'warn' | 'aus'
  text: string
  adresse?: string
  /** Was die Verbindung tut, hinter der Adresse („· zeigt …"). */
  zusatz?: string
}) {
  const punkt = art === 'ok' ? 'bg-success' : art === 'warn' ? 'bg-warning' : 'bg-fg-4'
  const farbe = art === 'ok' ? 'text-success' : art === 'warn' ? 'text-warning' : 'text-fg-4'
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
      <span aria-hidden className={`size-2 shrink-0 rounded-full ${punkt}`} />
      <span className={`font-medium ${farbe}`}>{text}</span>
      {/* `data-adresse`: Ein Rechnername ist kein Übersetzungsschlüssel (Wächter in tests/hilfen.ts). */}
      {adresse && (
        <span data-adresse className="text-fg-2">
          {adresse}
        </span>
      )}
      {adresse && zusatz && <span className="text-fg-3">· {zusatz}</span>}
    </span>
  )
}

/** Ein Abschnitt mit Überschrift in Großbuchstaben und einem Satz darunter. */
export function Abschnitt({
  titel,
  hinweis,
  children,
}: {
  titel: string
  hinweis?: string
  children: ReactNode
}) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
      <legend className="mb-1 p-0 text-[12px] font-semibold tracking-wide text-fg-3 uppercase">{titel}</legend>
      {hinweis && <p className="mb-1 text-[12px] leading-relaxed text-fg-4">{hinweis}</p>}
      {children}
    </fieldset>
  )
}

/** Die Knöpfe unten in der Karte, nebeneinander. */
export function Knopfreihe({ children, rechts = false }: { children: ReactNode; rechts?: boolean }) {
  return <div className={`flex flex-wrap gap-2 ${rechts ? 'justify-end' : ''}`}>{children}</div>
}
