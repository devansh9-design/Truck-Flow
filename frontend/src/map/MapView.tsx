import 'maplibre-gl/dist/maplibre-gl.css'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Layer,
  Map,
  Marker,
  NavigationControl,
  Popup,
  ScaleControl,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from 'react-map-gl/maplibre'
import type { AnalyzeResponse, HeatmapResponse, Route } from '../api/types'
import { CheckpointDetails } from '../components/CheckpointDetails'
import { maplibregl } from './maplibre'
import { riskColorExpression, riskStyle } from '../lib/risk'
import { truckPosition } from '../lib/heatmap'
import { riskSegments } from '../lib/segments'
import { useTimeFormatter, useUi } from '../store/ui'

// deck.gl is only needed once a heatmap exists: load it on demand so it is not parsed at startup.
const HeatmapOverlay = lazy(() => import('./HeatmapOverlay').then((m) => ({ default: m.HeatmapOverlay })))

const STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || 'https://tiles.openfreemap.org/styles/liberty'
const US_VIEW = { longitude: -98.5, latitude: 39.5, zoom: 3.4 }
const INTERACTIVE = ['route-hit', 'other-checkpoints-hit']

const RECOMMENDED_COLOR = '#0369a1'
const ALTERNATE_COLOR = '#64748b'

interface Props {
  data: AnalyzeResponse | undefined
  heat?: HeatmapResponse
}

function findCheckpoint(routes: Route[], id: string | null) {
  if (!id) return null
  for (const r of routes) {
    const i = r.checkpoints.findIndex((c) => c.id === id)
    if (i >= 0) return { route: r, cp: r.checkpoints[i], isLast: i === r.checkpoints.length - 1 }
  }
  return null
}

