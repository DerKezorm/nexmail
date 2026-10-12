/* „Was ist neu“: je Version ein geschriebener Text, nach dem Vorbild von
 * nexdiary und nexlore. Die Texte liegen in `i18n/wasneu/<sprache>.json`,
 * mit der Version als Schlüssel („0.24.0“), und werden erst geholt, wenn sie
 * gebraucht werden: Ein Konto liest sie einmal nach einem Update.
 *
 * ⚠️ **Ein Eintrag hat vier Felder**: `lead`, `sections` (je `title`, `where`,
 * `body`), `smallTitle` und `small`. Einer in anderer Form wird weggelassen,
 * nie halb gezeigt. Das Schweigen ist für Bugfix-Versionen gewollt (ohne Text
 * kein Banner) und für einen Tippfehler gefährlich: In Nexview fehlte so
 * zweimal der Text einer ganzen Version, ohne dass es jemand merkte. Deshalb
 * prüfen `wasneu.test.ts` und `backend/tests/test_wasneu.py` jeden Eintrag,
 * und eine Version auf `.0` gibt es nicht ohne ihren Text.
 */
import { useEffect, useState } from 'react'

export interface WasNeuAbschnitt {
  title: string
  /** Wo man es in der Oberfläche findet. */
  where: string
  body: string
}

export interface WasNeuEintrag {
  lead: string
  sections: WasNeuAbschnitt[]
  /** Überschrift über den Kleinigkeiten, meist „Außerdem“. */
  smallTitle: string
  small: string[]
}

type Eintraege = Record<string, WasNeuEintrag>
export type WasNeuSprache = 'de' | 'en'

/* Statisch, damit Vite je Sprache ein eigenes Stück baut, wie bei
   `i18n/index.ts`. */
const DATEIEN: Record<WasNeuSprache, () => Promise<{ default: Record<string, unknown> }>> = {
  de: () => import('../i18n/wasneu/de.json'),
  en: () => import('../i18n/wasneu/en.json'),
}

function istText(wert: unknown): wert is string {
  return typeof wert === 'string' && wert.trim() !== ''
}

export function istEintrag(wert: unknown): wert is WasNeuEintrag {
  if (!wert || typeof wert !== 'object') return false
  const e = wert as Partial<WasNeuEintrag>
  return (
    istText(e.lead) &&
    Array.isArray(e.sections) &&
    e.sections.length > 0 &&
    e.sections.every((a) => !!a && istText(a.title) && istText(a.where) && istText(a.body)) &&
    istText(e.smallTitle) &&
    Array.isArray(e.small) &&
    e.small.every(istText)
  )
}

/** Deutsch für Deutsch, Englisch für jede andere Sprache. */
export function dateiFuer(sprache: string): WasNeuSprache {
  return sprache.split('-')[0] === 'de' ? 'de' : 'en'
}

/** Nur die Einträge, die alle vier Felder tragen. */
export function gueltige(alle: Record<string, unknown>): Eintraege {
  return Object.fromEntries(
    Object.entries(alle).filter((paar): paar is [string, WasNeuEintrag] => istEintrag(paar[1])),
  )
}

const geladen = new Map<WasNeuSprache, Promise<Eintraege>>()

function eintraegeFuer(sprache: string): Promise<Eintraege> {
  const datei = dateiFuer(sprache)
  let eintraege = geladen.get(datei)
  if (!eintraege) {
    eintraege = DATEIEN[datei]().then(
      ({ default: alle }) => gueltige(alle),
      () => ({}),
    )
    geladen.set(datei, eintraege)
  }
  return eintraege
}

/** Der Eintrag einer Version in der Sprache der Seite, oder `null`. */
export function useWasNeu(version: string | undefined, sprache: string): WasNeuEintrag | null {
  const [stand, setStand] = useState<{ schluessel: string; eintrag: WasNeuEintrag | null } | null>(
    null,
  )
  const schluessel = `${dateiFuer(sprache)}:${version ?? ''}`
  useEffect(() => {
    if (!version) return
    let lebt = true
    void eintraegeFuer(sprache).then((eintraege) => {
      if (lebt) setStand({ schluessel, eintrag: eintraege[version] ?? null })
    })
    return () => {
      lebt = false
    }
  }, [schluessel, sprache, version])
  return stand?.schluessel === schluessel ? stand.eintrag : null
}
