/* Server › Speicher und Sicherung: die Seite des gemeinsamen Moduls sicherung (`vendor/nexsicherung`, bauplaene/
 * sicherung 1.0.1) aus dem Bausatz: Karte „Speicher" und Karte „Sicherung" (Automatisch Aus / Jede Nacht / Jede Woche /
 * Jeden Monat, Uhrzeit, Behalten, Jetzt sichern, Hochladen, je Sicherung Prüfen, Herunterladen, Wiederherstellen,
 * Löschen).
 *
 * nexmail behält zwei Eigenheiten (E22): Herunterladen fragt ein eigenes Passwort für die Datei und gibt das schlanke,
 * verschlüsselte Archiv hinaus (ohne Nachrichten, die das Postfach wieder hergibt); Wiederherstellen geschieht sofort,
 * danach ist jede Sitzung weg, auch die eigene. Ein hochgeladenes verschlüsseltes Archiv fragt beim Prüfen nach seinem
 * Passwort und nennt, was dabei ist: Schlüssel, die öffentliche Adresse im Archiv, die Anmeldeanbieter.
 */
import { useTranslation } from 'react-i18next'

import type { Ich } from '../api/client'
import { BASIS } from '../lib/basis'
import { zeitpunkt } from '../lib/format'
import { StorageArea } from '../vendor/nexsicherung/StorageArea'
import { makeSicherungApi, type Brief } from '../vendor/nexsicherung/sicherung'
import { Notice } from '../vendor/nexui'

const api = makeSicherungApi((pfad, init) => fetch(`${BASIS}${pfad}`, { ...init, credentials: 'include' }))

type Anbieter = { kuerzel: string; anzeigename: string; issuer: string; rueckkehr_adresse?: string; rueckkehr_adresse_archiv?: string }

export function Sicherungen({ ich }: { ich: Ich | null }) {
  const { t, i18n } = useTranslation()
  const sprache = (['de', 'en', 'fr'].includes(i18n.language) ? i18n.language : 'en') as 'de' | 'en' | 'fr'

  function befund(brief: Brief) {
    const d = brief.details as Record<string, unknown>
    if (!d || !('schluessel_dabei' in d)) return null
    const anbieter = (d.oidc_anbieter as Anbieter[] | undefined) ?? []
    return (
      <>
        <p className="m-0 text-sm">
          {t('sicherungen.schluessel')}: {d.schluessel_dabei ? t('sicherungen.schluessel_dabei') : t('sicherungen.schluessel_fehlt')}
        </p>
        {Boolean(d.adresse_weicht_ab) && (
          <Notice tone="warn">
            {t('sicherungen.adresse_anders')}: {String(d.adresse_im_archiv)}. {t('sicherungen.adresse_neu_folge')}
          </Notice>
        )}
        {anbieter.length > 0 && (
          <>
            <p className="m-0 text-sm">{t('sicherungen.oidc_titel')}:</p>
            {/* Wie die alte Seite: je Anbieter die Adresse, die bei ihm stehen muss (E38); weicht die Adresse ab, auch
                die mit der Adresse aus der Sicherung, je nachdem, was unten angekreuzt ist. */}
            <ul className="m-0 pl-5 text-sm" data-testid="sicherung-rueckkehr">
              {anbieter.map((a) => (
                <li key={a.kuerzel} className="break-all">
                  {t('sicherungen.rueckkehr', { name: a.anzeigename || a.kuerzel, jetzt: a.rueckkehr_adresse || a.issuer })}
                  {Boolean(d.adresse_weicht_ab) && a.rueckkehr_adresse_archiv
                    ? `, ${t('sicherungen.rueckkehr_archiv', { archiv: a.rueckkehr_adresse_archiv })}`
                    : ''}
                </li>
              ))}
            </ul>
          </>
        )}
      </>
    )
  }

  return (
    <StorageArea
      app="nexmail"
      things={t('einstellungen.dinge')}
      holds={t('speicher.enthaelt')}
      api={api}
      password={ich?.hat_kennwort !== false}
      details={befund}
      language={sprache}
      // Zeiten in der Zone, die unter Darstellung eingestellt ist, wie sonst in nexmail.
      when={(iso, sprache) => zeitpunkt(iso, sprache)}
      // E38: nexmails Frage beim Wiederherstellen, wie auf dem alten Weg (Adresse aus dem Archiv oder die jetzige).
      restoreOptions={[{ key: 'address', label: t('sicherungen.adresse_uebernehmen'), hint: t('sicherungen.adresse_uebernehmen_hinweis') }]}
    />
  )
}
