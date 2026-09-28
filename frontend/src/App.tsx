import { useCallback, useEffect, useState } from 'react'
import { BookOpen, FlaskConical, Menu, MessageSquare, MessageSquarePlus, Trash2, X } from 'lucide-react'
import clsx from 'clsx'
import { api, type Health } from './api'
import { useConversations } from './store'
import ChatPage from './pages/ChatPage'
import KnowledgePage from './pages/KnowledgePage'
import LabPage from './pages/LabPage'

type Page = 'chat' | 'knowledge' | 'lab'

const NAV: { id: Page; label: string; icon: typeof MessageSquare }[] = [
  { id: 'chat', label: 'Ассистент', icon: MessageSquare },
  { id: 'knowledge', label: 'База знаний', icon: BookOpen },
  { id: 'lab', label: 'NLP-лаборатория', icon: FlaskConical },
]

export default function App() {
  const [page, setPage] = useState<Page>('chat')
  const [menuOpen, setMenuOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [backendDown, setBackendDown] = useState(false)
  const convs = useConversations()

  const refreshHealth = useCallback(() => {
    api
      .health()
      .then((h) => {
        setHealth(h)
        setBackendDown(false)
      })
      .catch(() => setBackendDown(true))
  }, [])

  useEffect(() => {
    refreshHealth()
    const t = setInterval(refreshHealth, 15000)
    return () => clearInterval(t)
  }, [refreshHealth])

  const go = (p: Page) => {
    setPage(p)
    setMenuOpen(false)
  }

  const sidebar = (
    <aside className="flex h-full w-72 flex-col bg-navy-900 text-slate-300">
      <div className="flex items-center gap-3 px-5 pt-6 pb-5">
        <img src="/logo.svg" alt="" className="h-10 w-10 rounded-xl shadow-lg shadow-brand-600/30" />
        <div className="leading-tight">
          <div className="font-display text-[15px] font-bold tracking-tight text-white">KBTU Smart</div>
          <div className="text-xs text-slate-400">Assistant · RAG</div>
        </div>
      </div>

      <nav className="space-y-1 px-3">
        {NAV.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => go(id)}
            className={clsx(
              'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition',
              page === id ? 'bg-white/10 text-white' : 'hover:bg-white/5 hover:text-white',
            )}
          >
            <Icon size={18} className={page === id ? 'text-brand-400' : ''} />
            {label}
          </button>
        ))}
      </nav>

      <div className="mt-6 flex items-center justify-between px-5">
        <span className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Диалоги</span>
        <button
          onClick={() => {
            convs.create()
            go('chat')
          }}
          className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
          title="Новый чат"
        >
          <MessageSquarePlus size={16} />
        </button>
      </div>
      <div className="scrollbar-thin mt-2 flex-1 space-y-0.5 overflow-y-auto px-3 pb-3">
        {convs.conversations.filter((c) => c.messages.length).length === 0 && (
          <p className="px-3 py-2 text-xs text-slate-500">Здесь появится история ваших вопросов</p>
        )}
        {convs.conversations
          .filter((c) => c.messages.length)
          .map((c) => (
            <div
              key={c.id}
              className={clsx(
                'group flex items-center rounded-lg text-sm transition',
                c.id === convs.activeId && page === 'chat' ? 'bg-white/10 text-white' : 'hover:bg-white/5',
              )}
            >
              <button
                onClick={() => {
                  convs.setActiveId(c.id)
                  go('chat')
                }}
                className="min-w-0 flex-1 truncate px-3 py-2 text-left"
              >
                {c.title}
              </button>
              <button
                onClick={() => convs.remove(c.id)}
                className="mr-1 rounded p-1 text-slate-500 opacity-0 transition group-hover:opacity-100 hover:text-rose-400"
                title="Удалить"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
      </div>

      <div className="border-t border-white/5 px-5 py-4 text-xs">
        <StatusRow ok={!backendDown} label={backendDown ? 'Backend недоступен' : 'Backend подключён'} />
        <StatusRow ok={!!health?.openai_key} label={health?.openai_key ? `OpenAI · ${health.chat_model}` : 'Нет OPENAI_API_KEY'} />
        <StatusRow ok={!!health?.chunks} label={`${health?.documents ?? 0} док. · ${health?.chunks ?? 0} чанков`} />
      </div>
    </aside>
  )

  return (
    <div className="flex h-full">
      <div className="hidden lg:block">{sidebar}</div>
      {menuOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div className="animate-fade-in">{sidebar}</div>
          <button className="flex-1 bg-navy-950/60 backdrop-blur-sm" onClick={() => setMenuOpen(false)} aria-label="Закрыть" />
        </div>
      )}

      <main className="bg-mesh flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200/70 bg-white/70 px-4 py-3 backdrop-blur lg:hidden">
          <button onClick={() => setMenuOpen(true)} className="rounded-lg p-1.5 hover:bg-slate-100">
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <img src="/logo.svg" alt="" className="h-7 w-7 rounded-lg" />
          <span className="font-display text-sm font-bold">KBTU Smart Assistant</span>
        </header>

        {page === 'chat' && <ChatPage convs={convs} health={health} />}
        {page === 'knowledge' && <KnowledgePage onChange={refreshHealth} health={health} />}
        {page === 'lab' && <LabPage />}
      </main>
    </div>
  )
}

function StatusRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className={clsx('h-1.5 w-1.5 rounded-full', ok ? 'bg-emerald-400 shadow-[0_0_8px] shadow-emerald-400' : 'bg-amber-400')} />
      <span className="truncate text-slate-400">{label}</span>
    </div>
  )
}
