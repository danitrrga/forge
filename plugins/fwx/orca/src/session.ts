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

export type State = 'done' | 'current' | 'next'
export type Item = { name: string; state: State }

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
export function snapshot(s: Session | null, list: PhaseList): Snapshot | null {
  if (!s || !s.project) return null
  const phase = s.phase_dir ? baseName(s.phase_dir) : null
  const milestone = list.milestones.find((m) => m.name === s.milestone)
  const phases = (milestone?.phases ?? []).map((p) => ({
    name: p.name,
    stage: p.stage,
    state: (p.name === phase ? 'current' : p.open ? 'next' : 'done') as State
  }))
  const current = milestone?.phases.find((p) => p.name === phase)
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
    partList: partStates(current?.subphases ?? [], s.part, s.stage)
  }
}

/** A bar of BAR_CELLS characters filled to `progress` (0 to 1): `▰▰▰▱▱▱▱▱`. */
export function bar(progress: number): string {
  const filled = Math.max(0, Math.min(BAR_CELLS, Math.round(progress * BAR_CELLS)))
  return '▰'.repeat(filled) + '▱'.repeat(BAR_CELLS - filled)
}

/** The chip's text: `<project> · <profile> · ▰▰▰▱▱▱▱▱`, the profile only when there is one; `<project> · sin fase` with no phase. */
export function chipText(v: Snapshot): string {
  const head = [v.project, v.profile].filter(Boolean).join(' · ')
  if (!v.phase) return `${head} · sin fase`
  const where = [head, v.phase, v.stage].filter(Boolean).join(' · ')
  return v.progress === null ? where : `${where} · ${bar(v.progress)}`
}

const MARK: Record<State, string> = { done: '✓', current: '▶', next: '○' }
const AROUND = 2

/** The roadmap on one line: Orca's tooltip is `text-balance` with no `white-space: pre`, so a line break would collapse to a
 *  space. Phases around the current one (AROUND each side, `…` beyond), then the parts, then the branch. */
export function tooltip(v: Snapshot): string {
  if (!v.phase) return 'Sin fase abierta'
  const at = Math.max(0, v.phases.findIndex((p) => p.state === 'current'))
  const from = Math.max(0, at - AROUND)
  const to = Math.min(v.phases.length, at + AROUND + 1)
  const phases = v.phases.slice(from, to).map((p) => `${MARK[p.state]} ${p.name}${p.state === 'current' && p.stage ? ` (${p.stage})` : ''}`)
  const out = [v.milestone ? `Hito ${v.milestone}` : null, ...(from > 0 ? ['…'] : []), ...phases, ...(to < v.phases.length ? ['…'] : [])]
  if (v.partList.length) out.push(`Partes ${v.partList.map((p, i) => `${MARK[p.state]}${i + 1}`).join(' ')}`)
  if (v.branch) out.push(`Rama ${v.branch}`)
  return out.filter(Boolean).join(' · ')
}
