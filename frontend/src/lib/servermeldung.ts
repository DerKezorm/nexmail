/* Eine Kennung vom Server in einen Satz in der eingestellten Sprache.
 *
 * ⚠️ **Der Server benennt, die Oberfläche übersetzt.** Bis zum 03.09.2026
 * schickte er 142 fertige deutsche Sätze als `detail`, und die Oberfläche
 * zeigte sie wörtlich an — auf Englisch blieben sie deutsch. Das verstößt
 * gegen nexmails eigene Regel „nach außen ist alles Englisch".
 *
 * ⚠️ **Eine Stelle, nicht 73.** Vorher stand die einzige Übersetzung einer
 * Kennung als Ternär-Kette mitten in `App.tsx`. Bei 171 Kennungen wäre das
 * unhaltbar: Jede neue hätte einen eigenen Sonderfall gebraucht, und wer ihn
 * vergisst, zeigt die rohe Kennung an.
 *
 * ⚠️ **Werte gehören nicht in die Kennung.** „Der Name ist länger als 40
 * Zeichen" ist `ordner_name_zu_lang` mit `{ max: 40 }`; i18next setzt die Zahl
 * ein. Andernfalls bräuchte jede Grenze ihren eigenen Schlüssel.
 */
import i18next from 'i18next'
import { ApiFehler } from '../api/client'

/* ⚠️ **Auch ein Wert kann eine Kennung sein.** `rolle_ohne_ordner` nennt die
   Rolle, und die heißt im Server `papierkorb`. Bis 0.17.0 stand sie so im
   Satz, auf Englisch also „no folder for “papierkorb”“. Die Ordnernamen hat
   der Katalog längst; ein Wert, den er nicht kennt, bleibt, wie er kam. */
function werteUebersetzt(werte: Record<string, unknown>): Record<string, unknown> {
  const rolle = werte.rolle
  if (typeof rolle !== 'string' || !i18next.exists(`ordner.${rolle}`)) return werte
  return { ...werte, rolle: i18next.t(`ordner.${rolle}`) }
}

/** Der Satz zu einem Fehler — oder ein tragfähiger Rückfall. */
export function servermeldung(fehler: unknown, rueckfall?: string): string {
  if (!(fehler instanceof ApiFehler)) {
    return rueckfall ?? i18next.t('anmeldung.fehler_allgemein')
  }

  const kennung = fehler.detail
  const schluessel = `serverfehler.${kennung}`

  /* ⚠️ **`exists` statt eines blinden `t`.** i18next gibt bei einem unbekannten
     Schlüssel den Schlüssel selbst zurück — der Benutzer läse dann
     „serverfehler.ordner_name_fehlt". Ein Rückfall ist hässlich, das ist
     kaputt. */
  if (kennung && i18next.exists(schluessel)) {
    return i18next.t(schluessel, werteUebersetzt(fehler.werte ?? {}))
  }

  /* ⚠️ **Eine unbekannte Kennung ist ein Fehler bei uns, kein Betriebsfall.**
     Sie kommt nur vor, wenn der Server etwas nennt, das im Katalog fehlt —
     also nach einem Update, bei dem jemand den Eintrag vergessen hat. Der
     Wächter im Server hält das fest; hier bleibt ein lesbarer Satz übrig,
     statt einer rohen Kennung. */
  return rueckfall ?? i18next.t('anmeldung.fehler_allgemein')
}
