/* Verwaltung → Anmeldung: drei Karten untereinander, wie in jeder nex-App.
 * Reihenfolge, Wortlaut und Verhalten sind überall gleich (Wortlaute nur aus dem
 * Anmeldemodul, `oidc.*`), die Bauteile (Karte, Schalter, Feld, Knopf, Rückfrage) sind die von nexmail.
 *
 * 1. Anmeldung: „Anmeldung mit Passwort“ (gesperrt, solange kein Anbieter aktiv ist) und die öffentliche Adresse.
 *    Einen Schalter „Zweiten Faktor verlangen“ gibt es nicht: In nexmail ist der zweite Faktor eine Wahl jedes Kontos.
 * 2. Anmeldeanbieter: die Liste mit Marken und Ziehgriff, das Formular als Dialog.
 * 3. authentik in einem Schritt: Adresse, Token, „Einrichten“, der Blueprint, die Schritte mit dem Grund eines
 *    Fehlers. Ohne öffentliche Adresse schlägt die Karte die des Browsers vor und trägt nichts Geratenes ein.
 *
 * ⚠️ **Ab Werk ist die Liste leer, und dann ändert sich nichts.** Keine Knöpfe auf der Anmeldeseite, keine offenen
 * Adressen.
 */
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy, Download, GripVertical, KeyRound, Pencil, Trash2, X } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { Badge, Button, Dialog, IconButton, Input, Switch } from '../ds'
import { BASIS } from '../lib/basis'
import { servermeldung } from '../lib/servermeldung'
import {
  authentikIssuerChange,
  authentikProposal,
  authentikProxyWarning,
  authentikReasonKey,
  authentikRedirect,
  authentikStale,
  authentikStepKey,
  oidcErrorKey,
  oidcFormErrorKey,
  slugFromLabel,
  type AuthentikAddress,
} from '../vendor/nexoidc/oidc'

export interface Anbieter {
  id: number
  slug: string
  label: string
  issuer: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
  managed: string
  redirect_uri: string
  registered_redirect_uri: string
  redirect_stale: boolean
  links: number
  editable: boolean
}

interface Schritt {
  key: string
  ok: boolean
  reason?: string
  status?: number
}

interface Ergebnis {
  ok: boolean
  steps: Schritt[]
  count?: number
  address?: AuthentikAddress | null
}

/** Die Rückfrage beim Speichern der öffentlichen Adresse (409 `public_url_change`). */
interface Adressfrage {
  count: number
  address: string
  hand: number
}

function adressfrageAus(fehler: unknown): Adressfrage | null {
  if (!(fehler instanceof ApiFehler) || fehler.status !== 409 || fehler.detail !== 'public_url_change') return null
  const w = fehler.werte as Partial<Adressfrage>
  return { count: Number(w.count ?? 0), address: String(w.address ?? ''), hand: Number(w.hand ?? 0) }
}

/** Ein Fehler einer Anmelde-Route als Satz: Kennungen des Moduls aus dessen Wortlauten, der Rest wie überall. */
function useDeuten() {
  const { t } = useTranslation()
  return useCallback(
    (fehler: unknown): string => {
      if (fehler instanceof ApiFehler) {
        if (fehler.detail === 'public_url_invalid') return t('oidc.authentik.why.unusable')
        if (fehler.detail === 'public_url_needed') return t('oidc.authentik.why.public_url_needed')
        const schluessel = oidcFormErrorKey(fehler.detail) ?? oidcErrorKey(fehler.detail)
        if (schluessel) return t(schluessel)
      }
      return servermeldung(fehler, t('anmeldung.fehler_allgemein'))
    },
    [t],
  )
}

function Karte({ titel, text, kennung, children }: { titel: string; text?: string; kennung: string; children: ReactNode }) {
  return (
    <section
      aria-labelledby={kennung}
      data-testid={kennung}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface-1 px-4 py-4"
    >
      <div>
        <h3 id={kennung} className="mb-1 text-sm font-semibold text-fg-1">
          {titel}
        </h3>
        {text && <p className="mb-0 text-[13px] text-fg-3">{text}</p>}
      </div>
      {children}
    </section>
  )
}

