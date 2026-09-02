/* Eingabefelder — portiert aus nexapps-intern/design/components/forms.
 *
 * Input, Select und Switch mit den Eigenschaften ihrer .d.ts. Alle drei
 * teilen sich Hoehe, Rahmen und Fokusring, damit eine Formularzeile nicht
 * aus drei verschiedenen Welten besteht.
 */
import { useId } from 'react'
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'

type Groesse = 'sm' | 'md' | 'lg'

const HOEHE: Record<Groesse, string> = {
  sm: 'h-[var(--control-h-sm)]',
  md: 'h-[var(--control-h-md)]',
  lg: 'h-[var(--control-h-lg)]',
}

const BESCHRIFTUNG = 'text-[12px] font-semibold uppercase tracking-[0.06em] text-fg-3'

/** Der Rahmen um Eingabefelder. Fokus faerbt ihn, ein Fehler uebersteuert ihn. */
function huelle(fehler: boolean) {
  return (
    'fokusrahmen flex items-center gap-2 rounded-sm border bg-surface-3 px-2.5 ' +
    'transition-[border-color,box-shadow] duration-[var(--dur-fast)] ' +
    'focus-within:shadow-[var(--focus-ring)] ' +
    (fehler ? 'border-danger focus-within:border-danger' : 'border-line focus-within:border-accent')
  )
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: string
  /** Hilfetext unter dem Feld. */
  hint?: ReactNode
  /** Fehlertext — ersetzt hint und faerbt den Rahmen. */
  error?: string
  size?: Groesse
  iconLeft?: ReactNode
  /** Einheit oder Kuerzel rechts im Feld, z. B. "Port". */
  suffix?: string
  /** Feste Laufweite fuer Adressen, Kennungen, Pfade. */
  mono?: boolean
}

export function Input({
  label,
  hint,
  error,
  size = 'md',
  iconLeft,
  suffix,
  mono = false,
  className = '',
  ...rest
}: InputProps) {
  const kaputt = Boolean(error)
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      {label && <span className={BESCHRIFTUNG}>{label}</span>}
      <span className={`${huelle(kaputt)} ${HOEHE[size]} ${rest.disabled ? 'opacity-55' : ''}`}>
        {iconLeft && <span className="shrink-0 text-fg-4">{iconLeft}</span>}
        <input
          className={
            'min-w-0 flex-1 bg-transparent text-fg-1 outline-none placeholder:text-fg-4 ' +
            `${mono ? 'font-mono' : ''} ${size === 'sm' ? 'text-[13px]' : 'text-sm'} ${className}`
          }
          {...rest}
        />
        {suffix && <span className="shrink-0 font-mono text-[11px] text-fg-4">{suffix}</span>}
      </span>
      {(hint || error) && (
        <span className={`text-[12px] ${kaputt ? 'text-danger' : 'text-fg-4'}`}>{error || hint}</span>
      )}
    </label>
  )
}

export interface SelectOption {
  value: string
  label: string
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  label?: string
  hint?: ReactNode
  size?: Groesse
  options?: Array<string | SelectOption>
}

export function Select({ label, hint, size = 'md', options = [], className = '', children, ...rest }: SelectProps) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      {label && <span className={BESCHRIFTUNG}>{label}</span>}
      {/* ⚠️ **Der Pfeil muss zum Klickziel gehoeren.** Er ist ein Geschwister
          des <select>; ohne pointer-events-none faengt er den Klick ab und
          nichts klappt auf - an jeder Auswahl der Anwendung, denn alle
          nutzen diesen Baustein. Am 02.09.2026 aufgefallen. Das select
          liegt deshalb ueber die volle Breite, der Pfeil schwebt darueber
          und laesst Klicks durch. */}
      <span className={`relative ${huelle(false)} ${HOEHE[size]}`}>
        <select
          className={`min-w-0 flex-1 appearance-none bg-transparent pr-6 text-sm text-fg-1 outline-none ${className}`}
          {...rest}
        >
          {options.map((o) => {
            const wert = typeof o === 'string' ? o : o.value
            const text = typeof o === 'string' ? o : o.label
            return (
              <option key={wert} value={wert} className="bg-surface-1 text-fg-1">
                {text}
              </option>
            )
          })}
          {children}
        </select>
        <ChevronAbwaerts />
      </span>
      {hint && <span className="text-[12px] text-fg-4">{hint}</span>}
    </label>
  )
}

