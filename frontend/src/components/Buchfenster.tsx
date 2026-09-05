/* Ein Adressbuch verbinden. Beta.
 *
 * ⚠️ **Nur lesend, und das Fenster sagt es als Erstes.** Lieferung 1 holt
 * Karten von iCloud, Google oder einem anderen CardDAV-Server und schreibt
 * nichts zurück. Beim Anbieter wird nichts geändert und nichts gelöscht; wer
 * das Buch später trennt, verliert nur nexmails Kopie.
 *
 * ⚠️ **Ein Zugang ist nicht EIN Buch, sondern mehrere.** Eine Apple-ID liefert
 * „Alle Kontakte" und was der Mensch sonst angelegt hat. Deshalb wird gesucht
 * und dann ausgewählt, genau wie beim Kalender.
 *
 * ⚠️ **Google nur über eine Zustimmung, und die muss bis zu den Kontakten
 * reichen.** Eine Zustimmung von vor der Beta hat den Bereich nicht; sie steht
 * gesperrt da und sagt, was zu tun ist, statt Google 403 sagen zu lassen. */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiFehler, api } from '../api/client'
import { Badge, Button, Checkbox, Dialog, Input, Select } from '../ds'

export interface GefundenesBuch {
  url: string
  name: string
  /** Steht schon in der Liste; ein zweites Mal hieße jede Karte doppelt. */
  schon_verbunden?: boolean
}

interface Zugang {
  id: string
  art: string
  adresse: string
  kann_adressbuch: boolean
}

interface Props {
  onClose: () => void
  /** Nach dem Verbinden: Bücher und Kontakte neu holen. */
  onFertig: () => void
}

