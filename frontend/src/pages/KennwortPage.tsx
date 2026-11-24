/* Kennwort vergessen — die beiden Seiten dazu.
 *
 * ⚠️ **Die Antwort ist immer dieselbe.** Ob es den Namen gibt, ob dort eine
 * Adresse hinterlegt ist, ob der Postausgang läuft: Hier steht danach genau
 * ein Satz, und der sagt nichts darüber aus. Wer hier einen Unterschied sehen
 * kann, kann Namen durchprobieren.
 *
 * ⚠️ **Der Weg hierher steht auf der Anmeldeseite, nicht im Menü.** Wer sein
 * Kennwort vergessen hat, kommt nicht bis ins Menü.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MailCheck } from 'lucide-react'
import { api } from '../api/client'
import { Button, Input } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import { Torbogen } from '../components/Torbogen'
import { EMAIL_MAX, PASSWORD_MIN } from '../vendor/nexkonten/konten'

/** Schritt 1: den Link anfordern. */
export function VergessenPage({
  modus,
  aufModus,
  aufZurueck,
}: {
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufZurueck: () => void
}) {
  const { t } = useTranslation()
  const [benutzername, setBenutzername] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [gesendet, setGesendet] = useState(false)
  /* Ohne Postausgang gibt es keinen Link per Mail; dann steht hier der Weg über den Betreiber (Kontenmodul). */
  const [perMail, setPerMail] = useState<boolean | null>(null)
  useEffect(() => {
    api
      .holen<{ per_mail: boolean }>('/api/auth/kennwort-vergessen')
      .then((s) => setPerMail(s.per_mail))
      .catch(() => setPerMail(true))
  }, [])

  async function abschicken() {
    if (!benutzername.trim()) return
    setLaeuft(true)
    try {
      await api.senden('/api/auth/kennwort-vergessen', { benutzername: benutzername.trim() })
    } catch {
      /* ⚠️ **Auch ein Fehler ändert die Anzeige nicht.** Ein sichtbarer
         Unterschied zwischen „ging“ und „ging nicht“ wäre genau die Auskunft,
         die der Server sich verkneift. Einzig 429 der Bremse kommt durch — den
         merkt man ohnehin an der Wartezeit. */
    } finally {
      setLaeuft(false)
      setGesendet(true)
    }
  }

  return (
    <Torbogen modus={modus} aufModus={aufModus} titel={t('account.forgotTitle')}>
      {perMail === false ? (
        <div className="flex flex-col gap-4">
          <p className="mb-0 text-[13px] text-fg-2">{t('account.forgotNoMail')}</p>
          <Button variant="ghost" onClick={aufZurueck}>
            {t('kennwort.zur_anmeldung')}
          </Button>
        </div>
      ) : gesendet ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3 rounded-lg border border-line bg-surface-3 p-3">
            <MailCheck className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
            <p className="mb-0 text-[13px] text-fg-2">{t('account.forgotSent')}</p>
          </div>
          <Button variant="ghost" onClick={aufZurueck}>
            {t('kennwort.zur_anmeldung')}
          </Button>
        </div>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            void abschicken()
          }}
        >
          <p className="mb-0 text-[13px] text-fg-3">{t('kennwort.vergessen_hinweis')}</p>
          <Input
            label={t('account.login')}
            value={benutzername}
            autoFocus
            autoComplete="username"
            maxLength={EMAIL_MAX}
            onChange={(e) => setBenutzername(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={laeuft || !benutzername.trim()}>
            {t('account.forgotSubmit')}
          </Button>
          <Button variant="ghost" onClick={aufZurueck}>
            {t('kennwort.zur_anmeldung')}
          </Button>
        </form>
      )}
    </Torbogen>
  )
}

/** Schritt 2: das neue Kennwort setzen. */
export function KennwortNeuPage({
  schluessel,
  modus,
  aufModus,
  aufFertig,
}: {
  schluessel: string
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufFertig: () => void
}) {
  const { t } = useTranslation()
  const [passwort, setPasswort] = useState('')
  const [wiederholung, setWiederholung] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  /* Für wen der Link gilt; ein Link, der nicht gilt, sagt das gleich statt erst nach dem Tippen. */
  const [fuer, setFuer] = useState<{ benutzername: string; min_passwort: number } | null>(null)
  const [hinfaellig, setHinfaellig] = useState('')
  const [fertig, setFertig] = useState(false)
  useEffect(() => {
    api
      .holen<{ benutzername: string; min_passwort: number }>(`/api/auth/kennwort-neu/${encodeURIComponent(schluessel)}`)
      .then(setFuer)
      .catch((f) => setHinfaellig(servermeldung(f, t('account.error.reset_invalid'))))
  }, [schluessel, t])

  const mindestens = fuer?.min_passwort ?? PASSWORD_MIN
  const passtNicht = wiederholung.length > 0 && passwort !== wiederholung

  async function abschicken() {
    setFehler('')
    setLaeuft(true)
    try {
      await api.senden('/api/auth/kennwort-neu', { schluessel, passwort })
      setFertig(true)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      setLaeuft(false)
    }
  }

  if (hinfaellig || fertig) {
    return (
      <Torbogen modus={modus} aufModus={aufModus} titel={t('account.resetTitle')}>
        <div className="flex flex-col gap-4">
          <p role={hinfaellig ? 'alert' : undefined} className="mb-0 text-[13px] text-fg-2">
            {hinfaellig || t('kennwort.gesetzt')}
          </p>
          <Button variant={fertig ? 'primary' : 'ghost'} onClick={aufFertig}>
            {t('kennwort.zur_anmeldung')}
          </Button>
        </div>
      </Torbogen>
    )
  }

  return (
    <Torbogen
      modus={modus}
      aufModus={aufModus}
      titel={t('account.resetTitle')}
      untertitel={fuer ? t('kennwort.neu_fuer', { name: fuer.benutzername }) : undefined}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void abschicken()
        }}
      >
        <Input
          type="password"
          label={t('account.newPassword')}
          hint={t('account.passwordRules', { minimum: mindestens })}
          value={passwort}
          autoFocus
          autoComplete="new-password"
          onChange={(e) => setPasswort(e.target.value)}
        />
        {/* ⚠️ Ein Tippfehler im neuen Kennwort sperrt aus, und zwar sofort —
            man ist ja gerade dabei, sich auszusperren. Deshalb zweimal. */}
        <Input
          type="password"
          label={t('account.passwordRepeat')}
          value={wiederholung}
          autoComplete="new-password"
          error={passtNicht ? t('account.passwordMismatch') : undefined}
          onChange={(e) => setWiederholung(e.target.value)}
        />
        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          disabled={laeuft || passwort.length < mindestens || passtNicht || !wiederholung}
        >
          {t('kennwort.setzen')}
        </Button>
      </form>
    </Torbogen>
  )
}