function ChevronAbwaerts() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="pointer-events-none absolute top-1/2 right-2.5 size-4 shrink-0 -translate-y-1/2 text-fg-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

export interface SwitchProps {
  label?: string
  description?: string
  checked?: boolean
  disabled?: boolean
  onCheckedChange?: (checked: boolean) => void
}

export function Switch({ label, description, checked = false, onCheckedChange, disabled }: SwitchProps) {
  const id = useId()
  const beschriftung = `${id}-text`
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        id={id}
        role="switch"
        aria-checked={checked}
        /* ⚠️ **`<label for>` benennt keinen Knopf.** Es wirkt nur auf
           Formularfelder (input, select, textarea) — ein `<button>` bleibt
           damit fuer Vorleseprogramme stumm. Der Schalter sah richtig
           ausgezeichnet aus und war es nicht, und zwar an **jeder** Stelle,
           an der er benutzt wird: Darstellung, OIDC, Regeln, Signaturen,
           Ueber. Gefunden am 01.09.2026 von `jederKnopfHatEinenNamen`. */
        aria-labelledby={label ? beschriftung : undefined}
        aria-label={label ? undefined : description}
        disabled={disabled}
        onClick={() => onCheckedChange?.(!checked)}
        className={
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-pill border transition-colors duration-[var(--dur-fast)] ' +
          'disabled:cursor-not-allowed disabled:opacity-45 ' +
          (checked ? 'border-accent bg-accent' : 'border-line bg-surface-3')
        }
      >
        <span
          aria-hidden
          className={
            'absolute top-1/2 size-3.5 -translate-y-1/2 rounded-full transition-[left] duration-[var(--dur-fast)] ' +
            (checked ? 'left-[18px] bg-[var(--text-on-accent)]' : 'left-[3px] bg-fg-3')
          }
        />
      </button>
      {(label || description) && (
        <label htmlFor={id} className="min-w-0 cursor-pointer select-none">
          {label && (
            <span id={beschriftung} className="block text-sm text-fg-1">
              {label}
            </span>
          )}
          {description && <span className="block text-[12px] text-fg-4">{description}</span>}
        </label>
      )}
    </div>
  )
}

export interface CheckboxProps {
  label?: string
  /** Zweite Zeile in fg-4, fuer Konsequenzen der Option. */
  description?: string
  checked?: boolean
  disabled?: boolean
  onCheckedChange?: (checked: boolean) => void
}

/* Checkbox — portiert aus nexapps-intern/design/components/forms/Checkbox.
 *
 * Anders als beim Switch steckt hier ein echtes `<input type="checkbox">`
 * im `<label>`: Ein Formularfeld bekommt seinen Namen vom umschliessenden
 * Label von selbst — die `<label for>`-Falle des Switch gibt es hier nicht.
 * (`indeterminate` aus der Vorlage ist weggelassen: kein Aufrufer braucht es,
 * und ein Zustand ohne Benutzer ist toter Code.)
 */
export function Checkbox({ label, description, checked = false, disabled, onCheckedChange }: CheckboxProps) {
  return (
    <label
      className={
        'inline-flex gap-2.5 select-none ' +
        (description ? 'items-start ' : 'items-center ') +
        (disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer')
      }
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onCheckedChange?.(e.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className={
          'grid size-4 shrink-0 place-items-center rounded-xs border transition-colors duration-[var(--dur-fast)] ' +
          'peer-focus-visible:shadow-[var(--focus-ring)] ' +
          (description ? 'mt-0.5 ' : '') +
          (checked ? 'border-accent bg-accent' : 'border-line-strong bg-surface-3')
        }
      >
        {checked && (
          <svg viewBox="0 0 24 24" className="size-3 text-[var(--text-on-accent)]" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <path d="m5 13 4 4L19 7" />
          </svg>
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        {label && <span className="truncate text-[13px] text-fg-1">{label}</span>}
        {description && <span className="text-[12px] text-fg-4">{description}</span>}
      </span>
    </label>
  )
}
