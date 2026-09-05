/* Erteilte Zustimmungen für Google und Microsoft.
 *
 * ⚠️ **Eine Zustimmung, mehrere Nutzungen.** Wer sein Google-Konto freigibt,
 * soll nicht für den Kalender ein zweites Mal durch dieselbe Maske. Deshalb
 * steht die Liste hier — bei den Konten, nicht beim Postfach und nicht beim
 * Kalender.
 *
 * ⚠️ **Trennen vergisst nur nexmails Token.** Beim Anbieter bleibt die
 * Erlaubnis bestehen; dort widerruft man sie im eigenen Konto. Das steht in
 * der Rückfrage, sonst hält man es für vollständig.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, KeyRound } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { useNachfrage } from './Nachfrage'
import { Badge, Button } from '../ds'
import { RUECKWEG } from '../lib/oauthrueckweg'

interface Zugang {
  id: string
  art: string
  adresse: string
  letzter_fehler: string
  /** Wie viele Postfächer, Kalender und Adressbücher an dieser Zustimmung hängen. */
  postfaecher: number
  kalender: number
  adressbuecher: number
}

interface AnbieterZeile {
  art: string
  name: string
  eingerichtet: boolean
}

interface Props {
  /** Nur der Betreiber sieht, welche Apps eingerichtet sind. */
  istBetreiber?: boolean
}