export function Buchfenster({ onClose, onFertig }: Props) {
  const { t, i18n } = useTranslation()
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  const [anbieter, setAnbieter] = useState('icloud')
  const [adresse, setAdresse] = useState('')
  const [benutzer, setBenutzer] = useState('')
  const [passwort, setPasswort] = useState('')
  const [gefunden, setGefunden] = useState<GefundenesBuch[] | null>(null)
  const [gewaehlt, setGewaehlt] = useState<Set<string>>(new Set())

  const [zugaenge, setZugaenge] = useState<Zugang[]>([])
  const [zugangId, setZugangId] = useState('')
  useEffect(() => {
    void api
      .holen<Zugang[]>('/api/mailoauth/zugaenge')
      .then(setZugaenge)
      .catch(() => setZugaenge([]))
  }, [])
  const passende = zugaenge.filter((z) => z.art === 'google')
  const brauchbare = passende.filter((z) => z.kann_adressbuch)
  useEffect(() => {
    if (anbieter === 'google' && !zugangId && brauchbare.length) setZugangId(brauchbare[0].id)
  }, [anbieter, zugangId, brauchbare])
  const gewaehlterZugang = passende.find((z) => z.id === zugangId)

  /** ⚠️ Der Server nennt eine Kennung, die Oberfläche übersetzt. */
  function melden(f: unknown) {
    const kennung = f instanceof ApiFehler ? f.detail : ''
    const schluessel = `kontakte.buch_fehler_${kennung}`
    setFehler(i18n.exists(schluessel) ? t(schluessel) : t('kontakte.buch_fehler_allgemein'))
    setLaeuft(false)
  }

  const zugang = () => ({
    art: anbieter,
    adresse,
    benutzer,
    passwort,
    oauth_zugang_id: anbieter === 'google' ? zugangId : '',
  })

  async function suchen() {
    setLaeuft(true)
    setFehler('')
    try {
      const raus = await api.senden<GefundenesBuch[]>('/api/adressbuecher/pruefen', zugang())
      setGefunden(raus)
      // Ab Werk alle, die noch nicht dastehen; wer weniger will, hakt ab.
      setGewaehlt(new Set(raus.filter((b) => !b.schon_verbunden).map((b) => b.url)))
      if (raus.length === 0) setFehler(t('kontakte.buch_fehler_keine_gefunden'))
    } catch (f) {
      melden(f)
      return
    }
    setLaeuft(false)
  }

  async function verbinden() {
    setLaeuft(true)
    setFehler('')
    try {
      await api.senden('/api/adressbuecher/verbinden', {
        ...zugang(),
        auswahl: (gefunden ?? []).filter((b) => gewaehlt.has(b.url)),
      })
      onFertig()
      onClose()
    } catch (f) {
      melden(f)
    }
  }

  const bereit = gefunden !== null && gewaehlt.size > 0
  const pruefbar =
    anbieter === 'google'
      ? Boolean(zugangId && gewaehlterZugang?.kann_adressbuch)
      : Boolean(benutzer.trim() && passwort && (anbieter === 'icloud' || adresse.trim()))

  return (
    <Dialog
      open
      width={540}
      title={
        <span className="flex items-center gap-2">
          {t('kontakte.buch_verbinden')}
          <Badge tone="warning">{t('kontakte.beta')}</Badge>
        </span>
      }
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant="primary"
            disabled={!bereit || laeuft}
            loading={laeuft && gefunden !== null}
            onClick={() => void verbinden()}
          >
            {t('kontakte.buch_verbinden_knopf')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {/* ⚠️ Der eine Satz, auf dem die Beta ruht: nexmail liest nur. */}
        <p className="text-[12px] leading-relaxed text-fg-4">{t('kontakte.buch_verbinden_text')}</p>

        <Select
          label={t('kontakte.buch_anbieter')}
          value={anbieter}
          onChange={(e) => {
            setAnbieter(e.target.value)
            setGefunden(null)
            setFehler('')
          }}
        >
          <option value="icloud">{t('kontakte.buch_anbieter_icloud')}</option>
          {/* ⚠️ Nur wählbar, wenn es eine Google-Zustimmung gibt; sonst
              führte der Klick in eine Fehlermeldung statt zu einem Weg. */}
          <option value="google" disabled={passende.length === 0}>
            {passende.length
              ? t('kontakte.buch_anbieter_google')
              : t('kontakte.buch_anbieter_google_fehlt')}
          </option>
          <option value="andere">{t('kontakte.buch_anbieter_andere')}</option>
        </Select>

        {anbieter === 'google' && (
          <>
            <Select
              label={t('kontakte.buch_google_konto')}
              value={zugangId}
              onChange={(e) => setZugangId(e.target.value)}
            >
              {passende.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.adresse || z.id}
                </option>
              ))}
            </Select>
            {/* ⚠️ Eine Zustimmung ohne den Kontakte-Bereich ist keine
                Sackgasse mit Fehlermeldung, sondern ein benannter Weg. */}
            {gewaehlterZugang && !gewaehlterZugang.kann_adressbuch && (
              <p className="text-[12px] leading-relaxed text-warning">
                {t('kontakte.buch_google_bereich_fehlt')}
              </p>
            )}
            <p className="text-[12px] leading-relaxed text-fg-4">{t('kontakte.buch_google_api')}</p>
          </>
        )}

        {anbieter === 'andere' && (
          <Input
            label={t('kontakte.buch_adresse')}
            value={adresse}
            onChange={(e) => setAdresse(e.target.value)}
            placeholder="https://carddav.example.com/dav/"
          />
        )}
        {anbieter !== 'google' && (
          <>
            <Input
              label={t('kontakte.buch_benutzer')}
              value={benutzer}
              onChange={(e) => setBenutzer(e.target.value)}
              placeholder="name@example.com"
            />
            <Input
              label={t('kontakte.buch_passwort')}
              type="password"
              value={passwort}
              onChange={(e) => setPasswort(e.target.value)}
              hint={anbieter === 'icloud' ? t('kontakte.buch_icloud_hinweis') : undefined}
            />
          </>
        )}

        <div>
          <Button
            variant="secondary"
            size="sm"
            disabled={!pruefbar || laeuft}
            loading={laeuft && gefunden === null}
            onClick={() => void suchen()}
          >
            {t('kontakte.buch_pruefen')}
          </Button>
        </div>

        {gefunden !== null && gefunden.length > 0 && (
          <div className="flex flex-col gap-2 rounded-md border border-line p-3">
            <span className="text-[12px] font-medium text-fg-2">{t('kontakte.buch_gefunden')}</span>
            {gefunden.map((b) => (
              <Checkbox
                key={b.url}
                label={b.name}
                description={b.schon_verbunden ? t('kontakte.buch_schon_verbunden') : undefined}
                disabled={b.schon_verbunden}
                checked={gewaehlt.has(b.url)}
                onCheckedChange={(an) =>
                  setGewaehlt((alt) => {
                    const neu = new Set(alt)
                    if (an) neu.add(b.url)
                    else neu.delete(b.url)
                    return neu
                  })
                }
              />
            ))}
            <span className="text-[11px] leading-relaxed text-fg-4">
              {t('kontakte.buch_gefunden_hinweis')}
            </span>
          </div>
        )}

        {fehler && <p className="text-[12px] text-danger">{fehler}</p>}
      </div>
    </Dialog>
  )
}
