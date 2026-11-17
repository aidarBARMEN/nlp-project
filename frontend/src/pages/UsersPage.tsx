import { useEffect, useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import { adminApi, useAuth, type Role, type User } from '../auth'
import ProfileForm from '../components/ProfileForm'

const ROLES: { id: Role; name: string; hint: string }[] = [
  { id: 'student', name: 'Студент', hint: 'ассистент, заявления, диплом, практика' },
  { id: 'teacher', name: 'Преподаватель', hint: '+ посещаемость' },
  { id: 'dean', name: 'Деканат', hint: '+ входящие заявления, дипломы, документооборот, база знаний' },
  { id: 'admin', name: 'Администратор', hint: 'всё, включая пользователей и исследования' },
]

export function ProfilePage() {
  const { user } = useAuth()
  if (!user) return null
  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-2xl px-4 py-8">
        <h1 className="font-display text-2xl text-navy-900">Профиль</h1>
        <p className="mt-1 text-sm text-slate-500">
          Эти данные подставляются в заявления и формы. Роль: <b className="text-slate-700">{user.role_name}</b>.
        </p>
        <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <ProfileForm />
        </section>
      </div>
    </div>
  )
}

export default function UsersPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[] | null>(null)
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    adminApi.users().then(setUsers).catch((e) => setError(e.message))
  }, [])

  const change = async (u: User, role: Role) => {
    setError(null)
    try {
      const updated = await adminApi.setRole(u.id, role)
      setUsers((list) => list?.map((x) => (x.id === u.id ? updated : x)) ?? null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const shown = users?.filter((u) => `${u.full_name} ${u.email}`.toLowerCase().includes(q.toLowerCase()))

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="font-display text-2xl text-navy-900">Пользователи и роли</h1>
        <p className="mt-1 text-sm text-slate-500">Новые пользователи регистрируются студентами. Здесь назначаются роли преподавателей, деканата и администраторов.</p>
        <div className="mt-4 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
          {ROLES.map((r) => <div key={r.id} className="rounded-lg bg-white px-3 py-2 ring-1 ring-slate-200"><b className="text-slate-800">{r.name}</b> — {r.hint}</div>)}
        </div>
        {error && <div className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        <section className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-4 py-3">
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5">
              <Search size={14} className="text-slate-400" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Имя или email" className="flex-1 text-sm outline-none" />
            </label>
          </div>
          {!shown ? <Loader2 className="mx-auto my-10 animate-spin text-slate-400" /> : (
            <table className="w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {shown.map((u) => (
                  <tr key={u.id}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{u.full_name || '—'}</div>
                      <div className="text-xs text-slate-500">{u.email}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">{[u.program, u.course && `${u.course} курс`].filter(Boolean).join(' · ')}</td>
                    <td className="px-4 py-3 text-right">
                      <select value={u.role} disabled={u.id === me?.id} onChange={(e) => change(u, e.target.value as Role)}
                              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm disabled:bg-slate-50">
                        {ROLES.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
