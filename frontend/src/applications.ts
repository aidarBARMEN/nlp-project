// API заявлений (/api/applications)
import { withToken } from './auth'

export interface AppType {
  id: 'registration' | 'drop' | 'recredit' | 'master_thesis'
  title: string
  description: string
  audience: 'bachelor' | 'master'
}

export interface TypesInfo {
  types: AppType[]
  semesters: Record<string, string>
  default_year: string
  master_programs: string[]
  statuses: Record<string, string>
}

export interface Block {
  text: string
  align: 'left' | 'right' | 'center' | 'justify'
  style: string
}

export interface Application {
  id: number
  type: AppType['id']
  type_title: string
  data: Record<string, unknown>
  student: { full_name: string; email: string; program: string; course: string; study_group: string }
  status: 'submitted' | 'approved' | 'rejected'
  status_name: string
  comment: string | null
  created_at: string
  decided_at: string | null
  decided_by: string | null
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/applications${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
  })
  if (!res.ok) {
    let detail = `Ошибка ${res.status}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      /* не JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const applications = {
  types: () => call<TypesInfo>('/types'),
  preview: (type: string, data: unknown) => call<{ blocks: Block[] }>('/preview', post({ type, data })),
  submit: (type: string, data: unknown) => call<Application>('', post({ type, data })),
  mine: () => call<Application[]>('/mine'),
  inbox: (status = '') => call<{ items: Application[]; counts: Record<string, number> }>(`/inbox?status=${status}`),
  decide: (id: number, decision: 'approved' | 'rejected', comment: string) =>
    call<Application>(`/${id}/decision`, post({ decision, comment })),
  fileUrl: (id: number) => withToken(`/api/applications/${id}/file`),
  /** Скачать черновик без отправки: POST с телом, поэтому через blob. */
  async downloadDraft(type: string, data: unknown) {
    const res = await fetch('/api/applications/docx', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, data }),
    })
    if (!res.ok) throw new Error((await res.json()).detail ?? 'Не удалось сформировать заявление')
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = 'Заявление.docx'
    a.click()
    URL.revokeObjectURL(url)
  },
}
