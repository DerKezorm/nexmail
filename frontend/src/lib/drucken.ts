/* Eine Nachricht drucken.
 *
 * Die Druckseite baut der Server (`/api/nachrichten/{id}/druck`) — ein
 * eigenständiges, skriptfreies Dokument. Deshalb muss das Anstoßen des
 * Druckdialogs von hier kommen: Das Dokument selbst darf und kann sich nicht
 * selbst drucken.
 *
 * ⚠️ **Unsichtbarer Rahmen statt neuem Fenster** (umgebaut am 02.09.2026).
 * Der erste Wurf öffnete ein Fenster und wollte nach dessen `load` drucken —
 * nur hängt der Lauscher am *alten* Fensterobjekt (about:blank); nach der
 * Navigation feuert er nie, und übrig blieb genau das, was auffiel: ein neuer
 * Tab mit der Druckseite und **kein** Druckdialog. Der Rahmen bleibt im
 * selben Fenster, sein `load` gehört uns, und `contentWindow.print()` öffnet
 * den Dialog direkt über der App.
 *
 * ⚠️ **`width/height: 0`, nicht `display: none`.** Ein unsichtbar
 * geschalteter Rahmen wird von manchen Browsern gar nicht erst gesetzt —
 * gedruckt käme eine leere Seite.
 */
import { appPfad } from './basis'

export function nachrichtDrucken(id: string, sprache: string): void {
  // ⚠️ Durch `appPfad` — unter einem Unterpfad zeigt `/api/…` sonst auf die
  // Wurzel der Domain, und der Rahmen bleibt weiß.
  const adresse = appPfad(
    `/api/nachrichten/${encodeURIComponent(id)}/druck?sprache=${encodeURIComponent(sprache)}`,
  )

  const rahmen = document.createElement('iframe')
  rahmen.setAttribute('aria-hidden', 'true')
  rahmen.style.position = 'fixed'
  rahmen.style.right = '0'
  rahmen.style.bottom = '0'
  rahmen.style.width = '0'
  rahmen.style.height = '0'
  rahmen.style.border = '0'

  rahmen.addEventListener('load', () => {
    try {
      rahmen.contentWindow?.focus()
      rahmen.contentWindow?.print()
    } finally {
      // ⚠️ Nicht sofort wegräumen: In den meisten Browsern blockiert
      // `print()` bis zum Schließen des Dialogs, aber nicht in allen — ein zu
      // früh entfernter Rahmen druckt dort eine leere Seite. Eine Minute ist
      // für jeden Dialog genug, und ein unsichtbarer 0×0-Rahmen stört solange
      // niemanden.
      window.setTimeout(() => rahmen.remove(), 60_000)
    }
  })

  rahmen.src = adresse
  document.body.appendChild(rahmen)
}
