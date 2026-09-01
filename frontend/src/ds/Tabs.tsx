/* Tabs — portiert aus nexapps-intern/design/components/navigation/Tabs.
 *
 * underline = Seitenebene (die Reiter der Einstellungen).
 * segment   = Filter innerhalb einer Karte (der Suchbereich).
 */
import type { ReactNode } from 'react'

export interface TabDef {
  id: string
  label: string
  icon?: ReactNode
  count?: number
}

export interface TabsProps {
  tabs: TabDef[]
  activeId?: string
  onSelect?: (id: string) => void
  variant?: 'underline' | 'segment'
}

export function Tabs({ tabs, activeId, onSelect, variant = 'underline' }: TabsProps) {
  if (variant === 'segment') {
    return (
      <div role="tablist" className="inline-flex gap-0.5 rounded-md border border-line bg-surface-2 p-0.5">
        {tabs.map((t) => {
          const an = t.id === activeId
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={an}
              onClick={() => onSelect?.(t.id)}
              className={
                'inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-[13px] font-medium ' +
                'transition-colors duration-[var(--dur-fast)] ' +
                (an ? 'bg-surface-1 text-fg-1 shadow-[var(--shadow-1)]' : 'text-fg-3 hover:text-fg-1')
              }
            >
              {t.icon}
              {t.label}
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div role="tablist" className="flex gap-1 border-b border-line-subtle">
      {tabs.map((t) => {
        const an = t.id === activeId
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={an}
            onClick={() => onSelect?.(t.id)}
            className={
              'inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium ' +
              'transition-colors duration-[var(--dur-fast)] ' +
              (an
                ? 'border-accent text-fg-1'
                : 'border-transparent text-fg-3 hover:border-line-strong hover:text-fg-1')
            }
          >
            {t.icon}
            {t.label}
            {typeof t.count === 'number' && (
              <span className="rounded-pill bg-neutral-soft px-1.5 text-[11px] tabular-nums text-fg-3">
                {t.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
