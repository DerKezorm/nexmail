/* Ein Empfängerfeld mit Vorschlägen aus dem Adressbuch.
 *
 * ⚠️ **Vorgeschlagen wird auf das letzte Bruchstück**, nicht auf den ganzen
 * Feldinhalt. „anna@x.de, ma" soll „ma" vervollständigen und „anna@x.de"
 * stehen lassen — wer den ganzen Inhalt als Suchbegriff nimmt, findet ab dem
 * zweiten Empfänger nie wieder etwas.
 *
 * ⚠️ **Die Tastatur muss reichen.** Wer Adressen tippt, hat die Hand nicht an
 * der Maus: Pfeile wählen, Eingabe und Tab übernehmen, Esc schließt. Ein
 * Vorschlagskasten, den man nur klicken kann, ist im Weg statt eine Hilfe.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { Badge } from '../ds'
import type { Gruppe, Kontakt } from '../pages/KontaktePage'

interface Props {
  wert: string
  aufAendern: (s: string) => void
  platzhalter?: string
  autoFocus?: boolean
}

/* Ein Vorschlag ist ein Kontakt oder eine Gruppe. Die Gruppe ist ein reiner
 * Eingabehelfer: Auswählen setzt ihre Mitglieder als einzelne Empfänger ein —
 * in der Mail steht von der Gruppe nichts. */
type Eintrag = { art: 'gruppe'; gruppe: Gruppe } | { art: 'kontakt'; kontakt: Kontakt }

/* ⚠️ **Der Zustand bleibt EINE Zeichenkette** (`wert`), die Blasen sind nur
 * ihre Anzeige: Alles vor dem letzten Trenner sind fertige Empfänger, der
 * Rest ist das Tippfeld. Wer die Blasen zum eigenen Zustand macht, hat zwei
 * Wahrheiten — und beim Senden fehlt dann genau die Adresse, die noch im
 * Tippfeld stand. Enter, Komma und Verlassen des Feldes schließen eine Blase
 * ab; Rückschritt im leeren Tippfeld öffnet die letzte wieder zum
 * Bearbeiten, statt sie wortlos zu löschen. */

