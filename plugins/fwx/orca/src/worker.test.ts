// The worker over a mock host, with a fake `fwx` that is the only thing on PATH (no real fwx, no real project).
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { assert, mockHost, mountWorker, test } from 'orca/testing'
import * as main from './worker'

const PHASES = JSON.stringify({ milestones: [{ name: 'v1', phases: [{ name: '01-a', stage: 'executing', open: true, subphases: ['01.1-x', '01.2-y'] }] }] })
const SESSION = JSON.stringify({ project: 'atlas', phase_dir: '/srv/atlas/.fwx/milestones/v1/phases/01-a', milestone: 'v1', subproject: null,
  stage: 'executing', part: 1, parts: 2, branch: 'fwx/a', progress: 0.5 })

/** A folder holding a `fwx` that prints `session` for `session --json` (exit 1, as with no phase, when `exit1`) and PHASES for
 *  `phase list`, `waves` for `wave list --json` (a failure with no output when null, as an fwx that has no such flag), and records the folder it ran in. PATH is only that folder for the duration of `fn`. */
async function withFwx(session: string, fn: (calls: string) => Promise<void>, exit1 = false, waves: string | null = null): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), 'fwx-plugin-test-'))
  const calls = join(dir, 'calls')
  const script = `#!/bin/sh\necho "$(pwd) $*" >> '${calls}'\ncase "$1" in\n session) printf '%s' '${session}'; ${exit1 ? 'exit 1' : 'exit 0'};;\n phase) printf '%s' '${PHASES}';;\n wave) ${waves === null ? 'exit 2' : `printf '%s' '${waves}'`};;\nesac\n`
  writeFileSync(join(dir, 'fwx'), script)
  chmodSync(join(dir, 'fwx'), 0o755)
  const was = process.env.PATH
  process.env.PATH = dir
  try {
    await fn(calls)
  } finally {
    process.env.PATH = was
    rmSync(dir, { recursive: true, force: true })
  }
}

const WS = { id: 'ws-1', kind: 'worktree', name: 'atlas', path: tmpdir(), branch: 'master', hostId: null }
const host = (workspaces: object[], focused: string | null = 'ws-1') =>
  mockHost({
    capabilities: ['workspace:read'],
    results: {
      'workspace.readContext': focused ? { workspaceId: focused, branch: 'master', displayName: 'master', terminals: [] } : null,
      'workspace.list': { workspaces, truncated: false },
      'statusBar.update': { ok: true }
    }
  })
const updates = (h: ReturnType<typeof host>) => h.callsOf('statusBar.update') as Record<string, unknown>[]

test('the chip shows the focused workspace, read where it lives', async () => {
  await withFwx(SESSION, async (calls) => {
    const h = host([WS])
    const w = await mountWorker(main, { host: h, events: ['workspace.changed'] })
    await w.request('session.get')
    const last = updates(h).at(-1)!
    assert.equal(last.visible, true)
    assert.equal(last.text, 'atlas · 01-a · executing · ▰▰▰▰▱▱▱▱')
    assert.equal(last.tone, 'accent')
    assert.match(String(last.tooltip), /▶ 01-a \(executing\)/)
    const ran = (await import('node:fs')).readFileSync(calls, 'utf8')
    assert.match(ran, new RegExp(`^${tmpdir()} session --json$`, 'm'))
    assert.deepEqual(w.refusals, [])
    await w.deactivate()
  })
})

test('no phase (fwx exits 1 and still prints): the chip says so', async () => {
  const none = JSON.stringify({ project: 'atlas', phase_dir: null, milestone: null, subproject: null, stage: null, part: null, parts: null, branch: null, progress: null })
  await withFwx(none, async () => {
    const h = host([WS])
    const w = await mountWorker(main, { host: h })
    await w.request('session.get')
    assert.equal(updates(h).at(-1)!.text, 'atlas · no phase')
    await w.deactivate()
  }, true)
})

test('hidden: no fwx project, no focused workspace, a remote workspace, fwx missing', async () => {
  const noProject = JSON.stringify({ project: null, phase_dir: null })
  await withFwx(noProject, async () => {
    const h = host([WS])
    const w = await mountWorker(main, { host: h })
    assert.deepEqual((await w.request('session.get')).snapshot, null)
    assert.equal(updates(h).at(-1)!.visible, false)
    await w.deactivate()
  })
  await withFwx(SESSION, async () => {
    for (const [label, h] of [['nothing focused', host([WS], null)], ['an unknown workspace', host([], 'ws-9')],
      ['a remote workspace', host([{ ...WS, hostId: 'ssh:box' }])]] as const) {
      const w = await mountWorker(main, { host: h })
      await w.request('session.get')
      assert.equal(updates(h).at(-1)!.visible, false, label)
      await w.deactivate()
    }
  })
  const h = host([WS])
  const was = process.env.PATH
  process.env.PATH = mkdtempSync(join(tmpdir(), 'fwx-plugin-empty-'))
  try {
    const w = await mountWorker(main, { host: h })
    await w.request('session.get')
    assert.equal(updates(h).at(-1)!.visible, false)
    assert.ok(w.logs.some((l) => l.includes('fwx in')), w.logs.join('|'))
    await w.deactivate()
  } finally {
    rmSync(process.env.PATH, { recursive: true, force: true })
    process.env.PATH = was
  }
})

