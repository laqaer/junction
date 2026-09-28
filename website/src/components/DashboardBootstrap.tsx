import type { ReactNode } from 'react'
import { useRefreshScheduler } from '../hooks/useRefreshScheduler'
import HarnessPrerequisiteGate from './HarnessPrerequisiteGate'

export default function DashboardBootstrap({ children }: { children: ReactNode }) {
  // This must mount outside the prerequisite gate: a stale access cookie may
  // otherwise prevent App from mounting the scheduler that repairs that cookie.
  useRefreshScheduler()
  return <HarnessPrerequisiteGate>{children}</HarnessPrerequisiteGate>
}
