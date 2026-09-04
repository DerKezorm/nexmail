/* Der Editor mit der Outlook-Formatierleiste.
 *
 * Zuschnitt nach der Entscheidung „wer Outlook bedienen kann, soll sich hier
 * zu Hause fühlen": Schriftart, Größe, fett/kursiv/unterstrichen, Textfarbe,
 * Hervorheben, Aufzählung, Nummerierung, Einzug, Ausrichtung, Link, Zitat,
 * Bild, Formatierung entfernen.
 *
 * ⚠️ **Tabellen fehlen mit Absicht** — sie stehen in SPAETER.md. In Mail-HTML
 * gehen sie nur mit veralteten Attributen zuverlässig durch alle Clients.
 *
 * ⚠️ **Was hier herauskommt, wird im Server noch einmal bereinigt.** Der
 * Editor ist keine Sicherheitsgrenze: Wer eine Mail weiterleitet, trägt
 * fremdes HTML in den eigenen Entwurf, und das geht denselben Weg wie beim
 * Anzeigen.
 */
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { EditorContent, useEditor } from '@tiptap/react'
import type { Editor as TiptapEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import { TextStyle } from '@tiptap/extension-text-style'
import { Color } from '@tiptap/extension-color'
import FontFamily from '@tiptap/extension-font-family'
import Highlight from '@tiptap/extension-highlight'
import Link from '@tiptap/extension-link'
import TextAlign from '@tiptap/extension-text-align'
import Image from '@tiptap/extension-image'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  Highlighter,
  Image as BildSymbol,
  IndentDecrease,
  IndentIncrease,
  Italic,
  Link2,
  List,
  ListOrdered,
  Quote,
  RemoveFormatting,
  Underline as UnterstrichenSymbol,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useNachfrage } from './Nachfrage'

const SCHRIFTARTEN = ['Arial', 'Calibri', 'Georgia', 'Helvetica', 'Times New Roman', 'Verdana']
const GROESSEN = ['9', '10', '11', '12', '14', '18', '24', '36']

interface Props {
  /** Startinhalt — Zitat oder Weiterleitungsblock. */
  inhalt: string
  aufAendern: (html: string) => void
  /** Ein eingefügtes Bild soll als Anhang mitfahren, nicht als data:-URI. */
  aufBild: (datei: File) => Promise<string>
  /** Reicht die Editor-Instanz nach draußen — für Befehle an der
   *  Schreibmarke (Textvorlage einfügen). `null`, sobald sie weg ist. */
  aufEditor?: (editor: TiptapEditor | null) => void
}

