/* Die Postfächer als Kacheln, mit einer (+)-Kachel am Ende.
 *
 * ⚠️ **Kacheln statt Liste, weil es hier nicht mehr nur IMAP gibt.** Eine
 * Zeile trägt Name, Adresse, Server und zwei Knöpfe — woher das Postfach
 * kommt, hätte darin keinen Platz mehr. Auf der Kachel steht es oben rechts,
 * und die (+)-Kachel ist der eine Weg hinein, egal welcher Anbieter.
 *
 * Übernommen aus Nexview (Benachrichtigungs-Ziele), auf nexmails Bausteine
 * gesetzt — dieselbe Bedienung an beiden Stellen ist mehr wert als eine
 * eigene Idee.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Folder, Pencil, Plus, Trash2 } from 'lucide-react'
import { Badge, IconButton } from '../ds'
import { useNachfrage } from './Nachfrage'
import { PUNKT_KLASSE } from '../lib/farben'
import { api } from '../api/client'
import type { KontoZeile } from '../api/client'

/** Wie ein Anbieter auf der Kachel heißt. Leer = gewöhnliches IMAP-Postfach. */
const ANBIETER: Record<string, string> = {
  google: 'Google',
  microsoft: 'Microsoft',
}

interface Props {
  konten: KontoZeile[]
  aufHinzufuegen: () => void
  aufBearbeiten: (konto: KontoZeile) => void
  aufNeuLaden: () => void
}

export function Postfachkacheln({ konten, aufHinzufuegen, aufBearbeiten, aufNeuLaden }: Props) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [entfernt, setEntfernt] = useState<string | null>(null)

  async function entfernen(konto: KontoZeile) {
    /* ⚠️ **Die Kalender hängen an der Zustimmung, nicht am Postfach.** Sie
       stillschweigend mitzunehmen wäre falsch, sie stillschweigend stehen zu
       lassen aber auch: Wer beides in einem Zug angelegt hat, hält den
       Kalender danach für ein Waisenkind. Also fragen — vorbelegt mit aus. */
    const kalender = konto.oauth_kalender ?? 0
    const antwort = await fragen({
      titel: t('konto.entfernen'),
      text: t('konto.entfernen_sicher', { name: konto.anzeigename }),
      knopf: t('konto.entfernen'),
      gefaehrlich: true,
      haken: kalender
        ? { beschriftung: t('konto.kalender_mit_entfernen', { count: kalender }) }
        : undefined,
    })
    const ja = antwort === true || (typeof antwort === 'object' && antwort?.ja === true)
    if (!ja) return
    const mit = typeof antwort === 'object' && antwort !== null && 'haken' in antwort && antwort.haken
    setEntfernt(konto.id)
    try {
      await api.loeschen(`/api/konten/${konto.id}${mit ? '?kalender_mit=true' : ''}`)
      aufNeuLaden()
    } finally {
      setEntfernt(null)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {konten.map((k) => (
        <section
          key={k.id}
          className="flex min-h-[132px] flex-col gap-2 rounded-xl border border-line bg-surface-1 px-4 py-3"
        >
          <div className="flex min-w-0 items-start gap-2">
            <span
              aria-hidden
              className={`mt-1.5 size-2.5 shrink-0 rounded-full ${PUNKT_KLASSE[k.farbe as 1 | 2 | 3 | 4 | 5 | 6]}`}
            />
            <div className="min-w-0 flex-1">
              <p className="mb-0 truncate text-sm font-medium text-fg-1">{k.anzeigename}</p>
              <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{k.adresse}</p>
            </div>
            {/* Woher das Postfach kommt. Ohne das sähe ein Google-Postfach aus
                wie jedes andere — und niemand wüsste, warum es keine
                Passwortfelder hat. */}
            {ANBIETER[k.oauth_art ?? ''] && (
              <Badge tone="info">{ANBIETER[k.oauth_art ?? '']}</Badge>
            )}
          </div>

          {/* ⚠️ **Die Schlagworte gehören nach oben, nicht unter die
              Serverzeile.** Wer hier steht, will wissen, welches Postfach zu
              welcher Welt gehört — das ist eine Eigenschaft des Postfachs,
              keine Fußnote zur Technik. */}
          {(k.tags ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1">
              {(k.tags ?? []).map((w) => (
                <span
                  key={w}
                  className="rounded-pill bg-accent-soft px-2 py-0.5 text-[11px] text-accent-text"
                >
                  {w}
                </span>
              ))}
            </div>
          )}

          <p className="mb-0 flex items-center gap-1.5 truncate text-[11px] text-fg-4">
            <Folder aria-hidden className="size-3.5 shrink-0" />
            <span className="truncate">
              {t('konto.ordner_gefunden', { count: k.anzahl_ordner })}
              {' · '}
              {k.zuletzt_geprueft
                ? t('konto.geprueft_am', {
                    wann: new Date(k.zuletzt_geprueft).toLocaleString(i18n.language, {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    }),
                  })
                : t('konto.nie_geprueft')}
            </span>
          </p>

          <div className="mt-auto flex items-center gap-2 border-t border-line-subtle pt-2">
            {k.letzter_fehler ? (
              /* ⚠️ **Übersetzt über die Kennung, ganzer Satz als title.** Ein
                 deutscher Server-Satz bliebe auf Englisch deutsch, und
                 `slice(0, 40)` schnitt ihn mitten im Wort ab („abgewie"). */
              <Badge tone="danger" dot title={k.letzter_fehler}>
                <span className="max-w-40 truncate">
                  {k.letzter_fehler_art
                    ? t(`konto.fehler_${k.letzter_fehler_art}`, { defaultValue: k.letzter_fehler })
                    : k.letzter_fehler}
                </span>
              </Badge>
            ) : (
              <Badge tone="success" dot>
                {t('einstellungen.aktiv')}
              </Badge>
            )}
            <span className="flex-1" />
            <IconButton
              icon={<Pencil />}
              label={t('einstellungen.bearbeiten')}
              size="sm"
              onClick={() => aufBearbeiten(k)}
            />
            <IconButton
              icon={<Trash2 />}
              label={t('einstellungen.entfernen')}
              size="sm"
              disabled={entfernt === k.id}
              onClick={() => void entfernen(k)}
            />
          </div>
        </section>
      ))}

      <button
        type="button"
        onClick={aufHinzufuegen}
        className="flex min-h-[132px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-surface-1/40 px-4 py-3 text-center text-fg-3 transition-colors duration-[var(--dur-fast)] hover:border-accent hover:text-fg-1"
      >
        <Plus aria-hidden className="size-6" />
        <span className="text-[13px] font-medium">{t('konto.hinzufuegen')}</span>
      </button>

      {nachfrage}
    </div>
  )
}
