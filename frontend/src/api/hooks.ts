import { useMutation, useQuery } from '@tanstack/react-query'
import { analyzeTrip, getHealth } from './client'
import type { AnalyzeRequest } from './types'

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