export function Editor({ inhalt, aufAendern, aufBild, aufEditor }: Props) {
  const editor = useEditor({
    /* ⚠️ **Nicht schon beim Rendern bauen, sondern in der Wirkung.**
       `useEditor` legt den Editor sonst mitten im Rendern an und plant im
       selben Atemzug seine Zerstörung in einer Millisekunde
       (`EditorInstanceManager`: `setEditor(getInitialEditor()); scheduleDestroy()`).
       Abbestellt wird die erst von der Mount-Wirkung. Damit gilt eine
       stillschweigende Annahme: Zwischen Rendern und Festschreiben liegt
       weniger als eine Millisekunde.

       Am 04.09.2026 gebrochen, als der Editor per `lazy()` nachgeladen wurde:
       Er entsteht dann in demselben Festschreibe-Vorgang wie das ganze
       Verfassen-Fenster, und der dauert länger. Der Editor war tot, bevor
       seine eigene Wirkung lief — `getHTML()` fiel über `schema === null`,
       und die Anwendung war weiß. Mit `false` entsteht er in der Wirkung, und
       die Frist läuft gar nicht erst.

       ⚠️ Der Preis ist ein Durchgang mit `editor === null`. Den gab es vorher
       auch schon (unten `if (!editor)`), er ist nur jetzt der Normalfall. */
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({ heading: false }),
      Underline,
      TextStyle,
      Color,
      FontFamily,
      Highlight.configure({ multicolor: true }),
      Link.configure({ openOnClick: false, autolink: true }),
      TextAlign.configure({ types: ['paragraph'] }),
      Image.configure({ inline: true }),
    ],
    content: inhalt,
    onUpdate: ({ editor }) => aufAendern(editor.getHTML()),
    editorProps: {
      attributes: {
        class:
          'prose-nexmail min-h-full px-5 py-4 text-sm leading-relaxed text-fg-1 outline-none',
      },
      handlePaste(sicht, ereignis) {
        // Ein eingefügtes Bildschirmfoto wird zum Anhang mit cid: — nicht zu
        // einem data:-URI. Der bläht die Mail auf und wird von vielen
        // Empfängern gar nicht angezeigt.
        const dateien = Array.from(ereignis.clipboardData?.files ?? [])
        const bilder = dateien.filter((d) => d.type.startsWith('image/'))
        if (bilder.length === 0) return false
        void Promise.all(bilder.map(aufBild)).then((quellen) => {
          for (const quelle of quellen) {
            sicht.dispatch(
              sicht.state.tr.replaceSelectionWith(
                sicht.state.schema.nodes.image.create({ src: quelle }),
              ),
            )
          }
        })
        return true
      },
    },
  })

  useEffect(() => {
    aufEditor?.(editor)
    return () => aufEditor?.(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor])

  // Wenn von außen ein anderer Startinhalt kommt (andere Nachricht), muss der
  // Editor ihn übernehmen — sonst steht die vorige Antwort noch drin.
  useEffect(() => {
    /* ⚠️ **Ein zerstörter Editor ist immer noch wahr.** `editor` allein zu
       prüfen genügt nicht: Nach `destroy()` steht das Objekt weiter da, aber
       `schema` ist null, und `getHTML()` wirft. Genau daran ist die Anwendung
       am 04.09.2026 gestorben. */
    if (!editor || editor.isDestroyed) return
    if (inhalt !== editor.getHTML()) {
      editor.commands.setContent(inhalt, { emitUpdate: false })
    }
    /* ⚠️ **`editor` gehört in die Liste.** Wird er ausgetauscht, muss der
       Inhalt mitkommen — sonst öffnet sich das Fenster ohne Zitat und ohne
       Signatur, und das sagt niemand. */
  }, [inhalt, editor])

  if (!editor) return <div className="min-h-0 flex-1" />

  return (
    <>
      <Leiste editor={editor} aufBild={aufBild} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <EditorContent editor={editor} className="h-full" />
      </div>
    </>
  )
}

