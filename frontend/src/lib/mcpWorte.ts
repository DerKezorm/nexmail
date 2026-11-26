/* nexmails Wörter für die Bausteine des Moduls mcp und die Karte „KI-Werkzeuge (MCP)“ (Modul schluessel): Stufen,
 * das Extra „Mailtext lesen“, die Postfächer und die Namen der Werkzeuge. Die Werkzeuge selbst stehen im Server
 * (`services/mcp_werkzeuge.py`); fehlt hier ein Name, zeigt der Baustein den englischen. */
import type { TFunction } from 'i18next'

import type { McpWords } from '../vendor/nexmcp'
import type { AppWords } from '../vendor/nexschluessel/schluessel'

export const WERKZEUGE = [
  'mailbox_summary',
  'search_messages',
  'read_message',
  'list_tags',
  'list_tasks',
  'draft_reply',
  'create_draft',
  'set_tags',
  'move_message',
  'complete_task',
  'request_status',
] as const

const STUFEN = ['read', 'draft', 'write'] as const

export function mcpWorte(t: TFunction): McpWords {
  return {
    tools: Object.fromEntries(WERKZEUGE.map((name) => [name, t(`mcp.w_${name}`)])),
    levels: Object.fromEntries(STUFEN.map((stufe) => [stufe, t(`mcp.stufe_${stufe}`)])),
    levelHints: Object.fromEntries(STUFEN.map((stufe) => [stufe, t(`mcp.stufe_${stufe}_hinweis`)])),
    extras: { mailtext: t('mcp.mailtext') },
    extraHints: { mailtext: t('mcp.mailtext_hinweis') },
  }
}

/** Für die Karte „KI-Werkzeuge (MCP)“ (Formular „Neuer MCP-Schlüssel“). */
export function mcpSchluesselWorte(t: TFunction): AppWords {
  return {
    rights: Object.fromEntries(STUFEN.map((stufe) => [stufe, t(`mcp.stufe_${stufe}`)])),
    rightHints: Object.fromEntries(STUFEN.map((stufe) => [stufe, t(`mcp.stufe_${stufe}_hinweis`)])),
    options: { mailtext: t('mcp.mailtext') },
    optionHints: { mailtext: t('mcp.mailtext_hinweis') },
    areas: t('mcp.postfaecher'),
  }
}
