// P3-2 unit toggle: display only. The wire and the rules stay imperial (mi, mph, in/hr, lb);
// these helpers only change how a number is printed, never a value sent to the API.
import { formatNumber } from './format'

export type Units = 'imperial' | 'metric'

export const KM_PER_MI = 1.609344
export const MM_PER_IN = 25.4
export const KG_PER_LB = 0.45359237

export const miToKm = (mi: number) => mi * KM_PER_MI
export const kmToMi = (km: number) => km / KM_PER_MI
export const mphToKmh = (mph: number) => mph * KM_PER_MI
export const kmhToMph = (kmh: number) => kmh / KM_PER_MI
export const inHrToMmHr = (inHr: number) => inHr * MM_PER_IN
export const mmHrToInHr = (mmHr: number) => mmHr / MM_PER_IN
export const lbToKg = (lb: number) => lb * KG_PER_LB

export interface UnitFormat {
  units: Units
  distanceUnit: string
  speedUnit: string
  rateUnit: string
  /** Distance from miles, e.g. "12.3 mi" / "19.8 km". */
  distance: (mi: number, digits?: number) => string
  speed: (mph: number, digits?: number) => string
  /** Precipitation rate from in/hr. */
  rate: (inHr: number) => string
  weight: (lb: number) => string
  /** Convert an imperial heatmap value (mph or in/hr) for display, by its imperial unit. */
  convert: (value: number, imperialUnit: string) => number
}

const IMPERIAL: UnitFormat = {
  units: 'imperial',
  distanceUnit: 'mi',
  speedUnit: 'mph',
  rateUnit: 'in/hr',
  distance: (mi, digits = 1) => `${formatNumber(mi, digits)} mi`,
  speed: (mph, digits = 1) => `${formatNumber(mph, digits)} mph`,
  rate: (inHr) => `${formatNumber(inHr, 2)} in/hr`,
  weight: (lb) => `${Math.round(lb).toLocaleString('en-US')} lb`,
  convert: (v) => v,
}

const METRIC: UnitFormat = {
  units: 'metric',
  distanceUnit: 'km',
  speedUnit: 'km/h',
  rateUnit: 'mm/hr',
  distance: (mi, digits = 1) => `${formatNumber(miToKm(mi), digits)} km`,
  speed: (mph, digits = 1) => `${formatNumber(mphToKmh(mph), digits)} km/h`,
  rate: (inHr) => `${formatNumber(inHrToMmHr(inHr), 1)} mm/hr`,
  weight: (lb) => `${Math.round(lbToKg(lb)).toLocaleString('en-US')} kg`,
  convert: (v, unit) => (unit === 'mph' ? mphToKmh(v) : unit === 'in/hr' ? inHrToMmHr(v) : v),
}

export const unitFormat = (units: Units): UnitFormat => (units === 'metric' ? METRIC : IMPERIAL)

const KEY = 'truckrisk.units'

/** Remembered per browser; storage may be unavailable (private mode), so never throw. */
export function loadUnits(): Units {
  try {
    return globalThis.localStorage?.getItem(KEY) === 'metric' ? 'metric' : 'imperial'
  } catch {
    return 'imperial'
  }
}

export function storeUnits(units: Units): void {
  try {
    globalThis.localStorage?.setItem(KEY, units)
  } catch {
    /* display preference only */
  }
}
