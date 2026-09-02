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
