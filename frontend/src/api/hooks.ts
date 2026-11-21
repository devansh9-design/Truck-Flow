import { useMutation, useQuery } from '@tanstack/react-query'
import { analyzeTrip, getHealth, getHeatmap } from './client'
import type { AnalyzeRequest, AnalyzeResponse } from './types'
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
