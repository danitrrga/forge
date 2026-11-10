// An agent() call whose options name no model.
const x = 'b'
const r = await agent(`review ${x} with ${JSON.stringify({ a: 1 })}`, { label: 'a' })
