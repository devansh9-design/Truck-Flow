import { useMutation, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { analyzeTrip, getAlerts, getHealth, getHeatmap } from './client'
import type { AnalyzeRequest, AnalyzeResponse } from './types'
import { alertPoints } from '../lib/alerts'
import { hourZero } from '../lib/heatmap'

/** Called on load so sleeping hosts (Render free tier) wake before the first submit. */
export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: 3,
    retryDelay: (n) => Math.min(2000 * 2 ** n, 15000),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

export const useAnalyze = () =>
  useMutation({
    mutationKey: ['analyze'],
    mutationFn: (req: AnalyzeRequest) => analyzeTrip(req),
  })

/**
 * CORE-6: one request per analysed trip returns all 49 frames. Cached for the session
 * (staleTime Infinity), so the slider never triggers a network call while scrubbing.
 */
export function useHeatmap(data: AnalyzeResponse | undefined) {
  const bbox = data?.corridor.bbox
  const start = data ? hourZero(data.trip.departure_time) : ''
  const load = data?.trip.load_weight_lb ?? 0
  return useQuery({
    queryKey: ['heatmap', bbox, start, load],
    queryFn: () => getHeatmap(bbox!, start, load),
    enabled: !!data,
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: false,
  })
}

/**
 * P3-3 (non-core): NWS alerts at points about every 50 mi along the analysed routes.
 * Fetched after the analysis, in the background; failure never affects the results.
 */
export function useAlerts(data: AnalyzeResponse | undefined) {
  const points = useMemo(() => (data ? alertPoints(data.routes) : []), [data])
  const query = useQuery({
    queryKey: ['alerts', points.map((p) => [p.lat, p.lon])],
    queryFn: () => getAlerts(points.map(({ lat, lon }) => ({ lat, lon }))),
    enabled: points.length > 0,
    staleTime: 10 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: false,
  })
  return { points, ...query }
}
