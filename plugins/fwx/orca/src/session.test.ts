// The chip, the tooltip and the panel's data, from what `fwx session --json` and `fwx phase list --json` print. No host.
import { assert, test } from 'orca/testing'
import { bar, chipText, flowRows, parsePhases, parseSession, parseWaves, snapshot, tooltip } from './session'

const SESSION = {
  project: 'atlas', phase_dir: '/srv/atlas/.fwx/milestones/v1/phases/03-billing', milestone: 'v1', subproject: null,
  stage: 'executing', part: 1, parts: 2, branch: 'fwx/billing', progress: 0.667
}
const PHASES = JSON.stringify({
  milestones: [{ name: 'v1', phases: [
    { name: '01-login', stage: 'closed', open: false, subphases: [] },
    { name: '02-search', stage: 'closed', open: false, subphases: [] },
    { name: '03-billing', stage: 'executing', open: true, subphases: ['03.1-invoices', '03.2-receipts'] }
  ] }]
})
const snap = (s: object = SESSION, p: string = PHASES) => snapshot(parseSession(JSON.stringify(s)), parsePhases(p))

test('the chip is project, phase, stage, then a bar (D155)', () => {
  const v = snap()!
  assert.equal(chipText(v), 'atlas · 03-billing · executing · ▰▰▰▰▰▱▱▱')
})

test('the profile slot shows nothing until there is a profile, then sits after the project', () => {
  const v = snap()!
  assert.equal(v.profile, null)
  assert.equal(chipText({ ...v, profile: 'web' }), 'atlas · web · 03-billing · executing · ▰▰▰▰▰▱▱▱')
})

test('no phase: `<project> · no phase`, and the bar is not drawn', () => {
  const v = snap({ ...SESSION, phase_dir: null, stage: null, part: null, parts: null, branch: null, progress: null })!
  assert.equal(chipText(v), 'atlas · no phase')
  assert.equal(tooltip(v), 'No phase open')
})

test('a folder with no .claude/fwx.json (project null), an fwx without the keys and garbage show nothing', () => {
  assert.equal(snap({ ...SESSION, project: null }), null)
  assert.equal(snapshot(parseSession(JSON.stringify({ phase_dir: null })), parsePhases('')), null)
  assert.equal(snapshot(parseSession('not json'), parsePhases('')), null)
  assert.equal(snapshot(parseSession(''), parsePhases('')), null)
})

test('the bar fills in eighths and stays inside its width', () => {
  assert.deepEqual([0, 0.5, 1, 1.4, -1].map(bar), ['▱▱▱▱▱▱▱▱', '▰▰▰▰▱▱▱▱', '▰▰▰▰▰▰▰▰', '▰▰▰▰▰▰▰▰', '▱▱▱▱▱▱▱▱'])
})

test('the roadmap: phases done, current, next; the parts of the current phase by the part in hand', () => {
  const v = snap()!
  assert.deepEqual(v.phases.map((p) => p.state), ['done', 'done', 'current'])
  assert.deepEqual(v.partList, [{ name: '03.1-invoices', state: 'current' }, { name: '03.2-receipts', state: 'next' }])
  const second = snap({ ...SESSION, part: 2 })!
  assert.deepEqual(second.partList.map((p) => p.state), ['done', 'current'])
  const closed = snap({ ...SESSION, stage: 'closed', part: 2 })!
  assert.deepEqual(closed.partList.map((p) => p.state), ['done', 'done'])
  const open = JSON.parse(PHASES)
  open.milestones[0].phases.push({ name: '04-reports', stage: null, open: true, subphases: [] })
  assert.deepEqual(snap(SESSION, JSON.stringify(open))!.phases.map((p) => p.state), ['done', 'done', 'current', 'next'])
})

test('the tooltip is one line: the milestone, the phases with the current stage, the parts, the branch', () => {
  assert.equal(tooltip(snap()!), 'Milestone v1 · ✓ 01-login · ✓ 02-search · ▶ 03-billing (executing) · Parts ▶1 ○2 · Branch fwx/billing')
})

test('a long milestone is cut to two phases each side of the current one', () => {
  const many = { milestones: [{ name: 'v2', phases: Array.from({ length: 9 }, (_, i) => ({
    name: `0${i + 1}-p`, stage: i < 5 ? 'closed' : null, open: i >= 5, subphases: [] })) }] }
  const v = snap({ ...SESSION, milestone: 'v2', phase_dir: '/x/phases/06-p', stage: null, part: null, parts: null, branch: null }, JSON.stringify(many))!
  assert.equal(tooltip(v), 'Milestone v2 · … · ✓ 04-p · ✓ 05-p · ▶ 06-p · ○ 07-p · ○ 08-p · …')
})

test('without the phase list the chip and the current phase still show', () => {
  const v = snap(SESSION, 'broken')!
  assert.equal(chipText(v), 'atlas · 03-billing · executing · ▰▰▰▰▰▱▱▱')
  assert.deepEqual(v.phases, [])
  assert.equal(tooltip(v), 'Milestone v1 · Branch fwx/billing')
})