/** Die fertigen Empfänger — alles vor dem letzten Trenner. */
function fertige(wert: string): string[] {
  const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
  if (trenner === -1) return []
  return wert
    .slice(0, trenner + 1)
    .split(/[,;]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Sieht das nach einer Adresse aus? Grob reicht: Der Server prüft richtig.
 *  Die rote Blase soll nur „test@web.de blablabla" sichtbar machen. */
function siehtAusWieAdresse(text: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text)
}

/** Das Stück hinter dem letzten Trenner — nur das wird vervollständigt. */
function bruchstueck(wert: string): string {
  const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
  return wert.slice(trenner + 1).trim()
}

function einsetzen(wert: string, adresse: string): string {
  const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
  const vorher = trenner === -1 ? '' : wert.slice(0, trenner + 1) + ' '
  return `${vorher}${adresse}, `
}

/** Alle Mitglieder einer Gruppe einsetzen — ohne die, die schon dastehen. */
function gruppeEinsetzen(wert: string, adressen: string[]): string {
  const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
  const vorher = trenner === -1 ? '' : wert.slice(0, trenner + 1)
  // ⚠️ Nur der Teil VOR dem Bruchstück zählt als „schon drin" — das
  // Bruchstück selbst ist der Suchtext und wird gleich ersetzt.
  const schonDrin = new Set(
    vorher
      .split(/[,;]/)
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  )
  const neue = adressen.filter((a) => !schonDrin.has(a))
  const anfang = vorher ? `${vorher} ` : ''
  return neue.length > 0 ? `${anfang}${neue.join(', ')}, ` : anfang
}

export function Adressfeld({ wert, aufAendern, platzhalter, autoFocus }: Props) {
  const { t } = useTranslation()
  const [vorschlaege, setVorschlaege] = useState<Eintrag[]>([])
  const [gruppen, setGruppen] = useState<Gruppe[]>([])
  const [offen, setOffen] = useState(false)
  const [aktiv, setAktiv] = useState(0)
  const eingabe = useRef<HTMLInputElement>(null)
  const uhr = useRef<number | undefined>(undefined)
  // Für welches Bruchstück die laufende Abfrage gestartet wurde. Ältere
  // Antworten werden verworfen, sonst überholt eine langsame die schnelle.
  const laeuftFuer = useRef('')

  useEffect(() => {
    // Einmal beim Öffnen des Fensters holen: Es sind eine Handvoll Gruppen,
    // und je Tastendruck nach ihnen zu fragen wäre Zeremonie. ⚠️ Leere
    // Gruppen bleiben draußen — eine Auswahl, die nichts einsetzt, sieht aus
    // wie ein Fehler.
    api
      .holen<Gruppe[]>('/api/kontakte/gruppen')
      .then((g) => setGruppen(g.filter((x) => x.adressen.length > 0)))
      .catch(() => {
        // Keine Gruppen sind kein Fehler — dann gibt es eben nur Kontakte.
      })
  }, [])

  useEffect(() => {
    window.clearTimeout(uhr.current)
    const kern = bruchstueck(wert)
    if (kern.length < 2) {
      setVorschlaege([])
      setOffen(false)
      return
    }
    uhr.current = window.setTimeout(() => {
      laeuftFuer.current = kern
      api
        .holen<Kontakt[]>(`/api/kontakte/vorschlag?anfang=${encodeURIComponent(kern)}`)
        .then((gefunden) => {
          if (laeuftFuer.current !== kern) return
          const passendeGruppen = gruppen.filter((g) =>
            g.name.toLowerCase().includes(kern.toLowerCase()),
          )
          const eintraege: Eintrag[] = [
            ...passendeGruppen.map((g) => ({ art: 'gruppe', gruppe: g }) as const),
            ...gefunden.map((k) => ({ art: 'kontakt', kontakt: k }) as const),
          ]
          setVorschlaege(eintraege)
          setAktiv(0)
          setOffen(eintraege.length > 0)
        })
        .catch(() => {
          // Ein Adressbuch, das gerade nicht antwortet, darf das Tippen nicht
          // stören. Dann gibt es eben keine Vorschläge.
          if (laeuftFuer.current === kern) setOffen(false)
        })
    }, 180)
    return () => window.clearTimeout(uhr.current)
  }, [wert, gruppen])

  function uebernehmen(eintrag: Eintrag) {
    if (eintrag.art === 'gruppe') {
      aufAendern(gruppeEinsetzen(wert, eintrag.gruppe.adressen))
    } else {
      aufAendern(einsetzen(wert, eintrag.kontakt.adresse))
    }
    setOffen(false)
    setVorschlaege([])
  }

  return (
    <div className="relative min-w-0 flex-1">
      <div
        className="flex min-w-0 flex-wrap items-center gap-1"
        onClick={() => eingabe.current?.focus()}
      >
        {fertige(wert).map((adresse, i) => (
          <span
            key={`${adresse}-${i}`}
            className={
              'inline-flex max-w-full items-center gap-1 rounded-pill py-0.5 pr-1 pl-2.5 text-[13px] ' +
              (siehtAusWieAdresse(adresse)
                ? 'bg-surface-3 text-fg-1'
                : /* ⚠️ Rot, aber stehen lassen: Wer „test@web.de blabla" tippt,
                     soll es SEHEN und wegklicken können — nicht erst beim
                     Senden eine Meldung bekommen. */
                  'bg-danger/15 text-danger')
            }
          >
            <span className="truncate">{adresse}</span>
            <button
              type="button"
              aria-label={t('verfassen.empfaenger_entfernen', { adresse })}
              title={t('verfassen.empfaenger_entfernen', { adresse })}
              onClick={(e) => {
                e.stopPropagation()
                const rest = fertige(wert).filter((_, n) => n !== i)
                aufAendern(rest.length ? `${rest.join(', ')}, ${bruchstueck(wert)}` : bruchstueck(wert))
              }}
              className="rounded-full p-0.5 leading-none transition-colors duration-[var(--dur-fast)] hover:bg-surface-2"
            >
              ×
            </button>
          </span>
        ))}

        <input
          ref={eingabe}
          value={bruchstueck(wert)}
          autoFocus={autoFocus}
          autoComplete="off"
          onChange={(e) => {
            const trenner = Math.max(wert.lastIndexOf(','), wert.lastIndexOf(';'))
            const vorher = trenner === -1 ? '' : wert.slice(0, trenner + 1) + ' '
            aufAendern(vorher + e.target.value)
          }}
          onBlur={() => {
            window.setTimeout(() => setOffen(false), 120)
            // Verlassen schließt eine angefangene Adresse ab — sonst sieht das
            // Feld leer aus, obwohl beim Senden noch etwas mitginge.
            if (bruchstueck(wert).trim()) aufAendern(`${wert.trim()}, `)
          }}
          onKeyDown={(e) => {
            if (offen && vorschlaege.length > 0) {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setAktiv((a) => (a + 1) % vorschlaege.length)
                return
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault()
                setAktiv((a) => (a - 1 + vorschlaege.length) % vorschlaege.length)
                return
              }
              if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault()
                uebernehmen(vorschlaege[aktiv])
                return
              }
              if (e.key === 'Escape') {
                // ⚠️ Nur den Kasten schließen, nicht das Fenster. Sonst kostet
                // ein Esc gegen einen Vorschlag die ganze angefangene Mail.
                e.stopPropagation()
                setOffen(false)
                return
              }
            }
            if (e.key === 'Enter' && bruchstueck(wert).trim()) {
              // Enter macht aus dem Getippten eine Blase (02.09.2026 —
              // vorher tat Enter hier schlicht nichts).
              e.preventDefault()
              aufAendern(`${wert.trim()}, `)
              return
            }
            if (e.key === 'Backspace' && bruchstueck(wert) === '') {
              const alle = fertige(wert)
              if (alle.length > 0) {
                // Die letzte Blase wieder zum Bearbeiten öffnen — löschen
                // ohne Vorwarnung wäre die unfreundlichere Deutung.
                e.preventDefault()
                const rest = alle.slice(0, -1)
                aufAendern(
                  rest.length
                    ? `${rest.join(', ')}, ${alle[alle.length - 1]}`
                    : alle[alle.length - 1],
                )
              }
            }
          }}
          /* ⚠️ Der Platzhalter verschwindet mit der ersten Blase - ohne
             aria-label hat das Feld dann KEINEN vorlesbaren Namen, und
             jeder Test wie jede Vorlesehilfe verliert es. */
          aria-label={platzhalter}
          placeholder={fertige(wert).length === 0 ? platzhalter : undefined}
          className="min-w-[10ch] flex-1 bg-transparent text-sm text-fg-1 outline-none placeholder:text-fg-4"
        />
      </div>

      {offen && (
        <ul className="absolute top-full left-0 z-10 mt-1 max-h-56 w-[320px] overflow-y-auto rounded-md border border-line bg-surface-1 py-1 shadow-[var(--shadow-2)]">
          {vorschlaege.map((eintrag, i) => (
            <li key={eintrag.art === 'gruppe' ? `g${eintrag.gruppe.id}` : `k${eintrag.kontakt.id}`}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => uebernehmen(eintrag)}
                onMouseEnter={() => setAktiv(i)}
                className={
                  'flex w-full flex-col items-start px-3 py-1.5 text-left ' +
                  (i === aktiv ? 'bg-accent-soft' : 'hover:bg-surface-2')
                }
              >
                {eintrag.art === 'gruppe' ? (
                  <span className="flex w-full items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">
                      {eintrag.gruppe.name}
                    </span>
                    {/* Erkennbar als Gruppe, samt dem, was die Auswahl tut:
                        so viele Empfänger kommen herein. */}
                    <Badge tone="accent">
                      {t('kontakte.gruppe_badge', { count: eintrag.gruppe.mitglieder })}
                    </Badge>
                  </span>
                ) : (
                  <>
                    {eintrag.kontakt.name && (
                      <span className="text-[13px] text-fg-1">{eintrag.kontakt.name}</span>
                    )}
                    <span className="text-[12px] text-fg-3">{eintrag.kontakt.adresse}</span>
                  </>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
