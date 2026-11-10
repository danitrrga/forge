// referent: none, a fixture of its own: the smallest script that exercises every hook of tests/workflow_stub.mjs;
// it lives outside workflows/*.js, so the model lint (lib/fwx/lint_models.py) does not glob it, and it passes it anyway
// when named on the command line (python3 lib/fwx/lint_models.py tests/fixtures/workflows/toy.js).
export const meta = {
  name: 'toy',
  description: 'Test fixture: one script, a mode per behaviour of the workflow stub',
  phases: [{ title: 'Draft' }, { title: 'Review' }],
}

const SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' } }, required: ['ok'] }
const call = (label) => agent(`work on ${label}`, { label, model: args.models[label], agentType: 'toy:worker', schema: SCHEMA })
const close = () => agent('close up', { label: 'close', model: args.models.close, agentType: 'toy:worker' })

if (args.mode === 'base') {
  phase('Draft')
  const out = []
  for (const label of args.order) out.push(await call(label))
  phase('Review')
  log('drafted ' + out.length)
  return out
}
if (args.mode === 'throws') { // no finally: the record must still hold the two launches and the error
  await call('a')
  await call('b')
  throw new Error('boom after b')
}
if (args.mode === 'finally') { // the cleanup of 3.5 and 5.2b: runs after the throw
  try {
    await call('a')
    await call('b')
    throw new Error('boom after b')
  } finally {
    await close()
  }
}
if (args.mode === 'retry') { // a null answer once is relaunched once
  let r = await call('a')
  if (r === null) r = await call('a')
  return r
}
if (args.mode === 'parallel') {
  return await parallel([() => call('a'), () => { throw new Error('thunk blew up') }, () => call('c')])
}
if (args.mode === 'pipeline') {
  return await pipeline(['a', 'b'], (item) => call(item), (prev, item, index) => {
    log(`stage2 ${item} ${index} ${prev === null ? 'null' : 'prev'}`)
    if (item === 'b') throw new Error('stage blew up')
    return call('c')
  })
}
if (args.mode === 'nested') return await workflow('child', { x: 1 })
if (args.mode === 'clock') return Date.now()
if (args.mode === 'host') {
  log(`process ${typeof process} require ${typeof require}`)
  return null
}
return `unknown mode ${args.mode}`