/** Der Satz der Rückfrage zur Adresse: authentik kennt noch die alte, und/oder Anbieter von Hand ziehen nicht mit. */
function Adressrueckfrage({ frage }: { frage: Adressfrage }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2 text-[13px] text-fg-2">
      {frage.count > 0 && <p className="mb-0">{t('oidc.admin.addressChangeConfirm', { address: frage.address })}</p>}
      {frage.hand > 0 && <p className="mb-0">{t('oidc.admin.addressChangeHand', { count: frage.hand })}</p>}
    </div>
  )
}

function Rueckfrage({
  offen,
  titel,
  inhalt,
  knopf,
  laeuft,
  gefaehrlich,
  aufNein,
  aufJa,
}: {
  offen: boolean
  titel: string
  inhalt: ReactNode
  knopf: string
  laeuft?: boolean
  gefaehrlich?: boolean
  aufNein: () => void
  aufJa: () => void
}) {
  const { t } = useTranslation()
  if (!offen) return null
  return (
    <Dialog
      open
      title={titel}
      onClose={() => !laeuft && aufNein()}
      footer={
        <>
          <Button variant="ghost" onClick={aufNein} disabled={laeuft}>
            {t('aktion.abbrechen')}
          </Button>
          <Button variant={gefaehrlich ? 'danger' : 'primary'} loading={laeuft} onClick={aufJa}>
            {knopf}
          </Button>
        </>
      }
    >
      {inhalt}
    </Dialog>
  )
}

export function OidcVerwaltung() {
  const [eintraege, setEintraege] = useState<Anbieter[] | null>(null)
  const [adresse, setAdresse] = useState<AuthentikAddress | null>(null)
  const deuten = useDeuten()
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    try {
      const [liste, sicht] = await Promise.all([
        api.holen<Anbieter[]>('/api/oidc/admin/providers'),
        api.holen<AuthentikAddress>('/api/oidc/authentik/address'),
      ])
      setEintraege(liste)
      setAdresse(sicht)
      setFehler('')
    } catch (f) {
      setFehler(deuten(f))
    }
  }, [deuten])

  useEffect(() => {
    void laden()
  }, [laden])

  if (eintraege === null && !fehler) return <div className="h-24" />

  return (
    <div className="flex max-w-[720px] flex-col gap-5">
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      <AnmeldungKarte
        aktiv={(eintraege ?? []).some((e) => e.enabled)}
        oeffentlich={adresse?.public_url}
        aufGeaendert={laden}
      />
      <AnbieterKarte eintraege={eintraege ?? []} adresse={adresse} aufGeaendert={laden} />
      <AuthentikKarte adresse={adresse} aufGeaendert={laden} />
    </div>
  )
}

// --- Karte 1: Anmeldung ----------------------------------------------------------------------------------------------

