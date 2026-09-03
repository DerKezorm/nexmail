/* Einen Kalender anlegen, verbinden oder abonnieren.
 *
 * ⚠️ **Drei Wege, und sie tun wirklich Verschiedenes.** Das ist der Grund für
 * die Weiche am Anfang statt eines Formulars mit Umschalter:
 *
 * | | woher | schreiben |
 * |---|---|---|
 * | **Neuer Kalender** | nirgendwo, er entsteht hier | ja |
 * | **Verbinden** (CalDAV) | iCloud, Nextcloud, eigener Server | ja |
 * | **Abonnieren** (ICS) | ein Link, den jemand veröffentlicht | nie |
 *
 * ⚠️ **Ein CalDAV-Zugang ist nicht EIN Kalender, sondern mehrere.** Wer eine
 * iCloud-Adresse einträgt, bekommt „Privat", „Arbeit", „Geburtstage" und was
 * sonst dort liegt. Sie alle blind zu übernehmen füllt die Spalte mit Zeug,
 * das niemand sehen will — deshalb wird gesucht und **dann ausgewählt**,
 * genau wie beim Abonnieren von IMAP-Ordnern.
 *
 * ⚠️ **Google steht sichtbar da und ist gesperrt.** Ein Anbieter, der einfach
 * fehlt, sieht aus wie ein Versehen; hier steht der Grund daneben.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarPlus, Link2, Rss } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import {
  kalenderAbonnieren,
  kalenderAnlegen,
  kalenderPruefen,
  kalenderVerbinden,
} from '../api/laden'
import type { GefundenerKalender, KalenderZeile } from '../api/laden'
import { Button, Checkbox, Dialog, Input, Select } from '../ds'
import { PUNKT_KLASSE } from '../lib/farben'
import type { Postfachfarbe } from '../daten/typen'

type Weg = null | 'eigener' | 'verbinden' | 'abo'

interface Props {
  /** Die vorhandenen Kalender — daraus kommt die nächste freie Farbe. */
  vorhanden: KalenderZeile[]
  onClose: () => void
  /** Nach dem Anlegen: die Liste neu holen. */
  onFertig: () => void
}

