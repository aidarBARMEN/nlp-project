import { useState } from 'react'
import { Loader2, X } from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '../auth'

export default function AuthDialog({ onClose, reason }: { onClose: () => void; reason?: string }) {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(email.trim(), password)
      else await register(email.trim(), password, name.trim())
      onClose()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4 backdrop-blur-[2px]">
      <form onSubmit={submit} className="w-full max-w-sm animate-fade-in rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between">
          <img src="/kbtu-logo.png" alt="KBTU" className="h-8 w-auto" />
          <button type="button" onClick={onClose} className="-mt-1 -mr-1 rounded-lg p-1 text-slate-400 hover:bg-slate-100" aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
        <h2 className="mt-5 text-lg font-semibold text-navy-900">{mode === 'login' ? 'Вход' : 'Регистрация'}</h2>
        <p className="mt-1 text-sm text-slate-500">
          {reason ?? (mode === 'login' ? 'Войдите корпоративной почтой КБТУ.' : 'Аккаунт создаётся с ролью студента. Роль преподавателя или деканата назначает администратор.')}
        </p>

        <div className="mt-5 space-y-3">
          {mode === 'register' && (
            <Field label="ФИО">
              <input value={name} onChange={(e) => setName(e.target.value)} required minLength={3} autoComplete="name" className={input} />
            </Field>
          )}
          <Field label="Email">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email"
                   placeholder="name@kbtu.kz" className={input} />
          </Field>
          <Field label="Пароль">
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8}
                   autoComplete={mode === 'login' ? 'current-password' : 'new-password'} className={input} />
            {mode === 'register' && <span className="mt-1 block text-[11px] text-slate-400">Не меньше 8 символов</span>}
          </Field>
        </div>

        {error && <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}

        <button disabled={busy}
                className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-navy-900 py-2.5 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60">
          {busy && <Loader2 size={15} className="animate-spin" />}
          {mode === 'login' ? 'Войти' : 'Создать аккаунт'}
        </button>
        <p className="mt-4 text-center text-sm text-slate-500">
          {mode === 'login' ? 'Нет аккаунта?' : 'Уже есть аккаунт?'}{' '}
          <button type="button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}
                  className={clsx('font-medium text-navy-800 hover:underline')}>
            {mode === 'login' ? 'Зарегистрироваться' : 'Войти'}
          </button>
        </p>
      </form>
    </div>
  )
}

const input = 'w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-100'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  )
}
