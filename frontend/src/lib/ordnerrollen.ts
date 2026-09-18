/**
 * Was sich einem Ordner von Hand zuweisen laesst („Verwenden als").
 *
 * ⚠️ **Dieselbe Liste wie `ZUWEISBARE_ROLLEN` im Server**
 * (`services/konten.py`). Laufen sie auseinander, bietet das Menue etwas an,
 * das der Server abweist; ein Test im Server haelt beide aneinander.
 *
 * Der Posteingang fehlt mit Absicht: `INBOX` legt das Protokoll fest.
 * `eigen` steht zuletzt und heisst im Menue „Gewoehnlicher Ordner" — eine
 * echte Zuweisung, keine Ruecknahme: „das ist KEIN Papierkorb", auch wenn der
 * Ordner so heisst.
 */
export const ZUWEISBARE_ROLLEN = [
  'gesendet',
  'entwuerfe',
  'archiv',
  'junk',
  'papierkorb',
  'eigen',
] as const
