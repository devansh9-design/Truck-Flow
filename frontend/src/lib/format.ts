// Display formatting. The wire is imperial + UTC; times are shown in the browser's zone.

export const formatMiles = (mi: number): string =>
  `${mi.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mi`

export function formatDuration(seconds: number): string {
  const totalMin = Math.round(seconds / 60)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m} min`
}

export function formatTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
    timeZone,
  }).format(new Date(iso))
}

export const formatNumber = (n: number, digits: number): string =>
  n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

const pad = (n: number) => String(n).padStart(2, '0')

export const browserTimeZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone

/** UTC offset of `timeZone` at instant `ms`, in minutes east of UTC. */
export function zoneOffsetMinutes(timeZone: string, ms: number): number {
  const part = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'longOffset' })
    .formatToParts(new Date(ms))
    .find((p) => p.type === 'timeZoneName')?.value
  const m = part?.match(/GMT([+-])(\d{2}):(\d{2})/)
  if (!m) return 0 // "GMT" alone means UTC
  return (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]))
}

const offsetText = (min: number) => {
  const abs = Math.abs(min)
  return `${min >= 0 ? '+' : '-'}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
}

/** `<input type="datetime-local">` value, read as wall time in `timeZone` → ISO 8601 with offset. */
export function zonedInputToIso(value: string, timeZone: string): string {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) throw new Error('Invalid date')
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  let off = zoneOffsetMinutes(timeZone, wall)
  off = zoneOffsetMinutes(timeZone, wall - off * 60_000) // settle DST transitions
  return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00${offsetText(off)}`
}

/** The next whole hour after `now` in `timeZone`, as a datetime-local input value. */
export function nextHourInput(timeZone: string, now: Date = new Date()): string {
  // Round on the zone's wall clock so half-hour zones (e.g. +05:30) still get hh:00.
  const offMs = zoneOffsetMinutes(timeZone, now.getTime()) * 60_000
  const next = Math.floor((now.getTime() + offMs) / 3_600_000) * 3_600_000 + 3_600_000 - offMs
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(new Date(next))
      .map((p) => [p.type, p.value]),
  )
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

/** Trip time zones offered in the form; the browser's own zone is added if missing. */
export const TRIP_TIME_ZONES: { id: string; label: string }[] = [
  { id: 'America/New_York', label: 'Eastern (New York)' },
  { id: 'America/Chicago', label: 'Central (Chicago)' },
  { id: 'America/Denver', label: 'Mountain (Denver)' },
  { id: 'America/Phoenix', label: 'Arizona (Phoenix)' },
  { id: 'America/Los_Angeles', label: 'Pacific (Los Angeles)' },
  { id: 'America/Anchorage', label: 'Alaska (Anchorage)' },
  { id: 'Pacific/Honolulu', label: 'Hawaii (Honolulu)' },
  { id: 'America/Toronto', label: 'Eastern (Toronto)' },
  { id: 'America/Vancouver', label: 'Pacific (Vancouver)' },
  { id: 'UTC', label: 'UTC' },
]
