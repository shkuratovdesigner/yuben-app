/**
 * Composes the global stores in one place so `App.tsx` stays a two-liner and
 * every screen has access to config/run/history state. The stores are
 * independent (no cross-dependencies), so nesting order is not significant.
 */
import type { ReactNode } from 'react'

import { ConfigProvider } from '@/app/stores/config-store'
import { HistoryProvider } from '@/app/stores/history-store'
import { RunProvider } from '@/app/stores/run-store'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider>
      <HistoryProvider>
        <RunProvider>{children}</RunProvider>
      </HistoryProvider>
    </ConfigProvider>
  )
}
