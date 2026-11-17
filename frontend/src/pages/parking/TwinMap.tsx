import { useMemo, useRef, useState } from 'react'
import { Locate, Minus, Plus } from 'lucide-react'
import type { Layout, ParkingState, Pt, Recommendation, StallState } from '../../parking'
import { STALL_TYPE_NAMES } from '../../parking'

// координаты двойника — метры, y на север; в SVG y направлен вниз, поэтому отражаем
const p = ([x, y]: Pt) => `${x},${-y}`
const poly = (pts: Pt[]) => pts.map(p).join(' ')
const ROAD_WIDTH: Record<string, number> = { secondary: 16, tertiary: 14, residential: 12, service: 6 }

type Box = { x: number; y: number; w: number; h: number }

export default function TwinMap({
  layout,
  state,
  selected,
  onSelect,
  route,
}: {
  layout: Layout
  state: ParkingState | null
  selected: string | null
  onSelect: (id: string | null) => void
  route: Recommendation | null
}) {
  const home = useMemo<Box>(() => {
    const pts = [...layout.building.outer, ...layout.zones.flatMap((z) => z.polygon)]
    const xs = pts.map((q) => q[0])
    const ys = pts.map((q) => -q[1])
    const pad = 14
    return {
      x: Math.min(...xs) - pad,
      y: Math.min(...ys) - pad,
      w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
      h: Math.max(...ys) - Math.min(...ys) + 2 * pad,
    }
  }, [layout])
  const [box, setBox] = useState<Box>(home)
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null)
  const drag = useRef<{ x: number; y: number; box: Box } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const byId = useMemo(() => Object.fromEntries((state?.stalls ?? []).map((s) => [s.id, s])), [state])
  const stallMeta = useMemo(() => Object.fromEntries(layout.stalls.map((s) => [s.id, s])), [layout])

  const zoom = (factor: number, cx = box.x + box.w / 2, cy = box.y + box.h / 2) => {
    const w = Math.min(Math.max(box.w * factor, 40), home.w * 2)
    const h = (w / box.w) * box.h
    setBox({ x: cx - ((cx - box.x) / box.w) * w, y: cy - ((cy - box.y) / box.h) * h, w, h })
  }

  const toWorld = (e: React.MouseEvent | React.WheelEvent) => {
    const r = svgRef.current!.getBoundingClientRect()
    // preserveAspectRatio xMidYMid meet: учитываем поля по краям
    const scale = Math.min(r.width / box.w, r.height / box.h)
    const ox = (r.width - box.w * scale) / 2
    const oy = (r.height - box.h * scale) / 2
    return { x: box.x + (e.clientX - r.left - ox) / scale, y: box.y + (e.clientY - r.top - oy) / scale, scale }
  }

  const labelAt = (line: Pt[]) => {
    const i = Math.floor((line.length - 1) / 2)
    const a = line[i]
    const b = line[i + 1] ?? line[i]
    let ang = (Math.atan2(-(b[1] - a[1]), b[0] - a[0]) * 180) / Math.PI
    if (ang > 90) ang -= 180
    if (ang < -90) ang += 180
    return { x: (a[0] + b[0]) / 2, y: -(a[1] + b[1]) / 2, ang }
  }

  const hovered = hover ? byId[hover.id] : null
  const hoveredMeta = hover ? stallMeta[hover.id] : null

  return (
    <div className="relative h-full min-h-[420px] overflow-hidden rounded-2xl border border-slate-200 bg-[#eef1f5]">
      <svg
        ref={svgRef}
        viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
        className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
        onWheel={(e) => {
          const w = toWorld(e)
          zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, w.x, w.y)
        }}
        onMouseDown={(e) => (drag.current = { x: e.clientX, y: e.clientY, box })}
        onMouseMove={(e) => {
          if (!drag.current) return
          const { scale } = toWorld(e)
          const d = drag.current
          setBox({ ...d.box, x: d.box.x - (e.clientX - d.x) / scale, y: d.box.y - (e.clientY - d.y) / scale })
        }}
        onMouseUp={() => (drag.current = null)}
        onMouseLeave={() => {
          drag.current = null
          setHover(null)
        }}
        onClick={(e) => e.target === e.currentTarget && onSelect(null)}
      >
        <defs>
          <pattern id="staff-hatch" width="1.2" height="1.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="1.2" stroke="#7c3aed" strokeWidth="0.35" />
          </pattern>
          <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#002F6C" />
          </marker>
        </defs>

        {/* окружение */}
        {layout.buildings.map((b, i) => (
          <polygon key={`b${i}`} points={poly(b.polygon)} fill="#dde3ea" stroke="#cbd3dd" strokeWidth={0.3} />
        ))}
        {layout.footways.map((f, i) => (
          <polyline key={`f${i}`} points={poly(f)} fill="none" stroke="#ffffff" strokeWidth={1.6} strokeLinecap="round" />
        ))}
        {/* уличная зона — под проезжей частью: машины стоят вдоль бордюров по обе стороны улицы */}
        {layout.zones.filter((z) => z.kind === 'street').map((z) => (
          <polygon key={z.id} points={poly(z.polygon)} fill="#f8fafc" stroke="#94a3b8" strokeWidth={0.4} />
        ))}
        {layout.roads.map((r, i) => (
          <g key={`r${i}`}>
            <polyline points={poly(r.line)} fill="none" stroke="#c4ccd6"
                      strokeWidth={ROAD_WIDTH[r.kind] ?? 6}
                      strokeLinecap="round" strokeLinejoin="round" />
            {r.kind !== 'service' && (
              <polyline points={poly(r.line)} fill="none" stroke="#ffffff" strokeWidth={0.3} strokeDasharray="3 3" />
            )}
          </g>
        ))}

        {/* зоны парковки */}
        {layout.zones.filter((z) => z.kind !== 'street').map((z) => (
          <polygon key={z.id} points={poly(z.polygon)} fill="#f8fafc" stroke="#94a3b8" strokeWidth={0.4} />
        ))}
        {layout.aisles.map((a) => (
          <polyline key={a.zone} points={poly(a.line)} fill="none" stroke="#94a3b8" strokeWidth={0.5}
                    strokeDasharray="2 1.5" markerEnd="url(#arrow)" />
        ))}

        {/* здание КБТУ */}
        <path
          d={`M${poly(layout.building.outer)}Z ${layout.building.inner.map((h) => `M${poly(h)}Z`).join(' ')}`}
          fill="#002F6C"
          fillRule="evenodd"
          stroke="#001a3d"
          strokeWidth={0.4}
        />
        <text x={0} y={22} textAnchor="middle" fontSize={7} fontWeight={700} fill="#ffffff" fontFamily="Unbounded, sans-serif">
          КБТУ
        </text>

        {layout.fences.map((f, i) => (
          <polyline key={`fe${i}`} points={poly(f)} fill="none" stroke="#b45309" strokeWidth={0.35} strokeDasharray="1 0.6" />
        ))}

        {/* места */}
        {layout.stalls.map((s) => {
          const st: StallState | undefined = byId[s.id]
          const occupied = st?.occupied
          const isSel = selected === s.id || route?.stall === s.id
          const stroke = st?.violation ? '#dc2626' : isSel ? '#f59e0b' : s.type === 'disabled' ? '#2563eb'
            : s.type === 'ev' ? '#d97706' : s.type === 'staff' ? '#7c3aed' : occupied ? '#94a3b8' : '#16a34a'
          return (
            <g
              key={s.id}
              className="cursor-pointer"
              onMouseEnter={(e) => {
                const r = svgRef.current!.getBoundingClientRect()
                setHover({ id: s.id, x: e.clientX - r.left, y: e.clientY - r.top })
              }}
              onMouseLeave={() => setHover(null)}
              onClick={(e) => {
                e.stopPropagation()
                onSelect(s.id)
              }}
            >
              <polygon
                points={poly(s.polygon)}
                fill={occupied ? '#e2e8f0' : s.type === 'staff' ? 'url(#staff-hatch)' : '#dcfce7'}
                stroke={stroke}
                strokeWidth={isSel || st?.violation ? 0.6 : 0.25}
              >
                {st?.violation && <animate attributeName="stroke-opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite" />}
              </polygon>
              {occupied && <Car center={s.center} angle={s.angle} />}
              {!occupied && s.type === 'disabled' && <Glyph at={s.center} text="♿" color="#2563eb" />}
              {!occupied && s.type === 'ev' && <Glyph at={s.center} text="⚡" color="#d97706" />}
            </g>
          )
        })}

        {/* маршрут к рекомендованному месту */}
        {route && (
          <g pointerEvents="none">
            {route.drive.length > 1 && (
              <polyline points={poly(route.drive)} fill="none" stroke="#002F6C" strokeWidth={1.1} strokeLinecap="round"
                        strokeLinejoin="round" strokeDasharray="3 2">
                <animate attributeName="stroke-dashoffset" from="10" to="0" dur="0.8s" repeatCount="indefinite" />
              </polyline>
            )}
            <polyline points={poly(route.walk)} fill="none" stroke="#16a34a" strokeWidth={0.8} strokeDasharray="0.8 1.2"
                      strokeLinecap="round" />
            <circle cx={route.walk[0][0]} cy={-route.walk[0][1]} r={3.2} fill="none" stroke="#f59e0b" strokeWidth={0.7}>
              <animate attributeName="r" values="2.5;4.5;2.5" dur="1.4s" repeatCount="indefinite" />
            </circle>
          </g>
        )}

        {/* въезды, камеры, ворота, входы в здание */}
        {layout.zones.filter((z) => z.entry && z.camera).map((z) => (
          <g key={`cam${z.id}`} transform={`translate(${z.entry![0]},${-z.entry![1]})`}>
            <circle r={2.4} fill="#0f172a" />
            <circle r={1} fill="#38bdf8" />
          </g>
        ))}
        {layout.points.map((pt, i) =>
          pt.kind.startsWith('entrance') ? (
            <circle key={`e${i}`} cx={pt.at[0]} cy={-pt.at[1]} r={pt.kind === 'entrance_main' ? 1.6 : 1.1} fill="#22c55e" stroke="#fff" strokeWidth={0.4} />
          ) : (
            <rect key={`g${i}`} x={pt.at[0] - 1.2} y={-pt.at[1] - 0.5} width={2.4} height={1} fill="#b45309" />
          ),
        )}

        {/* подписи */}
        {layout.zones.map((z) => {
          const xs = z.polygon.map((q) => q[0])
          const ys = z.polygon.map((q) => q[1])
          const at: Pt = z.kind === 'street' ? [Math.min(...xs) - 8, (Math.min(...ys) + Math.max(...ys)) / 2] : [
            (Math.min(...xs) + Math.max(...xs)) / 2, Math.max(...ys) + 5]
          return (
            <g key={`zl${z.id}`} transform={`translate(${at[0]},${-at[1]})`} pointerEvents="none">
              <circle r={4} fill="#002F6C" />
              <text textAnchor="middle" dy={1.6} fontSize={4.4} fontWeight={700} fill="#fff">{z.id}</text>
            </g>
          )
        })}
        {layout.roads.filter((r) => r.name && (r.kind !== 'service' || /Казыбек/i.test(r.name))).map((r, i) => {
          const l = labelAt(r.line)
          return (
            <text key={`rl${i}`} x={l.x} y={l.y} transform={`rotate(${l.ang} ${l.x} ${l.y})`} textAnchor="middle" dy={1.2}
                  fontSize={3.2} fill="#475569" pointerEvents="none">
              {r.name}
            </text>
          )
        })}
      </svg>

      {/* масштаб и север */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex items-end gap-3 text-[10px] text-slate-600">
        <div className="flex flex-col items-center rounded-lg bg-white/90 px-2 py-1 shadow-sm">
          <span className="font-bold">С</span>
          <span className="leading-none">▲</span>
        </div>
        <ScaleBar box={box} svg={svgRef.current} />
      </div>
      <div className="absolute top-3 right-3 flex flex-col gap-1">
        {[
          { icon: Plus, f: 1 / 1.4, t: 'Приблизить' },
          { icon: Minus, f: 1.4, t: 'Отдалить' },
        ].map(({ icon: I, f, t }) => (
          <button key={t} title={t} onClick={() => zoom(f)}
                  className="rounded-lg bg-white p-1.5 text-slate-600 shadow-sm hover:text-navy-900">
            <I size={16} />
          </button>
        ))}
        <button title="Показать всю парковку" onClick={() => setBox(home)}
                className="rounded-lg bg-white p-1.5 text-slate-600 shadow-sm hover:text-navy-900">
          <Locate size={16} />
        </button>
      </div>

      {hover && hoveredMeta && (
        <div
          className="pointer-events-none absolute z-10 w-56 rounded-xl bg-navy-950/95 px-3 py-2 text-xs text-white shadow-xl"
          style={{ left: Math.min(hover.x + 14, (svgRef.current?.clientWidth ?? 600) - 230), top: hover.y + 14 }}
        >
          <div className="font-semibold">Место {hover.id}</div>
          <div className="text-white/70">{STALL_TYPE_NAMES[hoveredMeta.type]}</div>
          <div className="mt-1">
            {hovered?.occupied
              ? `Занято · ${hovered.plate ?? ''} · ${fmtDur(hovered.minutes)}`
              : 'Свободно'}
          </div>
          {hovered?.violation && <div className="mt-1 text-rose-300">{hovered.violation}</div>}
        </div>
      )}
    </div>
  )
}

