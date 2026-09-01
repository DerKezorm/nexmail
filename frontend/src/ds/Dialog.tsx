/* Dialog — portiert aus nexapps-intern/design/components/feedback/Dialog.
 *
 * ⚠️ **Ein Fenster hat genau einen sichtbaren Ausgang.** Wer unten
 * "Abbrechen" anbietet, bekommt oben kein Kreuz mehr — sonst steht der
 * Benutzer vor zwei Knoepfen und muss raten, ob sie dasselbe tun. Escape und
 * ein Klick daneben schliessen ohnehin, die brauchen keine Schaltflaeche.
 *
 * Diese Regel steht so in beiden Design-Systemen und wurde in Nexview schon
 * einmal verletzt; hier erzwingt sie der Code statt der guten Absicht.
 */
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { IconButton } from './Button'

export interface DialogProps {
  open?: boolean
  title?: ReactNode
  /** Ein Satz, der die Folge erklaert. */
  description?: ReactNode
  children?: ReactNode
  /** Aktionen rechtsbuendig; die primaere zuletzt. */
  footer?: ReactNode
  width?: number | string
  onClose?: () => void
  closeLabel?: string
}

export function Dialog({
  open = false,
  title,
  description,
  children,
  footer,
  width = 560,
  onClose,
  closeLabel = 'Schließen',
}: DialogProps) {
  const platte = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function beiTaste(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', beiTaste)
    return () => document.removeEventListener('keydown', beiTaste)
  }, [open, onClose])

  if (!open) return null

  // Genau ein Ausgang: Das Kreuz erscheint nur, wenn unten keiner steht.
  const kreuzZeigen = !footer

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--surface-overlay)] p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.()
      }}
    >
      <div
        ref={platte}
        role="dialog"
        aria-modal="true"
        style={{ width, maxWidth: '100%' }}
        className="flex max-h-full flex-col overflow-hidden rounded-xl border border-line bg-surface-1 shadow-[var(--shadow-3)]"
      >
        {(title || kreuzZeigen) && (
          <div className="flex items-start gap-3 border-b border-line-subtle px-5 py-4">
            <div className="min-w-0 flex-1">
              {title && <h2 className="truncate font-display text-[20px] text-fg-1">{title}</h2>}
              {description && <p className="mt-1 mb-0 text-[13px] text-fg-3">{description}</p>}
            </div>
            {kreuzZeigen && <IconButton icon={<X />} label={closeLabel} size="sm" onClick={onClose} />}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-line-subtle px-5 py-3">{footer}</div>
        )}
      </div>
    </div>
  )
}
