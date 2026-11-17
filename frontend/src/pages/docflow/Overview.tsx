import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, Clock3, FileStack, Hourglass, Inbox, Loader2 } from 'lucide-react'
import { edo, fmtDate, type Dashboard } from '../../edo'
import { AccessBadge, Card, CATEGORY_ICON, Empty, Kpi, StatusBadge } from './ui'

export default function Overview({
  role,
  refreshKey,
  onOpen,
  onCategory,
  onPending,
}: {
  role: string
  refreshKey: number
  onOpen: (id: number) => void
  onCategory: (code: string) => void
  onPending: () => void
}) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    edo.dashboard(role).then(setData).catch((e) => setError(e.message))
  }, [role, refreshKey])

  if (error) return <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
  if (!data) return <Loader2 className="mx-auto mt-16 animate-spin text-slate-400" />

  const max = Math.max(1, ...data.by_category.map((c) => c.count))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi icon={FileStack} label="Документов доступно" value={data.totals.all} hint={`+${data.totals.new_30d} за 30 дней`} />
        <Kpi icon={Inbox} label="Ждут моего решения" value={data.pending_for_me} tone={data.pending_for_me ? 'warn' : 'default'}
             hint="текущий шаг маршрута" />
        <Kpi icon={Clock3} label="На согласовании" value={data.totals.on_approval} hint="во всех подразделениях" />
        <Kpi icon={AlertTriangle} label="Просрочено" value={data.totals.overdue} tone={data.totals.overdue ? 'bad' : 'default'}
             hint="срок согласования истёк" />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card title="Документы по разделам" className="lg:col-span-3">
          <div className="divide-y divide-slate-100">
            {data.by_category.map((c) => {
              const Icon = CATEGORY_ICON[c.category] ?? FileStack
              return (
                <button
                  key={c.category}
                  onClick={() => onCategory(c.category)}
                  className="group flex w-full items-center gap-3 px-5 py-2.5 text-left transition hover:bg-slate-50"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy-900/5 text-navy-800">
                    <Icon size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                      {c.name} <AccessBadge access={c.access} />
                    </div>
                    <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-navy-800" style={{ width: `${(c.count / max) * 100}%` }} />
                    </div>
                  </div>
                  <div className="w-20 text-right">
                    <div className="text-sm font-semibold text-slate-800 tabular-nums">{c.count}</div>
                    {c.on_approval > 0 && <div className="text-[11px] text-amber-700">{c.on_approval} на согл.</div>}
                  </div>
                  <ArrowRight size={14} className="text-slate-300 transition group-hover:text-navy-800" />
                </button>
              )
            })}
          </div>
        </Card>

        <Card
          title="Ждут моего решения"
          className="lg:col-span-2"
          action={
            data.pending_for_me > 0 && (
              <button onClick={onPending} className="text-xs font-medium text-brand-600 hover:text-brand-700">
                Все ({data.pending_for_me})
              </button>
            )
          }
        >
          {data.pending.length === 0 ? (
            <Empty text="Очередь пуста: все документы этого подразделения согласованы" />
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.pending.map((d) => (
                <li key={d.id}>
                  <button onClick={() => onOpen(d.id)} className="w-full px-5 py-3 text-left transition hover:bg-slate-50">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[11px] text-slate-500">{d.reg_number}</span>
                      <StatusBadge status={d.status} label={d.status_name} overdue={d.overdue} />
                    </div>
                    <div className="mt-1 line-clamp-1 text-sm font-medium text-slate-800">{d.title}</div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      {d.person_name ?? d.category_name}
                      {d.due_date && ` · до ${fmtDate(d.due_date)}`}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card title="Последние действия" className="lg:col-span-3">
          {data.recent.length === 0 ? (
            <Empty text="Действий пока нет" />
          ) : (
            <ol className="relative px-5 py-3">
              {data.recent.map((a) => (
                <li key={a.id} className="relative flex gap-3 pb-3 last:pb-0">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-navy-800 ring-4 ring-navy-900/5" />
                  <button onClick={() => onOpen(a.document_id)} className="min-w-0 flex-1 text-left">
                    <div className="text-sm text-slate-800">
                      <span className="font-medium">{a.action_name}</span>
                      <span className="text-slate-500"> · {a.role_name}</span>
                    </div>
                    <div className="truncate text-xs text-slate-500">
                      <span className="font-mono">{a.reg_number}</span> {a.title}
                      {a.details && a.action !== 'registered' && ` — ${a.details}`}
                    </div>
                  </button>
                  <span className="shrink-0 text-[11px] text-slate-400">{fmtDate(a.at, true)}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Истекает срок хранения" className="lg:col-span-2">
          {data.expiring.length === 0 ? (
            <Empty text="В ближайший год сроки хранения не истекают" />
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.expiring.map((d) => (
                <li key={d.id}>
                  <button onClick={() => onOpen(d.id)} className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-slate-50">
                    <Hourglass size={15} className="shrink-0 text-amber-500" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-slate-800">{d.title}</div>
                      <div className="font-mono text-[11px] text-slate-500">{d.reg_number}</div>
                    </div>
                    <span className="shrink-0 text-xs text-slate-600">{fmtDate(d.retention_until)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="border-t border-slate-100 px-5 py-3 text-[11px] text-slate-500">
            По истечении срока документ рассматривает экспертная комиссия: уничтожение или постоянное хранение.
          </p>
        </Card>
      </div>
    </div>
  )
}
