/* Sicherheit — wer ist gerade angemeldet, und womit.
 *
 * ⚠️ **Angemeldete Geräte gehören sichtbar und einzeln kündbar.** Genau
 * dafür liegen die Sitzungen im Server und nicht im Token: „auf allen Geräten
 * abmelden" wirkt sofort. Eine Anwendung, die alle Postfächer hält, muss
 * zeigen können, wer sie gerade offen hat.
 *
 * ⚠️ **Die Zahl der übrigen Wiederherstellungscodes steht hier.** Sonst
 * erfährt man sie erst, wenn keiner mehr da ist — und dann ist es zu spät.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, LogOut, Monitor, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../api/client'
import type { Ich } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Oauthzugaenge } from '../components/Oauthzugaenge'
import { Badge, Button, Dialog, IconButton, Input } from '../ds'
import { ZweiterFaktor } from '../components/ZweiterFaktor'
import { appPfad } from '../lib/basis'
import { servermeldung } from '../lib/servermeldung'

interface Geraet {
  id: string
  geraet: string
  adresse: string
  angelegt: string
  zuletzt_gesehen: string
  aktuell: boolean
}

export function Sicherheit({
  ich,
  ichNeuLaden,
}: {
  ich: Ich | null
  ichNeuLaden?: () => void
}) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [geraete, setGeraete] = useState<Geraet[] | null>(null)
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    setGeraete(await api.holen<Geraet[]>('/api/sitzungen'))
  }, [])

  useEffect(() => {
    void laden().catch(() => setGeraete([]))
  }, [laden])

  async function mit<T>(tun: () => Promise<T>) {
    setFehler('')
    try {
      const ergebnis = await tun()
      await laden()
      // ⚠️ **Auch den angemeldeten Benutzer.** Der zweite Faktor, die Zahl der
      // Wiederherstellungscodes, der Anzeigename — alles steckt in `ich`, und
      // das kommt von oben. Ohne diese Zeile sieht man seine eigene Änderung
      // erst nach F5.
      ichNeuLaden?.()
      return ergebnis
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return null
    }
  }

  const [einschalten, setEinschalten] = useState(false)
  const [ausschalten, setAusschalten] = useState(false)
  const [kennwort, setKennwort] = useState('')

  /* Welche Anbieter es gibt und welche schon an diesem Konto hängen. */
  const [anbieter, setAnbieter] = useState<Array<{ kuerzel: string; anzeigename: string }>>([])
  const [verknuepfungen, setVerknuepfungen] = useState<
    Array<{ id: number; issuer: string; anzeigename: string; kuerzel: string }>
  >([])
  useEffect(() => {
    api
      .holen<Array<{ kuerzel: string; anzeigename: string }>>('/api/oidc/knoepfe')
      .then(setAnbieter)
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    api
      .holen<Array<{ id: number; issuer: string; anzeigename: string; kuerzel: string }>>(
        '/api/oidc/meine',
      )
      .then(setVerknuepfungen)
      .catch(() => undefined)
  }, [geraete])

  const wenige = (ich?.offene_codes ?? 0) <= 3

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {/* --- Zweiter Faktor --------------------------------------------- */}
      <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-4">
        <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('sicherheit.zwei_faktor')}</h2>

        <div className="flex flex-wrap items-center gap-2 text-[13px] text-fg-2">
          {ich?.zwei_faktor_aktiv ? (
            <ShieldCheck className="size-4 shrink-0 text-success" />
          ) : (
            <ShieldAlert className="size-4 shrink-0 text-warning" />
          )}
          <span>
            {ich?.zwei_faktor_aktiv ? t('sicherheit.aktiv') : t('sicherheit.nicht_aktiv')}
          </span>
        </div>

        {ich?.zwei_faktor_aktiv && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={wenige ? 'warning' : 'neutral'}>
              {t('sicherheit.codes_uebrig', { count: ich?.offene_codes ?? 0 })}
            </Badge>
            {/* ⚠️ Kein leiser Hinweis: Wer keine Codes mehr hat und sein Handy
                verliert, kommt nur noch über den Nothammer in der compose-Datei
                hinein. */}
            {wenige && (
              <span className="text-[12px] text-warning">{t('sicherheit.codes_knapp')}</span>
            )}
          </div>
        )}

        {/* ⚠️ **Die Anwendung sagt, was der ausgeschaltete Faktor kostet.**
            Er ist seit dem 01.09.2026 eine Wahl — und eine Wahl ohne Folgen
            ausgesprochen ist keine. Der Satz steht hier und nicht in einer
            README, die niemand aufschlägt. */}
        {!ich?.zwei_faktor_aktiv && (
          <p className="mb-0 text-[12px] text-fg-3">{t('sicherheit.faktor_empfehlung')}</p>
        )}

        <div className="flex flex-wrap gap-2 pt-1">
          {ich?.zwei_faktor_aktiv ? (
            <Button size="sm" variant="ghost" onClick={() => setAusschalten(true)}>
              {t('sicherheit.faktor_ausschalten')}
            </Button>
          ) : (
            <Button size="sm" variant="primary" onClick={() => setEinschalten(true)}>
              {t('sicherheit.faktor_einschalten')}
            </Button>
          )}
        </div>
      </section>

      {einschalten && (
        <Dialog open title={t('sicherheit.faktor_einschalten')} onClose={() => setEinschalten(false)}>
          <ZweiterFaktor
            benutzername={ich?.benutzername ?? ''}
            aufAbbrechen={() => setEinschalten(false)}
            aufFertig={() => {
              setEinschalten(false)
              void laden()
            }}
          />
        </Dialog>
      )}

      {ausschalten && (
        <Dialog open title={t('sicherheit.faktor_ausschalten')} onClose={() => setAusschalten(false)}>
          <div className="flex flex-col gap-4">
            <p className="mb-0 text-[13px] text-fg-2">{t('sicherheit.faktor_aus_warnung')}</p>
            <Input
              label={t('sicherheit.faktor_aus_frage')}
              type="password"
              autoComplete="current-password"
              value={kennwort}
              onChange={(e) => setKennwort(e.target.value)}
            />
            {fehler && <p className="mb-0 text-[13px] text-danger">{fehler}</p>}
            <div className="flex gap-2">
              <Button
                variant="danger"
                disabled={!kennwort}
                onClick={async () => {
                  const ok = await mit(() =>
                    api.senden('/api/auth/zwei-faktor/aus', { passwort: kennwort }),
                  )
                  if (ok !== null) {
                    setAusschalten(false)
                    setKennwort('')
                  }
                }}
              >
                {t('sicherheit.faktor_ausschalten')}
              </Button>
              <Button variant="ghost" onClick={() => setAusschalten(false)}>
                {t('aktion.abbrechen')}
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {/* --- Anmelde-Anbieter ---------------------------------------------
          ⚠️ **Ein Knopf, kein versteckter Aufruf.** Vorher führte der Weg zum
          Verknüpfen nur über eine Adresse, die man kennen musste
          (`/api/oidc/<kürzel>/start`). Der Betreiber am 01.09.2026: „Ist die Frage ob
          man einen Verknüpfen button einfach ins profil macht" — ja, denn eine
          Handlung, die man nicht sieht, gibt es nicht. */}
      {anbieter.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('sicherheit.anbieter')}</h2>
          <p className="mb-0 text-[12px] text-fg-3">{t('sicherheit.anbieter_hinweis')}</p>

          <ul className="flex list-none flex-col gap-2 p-0">
            {anbieter.map((a) => {
              /* ⚠️ **Ueber das Kuerzel, nicht ueber den Anzeigenamen.** Der
                 ist frei waehlbar; das Kuerzel steckt in der Rueckkehr-Adresse
                 und ist eindeutig. Am 01.09.2026 stand hier der Anzeigename,
                 und eine bestehende Verknuepfung blieb unsichtbar, sobald der
                 Anbieter seinen Aussteller mit abschliessendem Schraegstrich
                 nennt — bei authentik der Normalfall. */
              const verknuepft = verknuepfungen.find((v) => v.kuerzel === a.kuerzel)
              return (
                <li
                  key={a.kuerzel}
                  className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-2.5"
                >
                  <KeyRound aria-hidden className="size-4 shrink-0 text-fg-4" />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">
                    {a.anzeigename}
                  </span>
                  {verknuepft ? (
                    <>
                      <Badge tone="accent">{t('sicherheit.verknuepft')}</Badge>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          void mit(() => api.loeschen(`/api/oidc/meine/${verknuepft.id}`))
                        }
                      >
                        {t('sicherheit.loesen')}
                      </Button>
                    </>
                  ) : (
                    /* ⚠️ Ein Verweis, kein fetch: Der Hinweg ist eine
                       Browser-Weiterleitung zum Anbieter. */
                    <a
                      href={appPfad(`/api/oidc/${a.kuerzel}/start`)}
                      className="rounded-md border border-line px-3 py-1 text-[12px] text-fg-1 no-underline transition-colors duration-[var(--dur-fast)] hover:border-accent"
                    >
                      {t('sicherheit.verknuepfen')}
                    </a>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {/* --- Google und Microsoft ---------------------------------------- */}
      {/* ⚠️ **Hier, nicht beim Postfach.** Eine Zustimmung gilt fuer Postfach
          UND Kalender; sie an einem der beiden aufzuhaengen hiesse, sie beim
          anderen zu verstecken. */}
      <Oauthzugaenge istBetreiber={Boolean(ich?.ist_betreiber)} />

      {/* --- Angemeldete Geräte ------------------------------------------ */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <h2 className="mb-0 flex-1 text-[13px] font-semibold text-fg-1">
            {t('sicherheit.geraete')}
          </h2>
          {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
        </div>

        {geraete === null ? (
          <div className="h-16" />
        ) : (
          <ul className="flex flex-col gap-2">
            {geraete.map((g) => (
              <li
                key={g.id}
                className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5"
              >
                <Monitor className="size-4 shrink-0 text-fg-4" />
                <div className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-[13px] text-fg-1">
                      {g.geraet || t('sicherheit.unbekanntes_geraet')}
                    </span>
                    {g.aktuell && <Badge tone="success">{t('sicherheit.dieses_geraet')}</Badge>}
                  </span>
                  <span className="block truncate font-mono text-[11px] text-fg-4">
                    {g.adresse} · {new Date(g.zuletzt_gesehen).toLocaleString(i18n.language)}
                  </span>
                </div>
                <IconButton
                  icon={<LogOut />}
                  label={t('sicherheit.beenden')}
                  size="sm"
                  // Die eigene Sitzung beendet man über „Abmelden", nicht hier
                  // — sonst sieht es aus wie ein Fehler.
                  disabled={g.aktuell}
                  onClick={() => void mit(() => api.loeschen(`/api/sitzungen/${g.id}`))}
                />
              </li>
            ))}
          </ul>
        )}

        <div>
          <Button
            variant="danger"
            iconLeft={<LogOut className="size-4" />}
            disabled={(geraete?.length ?? 0) <= 1}
            onClick={() =>
              void (async () => {
                const ja = await fragen({
                  titel: t('sicherheit.alle_beenden'),
                  text: t('sicherheit.alle_beenden_sicher'),
                  knopf: t('sicherheit.alle_beenden'),
                  gefaehrlich: true,
                })
                if (ja !== true) return
                await mit(() => api.senden('/api/sitzungen/alle-beenden', {}))
              })()
            }
          >
            {t('sicherheit.alle_beenden')}
          </Button>
        </div>
      </section>

      {nachfrage}
    </div>
  )
}
