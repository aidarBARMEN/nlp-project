import { useEffect, useMemo, useRef, useState } from 'react'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import type { CampusMap, Room, Status } from '../../campus'
import { fmtMinutes, roomTitle } from '../../campus'

const M = 110 // поля под названия улиц (снизу — колоннада у входа)

export const COLORS = {
  free: '#10b981',
  soon: '#f59e0b',
  busy: '#f43f5e',
  open: '#0ea5e9',
  service: '#94a3b8',
  closed: '#cbd5e1',
}

export function colorFor(st: Status | undefined): string {
  if (!st) return COLORS.closed
  if (st.state === 'free') return (st.free_minutes ?? 0) < 20 ? COLORS.soon : COLORS.free
  return COLORS[st.state]
}

function hint(room: Room, st: Status | undefined): string {
  const name = roomTitle(room)
  if (!st || st.state === 'closed') return `${name} — корпус закрыт`
  if (st.state === 'service') return `${name} — служебное помещение`
  if (st.state === 'busy') return `${name} — идёт занятие: ${st.lesson!.subject}, до ${st.busy_until}`
  if (st.state === 'open') return `${name} — открыт, можно посидеть`
  return `${name} — свободна до ${st.free_until} (${fmtMinutes(st.free_minutes!)})`
}

interface Props {
  map: CampusMap
  floor: number
  statuses: Record<string, Status> | undefined
  selected: string | null
  highlight: string | null
  onSelect: (id: string | null) => void
}

