/* Der Weg zum Server.
 *
 * Ein einziger Ort, an dem Adressen gebaut und Fehler gedeutet werden.
 * Zwei Dinge sind hier wichtig und leicht zu vergessen:
 *
 * 1. **`credentials: 'include'`** — ohne das faehrt das Sitzungs-Cookie im
 *    Entwicklungsbetrieb nicht mit (Oberflaeche auf 5175, Server auf 8000),
 *    und man sucht den Fehler in der Anmeldung statt im fetch-Aufruf.
 * 2. **Der Vorbau.** Laeuft nexmail unter einem Unterpfad
 *    (`https://mail.example.org/nexmail`), muss die Oberflaeche ihn mitschicken.
 *
 *    ⚠️ **Er kommt vom Server, nicht aus dem Bau.** Vite traegt `BASE_URL`
 *    beim Bauen ein — ein Abbild waere damit fuer **einen** Pfad gebaut, und
 *    wer nexmail unter `/mail` betreibt statt unter `/nexmail`, braeuchte ein
 *    eigenes. Deshalb schreibt der Server beim Start `window.__NEXMAIL_BASIS__`
 *    in die `index.html`, und hier gilt dieser Wert zuerst. `BASE_URL` bleibt
 *    der Rueckfall fuer den Entwicklungsbetrieb.
 */

export class ApiFehler extends Error {
  constructor(
    readonly status: number,
    /** Die **Kennung** des Fehlers, kein fertiger Satz. */
    readonly detail: string,
    /** Sekunden bis zum naechsten Versuch — nur bei 429. */
    readonly wartenSekunden?: number,
    /* ⚠️ **Die Zahlen und Namen aus der Meldung.** „Der Name ist laenger
       als 40 Zeichen" ist `ordner_name_zu_lang` mit `{ max: 40 }`; den Satz
       baut `lib/servermeldung.ts`. Sie reisen in einem eigenen Feld neben
       `detail`, damit dieses eine Zeichenkette bleibt — 73 Stellen lesen sie
       so, und sie alle auf einmal umzubauen waere der teurere Weg. */
    readonly werte: Record<string, unknown> = {},
  ) {
    super(detail)
  }
}

import { BASIS } from '../lib/basis'

