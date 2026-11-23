/* Die Werkzeugleiste der Ansichten ohne eigene: Kalender, Aufgaben, Kontakte
 * und die Einstellungen. Gebaut wie die der Mail (`Kopfleiste`):
 * Seitenleisten-Knopf, die Ansichten, die eine Hauptaktion als grüner Knopf,
 * die Suche, rechts was zur Ansicht gehört.
 *
 * ⚠️ **Die Ansichtsknöpfe stehen hier an derselben Stelle wie in der Mail.**
 * Wo es keine Seitenleiste gibt, hält ein leerer Platz derselben Breite sie
 * dort. Ein Umschalter, der je Ansicht ein Stück springt, will jedes Mal neu
 * gesucht werden.
 * ⚠️ **Die Hauptaktion steht IMMER hier oben** („Neue Nachricht", „Neuer
 * Termin", „Neuer Kontakt"), nie unten in einer Spalte (gemeldet am
 * 23.11.2026: „Bitte IMMER nach da oben").
 */
import type { ReactNode } from 'react'

interface Props {
  /** Der Knopf der Seitenleiste. Fehlt er, hält ein Platz seine Breite;
   *  `null` heißt: auch kein Platz (schmal, dort gibt es keine Spalte). */
  seitenleiste?: ReactNode | null
  ansichtswahl: ReactNode
  /** Die Hauptaktion der Ansicht. */
  haupt?: ReactNode
  /** Das Suchfeld; es nimmt den freien Platz. */
  suche?: ReactNode
  /** Was rechts steht (Abgleichen, Umschalter der Ansicht). */
  rechts?: ReactNode
}

export function Ansichtsleiste({ seitenleiste, ansichtswahl, haupt, suche, rechts }: Props) {
  return (
    <header className="flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-line-subtle bg-surface-1 px-3">
      {seitenleiste === undefined ? <span aria-hidden className="size-[34px] shrink-0" /> : seitenleiste}
      {ansichtswahl}
      {haupt}
      {suche ? <div className="flex min-w-0 flex-1">{suche}</div> : <span className="flex-1" />}
      {rechts}
    </header>
  )
}

/** Was eine Ansicht von `App` bekommt, um Leiste und Spalte zu bauen. */
export interface Ansichtsrahmen {
  schmal: boolean
  /** Die Werkzeugleiste mit dem, was die Ansicht beiträgt. */
  kopf: (teile: Omit<Props, 'seitenleiste' | 'ansichtswahl'>) => ReactNode
  /** Die Seitenspalte samt Griff und Profilzeile; nichts, wenn sie
   *  eingeklappt ist oder die Ansicht schmal. */
  spalte: (inhalt: ReactNode) => ReactNode
  /** Steht hier etwas, nimmt es den Platz rechts der Seitenspalte ein: die
   *  Einstellungen, geöffnet aus dieser Ansicht (seit 23.11.2026, wie die
   *  Mail mit der Ordnerspalte). Die Spalte bleibt stehen. */
  ersatz?: ReactNode
  /** Zurück in diese Ansicht, etwa nach einem Klick in die Seitenspalte,
   *  während daneben die Einstellungen stehen. */
  zeigen: () => void
}
