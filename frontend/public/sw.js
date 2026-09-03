/* Der Service Worker — er nimmt Meldungen an, wenn nexmail gar nicht offen ist.
 *
 * ⚠️ **Er speichert nichts zwischen.** Kein Cache, keine Offline-Fassung. Ein
 * Mail-Client, der eine alte Oberfläche aus dem Speicher ausliefert, zeigt
 * einen Posteingang von gestern und sagt nicht dazu, dass er das tut — genau
 * der Schrecken, den ein Datenverlust macht. Dieser Worker hat genau eine
 * Aufgabe, und alles andere geht wie bisher übers Netz.
 *
 * ⚠️ **Er wird nicht gebündelt.** Er liegt in `public/` und geht unverändert
 * mit; Vite fasst ihn nicht an. Deshalb steht hier kein Import und keine
 * moderne Syntax, auf die ein Bauschritt nötig wäre.
 *
 * ⚠️ **Er hat keine Übersetzung.** Ein Service Worker lebt ohne Dokument, hat
 * also weder i18next noch die eingestellte Sprache. Was hier steht, kommt
 * deshalb **fertig formuliert vom Server** — der Text der Meldung wird nie
 * hier gebaut. Nur die eine Zeile für den Notfall unten ist fest, und die
 * sieht man nur, wenn etwas kaputt ist.
 */

/* Sofort übernehmen, statt auf das Schließen aller Reiter zu warten.
   ⚠️ Ohne das bliebe nach einem Update wochenlang der alte Worker aktiv, und
   eine Änderung hier käme bei niemandem an, der nexmail dauernd offen hat. */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('push', (ereignis) => {
  /* ⚠️ **Eine Meldung ist Pflicht, sobald ein Push ankommt.** Chrome und
     Firefox entziehen die Erlaubnis, wenn ein Worker einen Push annimmt, ohne
     etwas zu zeigen („silent push"). Deshalb steht am Ende jedes Zweigs eine
     Meldung — auch wenn der Rumpf unlesbar war. */
  let daten = {}
  try {
    daten = ereignis.data ? ereignis.data.json() : {}
  } catch (e) {
    daten = {}
  }

  const titel = daten.titel || 'nexmail'
  ereignis.waitUntil(
    self.registration.showNotification(titel, {
      body: daten.text || '',
      icon: 'symbol-192.png',
      badge: 'meldung-96.png',
      /* Gleiche Marke ersetzt statt zu stapeln — sonst steht nach einer Nacht
         ein Turm gleichlautender Meldungen da. */
      tag: daten.marke || 'nexmail',
      renotify: true,
      data: { ziel: daten.ziel || './' },
    }),
  )
})

self.addEventListener('notificationclick', (ereignis) => {
  ereignis.notification.close()

  /* ⚠️ **Erst einen offenen Reiter suchen, dann einen neuen aufmachen.** Wer
     bei jedem Klick ein weiteres Fenster bekommt, hat nach einem Tag zehn
     nexmails offen — und in jedem eine eigene Sitzung. */
  const ziel = new URL(
    (ereignis.notification.data && ereignis.notification.data.ziel) || './',
    self.registration.scope,
  ).href

  ereignis.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((fenster) => {
      for (const f of fenster) {
        /* Im Geltungsbereich heißt: dieselbe Installation. Ein zweites nexmail
           unter einem anderen Unterpfad ist ein anderes Fenster. */
        if (f.url.startsWith(self.registration.scope) && 'focus' in f) {
          if ('navigate' in f && f.url !== ziel) return f.navigate(ziel).then((g) => g && g.focus())
          return f.focus()
        }
      }
      return self.clients.openWindow(ziel)
    }),
  )
})

/* ⚠️ **Der Push-Dienst darf ein Abonnement von sich aus erneuern.** Passiert
   das, ist die Adresse im Server veraltet, und jede weitere Meldung liefe ins
   Leere — ohne Fehler, den irgendjemand sähe. Der Worker meldet die neue
   Adresse deshalb sofort nach.

   ⚠️ **Ohne Sitzungs-Cookie geht das nicht**, und das ist hinnehmbar: Der
   Aufruf scheitert dann mit 401, und beim nächsten Öffnen der Oberfläche
   meldet sie das Gerät ohnehin neu an. */
self.addEventListener('pushsubscriptionchange', (ereignis) => {
  const alt = ereignis.oldSubscription
  const neu = ereignis.newSubscription
  if (!neu) return
  ereignis.waitUntil(
    fetch(new URL('api/push/anmelden', self.registration.scope).href, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(_alsAnmeldung(neu)),
    }).catch(() => undefined),
  )
  void alt
})

function _alsAnmeldung(abo) {
  const roh = abo.toJSON()
  return {
    endpunkt: roh.endpoint,
    p256dh: roh.keys.p256dh,
    auth: roh.keys.auth,
  }
}
