/* Die iPhone-App verbinden: QR-Code und kurzer Code.
 *
 * ⚠️ **Der Code lebt nur auf dieser Seite.** Geheimnis und Code kommen einmal
 * vom Server und stehen dort nur als Hash; wer die Seite neu lädt, holt einen
 * neuen. Das verbundene Gerät steht danach unter Sicherheit, bei den
 * angemeldeten Geräten: Eine zweite Liste hieße, dass „überall abmelden" und diese
 * Seite verschiedene Dinge behaupten können.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, QrCode } from 'lucide-react'
import { api } from '../api/client'
import { Button, Switch } from '../ds'
import { servermeldung } from '../lib/servermeldung'

interface Kopplung {
  kennung: string
  code: string
  gilt_bis: string
  adresse: string
  qr_svg: string
}

interface Stand {
  stand: 'wartet' | 'verbunden' | 'abgelaufen'
  geraet: string
}

/** Wie oft die Seite nachfragt, ob der Code abgeholt ist. */
const NACHSEHEN_MS = 3000

export function IphoneVerbinden({ istBetreiber }: { istBetreiber: boolean }) {
  const { t, i18n } = useTranslation()
  const [erlaubt, setErlaubt] = useState<boolean | null>(null)
  const [kopplung, setKopplung] = useState<Kopplung | null>(null)
  const [stand, setStand] = useState<Stand | null>(null)
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    void api
      .holen<{ erlaubt: boolean }>('/api/app-kopplung/erlaubt')
      .then((r) => setErlaubt(r.erlaubt))
      .catch(() => setErlaubt(false))
  }, [])

  /* Nur solange gewartet wird: Ein verbundener oder abgelaufener Code ändert
     sich nicht mehr. */
  const kennung = kopplung?.kennung
  const wartet = Boolean(kennung) && (stand === null || stand.stand === 'wartet')
  useEffect(() => {
    if (!kennung || !wartet) return
    const uhr = window.setInterval(() => {
      void api
        .holen<Stand>(`/api/app-kopplung/${kennung}`)
        .then(setStand)
        .catch(() => undefined)
    }, NACHSEHEN_MS)
    return () => window.clearInterval(uhr)
  }, [kennung, wartet])

  async function anzeigen() {
    setFehler('')
    setStand(null)
    try {
      setKopplung(
        await api.senden<Kopplung>('/api/app-kopplung', {
          adresse: window.location.origin + window.location.pathname.replace(/\/$/, ''),
        }),
      )
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function zurueckziehen() {
    if (!kopplung) return
    try {
      await api.loeschen(`/api/app-kopplung/${kopplung.kennung}`)
      setKopplung(null)
      setStand(null)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function umlegen(an: boolean) {
    setFehler('')
    try {
      const r = await api.aendern<{ erlaubt: boolean }>('/api/app-kopplung/erlaubt', { erlaubt: an })
      setErlaubt(r.erlaubt)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  const fertig = stand?.stand === 'verbunden' || stand?.stand === 'abgelaufen'

  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      {istBetreiber && (
        <section className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface-2 p-4">
          <p className="mb-0 text-[13px] text-fg-2">{t('iphone.riegel_hinweis')}</p>
          <Switch
            label={t('iphone.riegel')}
            checked={erlaubt ?? false}
            disabled={erlaubt === null}
            onCheckedChange={(an) => void umlegen(an)}
          />
        </section>
      )}

      {erlaubt === false && !istBetreiber && (
        <p className="mb-0 text-[13px] text-fg-2">{t('iphone.riegel_zu')}</p>
      )}

      {erlaubt && (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
          <p className="mb-0 text-[13px] text-fg-2">{t('iphone.hinweis')}</p>

          {kopplung && stand?.stand !== 'verbunden' && stand?.stand !== 'abgelaufen' && (
            <div className="flex flex-wrap items-start gap-5">
              {/* ⚠️ **Das SVG baut der eigene Server aus dem Link**, wie beim
                  zweiten Faktor; es kommt nichts Fremdes hinein. */}
              <div
                role="img"
                aria-label={t('einstellungen.iphone')}
                className="size-[200px] shrink-0 overflow-hidden rounded-md bg-white [&>svg]:size-full"
                dangerouslySetInnerHTML={{ __html: kopplung.qr_svg }}
              />
              <div className="flex min-w-[220px] flex-1 flex-col gap-2">
                <p className="mb-0 text-[12px] text-fg-3">{t('iphone.code_abtippen')}</p>
                <p className="mb-0 text-[12px] text-fg-4">
                  {t('iphone.adresse')}:{' '}
                  <span className="font-mono break-all text-fg-2">{kopplung.adresse}</span>
                </p>
                <p className="mb-0 text-[12px] text-fg-4">
                  {t('iphone.code')}:{' '}
                  <span className="font-mono text-[18px] tracking-[0.08em] text-fg-1">
                    {kopplung.code}
                  </span>
                </p>
                <p role="status" className="mb-0 text-[12px] text-fg-3">
                  {t('iphone.wartet', {
                    zeit: new Date(kopplung.gilt_bis).toLocaleTimeString(i18n.language, {
                      hour: '2-digit',
                      minute: '2-digit',
                    }),
                  })}
                </p>
                <div>
                  <Button variant="ghost" onClick={() => void zurueckziehen()}>
                    {t('iphone.zurueckziehen')}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {stand?.stand === 'verbunden' && (
            <div role="status" className="flex items-start gap-2">
              <Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
              <div className="flex flex-col gap-1">
                <p className="mb-0 text-[13px] font-medium text-fg-1">
                  {t('iphone.verbunden', { geraet: stand.geraet })}
                </p>
                <p className="mb-0 text-[12px] text-fg-3">{t('iphone.verbunden_hinweis')}</p>
              </div>
            </div>
          )}

          {stand?.stand === 'abgelaufen' && (
            <p role="status" className="mb-0 text-[13px] text-fg-2">
              {t('iphone.abgelaufen')}
            </p>
          )}

          {(!kopplung || fertig) && (
            <div>
              <Button iconLeft={<QrCode className="size-4" />} onClick={() => void anzeigen()}>
                {kopplung ? t('iphone.neu') : t('iphone.knopf')}
              </Button>
            </div>
          )}
        </section>
      )}

      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
    </div>
  )
}
