"""Erzeugt src/lib/nextasksSymbole.ts aus nextasks' src/lib/symbols.ts.

Aufruf (aus frontend/): python tools/nextasks_symbole.py <nextasks/frontend/src/lib/symbols.ts> src/lib/nextasksSymbole.ts
"""
import pathlib
import re
import sys

quelle = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
eintraege = re.findall(r"\{ name: '([^']+)', icon: (\w+), group: '\w+', words: '([^']*)' \}", quelle)
assert len(eintraege) > 200, len(eintraege)
icons = sorted({i for _, i, _ in eintraege} | {"ListIcon"})
zeilen = [
    "/* Die Symbole von nextasks (MAIL-2, Postfächer): Name, Lucide-Icon, Suchwörter",
    " * deutsch und englisch.",
    " *",
    " * ⚠️ **Erzeugt, nicht von Hand ändern.** Quelle ist `nextasks/frontend/src/lib/symbols.ts`",
    " * (dort erzeugt aus einer gemeinsamen Liste). Neu erzeugen mit `tools/nextasks_symbole.py`;",
    " * es liest nur die Einträge `{ name, icon, group, words }`. Ein unbekannter Name zeigt das",
    " * Listen-Symbol, wie in nextasks.",
    " */",
    "import {",
    *[f"  {i}," for i in icons],
    "  type LucideIcon,",
    "} from 'lucide-react'",
    "",
    "export interface Symbol {",
    "  name: string",
    "  icon: LucideIcon",
    "  worte: string",
    "}",
    "",
    "export const SYMBOLE: Symbol[] = [",
    *[f"  {{ name: '{n}', icon: {i}, worte: '{w}' }}," for n, i, w in eintraege],
    "]",
    "",
    "const NACH_NAME = new Map(SYMBOLE.map((s) => [s.name, s.icon]))",
    "",
    "export function symbolFuer(name: string | null | undefined): LucideIcon {",
    "  return NACH_NAME.get(name ?? '') ?? ListIcon",
    "}",
    "",
    "/** Klein, ohne Akzente: „kuhl“ findet „Kühlschrank“ (wie nextasks). */",
    "function schlicht(text: string): string {",
    "  return text.toLowerCase().replaceAll('ß', 'ss').normalize('NFD').replace(/\\p{Diacritic}/gu, '')",
    "}",
    "",
    "/** Jedes getippte Wort muss ein Wort des Symbols beginnen (wie in nextasks). */",
    "export function symboleSuchen(text: string): Symbol[] {",
    "  const teile = schlicht(text).split(/[\\s-]+/).filter(Boolean)",
    "  if (!teile.length) return SYMBOLE",
    "  return SYMBOLE.filter((s) => {",
    "    const eigene = schlicht(`${s.name} ${s.worte}`).split(/[\\s-]+/)",
    "    return teile.every((t) => eigene.some((w) => w.startsWith(t)))",
    "  })",
    "}",
    "",
]
pathlib.Path(sys.argv[2]).write_text("\n".join(zeilen), encoding="utf-8")
print(len(eintraege), "Symbole")
