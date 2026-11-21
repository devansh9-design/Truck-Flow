// P3-1: under 768 px the side panel becomes a bottom sheet over a full-screen map.
// Three snap heights (peek / half / full); drag the handle, or tap it / use arrow keys on it.
// The panel element stays the same across the breakpoint, so form input is never lost.
import { useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent, type PointerEvent } from 'react'

export const MOBILE_QUERY = '(max-width: 767px)'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query)
      mq.addEventListener('change', cb)
      return () => mq.removeEventListener('change', cb)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

export type Snap = 'peek' | 'half' | 'full'
const ORDER: Snap[] = ['peek', 'half', 'full']
const PEEK_PX = 148
const TOP_GAP_PX = 64 // full height leaves a strip of map (and its controls) visible

function useViewportHeight(): number {
  const [h, setH] = useState(() => window.innerHeight)
  useEffect(() => {
    const on = () => setH(window.innerHeight)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return h
}

export function snapHeight(snap: Snap, viewport: number): number {
  if (snap === 'peek') return Math.round(Math.min(PEEK_PX, viewport * 0.4))
  if (snap === 'half') return Math.round(viewport * 0.5)
  return Math.round(Math.max(viewport - TOP_GAP_PX, viewport * 0.5))
}

/** Height, transition and handle props for a sheet at `snap`. */
export function useBottomSheet(snap: Snap, onSnap: (s: Snap) => void) {
  const viewport = useViewportHeight()
  const [dragPx, setDragPx] = useState<number | null>(null)
  const drag = useRef<{ y: number; h: number; moved: boolean } | null>(null)
  const justDragged = useRef(false)
  const height = dragPx ?? snapHeight(snap, viewport)

  const nearest = (px: number) =>
    ORDER.reduce((best, s) =>
      Math.abs(snapHeight(s, viewport) - px) < Math.abs(snapHeight(best, viewport) - px) ? s : best,
    )
  const step = (dir: 1 | -1) => onSnap(ORDER[Math.max(0, Math.min(2, ORDER.indexOf(snap) + dir))])

  const handleProps = {
    type: 'button' as const,
    'aria-label': snap === 'full' ? 'Collapse panel' : 'Expand panel',
    'aria-expanded': snap !== 'peek',
    'data-testid': 'sheet-handle',
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      e.currentTarget.setPointerCapture?.(e.pointerId)
      drag.current = { y: e.clientY, h: height, moved: false }
      justDragged.current = false
    },
    onPointerMove: (e: PointerEvent<HTMLButtonElement>) => {
      const d = drag.current
      if (!d) return
      const dy = d.y - e.clientY
      if (Math.abs(dy) > 6) d.moved = true
      if (d.moved) setDragPx(Math.max(snapHeight('peek', viewport) - 40, Math.min(viewport - 24, d.h + dy)))
    },
    onPointerUp: (e: PointerEvent<HTMLButtonElement>) => {
      const d = drag.current
      drag.current = null
      if (d?.moved) {
        justDragged.current = true
        onSnap(nearest(d.h + (d.y - e.clientY)))
      }
      setDragPx(null)
    },
    onPointerCancel: () => {
      drag.current = null
      setDragPx(null)
    },
    onClick: () => {
      // A drag also ends in a click; only a tap or Enter/Space cycles the snap.
      if (justDragged.current) {
        justDragged.current = false
        return
      }
      onSnap(snap === 'full' ? 'peek' : ORDER[ORDER.indexOf(snap) + 1])
    },
    onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()
        step(e.key === 'ArrowUp' ? 1 : -1)
      }
    },
  }

  return {
    height,
    style: { height, transition: dragPx === null ? 'height 200ms ease-out' : 'none' },
    handleProps,
  }
}
