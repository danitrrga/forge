// Finds the folder of the workspace in view, runs `fwx` there, and keeps the status bar chip and the panel current: on
// `workspace.changed` and every 5 s. The worker runs with Orca's PATH and $HOME as its folder (not the project's), so `fwx` is
// looked up by name and always run with `cwd` set to the workspace. Pressing the chip runs the `open` command.
import { execFile } from 'node:child_process'
import { dirname, join } from 'node:path'
import type { OrcaWorkerApi } from 'orca/worker'
import { chipText, parsePhases, parseSession, snapshot, tooltip, type Snapshot } from './session'

const EVERY_MS = 5000
const FWX_TIMEOUT_MS = 4000
/** What `orca plugin open` takes: `local.<id>` for a plugin loaded from a folder, which is how forge loads it. */
const PLUGIN_KEY = 'local.fwx-session'
const PANEL_ID = 'session'

/** Runs `fwx <args>` in `cwd`; the stdout whatever the exit code (`fwx session --json` exits 1 with no phase and still prints). */
function fwx(cwd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile('fwx', args, { cwd, timeout: FWX_TIMEOUT_MS }, (err, stdout) => {
      if (stdout) return resolve(stdout)
      reject(err ?? new Error('fwx printed nothing'))
    })
  })
}

/** Orca's own CLI: the launcher sits in the resources of the Orca this worker runs in, next to its executable (the worker's
 *  PATH has no `orca`). `plugin open` shows the panel in the right sidebar without taking focus. */
function openPanel(): Promise<void> {
  const cli = join(dirname(process.execPath), 'resources', 'bin', 'orca-ide')
  return new Promise((resolve, reject) => {
    execFile(cli, ['plugin', 'open', PLUGIN_KEY, '--panel', PANEL_ID], { timeout: FWX_TIMEOUT_MS }, (err) => (err ? reject(err) : resolve()))
  })
}

let timer: ReturnType<typeof setInterval> | undefined

export default function activate(orca: OrcaWorkerApi): void {
  let lastProblem = ''
  let running = false
  let again = false

  /** The snapshot of the workspace in view, or null (no workspace, a remote one, no fwx project there, fwx failing). */
  async function read(): Promise<Snapshot | null> {
    const context = await orca.host.call('workspace.readContext')
    if (!context?.workspaceId) return null
    const { workspaces } = await orca.host.call('workspace.list')
    const here = workspaces.find((w) => w.id === context.workspaceId)
    if (!here || (here.hostId !== null && here.hostId !== 'local')) return null
    try {
      const session = parseSession(await fwx(here.path, ['session', '--json']))
      // The roadmap is a second read of the same folder; without it the chip still shows.
      const sub = session?.subproject ? ['--subproject', session.subproject] : []
      const list = session?.project ? parsePhases(await fwx(here.path, ['phase', 'list', '--json', ...sub]).catch(() => '')) : parsePhases('')
      lastProblem = ''
      return snapshot(session, list)
    } catch (e) {
      const problem = `fwx in ${here.path}: ${e instanceof Error ? e.message : String(e)}`
      if (problem !== lastProblem) orca.log(problem)
      lastProblem = problem
      return null
    }
  }

  async function refresh(): Promise<Snapshot | null> {
    let shot: Snapshot | null = null
    try {
      shot = await read()
    } catch (e) {
      orca.log(`reading the workspace failed: ${e instanceof Error ? e.message : String(e)}`)
    }
    await orca.host.call(
      'statusBar.update',
      shot
        ? { id: 'session', visible: true, text: chipText(shot), tooltip: tooltip(shot), tone: shot.phase ? 'accent' : 'neutral' }
        : { id: 'session', visible: false }
    )
    orca.panels.post('session.changed', { snapshot: shot })
    return shot
  }

  /** One read at a time; an event during a read asks for one more after it. */
  async function tick(): Promise<void> {
    if (running) {
      again = true
      return
    }
    running = true
    try {
      do {
        again = false
        await refresh()
      } while (again)
    } finally {
      running = false
    }
  }

  orca.events.on('workspace.changed', () => tick())
  orca.commands.register('open', async () => {
    try {
      await openPanel()
    } catch (e) {
      orca.log(`opening the panel failed: ${e instanceof Error ? e.message : String(e)}`)
    }
  })
  orca.panels.handle('session.get', async () => ({ snapshot: await refresh() }))
  void tick()
  timer = setInterval(() => void tick(), EVERY_MS)
}

/** Orca awaits it before stopping the worker; the tests rely on it to let the process end. */
export function deactivate(): void {
  clearInterval(timer)
}
