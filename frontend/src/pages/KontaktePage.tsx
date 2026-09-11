/* Das Adressbuch.
 *
 * Aufteilung wie im Mailteil: links die Liste, rechts der Eintrag. Wer sich in
 * nexmail zurechtfindet, findet sich auch hier zurecht — eine zweite
 * Anordnung für dieselbe Sache wäre eine zweite Sache zum Lernen.
 *
 * ⚠️ **Aufgeschnapptes ist gekennzeichnet.** nexmail sammelt Empfänger aus
 * „Gesendet" ein; ohne sichtbaren Unterschied weiß später niemand mehr, was er
 * selbst gepflegt hat und was von allein kam — und traut sich deshalb nicht,
 * aufzuräumen.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  Download,
  Link2,
  Plus,
  RefreshCw,
  Trash2,
  Unlink,
  Upload,
  UserRoundPlus,
  Users,
} from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { Badge, Button, Checkbox, EmptyState, IconButton, Input, Select } from '../ds'
import { Buchfenster } from '../components/Buchfenster'
import { Kontaktkonflikt } from '../components/Kontaktkonflikt'
import type { Kontaktfassung } from '../components/Kontaktkonflikt'
import { useNachfrage } from '../components/Nachfrage'
import { appPfad } from '../lib/basis'
import { PUNKT_KLASSE } from '../lib/farben'
import { beschriftung, beschriftungFuer, sichtbareKontakte } from '../lib/kontaktanzeige'
import { servermeldung } from '../lib/servermeldung'
import type { Postfachfarbe } from '../daten/typen'

export interface Kontakt {
  id: number
  name: string
  adresse: string
  firma: string
  telefon: string
  notiz: string
  quelle: string
  verwendet: number
  /** In welchem Buch der Eintrag liegt. */
  adressbuch_id: string | null
  /** Alle Nummern und Adressen der Karte, nur bei verbundenen Kontakten:
   *  Das Modell kennt eine Nummer, die Karte viele. */
  nummern: Karteneintrag[]
  adressen: Karteneintrag[]
}

export interface Karteneintrag {
  nummer?: string
  adresse?: string
  typen: string
  beschriftung: string
}

/* Ein Adressbuch: das lokale, das nicht wegkann, oder ein verbundenes (Beta;
 * seit Lieferung 2 gelesen und geschrieben). Ein Buch ist der Ort eines
 * Kontakts, davon genau einer; eine Gruppe ist quer dazu. */
export interface Buch {
  id: string
  name: string
  farbe: number
  sichtbar: boolean
  ist_lokal: boolean
  /** "" (lebt nur hier) | "carddav" */
  art: string
  herkunft: string
  letzter_fehler: string
  kontakte: number
}

interface Abgleichbericht {
  neu: number
  geaendert: number
  entfernt: number
  belegt: number
  fehler: Record<string, string>
}

/* Ein Verteiler — ein Eingabehelfer beim Adressieren, kein Mailbegriff.
 * In der Mail stehen nur die Einzeladressen der Mitglieder. */
export interface Gruppe {
  id: number
  name: string
  mitglieder: number
  mitglied_ids: number[]
  adressen: string[]
}

const LEER: Pick<Kontakt, 'name' | 'adresse' | 'firma' | 'telefon' | 'notiz'> = {
  name: '',
  adresse: '',
  firma: '',
  telefon: '',
  notiz: '',
}

