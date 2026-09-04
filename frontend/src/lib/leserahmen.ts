/* Die Seite, die im Rahmen des Lesebereichs steht.
 *
 * ⚠️ **Hier steht keine Sicherheitsgrenze.** Das Ausklinken der Bilder und das
 * Bereinigen des HTML hat der Server längst erledigt; hier kommt nur noch das
 * Stylesheet dazu.
 *
 * ⚠️ **Ohne Browser, und der Grund ist der Testlauf.** Die Farbwerte kommen
 * als Parameter herein, statt hier aus `getComputedStyle` gelesen zu werden —
 * damit die schnelle Prüfebene (`environment: 'node'`) diese Datei überhaupt
 * laden kann. Dasselbe Muster wie bei `lib/pushlage.ts`, und aus demselben
 * Anlass: Am 04.09.2026 steckte hier ein Kontrastfehler, den nur ein Blick in
 * eine echte Mail gezeigt hat. Ein Wächter, der ihn festhält, braucht diese
 * Trennung.
 */
import type { Lesegrund } from './lesegrund'

/** Die Werte, die der Rahmen nicht selbst sehen kann.
 *
 * ⚠️ Ein `<iframe srcdoc>` sieht die CSS-Variablen des Elternfensters nicht.
 * Sie müssen mit hineingeschrieben werden.
 */
export interface Rahmenfarben {
  sans: string
  mono: string
  /** Fließtext der Anwendung (`--text-2`). */
  text: string
  /** Hervorgehobener Text der Anwendung (`--text-1`). */
  stark: string
  /** Linkfarbe der Anwendung (`--text-accent`). */
  akzent: string
}

/* Die Umkehr für fremde Mails, die eigene Farben setzen.
 *
 * ⚠️ **Umkehren, nicht umfärben.** Wer die Farben einer fremden Mail einzeln
 * umschreibt, muss jede Regel verstehen — Verläufe, Rahmen, Zellenfarben,
 * `!important`, Farben in Attributen. Was er übersieht, wird unlesbar, und das
 * fällt erst beim Empfänger auf. Eine Umkehr trifft alles gleich und lässt den
 * Abstand zwischen Vorder- und Hintergrund genau, wie er war.
 *
 * ⚠️ **`hue-rotate(180deg)` gehört dazu.** Ohne sie wird aus Blau Orange und
 * aus Rot Türkis; die Marke einer Firma sähe falsch aus. Mit ihr bleiben die
 * Farbtöne ungefähr stehen, und nur die Helligkeit dreht sich.
 *
 * ⚠️ **Bilder werden zurückgedreht** — sonst stünde jedes Logo als Negativ da
 * und jedes Foto sähe aus wie eine Röntgenaufnahme. Dasselbe gilt für alles,
 * was ein Bild trägt: `video`, `svg`, und ein Element mit `background-image`
 * erwischt man so nicht — das ist der bekannte Rest, und er ist selten.
 *
 * ⚠️ **`background: Canvas` trägt den ganzen Rand der Mail** — alles, was sie
 * selbst nicht bemalt. Es ist deshalb nur zusammen mit `color-scheme: light`
 * richtig; die Begründung steht unten in `leseseite`.
 */
const UMKEHR = `
    html { filter: invert(1) hue-rotate(180deg); background: Canvas; }
    img, video, svg, picture, canvas, iframe, embed, object {
      filter: invert(1) hue-rotate(180deg);
    }
  `

/** Das vollständige Dokument für den Rahmen. */
export function leseseite(koerper: string, grund: Lesegrund, farben: Rahmenfarben): string {
  /* ⚠️ **`umgekehrt` wird ZUERST hell gebaut und dann gedreht.** Die Umkehr
     ist nur ein Filter über dem fertigen Bild; sie setzt voraus, dass darunter
     das weiße Blatt liegt, mit dem die Mail rechnet.

     Am 04.09.2026 an einem echten Newsletter gemessen, weil es zuerst
     andersherum stand: Mit den Anwendungsfarben darunter kam Text, den die
     Mail nicht selbst einfärbt, als `rgb(155,166,165)` heraus — nach der
     Umkehr dunkelgrau auf fast schwarz. Also genau der Kontrastfehler, vor dem
     der Kopf von `lesegrund.ts` warnt, nur an neuer Stelle. Bei jenem
     Newsletter fiel er nicht auf, weil er jede Fläche selbst bemalt; die Zeile
     ohne eigene Farbe ist der Fall, den man nicht sucht.

     ⚠️ **Daran hängt auch `color-scheme`.** Mit `light dark` löst `Canvas`
     beim Leser, dessen Browser dunkel steht, zu `rgb(18,18,18)` auf — und die
     Umkehr macht daraus einen fast weißen Rand um die Mail. Auf einem hell
     eingestellten Browser wäre das nie aufgefallen: Dort ist `Canvas` weiß und
     es sah zufällig richtig aus. */
  const aufHell = grund !== 'anwendung'

  /* ⚠️ **Ganz oder gar nicht, je Mail.** Sagt die Mail irgendetwas über Farbe,
     rechnet sie mit hellem Grund und bekommt ihn — sonst trägt sie die Farben
     der Anwendung. Halb umzufärben ist der Fehler: Am 02.09.2026 gemessen
     stand eine Mail mit `color:#333` und ohne eigenen Grund als Dunkelgrau auf
     Fast-Schwarz da: Kontrast 1,53:1, auf hellem Grund sind es 12,63:1.

     ⚠️ **`Canvas` und `CanvasText`, keine erfundene Farbe.** Unter
     `color-scheme: light` fragt das die Systemfarben ab — genau den hellen
     Grund, mit dem die Mail rechnet. Ein hier eingetipptes `#ffffff` wäre eine
     Farbe, die in keinem Token steht. */
  const stil = `
    :root { color-scheme: ${aufHell ? 'light' : 'light dark'}; }
    body {
      margin: 0; padding: 16px 24px;
      font: 400 14px/1.6 var(--nm-sans);
      color: ${aufHell ? 'CanvasText' : 'var(--nm-text)'};
      background: ${aufHell ? 'Canvas' : 'transparent'};
      overflow-wrap: break-word;
    }
    p { margin: 0 0 12px; }
    ${aufHell ? '' : 'a { color: var(--nm-accent); }'}
    ${aufHell ? '' : 'b, strong { color: var(--nm-strong); }'}
    code, pre { font-family: var(--nm-mono); font-size: .92em; }
    pre { white-space: pre-wrap; }
    img { max-width: 100%; height: auto; }
    /* ⚠️ Auch das leere src. Ein Bild ohne Adresse ist für den Browser kein
       fehlendes, sondern ein kaputtes — er malt das Bruchsymbol. Der Server
       lässt das Attribut inzwischen ganz weg; die Regel hier steht daneben,
       weil ein älterer Bestand noch leere Adressen tragen kann. */
    img:not([src]), img[src=""] { display: none; }
    table { max-width: 100%; }
    ${grund === 'umgekehrt' ? UMKEHR : ''}
  `

  const vars = [
    `--nm-sans:${farben.sans}`,
    `--nm-mono:${farben.mono}`,
    `--nm-text:${farben.text}`,
    `--nm-strong:${farben.stark}`,
    `--nm-accent:${farben.akzent}`,
  ].join(';')

  return `<!doctype html><html><head><meta charset="utf-8">
<style>:root{${vars}}${stil}</style></head><body>${koerper}</body></html>`
}
