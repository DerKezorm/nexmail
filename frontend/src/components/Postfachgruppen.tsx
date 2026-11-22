/* Die Postfachgruppen als Reiter über der Mail-Ansicht.
 *
 * ⚠️ **Bis zum 22.11.2026 waren das Pillen oben in der Ordnerspalte.** Bei
 * sechs Gruppen brachen sie in eine zweite Zeile um, und die Spalte begann mit
 * einem Haufen kleiner Knöpfe statt mit „Alle Posteingänge" (Rückmeldung: „gefällt
 * mir nicht", Bildschirmfoto vom selben Tag). Als Reiter über allem sagen sie,
 * was sie sind: ein Umschalter für die ganze Ansicht — Baum, „Alle
 * Posteingänge", „Markierte" und die Liste. Der Zustand bleibt in `App`
 * (`nexmail.gruppe`), wie vorher.
 *
 * ⚠️ **Erst ab zwei Schlagworten.** Bei einem gäbe es nichts umzuschalten.
 * ⚠️ **Verglichen wird klein geschrieben, angezeigt die erste Schreibweise**
 * (`gruppenVon`), dieselbe Regel wie im Server; sonst stünden „Arbeit" und
 * „arbeit" als zwei Reiter da, die Verschiedenes filtern.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Konto, Ordner } from '../daten/typen'

const ALLE = '__alle__'

/** Die Gruppen in der eigenen Reihenfolge: erst, was dort steht (in dieser
 *  Folge), dann alle übrigen, wie die Postfächer stehen. Groß/klein zählt
 *  dabei nicht. Ein Wort der Reihenfolge, das keine Gruppe mehr ist, fällt weg. */
export function gruppenOrdnen(gruppen: readonly string[], reihenfolge: readonly string[]): string[] {
  const stelle = (w: string) => reihenfolge.findIndex((r) => r.toLowerCase() === w.toLowerCase())
  const bekannt = gruppen.filter((w) => stelle(w) >= 0).sort((a, b) => stelle(a) - stelle(b))
  return [...bekannt, ...gruppen.filter((w) => stelle(w) < 0)]
}

/** Eine Gruppe vor eine andere ziehen. Gezogen nach rechts landet sie hinter
 *  dem Ziel, nach links davor, wie in jeder Reiterleiste. */
export function verschoben(reihe: readonly string[], gezogen: string, ziel: string): string[] {
  const von = reihe.indexOf(gezogen)
  const nach = reihe.indexOf(ziel)
  if (von < 0 || nach < 0 || von === nach) return [...reihe]
  const neu = reihe.filter((w) => w !== gezogen)
  neu.splice(nach, 0, gezogen)
  return neu
}

/** Alle vergebenen Schlagworte der Postfächer, in ihrer Reihenfolge. */
export function gruppenVon(konten: readonly Konto[]): string[] {
  const raus: string[] = []
  for (const k of konten) {
    for (const w of k.tags ?? []) {
      if (!raus.some((v) => v.toLowerCase() === w.toLowerCase())) raus.push(w)
    }
  }
  return raus
}