function AnmeldungKarte({
  aktiv,
  oeffentlich,
  aufGeaendert,
}: {
  aktiv: boolean
  /** Die öffentliche Adresse, wie der Server sie zuletzt nannte: Karte 3 kann sie gerade übernommen haben. */
  oeffentlich: string | undefined
  aufGeaendert: () => Promise<void>
}) {
  const { t } = useTranslation()
  const deuten = useDeuten()
  const [passwort, setPasswort] = useState<boolean | null>(null)
  const [adresse, setAdresse] = useState('')
  const [zone, setZone] = useState('')
  const [gespeichert, setGespeichert] = useState('')
  const [frage, setFrage] = useState<Adressfrage | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [erfolg, setErfolg] = useState(false)

  const laden = useCallback(async () => {
    const [anmeldung, einstellungen] = await Promise.all([
      api.holen<{ passwort: boolean }>('/api/oidc/admin/anmeldung'),
      api.holen<{ oeffentliche_adresse: string; zeitzone: string }>('/api/einstellungen'),
    ])
    setPasswort(anmeldung.passwort)
    setAdresse(einstellungen.oeffentliche_adresse)
    setGespeichert(einstellungen.oeffentliche_adresse)
    setZone(einstellungen.zeitzone)
  }, [])

  useEffect(() => {
    void laden().catch((f) => setFehler(deuten(f)))
  }, [laden, deuten, aktiv, oeffentlich])

  async function umschalten(an: boolean) {
    setFehler('')
    try {
      const antwort = await api.aendern<{ passwort: boolean }>('/api/oidc/admin/anmeldung', { passwort: an })
      setPasswort(antwort.passwort)
    } catch (f) {
      setFehler(deuten(f))
    }
  }

  /* ⚠️ **Derselbe Weg wie Verwaltung → Server** (`PUT /api/einstellungen`), samt Rückfrage: Ändert die neue Adresse
     die Rückleitadresse eines Anbieters, fragt der Server (409 `public_url_change`) und speichert nichts. */
  async function speichern(bestaetigt: boolean) {
    setFehler('')
    setErfolg(false)
    setLaeuft(true)
    try {
      await api.aendern('/api/einstellungen', {
        oeffentliche_adresse: adresse.trim(),
        zeitzone: zone,
        adresse_bestaetigt: bestaetigt,
      })
      setFrage(null)
      setErfolg(true)
      await laden()
      await aufGeaendert()
    } catch (f) {
      const gefragt = adressfrageAus(f)
      if (gefragt) setFrage(gefragt)
      else setFehler(deuten(f))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Karte titel={t('oidc.admin.signInTitle')} kennung="oidc-karte-anmeldung">
      <Switch
        label={t('oidc.admin.password')}
        description={t('oidc.admin.passwordHint')}
        checked={passwort ?? true}
        // Ohne aktiven Anbieter käme außer dem Betreiber niemand herein: der Schalter bleibt an.
        disabled={passwort === null || (passwort && !aktiv)}
        onCheckedChange={(an) => void umschalten(an)}
      />
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          void speichern(false)
        }}
      >
        <div className="min-w-[240px] flex-1">
          <Input
            label={t('oidc.admin.address')}
            hint={t('oidc.admin.addressHint')}
            placeholder="https://mail.example.com"
            value={adresse}
            mono
            onChange={(e) => {
              setAdresse(e.target.value)
              setErfolg(false)
            }}
          />
        </div>
        <Button type="submit" variant="primary" loading={laeuft} disabled={adresse.trim() === gespeichert}>
          {t('aktion.speichern')}
        </Button>
      </form>
      {erfolg && (
        <p role="status" className="mb-0 text-[13px] text-success">
          {t('anmeldeweg.gespeichert')}
        </p>
      )}
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      <Rueckfrage
        offen={frage !== null}
        titel={t('oidc.admin.address')}
        inhalt={frage ? <Adressrueckfrage frage={frage} /> : null}
        knopf={t('aktion.speichern')}
        laeuft={laeuft}
        aufNein={() => setFrage(null)}
        aufJa={() => void speichern(true)}
      />
    </Karte>
  )
}

// --- Karte 2: Anmeldeanbieter ----------------------------------------------------------------------------------------

/** Derselbe Aussteller, wie auch immer am Ende geschrieben (``same_issuer`` des Servers ohne Platzhalter). */
function selberAussteller(a: string, b: string): boolean {
  return a.trim().replace(/\/+$/, '') === b.trim().replace(/\/+$/, '')
}