async function anfrage<T>(pfad: string, init?: RequestInit): Promise<T> {
  // ⚠️ **Bei FormData darf kein content-type gesetzt werden.** Der Browser
  // baut ihn selbst und hängt die `boundary` an, ohne die der Server den
  // Rumpf nicht zerlegen kann. Ein eigener Wert bricht den Upload — und der
  // Fehler kommt als „Feld fehlt", nicht als „Kopfzeile falsch".
  const istFormular = init?.body instanceof FormData
  const antwort = await fetch(`${BASIS}${pfad}`, {
    ...init,
    credentials: 'include',
    headers: istFormular
      ? { ...(init?.headers ?? {}) }
      : { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })

  if (antwort.status === 204) return undefined as T

  let daten: unknown = null
  try {
    daten = await antwort.json()
  } catch {
    // Eine Antwort ohne JSON ist bei einem Fehler normal (502 vom Proxy).
  }

  if (!antwort.ok) {
    const detail =
      (daten as { detail?: unknown } | null)?.detail
    const text =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? // Pydantic meldet Feldfehler als Liste. Fuer die Oberflaeche
            // zaehlt die erste Meldung; alles andere waere Fachchinesisch.
            String((detail[0] as { msg?: string })?.msg ?? '')
          : ''
    const warten = antwort.headers.get('retry-after')
    const werte = (daten as { werte?: Record<string, unknown> } | null)?.werte ?? {}
    throw new ApiFehler(
      antwort.status,
      text,
      warten ? Number(warten) : undefined,
      werte,
    )
  }

  return daten as T
}

export const api = {
  holen: <T>(pfad: string) => anfrage<T>(pfad),
  senden: <T>(pfad: string, koerper: unknown) =>
    anfrage<T>(pfad, { method: 'POST', body: JSON.stringify(koerper) }),
  aendern: <T>(pfad: string, koerper: unknown) =>
    anfrage<T>(pfad, { method: 'PUT', body: JSON.stringify(koerper) }),
  /** PATCH — nur die mitgegebenen Felder ändern. */
  flicken: <T>(pfad: string, koerper: unknown) =>
    anfrage<T>(pfad, { method: 'PATCH', body: JSON.stringify(koerper) }),
  formular: <T>(pfad: string, daten: FormData) =>
    anfrage<T>(pfad, { method: 'POST', body: daten }),
  /** DELETE — mit optionalem Rumpf: „Schlagwort von diesen Mails nehmen"
   *  braucht die Liste der Kennungen. */
  loeschen: <T>(pfad: string, koerper?: unknown) =>
    anfrage<T>(
      pfad,
      koerper === undefined
        ? { method: 'DELETE' }
        : { method: 'DELETE', body: JSON.stringify(koerper) },
    ),

  /** Eine Datei holen und im Browser speichern.
   *
   * ⚠️ **Kein GET.** Das Archivpasswort stuende sonst in der Adresszeile und
   * damit im Browserverlauf und in jedem Proxy-Protokoll. Deshalb POST, und
   * deshalb geht das nicht ueber `anfrage`: Dort wird JSON erwartet.
   */
  async herunterladen(pfad: string, koerper: unknown, name: string): Promise<void> {
    const antwort = await fetch(`${BASIS}${pfad}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(koerper),
    })
    if (!antwort.ok) {
      let text = ''
      try {
        text = String(((await antwort.json()) as { detail?: string }).detail ?? '')
      } catch {
        // Eine Antwort ohne JSON ist bei einem Fehler normal.
      }
      throw new ApiFehler(antwort.status, text)
    }

    const blob = await antwort.blob()
    const adresse = URL.createObjectURL(blob)
    const verweis = document.createElement('a')
    verweis.href = adresse
    verweis.download = name
    document.body.appendChild(verweis)
    verweis.click()
    verweis.remove()
    // ⚠️ Erst nach dem Klick freigeben - sonst ist die Adresse tot, bevor der
    // Browser sie gelesen hat. Ein kurzer Aufschub genuegt.
    setTimeout(() => URL.revokeObjectURL(adresse), 1000)
  },
}

// --- Die Formen, die der Server liefert --------------------------------- //

export interface Stand {
  eingerichtet: boolean
  zwei_faktor_aus: boolean
}

export interface Ich {
  id: string
  benutzername: string
  anzeigename: string
  ist_betreiber: boolean
  zwei_faktor_aktiv: boolean
  offene_codes: number
  /** Wohin ein Rücksetz-Link ginge. Leer heißt: **kein Weg zurück**. */
  kontaktadresse: string
  /** Ob der KI-Dienst eingeschaltet ist — daran hängt der Knopf im Editor. */
  ki_aktiv: boolean
}

export interface Schritt {
  /** "fertig" | "code" | "einrichten" */
  schritt: string
}

export interface Einrichtung {
  geheimnis: string
  otpauth: string
  qr_svg: string
}

export interface KontoAntwort {
  benutzername: string
}

// --- Postfächer ---------------------------------------------------------- //

export interface Serverteil {
  server: string
  port: number
  sicherheit: string
  benutzer: string
}

export interface Vorschlag {
  gefunden: boolean
  quelle: string
  anbietername: string
  app_passwort_noetig: boolean
  app_passwort_wo: string
  imap: Serverteil
  smtp: Serverteil
}

export interface OrdnerZeile {
  /** Vom Server gezählt — die Oberfläche kennt nur den offenen Ordner. */
  anzahl?: number
  ungelesen?: number
  /** 0 beim Verbindungstest — dort gibt es den Ordner noch nicht. */
  id: number
  pfad: string
  name: string
  rolle: string
  waehlbar: boolean
  abonniert: boolean
}

export interface Teilbefund {
  ok: boolean
  art: string
  text: string
}

export interface Befund {
  ok: boolean
  imap: Teilbefund
  smtp: Teilbefund
  ordner: OrdnerZeile[]
  kann_move: boolean
}

export interface KontoZeile {
  /** 'anmeldung', wenn der Mailserver die Zugangsdaten ablehnt. */
  stoerung?: string
  id: string
  /** Wie das Postfach in der Ordnerspalte heißt. */
  anzeigename: string
  /** Wie der Empfänger den Absender sieht. Leer = wie `anzeigename`. */
  absendername: string
  adresse: string
  farbe: number
  aktiv: boolean
  imap_server: string
  smtp_server: string
  imap_port: number
  imap_sicherheit: string
  imap_benutzer: string
  smtp_port: number
  smtp_sicherheit: string
  smtp_benutzer: string
  zuletzt_geprueft: string | null
  letzter_fehler: string
  /** Kennung dazu (z. B. 'anmeldung') — die Oberfläche übersetzt sie. */
  letzter_fehler_art?: string
  anzahl_ordner: number
  /** Freie Schlagworte zum Gruppieren der Postfächer. */
  tags: string[]
  /** Zusätzliche Absenderadressen dieses Postfachs. */
  aliase?: { adresse: string; name: string }[]
  /** 'google', 'microsoft' — oder leer bei einem gewöhnlichen IMAP-Postfach. */
  oauth_art?: string
  /** Wie viele Kalender an derselben Zustimmung hängen. */
  oauth_kalender?: number
}
