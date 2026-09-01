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
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5175,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: false },
    },
  },
})
