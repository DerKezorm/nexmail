/* Die Mail-Ansicht.
 *
 * Breit: Ordner | Liste | Lesebereich, mit ziehbaren Griffen dazwischen.
 * Schmal: zwei Ebenen - Liste, dann Nachricht - und die Ordner liegen in
 * einer Schublade von links. Kein drittes Layout dazwischen: Wer bei 1000 px
 * eine Sonderform baut, pflegt danach drei.
 */
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, X } from 'lucide-react'
import { AusgangListe } from '../components/AusgangListe'
import { Griff } from '../components/Griff'
import { Lesebereich } from '../components/Lesebereich'
import { Nachrichtenliste } from '../components/Nachrichtenliste'
import type { Wischen } from '../components/Nachrichtenliste'
import { Ordnerspalte } from '../components/Ordnerspalte'
import type { Ziel } from '../components/Ordnerspalte'
import type { MenueEintrag } from '../components/Kontextmenue'
import { IconButton } from '../ds'
import type { Ausgangseintrag, Konto, Nachricht, Ordner, Schlagwort } from '../daten/typen'
import type { VolleNachricht } from '../api/laden'
import type { Verfassart } from '../components/VerfassenFenster'

interface Props {
  konten: Konto[]
  ordner: Ordner[]
  nachrichten: Nachricht[]
  /** Die geoeffnete Nachricht - mit Koerper, Anhaengen und Bildstand. */
  offene: VolleNachricht | null
  offeneLaedt: boolean
  ziel: Ziel
  aufZiel: (z: Ziel) => void
  gewaehlt: string | null
  aufWahl: (id: string | null, mitStrg?: boolean, mitUmschalt?: boolean) => void
  mehrfach: string[]
  suche: string
  /** Das Ergebnis der Serversuche. `null` heißt: es wird gerade nicht gesucht. */
  suchbefund: { treffer: Nachricht[]; vollstaendig: boolean } | null
  suchtLaeuft?: boolean
  /** „Auch beim Anbieter suchen" — dauert, deshalb nur auf Klick. */
  aufAnbietersuche?: () => void
  ordnerBreite: number
  aufOrdnerBreite: (b: number) => void
  listeBreite: number
  aufListeBreite: (b: number) => void
  ordnerOffen: boolean
  schmal: boolean
  schubladeOffen: boolean
  aufSchublade: (offen: boolean) => void
  aufVerfassen: (art: Verfassart, n: Nachricht | null) => void
  /** Ziehen beginnt — welche Nachrichten kommen mit? */
  aufZiehen?: (n: Nachricht) => string[]
  kompakt?: boolean
  anreisserZeigen?: boolean
  punkteZeigen?: boolean
  /** Gewähltes Schlagwort. Leer heißt: alle Postfächer. */
  gruppe: string
  aufGruppe: (wort: string) => void
  aufMehr?: () => void
  mehrLaedt?: boolean
  amEnde?: boolean
  gruppiert?: boolean
  aufGruppiert?: (an: boolean) => void
  aufStrang?: (schluessel: string) => Promise<Nachricht[]>
  /** Wisch-Aktionen — `App` reicht sie nur in der schmalen Ansicht herein. */
  wischen?: Wischen
  filter?: 'alle' | 'ungelesen' | 'markiert'
  aufFilter?: (f: 'alle' | 'ungelesen') => void
  /** Die Schlagwort-Definitionen — Marken in Liste und Lesebereich. */
  schlagworte?: Schlagwort[]
  /** Gewähltes Schlagwort-Atom der Filterzeile. Leer heißt: alle. */
  schlagwortFilter?: string
  aufSchlagwortFilter?: (atom: string) => void
  /** Ein Schlagwort an einer Mail umschalten (Lesebereich). */
  aufSchlagwort?: (n: Nachricht, atom: string, setzen: boolean) => void
  aufNeuesSchlagwort?: (n: Nachricht) => void
  /** Fallengelassen über einem Ordner. */
  aufAblegen?: (ordnerId: string, ids: string[]) => void
  /** Aus welchem Postfach gerade gezogen wird. */
  ziehtAusKonto?: string
  aufAbweisung?: (grund: string) => void
  /** Liegt die geöffnete Nachricht im Entwurfsordner? */
  istEntwurf?: boolean
  aufPostfachHinzufuegen: () => void
  aufNachrichtKontext: (e: React.MouseEvent, n: Nachricht) => void
  aufOrdnerKontext: (e: React.MouseEvent, o: Ordner) => void
  favoriten: string[]
  eingeklappt: string[]
  aufEinklappen: (kontoId: string) => void
  /** Der Postausgang — geplante und liegen gebliebene Sendungen. */
  ausgaenge: Ausgangseintrag[]
  aufAusgangAbbrechen: (eintrag: Ausgangseintrag) => void
  /** Wartende Wiedervorlage-Eintraege je Postfach (kontoId → Zahl). */
  wiedervorlageZahlen?: Record<string, number>
  /** Aufwach-Zeitpunkte je Nachricht-Kennung (ISO) — Marken in der Liste. */
  aufwachZeiten?: Record<string, string>
  /** Das Untermenü „Wiedervorlage" für „Weitere Aktionen" im Lesebereich. */
  wiedervorlageMenue?: (n: Nachricht) => MenueEintrag[]
}

