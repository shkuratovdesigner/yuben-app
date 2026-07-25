/**
 * Runtime environment switches.
 *
 * VITE_API_BASE   -> absolute backend base URL. Empty string means "same
 *                    origin" and relies on the Vite dev proxy for `/api/*`.
 *
 * There is no mock switch: the app always talks to the backend. The bundled
 * example run is seeded into the backend's own store instead, so demo data can
 * never silently stand in for the user's real research.
 *
 * The YouTube key is NEVER read here — it lives only in the backend's local
 * secret store, write-only via the API. No secret ever reaches frontend env.
 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''
