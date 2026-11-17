// API посещаемости (/api/attendance)
import { withToken } from './auth'

export type Mark = 'present' | 'absent' | 'uncertain' | null

export interface SheetStudent {
  index: number
  name: string
  student_id: string
  status: Mark
  ink: number | null
  manual: boolean
}

export interface Sheet {
  id: number
  course: string
  group: string
  date: string
  students: SheetStudent[]
  counts: { present: number; absent: number; uncertain: number; unknown: number }
  pages: number
  scanned_pages: number[]
  created_at: string
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/attendance${path}`, init)
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

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const attendance = {
  sheets: () => call<Sheet[]>('/sheets'),
  sheet: (id: number) => call<Sheet>(`/sheets/${id}`),
  create: (body: { course: string; group: string; date: string; students: { name: string; student_id: string }[] }) =>
    call<Sheet>('/sheets', json('POST', body)),
  roster: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return call<{ students: { name: string; student_id: string }[] }>('/roster', { method: 'POST', body: form })
  },
  scan: (photo: File, sheetId?: number) => {
    const form = new FormData()
    form.append('photo', photo)
    return call<{ sheet: Sheet; page: number; qr: boolean; overlay: string }>(
      `/scan${sheetId ? `?sheet_id=${sheetId}` : ''}`, { method: 'POST', body: form })
  },
  setMarks: (id: number, marks: Record<string, 'present' | 'absent'>) => call<Sheet>(`/sheets/${id}/marks`, json('PUT', { marks })),
  pdfUrl: (id: number) => withToken(`/api/attendance/sheets/${id}/pdf`),
  exportUrl: (id: number) => withToken(`/api/attendance/sheets/${id}/export`),
}

/** «Иванов Иван; 23B030001» или «Иванов Иван<TAB>23B030001» — по строке на студента. */
export function parseRoster(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, id = ''] = line.split(/\t|;|,(?=\s*\d)/).map((s) => s.trim())
      return { name: name.replace(/^\d+[.)]\s*/, ''), student_id: id }
    })
    .filter((s) => s.name.length >= 2)
}