export function MailPage(p: Props) {
  const { t } = useTranslation()

  // Einmal herausgezogen: TypeScript verliert die Einengung von p.ziel,
  // sobald sie durch eine Rueckruffunktion muss - und "p" koennte sich
  // theoretisch zwischendurch aendern. Eine lokale Konstante kann das nicht.
  const ziel = p.ziel

  const sichtbar = useMemo(() => {
    // ⚠️ **Bei einer Suche kommt die Liste aus dem Server, nicht von hier.**
    // Der Browser hält 200 Zeilen des aktuellen Ordners; darin zu filtern
    // fände fast nichts von dem, was jemand sucht — und zwar lautlos.
    if (p.suchbefund) return p.suchbefund.treffer

    // ⚠️ **Bei „Markierte" nicht örtlich filtern.** Der Server hat schon
    // postfachübergreifend gesucht; hier noch einmal nach Ordner zu sieben
    // würde genau das wieder wegwerfen.
    if (ziel.typ === 'markiert') return p.nachrichten

    // Beim Ausgang zeigt die Spalte keine Nachrichten - siehe `listenspalte`.
    if (ziel.typ === 'ausgang') return []

    return ziel.typ === 'alle'
      ? p.nachrichten.filter((n) => {
          const o = p.ordner.find((x) => x.id === n.ordnerId)
          return o?.rolle === 'posteingang'
        })
      : p.nachrichten.filter((n) => n.ordnerId === ziel.id)
  }, [p.nachrichten, p.ordner, ziel, p.suchbefund])

  const titel = p.suchbefund
    ? t('suche.treffer', { count: p.suchbefund.treffer.length })
    : ziel.typ === 'alle'
      ? t('ordner.alle_posteingaenge')
      : ziel.typ === 'markiert'
        ? t('ordner.markierte')
        : ziel.typ === 'ausgang'
          ? t('ordner.postausgang')
          : (p.ordner.find((o) => o.id === ziel.id)?.name ?? '')

  /* ⚠️ **Der Hinweis ist Pflicht, nicht Zierde.** nexmail hält alle Kopfdaten,
     aber Texte nur von dem, was schon einmal geöffnet wurde. Eine Suche, die
     das verschweigt, lässt aus null Treffern schließen, dass es die Mail nicht
     gibt — dabei wurde nur nie hineingesehen. */
  const hinweis =
    p.suchbefund && !p.suchbefund.vollstaendig ? (
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line-subtle bg-surface-2 px-3 py-2 text-[12px] text-fg-3">
        <span>{t('suche.nur_zwischenspeicher')}</span>
        <button
          type="button"
          onClick={p.aufAnbietersuche}
          disabled={p.suchtLaeuft}
          className="rounded-sm px-1.5 py-0.5 font-medium text-accent-text underline underline-offset-2 hover:bg-surface-3 disabled:opacity-60"
        >
          {p.suchtLaeuft ? t('suche.laeuft') : t('suche.beim_anbieter')}
        </button>
      </div>
    ) : null

  const offene = p.offene

  /* Die mittlere Spalte. Beim Ziel „ausgang" zeigt sie die Warteschlange
     statt eines Ordners — einmal gebaut, damit schmal und breit nicht
     auseinanderlaufen. */
  const listenspalte =
    ziel.typ === 'ausgang' ? (
      <AusgangListe eintraege={p.ausgaenge} aufAbbrechen={p.aufAusgangAbbrechen} />
    ) : (
      <Nachrichtenliste
        nachrichten={sichtbar}
        konten={p.konten}
        gewaehlt={p.gewaehlt}
        aufWahl={p.aufWahl}
        mehrfach={p.mehrfach}
        postfachZeigen={ziel.typ !== 'ordner' && p.punkteZeigen !== false}
        titel={titel}
        aufKontext={p.aufNachrichtKontext}
        aufZiehen={p.aufZiehen}
        kompakt={p.kompakt}
        anreisserZeigen={p.anreisserZeigen}
        filter={ziel.typ === 'markiert' ? 'markiert' : p.filter}
        aufFilter={p.aufFilter}
        schlagworte={p.schlagworte}
        schlagwortFilter={p.schlagwortFilter}
        aufSchlagwortFilter={p.aufSchlagwortFilter}
        aufMehr={p.aufMehr}
        mehrLaedt={p.mehrLaedt}
        amEnde={p.amEnde}
        gruppiert={p.gruppiert}
        aufGruppiert={p.aufGruppiert}
        aufStrang={p.aufStrang}
        wischen={p.wischen}
        aufwachZeiten={p.aufwachZeiten}
      />
    )

  const ordnerspalte = (
    <Ordnerspalte
      gruppe={p.gruppe}
      aufGruppe={p.aufGruppe}
      ausgangZahl={p.ausgaenge.length}
      wiedervorlageZahlen={p.wiedervorlageZahlen}
      konten={p.konten}
      ordner={p.ordner}
      ziel={ziel}
      aufZiel={(z) => {
        p.aufZiel(z)
        p.aufWahl(null)
        p.aufSchublade(false)
      }}
      aufPostfachHinzufuegen={p.aufPostfachHinzufuegen}
      aufKontext={p.aufOrdnerKontext}
      favoriten={p.favoriten}
      aufAblegen={p.aufAblegen}
      ziehtAusKonto={p.ziehtAusKonto}
      aufAbweisung={p.aufAbweisung}
      eingeklappt={p.eingeklappt}
      aufEinklappen={p.aufEinklappen}
    />
  )

  /* --- Schmal: zwei Ebenen ------------------------------------------- */
  if (p.schmal) {
    return (
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {p.gewaehlt !== null ? (
          <div className="flex h-full flex-col">
            <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line-subtle bg-surface-1 px-2">
              <IconButton icon={<ArrowLeft />} label={t('aktion.zurueck')} onClick={() => p.aufWahl(null)} />
              <span className="truncate text-[13px] text-fg-3">{titel}</span>
            </div>
            <div className="min-h-0 flex-1">
              <Lesebereich
                nachricht={offene}
                laedt={p.offeneLaedt}
                aufVerfassen={(art, n) => p.aufVerfassen(art, n)}
                istEntwurf={p.istEntwurf}
                schlagworte={p.schlagworte}
                aufSchlagwort={p.aufSchlagwort}
                aufNeuesSchlagwort={p.aufNeuesSchlagwort}
                wiedervorlageMenue={p.wiedervorlageMenue}
              />
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col">
            {hinweis}
            {listenspalte}
          </div>
        )}

        {/* Die Schublade. Sie schiebt sich ueber die Liste, statt sie zur
            Seite zu draengen - auf 390 px bliebe daneben nichts uebrig. */}
        <div
          hidden={!p.schubladeOffen}
          className="absolute inset-0 z-40 bg-[var(--surface-overlay)]"
          onClick={() => p.aufSchublade(false)}
        />
        <aside
          className={
            'absolute inset-y-0 left-0 z-40 flex w-[280px] max-w-[85vw] flex-col border-r border-line bg-surface-1 ' +
            'shadow-[var(--shadow-3)] transition-transform duration-[var(--dur-mid)] ' +
            (p.schubladeOffen ? 'translate-x-0' : '-translate-x-full')
          }
          aria-hidden={!p.schubladeOffen}
        >
          <div className="flex h-10 shrink-0 items-center justify-between border-b border-line-subtle px-2">
            <span className="px-1 font-display text-[15px] text-fg-1">nexmail</span>
            <IconButton
              icon={<X />}
              label={t('aktion.schliessen')}
              size="sm"
              onClick={() => p.aufSchublade(false)}
            />
          </div>
          <div className="min-h-0 flex-1">{ordnerspalte}</div>
        </aside>
      </div>
    )
  }

  /* --- Breit: drei Spalten mit Griffen -------------------------------- */
  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {p.ordnerOffen && (
        <>
          <div style={{ width: p.ordnerBreite }} className="shrink-0 border-r border-line-subtle">
            {ordnerspalte}
          </div>
          <Griff
            breite={p.ordnerBreite}
            aufBreite={p.aufOrdnerBreite}
            min={180}
            max={380}
            label={t('griff.ordner')}
          />
        </>
      )}

      <div style={{ width: p.listeBreite }} className="flex shrink-0 flex-col">
        {hinweis}
        {listenspalte}
      </div>
      <Griff
        breite={p.listeBreite}
        aufBreite={p.aufListeBreite}
        min={280}
        max={560}
        label={t('griff.liste')}
      />

      <div className="min-w-0 flex-1">
        <Lesebereich
          nachricht={offene}
          laedt={p.offeneLaedt}
          aufVerfassen={(art, n) => p.aufVerfassen(art, n)}
          istEntwurf={p.istEntwurf}
          schlagworte={p.schlagworte}
          aufSchlagwort={p.aufSchlagwort}
          aufNeuesSchlagwort={p.aufNeuesSchlagwort}
          wiedervorlageMenue={p.wiedervorlageMenue}
        />
      </div>
    </div>
  )
}
