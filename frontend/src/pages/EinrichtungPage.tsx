/* Die erste Einrichtung — zwei Schritte.
 *
 * Schritt 1: Konto. Schritt 2: zweiter Faktor und die Wiederherstellungscodes.
 *
 * ⚠️ **Die Codes gibt es genau hier und nie wieder**, und deshalb kommt man
 * an diesem Schritt nicht mit einem Klick vorbei: Der Haken „Ich habe die
 * Codes gesichert" ist Pflicht. Das ist eine der wenigen Stellen, an denen
 * Reibung richtig ist — wer hier durchklickt, merkt es erst, wenn das Telefon
 * weg ist, und dann ist es zu spät.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Torbogen } from '../components/Torbogen'
import { Button, Input } from '../ds'
import { api } from '../api/client'
import type { KontoAntwort } from '../api/client'
import { servermeldung } from '../lib/servermeldung'

interface Props {
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufFertig: () => void
}

export function EinrichtungPage({ modus, aufModus, aufFertig }: Props) {
  const { t } = useTranslation()

  const [benutzername, setBenutzername] = useState('')
  const [anzeigename, setAnzeigename] = useState('')
  const [passwort, setPasswort] = useState('')
  const [wiederholung, setWiederholung] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  async function kontoAnlegen(e: React.FormEvent) {
    e.preventDefault()
    setFehler('')
    if (passwort !== wiederholung) {
      setFehler(t('einrichtung.passwort_ungleich'))
      return
    }
    setLaeuft(true)
    try {
      await api.senden<KontoAntwort>('/api/setup/konto', {
        benutzername: benutzername.trim(),
        passwort,
        anzeigename: anzeigename.trim(),
      })
      /* ⚠️ **Hier ist der Assistent zu Ende** (01.09.2026). Vorher kam ein
         zweiter Schritt mit QR-Code, aus dem man ohne Telefon nicht
         herauskam. Den zweiten Faktor schaltet jetzt jeder selbst ein, unter
         Einstellungen → Sicherheit. */
      aufFertig()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  // Der eine Satz, der den gesperrten Knopf erklärt. Reihenfolge = die
  // Reihenfolge der Felder, damit der Hinweis immer auf das nächste fehlende
  // zeigt und nicht hin und her springt.
  const grund = !benutzername
    ? t('einrichtung.grund_benutzername')
    : passwort.length < 10
      ? t('einrichtung.grund_kennwort_lang', { fehlen: 10 - passwort.length })
      : passwort !== wiederholung
        ? t('einrichtung.passwort_ungleich')
        : ''

  return (
    <Torbogen
      marke={t('einrichtung.schritt', { n: 1 })}
      titel={t('einrichtung.titel')}
      untertitel={t('einrichtung.untertitel')}
      modus={modus}
      aufModus={aufModus}
    >
      <form onSubmit={kontoAnlegen} className="flex flex-col gap-4">
        <Input
          label={t('einrichtung.benutzername')}
          hint={t('einrichtung.benutzername_hinweis')}
          value={benutzername}
          autoFocus
          autoComplete="username"
          onChange={(e) => setBenutzername(e.target.value)}
        />
        <Input
          label={t('einrichtung.anzeigename')}
          hint={t('einrichtung.anzeigename_optional')}
          value={anzeigename}
          autoComplete="name"
          onChange={(e) => setAnzeigename(e.target.value)}
        />
        {/* ⚠️ **Der Grund gehört an das Feld, nicht unter das Formular.**
            Er stand nur über dem gesperrten Knopf — der Betreiber hat ihn gelesen und
            nicht auf das Kennwort bezogen: „hier ist Ende, der Weiter-Knopf
            ist nicht anklickbar". Ein Hinweis, den man erst zuordnen muss,
            ist keiner. */}
        <Input
          label={t('einrichtung.passwort')}
          hint={t('einrichtung.passwort_hinweis')}
          error={
            passwort && passwort.length < 10
              ? t('einrichtung.grund_kennwort', { fehlen: 10 - passwort.length })
              : undefined
          }
          type="password"
          value={passwort}
          autoComplete="new-password"
          onChange={(e) => setPasswort(e.target.value)}
        />
        <Input
          label={t('einrichtung.passwort_wiederholen')}
          type="password"
          value={wiederholung}
          autoComplete="new-password"
          error={wiederholung && passwort !== wiederholung ? t('einrichtung.passwort_ungleich') : undefined}
          onChange={(e) => setWiederholung(e.target.value)}
        />

        {fehler && <Meldung text={fehler} />}

        {/* ⚠️ **Ein gesperrter Knopf muss sagen, warum.** Vorher stand er
            einfach grau da: Bei neun statt zehn Zeichen sieht das Formular
            fertig ausgefüllt aus, der Knopf reagiert nicht, und nichts
            erklärt es. Wer das trifft, hält nexmail für kaputt — und liegt
            damit nicht falsch. */}
        {grund && <p className="-mt-1 text-[13px] text-fg-3">{grund}</p>}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          fullWidth
          loading={laeuft}
          disabled={Boolean(grund)}
        >
          {t('einrichtung.weiter')}
        </Button>
      </form>
    </Torbogen>
  )
}

export function Meldung({ text }: { text: string }) {
  return (
    <p
      role="alert"
      className="mb-0 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-[13px] text-fg-1"
    >
      {text}
    </p>
  )
}
