// referent: none, the harness is this repo's own: pstack and marshal test no workflow script; the hook names and
// semantics follow Claude Code's workflow-authoring reference (agent, parallel, pipeline, phase, log, args, workflow, budget).
//
// Run a workflows/*.js with the hooks simulated and record what it launched.
//   node tests/workflow_stub.mjs SCRIPT SCENARIO.json RECORD.json
// Scenario: {"args": ..., "answers": {"<label>": answer}, "workflows": {"<name or scriptPath>": answer}, "budget": {"total": N}}
//   answer: returned as is (null included); {"$seq": [...]} one element per call, an exhausted list is an error;
//   {"$throw": "msg"} the call throws. The label of an agent() is opts.label, else opts.agentType; "*" answers any label
//   without an entry; no entry at all is an error in the record, never a silent null.
//   An answer is checked against opts.schema (type, enum, required, properties, items): one that breaks it is an error,
//   since the real tool returns only validated objects. The schema itself must be {type: 'object', properties} with
//   required inside properties, as the real tool demands.
// Record (rewritten at every launch, so an exception or a kill leaves what ran): launches [{n, label, prompt, opts,
//   phase, start, end, answer: value|null|throw|unanswered|schema}], phases, logs, workflows [{n, ref, args}], swallowed
//   [{where, message}] (what parallel/pipeline turned into null), meta, args, result, error {message, stage}, finished,
//   max_concurrent. start/end are ticks of one counter: two launches overlap when their intervals do.
// Exit 0 whenever the record was written (the script's own failure is in it), 2 on a usage problem.
// Not simulated: the concurrency cap, worktree isolation, one-level nesting of workflow() (a child is an answer, not run).
import { readFileSync, writeFileSync } from 'node:fs'

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)))

const [scriptPath, scenarioPath, recordPath] = process.argv.slice(2)
if (!scriptPath || !scenarioPath || !recordPath) {
  console.error('usage: node workflow_stub.mjs SCRIPT SCENARIO.json RECORD.json')
  process.exit(2)
}
let source, scenario
try {
  source = readFileSync(scriptPath, 'utf8')
  scenario = JSON.parse(readFileSync(scenarioPath, 'utf8'))
} catch (e) {
  console.error('workflow_stub: ' + e.message)
  process.exit(2)
}

const rec = {
  launches: [], phases: [], logs: [], workflows: [], swallowed: [], meta: null,
  args: clone(scenario.args), result: null, error: null, finished: false, max_concurrent: 0,
}
function flush() {
  writeFileSync(recordPath, JSON.stringify(rec, null, 1))
}
const describe = (e, stage = 'run') => ({ message: String((e && e.message) || e), stage })

let tick = 0
let inflight = 0
let currentPhase = null
const used = {}

function unwrap(entry, key) {
  if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
    if ('$throw' in entry) throw new Error(String(entry.$throw))
    if ('$seq' in entry) {
      const i = (used[key] = (used[key] ?? -1) + 1)
      if (i >= entry.$seq.length) throw new Error(`scenario sequence for "${key}" exhausted after ${entry.$seq.length} call(s)`)
      return unwrap(entry.$seq[i], key + '#' + i)
    }
  }
  return entry
}

function lookup(table, key, what) {
  table = table || {}
  if (Object.hasOwn(table, key)) return { value: unwrap(table[key], key) }
  if (Object.hasOwn(table, '*')) return { value: unwrap(table['*'], '*') }
  throw Object.assign(new Error(`scenario has no answer for ${what} "${key}"`), { unanswered: true })
}

function banned(what) {
  /*D*/ throw new Error(`${what} is unavailable in workflow scripts (it would break resume)`)
}

function schemaProblem(schema, v, at) {
  if (schema.type !== undefined) {
    const types = [].concat(schema.type)
    const t = v === null ? 'null' : Array.isArray(v) ? 'array' : Number.isInteger(v) ? 'integer' : typeof v
    const okType = types.some((x) => x === t || (x === 'number' && t === 'integer'))
    if (!okType) return `${at}: ${t}, want ${types.join('|')}`
  }
  if (schema.enum && !schema.enum.some((x) => JSON.stringify(x) === JSON.stringify(v))) return `${at}: ${JSON.stringify(v)} not in enum ${JSON.stringify(schema.enum)}`
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    for (const k of schema.required || []) if (!(k in v)) return `${at}.${k}: missing`
    for (const [k, sub] of Object.entries(schema.properties || {})) if (k in v) { const p = schemaProblem(sub, v[k], `${at}.${k}`); if (p) return p }
  }
  if (Array.isArray(v) && schema.items) for (let i = 0; i < v.length; i++) { const p = schemaProblem(schema.items, v[i], `${at}[${i}]`); if (p) return p }
  return null
}

