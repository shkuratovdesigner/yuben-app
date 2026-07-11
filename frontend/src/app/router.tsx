/**
 * App router (react-router-dom@7) + the two conventions Wave-2 screens rely on.
 *
 * SCREEN-EXPORT CONVENTION
 *   Every screen is the DEFAULT export of `src/screens/<Name>/index.tsx`.
 *   F1..F7 replace the placeholder stubs in those folders; this router already
 *   imports them by that path, so filling the folder is all that's needed.
 *   (F5 owns Results/index.tsx + Results/TopVideos.tsx; F6 owns
 *    Results/AnalysisTabs.tsx + Results/WatchList.tsx. The Results/index.tsx
 *    placeholder below is replaced by F5.)
 *
 * /run/:id  — Loader ↔ Results SWITCHING CONTRACT
 *   RunRoute drives off the run store (useRun(id)). It mounts <Loader/> for
 *   every non-finished status and <Results/> only once `status === 'done' &&
 *   result` — so Results (F5/F6) never has to defend against a null result.
 *   Both screens read their data from `useRun(id)` themselves.
 *
 * ONBOARDING GATE
 *   Onboarding routes are always reachable. The app routes (/, /run/:id,
 *   /history) are wrapped in <RequireOnboarding/>: while config loads it renders
 *   nothing; if `onboarding_complete` is false it redirects to /onboarding/model.
 */
import { Navigate, Outlet, Route, Routes, useParams } from 'react-router-dom'

import { AppLayout } from '@/app/AppLayout'
import { useConfig } from '@/app/stores/config-store'
import { useRun } from '@/app/stores/run-store'

import OnboardingModel from '@/screens/OnboardingModel'
import OnboardingSetup from '@/screens/OnboardingSetup'
import Composer from '@/screens/Composer'
import Loader from '@/screens/Loader'
import Results from '@/screens/Results'
import History from '@/screens/History'
import DesignPreview from '@/screens/_preview/DesignPreview'

/** Gate for app routes: hold during load, redirect to onboarding if incomplete. */
function RequireOnboarding() {
  const { config, loading } = useConfig()
  if (loading || !config) return null
  if (!config.onboarding_complete) return <Navigate to="/onboarding/model" replace />
  return <Outlet />
}

/** Loader while the run isn't done; Results once it is (see switching contract). */
function RunRoute() {
  const { id } = useParams<{ id: string }>()
  const run = useRun(id)
  if (run.status === 'done' && run.result) return <Results />
  return <Loader />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* Onboarding — always reachable (not gated). */}
        <Route path="/onboarding/model" element={<OnboardingModel />} />
        <Route path="/onboarding/setup" element={<OnboardingSetup />} />

        {/* App — gated behind completed onboarding. */}
        <Route element={<RequireOnboarding />}>
          <Route path="/" element={<Composer />} />
          <Route path="/run/:id" element={<RunRoute />} />
          <Route path="/history" element={<History />} />
        </Route>

        {/* Design-system reference (kept reachable for dev). */}
        <Route path="/_preview" element={<DesignPreview />} />

        {/* Unknown paths fall back home (which itself re-gates to onboarding). */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
