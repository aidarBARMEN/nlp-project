import { useEffect, useRef, useState } from 'react'
import {
  ArrowUp,
  BookMarked,
  Building2,
  Clock,
  GraduationCap,
  Library,
  Search,
  Sparkles,
  Square,
  Wallet,
  AlertTriangle,
} from 'lucide-react'
import clsx from 'clsx'
import { streamChat, type ChatMessage, type Health } from '../api'
import type { useConversations } from '../store'
import Markdown from '../components/Markdown'
import SourceCard from '../components/SourceCard'

const SUGGESTIONS = [
  { icon: GraduationCap, title: 'GPA и пересдачи', q: 'Как рассчитывается GPA и какие правила пересдачи (Retake)?' },
  { icon: Wallet, title: 'Гранты и оплата', q: 'Какие условия перевода с платного обучения на грант?' },
  { icon: Clock, title: 'Add/Drop', q: 'Когда проходит период Add/Drop и как зарегистрироваться на дисциплины?' },
  { icon: Building2, title: 'Дом студентов', q: 'Какие правила проживания и процедура заселения в ДС?' },
  { icon: BookMarked, title: 'Справки', q: 'Как получить справку с места учёбы через Uninet?' },
  { icon: Library, title: 'Инфраструктура', q: 'Какой график работы библиотеки и спорткомплекса?' },
]

type Convs = ReturnType<typeof useConversations>

export default function ChatPage({ convs, health }: { convs: Convs; health: Health | null }) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messages = convs.active?.messages ?? []

  useEffect(() => {
    const el = scrollRef.current
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 200) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [convs.activeId])

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [input])

  async function send(text: string) {
    const question = text.trim()
    if (!question || busy) return
    const conv = convs.active ?? convs.create()
    const history = conv.messages.filter((m) => !m.error).map(({ role, content }) => ({ role, content }))

    setInput('')
    setBusy(true)
    convs.update(conv.id, (c) => ({
      ...c,
      title: c.messages.length ? c.title : question.slice(0, 60),
      messages: [...c.messages, { role: 'user', content: question }, { role: 'assistant', content: '' }],
    }))
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }))

    const patchLast = (fn: (m: ChatMessage) => ChatMessage) =>
      convs.update(conv.id, (c) => ({ ...c, messages: [...c.messages.slice(0, -1), fn(c.messages[c.messages.length - 1])] }))

    const ctrl = new AbortController()
    abortRef.current = ctrl
    await streamChat(
      question,
      history,
      {
        onSources: ({ query, sources }) => patchLast((m) => ({ ...m, sources, query })),
        onToken: (t) => patchLast((m) => ({ ...m, content: m.content + t })),
        onDone: (meta) => patchLast((m) => ({ ...m, meta })),
        onError: (detail) => patchLast((m) => ({ ...m, error: detail })),
      },
      ctrl.signal,
    )
    setBusy(false)
    abortRef.current = null
  }

  const empty = messages.length === 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="scrollbar-thin flex-1 overflow-y-auto">
        {empty ? (
          <EmptyState onPick={send} health={health} />
        ) : (
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
            {messages.map((m, i) => (
              <MessageView key={i} m={m} streaming={busy && i === messages.length - 1} />
            ))}
          </div>
        )}
      </div>

      <div className="px-4 pt-2 pb-4">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
          className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-lg shadow-slate-900/5 transition focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-100"
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send(input)
              }
            }}
            rows={1}
            placeholder="Спросите о правилах, сроках, процедурах КБТУ…"
            className="max-h-[200px] flex-1 resize-none bg-transparent px-3 py-2 text-[15px] outline-none placeholder:text-slate-400"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-800 text-white transition hover:bg-slate-700"
              title="Остановить"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-md shadow-brand-600/30 transition hover:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </form>
        <p className="mt-2 text-center text-[11px] text-slate-400">
          Ответы основаны только на официальных документах КБТУ. Проверяйте важную информацию в Офисе Регистратора.
        </p>
      </div>
    </div>
  )
}

