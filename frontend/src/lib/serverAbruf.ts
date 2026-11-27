/* Der Weg der Module zum Server: `fetch` mit dem Vorbau (`BASIS`) und dem Sitzungs-Cookie. Für die Module, die einen
 * `Fetcher` nehmen (wasneu, updates); die eigenen Aufrufe der Oberfläche gehen über `api/client.ts`. */
import { BASIS } from './basis'

export const serverAbruf = (pfad: string, init: RequestInit): Promise<Response> =>
  fetch(`${BASIS}${pfad}`, { credentials: 'include', ...init })