function AnbieterKarte({
  eintraege,
  adresse,
  aufGeaendert,
}: {
  eintraege: Anbieter[]
  adresse: AuthentikAddress | null
  aufGeaendert: () => Promise<void>
}) {
  const { t } = useTranslation()
  const deuten = useDeuten()
  const [offen, setOffen] = useState<Anbieter | 'neu' | null>(null)
  const [entfernen, setEntfernen] = useState<{ eintrag: Anbieter; count: number; only: number } | null>(null)
  const [gezogen, setGezogen] = useState<number | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const nurLesen = eintraege.some((e) => !e.editable)

  async function ordnen(von: number, nach: number) {
    if (von === nach || nach < 0 || nach >= eintraege.length) return
    const ids = eintraege.map((e) => e.id)
    const [genommen] = ids.splice(von, 1)
    ids.splice(nach, 0, genommen)
    try {
      await api.aendern('/api/oidc/admin/providers/order', { ids })
    } catch (f) {
      setFehler(deuten(f))
    }
    await aufGeaendert()
  }

  async function entfernenFragen(eintrag: Anbieter) {
    setFehler('')
    try {
      const folgen = await api.holen<{ count: number; only: number }>(`/api/oidc/admin/providers/${eintrag.id}/impact`)
      setEntfernen({ eintrag, count: folgen.count, only: folgen.only })
    } catch (f) {
      setFehler(deuten(f))
    }
  }

  async function entfernenJa() {
    if (!entfernen) return
    setLaeuft(true)
    try {
      await api.loeschen(`/api/oidc/admin/providers/${entfernen.eintrag.id}`)
      setEntfernen(null)
      await aufGeaendert()
    } catch (f) {
      setFehler(deuten(f))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Karte titel={t('oidc.admin.providersTitle')} text={t('oidc.admin.providersText')} kennung="oidc-karte-anbieter">
      {eintraege.length === 0 ? (
        <p className="mb-0 text-[13px] text-fg-3" data-testid="oidc-anbieter-leer">
          {t('oidc.admin.empty')}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0" data-testid="provider-list">
          {eintraege.map((e, index) => (
            <li
              key={e.id}
              className={`flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5 ${gezogen === index ? 'opacity-50' : ''}`}
              draggable={!nurLesen && eintraege.length > 1}
              onDragStart={() => setGezogen(index)}
              onDragEnd={() => setGezogen(null)}
              onDragOver={(ereignis) => ereignis.preventDefault()}
              onDrop={(ereignis) => {
                ereignis.preventDefault()
                if (gezogen !== null) void ordnen(gezogen, index)
                setGezogen(null)
              }}
            >
              {/* Griff und Name bleiben auch auf dem Telefon in einer Zeile. */}
              <div className="flex min-w-0 flex-1 basis-full items-center gap-2 sm:basis-auto">
                {!nurLesen && eintraege.length > 1 ? (
                  <button
                    type="button"
                    className="cursor-grab rounded-sm p-0.5 text-fg-4 hover:text-fg-1"
                    aria-label={t('anmeldeweg.ordnen', { name: e.label })}
                    onKeyDown={(ereignis) => {
                      if (ereignis.key === 'ArrowUp') void ordnen(index, index - 1)
                      if (ereignis.key === 'ArrowDown') void ordnen(index, index + 1)
                    }}
                  >
                    <GripVertical aria-hidden className="size-4" />
                  </button>
                ) : (
                  <KeyRound aria-hidden className="size-4 shrink-0 text-fg-4" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="mb-0 truncate text-sm font-medium text-fg-1">{e.label}</p>
                  <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{e.issuer}</p>
                </div>
              </div>
              <span className="flex flex-wrap items-center gap-1.5">
                <Badge tone={e.enabled ? 'success' : 'neutral'}>
                  {e.enabled ? t('oidc.admin.active') : t('oidc.admin.inactive')}
                </Badge>
                {e.managed === 'authentik' && <Badge tone="accent">{t('oidc.admin.managed')}</Badge>}
              </span>
              {e.editable && (
                <span className="flex gap-1">
                  <IconButton icon={<Pencil />} label={`${t('oidc.admin.edit')}: ${e.label}`} onClick={() => setOffen(e)} />
                  <IconButton
                    icon={<Trash2 />}
                    label={`${t('oidc.admin.remove')}: ${e.label}`}
                    onClick={() => void entfernenFragen(e)}
                  />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      {!nurLesen && (
        <div>
          <Button variant="primary" onClick={() => setOffen('neu')}>
            {t('oidc.admin.add')}
          </Button>
        </div>
      )}
      {offen && (
        <Formular
          bestehend={offen === 'neu' ? null : offen}
          adresse={adresse}
          aufSchliessen={() => setOffen(null)}
          aufFertig={() => {
            setOffen(null)
            void aufGeaendert()
          }}
        />
      )}
      <Rueckfrage
        offen={entfernen !== null}
        titel={t('oidc.admin.remove')}
        inhalt={
          entfernen ? (
            <p className="mb-0 text-[13px] text-fg-2">
              {t('oidc.admin.removeConfirm', {
                name: entfernen.eintrag.label,
                count: entfernen.count,
                only: entfernen.only,
              })}
            </p>
          ) : null
        }
        knopf={t('oidc.admin.remove')}
        laeuft={laeuft}
        gefaehrlich
        aufNein={() => setEntfernen(null)}
        aufJa={() => void entfernenJa()}
      />
    </Karte>
  )
}

interface Formwerte {
  label: string
  slug: string
  issuer: string
  client_id: string
  client_secret: string
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
}

const LEER: Formwerte = {
  label: '',
  slug: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
}

type Feldname = 'label' | 'slug' | 'issuer' | 'client_id' | 'client_secret' | 'scopes' | 'id'

/** Das Formular eines Anbieters als Dialog, Felder in der gemeinsamen Reihenfolge. */
function Formular({
  bestehend,
  adresse,
  aufSchliessen,
  aufFertig,
}: {
  bestehend: Anbieter | null
  adresse: AuthentikAddress | null
  aufSchliessen: () => void
  aufFertig: () => void
}) {
  const { t } = useTranslation()
  const [f, setF] = useState<Formwerte>(
    bestehend
      ? {
          label: bestehend.label,
          slug: bestehend.slug,
          issuer: bestehend.issuer,
          client_id: bestehend.client_id,
          client_secret: '',
          scopes: bestehend.scopes,
          enabled: bestehend.enabled,
          auto_create: bestehend.auto_create,
          trusts_second_factor: bestehend.trusts_second_factor,
        }
      : LEER,
  )
  // Der Kurzname folgt dem Namen auf dem Knopf, bis er selbst getippt wird.
  const [slugGetippt, setSlugGetippt] = useState(false)
  const [kopiert, setKopiert] = useState(false)
  const [problem, setProblem] = useState<{ feld: Feldname; text: string } | null>(null)
  const [ausstellerFrage, setAusstellerFrage] = useState<number | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const setze = (aenderung: Partial<Formwerte>) => setF((jetzt) => ({ ...jetzt, ...aenderung }))

  const slug = bestehend ? bestehend.slug : slugGetippt ? f.slug : slugFromLabel(f.label)
  const basis = (adresse?.public_url || adresse?.seen || `${window.location.origin}${BASIS}`).replace(/\/+$/, '')
  const rueckleit = bestehend ? bestehend.redirect_uri : `${basis}/api/oidc/${slug || '…'}/callback`

  function problemAus(fehler: unknown): { feld: Feldname; text: string } {
    if (fehler instanceof ApiFehler) {
      const feld = (typeof fehler.werte.field === 'string' ? fehler.werte.field : 'id') as Feldname
      const schluessel = oidcFormErrorKey(fehler.detail) ?? oidcErrorKey(fehler.detail)
      if (schluessel) return { feld, text: t(schluessel) }
    }
    return { feld: 'id', text: servermeldung(fehler, t('anmeldung.fehler_allgemein')) }
  }

  async function speichern() {
    setLaeuft(true)
    setProblem(null)
    try {
      const koerper = { ...f, slug: bestehend ? undefined : slug }
      if (bestehend) await api.aendern(`/api/oidc/admin/providers/${bestehend.id}`, koerper)
      else await api.senden('/api/oidc/admin/providers', koerper)
      aufFertig()
    } catch (fehler) {
      setProblem(problemAus(fehler))
    } finally {
      setLaeuft(false)
    }
  }

  async function absenden(e: FormEvent) {
    e.preventDefault()
    setProblem(null)
    // Ein anderer Aussteller ist ein anderer Anbieter: erst sagen, wie viele Konten sich neu verknüpfen müssen.
    if (bestehend && bestehend.links > 0 && !selberAussteller(bestehend.issuer, f.issuer)) {
      try {
        const folgen = await api.holen<{ issuer_change: number }>(
          `/api/oidc/admin/providers/${bestehend.id}/impact?issuer=${encodeURIComponent(f.issuer.trim())}`,
        )
        if (folgen.issuer_change > 0) {
          setAusstellerFrage(folgen.issuer_change)
          return
        }
      } catch (fehler) {
        setProblem(problemAus(fehler))
        return
      }
    }
    await speichern()
  }

  const amFeld = (feld: Feldname) => (problem?.feld === feld ? problem.text : undefined)

  return (
    <Dialog
      open
      title={bestehend ? `${t('oidc.admin.edit')}: ${bestehend.label}` : t('oidc.admin.add')}
      onClose={() => !laeuft && aufSchliessen()}
      abweisbar={!laeuft}
    >
      <form className="flex flex-col gap-4" onSubmit={(e) => void absenden(e)} data-testid="provider-form">
        <Input
          label={t('oidc.admin.label')}
          placeholder="authentik"
          value={f.label}
          error={amFeld('label')}
          onChange={(e) => setze({ label: e.target.value })}
        />
        {bestehend ? (
          <p className="-mt-1 mb-0 text-[12px] text-fg-4">
            {t('oidc.admin.slug')}: <code className="font-mono text-fg-2">{bestehend.slug}</code>
          </p>
        ) : (
          <Input
            label={t('oidc.admin.slug')}
            hint={t('oidc.admin.slugHint')}
            value={slug}
            mono
            maxLength={40}
            error={amFeld('slug')}
            onChange={(e) => {
              setSlugGetippt(true)
              setze({ slug: e.target.value.toLowerCase() })
            }}
          />
        )}
        <Input
          label={t('oidc.admin.issuer')}
          hint={t('oidc.admin.issuerHint')}
          placeholder="https://auth.example.com/application/o/nexmail/"
          value={f.issuer}
          mono
          error={amFeld('issuer')}
          onChange={(e) => setze({ issuer: e.target.value })}
        />
        <Input
          label={t('oidc.admin.clientId')}
          value={f.client_id}
          error={amFeld('client_id')}
          onChange={(e) => setze({ client_id: e.target.value })}
        />
        <Input
          label={t('oidc.admin.secret')}
          type="password"
          autoComplete="new-password"
          placeholder={bestehend?.has_secret ? t('oidc.admin.secretKept') : ''}
          value={f.client_secret}
          error={amFeld('client_secret')}
          onChange={(e) => setze({ client_secret: e.target.value })}
        />
        <div className="flex flex-col gap-1.5">
          {/* Dieselbe Beschriftung wie die Felder (ds/Feld.tsx), aber nur lesbar. */}
          <span className="text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">{t('oidc.admin.redirect')}</span>
          <div className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2">
            <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-1 select-all" data-testid="provider-redirect">
              {rueckleit}
            </code>
            <button
              type="button"
              aria-label={t('aktion.kopieren')}
              onClick={() => {
                void navigator.clipboard?.writeText(rueckleit)
                setKopiert(true)
                window.setTimeout(() => setKopiert(false), 2000)
              }}
              className="shrink-0 rounded-sm p-0.5 text-fg-4 hover:bg-surface-3 hover:text-fg-1"
            >
              {kopiert ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            </button>
          </div>
        </div>
        <Switch label={t('oidc.admin.enabled')} checked={f.enabled} onCheckedChange={(an) => setze({ enabled: an })} />
        <Switch
          label={t('oidc.admin.autoCreate')}
          description={t('oidc.admin.autoCreateHint')}
          checked={f.auto_create}
          onCheckedChange={(an) => setze({ auto_create: an })}
        />
        <Switch
          label={t('oidc.admin.trustsSecondFactor')}
          description={t('oidc.admin.trustsSecondFactorHint')}
          checked={f.trusts_second_factor}
          onCheckedChange={(an) => setze({ trusts_second_factor: an })}
        />
        <details open={problem?.feld === 'scopes' || undefined}>
          <summary className="cursor-pointer text-[12px] text-fg-3">{t('anmeldeweg.mehr')}</summary>
          <div className="mt-3">
            <Input
              label={t('oidc.admin.scopes')}
              value={f.scopes}
              mono
              error={amFeld('scopes')}
              onChange={(e) => setze({ scopes: e.target.value })}
            />
          </div>
        </details>
        {problem?.feld === 'id' && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {problem.text}
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={laeuft}>
            {t('aktion.speichern')}
          </Button>
          <Button type="button" variant="ghost" onClick={aufSchliessen} disabled={laeuft}>
            {t('aktion.abbrechen')}
          </Button>
        </div>
      </form>
      <Rueckfrage
        offen={ausstellerFrage !== null}
        titel={t('oidc.admin.issuer')}
        inhalt={
          <p className="mb-0 text-[13px] text-fg-2">
            {t('oidc.admin.issuerChangeConfirm', { count: ausstellerFrage ?? 0 })}
          </p>
        }
        knopf={t('aktion.speichern')}
        laeuft={laeuft}
        aufNein={() => setAusstellerFrage(null)}
        aufJa={() => {
          setAusstellerFrage(null)
          void speichern()
        }}
      />
    </Dialog>
  )
}

// --- Karte 3: authentik in einem Schritt -----------------------------------------------------------------------------

function AuthentikKarte({
  adresse,
  aufGeaendert,
}: {
  adresse: AuthentikAddress | null
  aufGeaendert: () => Promise<void>
}) {
  const { t } = useTranslation()
  const deuten = useDeuten()
  const [werte, setWerte] = useState({ url: '', token: '' })
  const [ergebnis, setErgebnis] = useState<Ergebnis | null>(null)
  // Der Knopf hielt an, bevor er etwas schrieb: ein anderer Aussteller, so viele Konten müssten sich neu verknüpfen.
  const [fragtAussteller, setFragtAussteller] = useState<{ count: number; uebernehmen: boolean } | null>(null)
  // „Nur übernehmen“ hielt an: Das Speichern der Adresse lässt eine Rückleitadresse zurück, die ein Anbieter kennt.
  const [frage, setFrage] = useState<Adressfrage | null>(null)
  const [laeuft, setLaeuft] = useState<'einrichten' | 'uebernehmen' | 'blueprint' | null>(null)
  const [fehler, setFehler] = useState('')

  // Solange nexmail keine öffentliche Adresse hat, bietet die Karte die des Browsers an (nie eine geratene).
  const vorschlag = authentikProposal(window.location.origin, BASIS)
  const fehlt = adresse !== null && adresse.public_url === ''
  const veraltet = authentikStale(adresse)

  async function einrichten(bestaetigt: boolean, uebernehmen: boolean) {
    setFehler('')
    setErgebnis(null)
    setFragtAussteller(null)
    setLaeuft('einrichten')
    try {
      const antwort = await api.senden<Ergebnis>('/api/oidc/authentik/setup', {
        url: werte.url.trim(),
        token: werte.token.trim(),
        confirm_issuer_change: bestaetigt,
        public_url: uebernehmen ? vorschlag : '',
      })
      // Keine Niederlage: Der Knopf wartet auf das Ja, geändert ist nichts. Das Token bleibt für den zweiten Lauf.
      const anzahl = authentikIssuerChange(antwort)
      if (anzahl !== null) {
        setFragtAussteller({ count: anzahl, uebernehmen })
        return
      }
      setErgebnis(antwort)
      // Das Token galt nur für diesen Lauf; es bleibt auch nicht in der Seite stehen.
      setWerte((jetzt) => ({ ...jetzt, token: '' }))
      await aufGeaendert()
    } catch (f) {
      setFehler(deuten(f))
    } finally {
      setLaeuft(null)
    }
  }

  async function nurUebernehmen(bestaetigt: boolean) {
    setFehler('')
    setFrage(null)
    setLaeuft('uebernehmen')
    try {
      await api.senden('/api/oidc/authentik/address', bestaetigt ? { public_url: vorschlag, confirm: true } : { public_url: vorschlag })
      await aufGeaendert()
    } catch (f) {
      const gefragt = adressfrageAus(f)
      if (gefragt) setFrage(gefragt)
      else setFehler(deuten(f))
    } finally {
      setLaeuft(null)
    }
  }

  async function blueprint() {
    setFehler('')
    setLaeuft('blueprint')
    try {
      const antwort = await fetch(`${BASIS}/api/oidc/authentik/blueprint`, { credentials: 'include' })
      if (!antwort.ok) {
        const daten = (await antwort.json().catch(() => ({}))) as { detail?: string }
        throw new ApiFehler(antwort.status, String(daten.detail ?? ''))
      }
      const name = /filename="([^"]+)"/.exec(antwort.headers.get('content-disposition') ?? '')?.[1] ?? 'nexmail-authentik.yaml'
      const link = document.createElement('a')
      link.href = URL.createObjectURL(await antwort.blob())
      link.download = name
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000)
    } catch (f) {
      setFehler(deuten(f))
    } finally {
      setLaeuft(null)
    }
  }

  return (
    <Karte titel={t('oidc.authentik.title')} text={t('oidc.authentik.text')} kennung="oidc-karte-authentik">
      {fehlt && adresse && (
        <div
          className="flex flex-col gap-1.5 rounded-md border border-warning/40 bg-warning-soft px-3 py-2.5 text-[12px] text-warning-text"
          data-testid="authentik-no-address"
        >
          <p className="mb-0">{t('oidc.authentik.noAddress')}</p>
          <p className="mb-0 break-all font-mono text-[13px] text-fg-1" data-testid="authentik-proposal">
            {vorschlag}
          </p>
          <p className="mb-0 break-all">
            {t('oidc.admin.redirect')}: <code className="font-mono">{authentikRedirect(vorschlag, adresse)}</code>
          </p>
          {authentikProxyWarning(vorschlag, adresse) && (
            <p className="mb-0" data-testid="authentik-proxy-warning">
              {t('oidc.authentik.proxyWarning', { address: adresse.seen })}
            </p>
          )}
        </div>
      )}
      {veraltet && (
        <p
          className="mb-0 rounded-md border border-warning/40 bg-warning-soft px-3 py-2.5 text-[12px] text-warning-text"
          data-testid="authentik-stale"
        >
          {t('oidc.authentik.stale', { address: veraltet })}
        </p>
      )}
      <form
        className="flex flex-col gap-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          void einrichten(false, fehlt)
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label={t('oidc.authentik.url')}
            placeholder="https://auth.example.com"
            value={werte.url}
            onChange={(e) => setWerte({ ...werte, url: e.target.value })}
          />
          <Input
            label={t('oidc.authentik.token')}
            type="password"
            autoComplete="new-password"
            value={werte.token}
            onChange={(e) => setWerte({ ...werte, token: e.target.value })}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="submit"
            variant="primary"
            loading={laeuft === 'einrichten'}
            disabled={!werte.url.trim() || !werte.token.trim() || laeuft !== null}
          >
            {fehlt ? t('oidc.authentik.adopt') : t('oidc.authentik.run')}
          </Button>
          {fehlt && (
            <Button
              type="button"
              variant="ghost"
              loading={laeuft === 'uebernehmen'}
              disabled={laeuft !== null}
              onClick={() => void nurUebernehmen(false)}
            >
              {t('oidc.authentik.adoptOnly')}
            </Button>
          )}
          <Button type="button" variant="ghost" loading={laeuft === 'blueprint'} onClick={() => void blueprint()}>
            {laeuft !== 'blueprint' && <Download aria-hidden className="size-4" />}
            {t('oidc.authentik.blueprint')}
          </Button>
        </div>
      </form>
      {laeuft === 'einrichten' && (
        <p className="mb-0 text-[12px] text-fg-3" aria-live="polite">
          {t('oidc.authentik.asking')}
        </p>
      )}
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      {ergebnis && (
        <ol className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]" data-testid="authentik-steps">
          {ergebnis.steps.map((s) => {
            const name = authentikStepKey(s.key)
            const grund = s.ok ? null : authentikReasonKey(s.reason)
            return (
              <li key={s.key} className="flex items-start gap-2">
                {s.ok ? (
                  <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
                ) : (
                  <X aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
                )}
                <span className="min-w-0">
                  <span className={s.ok ? 'text-fg-1' : 'font-medium text-danger'}>{name ? t(name) : s.key}</span>
                  {grund && (
                    <span className="block text-[12px] text-fg-3">
                      {t(grund, { status: s.status ?? 0, count: ergebnis.count ?? 0 })}
                    </span>
                  )}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      <Rueckfrage
        offen={fragtAussteller !== null}
        titel={t('oidc.authentik.title')}
        inhalt={
          <p className="mb-0 text-[13px] text-fg-2">
            {t('oidc.admin.issuerChangeConfirm', { count: fragtAussteller?.count ?? 0 })}
          </p>
        }
        knopf={t('oidc.authentik.run')}
        laeuft={laeuft === 'einrichten'}
        aufNein={() => setFragtAussteller(null)}
        aufJa={() => void einrichten(true, fragtAussteller?.uebernehmen ?? false)}
      />
      <Rueckfrage
        offen={frage !== null}
        titel={t('oidc.admin.address')}
        inhalt={frage ? <Adressrueckfrage frage={frage} /> : null}
        knopf={t('aktion.speichern')}
        laeuft={laeuft === 'uebernehmen'}
        aufNein={() => setFrage(null)}
        aufJa={() => void nurUebernehmen(true)}
      />
    </Karte>
  )
}
