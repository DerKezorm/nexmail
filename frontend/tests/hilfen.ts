/* Was jeder Oberflächen-Test braucht. */
import { expect, type Locator, type Page } from '@playwright/test'

/** Anmelden und warten, bis die Mail-Ansicht steht.
 *
 * ⚠️ **Über die Beschriftungen, nicht über die Reihenfolge.** `input`
 * nacheinander zu füllen bricht, sobald irgendwo ein verstecktes Feld
 * dazukommt — und der Fehler sieht dann aus wie „die Anmeldung geht nicht".
 */
export async function anmelden(seite: Page) {
  /* ⚠️ **Gemerkte Einstellungen zuerst zurücksetzen.**
   *
   * Dichte, Anriss und der Listenfilter liegen in `localStorage` und
   * überleben zwischen Tests. Ein Lauf, der den Filter auf „ungelesen" stehen
   * lässt, gibt dem nächsten eine andere Liste — und der scheitert an etwas,
   * das er gar nicht geprüft hat. Genau so am 01.09.2026 passiert. */
  await seite.goto('/')
  await seite.evaluate(() => {
    for (const k of [
      'nexmail.filter',
      'nexmail.dichte',
      'nexmail.anreisser',
      'nexmail.punkte',
      // ⚠️ Ohne das startet der nächste Lauf mit gefilterten Postfächern und
      // scheitert an einem Ordner, den es für ihn gar nicht gibt.
      'nexmail.gruppe',
      'nexmail.gruppiert',
      'nexmail.gelesen_nach',
    ]) {
      localStorage.removeItem(k)
    }
  })
  await seite.reload()
  await expect(
    seite.getByRole('button', { name: 'Mail', exact: true }),
    'Die Mail-Ansicht steht nicht da. Läuft das Backend auf 8010 mit data-dev?',
  ).toBeVisible({ timeout: 15_000 })
}

/** Zu den eigenen Einstellungen — sie liegen im Benutzermenü oben rechts.
 *
 * ⚠️ **Nicht mehr in der NavRail.** Dort steht seit dem 01.09.2026 nur noch
 * die Verwaltung: Was dem Benutzer gehört, hängt an seinem Namen; was der
 * Anwendung gehört, unten in der Ecke.
 */
export async function zuEinstellungen(seite: Page) {
  /* ⚠️ **Nicht am Namen des Betreibers suchen.** „Anna" steht in keiner
     fremden Installation — und schmal stand er auch hier nicht da: Die
     Beschriftung ist ausgeblendet, die beiden Symbole sind `aria-hidden`, und
     damit hatte der Knopf **gar keinen Namen**. Der Test fand ihn nicht, eine
     Vorlesehilfe hätte ihn auch nicht gefunden. Er trägt jetzt ein
     `aria-label`; gesucht wird danach. */
  const menue = seite.getByRole('button', { name: /Benutzermenü|User menu/ }).first()
  await menue.click()
  await seite.getByRole('button', { name: 'Einstellungen' }).click()
  await expect(seite.getByRole('tab', { name: 'Postfächer' })).toBeVisible()
}

/**
 * ⚠️ **Der Test, den es ohne echten Browser nicht gibt.**
 *
 * Sucht Beschriftungen und Werte, die breiter sind als ihr Kasten. Genau so
 * entstand „VERSCHLÜSSELUNG" über dem Rand und „STARTTI" statt „STARTTLS":
 * Deutsche Wörter sind länger als die englischen, an denen man eine Spalte
 * unwillkürlich bemisst.
 */