test('an event reads again and tells the open panels', async () => {
  await withFwx(SESSION, async () => {
    const w = await mountWorker(main, { host: host([WS]), events: ['workspace.changed'] })
    try {
      await w.request('session.get')
      // The worker's first read may still be running: let it end, so the next post can only come from the event.
      for (let i = 0; i < 100; i++) {
        const n = w.posts.length
        await new Promise((r) => setTimeout(r, 30))
        if (w.posts.length === n) break
      }
      const before = w.posts.length
      await w.emit('workspace.changed', { context: { workspaceId: 'ws-1', branch: 'master', displayName: 'master', terminals: [] } })
      for (let i = 0; i < 100 && w.posts.length === before; i++) await new Promise((r) => setTimeout(r, 30))
      assert.ok(w.posts.length > before, 'no post after workspace.changed')
      assert.equal(w.posts.at(-1)!.event, 'session.changed')
    } finally {
      await w.deactivate()
    }
  })
})

test('the open command never throws when Orca\'s CLI is not where expected', async () => {
  await withFwx(SESSION, async () => {
    const w = await mountWorker(main, { host: host([WS]), commands: ['open'] })
    await w.command('open')
    assert.ok(w.logs.some((l) => l.includes('opening the panel failed')), w.logs.join('|'))
    await w.deactivate()
  })
})

const RUNS = JSON.stringify({ runs: [{
  run: 'r-1', part: '01.1-x', branch: 'fwx/a', state: 'active', pid: 1, alive: true, step: 'wave 1', started: 5, orca_run: 'run_1',
  waves: [{ n: 1, tasks: ['T1'] }], workers: [{ unit: 'T1', role: 'executor', state: 'running', released: false, line: null }], events: ['worker T1 started'], result: null
}] })

test('a live wave run is read with `wave list --json` in the workspace and shown in the chip, the tooltip and the snapshot', async () => {
  await withFwx(SESSION, async (calls) => {
    const h = host([WS])
    const w = await mountWorker(main, { host: h })
    const shot = (await w.request('session.get')).snapshot as { activeRun: { run: string } | null }
    const last = updates(h).at(-1)!
    assert.equal(shot.activeRun!.run, 'r-1')
    assert.equal(last.text, 'atlas · 01.1-x · wave 1 (1/1)')
    assert.equal(last.tone, 'accent')
    assert.match(String(last.tooltip), /^Workflow 01\.1-x \(wave 1\) · /)
    const ran = (await import('node:fs')).readFileSync(calls, 'utf8')
    assert.match(ran, new RegExp(`^${tmpdir()} wave list --json$`, 'm'))
    assert.deepEqual(w.refusals, [])
    await w.deactivate()
  }, false, RUNS)
})

test('a live run lights the chip when no phase is bound; without one the chip is neutral', async () => {
  const none = JSON.stringify({ project: 'atlas', phase_dir: null, milestone: null, subproject: null, stage: null, part: null, parts: null, branch: null, progress: null })
  await withFwx(none, async () => {
    const h = host([WS])
    const w = await mountWorker(main, { host: h })
    await w.request('session.get')
    assert.equal(updates(h).at(-1)!.text, 'atlas · 01.1-x · wave 1 (1/1)')
    assert.equal(updates(h).at(-1)!.tone, 'accent')
    await w.deactivate()
  }, true, RUNS)
  await withFwx(none, async () => {
    const h = host([WS])
    const w = await mountWorker(main, { host: h })
    await w.request('session.get')
    assert.equal(updates(h).at(-1)!.text, 'atlas · no phase')
    assert.equal(updates(h).at(-1)!.tone, 'neutral')
    await w.deactivate()
  }, true, JSON.stringify({ runs: [] }))
})

test('an fwx with no `wave list --json` (it fails) leaves the chip as it was, and garbage is no run', async () => {
  for (const waves of [null, 'garbage']) {
    await withFwx(SESSION, async () => {
      const h = host([WS])
      const w = await mountWorker(main, { host: h })
      const shot = (await w.request('session.get')).snapshot as { activeRun: unknown }
      assert.equal(shot.activeRun, null)
      assert.equal(updates(h).at(-1)!.text, 'atlas · 01-a · executing · ▰▰▰▰▱▱▱▱')
      await w.deactivate()
    }, false, waves)
  }
})
