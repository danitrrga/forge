// Every agent() call here names its model and its agentType. A call in a comment, agent('x'), is not a call.
const NOTE = "agent('in a string') is not a call either"
const model = 'sonnet'
const first = await agent(`review ${args.target} with ${JSON.stringify({ depth: 1 })}`, { label: 'review', model: 'sonnet', agentType: 'fwx:reviewer' })
const second = await agent('plan it', {
  label: 'plan',
  phase: 'Plan',
  model,
  agentType: 'fwx:planner',
})
const third = await agent(`split by /${'x'}/ then ${await agent('inner', { 'agentType': 'fwx:scout', 'model': 'haiku' })}`, { ...base, model: pick(1), agentType })