export default function FloorMap({ map, floor, statuses, selected, highlight, onSelect }: Props) {
  const [vx, vy, vw, vh] = map.meta.view
  const full = useMemo(() => [vx - M, vy - M, vw + 2 * M, vh + 2 * M] as const, [vx, vy, vw, vh])
  const [box, setBox] = useState<readonly [number, number, number, number]>(full)
  const [hover, setHover] = useState<string | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; box: typeof box; moved: boolean } | null>(null)
  const dragged = useRef(false)
  const data = map.floors.find((f) => f.floor === floor)!

  useEffect(() => setBox(full), [full])

  const zoom = (k: number, cx?: number, cy?: number) =>
    setBox(([x, y, w, h]) => {
      const nw = Math.min(full[2], Math.max(full[2] / 6, w * k))
      const nh = (nw / w) * h
      const px = cx ?? x + w / 2
      const py = cy ?? y + h / 2
      return [px - ((px - x) / w) * nw, py - ((py - y) / h) * nh, nw, nh]
    })

  // колесо мыши — зум к курсору (нативный слушатель, чтобы не прокручивать страницу)
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = svg.getBoundingClientRect()
      setBox(([x, y, w, h]) => {
        const k = e.deltaY > 0 ? 1.15 : 1 / 1.15
        const nw = Math.min(full[2], Math.max(full[2] / 6, w * k))
        const nh = (nw / w) * h
        const px = x + ((e.clientX - r.left) / r.width) * w
        const py = y + ((e.clientY - r.top) / r.height) * h
        return [px - ((px - x) / w) * nw, py - ((py - y) / h) * nh, nw, nh]
      })
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [full])

  const onDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, box, moved: false }
  }
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current
    const svg = svgRef.current
    if (!d || !svg) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    if (!d.moved && Math.hypot(dx, dy) < 5) return
    if (!d.moved) {
      d.moved = true
      svg.setPointerCapture(e.pointerId)
    }
    const r = svg.getBoundingClientRect()
    const [x, y, w, h] = d.box
    setBox([x - (dx / r.width) * w, y - (dy / r.height) * h, w, h])
  }
  const onUp = (e: React.PointerEvent) => {
    const d = drag.current
    drag.current = null
    dragged.current = !!d?.moved
    if (d?.moved) svgRef.current?.releasePointerCapture(e.pointerId)
  }
  const clickRoom = (id: string) => {
    // клик после перетаскивания карты — не выбор аудитории
    if (dragged.current) return
    onSelect(id === selected ? null : id)
  }

  const hoverRoom = hover ? data.rooms.find((r) => r.id === hover) : null
  const s = map.meta.streets
  const [fx, fy, fw, fh] = full

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <svg
        ref={svgRef}
        viewBox={box.join(' ')}
        className="block aspect-[1.03] w-full cursor-grab touch-none select-none active:cursor-grabbing"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          {/* подложка без исходных подписей улиц: оставляем здание с лестницами и колоннадой */}
          <clipPath id="campus-building">
            <rect x={vx - 75} y={vy - 20} width={vw + 150} height={vh + 95} />
          </clipPath>
        </defs>
        <rect x={fx} y={fy} width={fw} height={fh} fill="#ffffff" />
        <image href={data.image} x={0} y={0} width={data.size[0]} height={data.size[1]} opacity={0.9}
               clipPath="url(#campus-building)" style={{ filter: 'grayscale(1) contrast(1.15)' }} />
        <g fontSize={30} fontWeight={600} fill="#64748b" textAnchor="middle" style={{ letterSpacing: 1 }}>
          <text x={vx + vw / 2} y={fy + 45}>{s.top}</text>
          <text x={vx + vw / 2} y={fy + fh - 22}>{s.bottom}</text>
          <text transform={`translate(${fx + 45} ${vy + vh / 2}) rotate(-90)`}>{s.left}</text>
          <text transform={`translate(${fx + fw - 45} ${vy + vh / 2}) rotate(90)`}>{s.right}</text>
        </g>
        {data.rooms.map((r) => {
          const st = statuses?.[r.id]
          const active = r.id === selected
          const lit = r.id === highlight || r.id === hover
          return (
            <polygon
              key={r.id}
              points={r.polygon.map((p) => p.join(',')).join(' ')}
              fill={colorFor(st)}
              fillOpacity={active ? 0.75 : lit ? 0.6 : 0.42}
              stroke={active ? '#002f6c' : lit ? '#0b3f85' : colorFor(st)}
              strokeWidth={active ? 6 : lit ? 4 : 1.5}
              style={{ mixBlendMode: 'multiply', cursor: 'pointer', transition: 'fill .3s, fill-opacity .15s' }}
              onPointerEnter={() => setHover(r.id)}
              onPointerLeave={() => setHover((h) => (h === r.id ? null : h))}
              onClick={() => clickRoom(r.id)}
            >
              <title>{hint(r, st)}</title>
            </polygon>
          )
        })}
        {selected && data.rooms.some((r) => r.id === selected) && (() => {
          const r = data.rooms.find((x) => x.id === selected)!
          return <circle cx={r.label[0]} cy={r.label[1] - 30} r={9} fill="#002f6c" stroke="white" strokeWidth={3} pointerEvents="none" />
        })()}
      </svg>

      {hoverRoom && (
        <div className="pointer-events-none absolute top-3 left-3 max-w-[70%] rounded-lg bg-navy-950/90 px-3 py-1.5 text-xs text-white shadow-lg">
          {hint(hoverRoom, statuses?.[hoverRoom.id])}
        </div>
      )}

      <div className="absolute right-3 bottom-3 flex flex-col overflow-hidden rounded-lg bg-white shadow-md ring-1 ring-slate-200">
        <button onClick={() => zoom(1 / 1.4)} className="p-2 text-slate-600 hover:bg-slate-50" title="Приблизить"><Plus size={16} /></button>
        <button onClick={() => zoom(1.4)} className="border-t border-slate-100 p-2 text-slate-600 hover:bg-slate-50" title="Отдалить"><Minus size={16} /></button>
        <button onClick={() => setBox(full)} className="border-t border-slate-100 p-2 text-slate-600 hover:bg-slate-50" title="Весь этаж"><RotateCcw size={15} /></button>
      </div>
    </div>
  )
}