function Leiste({ editor, aufBild }: { editor: TiptapEditor; aufBild: Props['aufBild'] }) {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()

  function bildWaehlen() {
    const feld = document.createElement('input')
    feld.type = 'file'
    feld.accept = 'image/*'
    feld.onchange = () => {
      const datei = feld.files?.[0]
      if (datei) void aufBild(datei).then((quelle) => editor.chain().focus().setImage({ src: quelle }).run())
    }
    feld.click()
  }

  async function linkSetzen() {
    const vorher = editor.getAttributes('link').href as string | undefined
    // ⚠️ Eigenes Fenster statt `window.prompt`: Ein Browser-Kasten trägt die
    // Adresse der Seite im Titel, ignoriert das Design — und lässt sich vom
    // Betreiber dauerhaft abschalten, dann tut der Knopf einfach nichts.
    const eingabe = await fragen({
      titel: t('format.link'),
      eingabe: { beschriftung: t('format.link_adresse'), vorgabe: vorher ?? 'https://' },
      knopf: t('format.link_setzen'),
    })
    if (eingabe === null || typeof eingabe !== 'string') return
    if (eingabe.trim() === '') {
      editor.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: eingabe.trim() }).run()
  }

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-y border-line-subtle bg-surface-2 px-2 py-1">
      <select
        aria-label={t('format.schriftart')}
        onChange={(e) =>
          e.target.value
            ? editor.chain().focus().setFontFamily(e.target.value).run()
            : editor.chain().focus().unsetFontFamily().run()
        }
        className="h-7 w-[112px] shrink-0 cursor-pointer rounded-sm border border-line bg-surface-1 px-1.5 text-[12px] text-fg-2 outline-none hover:border-line-strong"
      >
        {SCHRIFTARTEN.map((s) => (
          <option key={s} value={s} className="bg-surface-1 text-fg-1">
            {s}
          </option>
        ))}
      </select>

      <select
        aria-label={t('format.groesse')}
        defaultValue="11"
        onChange={(e) => {
          // Tiptap kennt keine Punktgrößen; gesetzt wird ein Stil auf der
          // Textmarke. Das ist genau das, was in Mail-HTML ankommt.
          editor.chain().focus().setMark('textStyle', { fontSize: `${e.target.value}pt` }).run()
        }}
        className="h-7 w-[56px] shrink-0 cursor-pointer rounded-sm border border-line bg-surface-1 px-1.5 text-[12px] text-fg-2 outline-none hover:border-line-strong"
      >
        {GROESSEN.map((g) => (
          <option key={g} value={g} className="bg-surface-1 text-fg-1">
            {g}
          </option>
        ))}
      </select>

      <Trenner />
      <Knopf symbol={<Bold />} text={t('format.fett')} an={editor.isActive('bold')}
        tun={() => editor.chain().focus().toggleBold().run()} />
      <Knopf symbol={<Italic />} text={t('format.kursiv')} an={editor.isActive('italic')}
        tun={() => editor.chain().focus().toggleItalic().run()} />
      <Knopf symbol={<UnterstrichenSymbol />} text={t('format.unterstrichen')}
        an={editor.isActive('underline')}
        tun={() => editor.chain().focus().toggleUnderline().run()} />

      <label
        title={t('format.textfarbe')}
        className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-sm text-fg-3 hover:bg-surface-3 hover:text-fg-1"
      >
        <Baseline className="size-4" />
        <input
          type="color"
          className="sr-only"
          onChange={(e) => editor.chain().focus().setColor(e.target.value).run()}
        />
      </label>
      <Knopf symbol={<Highlighter />} text={t('format.markieren')} an={editor.isActive('highlight')}
        tun={() => editor.chain().focus().toggleHighlight({ color: '#fff3a3' }).run()} />

      <Trenner />
      <Knopf symbol={<List />} text={t('format.aufzaehlung')} an={editor.isActive('bulletList')}
        tun={() => editor.chain().focus().toggleBulletList().run()} />
      <Knopf symbol={<ListOrdered />} text={t('format.nummerierung')} an={editor.isActive('orderedList')}
        tun={() => editor.chain().focus().toggleOrderedList().run()} />
      <Knopf symbol={<IndentDecrease />} text={t('format.einzug_raus')}
        tun={() => editor.chain().focus().liftListItem('listItem').run()} />
      <Knopf symbol={<IndentIncrease />} text={t('format.einzug_rein')}
        tun={() => editor.chain().focus().sinkListItem('listItem').run()} />

      <Trenner />
      <Knopf symbol={<AlignLeft />} text={t('format.links')} an={editor.isActive({ textAlign: 'left' })}
        tun={() => editor.chain().focus().setTextAlign('left').run()} />
      <Knopf symbol={<AlignCenter />} text={t('format.mitte')} an={editor.isActive({ textAlign: 'center' })}
        tun={() => editor.chain().focus().setTextAlign('center').run()} />
      <Knopf symbol={<AlignRight />} text={t('format.rechts')} an={editor.isActive({ textAlign: 'right' })}
        tun={() => editor.chain().focus().setTextAlign('right').run()} />

      <Trenner />
      <Knopf
        symbol={<Link2 />}
        text={t('format.link')}
        an={editor.isActive('link')}
        tun={() => void linkSetzen()}
      />
      <Knopf symbol={<Quote />} text={t('format.zitat')} an={editor.isActive('blockquote')}
        tun={() => editor.chain().focus().toggleBlockquote().run()} />
      <Knopf symbol={<BildSymbol />} text={t('format.bild')} tun={bildWaehlen} />
      <Knopf symbol={<RemoveFormatting />} text={t('format.entfernen')}
        tun={() => editor.chain().focus().unsetAllMarks().clearNodes().run()} />
      {nachfrage}
    </div>
  )
}

function Trenner() {
  return <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-line" />
}

function Knopf({
  symbol,
  text,
  an = false,
  tun,
}: {
  symbol: ReactNode
  text: string
  an?: boolean
  tun: () => void
}) {
  return (
    <button
      type="button"
      title={text}
      aria-label={text}
      aria-pressed={an}
      onClick={tun}
      className={
        'flex size-7 shrink-0 items-center justify-center rounded-sm ' +
        'transition-colors duration-[var(--dur-fast)] [&_svg]:size-4 ' +
        (an ? 'bg-accent-soft text-accent-text' : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
      }
    >
      {symbol}
    </button>
  )
}
