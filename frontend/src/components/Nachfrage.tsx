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
import { Button, Checkbox, Dialog, Input, Select } from '../ds'

interface Frage {
  titel: string
  text?: string
  /** Gesetzt heißt: mit Eingabefeld (Ersatz für `prompt`).
   *  `typ` erlaubt andere Feldarten — „datetime-local" für die Wiedervorlage:
   *  Der Browser liest den Wert als Ortszeit, der Aufrufer macht ISO-UTC
   *  daraus (dasselbe Muster wie „Später senden" im Verfassen-Fenster). */
  eingabe?: { beschriftung: string; vorgabe?: string; platzhalter?: string; typ?: string }
  /** Beschriftung der bestätigenden Schaltfläche. */
  knopf?: string
  /** Ein Haken in der Rückfrage — für eine Nebenentscheidung, die zur
   *  Handlung gehört („Kalender mit entfernen"). ⚠️ **Vorbelegt mit aus:**
   *  Was zusätzlich gelöscht wird, soll man anhaken, nicht abwählen. */
  haken?: { beschriftung: string; vorgabe?: boolean }
  /** Eine Auswahl in der Rückfrage — wohin die Handlung gehen soll
   *  („In welchen Kalender?"). ⚠️ **Nur anbieten, wenn es etwas zu wählen
   *  gibt**; eine Liste mit einem Eintrag ist Zierde. */
  auswahl?: { beschriftung: string; werte: Array<{ wert: string; text: string }>; vorgabe?: string }
  /** Rot einfärben — für alles ohne Rückweg. */
  gefaehrlich?: boolean
}

/** Mit `haken` oder `auswahl` kommt statt `true` ein Objekt zurück — die
 *  Zustimmung **und** was nebenbei entschieden wurde. Rückfragen ohne beides
 *  bleiben, wie sie waren. */
export interface Zusage {
  ja: true
  haken: boolean
  wert: string
}

type Antwort = string | boolean | null | Zusage

export function useNachfrage() {
  const { t } = useTranslation()
  const [frage, setFrage] = useState<Frage | null>(null)
  const [wert, setWert] = useState('')
  const [hakenAn, setHakenAn] = useState(false)
  const [gewaehlt, setGewaehlt] = useState('')
  const aufloesen = useRef<((a: Antwort) => void) | null>(null)

  const fragen = useCallback((f: Frage): Promise<Antwort> => {
    setFrage(f)
    setWert(f.eingabe?.vorgabe ?? '')
    setHakenAn(f.haken?.vorgabe ?? false)
    setGewaehlt(f.auswahl?.vorgabe ?? f.auswahl?.werte[0]?.wert ?? '')
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
            onClick={() =>
              schliessen(
                frage?.eingabe
                  ? wert.trim()
                  : frage?.haken || frage?.auswahl
                    ? { ja: true, haken: hakenAn, wert: gewaehlt }
                    : true,
              )
            }
          >
            {frage?.knopf ?? t('aktion.weiter')}
          </Button>
        </>
      }
    >
      {frage?.auswahl && (
        <Select
          label={frage.auswahl.beschriftung}
          value={gewaehlt}
          onChange={(e) => setGewaehlt(e.target.value)}
        >
          {frage.auswahl.werte.map((w) => (
            <option key={w.wert} value={w.wert}>
              {w.text}
            </option>
          ))}
        </Select>
      )}

      {frage?.haken && (
        <Checkbox
          label={frage.haken.beschriftung}
          checked={hakenAn}
          onCheckedChange={setHakenAn}
        />
      )}

      {frage?.eingabe && (
        <Input
          label={frage.eingabe.beschriftung}
          placeholder={frage.eingabe.platzhalter}
          type={frage.eingabe.typ ?? 'text'}
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
