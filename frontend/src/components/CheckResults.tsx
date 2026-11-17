import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, Info, XCircle, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import type { CheckStatus, DocumentCheck, Finding } from '../practice'

export const STATUS_UI: Record<CheckStatus, { icon: LucideIcon; cls: string; label: string }> = {
  fail: { icon: XCircle, cls: 'text-rose-600', label: 'Ошибка' },
  warn: { icon: AlertTriangle, cls: 'text-amber-500', label: 'Замечание' },
  info: { icon: Info, cls: 'text-sky-600', label: 'Проверяется вручную' },
  pass: { icon: CheckCircle2, cls: 'text-emerald-600', label: 'Соответствует' },
}

export function FindingRow({ f }: { f: Finding }) {
  const ui = STATUS_UI[f.status]
  const Icon = ui.icon
  return (
    <li className="flex gap-3 px-5 py-3">
      <Icon size={17} className={clsx('mt-0.5 shrink-0', ui.cls)} aria-label={ui.label} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-800">{f.title}</div>
        <div className="mt-0.5 text-sm text-slate-600">{f.message}</div>
        {f.where.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {f.where.map((w, i) => (
              <li key={i} className="rounded-md bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-600">
                {w}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  )
}

/** Результат проверки одного документа: сначала ошибки и замечания, выполненные требования свёрнуты. */
export function DocumentCheckCard({ doc, compact = false }: { doc: DocumentCheck; compact?: boolean }) {
  const [showPassed, setShowPassed] = useState(false)
  const issues = doc.findings.filter((f) => f.status !== 'pass')
  const order: CheckStatus[] = ['fail', 'warn', 'info']
  issues.sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status))
  const passed = doc.findings.filter((f) => f.status === 'pass')

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div
        className={clsx(
          'flex flex-wrap items-center gap-3 px-5 py-4',
          doc.ready ? 'bg-emerald-50' : 'bg-rose-50',
          compact && 'py-3',
        )}
      >
        {doc.ready ? (
          <CheckCircle2 size={22} className="text-emerald-600" />
        ) : (
          <XCircle size={22} className="text-rose-600" />
        )}
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-slate-900">
            {doc.title}: {doc.ready ? 'можно сдавать' : 'нужно исправить'}
          </div>
          <div className="truncate text-xs text-slate-500">{doc.file_name}</div>
        </div>
        <div className="flex gap-3 text-xs">
          <span className="text-rose-700">ошибок {doc.counts.fail}</span>
          <span className="text-amber-700">замечаний {doc.counts.warn}</span>
          <span className="text-emerald-700">выполнено {doc.counts.pass}</span>
        </div>
      </div>
      {issues.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {issues.map((f) => (
            <FindingRow key={f.id} f={f} />
          ))}
        </ul>
      )}
      {passed.length > 0 && (
        <div className="border-t border-slate-100">
          <button
            onClick={() => setShowPassed((v) => !v)}
            className="flex w-full items-center gap-2 px-5 py-2.5 text-left text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            <ChevronDown size={14} className={clsx('transition', showPassed && 'rotate-180')} />
            Выполненные требования ({passed.length})
          </button>
          {showPassed && (
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {passed.map((f) => (
                <FindingRow key={f.id} f={f} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
