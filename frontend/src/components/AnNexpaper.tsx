/* „Als Dokument an nexpaper“ neben einem Anhang (Durchgang „Module“, Runde 2, V19: nexmail ist Gast mit
   `documents.add`). Steht nur, solange eine per „Verbinden“ gemachte Verbindung mit nexpaper trägt (V20: keine Wirkung
   ohne Verbindung, kein Knopf). Entwurf: Ort und Wortlaut sagt der Entwurf nicht (Frage in einst-fragen). */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, FileUp } from 'lucide-react'
import { api } from '../api/client'
import { IconButton } from '../ds'
import { servermeldung } from '../lib/servermeldung'

type Karte = { partner: string; state: string }

let gemerkt: { zeit: number; wert: Promise<boolean> } | null = null

/** Ob nexpaper per Klick verbunden ist; eine Minute gemerkt, damit nicht jede Mail die Karten holt. */
export function nexpaperVerbunden(jetzt = Date.now()): Promise<boolean> {
  if (!gemerkt || jetzt - gemerkt.zeit > 60_000) {
    gemerkt = {
      zeit: jetzt,
      wert: api
        .holen<Karte[]>('/api/connect/partners')
        .then((karten) => karten.some((k) => k.partner === 'nexpaper' && k.state === 'connected'))
        .catch(() => false),
    }
  }
  return gemerkt.wert
}

/** Nur für Tests. */
export function nexpaperVergessen() {
  gemerkt = null
}

export function AnNexpaper({ nachrichtId, anhangId }: { nachrichtId: number | string; anhangId: number | string }) {
  const { t } = useTranslation()
  const [da, setDa] = useState(false)
  const [lage, setLage] = useState<'ruhe' | 'laeuft' | 'fertig'>('ruhe')
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    let weg = false
    void nexpaperVerbunden().then((ja) => {
      if (!weg) setDa(ja)
    })
    return () => {
      weg = true
    }
  }, [])

  if (!da) return null

  async function senden() {
    setLage('laeuft')
    setFehler('')
    try {
      await api.senden(`/api/nachrichten/${nachrichtId}/anhang/${anhangId}/nexpaper`, {})
      setLage('fertig')
    } catch (f) {
      setLage('ruhe')
      setFehler(servermeldung(f))
    }
  }

  return (
    <span className="inline-flex items-center gap-1">
      <IconButton
        icon={lage === 'fertig' ? <Check className="size-4" /> : <FileUp className="size-4" />}
        label={lage === 'fertig' ? t('lesen.an_nexpaper_fertig') : t('lesen.an_nexpaper')}
        size="sm"
        disabled={lage !== 'ruhe'}
        onClick={() => void senden()}
        data-testid="an-nexpaper"
      />
      {fehler && (
        <span role="alert" className="max-w-[28ch] text-[12px] text-danger">
          {fehler}
        </span>
      )}
    </span>
  )
}