// ---- the live workflow: `fwx wave list --json` -----------------------------------------------------------------------------------
const RUN = {
  run: '01-billing-abc1234-1', part: '03.1-invoices', branch: 'fwx/billing', state: 'active', pid: 4242, alive: true, step: 'wave 1', started: 100, orca_run: 'run_1',
  waves: [{ n: 1, tasks: ['T1', 'T2'] }, { n: 2, tasks: ['T3'] }],
  workers: [
    { unit: 'T1', role: 'executor', state: 'running', released: false, line: null },
    { unit: 'T2', role: 'executor', state: 'succeeded', released: true, line: 'done /w/.fwx-agent/T2/report.json commits=1' }
  ],
  events: ['worker T1 started (executor, m)', 'worker T2 done'], result: null
}
const runs = (...r: object[]) => JSON.stringify({ runs: r })
const withRuns = (waves: string, s: object = SESSION) => snapshot(parseSession(JSON.stringify(s)), parsePhases(PHASES), parseWaves(waves))!
const NO_PHASE = { ...SESSION, phase_dir: null, stage: null, part: null, parts: null, branch: null, progress: null }

test('parseWaves reads the runs and never throws on what an older or broken fwx prints', () => {
  assert.equal(parseWaves(runs(RUN)).length, 1)
  assert.equal(parseWaves(runs(RUN))[0].workers[0].unit, 'T1')
  for (const bad of ['', 'not json', 'null', '[]', '{}', '{"runs": 3}', 'usage: fwx wave list\n']) assert.deepEqual(parseWaves(bad), [], bad)
  assert.deepEqual(parseWaves(runs({ nope: 1 }, 'x', null, RUN)).map((r) => r.run), [RUN.run])
  const thin = parseWaves(runs({ run: 'r1' }))[0]
  assert.deepEqual([thin.part, thin.state, thin.alive, thin.waves, thin.workers, thin.events, thin.step], ['', '', false, [], [], [], null])
})

test('the active run is the newest one that is active and alive; a dead or finished run is ignored', () => {
  const older = { ...RUN, run: 'r-old', started: 50, part: 'old-part' }
  assert.equal(withRuns(runs(older, RUN)).activeRun!.run, RUN.run)
  assert.equal(withRuns(runs(RUN, older)).activeRun!.run, RUN.run)
  assert.equal(withRuns(runs({ ...RUN, alive: false })).activeRun, null)
  assert.equal(withRuns(runs({ ...RUN, state: 'done', alive: false })).activeRun, null)
  assert.equal(withRuns(runs({ ...RUN, state: 'needs-owner' })).activeRun, null)
  assert.equal(withRuns('').activeRun, null)
  assert.equal(snap()!.activeRun, null)
})

test('with no live run the chip and the tooltip are what they were', () => {
  for (const v of [snap()!, withRuns(runs({ ...RUN, alive: false })), withRuns('')]) {
    assert.equal(chipText(v), 'atlas · 03-billing · executing · ▰▰▰▰▰▱▱▱')
    assert.equal(tooltip(v), 'Milestone v1 · ✓ 01-login · ✓ 02-search · ▶ 03-billing (executing) · Parts ▶1 ○2 · Branch fwx/billing')
  }
  assert.equal(chipText(withRuns(runs({ ...RUN, alive: false }), NO_PHASE)), 'atlas · no phase')
})

test('a live run is the chip: project, part, step and open workers of the total', () => {
  assert.equal(chipText(withRuns(runs(RUN))), 'atlas · 03.1-invoices · wave 1 (1/2)')
  assert.equal(chipText(withRuns(runs({ ...RUN, step: null, workers: [] }))), 'atlas · 03.1-invoices · running')
  assert.equal(chipText({ ...withRuns(runs(RUN)), profile: 'web' }), 'atlas · web · 03.1-invoices · wave 1 (1/2)')
})

test('a live run shows with no phase bound too, in the chip and the tooltip', () => {
  const v = withRuns(runs(RUN), NO_PHASE)
  assert.equal(v.phase, null)
  assert.equal(chipText(v), 'atlas · 03.1-invoices · wave 1 (1/2)')
  assert.equal(tooltip(v), 'Workflow 03.1-invoices (wave 1)')
})

test('the tooltip leads with the live run, then the roadmap', () => {
  assert.equal(tooltip(withRuns(runs(RUN))),
    'Workflow 03.1-invoices (wave 1) · Milestone v1 · ✓ 01-login · ✓ 02-search · ▶ 03-billing (executing) · Parts ▶1 ○2 · Branch fwx/billing')
  assert.equal(tooltip(withRuns(runs({ ...RUN, step: null }), NO_PHASE)), 'Workflow 03.1-invoices (running)')
})

test('the workflow rows: each planned task by its last worker, then the workers the plan did not name', () => {
  const run = parseWaves(runs({
    ...RUN,
    workers: [
      { unit: 'T1', role: 'executor', state: 'failed', released: true, line: 'failed /w/report.json commits=0' },
      { unit: 'T1', role: 'executor', state: 'running', released: false, line: null },
      { unit: 'T2', role: 'executor', state: 'succeeded', released: true, line: 'done /w/.fwx-agent/T2/report.json commits=1' },
      { unit: 'r1', role: 'reviewer', state: 'succeeded', released: true, line: 'reviewed /w/report.json looked_at=3 findings=0 criteria_no=0 criteria_unproven=0' },
      { unit: 'fix-1', role: 'executor', state: 'failed', released: true, line: null }
    ]
  }))[0]
  assert.deepEqual(flowRows(run), [
    { name: 'Wave 1 · T1', state: 'current', tag: 'executor · running', failed: false },
    { name: 'Wave 1 · T2', state: 'done', tag: 'executor', failed: false },
    { name: 'Wave 2 · T3', state: 'next', tag: '', failed: false },
    { name: 'r1', state: 'done', tag: 'reviewer', failed: false },
    { name: 'fix-1', state: 'next', tag: 'failed', failed: true }
  ])
  assert.deepEqual(withRuns(runs(RUN)).flow, flowRows(parseWaves(runs(RUN))[0]))
  assert.deepEqual(snap()!.flow, [])
})
