import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useAuth, type User } from '../auth'

const FIELDS: { key: keyof User; label: string; placeholder?: string; half?: boolean }[] = [
  { key: 'full_name', label: 'ФИО полностью' },
  { key: 'program', label: 'Образовательная программа', placeholder: '6B06101 – Информационные системы' },
  { key: 'course', label: 'Курс', placeholder: '3', half: true },
  { key: 'study_group', label: 'Группа', placeholder: 'ИС-23-1', half: true },
  { key: 'phone', label: 'Сотовый номер', placeholder: '+7 701 000 00 00', half: true },
  { key: 'student_id', label: 'Student ID', placeholder: '23B030001', half: true },
  { key: 'faculty', label: 'Школа / факультет', placeholder: 'ШИТиИ' },
]

/** Данные студента, которые подставляются в шапку заявлений и другие формы. */
export default function ProfileForm({ onSaved, compact }: { onSaved?: () => void; compact?: boolean }) {
  const { user, saveProfile } = useAuth()
  const [form, setForm] = useState<Partial<User>>(() => ({ ...user }))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  if (!user) return null

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      await saveProfile(form)
      setMessage({ ok: true, text: 'Сохранено' })
      onSaved?.()
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className={compact ? 'grid gap-3 sm:grid-cols-2' : 'grid gap-3 sm:grid-cols-2'}>
        {FIELDS.map((f) => (
          <label key={f.key} className={f.half ? 'block' : 'block sm:col-span-2'}>
            <span className="mb-1 block text-xs font-medium text-slate-600">{f.label}</span>
            <input
              value={String(form[f.key] ?? '')}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              placeholder={f.placeholder}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-100"
            />
          </label>
        ))}
        <div className="sm:col-span-2 text-xs text-slate-500">
          Корпоративная почта: <span className="font-medium text-slate-700">{user.email}</span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-800 disabled:opacity-60">
          {busy && <Loader2 size={14} className="animate-spin" />} Сохранить профиль
        </button>
        {message && <span className={message.ok ? 'text-sm text-emerald-700' : 'text-sm text-rose-700'}>{message.text}</span>}
      </div>
    </form>
  )
}
