// Account country helpers (display only).

/** Country of this browser's locale (e.g. "es-ES" -> "ES"), to preselect the picker. */
export function guessCountry(): string {
  try {
    const region = new Intl.Locale(navigator.language).maximize().region
    return region && /^[A-Z]{2}$/.test(region) ? region : ''
  } catch {
    return ''
  }
}
