import { useEffect, useState } from 'react'
import { Archive, Check, CircleDashed, Download, FileText, Loader2, ShieldCheck, X } from 'lucide-react'
import clsx from 'clsx'
import { edo, fmtDate, type DocDetail } from '../../edo'
import { AccessBadge, ConfidentialityBadge, StatusBadge } from './ui'
import { DocumentCheckCard } from '../../components/CheckResults'

export default function DocumentDrawer({
  role,
  id,
  onClose,
  onChanged,
}: {
  role: string
  id: number
  onClose: () => void
  onChanged: () => void
}) {
  const [doc, setDoc] = useState<DocDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setDoc(null)
    setError(null)
    edo.document(role, id).then(setDoc).catch((e) => setError(e.message))
  }, [role, id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const act = async (fn: () => Promise<DocDetail>) => {
    setBusy(true)
    setError(null)
    try {
      setDoc(await fn())
      setComment('')
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button className="flex-1 bg-navy-950/40 backdrop-blur-[2px]" onClick={onClose} aria-label="Закрыть" />
      <aside className="scrollbar-thin flex h-full w-full max-w-xl animate-fade-in flex-col overflow-y-auto bg-white shadow-2xl">
        <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-slate-100 bg-white/95 px-6 py-4 backdrop-blur">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-navy-900 text-white">
            <FileText size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-mono text-xs text-slate-500">{doc?.reg_number ?? '…'}</div>
            <h2 className="text-base leading-snug font-semibold text-slate-900">{doc?.title ?? 'Загрузка'}</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>

        {error && <div className="mx-6 mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {!doc && !error && <Loader2 className="mx-auto mt-16 animate-spin text-slate-400" />}

        {doc && (
          <div className="space-y-6 px-6 py-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={doc.status} label={doc.status_name} overdue={doc.overdue} />
              <ConfidentialityBadge level={doc.confidentiality} />
              <AccessBadge access={doc.access} />
              {doc.is_demo === 1 && <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">демо</span>}
            </div>

            <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-sm">
              <Row label="Тип">{doc.type_name}</Row>
              <Row label="Раздел">{doc.category_name}</Row>
              <Row label="Кому относится">{doc.person_name ?? '—'}</Row>
              <Row label="Зарегистрирован">{fmtDate(doc.created_at, true)}</Row>
              {doc.due_date && <Row label="Срок согласования">{fmtDate(doc.due_date)}</Row>}
              <Row label="Хранить до">{fmtDate(doc.retention_until)}</Row>
              {doc.notes && <Row label="Примечание">{doc.notes}</Row>}
            </dl>

            <section>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">Файл</h3>
              {doc.access !== 'full' ? (
                <p className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  Содержимое доступно только подразделению-владельцу. Вашей роли видна карточка документа.
                </p>
              ) : doc.has_file ? (
                <a
                  href={edo.fileUrl(role, doc.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 transition hover:border-brand-300 hover:bg-brand-50/40"
                >
                  <Download size={16} className="text-brand-600" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-slate-800">{doc.file_name}</div>
                    <div className="truncate font-mono text-[10px] text-slate-400" title="Контрольная сумма SHA-256">
                      SHA-256 {doc.file_sha256?.slice(0, 24)}…
                    </div>
                  </div>
                  {doc.file_size && <span className="text-xs text-slate-500">{(doc.file_size / 1024).toFixed(0)} КБ</span>}
                </a>
              ) : (
                <p className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500">Скан не прикреплён</p>
              )}
            </section>

            {doc.format_check && (
              <section>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                  Автопроверка оформления
                </h3>
                <DocumentCheckCard doc={doc.format_check} compact />
              </section>
            )}

            <section>
              <h3 className="mb-3 text-xs font-semibold tracking-wide text-slate-500 uppercase">Маршрут согласования</h3>
              {doc.route.length === 0 ? (
                <p className="text-sm text-slate-500">Регистрируется без согласования.</p>
              ) : (
                <ol className="space-y-0">
                  {doc.route.map((s, i) => (
                    <li key={s.id} className="relative flex gap-3 pb-4 last:pb-0">
                      {i < doc.route.length - 1 && (
                        <span className="absolute top-7 left-[13px] h-[calc(100%-1.5rem)] w-px bg-slate-200" />
                      )}
                      <StepIcon status={s.status} />
                      <div className="min-w-0 flex-1 pt-0.5">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <span className="text-sm font-medium text-slate-800">
                            {s.step}. {s.role_name}
                          </span>
                          <span className="text-[11px] text-slate-500">
                            {s.status === 'pending' ? 'ожидает' : s.status === 'skipped' ? 'не требуется' : fmtDate(s.decided_at, true)}
                          </span>
                        </div>
                        {s.comment && <p className="mt-1 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">{s.comment}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              )}

              {doc.can_decide && (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                  <div className="mb-2 text-sm font-medium text-slate-800">Решение вашего подразделения</div>
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    rows={2}
                    placeholder="Комментарий (обязателен при отклонении)"
                    className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400"
                  />
                  <div className="mt-2 flex gap-2">
                    <button
                      disabled={busy}
                      onClick={() => act(() => edo.decide(role, doc.id, 'approve', comment || undefined))}
                      className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
                    >
                      <Check size={15} /> Согласовать
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => act(() => edo.decide(role, doc.id, 'reject', comment))}
                      className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                    >
                      <X size={15} /> Отклонить
                    </button>
                  </div>
                </div>
              )}
              {doc.can_archive && (
                <button
                  disabled={busy}
                  onClick={() => act(() => edo.archive(role, doc.id))}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  <Archive size={15} /> Передать в архив
                </button>
              )}
            </section>

            <section>
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                <ShieldCheck size={13} /> Журнал действий
              </h3>
              <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 text-sm">
                {doc.audit.map((a) => (
                  <li key={a.id} className="flex items-start justify-between gap-3 px-4 py-2">
                    <div className="min-w-0">
                      <span className="text-slate-800">{a.action_name}</span>
                      <span className="text-slate-500"> · {a.role_name}</span>
                      {a.details && <div className="truncate text-xs text-slate-500">{a.details}</div>}
                    </div>
                    <span className="shrink-0 text-[11px] text-slate-400">{fmtDate(a.at, true)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </aside>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800">{children}</dd>
    </>
  )
}

function StepIcon({ status }: { status: string }) {
  const cls = {
    approved: 'bg-emerald-600 text-white',
    rejected: 'bg-rose-600 text-white',
    pending: 'bg-amber-100 text-amber-700 ring-2 ring-amber-300',
    skipped: 'bg-slate-100 text-slate-400',
  }[status]
  return (
    <span className={clsx('z-[1] flex h-7 w-7 shrink-0 items-center justify-center rounded-full', cls)}>
      {status === 'approved' ? <Check size={14} /> : status === 'rejected' ? <X size={14} /> : <CircleDashed size={14} />}
    </span>
  )
}
