import { useEffect, useMemo, useState } from 'react'
import {
  Accessibility,
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Camera,
  Car,
  Clock,
  Info,
  Loader2,
  Navigation,
  Pause,
  Play,
  Radio,
  Zap,
} from 'lucide-react'
import clsx from 'clsx'
import { parking, STALL_TYPE_NAMES, type Basemap, type Layout, type ParkingState, type Recommendation, type StallType } from '../parking'
import TwinMap, { fmtDur } from './parking/TwinMap'
import OccupancyChart from './parking/OccupancyChart'
import SatelliteTwin from './parking/SatelliteTwin'

const SPEEDS = [1, 10, 30, 120, 600]

export default function ParkingPage() {
  const [layout, setLayout] = useState<Layout | null>(null)
  const [state, setState] = useState<ParkingState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [route, setRoute] = useState<Recommendation | null>(null)
  const [need, setNeed] = useState<StallType>('regular')
  // вид из адреса: #parking/esri, #parking/google
  const [view, setView] = useState<string>(() => window.location.hash.split('/')[1] || 'scheme')
  const [basemaps, setBasemaps] = useState<Basemap[]>([])
  const [googleConfigured, setGoogleConfigured] = useState(false)

  useEffect(() => {
    parking.basemaps().then((b) => {
      setBasemaps(b.basemaps)
      setGoogleConfigured(b.google_configured)
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    parking.layout().then(setLayout).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    let alive = true
    const load = () => parking.state().then((s) => alive && setState(s)).catch((e) => alive && setError(e.message))
    load()
    const t = setInterval(load, 1000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  // рекомендованное место заняли — сбрасываем маршрут
  useEffect(() => {
    if (route && state?.stalls.find((s) => s.id === route.stall)?.occupied) setRoute(null)
  }, [state, route])

  const control = (body: Parameters<typeof parking.control>[0]) => parking.control(body).then(setState).catch((e) => setError(e.message))
  const findSpot = () =>
    parking
      .recommend(need)
      .then((r) => {
        setRoute(r)
        setSelected(r.stall)
      })
      .catch((e) => setError(e.message))

  const meta = useMemo(() => Object.fromEntries((layout?.stalls ?? []).map((s) => [s.id, s])), [layout])
  const sel = selected && state ? state.stalls.find((s) => s.id === selected) : null

  if (!layout || !state) {
    return (
      <div className="flex flex-1 items-center justify-center">
        {error ? <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : <Loader2 className="animate-spin text-slate-400" />}
      </div>
    )
  }

  const clock = new Date(state.clock)
  const t = state.totals

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1500px] px-4 py-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold tracking-wider text-brand-600 uppercase">Цифровой двойник</div>
            <h1 className="mt-1 font-display text-2xl font-bold text-navy-900">Умная парковка КБТУ</h1>
            <p className="mt-1 text-sm text-slate-500">ул. Казыбек би, за главным корпусом (Толе би, 59) · {t.total} мест в трёх зонах</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={clsx('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
              state.mode === 'live' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800')}>
              <Radio size={13} className={state.mode === 'live' ? 'animate-pulse' : ''} />
              {state.mode === 'live' ? 'Живые данные датчиков' : 'Симуляция датчиков'}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm">
              <Clock size={13} />
              {clock.toLocaleString('ru', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_360px]">
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex rounded-lg bg-white p-1 shadow-sm">
                {[{ id: 'scheme', name: 'Схема' }, ...basemaps].map((b) => (
                  <button key={b.id} onClick={() => setView(b.id)}
                          className={clsx('rounded-md px-3 py-1.5 text-xs font-medium transition',
                            view === b.id ? 'bg-navy-900 text-white' : 'text-slate-600 hover:text-slate-900')}>
                    {b.name}
                  </button>
                ))}
              </div>
              {!googleConfigured && view !== 'scheme' && (
                <span className="text-[11px] text-slate-500">
                  Google-спутник включится после добавления GOOGLE_MAPS_API_KEY в .env
                </span>
              )}
            </div>
            <div className="h-[560px]">
              {view === 'scheme' || !basemaps.find((b) => b.id === view) ? (
                <TwinMap layout={layout} state={state} selected={selected} onSelect={(id) => {
                  setSelected(id)
                  if (id !== route?.stall) setRoute(null)
                }} route={route} />
              ) : (
                <SatelliteTwin layout={layout} state={state} selected={selected} route={route}
                               basemap={basemaps.find((b) => b.id === view)!}
                               onSelect={(id) => {
                                 setSelected(id)
                                 if (id !== route?.stall) setRoute(null)
                               }} />
              )}
            </div>
            <div className="flex flex-wrap gap-x-5 gap-y-2 rounded-xl bg-white px-4 py-2.5 text-xs text-slate-600 shadow-sm">
              <Legend swatch={<span className="h-3 w-5 rounded-sm border border-emerald-600 bg-emerald-100" />} text="свободно" />
              <Legend swatch={<span className="flex h-3 w-5 items-center justify-center rounded-sm border border-slate-400 bg-slate-200"><span className="h-1.5 w-3.5 rounded-sm bg-slate-700" /></span>} text="занято" />
              <Legend swatch={<span className="h-3 w-5 rounded-sm border border-blue-600 bg-emerald-100 text-center text-[8px] leading-3 text-blue-600">♿</span>} text="для людей с инвалидностью" />
              <Legend swatch={<span className="h-3 w-5 rounded-sm border border-amber-600 bg-emerald-100 text-center text-[8px] leading-3 text-amber-600">⚡</span>} text="зарядка" />
              <Legend swatch={<span className="h-3 w-5 rounded-sm border border-violet-600" style={{ background: 'repeating-linear-gradient(45deg,#ede9fe 0 2px,#7c3aed55 2px 3px)' }} />} text="сотрудники" />
              <Legend swatch={<span className="h-3 w-5 rounded-sm border-2 border-rose-600" />} text="нарушение" />
              <Legend swatch={<span className="flex h-3 w-3 items-center justify-center rounded-full bg-slate-900"><span className="h-1 w-1 rounded-full bg-sky-400" /></span>} text="камера въезда" />
              <Legend swatch={<span className="h-2.5 w-2.5 rounded-full bg-green-500" />} text="вход в здание" />
            </div>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-800">Загрузка парковки за сутки</h3>
                <span className="text-xs text-slate-500">сценарий: {state.scenarios[state.scenario]}</span>
              </div>
              <OccupancyChart state={state} />
            </section>
          </div>

          <aside className="space-y-4">
            <section className="rounded-2xl bg-navy-900 p-5 text-white shadow-lg">
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-xs text-white/60">Свободно сейчас</div>
                  <div className="font-display text-4xl font-bold tabular-nums">{t.free}</div>
                </div>
                <div className="text-right text-sm text-white/80">
                  из {t.total}
                  <div className="text-xs text-white/60">занято {Math.round(t.rate * 100)}%</div>
                </div>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/15">
                <div className={clsx('h-full rounded-full transition-all', t.rate > 0.9 ? 'bg-rose-400' : t.rate > 0.75 ? 'bg-amber-300' : 'bg-emerald-400')}
                     style={{ width: `${t.rate * 100}%` }} />
              </div>
              {t.violations > 0 && (
                <div className="mt-3 flex items-center gap-1.5 text-xs text-rose-200">
                  <AlertTriangle size={13} /> Нарушений: {t.violations}
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
              {state.zones.map((z) => {
                const zm = layout.zones.find((x) => x.id === z.id)!
                const rate = 1 - z.free / z.total
                return (
                  <div key={z.id} className="flex items-center gap-3 border-b border-slate-100 px-5 py-3 last:border-0">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy-900 text-sm font-bold text-white">{z.id}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex justify-between text-sm">
                        <span className="truncate font-medium text-slate-800">{z.name}</span>
                        <span className="font-semibold text-slate-800 tabular-nums">{z.free}<span className="font-normal text-slate-400">/{z.total}</span></span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-navy-800 transition-all" style={{ width: `${rate * 100}%` }} />
                      </div>
                      <div className="mt-1 flex gap-3 text-[11px] text-slate-500">
                        <span>{zm.camera ? 'камера на въезде' : 'датчики в каждом месте'}</span>
                        {!!z.free_by_type.disabled && <span className="text-blue-700">♿ {z.free_by_type.disabled}</span>}
                        {!!z.free_by_type.ev && <span className="text-amber-700">⚡ {z.free_by_type.ev}</span>}
                      </div>
                    </div>
                  </div>
                )
              })}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Navigation size={15} /> Найти место</h3>
              <div className="mt-3 grid grid-cols-4 gap-1 rounded-lg bg-slate-100 p-1">
                {([['regular', Car, 'Любое'], ['disabled', Accessibility, ''], ['ev', Zap, 'Заряд'], ['staff', Info, 'Сотр.']] as const).map(([k, I, label]) => (
                  <button key={k} onClick={() => setNeed(k)} title={STALL_TYPE_NAMES[k]}
                          className={clsx('flex items-center justify-center gap-1 rounded-md py-1.5 text-xs font-medium',
                            need === k ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-600')}>
                    <I size={13} /> {label}
                  </button>
                ))}
              </div>
              <button onClick={findSpot} className="mt-3 w-full rounded-xl bg-navy-900 py-2.5 text-sm font-semibold text-white hover:bg-navy-800">
                Ближайшее ко входу в КБТУ
              </button>
              {route && (
                <div className="mt-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
                  Место <b>{route.stall}</b> (зона {route.zone}) · {route.walk_m} м пешком до входа.
                  {route.drive.length > 1 ? ' Маршрут проезда показан на карте.' : ' Уличное место на Казыбек би.'}
                </div>
              )}
            </section>

            {sel && meta[sel.id] && (
              <section className="rounded-2xl border border-amber-200 bg-amber-50/50 p-5 text-sm shadow-sm">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-slate-800">Место {sel.id}</h3>
                  <button onClick={() => setSelected(null)} className="text-xs text-slate-500 hover:text-slate-800">закрыть</button>
                </div>
                <dl className="mt-2 grid grid-cols-[7rem_1fr] gap-y-1 text-slate-600">
                  <dt>Тип</dt><dd className="text-slate-800">{STALL_TYPE_NAMES[meta[sel.id].type]}</dd>
                  <dt>Статус</dt><dd className="text-slate-800">{sel.occupied ? 'занято' : 'свободно'}</dd>
                  {sel.occupied && <><dt>Номер</dt><dd className="font-mono text-slate-800">{sel.plate}</dd></>}
                  {sel.occupied && <><dt>Стоит</dt><dd className="text-slate-800">{fmtDur(sel.minutes)}</dd></>}
                  <dt>Датчик</dt><dd className="font-mono text-slate-800">S-{sel.id}</dd>
                </dl>
                {sel.violation && <p className="mt-2 rounded-lg bg-rose-100 px-3 py-2 text-xs text-rose-800">{sel.violation}</p>}
              </section>
            )}

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-800">Управление двойником</h3>
              <div className="mt-3 flex items-center gap-2">
                <button onClick={() => control({ paused: !state.paused })}
                        className="flex h-9 w-9 items-center justify-center rounded-lg bg-navy-900 text-white hover:bg-navy-800"
                        title={state.paused ? 'Продолжить' : 'Пауза'}>
                  {state.paused ? <Play size={15} /> : <Pause size={15} />}
                </button>
                <div className="flex flex-1 rounded-lg bg-slate-100 p-1">
                  {SPEEDS.map((s) => (
                    <button key={s} onClick={() => control({ speed: s })}
                            className={clsx('flex-1 rounded-md py-1 text-xs font-medium',
                              state.speed === s ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-600')}>
                      ×{s}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <select value={state.scenario} onChange={(e) => control({ scenario: e.target.value })}
                        className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs">
                  {Object.entries(state.scenarios).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <select value="" onChange={(e) => e.target.value && control({ jump_to: e.target.value })}
                        className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs">
                  <option value="">Перейти ко времени…</option>
                  {['07:30', '08:45', '10:00', '13:00', '16:00', '19:00', '22:00'].map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </div>
              {state.mode === 'live' && (
                <button onClick={() => control({ mode: 'simulation' })} className="mt-2 text-xs text-brand-600 hover:underline">
                  Вернуться к симуляции
                </button>
              )}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
              <h3 className="flex items-center gap-2 border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-800">
                <Camera size={15} /> События датчиков и камер
              </h3>
              <ul className="scrollbar-thin max-h-72 divide-y divide-slate-100 overflow-y-auto">
                {state.events.slice(0, 20).map((e, i) => (
                  <li key={`${e.at}-${i}`} className="flex gap-2.5 px-5 py-2 text-xs">
                    {e.kind === 'arrival' ? <ArrowDownToLine size={13} className="mt-0.5 shrink-0 text-navy-800" />
                      : e.kind === 'departure' ? <ArrowUpFromLine size={13} className="mt-0.5 shrink-0 text-emerald-600" />
                        : <AlertTriangle size={13} className="mt-0.5 shrink-0 text-rose-600" />}
                    <button onClick={() => setSelected(e.stall)} className="min-w-0 flex-1 text-left text-slate-700 hover:text-navy-900">{e.text}</button>
                    <span className="shrink-0 text-slate-400">{e.at.slice(11, 16)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </aside>
        </div>

        <p className="mt-6 flex items-start gap-2 text-xs text-slate-500">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            Контуры здания, парковок, проездов и ограждений — {layout.meta.source}. Места разложены по контурам
            автоматически; число и нумерацию нужно сверить с разметкой на месте. Пока датчики не подключены, их
            показания симулируются по профилю спроса учебного дня; номера машин показываются частично.
          </span>
        </p>
      </div>
    </div>
  )
}

function Legend({ swatch, text }: { swatch: React.ReactNode; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {swatch}
      {text}
    </span>
  )
}