function EmptyState({ onPick, health }: { onPick: (q: string) => void; health: Health | null }) {
  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-4 py-10">
      <div className="animate-fade-in text-center">
        <div className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white/80 px-3 py-1 text-xs font-medium text-brand-700 shadow-sm">
          <Sparkles size={13} /> Retrieval-Augmented Generation
        </div>
        <h1 className="font-display text-3xl font-bold tracking-tight text-navy-900 sm:text-4xl">
          Привет! Я ассистент <span className="bg-gradient-to-r from-brand-600 to-sky-500 bg-clip-text text-transparent">КБТУ</span>
        </h1>
        <p className="mx-auto mt-3 max-w-lg text-slate-500">
          Отвечаю на вопросы об академической политике, Uninet, грантах и студенческой жизни — строго по официальным
          документам и со ссылками на источники.
        </p>
      </div>

      {health && !health.openai_key && (
        <Notice>
          Для ответов требуется ключ OpenAI. Укажите его в <code>.env</code> в корне проекта и перезапустите сервер.
        </Notice>
      )}
      {health && health.openai_key && health.chunks === 0 && (
        <Notice>Подготовьте и подтвердите официальные документы на вкладке «База знаний».</Notice>
      )}

      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {SUGGESTIONS.map(({ icon: Icon, title, q }, i) => (
          <button
            key={title}
            onClick={() => onPick(q)}
            style={{ animationDelay: `${i * 50}ms` }}
            className="group animate-fade-in rounded-2xl border border-slate-200 bg-white/80 p-4 text-left shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-md"
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition group-hover:bg-brand-600 group-hover:text-white">
              <Icon size={18} />
            </div>
            <div className="text-sm font-semibold text-slate-800">{title}</div>
            <div className="mt-1 line-clamp-2 text-xs text-slate-500">{q}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto mt-6 flex max-w-lg items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <div>{children}</div>
    </div>
  )
}

function MessageView({ m, streaming }: { m: ChatMessage; streaming: boolean }) {
  const [showSources, setShowSources] = useState(false)
  const [highlight, setHighlight] = useState<number | null>(null)

  if (m.role === 'user') {
    return (
      <div className="flex animate-fade-in justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-navy-900 px-4 py-2.5 text-[15px] whitespace-pre-wrap text-white shadow-md">
          {m.content}
        </div>
      </div>
    )
  }

  const cite = (n: number) => {
    setShowSources(true)
    setHighlight(n)
    setTimeout(() => {
      const src = m.sources?.find((s) => s.n === n)
      if (src) document.getElementById(`src-${src.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, 50)
    setTimeout(() => setHighlight(null), 2000)
  }

  const waiting = streaming && !m.content && !m.error

  return (
    <div className="flex animate-fade-in gap-3">
      <img src="/logo.svg" alt="" className="mt-0.5 h-8 w-8 shrink-0 rounded-lg shadow" />
      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-md border border-slate-200/80 bg-white px-5 py-4 shadow-sm">
          {waiting && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Search size={15} className="animate-pulse text-brand-500" />
              {m.sources ? 'Формирую ответ…' : 'Ищу в документах КБТУ…'}
            </div>
          )}
          {m.content && (
            <div className={clsx(streaming && 'cursor-caret')}>
              <Markdown text={m.content} onCite={cite} />
            </div>
          )}
          {m.error && (
            <div className="flex items-start gap-2 text-sm text-rose-600">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {m.error}
            </div>
          )}
        </div>

        {!!m.sources?.length && (
          <div className="mt-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-xs text-slate-500">
              <button onClick={() => setShowSources((s) => !s)} className="font-medium text-brand-600 hover:text-brand-700">
                {showSources ? 'Скрыть' : 'Показать'} источники ({m.sources.length})
              </button>
              {m.meta?.total_ms !== undefined && (
                <span>
                  поиск {m.meta.retrieval_ms} мс · всего {(m.meta.total_ms / 1000).toFixed(1)} с
                </span>
              )}
            </div>
            {showSources && (
              <div className="mt-2 grid animate-fade-in gap-2">
                {m.sources.map((s) => (
                  <SourceCard key={s.id} source={s} highlighted={highlight === s.n} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
