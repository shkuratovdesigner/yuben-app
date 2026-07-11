/**
 * Runtime environment switches.
 *
 * VITE_USE_MOCKS  -> the typed API client serves bundled fixtures and never
 *                    hits the network (lets the whole UI run with no backend).
 *                    Mock-first by design: ON unless explicitly set to "0".
 *                    Phase 2 integration flips it off (VITE_USE_MOCKS=0).
 * VITE_API_BASE   -> absolute backend base URL. Empty string means "same
 *                    origin" and relies on the Vite dev proxy for `/api/*`.
 *
 * The YouTube key is NEVER read here — it lives only in the backend's local
 * secret store, write-only via the API. No secret ever reaches frontend env.
 */
export const USE_MOCKS: boolean = import.meta.env.VITE_USE_MOCKS !== '0'

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''
