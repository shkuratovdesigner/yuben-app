/**
 * Config / onboarding store.
 *
 * WAVE-2 SCREENS CONSUME THIS — signatures are the contract, don't break them.
 *
 *   useConfig(): {
 *     config: Config | null            // null only while first load is in flight
 *     adapters: Adapter[]              // installed CLIs + versions + models
 *     loading: boolean                 // true until config + adapters resolve
 *     saveConfig(patch: Partial<Config>): Promise<Config>   // merge + PUT + update
 *     storeKey(key: string): Promise<{ ok: boolean }>       // write-only key store
 *     adapterHealth: AdapterHealth     // live probe result, not saved config
 *     runEnvCheck(): Promise<EnvCheckResult>                // "respond hello" probe
 *     runKeyTest(): Promise<KeyTestResult>                  // one cheap YouTube call
 *     refresh(): Promise<void>                              // reload config + adapters
 *   }
 *
 * Who uses it:
 *   • F1 OnboardingModel  — adapters (cards), saveConfig({ adapter, model }), runEnvCheck.
 *   • F2 OnboardingSetup   — storeKey, runKeyTest, saveConfig({ onboarding_complete: true }).
 *   • F3 Composer          — config.adapter/model for the footer model switcher,
 *                            adapterHealth for the footer's live model status.
 *   • App shell gate       — config.onboarding_complete.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'

import type { Adapter, Config, EnvCheckResult, KeyProvider, KeyTestResult } from '@/lib/types'
import { api } from '@/lib/api'

/**
 * Whether the configured adapter ANSWERS, as opposed to merely being configured.
 *
 *   unknown  — not probed yet, or the probe itself failed to reach the backend
 *   checking — probe in flight (an agent CLI can take up to 90s to answer)
 *   ok       — the adapter replied
 *   failed   — the adapter is installed/selected but refused: `result.message`
 *              carries the backend's reason and `result.remedy` the fix
 *
 * `unknown` and `failed` are deliberately distinct. "We don't know" must never
 * render as a red dot — a backend hiccup is not evidence the model is broken.
 */
export type AdapterHealthStatus = 'unknown' | 'checking' | 'ok' | 'failed'

export interface AdapterHealth {
  status: AdapterHealthStatus
  result: EnvCheckResult | null
}

interface ConfigContextValue {
  config: Config | null
  adapters: Adapter[]
  loading: boolean
  adapterHealth: AdapterHealth
  saveConfig: (patch: Partial<Config>) => Promise<Config>
  storeKey: (key: string, provider?: KeyProvider) => Promise<{ ok: boolean }>
  runEnvCheck: () => Promise<EnvCheckResult>
  runKeyTest: () => Promise<KeyTestResult>
  refresh: () => Promise<void>
}

const ConfigContext = createContext<ConfigContextValue | null>(null)

/** Which Config presence flag each stored key flips. Keys themselves never land here. */
const PRESENCE_FLAG: Record<KeyProvider, keyof Config> = {
  youtube: 'youtube_key_present',
  anthropic: 'anthropic_key_present',
  openai: 'openai_key_present',
  openrouter: 'openrouter_key_present',
  gemini: 'gemini_key_present',
}

