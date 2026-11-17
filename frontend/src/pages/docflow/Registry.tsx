import { useEffect, useState } from 'react'
import { Loader2, Paperclip, Search } from 'lucide-react'
import clsx from 'clsx'
import { edo, fmtDate, type DocCard, type Meta } from '../../edo'
import { AccessBadge, Card, CATEGORY_ICON, Empty, StatusBadge } from './ui'

export default function Registry({
  role,
  meta,
  refreshKey,
  category,
  onCategory,
  pendingOnly = false,
  onOpen,
}: {
  role: string
  meta: Meta
  refreshKey: number
  category: string
  onCategory: (code: string) => void
  pendingOnly?: boolean
  onOpen: (id: number) => void
}) {
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [docs, setDocs] = useState<DocCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const readable = meta.categories.filter((c) => c.my_access)

  useEffect(() => {
    const t = setTimeout(() => {
      setError(null)
      edo
        .documents(role, { category: category || undefined, status: status || undefined, q: q.trim() || undefined,
                           pending_for_me: pendingOnly || undefined })
        .then(setDocs)
        .catch((e) => setError(e.message))
    }, 200)
    return () => clearTimeout(t)
  }, [role, category, status, q, pendingOnly, refreshKey])

  return (
    <div className="space-y-4">
      {!pendingOnly && (
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          <Chip active={!category} onClick={() => onCategory('')}>
            Все разделы
          </Chip>
          {readable.map((c) => {
            const Icon = CATEGORY_ICON[c.code]
            return (
              <Chip key={c.code} active={category === c.code} onClick={() => onCategory(c.code)}>
                {Icon && <Icon size={13} />} {c.name}
              </Chip>
            )
          })}
        </div>
      )}

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
          <label className="flex min-w-60 flex-1 items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 focus-within:border-brand-400">
            <Search size={14} className="text-slate-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Рег. номер, название или ФИО"
              className="flex-1 bg-transparent text-sm outline-none"
            />
          </label>
          {!pendingOnly && (
            <select value={status} onChange={(e) => setStatus(e.target.value)}
                    className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm">
              <option value="">Любой статус</option>
              {Object.entries(meta.statuses).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          )}
          {docs && <span className="ml-auto text-xs text-slate-500">{docs.length} документов</span>}
        </div>

        {error ? (
          <div className="px-5 py-4 text-sm text-rose-700">{error}</div>
        ) : !docs ? (
          <Loader2 className="mx-auto my-10 animate-spin text-slate-400" />
        ) : docs.length === 0 ? (
          <Empty text={pendingOnly ? 'Нет документов, ожидающих решения этого подразделения' : 'Ничего не найдено'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-[11px] text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Рег. номер</th>
                  <th className="px-3 py-2.5 font-medium">Документ</th>
                  <th className="px-3 py-2.5 font-medium">Кому относится</th>
                  <th className="px-3 py-2.5 font-medium">Статус</th>
                  <th className="px-3 py-2.5 font-medium whitespace-nowrap">Срок / изменён</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs.map((d) => {
                  const Icon = CATEGORY_ICON[d.category]
                  return (
                    <tr key={d.id} onClick={() => onOpen(d.id)} className="cursor-pointer align-top hover:bg-slate-50/70">
                      <td className="px-4 py-3 font-mono text-xs whitespace-nowrap text-slate-600">{d.reg_number}</td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1.5 font-medium text-slate-800">
                          {d.title}
                          {d.has_file && d.access === 'full' && <Paperclip size={12} className="text-slate-400" />}
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                          {Icon && <Icon size={12} />} {d.type_name} <AccessBadge access={d.access} />
                        </div>
                      </td>
                      <td className="px-3 py-3 text-slate-600">{d.person_name ?? <span className="text-slate-400">—</span>}</td>
                      <td className="px-3 py-3">
                        <StatusBadge status={d.status} label={d.status_name} overdue={d.overdue} />
                      </td>
                      <td className="px-3 py-3 text-xs whitespace-nowrap text-slate-500">
                        {d.status === 'on_approval' && d.due_date ? (
                          <span className={clsx(d.overdue && 'font-semibold text-rose-700')}>до {fmtDate(d.due_date)}</span>
                        ) : (
                          fmtDate(d.updated_at)
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium whitespace-nowrap transition',
        active ? 'border-navy-900 bg-navy-900 text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
      )}
    >
      {children}
    </button>
  )
}
