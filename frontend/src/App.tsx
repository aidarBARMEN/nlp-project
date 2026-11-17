import { useCallback, useEffect, useState } from 'react'
import {
  BarChart3,
  BookOpen,
  CarFront,
  ChevronsLeft,
  ChevronsRight,
  DoorOpen,
  FileCheck2,
  FlaskConical,
  FolderKanban,
  Menu,
  MessageSquare,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { api, type Health } from './api'
import { useConversations } from './store'
import ChatPage from './pages/ChatPage'
import KnowledgePage from './pages/KnowledgePage'
import LabPage from './pages/LabPage'
import MetricsPage from './pages/MetricsPage'
import DocflowPage from './pages/DocflowPage'
import PracticeCheckPage from './pages/PracticeCheckPage'
import ParkingPage from './pages/ParkingPage'
import CampusPage from './pages/CampusPage'
import DiplomaPage from './pages/DiplomaPage'

type Page = 'chat' | 'knowledge' | 'lab' | 'metrics' | 'docflow' | 'practice' | 'parking' | 'campus' | 'diploma' | 'diploma-registry'
type NavItem = { id: Page; label: string; icon: typeof MessageSquare }

// разделы сгруппированы по тем, кто ими пользуется
const SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: 'Студентам',
    items: [
      { id: 'chat', label: 'Ассистент', icon: MessageSquare },
      { id: 'practice', label: 'Проверка практики', icon: FileCheck2 },
      { id: 'diploma', label: 'Мой диплом', icon: BookOpen },
      { id: 'campus', label: 'Свободные аудитории', icon: DoorOpen },
      { id: 'parking', label: 'Парковка', icon: CarFront },
    ],
  },
  {
    title: 'Университету',
    items: [
      { id: 'diploma-registry', label: 'Дипломные проекты', icon: BookOpen },
      { id: 'docflow', label: 'Документооборот', icon: FolderKanban },
      { id: 'knowledge', label: 'База знаний', icon: BookOpen },
    ],
  },
  {
    title: 'Исследования',
    items: [
      { id: 'lab', label: 'NLP-лаборатория', icon: FlaskConical },
      { id: 'metrics', label: 'Метрики моделей', icon: BarChart3 },
    ],
  },
]
const NAV = SECTIONS.flatMap((s) => s.items)
const COLLAPSED_KEY = 'kbtu:sidebar-collapsed'

export default function App() {
  // раздел из адреса (#docflow) — чтобы на раздел можно было дать прямую ссылку
  const [page, setPage] = useState<Page>(() => {
    const hash = window.location.hash.slice(1).split('/')[0]
    return NAV.some((n) => n.id === hash) ? (hash as Page) : 'chat'
  })
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })
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
    window.history.replaceState(null, '', `#${p}`)
    setMenuOpen(false)
  }

  const toggleCollapsed = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, c ? '0' : '1')
      } catch {
        /* storage недоступен */
      }
      return !c
    })

  const current = NAV.find((n) => n.id === page)!

  const sidebar = (compact: boolean) => (
    <aside
      className={clsx(
        'flex h-full flex-col border-r border-slate-200/80 bg-white transition-[width] duration-200',
        compact ? 'w-[72px]' : 'w-64',
      )}
    >
      <div className={clsx('flex h-16 shrink-0 items-center', compact ? 'justify-center' : 'gap-3 px-5')}>
        {compact ? (
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-navy-900 text-[11px] font-bold tracking-tight text-white">
            KBTU
          </span>
        ) : (
          <>
            <img src="/kbtu-logo.png" alt="KBTU — Kazakh-British Technical University" className="h-8 w-auto" />
            <span className="h-6 w-px bg-slate-200" />
            <span className="text-[13px] leading-tight font-semibold text-navy-900">
              Smart
              <br />
              Assistant
            </span>
          </>
        )}
      </div>

      <nav className="scrollbar-thin flex-1 overflow-y-auto px-3 pb-3">
        {SECTIONS.map((section) => (
          <div key={section.title} className="mt-4 first:mt-2">
            {compact ? (
              <div className="mx-auto mb-2 h-px w-6 bg-slate-200" />
            ) : (
              <div className="mb-1.5 px-3 text-[11px] font-medium tracking-wide text-slate-400 uppercase">
                {section.title}
              </div>
            )}
            <div className="space-y-0.5">
              {section.items.map(({ id, label, icon: Icon }) => {
                const active = page === id
                return (
                  <button
                    key={id}
                    onClick={() => go(id)}
                    title={compact ? label : undefined}
                    className={clsx(
                      'relative flex w-full items-center gap-3 rounded-lg text-sm transition',
                      compact ? 'justify-center py-2.5' : 'px-3 py-2',
                      active ? 'bg-navy-50 font-semibold text-navy-900' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
                    )}
                  >
                    {active && <span className="absolute top-1.5 bottom-1.5 left-0 w-[3px] rounded-r bg-navy-900" />}
                    <Icon size={18} strokeWidth={active ? 2.2 : 1.8} className={active ? 'text-navy-900' : 'text-slate-400'} />
                    {!compact && label}
                  </button>
                )
              })}
            </div>

            {/* история диалогов — только в разделе ассистента */}
            {!compact && section.title === 'Студентам' && page === 'chat' && (
              <ConversationList convs={convs} onNew={() => convs.create()} />
            )}
          </div>
        ))}
      </nav>

      <div className={clsx('border-t border-slate-100', compact ? 'py-3' : 'px-4 py-3')}>
        <SystemStatus health={health} down={backendDown} compact={compact} />
        <button
          onClick={toggleCollapsed}
          className={clsx(
            'mt-2 hidden w-full items-center gap-2 rounded-lg py-1.5 text-xs text-slate-400 transition hover:bg-slate-50 hover:text-slate-700 lg:flex',
            compact ? 'justify-center' : 'px-2',
          )}
          title={compact ? 'Развернуть меню' : 'Свернуть меню'}
        >
          {compact ? <ChevronsRight size={16} /> : <><ChevronsLeft size={16} /> Свернуть меню</>}
        </button>
      </div>
    </aside>
  )

  return (
    <div className="flex h-full">
      <div className="hidden lg:block">{sidebar(collapsed)}</div>
      {menuOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div className="animate-fade-in shadow-2xl">{sidebar(false)}</div>
          <button className="flex-1 bg-slate-900/30 backdrop-blur-[2px]" onClick={() => setMenuOpen(false)} aria-label="Закрыть меню" />
        </div>
      )}

      <main className="bg-mesh flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur lg:hidden">
          <button onClick={() => setMenuOpen(true)} className="-ml-1 rounded-lg p-1.5 text-slate-600 hover:bg-slate-100" aria-label="Меню">
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <img src="/kbtu-logo.png" alt="KBTU" className="h-6 w-auto" />
          <span className="ml-auto truncate text-sm font-medium text-slate-700">{current.label}</span>
        </header>

        {page === 'chat' && <ChatPage convs={convs} health={health} />}
        {page === 'knowledge' && <KnowledgePage onChange={refreshHealth} health={health} />}
        {page === 'lab' && <LabPage />}
        {page === 'metrics' && <MetricsPage />}
        {page === 'docflow' && <DocflowPage />}
        {page === 'practice' && <PracticeCheckPage />}
        {page === 'parking' && <ParkingPage />}
        {page === 'campus' && <CampusPage />}
        {page === 'diploma' && <DiplomaPage key="student" />}
        {page === 'diploma-registry' && <DiplomaPage key="university" university />}
      </main>
    </div>
  )
}

