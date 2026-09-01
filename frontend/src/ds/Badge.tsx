/* Badge — portiert aus nexapps-intern/design/components/core/Badge.
 *
 * Regel des Systems: **Der Farbton ist Bedeutung, nicht Schmuck.** Wer ein
 * Abzeichen einfaerbt, weil es huebscher aussieht, nimmt der Farbe die Aussage.
 */
import type { HTMLAttributes } from 'react'

type Ton = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'

const TON: Record<Ton, string> = {
  neutral: 'bg-neutral-soft text-fg-3',
  accent: 'bg-accent-soft text-accent-text',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
  info: 'bg-info-soft text-info',
}

const PUNKT: Record<Ton, string> = {
  neutral: 'bg-fg-4',
  accent: 'bg-accent',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Ton
  /** Statuspunkt vor der Beschriftung — fuer Live- und Laufzustaende. */
  dot?: boolean
  /** Feste Laufweite fuer Versionen, Kennungen, Zahlen. */
  mono?: boolean
}

export function Badge({ tone = 'neutral', dot = false, mono = false, className = '', children, ...rest }: BadgeProps) {
  return (
    <span
      className={
        'inline-flex items-center gap-1.5 rounded-pill px-2 py-0.5 text-[11px] font-medium leading-5 ' +
        `${TON[tone]} ${mono ? 'font-mono tabular-nums' : ''} ${className}`
      }
      {...rest}
    >
      {dot && <span aria-hidden className={`size-1.5 rounded-full ${PUNKT[tone]}`} />}
      {children}
    </span>
  )
}
