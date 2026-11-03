// Every agent() call here names its model. A call in a comment, agent('x'), is not a call.
const NOTE = "agent('in a string') is not a call either"
const model = 'sonnet'
const first = await agent(`review ${args.target} with ${JSON.stringify({ depth: 1 })}`, { label: 'review', model: 'sonnet' })
const second = await agent('plan it', {
  label: 'plan',
  phase: 'Plan',
  model,
})
const third = await agent(`split by /${'x'}/ then ${await agent('inner', { 'model': 'haiku' })}`, { ...base, model: pick(1) })
