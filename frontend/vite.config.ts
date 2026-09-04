/// <reference types="vitest/config" />
// ⚠️ Diese Zeile ist kein Beiwerk: Ohne sie kennt Vites
// ``UserConfigExport`` den Abschnitt ``test`` nicht, und ``npx tsc --noEmit``
// bricht ab — im automatischen Bau also, nicht hier.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Port 5175: 5173 gehoert Nexviews Vite-Server, 5174 ist der Host-Port des
// spaeteren nexmail-Containers. So koennen alle drei gleichzeitig laufen.
//
// Der Proxy schickt /api an uvicorn. Ohne ihn liefe die Oberflaeche gegen
// eine andere Herkunft, und das Sitzungs-Cookie (SameSite=Strict) faehrt
// dann nicht mit - man sucht den Fehler dann in der Anmeldung statt in der
// Entwicklungsumgebung.
//
// 8010 und nicht 8000: Auf diesem Rechner haengt schon etwas auf 8000, und
// uvicorn scheitert dann beim Start mit einem Fehler, den man erst im
// Protokoll sieht. Im Container laeuft nexmail weiterhin auf 8000 - dort ist
// es allein.
/* ⚠️ **In der Entwicklungsumgebung gab es die Inhaltsregel gar nicht.**
 * Das Dokument liefert Vite, den `Content-Security-Policy`-Kopf setzt nur das
 * Backend — also traf er hier nie zu. Genau daran ist der Fehler
 * „Bilder anzeigen tut nichts" drei Fassungen lang vorbeigelaufen: Lokal
 * erschienen die Bilder, im Container nicht, und der abgeschottete Lesebereich
 * meldet den Verstoss nicht einmal in der Konsole.
 *
 * Nachgezogen wird **nur `img-src`**, und das mit Absicht: Die vollständige
 * Regel des Servers (`script-src 'self'`, kein `ws:` in `connect-src`) würde
 * Vites eigenes Nachladen abwürgen. Was hier steht, ist die eine Zeile, an der
 * sich Bilder entscheiden — der Rest wird im Container geprüft.
 */
const BILDREGEL = "img-src 'self' data: blob:"

export default defineConfig({
  plugins: [react(), tailwindcss()],

  /* Die schnelle Ebene neben den Oberflaechen-Tests.
   *
   * ⚠️ **Sie ersetzt keinen Browser-Test.** jsdom haette keinen einzigen der
   * Fehler gefunden, die aus dem Betrieb gemeldet wurden - ueberlaufende
   * Beschriftung, abgeschnittener Auswahlwert, weisse Auswahlliste auf
   * schwarzem Grund, ein Kontextmenue ohne Wirkung. Das steht so im Kopf von
   * ``playwright.config.ts`` und bleibt richtig.
   *
   * ⚠️ **Sie steht daneben, fuer das, was ein Browser gar nicht besser
   * weiss.** Ein fehlender Uebersetzungsschluessel ist ein Textvergleich; ihn
   * im Browser zu suchen heisst, jede Ansicht einmal zu oeffnen. Am 03.09.2026
   * standen vier rohe Schluessel auf der Verwaltungsseite, und der vorhandene
   * Browser-Waechter kam nie in den Reiter, in dem sie stehen.
   *
   * ⚠️ **``environment: node``, kein jsdom.** Was hier geprueft wird,
   * braucht kein Dokument: Sprachdateien, reine Rechenfunktionen, die
   * Uebereinstimmung zweier Listen. Ein jsdom waere ein weiteres Paket in der
   * Lieferkette, das nichts traegt. Wer spaeter ein Bauteil zeichnen will,
   * holt es dann - und begruendet es dann.
   */
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    /* ⚠️ **Feste Zeitzone, sonst misst `ziehen.test.ts` nichts.** Der teuerste
     * Fall beim Ziehen eines Termins ist die Zeitumstellung — und in UTC, wie
     * das Fliessband laeuft, gibt es sie nicht. Die Probe liefe durch, ohne
     * etwas zu pruefen. `ziehen.test.ts` weist als Erstes nach, dass die Zone
     * wirklich gilt; ohne diesen Nachweis waere die Zeile hier nur Zierde. */
    env: { TZ: 'Europe/Berlin' },
    // Die Oberflaechen-Tests laufen mit Playwright, nicht hier - sonst
    // versucht Vitest sie zu starten und scheitert an fehlendem Browser.
    exclude: ['node_modules/**', 'tests/**', 'dist/**'],
  },

  build: {
    /* Das Manifest ist die Zutatenliste des Baus: welches Stueck haengt fest
     * am Einstieg, welches wird nur bei Bedarf geholt. Ohne es muss ein
     * Gewichtswaechter raten, welche Datei wozu gehoert. Es landet in
     * ``dist/.vite/`` und wird nie ausgeliefert. */
    manifest: true,
    rollupOptions: {
      output: {
        /* ⚠️ **Das aendert am ERSTEN Besuch nichts** — dieselben Bytes,
         * nur anders verpackt. Es hilft beim zweiten: Das Geruest aus React,
         * i18next und dem Editor aendert sich nur, wenn eine Fremdbibliothek
         * erneuert wird, also selten. Nach einem nexmail-Update holt der
         * Browser deshalb nur den Anwendungsteil neu.
         *
         * Gemessen am 03.09.2026: ein einziges Stueck von 1.089,93 kB, davon
         * 380,5 kB Editor (tiptap und ProseMirror), 197,3 kB React, 58,8 kB
         * Kalenderseite, 43,9 kB i18next. Jede Zeile Anwendungscode machte
         * bisher alles davon ungueltig.
         *
         * ⚠️ **Der Editor haengt seit dem 04.09.2026 nicht mehr am Einstieg.**
         * ``lazy()`` in ``App.tsx`` holt ihn erst auf Klick; dieser Block
         * bestimmt nur noch, in welche Datei die Fremdbibliotheken wandern.
         * Der erste Besuch faellt damit von 1074 auf 528 kB.
         */
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@tiptap') || id.includes('prosemirror')) return 'editor'
          if (id.includes('i18next')) return 'sprachen'
          return 'geruest'
        },
      },
    },
  },

  server: {
    port: 5175,
    strictPort: true,
    headers: {
      'Content-Security-Policy': BILDREGEL,
    },
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: false },
    },
  },
})
