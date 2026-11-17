import { useEffect, useState } from 'react'
import { FilePlus2, Info, Loader2, UserRound } from 'lucide-react'
import clsx from 'clsx'
import { edo, type Meta } from '../edo'
import Architecture from './docflow/Architecture'
import DocumentDrawer from './docflow/DocumentDrawer'
import Overview from './docflow/Overview'
import PersonalFiles from './docflow/PersonalFiles'
import RegisterDialog from './docflow/RegisterDialog'
import Registry from './docflow/Registry'

type Tab = 'overview' | 'registry' | 'files' | 'approvals' | 'architecture'

const ROLE_KEY = 'kbtu-edo:role'

export default function DocflowPage() {
  const [role, setRole] = useState(() => {
    try {
      return localStorage.getItem(ROLE_KEY) || 'rector'
    } catch {
      return 'rector'
    }
  })
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTabState] = useState<Tab>(() => {
    const sub = window.location.hash.split('/')[1]
    return (['overview', 'registry', 'files', 'approvals', 'architecture'] as Tab[]).includes(sub as Tab)
      ? (sub as Tab)
      : 'overview'
  })
  const setTab = (t: Tab) => {
    setTabState(t)
    window.history.replaceState(null, '', `#docflow/${t}`)
  }
  const [category, setCategory] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const [registering, setRegistering] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [pending, setPending] = useState(0)

  useEffect(() => {
    setMeta(null)
    setCategory('')
    edo.meta(role).then(setMeta).catch((e) => setError(e.message))
    try {
      localStorage.setItem(ROLE_KEY, role)
    } catch {
      /* storage недоступен */
    }
  }, [role])

  useEffect(() => {
    edo.dashboard(role).then((d) => setPending(d.pending_for_me)).catch(() => setPending(0))
  }, [role, refreshKey])

  const refresh = () => setRefreshKey((k) => k + 1)
  const current = meta?.roles.find((r) => r.code === role)

  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: 'overview', label: 'Обзор' },
    { id: 'registry', label: 'Реестр документов' },
    { id: 'files', label: 'Личные дела' },
    { id: 'approvals', label: 'На согласовании', badge: pending },
    { id: 'architecture', label: 'Архитектура' },
  ]

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-7xl px-4 py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-xs font-semibold tracking-wider text-brand-600 uppercase">Электронный документооборот</div>
            <h1 className="mt-1 font-display text-2xl font-bold text-navy-900">Документы университета</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">
              Личные дела, приём, учебный процесс, практика, медицина, командировки и кадры — в одном реестре с
              маршрутами согласования и сроками хранения.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-navy-900 text-white">
                <UserRound size={14} />
              </span>
              <span className="leading-tight">
                <span className="block text-[10px] text-slate-500 uppercase">Вы работаете как</span>
                <select value={role} onChange={(e) => setRole(e.target.value)}
                        className="cursor-pointer bg-transparent text-sm font-semibold text-slate-800 outline-none">
                  {(meta?.roles ?? [{ code: role, name: '…', unit: '' }]).map((r) => (
                    <option key={r.code} value={r.code}>{r.name}</option>
                  ))}
                </select>
              </span>
            </label>
            {meta && meta.creatable_types.length > 0 && (
              <button
                onClick={() => setRegistering(true)}
                className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-4 py-2.5 text-sm font-medium text-white shadow-md shadow-navy-900/20 transition hover:bg-navy-800"
              >
                <FilePlus2 size={16} /> Зарегистрировать
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            Демонстрационный режим: все студенты, сотрудники и документы вымышлены. Роль выбирается вручную;
            при внедрении она определяется учётной записью КБТУ.
            {current && <> Подразделение: <b>{current.unit}</b>.</>}
          </span>
        </div>

        <div className="mt-5 flex gap-1 overflow-x-auto border-b border-slate-200">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                '-mb-px inline-flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition',
                tab === t.id ? 'border-navy-900 text-navy-900' : 'border-transparent text-slate-500 hover:text-slate-800',
              )}
            >
              {t.label}
              {!!t.badge && (
                <span className="rounded-full bg-amber-500 px-1.5 py-px text-[10px] font-semibold text-white">{t.badge}</span>
              )}
            </button>
          ))}
        </div>

        <div className="mt-5">
          {error && <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
          {!meta && !error && <Loader2 className="mx-auto mt-16 animate-spin text-slate-400" />}
          {meta && tab === 'overview' && (
            <Overview
              role={role}
              refreshKey={refreshKey}
              onOpen={setOpenId}
              onCategory={(c) => {
                setCategory(c)
                setTab('registry')
              }}
              onPending={() => setTab('approvals')}
            />
          )}
          {meta && tab === 'registry' && (
            <Registry role={role} meta={meta} refreshKey={refreshKey} category={category} onCategory={setCategory} onOpen={setOpenId} />
          )}
          {meta && tab === 'approvals' && (
            <Registry role={role} meta={meta} refreshKey={refreshKey} category="" onCategory={() => undefined} pendingOnly onOpen={setOpenId} />
          )}
          {meta && tab === 'files' && <PersonalFiles role={role} meta={meta} refreshKey={refreshKey} onOpen={setOpenId} />}
          {meta && tab === 'architecture' && <Architecture meta={meta} />}
        </div>
      </div>

      {openId !== null && (
        <DocumentDrawer role={role} id={openId} onClose={() => setOpenId(null)} onChanged={refresh} />
      )}
      {registering && meta && (
        <RegisterDialog
          role={role}
          meta={meta}
          onClose={() => setRegistering(false)}
          onCreated={(id) => {
            setRegistering(false)
            refresh()
            setOpenId(id)
          }}
        />
      )}
    </div>
  )
}
