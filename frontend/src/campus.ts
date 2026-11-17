// API карты корпуса и занятости аудиторий (/api/campus)

export type Pt = [number, number]
export type RoomKind = 'classroom' | 'coworking' | 'hall' | 'service' | 'office'
export type RoomState = 'busy' | 'free' | 'open' | 'service' | 'closed'

export interface Room {
  id: string
  name: string
  number: string | null
  floor: number
  kind: RoomKind
  seats: number | null
  label: Pt
  polygon: Pt[]
}

export interface CampusMap {
  meta: {
    title: string
    source: string
    view: [number, number, number, number]
    generated_at: string
    streets: { top: string; bottom: string; left: string; right: string }
  }
  floors: { floor: number; image: string; size: [number, number]; rooms: Room[] }[]
}

export interface Lesson {
  start: string
  end: string
  subject: string
  type: string
  group: string
  teacher: string
}

export interface Status {
  state: RoomState
  lesson?: Lesson
  busy_until?: string
  busy_minutes?: number
  free_until?: string
  free_minutes?: number
  next?: Lesson | null
}

export interface Moment {
  day: number
  day_name: string
  time: string
  live: boolean
}

export interface Snapshot {
  at: Moment
  open: boolean
  hours: { open: string; close: string }
  totals: { total: number; busy: number; free: number; load: number }
  floors: { floor: number; total: number; free: number; busy: number }[]
  rooms: Record<string, Status>
}

export interface FreeRoom extends Status {
  id: string
  name: string
  number: string | null
  floor: number
  kind: RoomKind
  seats: number | null
}

export interface RoomDetails extends Omit<Room, 'polygon' | 'label'> {
  day: number
  day_name: string
  status: Status
  lessons: Lesson[]
}

/** null — «сейчас» (время берёт сервер, Алматы) */
export type When = { day: number; time: string } | null

async function call<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v))
  const res = await fetch(`/api/campus${path}${q.size ? `?${q}` : ''}`)
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* не JSON */
    }
    throw new Error(typeof detail === 'string' ? detail : res.statusText)
  }
  return res.json()
}

const at = (w: When) => (w ? { day: w.day, time: w.time } : {})

export const campus = {
  map: () => call<CampusMap>('/map'),
  status: (w: When) => call<Snapshot>('/status', at(w)),
  free: (w: When, minMinutes: number, floor?: number) =>
    call<{ at: Moment; open: boolean; count: number; rooms: FreeRoom[] }>('/free', {
      ...at(w),
      min_minutes: minMinutes,
      floor,
      limit: 40,
    }),
  room: (id: string, w: When) => call<RoomDetails>(`/rooms/${encodeURIComponent(id)}`, at(w)),
}

export const DAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export function fmtMinutes(m: number): string {
  if (m < 60) return `${m} мин`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h} ч ${r} мин` : `${h} ч`
}

export function roomTitle(r: { number: string | null; name: string }): string {
  return r.number ? `Ауд. ${r.number}` : r.name
}
