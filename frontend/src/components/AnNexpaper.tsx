/* „Als Dokument an nexpaper“ neben einem Anhang (Durchgang „Module“, Runde 2, V19: nexmail ist Gast mit
   `documents.add`). Steht nur, solange eine per „Verbinden“ gemachte Verbindung mit nexpaper trägt (V20: keine Wirkung
   ohne Verbindung, kein Knopf). Entwurf: Ort und Wortlaut sagt der Entwurf nicht (Frage in einst-fragen).
   V38: Darf die Verbindung in mehr als einen Tresor ablegen, fragt ein kleines Fenster wie „Zu Aufgabe machen“, der
   zuletzt genutzte vorgewählt (der Server merkt ihn je Konto); sonst geht der Anhang direkt. */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, FileUp } from 'lucide-react'
import { api } from '../api/client'
import { Button, Dialog, IconButton, Select } from '../ds'
import { servermeldung } from '../lib/servermeldung'

type Karte = { partner: string; state: string }
type Tresor = { id: number; name: string }

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
  /** V38: die Tresore zur Wahl, solange das Fenster offen ist. */
  const [wahl, setWahl] = useState<Tresor[] | null>(null)
  const [gewaehlt, setGewaehlt] = useState<number | null>(null)

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

  async function senden(tresor: number | null) {
    setLage('laeuft')
    setFehler('')
    setWahl(null)
    try {
      await api.senden(`/api/nachrichten/${nachrichtId}/anhang/${anhangId}/nexpaper`, { tresor })
      setLage('fertig')
    } catch (f) {
      setLage('ruhe')
      setFehler(servermeldung(f))
    }
  }

  async function los() {
    setFehler('')
    setLage('laeuft')
    try {
      const stand = await api.holen<{ tresore: Tresor[]; zuletzt: number | null }>('/api/nexpaper/tresore')
      if (stand.tresore.length > 1) {
        setGewaehlt(stand.zuletzt ?? stand.tresore[0].id)
        setWahl(stand.tresore)
        setLage('ruhe')
        return
      }
      await senden(stand.tresore[0]?.id ?? null)
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
        onClick={() => void los()}
        data-testid="an-nexpaper"
      />
      <Dialog
        open={wahl !== null}
        title={t('lesen.an_nexpaper')}
        onClose={() => setWahl(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setWahl(null)}>
              {t('aktion.abbrechen')}
            </Button>
            <Button variant="primary" type="submit" form={`an-nexpaper-${anhangId}`}>
              {t('lesen.an_nexpaper_ablegen')}
            </Button>
          </>
        }
      >
        <form
          id={`an-nexpaper-${anhangId}`}
          onSubmit={(e) => {
            e.preventDefault()
            void senden(gewaehlt)
          }}
        >
          <Select
            label={t('lesen.an_nexpaper_tresor')}
            value={gewaehlt === null ? '' : String(gewaehlt)}
            onChange={(e) => setGewaehlt(Number(e.target.value))}
            data-testid="an-nexpaper-tresor"
          >
            {(wahl ?? []).map((tresor) => (
              <option key={tresor.id} value={String(tresor.id)} className="bg-surface-1 text-fg-1">
                {tresor.name}
              </option>
            ))}
          </Select>
        </form>
      </Dialog>
      {fehler && (
        <span role="alert" className="max-w-[28ch] text-[12px] text-danger">
          {fehler}
        </span>
      )}
    </span>
  )
}
