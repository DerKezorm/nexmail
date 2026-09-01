/* EmptyState — portiert aus nexapps-intern/design/components/feedback.
 *
 * Regel des Systems: **genau eine Aktion**, und die loest den Zustand auf.
 * Ein leerer Zustand mit drei Vorschlaegen ist keine Hilfe, sondern eine
 * zweite Entscheidung obendrauf.
 *
 * Abweichung vom Original: dort ist `icon` ein Dateiname aus assets/icons,
 * hier ein fertiger Knoten — nexmail nimmt lucide-react, weil eine
 * Formatierleiste mehr Symbole braucht, als der Ordner mitbringt.
 */
import type { ReactNode } from 'react'

export interface EmptyStateProps {
  icon?: ReactNode
  title?: ReactNode
  description?: ReactNode
  action?: ReactNode
  /** Weniger Polster — fuer leere Spalten statt leerer Seiten. */
  compact?: boolean
}

export function EmptyState({ icon, title, description, action, compact = false }: EmptyStateProps) {
  return (
    <div
      className={
        'flex flex-col items-center justify-center text-center ' + (compact ? 'gap-2 p-6' : 'gap-3 p-12')
      }
    >
      {icon && <div className="mb-1 text-fg-4 [&_svg]:size-7">{icon}</div>}
      {title && <p className="mb-0 font-display text-[16px] text-fg-2">{title}</p>}
      {description && <p className="mb-0 max-w-[38ch] text-[13px] text-fg-4">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
