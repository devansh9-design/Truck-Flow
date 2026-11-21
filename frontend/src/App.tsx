import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'

// Chunk 1 shell: wakes both services on load. The trip form, map and results arrive in Chunk 3.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch((e: Error) => setError(e.message))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Weather-Aware Truck Routing</h1>
      <p role="status">
        {error
          ? `API unreachable: ${error}`
          : health
            ? `API ${health.status} · risk engine ${health.risk_engine}`
            : 'Waking services…'}
      </p>
    </main>
  )
}
