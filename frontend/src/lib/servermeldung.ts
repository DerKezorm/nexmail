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
import { oidcErrorKey, oidcFormErrorKey } from '../vendor/nexoidc/oidc'
import { accountErrorKeyOf } from '../vendor/nexkonten/konten'
import { KI_TEXTS } from '../vendor/nexki/ki'

/** nexmails alte Kennungen zurück auf die des Kontenmoduls (der Server sendet die alten, `ALTE_KENNUNGEN` in
 *  `services/konten_store.py`); die meisten haben schon einen eigenen Satz unter `serverfehler`. */
export const ALTE_KENNUNGEN: Readonly<Record<string, string>> = {
  anmeldung_falsch: 'wrong_credentials',
  benutzername_vergeben: 'username_taken',
  benutzername_ungueltig: 'username_invalid',
  passwort_zu_kurz: 'password_too_short',
  adresse_ungueltig: 'email_invalid',
  kennwort_falsch: 'wrong_password',
  einladung_abgelaufen: 'invite_invalid',
  ruecksetzung_ungueltig: 'reset_invalid',
  benutzer_nicht_gefunden: 'not_found',
}

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
  const { account_code: kontoKennung, ...werte } = fehler.werte ?? {}
  const antwort = { code: kennung, account_code: typeof kontoKennung === 'string' ? kontoKennung : null }

  /* konten 0.3.10: Hinter einer alten Kennung mit zwei Bedeutungen (`einladung_abgelaufen`, `ruecksetzung_ungueltig`)
     nennt der Server die des Moduls daneben (`werte.account_code`). Sagt sie mehr als die alte (abgelaufen statt
     ungültig), gilt ihr Satz (`accountErrorKeyOf`). */
  if (antwort.account_code && antwort.account_code !== ALTE_KENNUNGEN[kennung]) {
    const genauer = accountErrorKeyOf(antwort, ALTE_KENNUNGEN)
    if (genauer !== 'account.error.unknown') return i18next.t(genauer, werte)
  }

  /* ⚠️ **`exists` statt eines blinden `t`.** i18next gibt bei einem unbekannten
     Schlüssel den Schlüssel selbst zurück — der Benutzer läse dann
     „serverfehler.ordner_name_fehlt". Ein Rückfall ist hässlich, das ist
     kaputt. */
  if (kennung && i18next.exists(schluessel)) {
    return i18next.t(schluessel, werteUebersetzt(werte))
  }

  /* Die Anmeldung über Anbieter nennt die Kennungen des gemeinsamen Moduls (`routers/oidc.abgelehnt`); ihre Sätze
     stehen in dessen Wortlauten (`oidc.error.*`, `oidc.formError.*`), nicht unter `serverfehler`. */
  const modul = oidcFormErrorKey(kennung) ?? oidcErrorKey(kennung)
  if (modul) return i18next.t(modul)

  /* Das Modul ki nennt auf nexmails alten KI-Wegen die Kennungen, die es vorher nicht gab (Netzregeln, Bremsen:
     `ai_address_private`, `ai_too_often` …); die Sätze stehen in seinen Wortlauten (`errors.*`). */
  if (kennung.startsWith('ai_')) {
    const sprache = i18next.language?.startsWith('de') ? 'de' : i18next.language?.startsWith('fr') ? 'fr' : 'en'
    const satz = (KI_TEXTS[sprache].errors as Record<string, string>)[kennung]
    if (satz) return satz
  }

  /* Das Kontenmodul nennt seine Kennungen (`display_name_taken`, `setup_code_wrong` …); die Sätze stehen in seinen
     Wortlauten (`account.*`). */
  const konto = accountErrorKeyOf(antwort, ALTE_KENNUNGEN)
  if (konto !== 'account.error.unknown') return i18next.t(konto, werte)

  /* ⚠️ **Eine unbekannte Kennung ist ein Fehler bei uns, kein Betriebsfall.**
     Sie kommt nur vor, wenn der Server etwas nennt, das im Katalog fehlt —
     also nach einem Update, bei dem jemand den Eintrag vergessen hat. Der
     Wächter im Server hält das fest; hier bleibt ein lesbarer Satz übrig,
     statt einer rohen Kennung. */
  return rueckfall ?? i18next.t('anmeldung.fehler_allgemein')
}