/** Fallback used only to merge a patch before the first config load resolves. */
const EMPTY_CONFIG: Config = {
  schema_version: '1.0',
  adapter: null,
  model: null,
  youtube_key_present: false,
  anthropic_key_present: false,
  openai_key_present: false,
  openrouter_key_present: false,
  gemini_key_present: false,
  onboarding_complete: false,
}

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null)
  const [adapters, setAdapters] = useState<Adapter[]>([])
  const [loading, setLoading] = useState(true)
  const [adapterHealth, setAdapterHealth] = useState<AdapterHealth>({
    status: 'unknown',
    result: null,
  })
  // Which adapter id the current page load has already probed. Keyed on the
  // adapter rather than a bare boolean so switching CLI re-probes, and set
  // synchronously at call time so the load effect can't double-fire.
  const checkedAdapterRef = useRef<string | null | undefined>(undefined)

  const refresh = useCallback(async () => {
    const [nextConfig, nextAdapters] = await Promise.all([api.getConfig(), api.getAdapters()])
    setConfig(nextConfig)
    setAdapters(nextAdapters)
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([api.getConfig(), api.getAdapters()])
      .then(([nextConfig, nextAdapters]) => {
        if (!active) return
        setConfig(nextConfig)
        setAdapters(nextAdapters)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const saveConfig = useCallback(
    async (patch: Partial<Config>) => {
      const next: Config = { ...(config ?? EMPTY_CONFIG), ...patch }
      const saved = await api.putConfig(next)
      setConfig(saved)
      return saved
    },
    [config],
  )

  const storeKey = useCallback(async (key: string, provider: KeyProvider = 'youtube') => {
    const result = await api.postKey(key, provider)
    if (result.ok) {
      // Optimistically reflect presence; the value itself never lives here.
      setConfig((prev) => (prev ? { ...prev, [PRESENCE_FLAG[provider]]: true } : prev))
    }
    return result
  }, [])

  /**
   * The "respond hello" probe. Still returns the raw result (onboarding's
   * EnvCheckRow renders it inline) but ALSO records it as `adapterHealth`, so a
   * check run anywhere is the check the whole app reports. That is what keeps
   * finishing onboarding from immediately re-probing on the composer: step 1
   * just proved the CLI answers, and this remembers it.
   */
  const runEnvCheck = useCallback(async () => {
    const adapter = config?.adapter ?? null
    checkedAdapterRef.current = adapter
    setAdapterHealth({ status: 'checking', result: null })
    try {
      const result = await api.envCheck()
      // Discard a verdict the user has already navigated past by switching CLI.
      if (checkedAdapterRef.current === adapter) {
        setAdapterHealth({ status: result.ok ? 'ok' : 'failed', result })
      }
      return result
    } catch (error) {
      // A transport failure is not a verdict ON the adapter — stay 'unknown'
      // rather than accusing a model that may be perfectly healthy.
      if (checkedAdapterRef.current === adapter) {
        setAdapterHealth({ status: 'unknown', result: null })
      }
      throw error
    }
  }, [config?.adapter])

  /**
   * Probe once per page load, so the UI reports whether the model ACTUALLY
   * answers instead of that one was configured. Saved config is not evidence of
   * a live credential: an agent CLI's OAuth token rotates and expires, so a
   * selection can read as connected long after the CLI stopped being able to
   * reply — and the first symptom used to be a run dying mid-flight.
   *
   * Deliberately narrow. Onboarding is skipped (`onboarding_complete` is false
   * there, and it runs its own check anyway), and the ref keys on the adapter
   * id, so switching MODEL in the footer spawns no second subprocess — the
   * probe is adapter-level, since `envCheck()` sends no body and the backend
   * probes the saved adapter with `model=None`.
   */
  useEffect(() => {
    if (!config?.onboarding_complete) return
    const adapter = config.adapter
    if (!adapter || checkedAdapterRef.current === adapter) return
    void runEnvCheck().catch(() => {
      // Swallowed on purpose: runEnvCheck already recorded 'unknown', and an
      // automatic background probe must never raise an unhandled rejection.
    })
  }, [config?.onboarding_complete, config?.adapter, runEnvCheck])

  const runKeyTest = useCallback(() => api.keyTest(), [])

  const value = useMemo<ConfigContextValue>(
    () => ({
      config,
      adapters,
      loading,
      adapterHealth,
      saveConfig,
      storeKey,
      runEnvCheck,
      runKeyTest,
      refresh,
    }),
    [
      config,
      adapters,
      loading,
      adapterHealth,
      saveConfig,
      storeKey,
      runEnvCheck,
      runKeyTest,
      refresh,
    ],
  )

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>
}

export function useConfig(): ConfigContextValue {
  const ctx = useContext(ConfigContext)
  if (!ctx) throw new Error('useConfig must be used within <ConfigProvider> (see AppProviders).')
  return ctx
}