export function Kalenderfenster({ vorhanden, onClose, onFertig }: Props) {
  const { t, i18n } = useTranslation()
  const [weg, setWeg] = useState<Weg>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  // Eigener Kalender
  const erste =
    ([1, 2, 3, 4, 5, 6] as Postfachfarbe[]).find((f) => !vorhanden.some((k) => k.farbe === f)) ?? 1
  const [name, setName] = useState('')
  const [farbe, setFarbe] = useState<Postfachfarbe>(erste)

  // Verbinden
  const [anbieter, setAnbieter] = useState('icloud')
  const [adresse, setAdresse] = useState('')
  const [benutzer, setBenutzer] = useState('')
  const [passwort, setPasswort] = useState('')
  const [gefunden, setGefunden] = useState<GefundenerKalender[] | null>(null)
  const [gewaehlt, setGewaehlt] = useState<Set<string>>(new Set())

  // Abo
  const [aboUrl, setAboUrl] = useState('')

  /* ⚠️ **Google spricht CalDAV nur mit einem Token.** Basic Auth an seinem
     Endpunkt wird abgewiesen — deshalb steht dort keine Passwortmaske,
     sondern die Liste der erteilten Zustimmungen. */
  const [zugaenge, setZugaenge] = useState<Array<{ id: string; art: string; adresse: string }>>([])
  const [zugangId, setZugangId] = useState('')
  useEffect(() => {
    void api
      .holen<Array<{ id: string; art: string; adresse: string }>>('/api/mailoauth/zugaenge')
      .then(setZugaenge)
      .catch(() => setZugaenge([]))
  }, [])
  const passende = zugaenge.filter((z) => z.art === 'google')
  useEffect(() => {
    if (anbieter === 'google' && !zugangId && passende.length) setZugangId(passende[0].id)
  }, [anbieter, zugangId, passende])

  /** ⚠️ Der Server nennt eine Kennung, die Oberfläche übersetzt. */
  function melden(f: unknown) {
    const kennung = f instanceof ApiFehler ? f.detail : ''
    const schluessel = `kalender.fehler_${kennung}`
    setFehler(i18n.exists(schluessel) ? t(schluessel) : t('kalender.fehler_allgemein'))
    setLaeuft(false)
  }

  async function suchen() {
    setLaeuft(true)
    setFehler('')
    try {
      const raus = await kalenderPruefen({
        art: anbieter,
        adresse,
        benutzer,
        passwort,
        oauthZugangId: anbieter === 'google' ? zugangId : '',
      })
      setGefunden(raus)
      // Ab Werk alle — wer weniger will, hakt ab.
      setGewaehlt(new Set(raus.map((k) => k.url)))
      if (raus.length === 0) setFehler(t('kalender.fehler_keine_gefunden'))
    } catch (f) {
      melden(f)
      return
    }
    setLaeuft(false)
  }

  async function fertigstellen() {
    setLaeuft(true)
    setFehler('')
    try {
      if (weg === 'eigener') {
        await kalenderAnlegen(name.trim(), farbe)
      } else if (weg === 'abo') {
        await kalenderAbonnieren(aboUrl.trim(), name.trim(), farbe)
      } else {
        await kalenderVerbinden({
          art: anbieter,
          adresse,
          benutzer,
          passwort,
          oauthZugangId: anbieter === 'google' ? zugangId : '',
          auswahl: (gefunden ?? []).filter((k) => gewaehlt.has(k.url)),
        })
      }
      onFertig()
      onClose()
    } catch (f) {
      melden(f)
    }
  }

  const bereit =
    weg === 'eigener'
      ? Boolean(name.trim())
      : weg === 'abo'
        ? Boolean(aboUrl.trim())
        : gefunden !== null && gewaehlt.size > 0

  return (
    <Dialog
      open
      width={weg === 'verbinden' ? 540 : 480}
      title={t('kalender.hinzu_titel')}
      onClose={onClose}
      footer={
        weg === null ? undefined : (
          <>
            <Button variant="ghost" onClick={() => setWeg(null)}>
              {t('aktion.zurueck')}
            </Button>
            <Button
              variant="primary"
              disabled={!bereit || laeuft}
              loading={laeuft}
              onClick={() => void fertigstellen()}
            >
              {weg === 'eigener'
                ? t('kalender.anlegen')
                : weg === 'abo'
                  ? t('kalender.abonnieren')
                  : t('kalender.verbinden')}
            </Button>
          </>
        )
      }
    >
      {weg === null && <Weiche aufWeg={setWeg} />}

      {weg === 'eigener' && (
        <div className="flex flex-col gap-3">
          <Input
            label={t('kalender.name')}
            placeholder={t('kalender.name_platzhalter')}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Farbwahl farbe={farbe} aufFarbe={setFarbe} />
        </div>
      )}

      {weg === 'verbinden' && (
        <div className="flex flex-col gap-3">
          <Select
            label={t('kalender.anbieter')}
            value={anbieter}
            onChange={(e) => {
              setAnbieter(e.target.value)
              setGefunden(null)
            }}
          >
            <option value="icloud">{t('kalender.anbieter_icloud')}</option>
            <option value="nextcloud">{t('kalender.anbieter_nextcloud')}</option>
            {/* ⚠️ Nur waehlbar, wenn es eine Zustimmung gibt — sonst
                fuehrte der Klick in eine Fehlermeldung statt zu einem Weg. */}
            <option value="google" disabled={passende.length === 0}>
              {passende.length ? 'Google' : t('kalender.anbieter_google')}
            </option>
            <option value="andere">{t('kalender.anbieter_andere')}</option>
          </Select>

          {/* ⚠️ **Nur unter Google.** Der Satz stand unter jedem Anbieter — auch
              unter einem, der mit Google nichts zu tun hat; dort las er sich
              wie eine Bedingung für dessen Anmeldung. Der Grund gehört neben
              den gesperrten Eintrag, nicht in eine Fehlermeldung nach dem
              Klick — aber eben auch nur dorthin. */}
          {anbieter === 'google' && (
            <p className="text-[12px] leading-relaxed text-fg-4">{t('kalender.google_warum')}</p>
          )}

          {anbieter === 'google' ? (
            <Select
              label={t('kalender.google_konto')}
              value={zugangId}
              onChange={(e) => setZugangId(e.target.value)}
            >
              {passende.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.adresse || z.id}
                </option>
              ))}
            </Select>
          ) : null}

          {anbieter !== 'icloud' && anbieter !== 'google' && (
            <Input
              label={t('kalender.adresse')}
              value={adresse}
              onChange={(e) => setAdresse(e.target.value)}
              placeholder={
                anbieter === 'nextcloud'
                  ? 'https://wolke.example.com/remote.php/dav'
                  : 'https://caldav.example.com/dav/'
              }
            />
          )}
          {anbieter !== 'google' && (
            <>
              <Input
                label={t('kalender.benutzer')}
                value={benutzer}
                onChange={(e) => setBenutzer(e.target.value)}
                placeholder="name@example.com"
              />
              <Input
                label={t('kalender.passwort')}
                type="password"
                value={passwort}
                onChange={(e) => setPasswort(e.target.value)}
                hint={anbieter === 'icloud' ? t('kalender.icloud_hinweis') : undefined}
              />
            </>
          )}

          <div>
            <Button
              variant="secondary"
              size="sm"
              disabled={
                (anbieter === 'google' ? !zugangId : !benutzer.trim() || !passwort) || laeuft
              }
              loading={laeuft && gefunden === null}
              onClick={() => void suchen()}
            >
              {t('kalender.pruefen')}
            </Button>
          </div>

          {gefunden !== null && gefunden.length > 0 && (
            <div className="flex flex-col gap-2 rounded-md border border-line p-3">
              <span className="text-[12px] font-medium text-fg-2">{t('kalender.gefunden')}</span>
              {/* ⚠️ **Was schon dasteht, ist gesperrt und sagt warum.** Ein
                  Eintrag, dessen Auswahl nur in eine Absage führt, ist eine
                  Sackgasse mit Beschriftung — und wer ihn doch verbindet, hat
                  jeden Termin doppelt. */}
              {gefunden.map((k) => (
                <Checkbox
                  key={k.url}
                  label={k.name}
                  description={k.schon_verbunden ? t('kalender.schon_verbunden') : undefined}
                  disabled={k.schon_verbunden}
                  checked={gewaehlt.has(k.url)}
                  onCheckedChange={(an) =>
                    setGewaehlt((alt) => {
                      const neu = new Set(alt)
                      if (an) neu.add(k.url)
                      else neu.delete(k.url)
                      return neu
                    })
                  }
                />
              ))}
              <span className="text-[11px] leading-relaxed text-fg-4">
                {t('kalender.gefunden_hinweis')}
              </span>
            </div>
          )}
        </div>
      )}

      {weg === 'abo' && (
        <div className="flex flex-col gap-3">
          <Input
            label={t('kalender.abo_adresse')}
            placeholder={t('kalender.abo_platzhalter')}
            value={aboUrl}
            onChange={(e) => setAboUrl(e.target.value)}
          />
          <Input
            label={t('kalender.name')}
            placeholder={t('kalender.name_platzhalter')}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Farbwahl farbe={farbe} aufFarbe={setFarbe} />
        </div>
      )}

      {fehler && <p className="mt-3 text-[12px] text-danger">{fehler}</p>}
    </Dialog>
  )
}