export function Postfachgruppen({
  konten,
  ordner,
  gruppe,
  aufGruppe,
  reihenfolge = [],
  aufReihenfolge,
}: {
  konten: readonly Konto[]
  ordner: readonly Ordner[]
  gruppe: string
  aufGruppe: (wort: string) => void
  /** Die eigene Reihenfolge, am Konto gespeichert (`ich.gruppen_reihenfolge`). */
  reihenfolge?: readonly string[]
  /** Nach dem Ziehen: die neue Reihenfolge aller Gruppen. */
  aufReihenfolge?: (reihe: string[]) => void
}) {
  const { t } = useTranslation()
  const [gezogen, setGezogen] = useState<string | null>(null)
  const [ueber, setUeber] = useState<string | null>(null)
  const gruppen = gruppenOrdnen(gruppenVon(konten), reihenfolge)
  if (gruppen.length < 2) return null

  // Ein Schlagwort, das an keinem Postfach mehr hängt, zählt als „Alle".
  const gewaehlt = gruppen.find((w) => w.toLowerCase() === gruppe.toLowerCase()) ?? ''

  /** Ungelesenes in den Posteingängen dieser Gruppe — dieselbe Zahl, die
   *  „Alle Posteingänge" nach dem Umschalten zeigt. */
  function ungelesen(wort: string): number | undefined {
    const ids = new Set(
      konten
        .filter((k) => !wort || (k.tags ?? []).some((w) => w.toLowerCase() === wort.toLowerCase()))
        .map((k) => k.id),
    )
    const zahl = ordner
      .filter((o) => o.rolle === 'posteingang' && ids.has(o.kontoId))
      .reduce((s, o) => s + o.ungelesen, 0)
    return zahl > 0 ? zahl : undefined
  }

  const eintraege = ['', ...gruppen]

  return (
    /* ⚠️ **Sieht aus wie Reiter, nicht wie Pillen** (Skizze vom 22.11.2026): Rahmen oben, links und rechts, unten sitzt der Reiter auf der
       Linie über Ordnerspalte und Liste. Der gewählte grün und ohne Linie
       darunter, die anderen grau. Steht UNTER der Werkzeugleiste, direkt über
       dem, was er filtert.
       ⚠️ **Die Linie unten ist ein Schatten nach innen, kein Rahmen.** Mit
       Rahmen musste der gewählte Reiter 1 px darüber hinausragen, um ihn zu
       verdecken, und `overflow-x-auto` machte daraus eine winzige senkrechte
       Scrollleiste rechts (gemeldet am selben Abend). Ein Schatten nach innen
       liegt unter dem Inhalt, der Reiter deckt ihn mit seinem Grund ab. */
    <nav
      aria-label={t('ordner.gruppe_hinweis')}
      className="shrink-0 overflow-x-auto overflow-y-hidden bg-surface-2 px-3 pt-1.5 shadow-[inset_0_-1px_0_var(--color-line)]"
      data-testid="postfachgruppen"
    >
      <div role="tablist" className="flex items-end gap-1">
        {eintraege.map((w) => {
          const an = (gewaehlt || ALLE) === (w || ALLE)
          const zahl = ungelesen(w)
          /* ⚠️ **„Alle" steht fest vorn** und lässt sich weder ziehen noch als
             Ziel nehmen: Er ist kein Schlagwort, sondern der Ausweg aus jedem. */
          const ziehbar = Boolean(w) && Boolean(aufReihenfolge)
          /* ⚠️ **Gezogen wird der Rahmen um den Reiter, nicht der Knopf.** Ein
             `button[draggable]` ist in nexmail eine Mailzeile; die Tests und
             das Ziehen auf Ordner erkennen Mailzeilen genau daran. */
          return (
            <span
              key={w || ALLE}
              role="presentation"
              className="relative flex shrink-0"
              draggable={ziehbar}
              data-gruppe={w || undefined}
              onDragStart={(e) => {
                if (!ziehbar) return
                setGezogen(w)
                e.dataTransfer.effectAllowed = 'move'
                e.dataTransfer.setData('text/plain', w)
              }}
              onDragOver={(e) => {
                if (!gezogen || !w || w === gezogen) return
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                setUeber(w)
              }}
              onDragLeave={() => setUeber((u) => (u === w ? null : u))}
              onDrop={(e) => {
                e.preventDefault()
                if (gezogen && w && w !== gezogen) aufReihenfolge?.(verschoben(gruppen, gezogen, w))
                setGezogen(null)
                setUeber(null)
              }}
              onDragEnd={() => {
                setGezogen(null)
                setUeber(null)
              }}
            >
            <button
              type="button"
              role="tab"
              aria-selected={an}
              onClick={() => aufGruppe(w)}
              className={
                'relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-md border border-b-0 ' +
                'px-3 py-1 text-[12px] font-medium transition-colors duration-[var(--dur-fast)] ' +
                (an
                  ? 'z-10 border-accent bg-surface-1 text-accent-text'
                  : 'border-line bg-surface-2 text-fg-3 hover:bg-surface-3 hover:text-fg-1') +
                /* ⚠️ **Die Hand erst beim Drücken.** Ein Reiter ist zuerst ein
                   Klick; die Hand schon beim Drüberfahren sagte „nur ziehen"
                   (gemeldet am 22.11.2026). */
                (ziehbar ? ' active:cursor-grabbing' : '') +
                (gezogen === w ? ' opacity-50' : '') +
                (ueber === w ? ' ring-2 ring-accent/50' : '')
              }
            >
              {w || t('ordner.gruppe_alle')}
              {zahl !== undefined && (
                <span
                  className={
                    'rounded-pill px-1.5 text-[10px] leading-4 tabular-nums ' +
                    (an ? 'bg-accent-soft text-accent-text' : 'bg-surface-3 text-fg-3')
                  }
                >
                  {zahl}
                </span>
              )}
            </button>
            </span>
          )
        })}
      </div>
    </nav>
  )
}
