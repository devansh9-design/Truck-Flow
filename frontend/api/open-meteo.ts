// Vercel Function: relays the risk engine's Open-Meteo forecast requests.
//
// Open-Meteo's free tier limits calls per outbound IP, and Render's free services share
// outbound IPs that other tenants exhaust daily. The risk engine sets OPEN_METEO_URL to
// this function so its requests leave from Vercel's network instead (docs/deployment.md).
// The upstream is fixed to the forecast endpoint: this is not an open proxy.
const UPSTREAM = 'https://api.open-meteo.com/v1/forecast'

export async function GET(request: Request): Promise<Response> {
  const { search } = new URL(request.url)
  const upstream = await fetch(UPSTREAM + search, { headers: { accept: 'application/json' } })
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') ?? 'application/json',
      'cache-control': 'no-store',
    },
  })
}
