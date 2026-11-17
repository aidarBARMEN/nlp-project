import { useMemo, useState } from 'react'
import type { ParkingState } from '../../parking'

const W = 640
const H = 170
const PAD = { l: 34, r: 22, t: 12, b: 22 }

export default function OccupancyChart({ state }: { state: ParkingState }) {
  const [hover, setHover] = useState<number | null>(null)
  const now = new Date(state.clock)
  const day = state.clock.slice(0, 10)

  const x = (h: number) => PAD.l + (h / 24) * (W - PAD.l - PAD.r)
  const y = (r: number) => PAD.t + (1 - r) * (H - PAD.t - PAD.b)

  const actual = useMemo(
    () =>
      state.history
        .filter((p) => p.at.startsWith(day))
        .map((p) => {
          const t = new Date(p.at)
          return { h: t.getHours() + t.getMinutes() / 60, r: p.rate }
        }),
    [state.history, day],
  )
  const forecast = [...state.forecast, { hour: 24, rate: state.forecast[0]?.rate ?? 0 }]
  const nowH = now.getHours() + now.getMinutes() / 60

  const hourActual = (h: number) => {
    const pts = actual.filter((p) => p.h >= h && p.h < h + 1)
    return pts.length ? pts.reduce((s, p) => s + p.r, 0) / pts.length : null
  }

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseLeave={() => setHover(null)}
           onMouseMove={(e) => {
             const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
             const h = Math.floor((((e.clientX - r.left) / r.width) * W - PAD.l) / (W - PAD.l - PAD.r) * 24)
             setHover(h >= 0 && h < 24 ? h : null)
           }}>
        {[0, 0.25, 0.5, 0.75, 1].map((r) => (
          <g key={r}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(r)} y2={y(r)} stroke="#e2e8f0" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(r) + 3.5} textAnchor="end" fontSize={10} fill="#64748b">{r * 100}%</text>
          </g>
        ))}
        {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
          <text key={h} x={x(h)} y={H - 6} textAnchor="middle" fontSize={10} fill="#64748b">{`${h}:00`}</text>
        ))}
        {hover !== null && (
          <rect x={x(hover)} y={PAD.t} width={x(1) - x(0)} height={H - PAD.t - PAD.b} fill="#002F6C" opacity={0.06} />
        )}
        <polyline
          points={forecast.map((f) => `${x(f.hour)},${y(f.rate)}`).join(' ')}
          fill="none" stroke="#7b93b8" strokeWidth={2} strokeDasharray="5 4" strokeLinejoin="round"
        />
        {actual.length > 1 && (
          <polyline points={actual.map((p) => `${x(p.h)},${y(p.r)}`).join(' ')} fill="none" stroke="#002F6C"
                    strokeWidth={2} strokeLinejoin="round" />
        )}
        <line x1={x(nowH)} x2={x(nowH)} y1={PAD.t} y2={H - PAD.b} stroke="#f59e0b" strokeWidth={1.5} />
        <text x={x(nowH)} y={PAD.t - 2} textAnchor="middle" fontSize={10} fontWeight={600} fill="#b45309">сейчас</text>
      </svg>
      <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 bg-navy-900" /> факт за сегодня</span>
        <span className="flex items-center gap-1.5"><span className="h-0 w-5 border-t-2 border-dashed border-[#7b93b8]" /> прогноз</span>
      </div>
      {hover !== null && (
        <div className="pointer-events-none absolute top-0 rounded-lg bg-navy-950/95 px-2.5 py-1.5 text-[11px] text-white shadow-lg"
             style={{ left: `${Math.min((x(hover) / W) * 100, 78)}%` }}>
          <div className="font-semibold">{hover}:00–{hover + 1}:00</div>
          <div>прогноз {Math.round(state.forecast[hover].rate * 100)}%</div>
          {hourActual(hover) !== null && <div>факт {Math.round(hourActual(hover)! * 100)}%</div>}
        </div>
      )}
    </div>
  )
}
