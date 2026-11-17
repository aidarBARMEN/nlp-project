// API цифрового двойника парковки (/api/parking)

export type Pt = [number, number]
export type StallType = 'regular' | 'disabled' | 'ev' | 'staff'

export interface Layout {
  meta: { title: string; source: string; note: string; generated_at: string; origin: { lat: number; lon: number } }
  building: { name: string; outer: Pt[]; inner: Pt[][] }
  zones: { id: string; name: string; polygon: Pt[]; entry: Pt | null; kind: 'street' | 'lot'; camera: boolean }[]
  aisles: { zone: string; line: Pt[] }[]
  stalls: { id: string; zone: string; polygon: Pt[]; center: Pt; angle: number; type: StallType }[]
  roads: { name: string | null; kind: string; line: Pt[]; lanes: number }[]
  footways: Pt[][]
  buildings: { polygon: Pt[]; name: string | null; levels: string | null }[]
  fences: Pt[][]
  points: { kind: string; at: Pt }[]
}

export interface Basemap {
  id: string
  name: string
  url: string
  attribution: string
  max_zoom: number
  viewport_url?: string
}

export interface StallState {
  id: string
  occupied: boolean
  plate: string | null
  since: string | null
  minutes: number | null
  violation: string | null
}

export interface ParkingEvent {
  at: string
  kind: 'arrival' | 'departure' | 'violation'
  stall: string
  text: string
}

export interface ParkingState {
  clock: string
  mode: 'simulation' | 'live'
  scenario: string
  scenarios: Record<string, string>
  speed: number
  paused: boolean
  totals: { total: number; occupied: number; free: number; rate: number; violations: number }
  zones: { id: string; name: string; total: number; free: number; free_by_type: Partial<Record<StallType, number>> }[]
  stalls: StallState[]
  events: ParkingEvent[]
  history: { at: string; occupied: number; rate: number }[]
  forecast: { hour: number; rate: number }[]
}

export interface Recommendation {
  stall: string
  zone: string
  type: StallType
  walk_m: number
  drive: Pt[]
  walk: Pt[]
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/parking${path}`, init)
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* не JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const parking = {
  layout: () => call<Layout>('/layout'),
  basemaps: () => call<{ basemaps: Basemap[]; google_configured: boolean }>('/basemaps'),
  state: () => call<ParkingState>('/state'),
  control: (body: { speed?: number; paused?: boolean; scenario?: string; jump_to?: string; mode?: string }) =>
    call<ParkingState>('/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  recommend: (need: StallType = 'regular') => call<Recommendation>(`/recommend?need=${need}`),
}

export const STALL_TYPE_NAMES: Record<StallType, string> = {
  regular: 'Обычное',
  disabled: 'Для людей с инвалидностью',
  ev: 'С зарядкой для электромобиля',
  staff: 'Для сотрудников',
}
