/**
 * History store — the past runs list.
 *
 * WAVE-2 SCREENS CONSUME THIS (F7 History):
 *
 *   useHistory(): {
 *     items: HistoryItem[]                       // past runs (newest-first as served)
 *     loading: boolean
 *     remove(runId: string): Promise<void>       // delete a saved run (optimistic)
 *     refresh(): Promise<void>                    // reload the list
 *   }
 *
 * Reopening a run is NOT done here — a History row links to `/run/:id`, and the
 * run store's `useRun(id)` fetches the cached result (never re-runs). See
 * run-store.tsx.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { HistoryItem } from '@/lib/types'
import { api } from '@/lib/api'

interface HistoryContextValue {
  items: HistoryItem[]
  loading: boolean
  remove: (runId: string) => Promise<void>
  refresh: () => Promise<void>
}

const HistoryContext = createContext<HistoryContextValue | null>(null)

export function HistoryProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const next = await api.getHistory()
    setItems(next)
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    api
      .getHistory()
      .then((next) => {
        if (active) setItems(next)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const remove = useCallback(async (runId: string) => {
    // Optimistic removal, then persist.
    setItems((prev) => prev.filter((item) => item.run_id !== runId))
    await api.deleteHistory(runId)
  }, [])

  const value = useMemo<HistoryContextValue>(
    () => ({ items, loading, remove, refresh }),
    [items, loading, remove, refresh],
  )

  return <HistoryContext.Provider value={value}>{children}</HistoryContext.Provider>
}

export function useHistory(): HistoryContextValue {
  const ctx = useContext(HistoryContext)
  if (!ctx) throw new Error('useHistory must be used within <HistoryProvider> (see AppProviders).')
  return ctx
}