function rootSchemaProblem(schema) {
  if (schema.type !== 'object' || typeof schema.properties !== 'object') return "schema needs {type: 'object', properties: {...}} at its root"
  for (const k of schema.required || []) if (!(k in schema.properties)) return `schema requires "${k}" which is not in properties`
  return null
}

async function agent(prompt, opts = {}) {
  if (typeof prompt !== 'string') throw new TypeError('agent(prompt, opts): prompt must be a string')
  const key = opts.label ?? opts.agentType ?? ''
  const l = { n: rec.launches.length + 1, label: key, prompt, opts: clone(opts), phase: opts.phase ?? currentPhase, start: ++tick, end: null, answer: null }
  rec.launches.push(l)
  rec.max_concurrent = Math.max(rec.max_concurrent, ++inflight)
  flush()
  try {
    await new Promise((r) => setImmediate(r)) // a real agent takes time: the launches of a parallel() overlap
    if (opts.schema) {
      const bad = rootSchemaProblem(opts.schema)
      if (bad) { l.answer = 'schema'; throw new Error(`agent "${key}": ${bad}`) }
    }
    let value
    try {
      value = lookup(scenario.answers, key, 'agent').value
    } catch (e) {
      l.answer = e.unanswered ? 'unanswered' : 'throw'
      throw e
    }
    if (value !== null && opts.schema) {
      const p = schemaProblem(opts.schema, value, '$')
      if (p) { l.answer = 'schema'; throw new Error(`answer for "${key}" breaks the schema: ${p}`) }
    }
    l.answer = value === null ? 'null' : 'value'
    return value === null ? null : clone(value)
  } finally {
    l.end = ++tick
    inflight--
    flush()
  }
}

async function parallel(thunks) {
  if (!Array.isArray(thunks)) throw new TypeError('parallel(thunks): thunks must be an array of functions')
  return Promise.all(thunks.map(async (t) => {
    try {
      return await t()
    } catch (e) {
      rec.swallowed.push({ where: 'parallel', message: describe(e).message })
      /*P*/ return null
    }
  }))
}

async function pipeline(items, ...stages) {
  return Promise.all(items.map(async (item, index) => {
    let prev = item
    for (const stage of stages) {
      try {
        prev = await stage(prev, item, index)
      } catch (e) {
        rec.swallowed.push({ where: 'pipeline', message: describe(e).message })
        /*L*/ return null
      }
    }
    return prev
  }))
}

function phase(title) {
  currentPhase = String(title)
  rec.phases.push(currentPhase)
}
function log(message) {
  rec.logs.push(String(message))
}
async function workflow(ref, wargs) {
  const key = typeof ref === 'string' ? ref : ref && ref.scriptPath
  rec.workflows.push({ n: rec.workflows.length + 1, ref: clone(ref), args: clone(wargs) })
  flush()
  try {
    return clone(lookup(scenario.workflows, key, 'workflow').value)
  } catch (e) {
    throw e.unanswered ? new Error(`unknown workflow "${key}"`) : e
  }
}
const total = scenario.budget?.total ?? null
const budget = { total, spent: () => 0, remaining: () => (total === null ? Infinity : total) }

const RealDate = Date
class NoClockDate extends RealDate {
  constructor(...a) {
    if (a.length === 0) banned('new Date() without arguments')
    super(...a)
  }
  static now() { banned('Date.now()') }
}

let body = null
try {
  if (!/^\s*export\s+const\s+meta\s*=/m.test(source)) throw new Error('the script has no `export const meta = {...}`')
  const text = source.replace(/^(\s*)export\s+const\s+meta\s*=/m, '$1const meta = globalThis.__fwx_meta =')
  // process, require and module are shadowed: a workflow script has no Node API
  body = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'workflow', 'budget',
    'process', 'require', 'module', text)
} catch (e) {
  rec.error = describe(e, 'compile')
}

if (body) {
  const realRandom = Math.random
  globalThis.Date = NoClockDate
  Math.random = () => banned('Math.random()')
  try {
    rec.result = clone(await body(agent, parallel, pipeline, phase, log, clone(scenario.args), workflow, budget,
      undefined, undefined, undefined)) ?? null
  } catch (e) {
    rec.error = describe(e)
  } finally {
    globalThis.Date = RealDate
    Math.random = realRandom
    rec.meta = clone(globalThis.__fwx_meta) ?? null
  }
}
rec.finished = true
flush()
