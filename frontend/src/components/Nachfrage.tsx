/* Rückfragen im eigenen Fenster — nicht im Browser-Kasten.
 *
 * ⚠️ **`window.confirm` und `window.prompt` sind keine Oberfläche.** Sie sehen
 * in jedem Browser anders aus, tragen „Auf localhost:5175 wird Folgendes
 * angezeigt" im Titel, ignorieren Farben und Schrift der Anwendung und lassen
 * sich vom Betreiber dauerhaft abschalten — dann verschwindet die Rückfrage
 * ersatzlos und die Handlung passiert kommentarlos. Für ein Löschen ohne
 * Rückweg ist das der falsche Weg.
 *
 * Benutzt wird das als Haken: `const { fragen, fenster } = useNachfrage()`.
 * `fragen(...)` gibt ein Versprechen zurück, das mit der Antwort aufgelöst
 * wird — genau wie `confirm`/`prompt`, nur eben im eigenen Haus.
 */
import { useCallback, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Dialog, Input } from '../ds'

interface Frage {
  titel: string
  text?: string
  /** Gesetzt heißt: mit Eingabefeld (Ersatz für `prompt`). */
  eingabe?: { beschriftung: string; vorgabe?: string; platzhalter?: string }
  /** Beschriftung der bestätigenden Schaltfläche. */
  knopf?: string
  /** Rot einfärben — für alles ohne Rückweg. */
  gefaehrlich?: boolean
}

type Antwort = string | boolean | null

export function useNachfrage() {
  const { t } = useTranslation()
  const [frage, setFrage] = useState<Frage | null>(null)
  const [wert, setWert] = useState('')
  const aufloesen = useRef<((a: Antwort) => void) | null>(null)

  const fragen = useCallback((f: Frage): Promise<Antwort> => {
    setFrage(f)
    setWert(f.eingabe?.vorgabe ?? '')
    return new Promise<Antwort>((fertig) => {
      aufloesen.current = fertig
    })
  }, [])

  function schliessen(antwort: Antwort) {
    setFrage(null)
    aufloesen.current?.(antwort)
    aufloesen.current = null
  }

  const fenster = (
    <Dialog
      open={frage !== null}
      title={frage?.titel}
      description={frage?.text}
      width={460}
      // ⚠️ Abbrechen ist hier der **einzige** stille Ausgang: Wer das Fenster
      // schließt, hat nicht zugestimmt.
      onClose={() => schliessen(frage?.eingabe ? null : false)}
      closeLabel={t('aktion.abbrechen')}
      footer={
        <>
          <Button variant="ghost" onClick={() => schliessen(frage?.eingabe ? null : false)}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant={frage?.gefaehrlich ? 'danger' : 'primary'}
            disabled={Boolean(frage?.eingabe) && !wert.trim()}
            onClick={() => schliessen(frage?.eingabe ? wert.trim() : true)}
          >
            {frage?.knopf ?? t('aktion.weiter')}
          </Button>
        </>
      }
    >
      {frage?.eingabe && (
        <Input
          label={frage.eingabe.beschriftung}
          placeholder={frage.eingabe.platzhalter}
          value={wert}
          autoFocus
          onChange={(e) => setWert(e.target.value)}
          onKeyDown={(e) => {
            // Eingabetaste bestätigt — sonst sucht man die Schaltfläche.
            if (e.key === 'Enter' && wert.trim()) {
              e.preventDefault()
              schliessen(wert.trim())
            }
          }}
        />
      )}
    </Dialog>
  )

  return { fragen, fenster }
}
