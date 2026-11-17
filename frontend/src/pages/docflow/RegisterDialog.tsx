import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, FilePlus2, Loader2, Upload, X } from 'lucide-react'
import { edo, type Meta, type Person } from '../../edo'

export default function RegisterDialog({
  role,
  meta,
  onClose,
  onCreated,
}: {
  role: string
  meta: Meta
  onClose: () => void
  onCreated: (id: number) => void
}) {
  const types = meta.doc_types.filter((t) => meta.creatable_types.includes(t.code))
  const [typeCode, setTypeCode] = useState(types[0]?.code ?? '')
  const [title, setTitle] = useState('')
  const [personId, setPersonId] = useState('')
  const [due, setDue] = useState('')
  const [notes, setNotes] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [persons, setPersons] = useState<Person[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const type = types.find((t) => t.code === typeCode)
  const category = meta.categories.find((c) => c.code === type?.category)

  useEffect(() => {
    edo.persons(role).then(setPersons).catch(() => setPersons([]))
  }, [role])

  const grouped = useMemo(() => {
    const out: Record<string, typeof types> = {}
    types.forEach((t) => (out[t.category] ??= []).push(t))
    return out
  }, [types])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const form = new FormData()
    form.append('type_code', typeCode)
    form.append('title', title)
    if (personId) form.append('person_id', personId)
    if (due) form.append('due_date', due)
    if (notes) form.append('notes', notes)
    if (file) form.append('file', file)
    try {
      const doc = await edo.register(role, form)
      onCreated(doc.id)
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/40 p-4 backdrop-blur-[2px]">
      <form onSubmit={submit} className="w-full max-w-lg animate-fade-in rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center gap-3 border-b border-slate-100 px-6 py-4">
          <FilePlus2 size={18} className="text-navy-800" />
          <h2 className="flex-1 font-semibold text-slate-900">Регистрация документа</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-4 px-6 py-5">
          <Label text="Тип документа">
            <select value={typeCode} onChange={(e) => setTypeCode(e.target.value)} className={input}>
              {Object.entries(grouped).map(([cat, list]) => (
                <optgroup key={cat} label={meta.categories.find((c) => c.code === cat)?.name}>
                  {list.map((t) => (
                    <option key={t.code} value={t.code}>{t.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </Label>

          {type && (
            <div className="rounded-xl bg-slate-50 px-4 py-3 text-xs text-slate-600">
              <div>
                Рег. номер: <span className="font-mono">{category?.prefix}-{new Date().getFullYear()}/NNNNN</span> ·
                хранение {type.retention_years} лет
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1">
                Маршрут:
                {type.route_names.length === 0 ? (
                  <span className="text-slate-500">без согласования</span>
                ) : (
                  type.route_names.map((r, i) => (
                    <span key={i} className="inline-flex items-center gap-1">
                      {i > 0 && <ArrowRight size={11} className="text-slate-400" />}
                      <span className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">{r}</span>
                    </span>
                  ))
                )}
              </div>
            </div>
          )}

          <Label text="Название">
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={type?.name} className={input} maxLength={300} />
          </Label>
          <Label text="Кому относится (необязательно)">
            <select value={personId} onChange={(e) => setPersonId(e.target.value)} className={input}>
              <option value="">— документ подразделения —</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name} · {p.kind_name}
                </option>
              ))}
            </select>
          </Label>
          <div className="grid grid-cols-2 gap-3">
            <Label text="Срок согласования">
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className={input}
                     disabled={!type?.route.length} />
            </Label>
            <Label text={`Скан (до ${meta.max_file_mb} МБ)`}>
              <label className={`${input} flex cursor-pointer items-center gap-2 text-slate-500`}>
                <Upload size={14} />
                <span className="truncate">{file?.name ?? 'PDF, DOCX, JPG…'}</span>
                <input type="file" className="hidden" accept=".pdf,.docx,.doc,.xlsx,.jpg,.jpeg,.png"
                       onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            </Label>
          </div>
          <Label text="Примечание">
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={`${input} resize-none`} />
          </Label>
          {error && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Отмена
          </button>
          <button disabled={busy || !typeCode}
                  className="inline-flex items-center gap-2 rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-800 disabled:opacity-60">
            {busy && <Loader2 size={14} className="animate-spin" />} Зарегистрировать
          </button>
        </div>
      </form>
    </div>
  )
}

const input = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400 disabled:bg-slate-50'

function Label({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{text}</span>
      {children}
    </label>
  )
}
