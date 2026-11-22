/* Eine Karte der Einstellungen, wie in nexnotes (`settings/ui.tsx`, `Card`):
 * Symbol in einem kleinen Kasten, Titel, eine Zeile Erklärung, darunter der
 * Inhalt. Wer eine nex-App kennt, findet dieselbe Karte in der anderen. */
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export function Karte({
  symbol: Symbol,
  titel,
  text,
  children,
  id,
}: {
  symbol: LucideIcon
  titel: string
  text?: string
  children: ReactNode
  id?: string
}) {
  return (
    /* ⚠️ Ein `div` mit Rolle, kein `section`: Die Bereiche darin (etwa
       Google und Microsoft) sind selbst `section`s, und Tests wie Vorlesehilfen
       suchen dort die innerste. */
    <div
      id={id}
      role="region"
      aria-labelledby={id ? `${id}-titel` : undefined}
      className="rounded-xl border border-line bg-surface-1 p-5"
    >
      <div className="mb-4 flex gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
          <Symbol className="size-4" strokeWidth={1.8} aria-hidden />
        </span>
        <div className="min-w-0">
          <h2 id={id ? `${id}-titel` : undefined} className="mb-0 text-[15px] font-semibold text-fg-1">
            {titel}
          </h2>
          {text && <p className="mb-0 text-[13px] text-fg-3">{text}</p>}
        </div>
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  )
}
