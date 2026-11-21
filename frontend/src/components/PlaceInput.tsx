// A10: place field with suggestions while typing and an optional country filter.
// Picking a suggestion fixes exact coordinates (sent as {label, lat, lon}); free text still
// works and is geocoded by the server as before.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useState, type ReactNode } from 'react'
import { useCountries } from '../api/account'
import { ApiError, lookupPlace, suggestPlaces } from '../api/client'
import type { Place } from '../api/types'

const DEBOUNCE_MS = 200

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

const inputCls =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm ' +
  'focus:border-sky-600 focus:outline-none focus:ring-2 focus:ring-sky-600/30 aria-[invalid=true]:border-red-500'

interface Props {
  id: string
  label: string
  placeholder: string
  text: string
  place: Place | null
  onText: (text: string) => void
  onPlace: (place: Place | null) => void
  /** ISO alpha-2, '' = any country */
  country: string
  onCountry: (code: string) => void
  /** Bias suggestions towards this point (e.g. the chosen origin). */
  near?: Place | null
  error?: string
  /** Extra control on the label row (e.g. the swap button). */
  action?: ReactNode
}

export function PlaceInput({
  id,
  label,
  placeholder,
  text,
  place,
  onText,
  onPlace,
  country,
  onCountry,
  near,
  error,
  action,
}: Props) {
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [picking, setPicking] = useState(false)
  const [pickError, setPickError] = useState<string | null>(null)
  const countries = useCountries()
  const q = useDebounced(text.trim(), DEBOUNCE_MS)
  const nearKey = near ? `${near.lat.toFixed(1)},${near.lon.toFixed(1)}` : ''

  const suggestions = useQuery({
    queryKey: ['suggest', q.toLowerCase(), country, nearKey],
    queryFn: () => suggestPlaces(q, country, nearKey),
    enabled: open && !place && q.length >= 1,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
  const items = open && !place ? (suggestions.data?.suggestions ?? []) : []
  const expanded = items.length > 0

  async function choose(i: number) {
    const s = items[i]
    if (!s) return
    setOpen(false)
    setActive(-1)
    onText(s.label)
    setPicking(true)
    setPickError(null)
    try {
      onPlace(await lookupPlace(s.id))
    } catch (e) {
      setPickError(e instanceof ApiError ? e.message : 'Could not get that place. Try again.')
    } finally {
      setPicking(false)
    }
  }

  const status = picking
    ? 'Finding the exact location…'
    : place
      ? '✓ Exact location selected'
      : open && q && suggestions.isError
        ? 'Suggestions are unavailable; you can still type the full place name.'
        : null
  const describedBy = [error ? `${id}-err` : '', status || pickError ? `${id}-status` : ''].filter(Boolean).join(' ')

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <label htmlFor={id} className="block text-xs font-medium text-slate-700">
          {label}
        </label>
        <div className="flex items-center gap-1">
          <select
            aria-label={`Search ${label.toLowerCase()} in`}
            value={country}
            onChange={(e) => {
              onCountry(e.target.value)
              setActive(-1)
            }}
            className="max-w-36 rounded border-0 bg-transparent py-0 pr-6 pl-1 text-right text-xs text-sky-800 hover:bg-sky-50 focus:outline-none focus:ring-2 focus:ring-sky-600/40"
          >
            <option value="">Any country</option>
            {countries.data?.continents.map((cont) => (
              <optgroup key={cont} label={cont}>
                {countries.data.countries
                  .filter((c) => c.continent === cont)
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
          {action}
        </div>
      </div>
      <div className="relative">
        <input
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
          className={inputCls}
          placeholder={placeholder}
          value={text}
          autoComplete="off"
          aria-invalid={!!error}
          aria-describedby={describedBy || undefined}
          onChange={(e) => {
            onText(e.target.value)
            if (place) onPlace(null) // typing again means a new search
            setPickError(null)
            setOpen(true)
            setActive(-1)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              if (!expanded) {
                setOpen(true)
                return
              }
              e.preventDefault()
              const n = items.length
              setActive((a) => (e.key === 'ArrowDown' ? (a + 1) % n : (a - 1 + n) % n))
            } else if (e.key === 'Enter' && expanded && active >= 0) {
              e.preventDefault() // pick, don't submit the form
              void choose(active)
            } else if (e.key === 'Enter') {
              setOpen(false) // submitting the form: don't leave the list over the results
            } else if (e.key === 'Escape' && expanded) {
              e.preventDefault()
              setOpen(false)
            }
          }}
        />
        {expanded && (
          <ul
            id={listId}
            role="listbox"
            aria-label={`${label} suggestions`}
            className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg"
          >
            {items.map((s, i) => (
              <li
                key={s.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                // mousedown, not click: runs before the input's blur closes the list
                onMouseDown={(e) => {
                  e.preventDefault()
                  void choose(i)
                }}
                onMouseEnter={() => setActive(i)}
                className={`cursor-pointer px-3 py-1.5 ${i === active ? 'bg-sky-50 text-sky-900' : 'text-slate-800'}`}
              >
                {s.label}
              </li>
            ))}
          </ul>
        )}
      </div>
      {(status || pickError) && (
        <p
          id={`${id}-status`}
          role={pickError ? 'alert' : 'status'}
          className={`mt-1 text-[11px] ${pickError ? 'text-red-700' : place ? 'text-emerald-700' : 'text-slate-500'}`}
        >
          {pickError ?? status}
        </p>
      )}
      {error && (
        <p id={`${id}-err`} className="mt-1 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}