export function KontaktePage() {
  const { t, i18n } = useTranslation()

  const [liste, setListe] = useState<Kontakt[]>([])
  const [suche, setSuche] = useState('')
  const [gewaehlt, setGewaehlt] = useState<number | null>(null)
  const [entwurf, setEntwurf] = useState<typeof LEER | null>(null)
  const [gruppen, setGruppen] = useState<Gruppe[]>([])
  const [gruppeGewaehlt, setGruppeGewaehlt] = useState<number | null>(null)
  const [gruppeNeu, setGruppeNeu] = useState(false)
  const [buecher, setBuecher] = useState<Buch[]>([])
  const [buchNeu, setBuchNeu] = useState(false)
  const [gleichtAb, setGleichtAb] = useState(false)
  const [fehler, setFehler] = useState('')
  const [meldung, setMeldung] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  /* Ein offener Konflikt: die eigene Fassung, wie sie gespeichert werden
     sollte. Solange er steht, ist nichts gespeichert. */
  const [konflikt, setKonflikt] = useState<{ id: number; meine: Kontaktfassung } | null>(null)
  const dateifeld = useRef<HTMLInputElement>(null)
  const { fragen, fenster: nachfrage } = useNachfrage()

  const laden = useCallback(async (s: string) => {
    const roh = await api.holen<Kontakt[]>(`/api/kontakte?suche=${encodeURIComponent(s)}`)
    setListe(roh)
    return roh
  }, [])

  const gruppenLaden = useCallback(async () => {
    setGruppen(await api.holen<Gruppe[]>('/api/kontakte/gruppen'))
  }, [])

  const buecherLaden = useCallback(async () => {
    setBuecher(await api.holen<Buch[]>('/api/adressbuecher'))
  }, [])

  useEffect(() => {
    // Kurz warten, sonst eine Abfrage je Tastendruck.
    const uhr = window.setTimeout(() => void laden(suche).catch(() => setListe([])), 200)
    return () => window.clearTimeout(uhr)
  }, [suche, laden])

  useEffect(() => {
    void gruppenLaden().catch(() => setGruppen([]))
    void buecherLaden().catch(() => setBuecher([]))
  }, [gruppenLaden, buecherLaden])

  const offen = liste.find((k) => k.id === gewaehlt) ?? null
  const gruppeOffen = gruppen.find((g) => g.id === gruppeGewaehlt) ?? null
  /* Die Haken an den Büchern gelten für die Liste; ein Kontakt, dessen Buch
     die Liste nicht kennt, bleibt sichtbar. */
  const sichtbar = sichtbareKontakte(liste, buecher)
  const nachBuch = new Map(buecher.map((b) => [b.id, b]))

  async function mit<T>(tun: () => Promise<T>, erfolg = ''): Promise<T | null> {
    setFehler('')
    setMeldung('')
    setLaeuft(true)
    try {
      const ergebnis = await tun()
      await laden(suche)
      // Die Gruppen haengen an den Kontakten (Mitgliederzahl!) — nach jeder
      // Handlung frisch holen, sonst zaehlt die Liste Geloeschte weiter mit.
      // Die Buecher ebenso: Ihre Zahl steht in der Spalte.
      await gruppenLaden()
      await buecherLaden()
      if (erfolg) setMeldung(erfolg)
      return ergebnis
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return null
    } finally {
      setLaeuft(false)
    }
  }

  /** ⚠️ Der Server nennt eine Kennung, die Oberfläche übersetzt. */
  function buchfehlertext(kennung: string): string {
    const schluessel = `kontakte.buch_fehler_${kennung}`
    return i18n.exists(schluessel) ? t(schluessel) : t('kontakte.buch_fehler_allgemein')
  }

  async function buchUmschalten(b: Buch, an: boolean) {
    // Sofort umschalten, damit der Haken nicht hakt; die gezählte Wahrheit
    // holt der nächste Abruf.
    setBuecher((alt) => alt.map((x) => (x.id === b.id ? { ...x, sichtbar: an } : x)))
    try {
      await api.flicken(`/api/adressbuecher/${b.id}`, { sichtbar: an })
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      await buecherLaden().catch(() => undefined)
    }
  }

  async function jetztAbgleichen() {
    setGleichtAb(true)
    setFehler('')
    setMeldung('')
    try {
      const b = await api.senden<Abgleichbericht>('/api/adressbuecher/abgleichen', {})
      await laden(suche)
      await buecherLaden()
      const saetze = [
        b.neu + b.geaendert + b.entfernt > 0
          ? t('kontakte.buch_abgleich_fertig', {
              neu: b.neu,
              geaendert: b.geaendert,
              entfernt: b.entfernt,
            })
          : t('kontakte.buch_abgleich_nichts'),
      ]
      // ⚠️ Übergangene Karten werden genannt, sonst fehlen drüben Kontakte
      // und niemand weiss warum.
      if (b.belegt) saetze.push(t('kontakte.buch_abgleich_belegt', { count: b.belegt }))
      setMeldung(saetze.join(' '))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setGleichtAb(false)
    }
  }

  async function buchTrennen(b: Buch) {
    /* ⚠️ Die Rückfrage sagt, dass beim Anbieter nichts gelöscht wird. Ohne
       den Satz klingt „trennen" nach „weg". */
    const ja = await fragen({
      titel: t('kontakte.buch_trennen_frage', { name: b.name }),
      text: t('kontakte.buch_trennen_text', { count: b.kontakte, wo: b.herkunft }),
      knopf: t('kontakte.buch_trennen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(async () => {
      await api.loeschen(`/api/adressbuecher/${b.id}`)
      if (offen && offen.adressbuch_id === b.id) setGewaehlt(null)
    })
  }

  async function gruppeSpeichern(name: string, kontaktIds: number[]) {
    if (gruppeNeu) {
      const neu = await mit(async () => {
        const g = await api.senden<Gruppe>('/api/kontakte/gruppen', { name })
        if (kontaktIds.length > 0) {
          await api.aendern<Gruppe>(`/api/kontakte/gruppen/${g.id}/mitglieder`, {
            kontakt_ids: kontaktIds,
          })
        }
        return g
      })
      if (neu) {
        setGruppeNeu(false)
        setGruppeGewaehlt(neu.id)
      }
      return
    }
    if (!gruppeOffen) return
    await mit(async () => {
      if (name !== gruppeOffen.name) {
        await api.flicken<Gruppe>(`/api/kontakte/gruppen/${gruppeOffen.id}`, { name })
      }
      await api.aendern<Gruppe>(`/api/kontakte/gruppen/${gruppeOffen.id}/mitglieder`, {
        kontakt_ids: kontaktIds,
      })
    })
  }

  async function gruppeEntfernen(g: Gruppe) {
    // ⚠️ Die Rueckfrage nennt die Mitgliederzahl und sagt dazu, dass die
    // Kontakte bleiben — sonst liest jemand „entfernen" und fuerchtet um
    // sein Adressbuch.
    const ja = await fragen({
      titel: t('kontakte.gruppe_entfernen'),
      text:
        g.mitglieder === 0
          ? t('kontakte.gruppe_entfernen_text_leer', { name: g.name })
          : t('kontakte.gruppe_entfernen_text', { name: g.name, count: g.mitglieder }),
      knopf: t('kontakte.gruppe_entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(async () => {
      await api.loeschen(`/api/kontakte/gruppen/${g.id}`)
      setGruppeGewaehlt(null)
    })
  }

  async function speichern(felder: typeof LEER, buchId: string) {
    if (entwurf && gewaehlt === null) {
      /* Ein neuer Kontakt entsteht in dem Buch, das im Formular gewählt ist;
         in einem verbundenen zuerst beim Anbieter. Was der ablehnt, gibt es
         hier gar nicht erst. */
      const neu = await mit(() =>
        api.senden<Kontakt>('/api/kontakte', { ...felder, adressbuch_id: buchId || null }),
      )
      if (neu) {
        setEntwurf(null)
        setGewaehlt(neu.id)
      }
      return
    }
    if (offen) await schreiben(offen.id, felder, false)
  }

  /* ⚠️ **Ein Konflikt ist keine Fehlermeldung, sondern eine Frage.** Jemand
     hat die Karte am Telefon geändert, seit sie hier offen ist. Die eigene
     Eingabe bleibt im Formular stehen (als Entwurf), und das Fenster fragt,
     welche Fassung gilt — dasselbe Muster wie beim Termin. */
  async function schreiben(id: number, felder: typeof LEER, erzwingen: boolean) {
    const fertig = await mit(async () => {
      try {
        await api.flicken<Kontakt>(`/api/kontakte/${id}`, { ...felder, erzwingen })
        return true
      } catch (f) {
        if (f instanceof ApiFehler && f.detail === 'kontakt_konflikt') {
          setEntwurf({ ...felder })
          setKonflikt({ id, meine: felder })
          return false
        }
        throw f
      }
    })
    if (fertig) setEntwurf(null)
  }

  async function konfliktEntscheiden(wahl: 'meine' | 'andere') {
    if (!konflikt) return
    const { id, meine } = konflikt
    setKonflikt(null)
    if (wahl === 'meine') {
      await schreiben(id, meine, true)
      return
    }
    const uebernommen = await mit(() => api.senden<Kontakt>(`/api/kontakte/${id}/konflikt`, {}))
    if (uebernommen) setEntwurf(null)
  }

  /* Ein Kontakt wechselt sein Buch. In ein verbundenes hinein hängt er sich
     an die Karte, die dort schon seine Adresse trägt, sonst entsteht sie.
     ⚠️ **Aus einem verbundenen heraus heisst: dort löschen** — und das wird
     gefragt, denn beim Anbieter gibt es kein Rückgängig. */
  async function verschieben(k: Kontakt, buchId: string) {
    const von = k.adressbuch_id ? nachBuch.get(k.adressbuch_id) : undefined
    const nach = nachBuch.get(buchId)
    if (!nach || von?.id === nach.id) return
    if (von?.art) {
      const ja = await fragen({
        titel: t('kontakte.verschieben_frage', { name: nach.name }),
        text: t('kontakte.verschieben_text', { wo: von.herkunft }),
        knopf: t('kontakte.verschieben_knopf'),
        gefaehrlich: true,
      })
      if (ja !== true) return
    }
    await mit(
      () => api.senden<Kontakt>(`/api/kontakte/${k.id}/verschieben`, { adressbuch_id: buchId }),
      t('kontakte.verschoben', { name: nach.name }),
    )
  }

  /* Löschen nimmt bei einem verbundenen Kontakt die Karte beim Anbieter mit.
     ⚠️ Genau davor wird gefragt; ein lokaler Eintrag geht wie bisher ohne
     Umweg, denn der ist mit einem Klick wieder angelegt. */
  async function entfernen(k: Kontakt) {
    const buch = k.adressbuch_id ? nachBuch.get(k.adressbuch_id) : undefined
    if (buch?.art) {
      const ja = await fragen({
        titel: t('kontakte.entfernen_frage', { name: beschriftung(k).titel }),
        text: t('kontakte.entfernen_text', { wo: buch.herkunft }),
        knopf: t('kontakte.entfernen'),
        gefaehrlich: true,
      })
      if (ja !== true) return
    }
    await mit(async () => {
      await api.loeschen(`/api/kontakte/${k.id}`)
      setGewaehlt(null)
    })
  }

  async function vcardEinlesen(datei: File) {
    const formular = new FormData()
    formular.append('datei', datei)
    const stand = await mit(() =>
      api.formular<{ neu: number; ergaenzt: number }>('/api/kontakte/vcard', formular),
    )
    if (stand) setMeldung(t('kontakte.eingelesen', stand))
  }

  return (
    <div className="flex min-h-0 flex-1 bg-canvas">
      {/* --- Liste --------------------------------------------------- */}
      <div className="flex w-[320px] shrink-0 flex-col border-r border-line">
        <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line-subtle px-2">
          <IconButton
            icon={<Plus />}
            label={t('kontakte.neu')}
            size="sm"
            onClick={() => {
              setGewaehlt(null)
              setGruppeGewaehlt(null)
              setGruppeNeu(false)
              setEntwurf({ ...LEER })
            }}
          />
          <IconButton
            icon={<UserRoundPlus />}
            label={t('kontakte.einsammeln')}
            size="sm"
            onClick={() =>
              void mit(
                () => api.senden<{ neu: number }>('/api/kontakte/einsammeln', {}),
                t('kontakte.eingesammelt'),
              )
            }
          />
          <span aria-hidden className="mx-1 h-5 w-px bg-line" />
          <IconButton
            icon={<Upload />}
            label={t('kontakte.einlesen')}
            size="sm"
            onClick={() => dateifeld.current?.click()}
          />
          <IconButton
            icon={<Download />}
            label={t('kontakte.ausfuehren')}
            size="sm"
            onClick={() => {
              window.location.href = appPfad('/api/kontakte/vcard')
            }}
          />
          <span className="flex-1" />
          <span className="pr-1 text-[11px] text-fg-4">{sichtbar.length}</span>
        </div>

        <input
          ref={dateifeld}
          type="file"
          accept=".vcf,text/vcard"
          className="sr-only"
          onChange={(e) => {
            const datei = e.target.files?.[0]
            if (datei) void vcardEinlesen(datei)
            e.target.value = ''
          }}
        />

        <div className="shrink-0 border-b border-line-subtle p-2">
          <Input
            placeholder={t('kontakte.suchen')}
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
          />
        </div>

        {/* --- Bücher: wo ein Kontakt liegt. Beta ------------------------ */}
        <div className="shrink-0 border-b border-line-subtle">
          <div className="flex h-9 items-center gap-1.5 pr-1 pl-3">
            <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
              {t('kontakte.buecher')}
            </span>
            {/* ⚠️ Die Beta steht dort, wo die verbundenen Bücher stehen, nicht
                in einer README. Sie fällt, wenn das Schreiben gegen iCloud
                und Google gemessen ist. */}
            <Badge tone="warning">{t('kontakte.beta')}</Badge>
            <span className="flex-1" />
            {buecher.some((b) => b.art) && (
              <IconButton
                icon={<RefreshCw className={gleichtAb ? 'animate-spin' : undefined} />}
                label={gleichtAb ? t('kontakte.buch_abgleich_laeuft') : t('kontakte.buch_abgleichen')}
                size="sm"
                onClick={() => void jetztAbgleichen()}
              />
            )}
            <IconButton
              icon={<Plus />}
              label={t('kontakte.buch_verbinden')}
              size="sm"
              onClick={() => setBuchNeu(true)}
            />
          </div>
          <div className="pb-1">
            {buecher.map((b) => (
              /* ⚠️ Der Farbfleck steht VOR dem Haken, wie beim Kalender: Der
                 Haken sagt „wird angezeigt", der Fleck sagt, welches Buch. */
              <div key={b.id} className="flex items-center gap-2 px-3 py-1 hover:bg-surface-2">
                <span
                  aria-hidden
                  className={`size-2.5 shrink-0 rounded-sm ${PUNKT_KLASSE[b.farbe as Postfachfarbe]}`}
                />
                <span className="min-w-0 flex-1 truncate text-[13px]">
                  <Checkbox
                    label={b.name}
                    checked={b.sichtbar}
                    onCheckedChange={(an) => void buchUmschalten(b, an)}
                  />
                </span>
                <span className="text-[11px] text-fg-4">{b.kontakte}</span>
                {/* ⚠️ Der Fehler steht am Buch, nicht in einem Banner. Bei
                    drei verbundenen Büchern sagt „fehlgeschlagen" nicht,
                    welches. */}
                {b.letzter_fehler ? (
                  <span title={buchfehlertext(b.letzter_fehler)}>
                    <AlertTriangle aria-hidden className="size-3.5 shrink-0 text-warning" />
                  </span>
                ) : b.art ? (
                  <span title={b.herkunft}>
                    <Link2 aria-hidden className="size-3.5 shrink-0 text-fg-4" />
                  </span>
                ) : null}
                {b.art && (
                  <IconButton
                    icon={<Unlink />}
                    label={t('kontakte.buch_trennen')}
                    size="sm"
                    onClick={() => void buchTrennen(b)}
                  />
                )}
              </div>
            ))}
            {/* Das Ergebnis eines Abgleichs gehört hierher, wenn rechts
                gerade kein Eintrag offen ist, der es zeigen könnte. */}
            {!(entwurf || offen || gruppeNeu || gruppeOffen) && (fehler || meldung) && (
              <p className={`px-3 pb-2 text-[12px] ${fehler ? 'text-danger' : 'text-accent-text'}`}>
                {fehler || meldung}
              </p>
            )}
          </div>
        </div>

        {/* --- Gruppen: Verteiler als Eingabehelfer beim Adressieren --- */}
        <div className="shrink-0 border-b border-line-subtle">
          <div className="flex h-9 items-center gap-1 pr-1 pl-3">
            <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
              {t('kontakte.gruppen')}
            </span>
            <span className="flex-1" />
            <IconButton
              icon={<Plus />}
              label={t('kontakte.gruppe_neu')}
              size="sm"
              onClick={() => {
                setGewaehlt(null)
                setEntwurf(null)
                setGruppeGewaehlt(null)
                setGruppeNeu(true)
                setFehler('')
                setMeldung('')
              }}
            />
          </div>
          {gruppen.length === 0 ? (
            <p className="px-3 pb-2 text-[12px] text-fg-4">{t('kontakte.gruppe_leer')}</p>
          ) : (
            <div className="max-h-44 overflow-y-auto pb-1">
              {gruppen.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => {
                    setGewaehlt(null)
                    setEntwurf(null)
                    setGruppeNeu(false)
                    setGruppeGewaehlt(g.id)
                    setFehler('')
                    setMeldung('')
                  }}
                  className={
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left ' +
                    'transition-colors duration-[var(--dur-fast)] ' +
                    (g.id === gruppeGewaehlt && !gruppeNeu ? 'bg-accent-soft' : 'hover:bg-surface-2')
                  }
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">{g.name}</span>
                  <Badge tone="neutral">{t('kontakte.gruppe_zahl', { count: g.mitglieder })}</Badge>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {sichtbar.length === 0 ? (
            <p className="px-3 py-6 text-center text-[13px] text-fg-4">{t('kontakte.leer')}</p>
          ) : (
            sichtbar.map((k) => (
              <button
                key={k.id}
                type="button"
                onClick={() => {
                  setGewaehlt(k.id)
                  setEntwurf(null)
                  setGruppeGewaehlt(null)
                  setGruppeNeu(false)
                  setFehler('')
                  setMeldung('')
                }}
                className={
                  'flex w-full flex-col items-start gap-0.5 border-b border-line-subtle px-3 py-2 text-left ' +
                  'transition-colors duration-[var(--dur-fast)] ' +
                  (k.id === gewaehlt ? 'bg-accent-soft' : 'hover:bg-surface-2')
                }
              >
                <span className="flex w-full items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg-1">
                    {beschriftung(k).titel}
                  </span>
                  {/* ⚠️ Aufgeschnapptes muss man sehen — sonst traut sich
                      niemand, das Adressbuch aufzuräumen. */}
                  {k.quelle === 'gesammelt' && (
                    <Badge tone="neutral">{t('kontakte.gesammelt')}</Badge>
                  )}
                </span>
                {/* Ohne Adresse steht hier die Nummer: ein Kontakt darf seit
                    dem 05.09.2026 ohne Postfach leben. */}
                <span className="w-full truncate text-[12px] text-fg-3">{beschriftung(k).unter}</span>
              </button>
            ))
          )}
        </div>

        <div className="shrink-0 border-t border-line-subtle p-2">
          <Button
            size="sm"
            variant="ghost"
            fullWidth
            iconLeft={<Trash2 className="size-4" />}
            disabled={laeuft || !liste.some((k) => k.quelle === 'gesammelt')}
            onClick={() =>
              void mit(
                () => api.loeschen<{ entfernt: number }>('/api/kontakte/gesammelte'),
                t('kontakte.aufgeraeumt'),
              )
            }
          >
            {t('kontakte.gesammelte_weg')}
          </Button>
        </div>
      </div>

      {/* --- Eintrag ------------------------------------------------- */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {gruppeNeu || gruppeOffen ? (
          <GruppenFormular
            key={gruppeNeu ? 'gruppe-neu' : gruppeOffen!.id}
            gruppe={gruppeNeu ? null : gruppeOffen}
            laeuft={laeuft}
            fehler={fehler}
            meldung={meldung}
            aufSpeichern={gruppeSpeichern}
            aufEntfernen={gruppeOffen ? () => void gruppeEntfernen(gruppeOffen) : undefined}
          />
        ) : entwurf || offen ? (
          <Formular
            key={gewaehlt ?? 'neu'}
            werte={entwurf ?? {
              name: offen!.name,
              adresse: offen!.adresse,
              firma: offen!.firma,
              telefon: offen!.telefon,
              notiz: offen!.notiz,
            }}
            neu={gewaehlt === null}
            laeuft={laeuft}
            fehler={fehler}
            meldung={meldung}
            buecher={buecher}
            buchId={offen?.adressbuch_id ?? buecher.find((b) => b.ist_lokal)?.id ?? ''}
            herkunft={offen?.adressbuch_id ? (nachBuch.get(offen.adressbuch_id)?.herkunft ?? '') : ''}
            nummern={offen?.nummern ?? []}
            adressen={offen?.adressen ?? []}
            aufSpeichern={speichern}
            aufVerschieben={offen ? (buchId) => void verschieben(offen, buchId) : undefined}
            aufEntfernen={offen ? () => void entfernen(offen) : undefined}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              icon={<Users />}
              title={t('kontakte.keine_auswahl')}
              description={t('kontakte.keine_auswahl_text')}
            />
          </div>
        )}
      </div>

      {buchNeu && (
        <Buchfenster
          onClose={() => setBuchNeu(false)}
          onFertig={() => {
            void buecherLaden().catch(() => undefined)
            void laden(suche).catch(() => undefined)
          }}
        />
      )}

      {/* ⚠️ Das Konfliktfenster liegt über dem Formular; die eigene Eingabe
          steht darunter als Entwurf und geht bei „Abbrechen“ nicht verloren. */}
      {konflikt && (
        <Kontaktkonflikt
          kontaktId={konflikt.id}
          meine={konflikt.meine}
          aufSchliessen={() => setKonflikt(null)}
          aufWahl={(wahl) => void konfliktEntscheiden(wahl)}
        />
      )}

      {nachfrage}
    </div>
  )
}

/* Das Formular fuer eine Gruppe: Name plus Mehrfachauswahl aus dem Adressbuch.
 *
 * ⚠️ **Die Auswahl zeigt das ganze Adressbuch, nicht die gefilterte Liste
 * links.** Wer links nach „anna" gesucht hat, soll rechts trotzdem Bernd
 * ankreuzen koennen — deshalb holt das Formular seine Kontakte selbst und
 * bringt einen eigenen Filter mit. */
function GruppenFormular({
  gruppe,
  laeuft,
  fehler,
  meldung,
  aufSpeichern,
  aufEntfernen,
}: {
  gruppe: Gruppe | null
  laeuft: boolean
  fehler: string
  meldung: string
  aufSpeichern: (name: string, kontaktIds: number[]) => Promise<void>
  aufEntfernen?: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(gruppe?.name ?? '')
  const [gewaehlt, setGewaehlt] = useState<Set<number>>(new Set(gruppe?.mitglied_ids ?? []))
  const [alle, setAlle] = useState<Kontakt[] | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api
      .holen<Kontakt[]>('/api/kontakte')
      .then(setAlle)
      .catch(() => setAlle([]))
  }, [])

  const kern = filter.trim().toLowerCase()
  const sichtbar = (alle ?? []).filter(
    (k) =>
      !kern ||
      k.name.toLowerCase().includes(kern) ||
      k.adresse.toLowerCase().includes(kern) ||
      k.telefon.includes(kern),
  )

  return (
    <form
      className="flex max-w-[560px] flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        void aufSpeichern(name.trim(), [...gewaehlt])
      }}
    >
      <Input
        label={t('kontakte.gruppe_name')}
        value={name}
        autoFocus={gruppe === null}
        onChange={(e) => setName(e.target.value)}
      />

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('kontakte.gruppe_mitglieder')}
        </span>
        {alle !== null && alle.length === 0 ? (
          <p className="text-[13px] text-fg-4">{t('kontakte.gruppe_keine_kontakte')}</p>
        ) : (
          <div className="flex flex-col overflow-hidden rounded-md border border-line">
            <div className="border-b border-line-subtle p-2">
              <Input
                size="sm"
                placeholder={t('kontakte.gruppe_mitglieder_filtern')}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <div className="max-h-72 overflow-y-auto p-2">
              <div className="flex flex-col gap-1.5">
                {sichtbar.map((k) => (
                  <Checkbox
                    key={k.id}
                    label={beschriftung(k).titel}
                    description={beschriftung(k).unter || undefined}
                    checked={gewaehlt.has(k.id)}
                    onCheckedChange={(an) =>
                      setGewaehlt((alt) => {
                        const neu = new Set(alt)
                        if (an) neu.add(k.id)
                        else neu.delete(k.id)
                        return neu
                      })
                    }
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}
      {meldung && <p className="text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" loading={laeuft} disabled={!name.trim()}>
          {gruppe === null ? t('kontakte.anlegen') : t('kontakte.speichern')}
        </Button>
        {aufEntfernen && (
          <Button variant="danger" iconLeft={<Trash2 className="size-4" />} onClick={aufEntfernen}>
            {t('kontakte.gruppe_entfernen')}
          </Button>
        )}
      </div>
    </form>
  )
}

function Formular({
  werte,
  neu,
  laeuft,
  fehler,
  meldung,
  buecher,
  buchId,
  herkunft = '',
  nummern = [],
  adressen = [],
  aufSpeichern,
  aufVerschieben,
  aufEntfernen,
}: {
  werte: typeof LEER
  neu: boolean
  laeuft: boolean
  fehler: string
  meldung: string
  /** Alle Bücher, zur Wahl: bei einem neuen Kontakt, wo er entsteht; bei
      einem bestehenden, wohin er zieht. */
  buecher: Buch[]
  buchId: string
  /** Der Anbieter, wenn der Kontakt in einem verbundenen Buch liegt. */
  herkunft?: string
  nummern?: Karteneintrag[]
  adressen?: Karteneintrag[]
  aufSpeichern: (f: typeof LEER, buchId: string) => void
  aufVerschieben?: (buchId: string) => void
  aufEntfernen?: () => void
}) {
  const { t } = useTranslation()
  const [felder, setFelder] = useState(werte)
  /* Bei einem neuen Kontakt gehört das Buch zum Formular; bei einem
     bestehenden ist die Auswahl eine Handlung (verschieben) und zeigt den
     gespeicherten Stand. */
  const [buchNeu, setBuchNeu] = useState(buchId)

  useEffect(() => setFelder(werte), [werte])

  const setzen = (teil: Partial<typeof LEER>) => setFelder((alt) => ({ ...alt, ...teil }))
  const artText = (art: string) => t(`kontakte.art_${art}`)

  /* ⚠️ **Die Karte kennt mehr als das eine Feld.** Bei einem verbundenen
     Kontakt stehen alle Nummern und Adressen darunter, mit Beschriftung;
     sonst sieht ein Kontakt mit Handy und Festnetz aus wie halb geholt. */
  const weitere = (eintraege: Karteneintrag[], schluessel: 'nummer' | 'adresse', titel: string) =>
    eintraege.length > 1 && (
      <div className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">{titel}</span>
        <ul className="flex flex-col gap-0.5 text-[13px] text-fg-1">
          {eintraege.map((e, i) => {
            const marke = beschriftungFuer(e, artText)
            return (
              <li key={`${e[schluessel]}-${i}`} className="flex gap-2">
                <span className="w-24 shrink-0 truncate text-fg-4">{marke}</span>
                <span className={schluessel === 'adresse' ? 'font-mono' : ''}>{e[schluessel]}</span>
              </li>
            )
          })}
        </ul>
      </div>
    )

  return (
    <form
      className="flex max-w-[560px] flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        aufSpeichern(felder, neu ? buchNeu : buchId)
      }}
    >
      {/* ⚠️ Wer einen verbundenen Kontakt bearbeitet, soll wissen, dass es
          sofort beim Anbieter ankommt — bevor er speichert, nicht danach. */}
      {herkunft && (
        <p className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-[12px] leading-relaxed text-fg-3">
          <Badge tone="warning">{t('kontakte.beta')}</Badge>
          <span>
            {`${t('kontakte.aus_buch', { wo: herkunft })}. `}
            {t('kontakte.verbunden_hinweis')}
          </span>
        </p>
      )}
      {/* Das Buch steht nur zur Wahl, wenn es mehr als eines gibt: eine
          Auswahl mit einem Eintrag ist ein Klick, der nichts entscheidet. */}
      {buecher.length > 1 && (
        <Select
          label={t('kontakte.buch_feld')}
          value={neu ? buchNeu : buchId}
          onChange={(e) => {
            if (neu) setBuchNeu(e.target.value)
            else aufVerschieben?.(e.target.value)
          }}
        >
          {buecher.map((b) => (
            <option key={b.id} value={b.id}>
              {b.art ? `${b.name} · ${b.herkunft}` : b.name}
            </option>
          ))}
        </Select>
      )}
      <Input
        label={t('kontakte.adresse')}
        mono
        autoComplete="email"
        value={felder.adresse}
        onChange={(e) => setzen({ adresse: e.target.value })}
      />
      <Input
        label={t('kontakte.name')}
        value={felder.name}
        onChange={(e) => setzen({ name: e.target.value })}
      />
      <Input
        label={t('kontakte.firma')}
        value={felder.firma}
        onChange={(e) => setzen({ firma: e.target.value })}
      />
      <Input
        label={t('kontakte.telefon')}
        value={felder.telefon}
        onChange={(e) => setzen({ telefon: e.target.value })}
      />
      {weitere(nummern, 'nummer', t('kontakte.alle_nummern'))}
      {weitere(adressen, 'adresse', t('kontakte.alle_adressen'))}
      <label className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('kontakte.notiz')}
        </span>
        <textarea
          rows={4}
          value={felder.notiz}
          onChange={(e) => setzen({ notiz: e.target.value })}
          className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none disabled:opacity-60"
        />
      </label>

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}
      {meldung && <p className="text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" loading={laeuft}>
          {neu ? t('kontakte.anlegen') : t('kontakte.speichern')}
        </Button>
        {aufEntfernen && (
          <Button variant="danger" iconLeft={<Trash2 className="size-4" />} onClick={aufEntfernen}>
            {t('kontakte.entfernen')}
          </Button>
        )}
      </div>
    </form>
  )
}
