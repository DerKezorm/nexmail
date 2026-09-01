/* Das nexmail-Zeichen.
 *
 * Gebaut nach demselben Muster wie Nexviews Logo
 * (nexview/frontend/src/components/Logo.tsx): abgerundetes Quadrat, Kontur im
 * Farbverlauf, ein einziges gefuelltes Element darin, und daneben die
 * Wortmarke aus zwei Haelften - die erste neutral, die zweite im Akzent.
 *
 * Zwei Unterschiede, beide gewollt:
 *
 *   Rot wird Gruen. Nexview ist die Kino-App, nexmail gehoert zur
 *   Werkstatt - und nexmail bleibt beim nex-Gruen des nexapps-Systems,
 *   statt sich eine eigene Marke zu nehmen.
 *
 *   Aus der Blende mit Play-Dreieck wird ein Briefumschlag. Die gefuellte
 *   Klappe uebernimmt dabei die Rolle, die drueben das Dreieck hat: genau
 *   ein volles Element, damit das Zeichen auch bei 20 px noch etwas ist und
 *   nicht nur ein Gitter aus Strichen.
 *
 * Die Farbwerte stehen hier ausgeschrieben und nicht als Token. Ein Logo ist
 * eine Marke, kein Oberflaechenelement: Es sieht im hellen wie im dunklen
 * Modus gleich aus, sonst waere es zwei Logos.
 */

type LogoProps = {
  className?: string
  withWordmark?: boolean
}

export function Logo({ className = 'h-8 w-8', withWordmark = false }: LogoProps) {
  const zeichen = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexmail-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#5fe4bb" />
          <stop offset="55%" stopColor="#23d19e" />
          <stop offset="100%" stopColor="#02543e" />
        </linearGradient>
      </defs>

      {/* Die Platte. Ein eigener, sehr dunkler Gruenton statt einer
          Token-Flaeche: Das Zeichen muss auch auf hellem Grund stehen. */}
      <rect x="2" y="2" width="60" height="60" rx="16" fill="#0d1614" />
      <rect
        x="2"
        y="2"
        width="60"
        height="60"
        rx="16"
        fill="none"
        stroke="url(#nexmail-mark)"
        strokeWidth="2.5"
        strokeOpacity=".55"
      />

      {/* Der Umschlag. */}
      <rect
        x="13"
        y="20"
        width="38"
        height="24"
        rx="4"
        fill="none"
        stroke="url(#nexmail-mark)"
        strokeWidth="3.2"
        strokeLinejoin="round"
      />
      <path d="M14.6 21.8 32 34.8 49.4 21.8Z" fill="url(#nexmail-mark)" />
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
