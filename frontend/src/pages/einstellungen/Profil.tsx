/* Einstellungen → Profil, wie in nexnotes: Bild, Name, Mailadresse, Sprache,
 * und darunter „Abmelden".
 *
 * ⚠️ **Die Mailadresse ist die Adresse für Kontosachen** (`kontaktadresse`),
 * nicht eines der Postfächer. Bis 0.30 stand sie oben unter Sicherheit; dort
 * hat nexnotes sie nicht, und wer beide Apps kennt, sucht sie im Profil.
 * ⚠️ **Ohne sie gibt es keinen Weg zurück** nach einem vergessenen Kennwort.
 * Deshalb steht die Warnung direkt unter dem Feld, sobald sie leer ist.
 *
 * ⚠️ **Die Sprache gilt in diesem Browser**, anders als in nexnotes, wo sie am
 * Konto hängt. nexmail merkt sie seit jeher im Browser (`i18n/index.ts`); der
 * Hinweis sagt das, sonst wirkt sie am zweiten Gerät kaputt.
 */
import { LogOut, ShieldAlert, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Ich } from '../../api/client'
import { Profilbild } from '../../components/Profilbild'
import { Button, Input, Select } from '../../ds'
import { SPRACHEN, spracheSetzen, type Sprachcode } from '../../i18n'
import { servermeldung } from '../../lib/servermeldung'
import { Karte } from './Karte'

export function Profil({
  ich,
  ichNeuLaden,
  aufAbmelden,
}: {
  ich: Ich | null
  ichNeuLaden?: () => void
  aufAbmelden: () => void
}) {
  const { t, i18n } = useTranslation()
  const [name, setName] = useState(ich?.anzeigename ?? '')
  const [adresse, setAdresse] = useState(ich?.kontaktadresse ?? '')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [erledigt, setErledigt] = useState('')

  /* ⚠️ Nachziehen, wenn `ich` später eintrifft — beim ersten Rendern ist es
     null, und ein Feld, das dann leer bleibt, sähe aus wie „nichts gesetzt". */
  useEffect(() => {
    setName(ich?.anzeigename ?? '')
    setAdresse(ich?.kontaktadresse ?? '')
  }, [ich?.anzeigename, ich?.kontaktadresse])

  if (!ich) return null
  const person = ich

  async function tun(aktion: () => Promise<unknown>, meldung: string) {
    setLaeuft(true)
    setFehler('')
    setErledigt('')
    try {
      await aktion()
      setErledigt(meldung)
      ichNeuLaden?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  const unveraendert =
    name.trim() === person.anzeigename && adresse.trim() === (person.kontaktadresse ?? '')

  return (
    <div className="flex flex-col gap-5">
      <div aria-live="polite">
        {fehler && (
          <p role="alert" className="mb-0 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-[13px] text-danger">
            {fehler}
          </p>
        )}
        {erledigt && !fehler && (
          <p className="mb-0 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-[13px] text-success">
            {erledigt}
          </p>
        )}
      </div>

      <Karte id="profil" symbol={UserRound} titel={t('einstellungen.bereiche.profil.titel')}>
        <div className="flex flex-wrap items-center gap-3" data-testid="profil-bild">
          <Profilbild id={person.id} name={person.anzeigename} stand={person.profilbild} groesse={64} />
          <div className="flex flex-wrap gap-2">
            {/* Ein Label als Knopf: Das Dateifeld selbst ist unsichtbar, der
                Klick auf die Beschriftung öffnet die Auswahl. */}
            <label className="inline-flex h-[34px] cursor-pointer items-center rounded-md border border-line bg-surface-2 px-3 text-[13px] font-medium text-fg-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3">
              {person.profilbild ? t('profil.bild_aendern') : t('profil.bild_hinzufuegen')}
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                data-testid="profilbild-datei"
                disabled={laeuft}
                onChange={(e) => {
                  const datei = e.target.files?.[0]
                  e.target.value = ''
                  if (datei)
                    void tun(() => api.datei('/api/auth/ich/profilbild', datei), t('profil.bild_gespeichert'))
                }}
              />
            </label>
            {person.profilbild && (
              <Button
                variant="ghost"
                disabled={laeuft}
                onClick={() =>
                  void tun(() => api.loeschen('/api/auth/ich/profilbild'), t('profil.bild_entfernt'))
                }
              >
                {t('profil.bild_entfernen')}
              </Button>
            )}
          </div>
        </div>

        <form
          className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault()
            void tun(
              () =>
                api.aendern('/api/auth/ich/profil', {
                  anzeigename: name.trim(),
                  kontaktadresse: adresse.trim(),
                }),
              t('profil.gespeichert'),
            )
          }}
        >
          <Input
            label={t('profil.name')}
            value={name}
            maxLength={120}
            autoComplete="name"
            onChange={(e) => setName(e.target.value)}
          />
          <Input
            type="email"
            label={t('profil.mail')}
            placeholder="name@example.com"
            value={adresse}
            autoComplete="email"
            onChange={(e) => setAdresse(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={laeuft || unveraendert}>
            {t('aktion.speichern')}
          </Button>
        </form>

        <p className="mb-0 text-[12px] text-fg-3">
          {t('profil.rolle', {
            rolle: person.ist_betreiber ? t('profil.rolle_betreiber') : t('profil.rolle_benutzer'),
          })}
          {' · '}
          {t('sicherheit.kontaktadresse_hinweis')}
        </p>

        {!person.kontaktadresse && (
          <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft p-3 text-[12px] text-warning-text">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" />
            <span>{t('sicherheit.kontaktadresse_fehlt')}</span>
          </div>
        )}

        <Select
          label={t('profil.sprache')}
          hint={t('profil.sprache_hinweis')}
          value={i18n.language}
          onChange={(e) => void spracheSetzen(e.target.value as Sprachcode)}
          options={SPRACHEN.map((s) => ({ value: s.code, label: s.name }))}
        />
      </Karte>

      <Karte id="abmelden" symbol={LogOut} titel={t('profil.abmelden_titel')} text={t('profil.abmelden_text')}>
        <div>
          <Button iconLeft={<LogOut className="size-4" />} onClick={aufAbmelden}>
            {t('anmeldung.abmelden')}
          </Button>
        </div>
      </Karte>
    </div>
  )
}
