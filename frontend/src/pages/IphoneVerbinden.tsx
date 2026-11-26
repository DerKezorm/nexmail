/* Mein Konto › Verbindungen, erste Karte „Geräte" (Bauplan „Einstellungen", Verbindungen 1, E4): die gekoppelten
 * iPhones und iPads mit „zuletzt …", ob sie Mitteilungen bekommen, `sm` „Trennen"; unten „iPhone oder iPad verbinden"
 * mit QR-Code und kurzem Code im Fenster. Ersetzt nexmails Karte „iPhone verbinden"; der Schalter des Betreibers
 * („iPhone-App erlauben") steht seitdem unter Server › Allgemein › Schnittstellen.
 *
 * ⚠️ **Der Code lebt nur in diesem Fenster.** Geheimnis und Code kommen einmal vom Server und stehen dort nur als Hash;
 * wer neu lädt, holt einen neuen. Getrennt wird über denselben Weg wie unter Sicherheit (`DELETE /api/sitzungen/{id}`),
 * damit „überall abmelden" und diese Liste nie Verschiedenes behaupten.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Unlink } from 'lucide-react'

import { api } from '../api/client'
import { servermeldung } from '../lib/servermeldung'
import { Badge, Button, Buttons, Card, Dialog, Notice, Row, Rows } from '../vendor/nexui'

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

interface Geraet {
  id: string
  geraet: string
  zuletzt_gesehen: string
  mitteilungen: boolean
}

/** Wie oft das Fenster nachfragt, ob der Code abgeholt ist. */
const NACHSEHEN_MS = 3000

export function IphoneVerbinden() {
  const { t, i18n } = useTranslation()
  const [erlaubt, setErlaubt] = useState<boolean | null>(null)
  const [geraete, setGeraete] = useState<Geraet[] | null>(null)
  const [fenster, setFenster] = useState(false)
  const [fehler, setFehler] = useState('')

  const laden = useCallback(() => {
    void api
      .holen<{ erlaubt: boolean }>('/api/app-kopplung/erlaubt')
      .then((r) => setErlaubt(r.erlaubt))
      .catch(() => setErlaubt(false))
    void api
      .holen<Geraet[]>('/api/app-kopplung/geraete')
      .then(setGeraete)
      .catch(() => setGeraete([]))
  }, [])
  useEffect(laden, [laden])

  async function trennen(g: Geraet) {
    setFehler('')
    try {
      await api.loeschen(`/api/sitzungen/${g.id}`)
      laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  return (
    <Card id="devices" icon="Smartphone" title={t('geraete.titel')} subtitle={t('iphone.hinweis')}>
      {erlaubt === false && <Notice tone="warn">{t('iphone.riegel_zu')}</Notice>}
      {geraete && geraete.length > 0 ? (
        <Rows label={t('geraete.titel')} testId="geraete-liste">
          {geraete.map((g) => (
            <Row
              key={g.id}
              icon="Smartphone"
              name={g.geraet || t('geraete.ohne_namen')}
              badge={<Badge tone={g.mitteilungen ? 'on' : 'off'}>{g.mitteilungen ? t('geraete.mitteilungen_an') : t('geraete.mitteilungen_aus')}</Badge>}
              detail={t('geraete.zuletzt', {
                wann: new Date(g.zuletzt_gesehen).toLocaleString(i18n.language, { dateStyle: 'short', timeStyle: 'short' }),
              })}
              action={
                <Button size="sm" kind="danger" icon={Unlink} onClick={() => void trennen(g)} testId="geraet-trennen">
                  {t('geraete.trennen')}
                </Button>
              }
            />
          ))}
        </Rows>
      ) : (
        geraete && <p className="m-0 text-sm">{t('geraete.keine')}</p>
      )}
      {fehler && <Notice tone="danger">{fehler}</Notice>}
      {erlaubt && (
        <Buttons>
          <Button kind="primary" icon="Smartphone" onClick={() => setFenster(true)} testId="geraet-verbinden">
            {t('geraete.verbinden')}
          </Button>
        </Buttons>
      )}
      {fenster && (
        <Koppeln
          aufZu={() => {
            setFenster(false)
            laden()
          }}
        />
      )}
    </Card>
  )
}

/** Das Fenster „iPhone oder iPad verbinden": QR-Code, Adresse und Code zum Abtippen, wartet auf die App. */
function Koppeln({ aufZu }: { aufZu: () => void }) {
  const { t, i18n } = useTranslation()
  const [kopplung, setKopplung] = useState<Kopplung | null>(null)
  const [stand, setStand] = useState<Stand | null>(null)
  const [fehler, setFehler] = useState('')

  const anzeigen = useCallback(async () => {
    setFehler('')
    setStand(null)
    try {
      setKopplung(
        await api.senden<Kopplung>('/api/app-kopplung', {
          adresse: window.location.origin + window.location.pathname.replace(/\/settings(\/.*)?$/, '').replace(/\/$/, ''),
        }),
      )
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])
  useEffect(() => {
    void anzeigen()
  }, [anzeigen])

  /* Nur solange gewartet wird: Ein verbundener oder abgelaufener Code ändert sich nicht mehr. */
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

  async function schliessen() {
    if (kopplung && stand?.stand !== 'verbunden') {
      // Ein Code, den niemand mehr braucht, verfällt gleich.
      await api.loeschen(`/api/app-kopplung/${kopplung.kennung}`).catch(() => undefined)
    }
    aufZu()
  }

  return (
    <Dialog title={t('geraete.verbinden')} onClose={() => void schliessen()} closeLabel={t('aktion.schliessen')} testId="koppeln-fenster">
      <div className="flex flex-col gap-3">
        {kopplung && stand?.stand !== 'verbunden' && stand?.stand !== 'abgelaufen' && (
          <>
            {/* ⚠️ **Das SVG baut der eigene Server aus dem Link**, wie beim zweiten Faktor. */}
            <div
              role="img"
              aria-label={t('geraete.verbinden')}
              className="size-[200px] shrink-0 self-center overflow-hidden rounded-md bg-white [&>svg]:size-full"
              dangerouslySetInnerHTML={{ __html: kopplung.qr_svg }}
            />
            <p className="m-0 text-sm">{t('iphone.code_abtippen')}</p>
            <p className="m-0 text-sm">
              {t('iphone.adresse')}: <span className="font-mono break-all">{kopplung.adresse}</span>
            </p>
            <p className="m-0 text-sm">
              {t('iphone.code')}: <span className="font-mono text-lg tracking-[0.08em]">{kopplung.code}</span>
            </p>
            <p role="status" className="m-0 text-sm">
              {t('iphone.wartet', {
                zeit: new Date(kopplung.gilt_bis).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }),
              })}
            </p>
          </>
        )}
        {stand?.stand === 'verbunden' && <Notice tone="ok" title={t('iphone.verbunden', { geraet: stand.geraet })} />}
        {stand?.stand === 'abgelaufen' && (
          <>
            <Notice tone="warn">{t('iphone.abgelaufen')}</Notice>
            <Buttons>
              <Button kind="secondary" icon="RefreshCw" onClick={() => void anzeigen()}>
                {t('iphone.neu')}
              </Button>
            </Buttons>
          </>
        )}
        {fehler && <Notice tone="danger">{fehler}</Notice>}
      </div>
    </Dialog>
  )
}
