/* Wer nexmail benutzen darf — der Reiter „Benutzer" in der Verwaltung.
 *
 * ⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
 * einzeln. nexmail ist der Mail-Client eines Haushalts, keine Plattform.
 *
 * ⚠️ **Was fehlt, steht oben — bevor jemand tippt.** Ohne Postausgang und
 * ohne öffentliche Adresse geht keine Einladung hinaus. Das erst beim
 * Absenden zu melden, hieße: Formular ausgefüllt, Fehler kassiert, und der
 * Weg zur Abhilfe liegt in einem anderen Reiter.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Mail, ShieldCheck, Trash2, UserPlus } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Badge, Button, Dialog, IconButton, Input } from '../ds'

interface BenutzerZeile {
  id: string
  benutzername: string
  anzeigename: string
  ist_betreiber: boolean
  zwei_faktor_aktiv: boolean
  angelegt: string
  postfaecher: number
}

interface EinladungsZeile {
  id: string
  benutzername: string
  anzeigename: string
  adresse: string
  laeuft_ab: string
  abgelaufen: boolean
}

interface Bestand {
  benutzer: BenutzerZeile[]
  einladungen: EinladungsZeile[]
  postausgang_da: boolean
  adresse_da: boolean
}

interface Umfang {
  postfaecher: number
  nachrichten: number
  kontakte: number
  regeln: number
  signaturen: number
}

export function Benutzerverwaltung() {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [bestand, setBestand] = useState<Bestand | null>(null)
  const [fehler, setFehler] = useState('')
  const [einladen, setEinladen] = useState(false)

  const laden = useCallback(async () => {
    try {
      setBestand(await api.holen<Bestand>('/api/benutzer'))
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function entfernen(person: BenutzerZeile) {
    setFehler('')
    let umfang: Umfang | null = null
    try {
      umfang = await api.holen<Umfang>(`/api/benutzer/${person.id}/umfang`)
    } catch {
      umfang = null
    }

    /* ⚠️ **Zahlen statt „alle Daten".** „Wirklich entfernen?" beantwortet man
       mit Ja, ohne nachzudenken. „3 Postfächer und 12.418 Nachrichten" liest
       man. Und der Satz sagt ausdrücklich, dass auf dem Mailserver nichts
       passiert — sonst traut sich niemand. */
    const ja = await fragen({
      titel: t('verwaltung.benutzer_entfernen'),
      text: umfang
        ? t('verwaltung.benutzer_entfernen_text', {
            name: person.anzeigename || person.benutzername,
            postfaecher: umfang.postfaecher,
            nachrichten: umfang.nachrichten.toLocaleString(i18n.language),
          })
        : t('verwaltung.benutzer_entfernen_kurz', {
            name: person.anzeigename || person.benutzername,
          }),
      knopf: t('verwaltung.benutzer_entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return

    try {
      await api.loeschen(`/api/benutzer/${person.id}`)
      await laden()
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    }
  }

  async function zuruecknehmen(e: EinladungsZeile) {
    const ja = await fragen({
      titel: t('verwaltung.einladung_zuruecknehmen'),
      text: t('verwaltung.einladung_zuruecknehmen_text', { name: e.benutzername }),
      knopf: t('verwaltung.einladung_zuruecknehmen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await api.loeschen(`/api/benutzer/einladungen/${e.id}`)
    await laden()
  }

  if (bestand === null) return <div className="h-24" />

  const bereit = bestand.postausgang_da && bestand.adresse_da

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {!bereit && (
        <div className="flex gap-3 rounded-lg border border-warning/40 bg-warning-soft p-4">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="min-w-0">
            <p className="mb-1 text-[13px] font-medium text-fg-1">
              {t('verwaltung.einladen_geht_nicht')}
            </p>
            <p className="mb-0 text-[13px] text-fg-2">
              {!bestand.postausgang_da
                ? t('verwaltung.kein_postausgang')
                : t('verwaltung.keine_adresse')}
            </p>
          </div>
        </div>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <h2 className="mb-0 flex-1 text-[13px] font-semibold text-fg-1">
            {t('verwaltung.benutzer')}
          </h2>
          {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
        </div>

        <ul className="flex list-none flex-col gap-2 p-0">
          {bestand.benutzer.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <p className="mb-0 truncate text-sm font-medium text-fg-1">
                    {p.anzeigename || p.benutzername}
                  </p>
                  {p.ist_betreiber && <Badge tone="accent">{t('verwaltung.betreiber')}</Badge>}
                  {p.zwei_faktor_aktiv && (
                    <ShieldCheck
                      className="size-3.5 shrink-0 text-success"
                      aria-label={t('sicherheit.aktiv')}
                    />
                  )}
                </div>
                <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{p.benutzername}</p>
                <p className="mb-0 truncate text-[11px] text-fg-4">
                  {t('verwaltung.postfaecher_zahl', { count: p.postfaecher })}
                </p>
              </div>

              {/* ⚠️ Der Betreiber hat keinen Papierkorb: Danach könnte niemand
                  mehr die Verwaltung öffnen, und aus der Anwendung heraus führt
                  kein Weg zurück. */}
              {!p.ist_betreiber && (
                <IconButton
                  icon={<Trash2 />}
                  label={t('verwaltung.benutzer_entfernen')}
                  onClick={() => void entfernen(p)}
                />
              )}
            </li>
          ))}
        </ul>
      </section>

      {bestand.einladungen.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">
            {t('verwaltung.offene_einladungen')}
          </h2>
          <ul className="flex list-none flex-col gap-2 p-0">
            {bestand.einladungen.map((e) => (
              <li
                key={e.id}
                className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
              >
                <Mail aria-hidden className="size-4 shrink-0 text-fg-4" />
                <div className="min-w-0 flex-1">
                  <p className="mb-0 truncate text-sm text-fg-1">{e.benutzername}</p>
                  <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{e.adresse}</p>
                </div>
                {/* ⚠️ Abgelaufene bleiben sichtbar — sonst verschwindet eine
                    Einladung lautlos und der Betreiber wartet auf jemanden,
                    der nie einen gültigen Link hatte. */}
                <Badge tone={e.abgelaufen ? 'warning' : 'neutral'}>
                  {e.abgelaufen
                    ? t('verwaltung.abgelaufen')
                    : t('verwaltung.gilt_bis', {
                        wann: new Date(e.laeuft_ab).toLocaleDateString(i18n.language),
                      })}
                </Badge>
                <IconButton
                  icon={<Trash2 />}
                  label={t('verwaltung.einladung_zuruecknehmen')}
                  onClick={() => void zuruecknehmen(e)}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div>
        <Button
          variant="primary"
          iconLeft={<UserPlus className="size-4" />}
          disabled={!bereit}
          onClick={() => setEinladen(true)}
        >
          {t('verwaltung.einladen')}
        </Button>
      </div>

      {einladen && (
        <Einladungsfenster
          aufSchliessen={() => setEinladen(false)}
          aufFertig={() => {
            setEinladen(false)
            void laden()
          }}
        />
      )}

      {nachfrage}
    </div>
  )
}

function Einladungsfenster({
  aufSchliessen,
  aufFertig,
}: {
  aufSchliessen: () => void
  aufFertig: () => void
}) {
  const { t } = useTranslation()
  const [benutzername, setBenutzername] = useState('')
  const [adresse, setAdresse] = useState('')
  const [anzeigename, setAnzeigename] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  async function abschicken() {
    setFehler('')
    setLaeuft(true)
    try {
      await api.senden('/api/benutzer/einladungen', {
        benutzername: benutzername.trim(),
        adresse: adresse.trim(),
        anzeigename: anzeigename.trim(),
      })
      aufFertig()
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Dialog open title={t('verwaltung.einladen')} onClose={aufSchliessen}>
      <div className="flex flex-col gap-4">
        <Input
          label={t('verwaltung.einladung_adresse')}
          hint={t('verwaltung.einladung_adresse_hinweis')}
          placeholder="name@example.com"
          value={adresse}
          onChange={(e) => setAdresse(e.target.value)}
        />
        <Input
          label={t('verwaltung.einladung_benutzername')}
          hint={t('verwaltung.einladung_benutzername_hinweis')}
          value={benutzername}
          onChange={(e) => setBenutzername(e.target.value)}
        />
        <Input
          label={t('verwaltung.einladung_anzeigename')}
          placeholder={benutzername}
          value={anzeigename}
          onChange={(e) => setAnzeigename(e.target.value)}
        />

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        <div className="flex gap-2">
          <Button
            variant="primary"
            loading={laeuft}
            disabled={!benutzername.trim() || !adresse.includes('@')}
            onClick={() => void abschicken()}
          >
            {t('verwaltung.einladung_abschicken')}
          </Button>
          <Button variant="ghost" onClick={aufSchliessen}>
            {t('aktion.abbrechen')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
