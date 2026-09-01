/* Button und IconButton — portiert aus nexapps-intern/design/components/core.
 *
 * Die Eigenschaften sind wortgleich mit den .d.ts des Design-Systems
 * uebernommen; nur die Umsetzung wechselt von Inline-Stilen auf Tailwind auf
 * denselben Tokens. Wer dort etwas nachschlaegt, findet es hier wieder.
 *
 * Haltung des Systems: **genau ein `primary` je Ansicht.** Zwei Hauptaktionen
 * nebeneinander heisst, dass keine die Hauptaktion ist.
 */
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variante = 'primary' | 'secondary' | 'ghost' | 'danger'
type Groesse = 'sm' | 'md' | 'lg'

const GROESSE: Record<Groesse, string> = {
  sm: 'h-[var(--control-h-sm)] px-2.5 text-[13px] gap-1.5',
  md: 'h-[var(--control-h-md)] px-3.5 text-sm gap-2',
  lg: 'h-[var(--control-h-lg)] px-[18px] text-sm gap-2',
}

const VARIANTE: Record<Variante, string> = {
  primary:
    'bg-accent text-on-accent border-accent hover:bg-accent-hover hover:border-accent-hover active:bg-accent-press',
  secondary:
    'bg-surface-3 text-fg-1 border-line hover:bg-surface-2 hover:border-line-strong active:border-line-strong',
  ghost:
    'bg-transparent text-fg-2 border-transparent hover:bg-surface-3 hover:text-fg-1 active:bg-surface-2',
  danger:
    'bg-danger-soft text-danger border-transparent hover:bg-danger hover:text-on-accent active:bg-danger active:text-on-accent',
}

// ⚠️ **Ein gesperrter Knopf wird nicht blass, sondern grau.** Das
// Design-System blendet ihn mit 45 % Deckkraft aus; auf der gesaettigten
// Akzentflaeche eines `primary` ergibt das eine matschige Flaeche, auf der
// die Beschriftung kaum noch zu lesen ist - er sieht dann kaputt aus statt
// noch-nicht-bereit. Deshalb bekommt der gesperrte Zustand hier eine eigene,
// ruhige Flaeche. Die Abweichung ist bewusst und steht hier, damit sie
// niemand fuer ein Versehen haelt.
const RUMPF =
  'inline-flex items-center justify-center whitespace-nowrap rounded-md border font-medium ' +
  'transition-[background-color,border-color,color,box-shadow] duration-[var(--dur-fast)] ' +
  'active:translate-y-px disabled:cursor-not-allowed disabled:active:translate-y-0 ' +
  'disabled:border-line disabled:bg-surface-3 disabled:text-fg-4 disabled:shadow-none'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary = die eine Hauptaktion pro Ansicht. ghost = Werkzeugleiste. danger = zerstoerend. */
  variant?: Variante
  /** sm 28px (Tabellenzeile) · md 34px (Standard) · lg 40px (leere Zustaende, Anmeldung) */
  size?: Groesse
  iconLeft?: ReactNode
  iconRight?: ReactNode
  /** Zeigt einen Kreisel und sperrt den Knopf. */
  loading?: boolean
  fullWidth?: boolean
}

export function Button({
  variant = 'secondary',
  size = 'md',
  iconLeft,
  iconRight,
  loading = false,
  fullWidth = false,
  disabled,
  type = 'button',
  className = '',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled ?? loading}
      className={`${RUMPF} ${GROESSE[size]} ${VARIANTE[variant]} ${fullWidth ? 'w-full' : ''} ${className}`}
      {...rest}
    >
      {loading ? <Kreisel /> : iconLeft}
      {children}
      {iconRight}
    </button>
  )
}

function Kreisel() {
  return (
    <span
      aria-hidden
      className="size-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent"
    />
  )
}

const ICON_GROESSE: Record<Groesse, string> = {
  sm: 'size-7 [&_svg]:size-4',
  md: 'size-[34px] [&_svg]:size-[18px]',
  lg: 'size-10 [&_svg]:size-5',
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode
  /** Pflicht — wird als title und aria-label gesetzt. Ein Symbol ohne Namen ist ein Raetsel. */
  label: string
  variant?: 'ghost' | 'outline'
  size?: Groesse
  /** Gedrueckter Zustand (Filter an, Spalte offen). */
  active?: boolean
}

export function IconButton({
  icon,
  label,
  variant = 'ghost',
  size = 'md',
  active = false,
  className = '',
  type = 'button',
  ...rest
}: IconButtonProps) {
  const aussehen = active
    ? 'bg-accent-soft text-accent-text border-accent-line'
    : variant === 'outline'
      ? 'border-line text-fg-2 hover:bg-surface-3 hover:text-fg-1'
      : 'border-transparent text-fg-3 hover:bg-surface-3 hover:text-fg-1'

  return (
    <button
      type={type}
      title={label}
      aria-label={label}
      aria-pressed={active || undefined}
      className={
        'inline-flex shrink-0 items-center justify-center rounded-md border ' +
        'transition-[background-color,border-color,color] duration-[var(--dur-fast)] ' +
        'disabled:cursor-not-allowed disabled:opacity-45 ' +
        `${ICON_GROESSE[size]} ${aussehen} ${className}`
      }
      {...rest}
    >
      {icon}
    </button>
  )
}
