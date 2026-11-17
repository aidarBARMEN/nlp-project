import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Basemap, Layout, ParkingState, Pt, Recommendation } from '../../parking'
import { STALL_TYPE_NAMES } from '../../parking'
import { fmtDur } from './TwinMap'

// метры двойника -> широта/долгота (та же проекция, что в scripts/build_parking_twin.py)
const KY = 110574
function toLatLng(origin: { lat: number; lon: number }) {
  const kx = Math.cos((origin.lat * Math.PI) / 180) * 111320
  return ([x, y]: Pt): L.LatLngTuple => [origin.lat + y / KY, origin.lon + x / kx]
}

const TYPE_COLOR: Record<string, string> = { disabled: '#3b82f6', ev: '#f59e0b', staff: '#a855f7' }

function stallStyle(occupied: boolean, type: string, violation: boolean, selected: boolean): L.PathOptions {
  return {
    color: violation ? '#ef4444' : selected ? '#facc15' : (TYPE_COLOR[type] ?? '#ffffff'),
    weight: violation || selected ? 3 : 1,
    fillColor: occupied ? '#0f172a' : '#22c55e',
    fillOpacity: occupied ? 0.55 : 0.6,
    opacity: 0.9,
  }
}

export default function SatelliteTwin({
  layout,
  state,
  selected,
  onSelect,
  route,
  basemap,
}: {
  layout: Layout
  state: ParkingState | null
  selected: string | null
  onSelect: (id: string | null) => void
  route: Recommendation | null
  basemap: Basemap
}) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const base = useRef<L.TileLayer | null>(null)
  const stalls = useRef<Record<string, L.Polygon>>({})
  const routeLayer = useRef<L.LayerGroup | null>(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const ll = useMemo(() => toLatLng(layout.meta.origin), [layout])
  const types = useMemo(() => Object.fromEntries(layout.stalls.map((s) => [s.id, s.type])), [layout])

  // карта и неизменные слои — один раз
  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { zoomControl: true, maxZoom: 21, attributionControl: true })
    map.current = m
    const zonesBounds = L.latLngBounds(layout.zones.flatMap((z) => z.polygon.map(ll)))
    m.fitBounds(zonesBounds, { padding: [20, 20] })

    layout.zones.forEach((z) =>
      L.polygon(z.polygon.map(ll), { color: '#ffffff', weight: 1.5, dashArray: '6 4', fill: false, interactive: false })
        .bindTooltip(`Зона ${z.id} · ${z.name}`, { permanent: true, direction: 'center', className: 'twin-zone-label' })
        .addTo(m),
    )
    layout.aisles.forEach((a) =>
      L.polyline(a.line.map(ll), { color: '#ffffff', weight: 1, opacity: 0.7, dashArray: '2 6', interactive: false }).addTo(m),
    )
    layout.zones.filter((z) => z.entry && z.camera).forEach((z) =>
      L.circleMarker(ll(z.entry!), { radius: 6, color: '#0f172a', weight: 2, fillColor: '#38bdf8', fillOpacity: 1 })
        .bindTooltip(`Камера въезда, зона ${z.id}`)
        .addTo(m),
    )
    layout.points.filter((p) => p.kind.startsWith('entrance')).forEach((p) =>
      L.circleMarker(ll(p.at), { radius: 4, color: '#ffffff', weight: 1.5, fillColor: '#22c55e', fillOpacity: 1 })
        .bindTooltip(p.kind === 'entrance_main' ? 'Главный вход КБТУ' : 'Вход в здание')
        .addTo(m),
    )
    layout.stalls.forEach((s) => {
      const poly = L.polygon(s.polygon.map(ll), stallStyle(false, s.type, false, false))
        .on('click', (e) => {
          L.DomEvent.stopPropagation(e)
          onSelectRef.current(s.id)
        })
        .bindTooltip('', { sticky: true })
        .addTo(m)
      stalls.current[s.id] = poly
    })
    m.on('click', () => onSelectRef.current(null))
    routeLayer.current = L.layerGroup().addTo(m)
    return () => {
      m.remove()
      map.current = null
      stalls.current = {}
    }
  }, [layout, ll])

  // подложка
  useEffect(() => {
    const m = map.current
    if (!m) return
    base.current?.remove()
    base.current = L.tileLayer(basemap.url, {
      maxNativeZoom: basemap.max_zoom,
      maxZoom: 21,
      attribution: basemap.attribution,
    }).addTo(m)
    base.current.bringToBack()
    if (basemap.viewport_url) {
      // Google требует показывать актуальный копирайт снимков для текущего вида
      const update = () => {
        const b = m.getBounds()
        const url = `${basemap.viewport_url}&zoom=${Math.min(m.getZoom(), basemap.max_zoom)}&north=${b.getNorth()}&south=${b.getSouth()}&east=${b.getEast()}&west=${b.getWest()}`
        fetch(url).then((r) => r.json()).then((d) => {
          m.attributionControl.setPrefix(`© Google${d.copyright ? ` · ${d.copyright}` : ''}`)
        }).catch(() => undefined)
      }
      update()
      m.on('moveend', update)
      return () => {
        m.off('moveend', update)
        m.attributionControl.setPrefix('')
      }
    }
    m.attributionControl.setPrefix('')
  }, [basemap])

  // состояние мест
  useEffect(() => {
    if (!state) return
    for (const s of state.stalls) {
      const poly = stalls.current[s.id]
      if (!poly) continue
      poly.setStyle(stallStyle(s.occupied, types[s.id], !!s.violation, selected === s.id || route?.stall === s.id))
      poly.setTooltipContent(
        `<b>Место ${s.id}</b><br/>${STALL_TYPE_NAMES[types[s.id] as keyof typeof STALL_TYPE_NAMES]}<br/>` +
          (s.occupied ? `Занято · ${s.plate ?? ''} · ${fmtDur(s.minutes)}` : 'Свободно') +
          (s.violation ? `<br/><span style="color:#ef4444">${s.violation}</span>` : ''),
      )
    }
  }, [state, selected, route, types])

  // маршрут к рекомендованному месту
  useEffect(() => {
    const g = routeLayer.current
    if (!g) return
    g.clearLayers()
    if (!route) return
    if (route.drive.length > 1) {
      L.polyline(route.drive.map(ll), { color: '#facc15', weight: 4, dashArray: '8 6' }).addTo(g)
    }
    L.polyline(route.walk.map(ll), { color: '#22c55e', weight: 3, dashArray: '2 6' }).addTo(g)
    map.current?.panTo(ll(route.walk[0]))
  }, [route, ll])

  return <div ref={el} className="h-full w-full overflow-hidden rounded-2xl border border-slate-200" />
}
