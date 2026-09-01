/* Der Vorbau, unter dem nexmail läuft — `/nexmail` bei
 * `https://mail.example.org/nexmail`, sonst leer.
 *
 * ⚠️ **Er kommt vom Server, nicht aus dem Bau.** Vite trägt `BASE_URL` beim
 * Bauen ein; ein Abbild wäre damit für **einen** Pfad gebaut, und wer nexmail
 * unter `/mail` betreibt statt unter `/nexmail`, bräuchte ein eigenes.
 * Deshalb schreibt der Server beim Start `window.__NEXMAIL_BASIS__` in die
 * `index.html`. `BASE_URL` bleibt der Rückfall für den Entwicklungsbetrieb.
 *
 * ⚠️ **Jede Adresse, die die Oberfläche selbst baut, muss hier durch.** Nicht
 * nur die API-Aufrufe: Auch was sie aus `window.location.pathname` liest und
 * was sie mit `history.replaceState` setzt. Genau daran ist der Einladungslink
 * gescheitert — `^/einladung/` traf unter einem Vorbau nie zu, und die Seite
 * zeigte stumm die Anmeldung.
 */

/* ⚠️ **Der Wert steht in einem `<meta>`, nicht in einer Inline-Zeile.**
   Nexview spritzt an dieser Stelle ein `<script>` ein; dort geht das, weil
   dessen CSP mit Prüfsummen der Inline-Skripte arbeitet. nexmails CSP sagt
   schlicht `script-src 'self'` — die Zeile wurde stumm verworfen, die Seite
   lud ohne Vorbau und zeigte gar keine Anmeldemaske. Ein `meta` fällt unter
   keine Skript-Regel. */
const ausMeta = document
  .querySelector('meta[name="nexmail-basis"]')
  ?.getAttribute('content')

export const BASIS = (ausMeta || import.meta.env.BASE_URL || '/').replace(/\/$/, '')

/** Eine App-Adresse mit Vorbau — `/einladung/abc` → `/nexmail/einladung/abc`. */
export function appPfad(pfad: string): string {
  const rein = pfad.startsWith('/') ? pfad : `/${pfad}`
  return `${BASIS}${rein}` || '/'
}

/** Der Pfad **ohne** Vorbau — die Umkehrung von `appPfad`.
 *
 * Gibt `null` zurück, wenn die Adresse gar nicht zu dieser Installation
 * gehört. ⚠️ `/nexmailfoo` trägt den Vorbau nur scheinbar und zählt nicht.
 */
export function ohneBasis(pfad: string): string | null {
  if (!BASIS) return pfad
  if (pfad === BASIS) return '/'
  if (pfad.startsWith(`${BASIS}/`)) return pfad.slice(BASIS.length)
  return null
}