export function MapView({ data, heat }: Props) {
  const mapRef = useRef<MapRef>(null)
  const selectedRouteId = useUi((s) => s.selectedRouteId)
  const selectedCheckpointId = useUi((s) => s.selectedCheckpointId)
  const selectRoute = useUi((s) => s.selectRoute)
  const selectCheckpoint = useUi((s) => s.selectCheckpoint)
  const formatTime = useTimeFormatter()
  const [hoverRouteId, setHoverRouteId] = useState<string | null>(null)
  const [cursor, setCursor] = useState<string>('')

  const routes = useMemo(() => data?.routes ?? [], [data])
  const selected = routes.find((r) => r.id === selectedRouteId)

  const routeLines = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: routes.map((r) => ({
        type: 'Feature' as const,
        properties: { id: r.id, recommended: r.recommended, label: r.label },
        geometry: r.geometry,
      })),
    }),
    [routes],
  )

  const segments = useMemo(
    () => ({ type: 'FeatureCollection' as const, features: selected ? riskSegments(selected) : [] }),
    [selected],
  )

  // Checkpoints of the routes that are not selected: GPU circles, still clickable.
  const otherCheckpoints = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: routes
        .filter((r) => r.id !== selectedRouteId)
        .flatMap((r) =>
          r.checkpoints.map((c) => ({
            type: 'Feature' as const,
            properties: { id: c.id, level: c.risk.level },
            geometry: { type: 'Point' as const, coordinates: [c.lon, c.lat] },
          })),
        ),
    }),
    [routes, selectedRouteId],
  )

  const fit = useCallback(() => {
    const bbox = data?.corridor.bbox
    if (!bbox || !mapRef.current) return
    mapRef.current.fitBounds(
      [
        [bbox[0], bbox[1]],
        [bbox[2], bbox[3]],
      ],
      { padding: 48, duration: 700 },
    )
  }, [data])

  useEffect(() => fit(), [fit])

  const activeCp = findCheckpoint(routes, selectedCheckpointId)

  function onClick(e: MapLayerMouseEvent) {
    const f = e.features?.[0]
    if (!f) return selectCheckpoint(null)
    if (f.layer.id === 'other-checkpoints-hit') selectCheckpoint(String(f.properties.id))
    else selectRoute(String(f.properties.id))
  }

  function onMove(e: MapLayerMouseEvent) {
    const f = e.features?.[0]
    setCursor(f ? 'pointer' : '')
    setHoverRouteId(f?.layer.id === 'route-hit' ? String(f.properties.id) : null)
  }

  const notSelected = ['!=', ['get', 'id'], selectedRouteId ?? ''] as const

  return (
    <Map
      ref={mapRef}
      mapLib={maplibregl}
      initialViewState={US_VIEW}
      mapStyle={STYLE_URL}
      interactiveLayerIds={data ? INTERACTIVE : []}
      onClick={onClick}
      onMouseMove={onMove}
      onMouseLeave={() => {
        setCursor('')
        setHoverRouteId(null)
      }}
      onLoad={fit}
      cursor={cursor}
      style={{ width: '100%', height: '100%' }}
      attributionControl={{ compact: true }}
    >
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="top-right" unit="imperial" />

      {heat && (
        <Suspense fallback={null}>
          <HeatmapOverlay heat={heat} />
        </Suspense>
      )}

      <Source id="routes" type="geojson" data={routeLines}>
        {/* Alternates: grey; the recommended route keeps a blue dashed line when not selected. */}
        <Layer
          id="route-casing"
          type="line"
          filter={notSelected as never}
          layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          paint={{ 'line-color': '#ffffff', 'line-width': 7, 'line-opacity': 0.9 }}
        />
        <Layer
          id="route-alt"
          type="line"
          filter={['all', notSelected, ['!', ['get', 'recommended']]] as never}
          layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          paint={{ 'line-color': ALTERNATE_COLOR, 'line-width': 4, 'line-opacity': 0.85 }}
        />
        <Layer
          id="route-rec"
          type="line"
          filter={['all', notSelected, ['get', 'recommended']] as never}
          layout={{ 'line-join': 'round' }}
          paint={{ 'line-color': RECOMMENDED_COLOR, 'line-width': 4, 'line-dasharray': [2, 1.5] }}
        />
        <Layer
          id="route-hover"
          type="line"
          filter={['all', notSelected, ['==', ['get', 'id'], hoverRouteId ?? '']] as never}
          layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          paint={{ 'line-color': '#0f172a', 'line-width': 6, 'line-opacity': 0.35 }}
        />
        <Layer
          id="route-hit"
          type="line"
          filter={notSelected as never}
          paint={{ 'line-color': '#000000', 'line-width': 16, 'line-opacity': 0 }}
        />
      </Source>

      <Source id="selected-segments" type="geojson" data={segments}>
        <Layer
          id="selected-casing"
          type="line"
          layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          paint={{ 'line-color': '#0f172a', 'line-width': 9 }}
        />
        <Layer
          id="selected-risk"
          type="line"
          layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          paint={{ 'line-color': riskColorExpression() as never, 'line-width': 5.5 }}
        />
      </Source>

      <Source id="other-checkpoints" type="geojson" data={otherCheckpoints}>
        <Layer
          id="other-checkpoints"
          type="circle"
          paint={{
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 3, 9, 6],
            'circle-color': riskColorExpression() as never,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 1.5,
          }}
        />
        {/* Invisible, larger target so the small dots are easy to click or tap. */}
        <Layer id="other-checkpoints-hit" type="circle" paint={{ 'circle-radius': 11, 'circle-opacity': 0 }} />
      </Source>

      {selected?.checkpoints.map((cp, i) => {
        const s = riskStyle(cp.risk.level)
        const end = i === 0 || i === selected.checkpoints.length - 1
        const name = i === 0 ? 'Origin' : end ? 'Destination' : `Checkpoint ${cp.index}`
        return (
          <Marker
            key={cp.id}
            longitude={cp.lon}
            latitude={cp.lat}
            onClick={(e) => {
              e.originalEvent.stopPropagation()
              selectCheckpoint(cp.id)
            }}
          >
            <button
              type="button"
              data-testid="checkpoint-marker"
              aria-label={`${selected.label} ${name}: ${s.label} risk, ETA ${formatTime(cp.eta)}`}
              title={`${name} · ${s.label} · ETA ${formatTime(cp.eta)}`}
              className={`flex items-center justify-center rounded-full border-2 font-bold leading-none shadow focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-500/60 ${
                end ? 'h-7 w-7 border-slate-900 text-xs' : 'h-5 w-5 border-white text-[10px]'
              } ${selectedCheckpointId === cp.id ? 'scale-125 ring-2 ring-slate-900' : ''}`}
              style={{ background: s.color, color: s.text }}
            >
              {i === 0 ? 'A' : end ? 'B' : <span aria-hidden="true">{s.icon}</span>}
            </button>
          </Marker>
        )
      })}

      {selected && heat && <TruckMarker route={selected} times={heat.times} />}

      {activeCp && (
        <Popup
          longitude={activeCp.cp.lon}
          latitude={activeCp.cp.lat}
          onClose={() => selectCheckpoint(null)}
          closeOnClick={false}
          maxWidth="320px"
          offset={14}
          focusAfterOpen={false}
        >
          <CheckpointDetails cp={activeCp.cp} routeLabel={activeCp.route.label} isLast={activeCp.isLast} />
        </Popup>
      )}
    </Map>
  )
}

/**
 * Where the truck on the selected route is at the slider hour (from checkpoint ETAs).
 * Subscribes to the hour itself so scrubbing re-renders only this marker, not the map.
 */
function TruckMarker({ route, times }: { route: Route; times: string[] }) {
  const hour = useUi((s) => s.heatHour)
  const at = times[hour]
  if (!at) return null
  const p = truckPosition(route, new Date(at).getTime())
  return (
    <Marker longitude={p.lon} latitude={p.lat} anchor="center" style={{ zIndex: 2 }}>
      <div
        role="img"
        aria-label={`Truck on ${route.label} at the selected forecast hour`}
        title="Truck position at the selected hour"
        className="pointer-events-none flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-slate-900 text-base shadow-lg"
      >
        <span aria-hidden="true">🚚</span>
      </div>
    </Marker>
  )
}