function Car({ center, angle }: { center: Pt; angle: number }) {
  // машина стоит перпендикулярно проезду: длина — вдоль angle (от проезда вглубь места)
  const L = 4.2
  const W = 1.8
  return (
    <g transform={`translate(${center[0]},${-center[1]}) rotate(${-angle})`} pointerEvents="none">
      <rect x={-L / 2} y={-W / 2} width={L} height={W} rx={0.6} fill="#334155" />
      <rect x={L / 2 - 1.5} y={-W / 2 + 0.25} width={0.9} height={W - 0.5} rx={0.2} fill="#94a3b8" />
    </g>
  )
}

function Glyph({ at, text, color }: { at: Pt; text: string; color: string }) {
  return (
    <text x={at[0]} y={-at[1]} textAnchor="middle" dy={1} fontSize={2.6} fill={color} pointerEvents="none">
      {text}
    </text>
  )
}

function ScaleBar({ box, svg }: { box: Box; svg: SVGSVGElement | null }) {
  const width = svg?.clientWidth ?? 800
  const height = svg?.clientHeight ?? 500
  const scale = Math.min(width / box.w, height / box.h)
  const meters = [10, 20, 50, 100].find((m) => m * scale >= 60) ?? 100
  return (
    <div className="rounded-lg bg-white/90 px-2 py-1 shadow-sm">
      <div className="h-1.5 border-x border-b border-slate-600" style={{ width: meters * scale }} />
      <div className="mt-0.5 text-center">{meters} м</div>
    </div>
  )
}

export const fmtDur = (m: number | null) => (m == null ? '' : m < 60 ? `${m} мин` : `${Math.floor(m / 60)} ч ${m % 60} мин`)
