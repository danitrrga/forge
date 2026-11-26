// What `fwx session --json` and `fwx phase list --json` say, and the chip, the tooltip and the panel's data made from them.
// No Orca calls here, so tests need no host.

/** The keys of `fwx session --json` the plugin reads. `project` is null where the folder has no `.claude/fwx.json`. */
export type Session = {
  project: string | null
  phase_dir: string | null
  milestone: string | null
  subproject: string | null
  stage: string | null
  part: number | null
  parts: number | null
  branch: string | null
  progress: number | null
}

/** `fwx phase list --json`, the part the roadmap reads. */
export type PhaseList = {
  milestones: { name: string; phases: { name: string; stage: string | null; open: boolean; subphases: string[] }[] }[]
}

/** `fwx wave list --json`, one live or finished `fwx wave run` per entry; only what the chip and the panel read. */
export type WaveWorker = { unit: string | null; role: string | null; state: string | null; released: boolean; line: string | null }
export type WaveInfo = { n: number; tasks: string[] }
export type WaveRun = {
  run: string
  part: string
  branch: string
  state: string
  pid: number | null
  alive: boolean
  step: string | null
  started: number | null
  orca_run: string | null
  waves: WaveInfo[]
  done: string[]
  workers: WaveWorker[]
  events: string[]
  result: unknown
}
export type WaveList = { runs: WaveRun[] }

export type State = 'done' | 'current' | 'next'
export type Item = { name: string; state: State }
/** One line of the panel's Workflow section: a planned task or another worker (a reviewer, a fixer), where it stands. */
export type FlowRow = { name: string; state: State; tag: string; failed: boolean }

/** Everything the chip, the tooltip and the panel show; JSON, so it crosses to the panel as it is. */
export type Snapshot = {
  project: string
  /** Session profiles do not exist yet (plan 4.3): see `profileOf`. */
  profile: string | null
  stage: string | null
  progress: number | null
  branch: string | null
  milestone: string | null
  /** The current phase's folder name, null with no phase open. */
  phase: string | null
  part: number | null
  parts: number | null
  /** The milestone's phases, in order, each with its last stage. */
  phases: (Item & { stage: string | null })[]
  /** The current phase's parts (its subphases), in order. */
  partList: Item[]
  /** The newest `fwx wave run` that is active and alive in this folder, null when none is running. */
  activeRun: WaveRun | null
  /** The rows of `activeRun` for the panel (`flowRows`), empty with no live run. */
  flow: FlowRow[]
}

const BAR_CELLS = 8

/** The profile of the session. One place to fill when 4.3 adds a field to `fwx session --json`; null shows nothing. */
export function profileOf(_session: Session): string | null {
  return null
}

function raw<T>(stdout: string): T | null {
  try {
    const v: unknown = JSON.parse(stdout)
    return typeof v === 'object' && v !== null ? (v as T) : null
  } catch {
    return null
  }
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const num = (v: unknown): number | null => (typeof v === 'number' ? v : null)

/** The Session in `stdout`, or null when it is not one: not JSON, or from an fwx too old to carry `project`.
 *  `fwx session --json` prints it with exit 1 too (no phase open), so the caller must not read the exit code. */
export function parseSession(stdout: string): Session | null {
  const r = raw<Record<string, unknown>>(stdout)
  if (!r || !('project' in r)) return null
  return {
    project: str(r.project),
    phase_dir: str(r.phase_dir),
    milestone: str(r.milestone),
    subproject: str(r.subproject),
    stage: str(r.stage),
    part: num(r.part),
    parts: num(r.parts),
    branch: str(r.branch),
    progress: num(r.progress)
  }
}

/** The PhaseList in `stdout`, or an empty one: the roadmap is then just the current phase, never a reason to hide the chip. */
export function parsePhases(stdout: string): PhaseList {
  const r = raw<{ milestones?: unknown }>(stdout)
  const ms = Array.isArray(r?.milestones) ? (r.milestones as PhaseList['milestones']) : []
  return { milestones: ms.filter((m) => m && typeof m.name === 'string' && Array.isArray(m.phases)) }
}

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
const objs = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null) : []

/** The runs of `fwx wave list --json`, or none: an fwx that has no such flag prints a usage line, a broken one garbage, and neither may hide the chip. */
export function parseWaves(stdout: string): WaveRun[] {
  const r = raw<{ runs?: unknown }>(stdout)
  return objs(r?.runs)
    .filter((x) => typeof x.run === 'string' && x.run)
    .map((x) => ({
      run: x.run as string,
      part: typeof x.part === 'string' ? x.part : '',
      branch: typeof x.branch === 'string' ? x.branch : '',
      state: typeof x.state === 'string' ? x.state : '',
      pid: num(x.pid),
      alive: x.alive === true,
      step: str(x.step),
      started: num(x.started),
      orca_run: str(x.orca_run),
      waves: objs(x.waves).map((w) => ({ n: num(w.n) ?? 0, tasks: strs(w.tasks) })),
      done: strs(x.done),
      workers: objs(x.workers).map((w) => ({ unit: str(w.unit), role: str(w.role), state: str(w.state), released: w.released === true, line: str(w.line) })),
      events: strs(x.events),
      result: x.result ?? null
    }))
}

/** The run in progress: the newest (by start time) that is active and whose process lives; a dead or finished one shows nothing. */
function liveRun(runs: WaveRun[]): WaveRun | null {
  return runs.filter((r) => r.state === 'active' && r.alive).reduce<WaveRun | null>((a, r) => (!a || (r.started ?? 0) >= (a.started ?? 0) ? r : a), null)
}

