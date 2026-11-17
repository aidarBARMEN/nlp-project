import { useCallback, useEffect, useState } from 'react'
import { Check, Download, Loader2, X } from 'lucide-react'
import clsx from 'clsx'
import { applications, type Application } from '../applications'
import { StatusPill } from './ApplicationsPage'

const TABS = [
  { id: 'submitted', label: 'На рассмотрении' },
  { id: 'approved', label: 'Одобренные' },
  { id: 'rejected', label: 'Отклонённые' },
  { id: '', label: 'Все' },
]

export default function ApplicationsInboxPage() {
  const [tab, setTab] = useState('submitted')
  const [data, setData] = useState<{ items: Application[]; counts: Record<string, number> } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [comment, setComment] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | null>(null)

  const load = useCallback(() => {
    applications.inbox(tab).then(setData).catch((e) => setError(e.message))
  }, [tab])
  useEffect(load, [load])

  const decide = async (a: Application, decision: 'approved' | 'rejected') => {
    setBusy(a.id)
    setError(null)
    try {
      await applications.decide(a.id, decision, comment[a.id] ?? '')
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="text-xs font-semibold tracking-wider text-navy-700 uppercase">Деканат</div>
        <h1 className="mt-1 font-display text-2xl text-navy-900">Входящие заявления</h1>
        <p className="mt-1 text-sm text-slate-500">Заявления студентов, сформированные по образцам. При отказе укажите причину — студент увидит её в кабинете.</p>

        <div className="mt-5 flex gap-1 overflow-x-auto border-b border-slate-200">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
                    className={clsx('-mb-px inline-flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap',
                      tab === t.id ? 'border-navy-900 text-navy-900' : 'border-transparent text-slate-500 hover:text-slate-800')}>
              {t.label}
              {t.id && data && <span className="rounded-full bg-slate-100 px-1.5 text-[11px] text-slate-600">{data.counts[t.id] ?? 0}</span>}
            </button>
          ))}
        </div>

        {error && <div className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {!data ? (
          <Loader2 className="mx-auto mt-12 animate-spin text-slate-400" />
        ) : data.items.length === 0 ? (
          <p className="mt-10 text-center text-sm text-slate-500">Заявлений нет</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {data.items.map((a) => (
              <li key={a.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-slate-900">{a.type_title} <span className="font-normal text-slate-400">№ {a.id}</span></div>
                    <div className="mt-0.5 text-sm text-slate-600">
                      {a.student.full_name} · {a.student.course} курс · {a.student.program}
                    </div>
                    <div className="text-xs text-slate-400">{a.student.email} · подано {new Date(a.created_at).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'short' })}</div>
                  </div>
                  <StatusPill status={a.status} label={a.status_name} />
                  <a href={applications.fileUrl(a.id)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
                    <Download size={13} /> Word
                  </a>
                </div>
                <Summary a={a} />
                {a.status === 'submitted' ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <input value={comment[a.id] ?? ''} onChange={(e) => setComment({ ...comment, [a.id]: e.target.value })}
                           placeholder="Комментарий (обязателен при отказе)"
                           className="min-w-56 flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-sm outline-none focus:border-navy-700" />
                    <button disabled={busy === a.id} onClick={() => decide(a, 'approved')}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60">
                      <Check size={14} /> Одобрить
                    </button>
                    <button disabled={busy === a.id} onClick={() => decide(a, 'rejected')}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60">
                      <X size={14} /> Отклонить
                    </button>
                  </div>
                ) : (
                  a.comment && <p className="mt-3 text-sm text-slate-600">Решение ({a.decided_by}): {a.comment}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/** Суть заявления одной-двумя строками, чтобы не открывать Word ради каждого. */
function Summary({ a }: { a: Application }) {
  const d = a.data as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  const list = (items: { name: string }[] = []) => items.map((x) => x.name).join('; ')
  const text =
    a.type === 'registration' ? list(d.disciplines)
      : a.type === 'drop' ? `Снять: ${d.discipline}${d.replacement ? ` → ${d.replacement.name}` : ''}`
        : a.type === 'recredit' ? `Перезачёт: ${d.recredited} → ${list(d.disciplines)}`
          : `Тема: ${d.topic_ru} · руководитель ${d.supervisor}`
  return <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{text}</p>
}
