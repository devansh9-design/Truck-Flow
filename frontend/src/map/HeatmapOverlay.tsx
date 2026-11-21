import { BitmapLayer } from '@deck.gl/layers'
import { MapboxOverlay, type MapboxOverlayProps } from '@deck.gl/mapbox'
import { useMemo } from 'react'
import { useControl } from 'react-map-gl/maplibre'
import type { HeatmapResponse } from '../api/types'
import { frameImage, gridBounds, HEATMAP_HOURS } from '../lib/heatmap'
import { useUi } from '../store/ui'

function DeckOverlay(props: MapboxOverlayProps) {
  const overlay = useControl<MapboxOverlay>(() => new MapboxOverlay(props))
  overlay.setProps(props)
  return null
}

/**
 * CORE-6 heatmap. All 49 frames are in memory; for the chosen variable every frame is
 * pre-rendered to a tiny image (one pixel per grid cell), so moving the slider only
 * swaps which image the layer shows: no network, no recomputation (NFR-2).
 *
 * Why a smoothed bitmap and not deck.gl's HeatmapLayer: HeatmapLayer estimates point
 * density with a kernel whose spread is ~8% of radiusPixels (capped at 100 px), so a
 * corridor grid of ~256 cells renders as separate dots. A gridded forecast is a field;
 * linear texture filtering shows it as one, with exact values at the cell centres.
 */
export function HeatmapOverlay({ heat }: { heat: HeatmapResponse }) {
  const hour = useUi((s) => s.heatHour)
  const variable = useUi((s) => s.heatVariable)
  const visible = useUi((s) => s.heatVisible)

  const bounds = useMemo(() => gridBounds(heat), [heat])
  const images = useMemo(
    () =>
      Array.from({ length: HEATMAP_HOURS }, (_, h) => {
        const f = frameImage(heat, variable, h)
        return new ImageData(f.data, f.width, f.height)
      }),
    [heat, variable],
  )

  const layer = new BitmapLayer({
    id: 'weather-heatmap',
    bounds,
    image: images[hour],
    opacity: 0.65,
    visible,
    textureParameters: { minFilter: 'linear', magFilter: 'linear' },
  })

  // Overlaid (deck.gl's own canvas), not interleaved: @deck.gl/mapbox 9.4's interleaved
  // renderer reads map.transform, which MapLibre 6 no longer exposes. Route markers are
  // DOM elements and stay above; the semi-transparent heatmap sits over the line layers.
  // The heatmap must never take the map down with it (e.g. no WebGL context available):
  // deck.gl reports the failure here and the routes and checkpoints carry on.
  return <DeckOverlay layers={[layer]} onError={(e) => console.warn('Heatmap could not render:', e.message)} />
}
