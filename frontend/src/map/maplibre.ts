// MapLibre 6 loads its web worker from a URL relative to its own module, which breaks
// once Vite pre-bundles or hashes the library. Point it at the worker file explicitly.
import * as maplibregl from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

maplibregl.setWorkerUrl(workerUrl)

export { maplibregl }
