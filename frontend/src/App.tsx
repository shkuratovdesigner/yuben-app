import { BrowserRouter } from 'react-router-dom'

import { AppProviders } from '@/app/AppProviders'
import { AppRoutes } from '@/app/router'

/**
 * App root: router → global stores → routes. The global chrome + onboarding
 * gate + /run/:id Loader↔Results switch all live in `@/app/router`; the stores
 * (config / run / history) live in `@/app/AppProviders`. Screens are filled in
 * by the Wave-2 agents (F1..F7).
 */
export default function App() {
  return (
    <BrowserRouter>
      <AppProviders>
        <AppRoutes />
      </AppProviders>
    </BrowserRouter>
  )
}
