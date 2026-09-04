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
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MailCheck } from 'lucide-react'
import { api } from '../api/client'
import { Button, Input } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import { Torbogen } from '../components/Torbogen'

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
    <Torbogen modus={modus} aufModus={aufModus} titel={t('kennwort.vergessen_titel')}>
      {gesendet ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3 rounded-lg border border-line bg-surface-3 p-3">
            <MailCheck className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
            <p className="mb-0 text-[13px] text-fg-2">{t('kennwort.vergessen_gesendet')}</p>
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
            label={t('anmeldung.benutzername')}
            value={benutzername}
            autoFocus
            onChange={(e) => setBenutzername(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={laeuft || !benutzername.trim()}>
            {t('kennwort.link_anfordern')}
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

  const passtNicht = wiederholung.length > 0 && passwort !== wiederholung

  async function abschicken() {
    setFehler('')
    setLaeuft(true)
    try {
      await api.senden('/api/auth/kennwort-neu', { schluessel, passwort })
      aufFertig()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      setLaeuft(false)
    }
  }

  return (
    <Torbogen modus={modus} aufModus={aufModus} titel={t('kennwort.neu_titel')}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void abschicken()
        }}
      >
        <Input
          type="password"
          label={t('kennwort.neues')}
          value={passwort}
          autoFocus
          onChange={(e) => setPasswort(e.target.value)}
        />
        {/* ⚠️ Ein Tippfehler im neuen Kennwort sperrt aus, und zwar sofort —
            man ist ja gerade dabei, sich auszusperren. Deshalb zweimal. */}
        <Input
          type="password"
          label={t('kennwort.wiederholen')}
          value={wiederholung}
          hint={passtNicht ? t('kennwort.stimmt_nicht') : undefined}
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
          disabled={laeuft || !passwort || passtNicht || !wiederholung}
        >
          {t('kennwort.setzen')}
        </Button>
      </form>
    </Torbogen>
  )
}