export async function keinTextLaeuftUeber(seite: Page, bereich = 'body') {
  const ueberlaeufe = await seite.evaluate((auswahl) => {
    const wurzel = document.querySelector(auswahl)
    if (!wurzel) return []
    const treffer: Array<{ text: string; sichtbar: number; noetig: number }> = []
    for (const el of Array.from(wurzel.querySelectorAll<HTMLElement>('*'))) {
      if (el.children.length > 0) continue
      const text = (el.textContent ?? '').trim()
      if (!text) continue
      const stil = getComputedStyle(el)
      // Was absichtlich abgeschnitten wird, ist kein Fehler.
      if (stil.textOverflow === 'ellipsis' || stil.overflow === 'hidden') continue
      if (stil.display === 'none' || stil.visibility === 'hidden') continue
      if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        treffer.push({ text: text.slice(0, 60), sichtbar: el.clientWidth, noetig: el.scrollWidth })
      }
    }
    return treffer
  }, bereich)

  expect(
    ueberlaeufe,
    `Text läuft über seinen Kasten hinaus:\n${ueberlaeufe
      .map((u) => `  „${u.text}" braucht ${u.noetig}px, hat ${u.sichtbar}px`)
      .join('\n')}`,
  ).toEqual([])
}

/**
 * ⚠️ **Auch das geht nur im echten Browser.** Ein `<select>` malt seine
 * aufgeklappte Liste selbst und erbt nichts vom Feld darüber — ohne eigene
 * Farbe steht auf schwarzem Grund eine weiße Liste.
 */
export async function auswahllistenSindGefaerbt(seite: Page) {
  const ungefaerbt = await seite.evaluate(() => {
    const schlecht: string[] = []
    for (const option of Array.from(document.querySelectorAll('option'))) {
      const stil = getComputedStyle(option)
      const grund = stil.backgroundColor
      // „transparent" oder Weiß heißt: Der Browser malt sein eigenes Ding.
      if (
        grund === 'rgba(0, 0, 0, 0)' ||
        grund === 'transparent' ||
        grund === 'rgb(255, 255, 255)'
      ) {
        schlecht.push(`${(option.textContent ?? '').trim().slice(0, 40)} → ${grund}`)
      }
    }
    return schlecht
  })

  expect(ungefaerbt, `Auswahl-Einträge ohne eigene Farbe:\n  ${ungefaerbt.join('\n  ')}`).toEqual([])
}

/** Bilder, die der Browser nicht laden konnte — das kaputte Symbol. */
export async function keineKaputtenBilder(seite: Page) {
  const kaputt = await seite.evaluate(() => {
    const schlecht: string[] = []
    for (const bild of Array.from(document.images)) {
      if (bild.classList.contains('ProseMirror-separator')) continue
      if (!bild.getAttribute('src')) continue
      if (bild.complete && bild.naturalWidth === 0) {
        schlecht.push(bild.getAttribute('src')?.slice(0, 60) ?? '')
      }
    }
    return schlecht
  })
  expect(kaputt, `Bilder, die nicht geladen haben:\n  ${kaputt.join('\n  ')}`).toEqual([])
}

/** Nichts darf die Seite seitlich scrollen lassen. */
export async function keinSeitlichesScrollen(seite: Page) {
  const zuBreit = await seite.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  )
  expect(zuBreit, 'Die Seite lässt sich seitlich scrollen.').toBe(false)
}

/** Sammelt Server-Absagen, damit ein roter Test seine **Ursache** nennt.
 *
 * ⚠️ **Aus Schaden entstanden, 01.09.2026.** Zwei Tests scheiterten mit
 * „Beschriftung blieb ‚Markierung entfernen‘" und „Der Unterordner taucht
 * nicht auf". Beides war eine Folge, keine Ursache: Der Mailserver wies die
 * Anmeldung ab. Ich habe das zuerst für Testflackern gehalten — und lag
 * falsch. Ein Test, der die Absage des Servers verschweigt, führt genau
 * dorthin.
 *
 * ``pruefen()`` wirft mit der Meldung des Servers, sobald eine kam.
 */
export function serverabsagen(seite: Page) {
  // ⚠️ **Die Rumpf-Auswertung läuft asynchron.** Ein Wächter, der die Liste
  // erst beim Lesen des Rumpfes füllt, ist beim Prüfen womöglich noch leer —
  // dann schweigt er und der Test meldet die Folge statt der Ursache. Genau
  // so beim ersten Anlauf passiert. Deshalb werden die Versprechen gesammelt
  // und beim Prüfen abgewartet.
  const laufend: Array<Promise<string | null>> = []

  seite.on('response', (antwort) => {
    if (!antwort.url().includes('/api/') || antwort.status() < 400) return
    if (antwort.status() === 401 || antwort.status() === 404) return
    const kurz = antwort.url().split('/api/')[1]?.slice(0, 40)
    laufend.push(
      antwort
        .json()
        .then((d) => `${antwort.status()} ${kurz}: ${(d as { detail?: string }).detail ?? ''}`)
        .catch(() => `${antwort.status()} ${kurz}`),
    )
  })

  return {
    async pruefen() {
      const gesehen = (await Promise.all(laufend)).filter(Boolean)
      expect(
        gesehen,
        'Der Server hat abgesagt — daran scheitert der Test, nicht an der ' +
          'Oberfläche: ' +
          gesehen.join(' | '),
      ).toEqual([])
    },
  }
}

/** Rechtsklick auf die erste Nachricht in der Liste. */
export async function ersteNachrichtKontext(seite: Page) {
  const zeile = seite.locator('button[draggable="true"]').first()
  await expect(zeile).toBeVisible()
  await zeile.click({ button: 'right' })
  await expect(seite.getByRole('menu').first()).toBeVisible()
  return zeile
}

/** Der Ordnerbaum **eines bestimmten Postfachs**.
 *
 * ⚠️ **Aus Schaden entstanden, 01.09.2026.** Wer den erstbesten „Posteingang"
 * anklickt, landet in dem Postfach, das zufällig oben steht. Als ein zweites
 * dazukam, war das eines, dessen Anmeldung der Server ablehnte — und der Test
 * meldete „Der Unterordner taucht nicht auf". Die Ursache lag vier Zeilen
 * vorher.
 *
 * Alles, was in einem Postfach **etwas anlegt oder löscht**, benutzt das
 * Testpostfach — nie ein echtes.
 */
export const TESTPOSTFACH = 'Test1'

export function postfach(seite: Page, name: string = TESTPOSTFACH) {
  return seite.locator('section').filter({ hasText: name }).first()
}

/** Jeder Knopf muss einen Namen haben, den man vorlesen kann.
 *
 * ⚠️ Ein Knopf aus lauter `aria-hidden`-Symbolen ist für eine Vorlesehilfe
 * eine namenlose Schaltfläche. Genau so verschwand das Benutzermenü in der
 * schmalen Ansicht — sichtbar war es, ansprechbar nicht.
 */
export async function jederKnopfHatEinenNamen(seite: Page) {
  const namenlos = await seite.evaluate(() => {
    const schlecht: string[] = []
    for (const b of Array.from(document.querySelectorAll<HTMLElement>('button'))) {
      if (b.offsetParent === null) continue // unsichtbar zählt nicht
      const name =
        b.getAttribute('aria-label') ??
        b.getAttribute('title') ??
        Array.from(b.childNodes)
          .filter((n) => !(n instanceof HTMLElement) || n.getAttribute('aria-hidden') === null)
          .map((n) => n.textContent ?? '')
          .join('')
      // ⚠️ Der Klassenname allein sagt nicht, **welcher** Knopf es ist — die
      // Primitive teilen ihn sich alle. Das Symbol schon: lucide schreibt
      // seinen Namen in die Klasse (`lucide-menu`). Dazu, wo der Knopf sitzt.
      if (!name.trim()) {
        const symbol = Array.from(b.querySelector('svg')?.classList ?? []).find((c) =>
          c.startsWith('lucide-'),
        )
        const kasten = b.getBoundingClientRect()
        schlecht.push(`${symbol ?? '(kein Symbol)'} bei ${Math.round(kasten.x)}/${Math.round(kasten.y)}`)
      }
    }
    return schlecht
  })
  expect(namenlos, 'Knöpfe ohne vorlesbaren Namen: ' + namenlos.join(', ')).toEqual([])
}

/** Kein roher Übersetzungsschlüssel darf in der Oberfläche stehen.
 *
 * ⚠️ **Aus Schaden entstanden, 01.09.2026.** Auf der Einladungsseite standen
 * „einrichtung.grund_passwort" und „EINRICHTUNG.WIEDERHOLUNG" als Text da —
 * ich hatte Schlüssel erfunden, die es nicht gab. i18next gibt dann still den
 * Schlüssel zurück; nichts schlägt fehl, nichts wird rot. Nur der Betreiber
 * liest Kauderwelsch.
 */
export async function keineRohenSchluessel(seite: Page) {
  const roh = await seite.evaluate(() => {
    const treffer: string[] = []
    // `bereich.wort_wort` — genau die Form, die i18next durchreicht.
    const muster = /^[a-z][a-z0-9]*(_[a-z0-9]+)*(\.[a-z][a-z0-9]*(_[a-z0-9]+)*)+$/i
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
      if (el.children.length > 0) continue
      const text = (el.textContent ?? '').trim()
      if (!text || text.includes(' ')) continue
      // Adressen und Dateinamen sehen ähnlich aus, sind aber keine Schlüssel.
      if (text.includes('@') || text.includes('/') || text.includes(':')) continue
      if (muster.test(text)) treffer.push(text)
    }
    return treffer
  })
  expect(roh, 'Roher Übersetzungsschlüssel in der Oberfläche: ' + roh.join(', ')).toEqual([])
}

/** Rechtsklick, bis das Menü wirklich steht.
 *
 * ⚠️ **Aus Schaden entstanden, 01.09.2026.** Ein Rechtsklick, der landet,
 * während der Ordnerbaum gerade neu zeichnet, öffnet nichts — das Element
 * unter dem Zeiger ist im nächsten Moment ein anderes. Der Test scheiterte
 * dann an „Neuer Unterordner nicht gefunden" und im Einzellauf nie. Genau die
 * Sorte Flackern, die man zweimal wegerklärt und beim dritten Mal für einen
 * echten Fehler hält.
 */
export async function rechtsklick(seite: Page, ziel: Locator) {
  await expect(ziel).toBeVisible()
  for (let versuch = 0; versuch < 3; versuch++) {
    await ziel.click({ button: 'right' })
    const menue = seite.getByRole('menu').first()
    if (await menue.isVisible().catch(() => false)) return menue
    await seite.waitForTimeout(500)
  }
  const menue = seite.getByRole('menu').first()
  await expect(menue, 'Der Rechtsklick öffnet kein Menü.').toBeVisible()
  return menue
}

/** Die lokale Tabu-Liste — Wörter, die nie in einem Platzhalter stehen dürfen.
 *
 * ⚠️ **Sie steht nicht im Repo.** Ein Wächter, der die Namen mitliefert, die er
 * verbieten soll, wäre in einem öffentlichen Repo genau die Leckstelle, die er
 * verhindern will. Fehlt die Datei, bleiben die allgemeinen Formen — der Test
 * prüft dann weniger, aber er behauptet es auch nicht.
 */
export function tabuWoerter(): string[] {
  const allgemein = ['@icloud.com', '@gmail.com', '@web.de', '@gmx.de']
  try {
    const fs = require('node:fs') as typeof import('node:fs')
    const roh = fs.readFileSync(new URL('../../.veroeffentlichung-tabu', import.meta.url), 'utf-8')
    const eigene = roh
      .split('\n')
      .map((z) => z.trim().toLowerCase())
      .filter((z) => z && !z.startsWith('#'))
    return [...eigene, ...allgemein]
  } catch {
    return allgemein
  }
}
