// The chip, the tooltip and the panel's data, from what `fwx session --json` and `fwx phase list --json` print. No host.
import { assert, test } from 'orca/testing'
import { bar, chipText, parsePhases, parseSession, snapshot, tooltip } from './session'

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

test('the chip is project, then a bar, with no stage word', () => {
  const v = snap()!
  assert.equal(chipText(v), 'atlas · ▰▰▰▰▰▱▱▱')
})

test('the profile slot shows nothing until there is a profile, then sits after the project', () => {
  const v = snap()!
  assert.equal(v.profile, null)
  assert.equal(chipText({ ...v, profile: 'web' }), 'atlas · web · ▰▰▰▰▰▱▱▱')
})

test('no phase: `<project> · sin fase`, and the bar is not drawn', () => {
  const v = snap({ ...SESSION, phase_dir: null, stage: null, part: null, parts: null, branch: null, progress: null })!
  assert.equal(chipText(v), 'atlas · sin fase')
  assert.equal(tooltip(v), 'Sin fase abierta')
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
  assert.equal(tooltip(snap()!), 'Hito v1 · ✓ 01-login · ✓ 02-search · ▶ 03-billing (executing) · Partes ▶1 ○2 · Rama fwx/billing')
})

test('a long milestone is cut to two phases each side of the current one', () => {
  const many = { milestones: [{ name: 'v2', phases: Array.from({ length: 9 }, (_, i) => ({
    name: `0${i + 1}-p`, stage: i < 5 ? 'closed' : null, open: i >= 5, subphases: [] })) }] }
  const v = snap({ ...SESSION, milestone: 'v2', phase_dir: '/x/phases/06-p', stage: null, part: null, parts: null, branch: null }, JSON.stringify(many))!
  assert.equal(tooltip(v), 'Hito v2 · … · ✓ 04-p · ✓ 05-p · ▶ 06-p · ○ 07-p · ○ 08-p · …')
})

test('without the phase list the chip and the current phase still show', () => {
  const v = snap(SESSION, 'broken')!
  assert.equal(chipText(v), 'atlas · ▰▰▰▰▰▱▱▱')
  assert.deepEqual(v.phases, [])
  assert.equal(tooltip(v), 'Hito v1 · Rama fwx/billing')
})