/** What a worker's last line says: the replies `fwx wave run` itself counts as a good end (`done`, `reviewed`, `verdicts`). */
const GOOD = /^(done|reviewed|verdicts)(?:\s|$)/

/** The rows of a run: each planned task (by its last worker, `done` if already on the branch, else `next`), then the workers the plan does not name (reviewers, fixers). */
export function flowRows(run: WaveRun): FlowRow[] {
  const last = new Map<string, WaveWorker>()
  for (const w of run.workers) if (w.unit) last.set(w.unit, w)
  const done = new Set(run.done)
  const row = (name: string, w: WaveWorker | undefined, alreadyDone = false): FlowRow => {
    if (!w) return { name, state: alreadyDone ? 'done' : 'next', tag: '', failed: false }
    if (!w.released) return { name, state: 'current', tag: [w.role, w.state ?? 'running'].filter(Boolean).join(' · '), failed: false }
    if (w.line && GOOD.test(w.line)) return { name, state: 'done', tag: w.role ?? '', failed: false }
    return { name, state: 'next', tag: 'failed', failed: true }
  }
  const planned = new Set(run.waves.flatMap((w) => w.tasks))
  return [
    ...run.waves.flatMap((w) => w.tasks.map((id) => row(`Wave ${w.n} · ${id}`, last.get(id), done.has(id)))),
    ...[...last].filter(([unit]) => !planned.has(unit)).map(([unit, w]) => row(unit, w))
  ]
}

/** The folder's own name (`01-login`) from the path `fwx` prints. */
export function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

/** Where each part stands, given the part in hand (N): before it done, N current, after it next; all done once the phase closed. */
function partStates(names: string[], part: number | null, stage: string | null): Item[] {
  return names.map((name, i) => ({
    name,
    state: stage === 'closed' || (part !== null && i + 1 < part) ? 'done' : part !== null && i + 1 === part ? 'current' : 'next'
  }))
}

/** The Snapshot of a session and the phase list read in the same folder; null when the folder has no fwx project. */
export function snapshot(s: Session | null, list: PhaseList, waves: WaveRun[] = []): Snapshot | null {
  if (!s || !s.project) return null
  const phase = s.phase_dir ? baseName(s.phase_dir) : null
  const milestone = list.milestones.find((m) => m.name === s.milestone)
  const phases = (milestone?.phases ?? []).map((p) => ({
    name: p.name,
    stage: p.stage,
    state: (p.name === phase ? 'current' : p.open ? 'next' : 'done') as State
  }))
  const current = milestone?.phases.find((p) => p.name === phase)
  const activeRun = liveRun(waves)
  return {
    project: s.project,
    profile: profileOf(s),
    stage: s.stage,
    progress: phase ? s.progress : null,
    branch: s.branch,
    milestone: s.milestone,
    phase,
    part: s.part,
    parts: s.parts,
    phases,
    partList: partStates(current?.subphases ?? [], s.part, s.stage),
    activeRun,
    flow: activeRun ? flowRows(activeRun) : []
  }
}

/** A bar of BAR_CELLS characters filled to `progress` (0 to 1): `▰▰▰▱▱▱▱▱`. */
export function bar(progress: number): string {
  const filled = Math.max(0, Math.min(BAR_CELLS, Math.round(progress * BAR_CELLS)))
  return '▰'.repeat(filled) + '▱'.repeat(BAR_CELLS - filled)
}

/** The chip's text: `<project> · <profile> · ▰▰▰▱▱▱▱▱`, the profile only when there is one; `<project> · no phase` with no phase.
 *  A live `fwx wave run` takes the chip over, phase or not: `<project> · <part> · <step> (<open workers>/<workers>)`. */
export function chipText(v: Snapshot): string {
  const head = [v.project, v.profile].filter(Boolean).join(' · ')
  const r = v.activeRun
  if (r) return `${head} · ${r.part || r.run} · ${r.step ?? 'running'}${r.workers.length ? ` (${r.workers.filter((w) => !w.released).length}/${r.workers.length})` : ''}`
  if (!v.phase) return `${head} · no phase`
  const where = [head, v.phase, v.stage].filter(Boolean).join(' · ')
  return v.progress === null ? where : `${where} · ${bar(v.progress)}`
}

const MARK: Record<State, string> = { done: '✓', current: '▶', next: '○' }
const AROUND = 2

/** The roadmap on one line: Orca's tooltip is `text-balance` with no `white-space: pre`, so a line break would collapse to a
 *  space. Phases around the current one (AROUND each side, `…` beyond), then the parts, then the branch. */
export function tooltip(v: Snapshot): string {
  const flow = v.activeRun ? `Workflow ${v.activeRun.part || v.activeRun.run} (${v.activeRun.step ?? 'running'})` : null
  if (!v.phase) return flow ?? 'No phase open'
  const at = Math.max(0, v.phases.findIndex((p) => p.state === 'current'))
  const from = Math.max(0, at - AROUND)
  const to = Math.min(v.phases.length, at + AROUND + 1)
  const phases = v.phases.slice(from, to).map((p) => `${MARK[p.state]} ${p.name}${p.state === 'current' && p.stage ? ` (${p.stage})` : ''}`)
  const out = [flow, v.milestone ? `Milestone ${v.milestone}` : null, ...(from > 0 ? ['…'] : []), ...phases, ...(to < v.phases.length ? ['…'] : [])]
  if (v.partList.length) out.push(`Parts ${v.partList.map((p, i) => `${MARK[p.state]}${i + 1}`).join(' ')}`)
  if (v.branch) out.push(`Branch ${v.branch}`)
  return out.filter(Boolean).join(' · ')
}