/* --- Die Weiche --------------------------------------------------------- */

function Weiche({ aufWeg }: { aufWeg: (w: Weg) => void }) {
  const { t } = useTranslation()
  const karten: Array<{ id: Weg; symbol: React.ReactNode; titel: string; text: string }> = [
    {
      id: 'eigener',
      symbol: <CalendarPlus />,
      titel: t('kalender.hinzu_eigener'),
      text: t('kalender.hinzu_eigener_text'),
    },
    {
      id: 'verbinden',
      symbol: <Link2 />,
      titel: t('kalender.hinzu_verbinden'),
      text: t('kalender.hinzu_verbinden_text'),
    },
    {
      id: 'abo',
      symbol: <Rss />,
      titel: t('kalender.hinzu_abo'),
      text: t('kalender.hinzu_abo_text'),
    },
  ]

  return (
    <div className="flex flex-col gap-2">
      {karten.map((k) => (
        <button
          key={k.id}
          type="button"
          onClick={() => aufWeg(k.id)}
          className="flex items-start gap-3 rounded-md border border-line p-3 text-left transition-colors duration-[var(--dur-fast)] hover:border-accent-line hover:bg-surface-3 [&_svg]:size-5 [&_svg]:shrink-0 [&_svg]:text-fg-3"
        >
          {k.symbol}
          <span className="min-w-0">
            <span className="block text-[13px] font-medium text-fg-1">{k.titel}</span>
            <span className="block text-[12px] leading-relaxed text-fg-4">{k.text}</span>
          </span>
        </button>
      ))}
    </div>
  )
}

/** ⚠️ **Sechs zugeteilte Töne, kein Farbwähler.** Dieselbe Palette wie bei den
 *  Postfächern, aus demselben Grund: Zwei selbstgemischte, kaum
 *  unterscheidbare Farben fallen erst auf, wenn man den falschen Termin
 *  angesehen hat. */
function Farbwahl({
  farbe,
  aufFarbe,
}: {
  farbe: Postfachfarbe
  aufFarbe: (f: Postfachfarbe) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-fg-3">{t('kalender.farbe')}</span>
      <div className="flex gap-2">
        {([1, 2, 3, 4, 5, 6] as Postfachfarbe[]).map((f) => (
          <button
            key={f}
            type="button"
            aria-label={`${t('kalender.farbe')} ${f}`}
            aria-pressed={farbe === f}
            onClick={() => aufFarbe(f)}
            className={
              'size-7 rounded-md transition-transform duration-[var(--dur-fast)] ' +
              PUNKT_KLASSE[f] +
              (farbe === f ? ' ring-2 ring-accent ring-offset-2 ring-offset-surface-1' : '')
            }
          />
        ))}
      </div>
    </div>
  )
}
