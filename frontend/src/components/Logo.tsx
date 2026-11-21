/* Das nexmail-Zeichen: ein Umschlag mit dunklerem gruenem Rahmen.
 *
 * Quelle aller Fassungen ist nexapps/icons-vergleich/neu.py (seit 21.11.2026,
 * Vorbild nextasks). Dieselbe Form steht in public/favicon.svg,
 * tools/symbole.mjs (Home-Bildschirm) und backend/app/vorlagen/logo-rastern.mjs
 * (Systemmails). ⚠️ Wer sie hier aendert, aendert sie dort mit.
 *
 * Die Farben kommen aus styles/index.css (``--nm-logo-…``) und folgen damit
 * dem Modus der App: weisse Kachel im hellen, fast schwarze im dunklen.
 */

type LogoProps = {
  className?: string
  withWordmark?: boolean
}

export function Logo({ className = 'h-8 w-8', withWordmark = false }: LogoProps) {
  const zeichen = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexmail-mark" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" style={{ stopColor: 'var(--nm-logo-verlauf-1)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--nm-logo-verlauf-2)' }} />
          <stop offset="1" style={{ stopColor: 'var(--nm-logo-verlauf-3)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={{ fill: 'var(--nm-logo-grund)' }} />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="15.3"
        fill="none"
        strokeWidth="1.5"
        style={{ stroke: 'var(--nm-logo-rand)', strokeOpacity: 'var(--nm-logo-rand-deckung)' }}
      />
      <rect x="12" y="18" width="40" height="28" rx="5" fill="none" stroke="url(#nexmail-mark)" strokeWidth="4.2" />
      <path
        d="M15 21.5 32 34.5 49 21.5"
        fill="none"
        strokeWidth="4.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ stroke: 'var(--nm-logo-klappe)' }}
      />
    </svg>
  )

  if (!withWordmark) return zeichen

  return (
    <span className="flex items-center gap-2.5">
      {zeichen}
      {/* Auf dem Telefon nur das Zeichen — der Schriftzug wuerde die Zeile
          mit Modus- und Sprachschalter ueberfuellen. */}
      <span className="hidden font-display text-lg font-semibold tracking-tight text-fg-1 sm:inline">
        NEX<span className="text-accent-text">MAIL</span>
      </span>
    </span>
  )
}