function ConversationList({ convs, onNew }: { convs: ReturnType<typeof useConversations>; onNew: () => void }) {
  const list = convs.conversations.filter((c) => c.messages.length)
  return (
    <div className="mt-3 ml-3 border-l border-slate-200 pl-2">
      <button
        onClick={onNew}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-navy-800 transition hover:bg-navy-50"
      >
        <Plus size={14} /> Новый диалог
      </button>
      {list.length === 0 ? (
        <p className="px-2 py-1.5 text-xs text-slate-400">Здесь появятся ваши диалоги</p>
      ) : (
        <div className="scrollbar-thin max-h-[40vh] space-y-px overflow-y-auto">
          {list.map((c) => (
            <div
              key={c.id}
              className={clsx(
                'group flex items-center rounded-md text-[13px] transition',
                c.id === convs.activeId ? 'bg-slate-100 text-slate-900' : 'text-slate-600 hover:bg-slate-50',
              )}
            >
              <button onClick={() => convs.setActiveId(c.id)} className="min-w-0 flex-1 truncate px-2 py-1.5 text-left">
                {c.title}
              </button>
              <button
                onClick={() => convs.remove(c.id)}
                className="mr-1 rounded p-1 text-slate-400 opacity-0 transition group-hover:opacity-100 hover:text-rose-500"
                title="Удалить диалог"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SystemStatus({ health, down, compact }: { health: Health | null; down: boolean; compact: boolean }) {
  const [open, setOpen] = useState(false)
  const ok = !down && !!health?.openai_key && !!health?.chunks
  const label = down ? 'Сервер недоступен' : !health ? 'Подключение…' : ok ? 'Система работает' : 'Требует настройки'
  const rows: [boolean, string][] = [
    [!down, down ? 'Backend недоступен' : 'Backend подключён'],
    [!!health?.openai_key, health?.openai_key ? `Модель: ${health.chat_model}` : 'Нет OPENAI_API_KEY'],
    [!!health?.chunks, `База знаний: ${health?.documents ?? 0} док., ${health?.chunks ?? 0} фрагм.`],
  ]
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        title={compact ? label : undefined}
        className={clsx('flex w-full items-center gap-2 rounded-lg py-1.5 text-xs text-slate-500 transition hover:bg-slate-50',
          compact ? 'justify-center' : 'px-2')}
      >
        <span className={clsx('h-2 w-2 shrink-0 rounded-full', ok ? 'bg-emerald-500' : down ? 'bg-rose-500' : 'bg-amber-400')} />
        {!compact && <span className="truncate">{label}</span>}
      </button>
      {open && (
        <div className={clsx('absolute bottom-full z-50 mb-2 w-60 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-xl',
          compact ? 'left-2' : 'left-0')}>
          {rows.map(([good, text]) => (
            <div key={text} className="flex items-center gap-2 py-1 text-slate-600">
              <span className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', good ? 'bg-emerald-500' : 'bg-amber-400')} />
              {text}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
