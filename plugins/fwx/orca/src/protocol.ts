// The panel <-> worker contract: panel.html and src/worker.ts both read it.
import type { Snapshot } from './session'

export {}

declare module 'orca' {
  interface PluginRequests {
    /** The session of the workspace in view, read now; null where there is none to show. */
    'session.get': { output: { snapshot: Snapshot | null } }
  }
  interface PluginPanelEvents {
    /** Posted to every open panel after each read. */
    'session.changed': { snapshot: Snapshot | null }
  }
}