export function Oauthzugaenge({ istBetreiber = false }: Props) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster } = useNachfrage()
  const [zugaenge, setZugaenge] = useState<Zugang[] | null>(null)
  const [anbieter, setAnbieter] = useState<AnbieterZeile[]>([])
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    try {
      setZugaenge(await api.holen<Zugang[]>('/api/mailoauth/zugaenge'))
    } catch {
      setZugaenge([])
    }
    /* ⚠️ **`/moeglich` steht jedem offen, `/anbieter` nur dem Betreiber.**
       Vorher wurde für alle anderen geraten („dann bieten wir eben beide an"),
       und wer auf einen nicht eingerichteten Anbieter klickte, bekam eine
       Fehlermeldung statt einer Auskunft. */
    try {
      setAnbieter(await api.holen<AnbieterZeile[]>('/api/mailoauth/moeglich'))
    } catch {
      setAnbieter([])
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  /* ⚠️ **Die Rückkehr landet auf der Startseite mit `?oauth=…`.** Der Rückweg
     ist eine Weiterleitung vom Anbieter — er kann nicht in dieses Fenster
     zurückspringen. Gelesen wird er einmal beim Laden der Seite
     (`lib/oauthrueckweg.ts`); wer ihn hier selbst aus der Adresse holte, nähme
     ihn dem Fenster „Postfach hinzufügen" weg, das auf denselben Wert wartet.

     ⚠️ **Was aus „Postfach hinzufügen" kam, gehört nicht hierher.** Der Fehler
     steht dann in jenem Fenster; zweimal derselbe Satz an zwei Stellen sieht
     aus wie zwei Fehler. */
  useEffect(() => {
    if (!RUECKWEG.stand || RUECKWEG.weiter === 'postfach') return
    if (RUECKWEG.stand !== 'ok') {
      const schluessel = `oauth.fehler_${RUECKWEG.stand}`
      setFehler(i18n.exists(schluessel) ? t(schluessel) : t('oauth.fehler_allgemein'))
    }
    void laden()
  }, [i18n, t, laden])

  async function verbinden(art: string) {
    setFehler('')
    try {
      const { ziel } = await api.senden<{ ziel: string }>(`/api/mailoauth/${art}/start`, {})
      // ⚠️ Eine echte Navigation, kein fetch: Die Zustimmung erteilt der
      // Mensch beim Anbieter, nicht nexmail in seinem Namen.
      window.location.href = ziel
    } catch (f) {
      const kennung = f instanceof ApiFehler ? f.detail : ''
      const schluessel = `oauth.fehler_${kennung}`
      setFehler(i18n.exists(schluessel) ? t(schluessel) : t('oauth.fehler_allgemein'))
    }
  }

  /* ⚠️ **Was mitgeht, steht VOR der Zustimmung, nicht im Bericht danach.**
     Ein Postfach ohne Zustimmung hat keinen Anmeldeweg mehr; es stehen zu
     lassen hiesse, bei jedem Takt „Anmeldung fehlgeschlagen" zu melden — und
     niemand brächte das mit dem Trennen in Verbindung. Also wird es entfernt,
     und die Frage sagt mit Zahlen, was das kostet. */
  function haengtDran(z: Zugang) {
    // ⚠️ Nur nennen, was es gibt. „und 0 Kalender" liest sich wie ein Fehler.
    const teile: string[] = []
    if (z.postfaecher) teile.push(t('oauth.trennen_postfaecher', { count: z.postfaecher }))
    if (z.kalender) teile.push(t('oauth.trennen_kalender', { count: z.kalender }))
    if (z.adressbuecher) teile.push(t('oauth.trennen_adressbuecher', { count: z.adressbuecher }))
    if (teile.length === 0) return t('oauth.trennen_text')
    return `${t('oauth.trennen_haengt_dran', { was: teile.join(t('oauth.und')) })} ${t(
      'oauth.trennen_text',
    )}`
  }

  const moeglich = anbieter.filter((a) => a.eingerichtet)
  const knoepfe = moeglich.map((a) => a.art)

  return (
    <section className="flex flex-col gap-3">
      <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('oauth.zugaenge')}</h2>
      <p className="mb-0 text-[12px] text-fg-3">{t('oauth.zugaenge_text')}</p>

      {fehler && <p className="mb-0 text-[12px] text-danger">{fehler}</p>}

      {zugaenge !== null && zugaenge.length === 0 && (
        <p className="mb-0 text-[12px] text-fg-4">{t('oauth.keine_zugaenge')}</p>
      )}

      <ul className="flex list-none flex-col gap-2 p-0">
        {(zugaenge ?? []).map((z) => (
          <li
            key={z.id}
            className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-2.5"
          >
            <KeyRound aria-hidden className="size-4 shrink-0 text-fg-4" />
            <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">
              {z.adresse || z.art}
            </span>
            {/* ⚠️ **Ein toter Zugang muss man sehen.** Sonst sieht er aus wie
                ein kaputter Mailserver, und man sucht an der falschen Stelle. */}
            {z.letzter_fehler ? (
              <span className="flex items-center gap-1.5 text-[12px] text-warning">
                <AlertTriangle aria-hidden className="size-3.5" />
                {t('oauth.abgelaufen')}
              </span>
            ) : (
              <Badge tone="accent">{t(`oauth.verbinden_${z.art}`).split(' ')[0]}</Badge>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                void (async () => {
                  const ja = await fragen({
                    titel: t('oauth.trennen_frage', { adresse: z.adresse || z.art }),
                    text: haengtDran(z),
                    knopf: t('oauth.trennen'),
                    gefaehrlich: true,
                  })
                  if (ja !== true) return
                  await api.loeschen(`/api/mailoauth/zugaenge/${z.id}`)
                  await laden()
                })()
              }
            >
              {t('oauth.trennen')}
            </Button>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap gap-2">
        {knoepfe.map((art) => (
          <Button key={art} size="sm" variant="secondary" onClick={() => void verbinden(art)}>
            {t(`oauth.verbinden_${art}`)}
          </Button>
        ))}
      </div>

      {anbieter.length > 0 && moeglich.length === 0 && (
        <p className="mb-0 text-[12px] text-fg-4">
          {istBetreiber ? t('oauth.nicht_eingerichtet') : t('oauth.nicht_eingerichtet_benutzer')}
        </p>
      )}

      {fenster}
    </section>
  )
}
