/* Die Seite hinter dem Link aus der Einladungsmail.
 *
 * ⚠️ **Die einzige Seite, die ohne Anmeldung etwas anlegt.** Wer hier landet,
 * hat noch kein Konto — der Schlüssel aus der Mail ist der ganze Nachweis.
 *
 * ⚠️ **Ein Kennwort und sonst nichts.** Kein zweiter Faktor, kein
 * Postfach-Assistent, keine Tour. Das ist die erste Minute, die jemand mit
 * nexmail verbringt; alles, was hier steht, muss er beantworten können, ohne
 * etwas zu wissen. Den zweiten Faktor schaltet er später selbst ein.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { appPfad } from '../lib/basis'
import { Torbogen } from '../components/Torbogen'
import { Button, Input } from '../ds'
import { Meldung } from './EinrichtungPage'

interface Vorschau {
  benutzername: string
  anzeigename: string
}

export function EinladungPage({
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
  const [vorschau, setVorschau] = useState<Vorschau | null>(null)
  const [hinfaellig, setHinfaellig] = useState('')
  const [passwort, setPasswort] = useState('')
  const [wiederholung, setWiederholung] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  /* Die Anbieter, über die man die Einladung auch annehmen kann.
     ⚠️ Der Schlüssel wird dabei **nicht** gebraucht: nexmail findet die offene
     Einladung über die bestätigte Adresse, die der Anbieter meldet. */
  const [anbieter, setAnbieter] = useState<Array<{ kuerzel: string; anzeigename: string }>>([])
  useEffect(() => {
    api
      .holen<Array<{ kuerzel: string; anzeigename: string }>>('/api/oidc/knoepfe')
      .then(setAnbieter)
      .catch(() => undefined)
  }, [])

  const holen = useCallback(async () => {
    try {
      setVorschau(await api.holen<Vorschau>(`/api/einladung/${encodeURIComponent(schluessel)}`))
    } catch (f) {
      setHinfaellig(
        f instanceof ApiFehler && f.detail ? f.detail : t('einladung.ungueltig_fallback'),
      )
    }
  }, [schluessel, t])

  useEffect(() => {
    void holen()
  }, [holen])

  async function annehmen(e: React.FormEvent) {
    e.preventDefault()
    setFehler('')
    if (passwort !== wiederholung) {
      setFehler(t('einrichtung.passwort_ungleich'))
      return
    }
    setLaeuft(true)
    try {
      await api.senden(`/api/einladung/${encodeURIComponent(schluessel)}`, { passwort })
      // ⚠️ Die Adresse aufräumen, bevor die App startet: Sonst steht der
      // Schlüssel weiter im Verlauf des Browsers und im Verlaufsspeicher.
      // ⚠️ Mit Vorbau — sonst springt der Browser aus der Anwendung heraus
      // auf die Wurzel der Domain.
      window.history.replaceState(null, '', appPfad('/'))
      aufFertig()
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setLaeuft(false)
    }
  }

  if (hinfaellig) {
    return (
      <Torbogen
        marke="nexmail"
        titel={t('einladung.ungueltig_titel')}
        untertitel={hinfaellig}
        modus={modus}
        aufModus={aufModus}
      >
        <Button
          fullWidth
          onClick={() => {
            window.history.replaceState(null, '', appPfad('/'))
            aufFertig()
          }}
        >
          {t('einladung.zur_anmeldung')}
        </Button>
      </Torbogen>
    )
  }

  if (!vorschau) {
    return <div className="h-full bg-canvas" />
  }

  /* ⚠️ Dieselben Sätze wie in der Ersteinrichtung — und dieselben Schlüssel.
     Beim ersten Anlauf standen hier drei erfundene Namen, und die Oberfläche
     zeigte roh „einrichtung.grund_passwort". */
  const grund = !passwort
    ? t('einrichtung.grund_kennwort')
    : passwort.length < 10
      ? t('einrichtung.grund_kennwort_lang', { fehlen: 10 - passwort.length })
      : passwort !== wiederholung
        ? t('einrichtung.passwort_ungleich')
        : ''

  return (
    <Torbogen
      marke="nexmail"
      titel={t('einladung.titel', { name: vorschau.anzeigename })}
      untertitel={t('einladung.untertitel', { name: vorschau.benutzername })}
      modus={modus}
      aufModus={aufModus}
    >
      <form onSubmit={annehmen} className="flex flex-col gap-4">
        <Input
          label={t('einrichtung.passwort')}
          type="password"
          autoComplete="new-password"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
        />
        <Input
          label={t('einrichtung.passwort_wiederholen')}
          type="password"
          autoComplete="new-password"
          value={wiederholung}
          onChange={(e) => setWiederholung(e.target.value)}
        />

        {fehler && <Meldung text={fehler} />}
        {/* ⚠️ Der Grund steht am Feld und nicht am gesperrten Knopf — sonst
            sucht man ihn dort, wo nichts passiert. */}
        {grund && <p className="-mt-1 text-[13px] text-fg-3">{grund}</p>}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          fullWidth
          loading={laeuft}
          disabled={Boolean(grund)}
        >
          {t('einladung.loslegen')}
        </Button>
      </form>

      {/* ⚠️ **Beide Wege nebeneinander, nicht statt einander.** Der Betreiber am
          01.09.2026: „nicht jeder hat ein authentik konto" — eben. Wer keins
          hat, vergibt ein Kennwort wie bisher; wer eins hat, spart es sich und
          bekommt ein Konto **ohne** Kennwort. Ein ungenutztes Kennwort ist das,
          welches schwach ist. */}
      {anbieter.length > 0 && (
        <div className="mt-5 flex flex-col gap-2 border-t border-line-subtle pt-5">
          <p className="mb-0 text-center text-[12px] text-fg-4">{t('einladung.oder')}</p>
          {anbieter.map((a) => (
            <a
              key={a.kuerzel}
              href={appPfad(`/api/oidc/${a.kuerzel}/start`)}
              className="flex h-[var(--control-h-lg)] items-center justify-center gap-2 rounded-md border border-line bg-surface-2 text-sm font-medium text-fg-1 no-underline transition-colors duration-[var(--dur-fast)] hover:border-accent"
            >
              <KeyRound aria-hidden className="size-4" />
              {t('oidc.anmelden_mit', { name: a.anzeigename })}
            </a>
          ))}
        </div>
      )}
    </Torbogen>
  )
}
