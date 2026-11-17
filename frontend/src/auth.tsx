import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

export type Role = 'student' | 'teacher' | 'dean' | 'admin'

export interface User {
  id: number
  email: string
  role: Role
  role_name: string
  full_name: string
  student_id: string
  faculty: string
  program: string
  course: string
  study_group: string
  phone: string
}

const TOKEN_KEY = 'kbtu:token'

function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

let token = readToken()

export const getToken = () => token

function setToken(value: string) {
  token = value
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage недоступен — сессия живёт до перезагрузки */
  }
}

// Токен добавляется ко всем запросам к своему API: модули страниц используют обычный fetch,
// и так им не нужно знать о сессии. Явно переданный Authorization (модуль дипломов) не трогаем.
const nativeFetch = window.fetch.bind(window)
window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  if (token && url.startsWith('/api/')) {
    const headers = new Headers(init.headers)
    if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
    init = { ...init, headers }
  }
  return nativeFetch(input, init)
}

/** Ссылка на файл, который открывает браузер: заголовок в ней не передать, поэтому токен в адресе. */
export const withToken = (url: string) => `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/auth${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
  })
  if (!res.ok) {
    let detail = `Ошибка ${res.status}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg ?? detail
    } catch {
      /* не JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

interface AuthState {
  user: User | null
  ready: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, full_name: string) => Promise<void>
  logout: () => Promise<void>
  saveProfile: (profile: Partial<User>) => Promise<User>
  can: (...roles: Role[]) => boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(!token)

  useEffect(() => {
    if (!token) return
    call<User>('/me')
      .then(setUser)
      .catch(() => setToken(''))
      .finally(() => setReady(true))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const r = await call<{ token: string; user: User }>('/login', { method: 'POST', body: JSON.stringify({ email, password }) })
    setToken(r.token)
    setUser(r.user)
  }, [])

  const register = useCallback(async (email: string, password: string, full_name: string) => {
    const r = await call<{ token: string; user: User }>('/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name }),
    })
    setToken(r.token)
    setUser(r.user)
  }, [])

  const logout = useCallback(async () => {
    await call('/logout', { method: 'POST' }).catch(() => undefined)
    setToken('')
    setUser(null)
  }, [])

  const saveProfile = useCallback(async (profile: Partial<User>) => {
    const fields = ['full_name', 'student_id', 'faculty', 'program', 'course', 'study_group', 'phone'] as const
    const body = Object.fromEntries(fields.map((f) => [f, profile[f] ?? '']))
    const updated = await call<User>('/me', { method: 'PUT', body: JSON.stringify(body) })
    setUser(updated)
    return updated
  }, [])

  const can = useCallback((...roles: Role[]) => !!user && roles.includes(user.role), [user])

  return <Ctx.Provider value={{ user, ready, login, register, logout, saveProfile, can }}>{children}</Ctx.Provider>
}

export function useAuth() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth вне AuthProvider')
  return ctx
}

export const adminApi = {
  users: () => call<User[]>('/users'),
  setRole: (id: number, role: Role) => call<User>(`/users/${id}/role`, { method: 'PUT', body: JSON.stringify({ role }) }),
}
