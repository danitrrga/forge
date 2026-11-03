// The first call names a role, the second does not: it reaches the hook as workflow-subagent.
const ok = await agent('review it', { label: 'review', model: 'sonnet', agentType: 'fwx:reviewer' })
const bad = await agent('plan it', { label: 'plan', model: 'opus' })
