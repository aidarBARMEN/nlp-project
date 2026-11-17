import { useEffect, useMemo, useState } from 'react'
import { Armchair, BookOpen, Clock, DoorOpen, Info, Loader2, MapPin, Moon, Radio, Users, X } from 'lucide-react'
import clsx from 'clsx'
import {
  campus,
  DAYS_SHORT,
  fmtMinutes,
  roomTitle,
  type CampusMap,
  type FreeRoom,
  type Lesson,
  type RoomDetails,
  type Snapshot,
  type When,
} from '../campus'
import FloorMap, { COLORS } from './campus/FloorMap'

const MIN_OPTIONS = [15, 30, 60, 120]
const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5))
const toHHMM = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`

export default function CampusPage() {
  const [map, setMap] = useState<CampusMap | null>(null)
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [when, setWhen] = useState<When>(null)
  const [floor, setFloor] = useState(1)
  // выбранная аудитория из адреса: #campus/312
  const [selected, setSelected] = useState<string | null>(() => decodeURIComponent(window.location.hash.split('/')[1] ?? '') || null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const [minMinutes, setMinMinutes] = useState(30)
  const [onlyFloor, setOnlyFloor] = useState(false)
  const [free, setFree] = useState<{ count: number; rooms: FreeRoom[] } | null>(null)
  const [details, setDetails] = useState<RoomDetails | null>(null)

  useEffect(() => {
    campus.map().then(setMap).catch((e) => setError(e.message))
  }, [])

  // состояние аудиторий; в режиме «сейчас» — обновляем раз в минуту
  useEffect(() => {
    let alive = true
    const load = () => campus.status(when).then((s) => alive && setSnap(s)).catch((e) => alive && setError(e.message))
    load()
    const t = when ? undefined : setInterval(load, 60_000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [when])

  const stamp = snap ? `${snap.at.day}-${snap.at.time}` : ''

  useEffect(() => {
    if (!stamp) return
    campus.free(when, minMinutes, onlyFloor ? floor : undefined).then(setFree).catch(() => setFree(null))
  }, [stamp, when, minMinutes, onlyFloor, floor])

  useEffect(() => {
    window.history.replaceState(null, '', selected ? `#campus/${encodeURIComponent(selected)}` : '#campus')
    if (!selected || !stamp) {
      setDetails(null)
      return
    }
    campus.room(selected, when).then(setDetails).catch(() => setDetails(null))
  }, [selected, stamp, when])

  const roomsById = useMemo(() => Object.fromEntries((map?.floors ?? []).flatMap((f) => f.rooms.map((r) => [r.id, r]))), [map])

  // выбранная по ссылке аудитория — открываем её этаж
  useEffect(() => {
    if (selected && roomsById[selected]) setFloor(roomsById[selected].floor)
  }, [roomsById]) // только при загрузке карты

  const pick = (id: string) => {
    const r = roomsById[id]
    if (r) setFloor(r.floor)
    setSelected(id)
  }

  if (!map || !snap) {
    return (
      <div className="flex flex-1 items-center justify-center">
        {error ? <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : <Loader2 className="animate-spin text-slate-400" />}
      </div>
    )
  }

  const minute = toMin(snap.at.time)
  const setMoment = (day: number, m: number) => setWhen({ day, time: toHHMM(m) })
  const t = snap.totals
  const floorStats = snap.floors.find((f) => f.floor === floor)!

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1500px] px-4 py-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold tracking-wider text-brand-600 uppercase">Карта корпуса</div>
            <h1 className="mt-1 font-display text-2xl font-bold text-navy-900">Свободные аудитории</h1>
            <p className="mt-1 text-sm text-slate-500">
              {map.meta.title} · 5 этажей · {Object.keys(roomsById).length} помещений
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={clsx('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
              snap.at.live ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800')}>
              <Radio size={13} className={snap.at.live ? 'animate-pulse' : ''} />
              {snap.at.live ? 'Сейчас' : 'Выбранное время'}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm">
              <Clock size={13} />
              {snap.at.day_name}, {snap.at.time}
            </span>
          </div>
        </div>

        {/* выбор момента времени */}
        <section className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <button onClick={() => setWhen(null)}
                  className={clsx('rounded-lg px-3 py-1.5 text-xs font-semibold transition',
                    snap.at.live ? 'bg-navy-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200')}>
            Сейчас
          </button>
          <div className="flex rounded-lg bg-slate-100 p-1">
            {DAYS_SHORT.map((d, i) => (
              <button key={d} onClick={() => setMoment(i, Math.min(Math.max(minute, 480), 1250))}
                      className={clsx('rounded-md px-2.5 py-1 text-xs font-medium',
                        snap.at.day === i ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-600 hover:text-slate-900')}>
                {d}
              </button>
            ))}
          </div>
          <label className="flex min-w-[220px] flex-1 items-center gap-3 text-xs text-slate-500">
            08:00
            <input type="range" min={480} max={1260} step={5} value={Math.min(Math.max(minute, 480), 1260)}
                   onChange={(e) => setMoment(snap.at.day, Number(e.target.value))}
                   className="flex-1 accent-navy-900" />
            21:00
          </label>
        </section>

        <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_380px]">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="scrollbar-thin flex max-w-full overflow-x-auto rounded-lg bg-white p-1 shadow-sm">
                {snap.floors.map((f) => (
                  <button key={f.floor} onClick={() => setFloor(f.floor)}
                          className={clsx('shrink-0 rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap transition',
                            floor === f.floor ? 'bg-navy-900 text-white' : 'text-slate-600 hover:text-slate-900')}>
                    {f.floor} этаж
                    {snap.open && (
                      <span className={clsx('ml-1.5 rounded px-1 tabular-nums', floor === f.floor ? 'bg-white/15' : 'bg-emerald-50 text-emerald-700')}>
                        {f.free}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              <span className="text-xs text-slate-500">
                {snap.open ? <>На этаже свободно <b className="text-slate-800">{floorStats.free}</b> из {floorStats.total}</> : 'Корпус закрыт'}
              </span>
            </div>

            <FloorMap map={map} floor={floor} statuses={snap.rooms} selected={selected} highlight={highlight} onSelect={setSelected} />

            <div className="flex flex-wrap gap-x-5 gap-y-2 rounded-xl bg-white px-4 py-2.5 text-xs text-slate-600 shadow-sm">
              <Legend color={COLORS.free} text="свободна" />
              <Legend color={COLORS.soon} text="скоро занятие (< 20 мин)" />
              <Legend color={COLORS.busy} text="идёт занятие" />
              <Legend color={COLORS.open} text="коворкинг — открыт всем" />
              <Legend color={COLORS.service} text="служебное" />
              <span className="ml-auto text-slate-400">колесо — масштаб, перетаскивание — сдвиг</span>
            </div>
          </div>

          <aside className="space-y-4">
            <section className="rounded-2xl bg-navy-900 p-5 text-white shadow-lg">
              {snap.open ? (
                <>
                  <div className="flex items-end justify-between">
                    <div>
                      <div className="text-xs text-white/60">Свободных аудиторий</div>
                      <div className="font-display text-4xl font-bold tabular-nums">{t.free}</div>
                    </div>
                    <div className="text-right text-sm text-white/80">
                      из {t.total}
                      <div className="text-xs text-white/60">идут занятия в {Math.round(t.load * 100)}%</div>
                    </div>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/15">
                    <div className={clsx('h-full rounded-full transition-all', t.load > 0.85 ? 'bg-rose-400' : t.load > 0.6 ? 'bg-amber-300' : 'bg-emerald-400')}
                         style={{ width: `${t.load * 100}%` }} />
                  </div>
                </>
              ) : (
                <div className="flex items-center gap-3">
                  <Moon size={28} className="text-white/70" />
                  <div>
                    <div className="font-semibold">Корпус закрыт</div>
                    <div className="text-xs text-white/60">Открыт пн–сб, {snap.hours.open}–{snap.hours.close}</div>
                  </div>
                </div>
              )}
            </section>

            {details && (
              <RoomCard details={details} live={snap.at.live} now={minute} onClose={() => setSelected(null)} />
            )}

            <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="border-b border-slate-100 px-5 py-3">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Armchair size={15} /> Где посидеть</h3>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  <div className="flex rounded-lg bg-slate-100 p-0.5">
                    {MIN_OPTIONS.map((m) => (
                      <button key={m} onClick={() => setMinMinutes(m)}
                              className={clsx('rounded-md px-2 py-1 text-[11px] font-medium',
                                minMinutes === m ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-600')}>
                        ≥ {fmtMinutes(m)}
                      </button>
                    ))}
                  </div>
                  <label className="flex items-center gap-1.5 text-[11px] text-slate-600">
                    <input type="checkbox" checked={onlyFloor} onChange={(e) => setOnlyFloor(e.target.checked)} className="accent-navy-900" />
                    только {floor} этаж
                  </label>
                </div>
              </div>
              {!snap.open ? (
                <p className="px-5 py-4 text-sm text-slate-500">Корпус закрыт — выберите другое время.</p>
              ) : !free ? (
                <div className="flex justify-center py-6"><Loader2 size={18} className="animate-spin text-slate-300" /></div>
              ) : free.rooms.length === 0 ? (
                <p className="px-5 py-4 text-sm text-slate-500">Нет аудиторий, свободных хотя бы {fmtMinutes(minMinutes)}. Попробуйте коворкинг или меньший интервал.</p>
              ) : (
                <ul className="scrollbar-thin max-h-[420px] divide-y divide-slate-100 overflow-y-auto">
                  {free.rooms.map((r) => (
                    <li key={r.id}>
                      <button onClick={() => pick(r.id)} onMouseEnter={() => setHighlight(r.id)} onMouseLeave={() => setHighlight(null)}
                              className={clsx('flex w-full items-center gap-3 px-5 py-2.5 text-left transition hover:bg-slate-50',
                                selected === r.id && 'bg-navy-50')}>
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold text-white"
                              style={{ background: r.kind === 'coworking' ? COLORS.open : COLORS.free }}>
                          {r.kind === 'coworking' ? <Users size={16} /> : r.number}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-slate-800">{roomTitle(r)}</span>
                          <span className="block text-[11px] text-slate-500">
                            {r.floor} этаж{r.seats ? ` · ≈${r.seats} мест` : ''}
                            {r.next && ` · дальше: ${r.next.subject}`}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          <span className="block text-xs font-semibold text-emerald-700">до {r.free_until}</span>
                          <span className="block text-[11px] text-slate-400">{fmtMinutes(r.free_minutes!)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {free && free.count > free.rooms.length && (
                <div className="border-t border-slate-100 px-5 py-2 text-[11px] text-slate-400">
                  показаны {free.rooms.length} из {free.count}
                </div>
              )}
            </section>
          </aside>
        </div>

        <p className="mt-6 flex items-start gap-2 text-xs text-slate-500">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            Планы этажей оцифрованы из «{map.meta.source}»: контуры аудиторий выделены автоматически по стенам на
            плане. Расписание — демонстрационное (пары по 50 минут, с 08:00 до 21:00, в будни днём заняты почти все
            аудитории); вместимость оценена по площади на плане. Для реальной работы подключите выгрузку расписания
            университета.
          </span>
        </p>
      </div>
    </div>
  )
}

function Legend({ color, text }: { color: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-3 w-5 rounded-sm border" style={{ background: `${color}66`, borderColor: color }} />
      {text}
    </span>
  )
}

/** Склеивает сдвоенные пары и показывает окна между ними */
function timeline(lessons: Lesson[]): { start: string; end: string; lesson: Lesson | null }[] {
  const out: { start: string; end: string; lesson: Lesson | null }[] = []
  let cursor = '08:00'
  for (const ls of lessons) {
    const prev = out[out.length - 1]
    if (prev?.lesson && prev.lesson.subject === ls.subject && prev.lesson.group === ls.group && toMin(ls.start) - toMin(prev.end) <= 10) {
      prev.end = ls.end
      cursor = ls.end
      continue
    }
    if (toMin(ls.start) - toMin(cursor) > 10) out.push({ start: cursor, end: ls.start, lesson: null })
    out.push({ start: ls.start, end: ls.end, lesson: ls })
    cursor = ls.end
  }
  if (toMin('21:00') - toMin(cursor) > 10) out.push({ start: cursor, end: '21:00', lesson: null })
  return out
}

function RoomCard({ details, live, now, onClose }: { details: RoomDetails; live: boolean; now: number; onClose: () => void }) {
  const st = details.status
  const rows = timeline(details.lessons)
  const withLessons = details.kind === 'classroom' || details.kind === 'hall'
  return (
    <section className="animate-fade-in rounded-2xl border border-slate-200 bg-white p-5 text-sm shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 font-display text-lg font-bold text-navy-900">
            <DoorOpen size={18} /> {roomTitle(details)}
          </h3>
          <div className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
            <MapPin size={12} /> {details.floor} этаж{details.seats ? ` · ≈${details.seats} мест` : ''}
          </div>
        </div>
        <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="Закрыть"><X size={16} /></button>
      </div>

      <div className="mt-3">
        {st.state === 'busy' && st.lesson && (
          <div className="rounded-xl bg-rose-50 px-4 py-3 text-rose-900">
            <div className="text-xs font-semibold tracking-wide text-rose-600 uppercase">Идёт занятие · до {st.busy_until}</div>
            <div className="mt-1 font-semibold">{st.lesson.subject}</div>
            <div className="text-xs text-rose-800/80">{st.lesson.type} · {st.lesson.group} · {st.lesson.teacher}</div>
            <div className="mt-1.5 text-xs">Освободится через {fmtMinutes(st.busy_minutes!)}</div>
          </div>
        )}
        {(st.state === 'free' || st.state === 'open') && (
          <div className={clsx('rounded-xl px-4 py-3', st.state === 'open' ? 'bg-sky-50 text-sky-900' : (st.free_minutes ?? 0) < 20 ? 'bg-amber-50 text-amber-900' : 'bg-emerald-50 text-emerald-900')}>
            <div className="text-xs font-semibold tracking-wide uppercase opacity-80">
              {st.state === 'open' ? 'Открыто для всех' : (st.free_minutes ?? 0) < 20 ? 'Скоро занятие' : 'Свободна — можно посидеть'}
            </div>
            <div className="mt-1 text-base font-semibold">
              до {st.free_until} <span className="font-normal opacity-70">· {fmtMinutes(st.free_minutes!)}</span>
            </div>
            {st.next && <div className="mt-1 text-xs opacity-80">Дальше: {st.next.subject} ({st.next.type}, {st.next.group})</div>}
          </div>
        )}
        {st.state === 'service' && <div className="rounded-xl bg-slate-100 px-4 py-3 text-slate-700">Служебное помещение — занятий здесь нет.</div>}
        {st.state === 'closed' && <div className="rounded-xl bg-slate-100 px-4 py-3 text-slate-700">Корпус закрыт.</div>}
      </div>

      {withLessons && (
        <div className="mt-4">
          <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-slate-500">
            <BookOpen size={13} /> {live ? 'Сегодня' : details.day_name}
          </div>
          {details.lessons.length === 0 ? (
            <p className="text-xs text-slate-500">{details.day === 6 ? 'Воскресенье — корпус закрыт.' : 'Занятий нет весь день.'}</p>
          ) : (
            <ol className="space-y-1">
              {rows.map((r) => {
                const current = toMin(r.start) <= now && now < toMin(r.end)
                return (
                  <li key={r.start} className={clsx('flex gap-3 rounded-lg px-2.5 py-1.5 text-xs',
                    current && 'ring-2 ring-navy-900/70', r.lesson ? 'bg-slate-50' : 'bg-emerald-50/60')}>
                    <span className="w-[76px] shrink-0 text-slate-500 tabular-nums">{r.start}–{r.end}</span>
                    {r.lesson ? (
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-slate-800">{r.lesson.subject}</span>
                        <span className="block truncate text-slate-500">{r.lesson.type} · {r.lesson.group}</span>
                      </span>
                    ) : (
                      <span className="font-medium text-emerald-700">свободно</span>
                    )}
                  </li>
                )
              })}
            </ol>
          )}
        </div>
      )}
    </section>
  )
}
