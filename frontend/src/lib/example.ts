import type { Interval } from '../api/types'

/** Sample trip behind "Try an example" (the route used throughout the docs). */
export const EXAMPLE = {
  origin: 'Denver, CO',
  destination: 'Salt Lake City, UT',
  loadLb: 42000,
  interval: 25 as Interval,
}
