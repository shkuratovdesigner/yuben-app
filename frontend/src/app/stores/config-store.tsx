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
 *     runEnvCheck(): Promise<EnvCheckResult>                // "respond hello" probe
 *     runKeyTest(): Promise<KeyTestResult>                  // one cheap YouTube call
 *     refresh(): Promise<void>                              // reload config + adapters
 *   }
 *
 * Who uses it:
 *   • F1 OnboardingModel  — adapters (cards), saveConfig({ adapter, model }), runEnvCheck.
 *   • F2 OnboardingSetup   — storeKey, runKeyTest, saveConfig({ onboarding_complete: true }).
 *   • F3 Composer          — config.adapter/model for the footer model switcher.
 *   • App shell gate       — config.onboarding_complete.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { Adapter, Config, EnvCheckResult, KeyProvider, KeyTestResult } from '@/lib/types'
import { api } from '@/lib/api'

interface ConfigContextValue {
  config: Config | null
  adapters: Adapter[]
  loading: boolean
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
  onboarding_complete: false,
}

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null)
  const [adapters, setAdapters] = useState<Adapter[]>([])
  const [loading, setLoading] = useState(true)

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

  const runEnvCheck = useCallback(() => api.envCheck(), [])
  const runKeyTest = useCallback(() => api.keyTest(), [])

  const value = useMemo<ConfigContextValue>(
    () => ({ config, adapters, loading, saveConfig, storeKey, runEnvCheck, runKeyTest, refresh }),
    [config, adapters, loading, saveConfig, storeKey, runEnvCheck, runKeyTest, refresh],
  )

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>
}

export function useConfig(): ConfigContextValue {
  const ctx = useContext(ConfigContext)
  if (!ctx) throw new Error('useConfig must be used within <ConfigProvider> (see AppProviders).')
  return ctx
}
